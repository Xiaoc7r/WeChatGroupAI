"""One worker, one sender, up to three isolated group contexts."""
import json
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from concurrent.futures import Future
from core import Store, PollWindow, normalize, trigger, ask, PREFIX
from features import prepare, schedule_due, daily_status

VERSION = '4.1'
SEND_INTERVAL = 20
MEMBER_INTERVAL = 60
MAX_PENDING = 8

class SessionPaused(RuntimeError):
    pass

class SendUnconfirmed(RuntimeError):
    pass

def group_settings(config):
    groups = config.get('groups')
    if groups is None:
        groups = [{'group': config.get('group',''), 'nickname': config.get('nickname','')}]
    if not isinstance(groups,list) or not 1 <= len(groups) <= 3:
        raise ValueError('请选择 1～3 个群。')
    result=[]
    for item in groups:
        name=str(item.get('group','')).strip()
        nick=str(item.get('nickname','')).strip()
        if not name or not nick:
            raise ValueError('每个启用群都要填写完整群名和本微信号的群昵称。')
        if name in [g['group'] for g in result]:
            raise ValueError('群名称不能重复。')
        result.append({'group':name,'nickname':nick})
    return result

@dataclass
class Room:
    room: str
    config: dict
    names: dict
    members: dict
    poller: PollWindow
    last_poll: float
    count: int = 0
    failures: int = 0

@dataclass
class Job:
    room: Room
    key: str
    prompt: str = ''
    sender: str = ''
    send: bool | None = None
    style: str = ''
    ready: float = 0
    until: float | None = None
    created: float = 0

class Engine:
    def __init__(self, app, config, db, gui, store, executor, pause_path,
                 clock=time.time, sleep=time.sleep):
        self.app,self.cfg,self.db,self.gui,self.store,self.executor=app,config,db,gui,store,executor
        self.pause_path,self.clock,self.sleep=pause_path,clock,sleep
        self.rooms=[];self.pending=deque();self.active=None
        self.member_times=OrderedDict();self.cursor=0;self.unconfirmed=0
        self.fault=False;self.started=clock();self.last_health=0;self.last_prune=0
        self.last_status=None;self.last_schedule=None
        self.own=db.get_self_info()['username']
        store.db.execute('CREATE TABLE IF NOT EXISTS send_budget (account TEXT PRIMARY KEY, attempted REAL)')
        row=store.db.execute('SELECT attempted FROM send_budget WHERE account=?',(self.own,)).fetchone()
        self.last_send=row[0] if row else -1e12

    def emit(self,text):self.app.emit(text)
    def event(self,kind,text):self.app.events.put((kind,text))
    def state(self,job,state):self.store.state(self.own,job.room.room,job.key,state)
    def check_session(self):self.gui.check_session()

    def pause(self,reason):
        self.fault=True
        temporary=self.pause_path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'reason':reason,'time':self.clock()},ensure_ascii=False),encoding='utf-8')
        temporary.replace(self.pause_path)
        self.event('notice','已暂停：'+reason+'；手动处理微信后重新启动。')
        raise SessionPaused(reason)

    def initialize(self):
        self.check_session()
        if self.pause_path.exists():
            if not self.cfg.get('resume_confirmed'):
                raise SessionPaused('上次异常已暂停，请确认微信登录正常后手动重新启动。')
            self.pause_path.unlink()
        names=self.db.nickname_map()
        # Validate all destinations before enabling the worker.
        for settings in group_settings(self.cfg):
            matches=[uid for uid,name in names.items() if name==settings['group']]
            if len(matches)!=1 or not matches[0].endswith('@chatroom'):
                raise ValueError('群未唯一匹配（包括同名联系人）：'+settings['group'])
            room=matches[0];mapping=dict(names);members={self.own:settings['nickname']}
            for member in self.db.get_group_members(room):
                uid=member['username'];nick=member.get('nick_name') or uid
                mapping[uid]=nick;members[uid]=nick
            rows=self.db.get_messages(room,limit=500)
            messages=[normalize(row,mapping) for row in reversed(rows)]
            self.store.add_many(self.own,room,messages)
            for msg in messages:
                if msg['sender']:members.setdefault(msg['sender'],msg['name'])
            poller=PollWindow(rows);poller.last_full=self.clock()
            self.rooms.append(Room(room,{**self.cfg,**settings},mapping,members,poller,self.clock()))
        self.started=self.clock()
        self.app.ready=True
        self.emit(f'已连接 {len(self.rooms)} 个群；上下文分别保存，发送共用队列。')

    def enqueue(self,job):
        if not self.store.claim(self.own,job.room.room,job.key):return False
        busy = list(self.pending)
        if self.active:busy.append(self.active[1])
        member_key=(job.room.room,job.sender)
        if job.sender and (any(j.room.room==job.room.room and j.sender==job.sender for j in busy)
                           or self.clock()-self.member_times.get(member_key,-1e12)<MEMBER_INTERVAL):
            self.state(job,'sender_busy');return False
        if len(busy)>=MAX_PENDING or sum(j.room.room==job.room.room for j in busy)>=4:
            self.state(job,'queue_full');return False
        if job.sender:
            self.member_times[member_key]=self.clock();self.member_times.move_to_end(member_key)
            while len(self.member_times)>4096:self.member_times.popitem(last=False)
        self.pending.append(job)
        return True

    def poll_one(self):
        room=self.rooms[self.cursor];self.cursor=(self.cursor+1)%len(self.rooms)
        try:
            scanned,rows=room.poller.fetch(self.db,room.room,self.clock())
            messages=[normalize(row,room.names) for row in reversed(rows)]
            inserted=self.store.add_many(self.own,room.room,[m for m in messages if not m['ts'] or m['ts']>=self.clock()-7*86400])
            room.poller.remember(scanned);room.last_poll=self.clock();room.failures=0
            if room.poller.saturated:self.emit(room.config['group']+'：补读窗口已满，可能缺少更早消息。')
            for msg in inserted:
                room.count+=1
                if msg['sender']:room.members.setdefault(msg['sender'],msg['name'])
                if msg['ts']<self.started or msg['kind'] not in ('文本','text'):continue
                prompt=trigger(msg['text'],room.config['nickname'],is_self=msg['sender']==self.own)
                if prompt:
                    wait=int(self.cfg.get('context_wait',3))
                    self.enqueue(Job(room,msg['key'],prompt,msg['sender'],style=self.cfg['style'],
                                     ready=self.clock()+wait,until=msg['ts']+wait,created=self.clock()))
        except SessionPaused:raise
        except Exception as e:
            room.failures+=1
            self.emit(room.config['group']+'：采集异常 '+str(e)[:250])
            if room.failures>=3:self.pause('同一群连续三次采集失败，请检查微信登录。')

    def collect_commands(self):
        while not self.app.commands.empty():
            target,prompt,send,style=self.app.commands.get_nowait()
            room=next((r for r in self.rooms if r.config['group']==target),None)
            if room is None:
                self.emit('手动请求的群不在运行配置中，已取消。');continue
            self.enqueue(Job(room,'manual-'+uuid.uuid4().hex,prompt,send=send,style=style,created=self.clock()))
        for room in self.rooms:
            due=schedule_due(room.config,self.clock())
            # Do not claim a daily job unless there is queue capacity.
            if due and len(self.pending)+(1 if self.active else 0)<MAX_PENDING:
                self.enqueue(Job(room,due[0],'/morning',style=self.cfg['style'],until=due[1],created=self.clock()))

    def send(self,room,text):
        try:self.check_session()
        except SessionPaused:self.pause('微信会话已变化或要求验证，请手动检查。')
        fresh=self.db.nickname_map(refresh=True)
        if [uid for uid,name in fresh.items() if name==room.config['group']] != [room.room]:
            self.pause('目标群名变动或出现同名联系人，已停止发送。')
        self.last_send=self.clock()
        with self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO send_budget VALUES (?,?)',(self.own,self.last_send))
        result=self.gui.send_msg(text,who=room.config['group'],verify=True)
        if not result:
            reason=result.get('message','发送未确认') if hasattr(result,'get') else '发送未确认'
            if '消息已操作发送，但数据库未确认' in str(reason):
                self.unconfirmed+=1
                if self.unconfirmed>=3:self.pause('连续三次发送未获数据库确认，停止自动操作以避免重复。')
                raise SendUnconfirmed('已操作发送但数据库未确认；请查看群消息，不自动重发。')
            self.pause('发送失败，微信可能未登录、需验证或桌面不可操作。')
        self.unconfirmed=0

    def process(self):
        now=self.clock()
        if self.active and self.active[0].done():
            future,job=self.active
            actual=job.send if job.send is not None else not self.app.runtime_preview
            if actual and now-self.last_send<SEND_INTERVAL:return
            self.active=None
            text=None
            try:
                text,count=future.result()
                if self.app.stop.is_set():self.state(job,'cancelled');return
                if actual:
                    self.send(job.room,text)
                    self.state(job,'sent')
                else:self.state(job,'preview')
                label='已发送' if actual else '仅预览，未发送'
                self.event('answer',f'{job.room.config["group"]} · {label} · 参考 {count} 条\n\n{text}')
            except SessionPaused:
                self.state(job,'failed')
                if text:self.event('answer','自动操作已暂停，先确认群里是否收到。\n\n'+text)
                raise
            except Exception as e:
                self.state(job,'unconfirmed' if isinstance(e,SendUnconfirmed) else 'failed')
                self.event('answer',job.room.config['group']+'：'+str(e).replace(self.cfg['api_key'],'[Key]')[:350]+('\n\n已生成的回答：\n'+text if text else ''))
            return
        if self.active or not self.pending:return
        # Rotate not-yet-ready jobs so a busy group cannot block another group.
        for _ in range(len(self.pending)):
            job=self.pending.popleft()
            if now-job.created>300:
                self.state(job,'expired');continue
            if now<job.ready or (job.ready and job.room.last_poll<job.ready):
                self.pending.append(job);continue
            reference=job.until if job.key.startswith('daily:') else now
            direct,prompt,context=prepare(self.store,self.own,job.room.room,job.key,job.prompt,
                {**job.room.config,'preview':self.app.runtime_preview},reference,job.room.members,job.sender or self.own,job.until)
            if direct is not None:
                future=Future();future.set_result((direct,len(context)))
            else:future=self.executor.submit(ask,{**job.room.config,'style':job.style},prompt,context)
            self.active=(future,job)
            return

    def tick(self):
        if self.clock()-self.last_health>=30:
            self.check_session();self.last_health=self.clock()
        self.poll_one();self.collect_commands();self.process()
        if self.clock()-self.last_prune>3600:self.store.prune();self.last_prune=self.clock()
        status=f'运行中 · {len(self.rooms)} 个群 · '+('只预览' if self.app.runtime_preview else '自动回复')+f' · 排队 {len(self.pending)}'+(' · 正在处理回答' if self.active else '')
        schedule='\n'.join(r.config['group']+'：'+daily_status(self.store,self.own,r.room,r.config,self.clock()) for r in self.rooms)
        if status!=self.last_status:self.event('status',status);self.last_status=status
        if schedule!=self.last_schedule:self.event('schedule',schedule);self.last_schedule=schedule

    def close(self,normal=False):
        # Lifecycle transitions are local-only: never send or wait for a send slot.
        if self.active:self.state(self.active[1],'cancelled')
        for job in self.pending:self.state(job,'cancelled')
        self.pending.clear()
        self.active=None


def make_gui():
    """Do not auto-login or fall back to clicking an unrecognized window."""
    from wechatauto.guia import WeChatGUI
    from wechatauto.uia_driver import WeChatUIA

    class ManualLoginUIA(WeChatUIA):
        def _auto_login(self):
            raise SessionPaused('微信要求登录或验证，请在官方客户端手动完成。')
        def _wait_main(self,*args,**kwargs):
            main=self._find_main()
            if main is None:raise SessionPaused('微信主窗口未就绪，请检查登录或验证提示。')
            self._win=main
            return main
        def ensure_window(self,*args,**kwargs):
            if self._login_window() is not None:raise SessionPaused('微信已退出登录或要求验证。')
            return super().ensure_window(*args,**kwargs)
        def wake(self):
            raise SessionPaused('微信未运行，请手动登录；不会自动重启或点击登录。')

    class GuardedGUI(WeChatGUI):
        def _get_uia(self,refresh=False):
            engine=getattr(self,'_manual_uia',None)
            if engine is None:
                engine=ManualLoginUIA();self._manual_uia=engine
            if engine._login_window() is not None:raise SessionPaused('微信已退出登录或要求验证。')
            if not engine.ensure_window():raise SessionPaused('无法确认微信主窗口，不再尝试坐标点击。')
            self._uia=engine
            return engine
        def check_session(self):
            engine=getattr(self,'_manual_uia',None)
            if engine is None:self._get_uia();return
            if engine._login_window() is not None:raise SessionPaused('微信已退出登录或要求验证。')
            if not engine.is_materialized():raise SessionPaused('微信窗口或登录状态已变化，请手动检查。')
    return GuardedGUI()
