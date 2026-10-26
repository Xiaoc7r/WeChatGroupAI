"""V3 commands and scheduler. Pure routing; no WeChat I/O or API calls here."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from core import PREFIX, BEIJING

def problem_hint(error):
    text=str(error).lower()
    if 'win32ui' in text or 'dll load failed' in text:
        return '缺少Windows运行组件：关闭助手，运行配套DLL修复文件，再重新打开。不要改Key或群名。'
    if '401' in text:
        return 'API Key未通过验证：检查Key是否完整、是否属于DeepSeek，改好后重新启动。'
    if '402' in text or '余额不足' in text:
        return '请检查DeepSeek账户余额和模型权限，再点击“测试API”。'
    if '429' in text:
        return '模型服务暂时限流：稍等后重新提问，不要连续点击发送。'
    if 'timeout' in text or 'timed out' in text or '连接' in text and '失败' in text:
        return '连接或生成超时：检查网络后重试。如果涉及发送，先看群里是否收到，避免重复。'
    if '发送' in text or '桌面' in text:
        return '先重新连接服务器，检查微信登录和目标群。确认未收到后再试；离开服务器使用专用断开文件。'
    if '账号' in text:
        return '到“连接设置”检查账号目录，按日志列出的目录选择当前微信号。'
    if '群' in text:
        return '先在微信打开目标群，再核对完整群名；同名群或同名联系人需区分后重新启动。'
    return '查看下面的具体错误；可用“复制当前回答/报错”提供排查信息，不必先重装。'

MENU = """功能菜单（@我后输入）
/help 或 /all：查看菜单
/today：总结最近一个完整日周期
/status：运行状态
/member @昵称：总结该成员发言
/morning：早安与日总结
/eat：吃什么（尚未统计）
也可直接提问；当前微信号可发送 /ai 问题。
日周期按设置时间分界，默认昨天09:00至今天09:00；最多500条已采集记录。"""

@dataclass
class Plan:
    prompt: str = ''
    reply: str = ''
    since: int = 0
    until: int | None = None
    sender: str | None = None
    limit: int = 500
    page: int = 1
    keyword: str = ''

def daily_status(store, account, room, config, now):
    if not config.get('daily_enabled'):
        return '每日早安：已关闭'
    current=datetime.fromtimestamp(now,BEIJING)
    key='daily:'+current.date().isoformat()
    state=store.request_state(account,room,key)
    label={'claimed':'已排队/处理中','sent':'已发送','preview':'已预览，未发送','failed':'失败，请先检查群记录',
           'cancelled':'已停止取消，当天不自动重发'}.get(state,state)
    if label:
        return f'今日早安：{label}；下次明天 {config["daily_time"]}（北京时间）'
    hour,minute=map(int,config.get('daily_time','09:00').split(':'))
    due=current.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if current<due:
        return f'今日早安：等待 {config["daily_time"]}（北京时间）'
    if (current-due).total_seconds()<300:
        return '今日早安：等待排队（5分钟补发窗口内）'
    return f'今日早安：已错过，不补发；下次明天 {config["daily_time"]}（北京时间）'

def day_start(now):
    return datetime.fromtimestamp(now, BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)

def schedule_due(config, now):
    """5-minute catch-up window; persistent claim is performed by the caller."""
    if not config.get('daily_enabled', False):
        return None
    current = datetime.fromtimestamp(now, BEIJING)
    hour, minute = map(int, config.get('daily_time', '09:00').split(':'))
    due = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if 0 <= (current - due).total_seconds() < 300:
        return 'daily:' + due.date().isoformat(), due.timestamp()
    return None

def resolve_member(argument, members, requester, numbers=None):
    numbers=numbers if numbers is not None else {uid:i+1 for i,uid in enumerate(sorted(members))}
    name = argument.strip().lstrip('@').strip()
    if name in ('', '我', '自己', 'me'):
        if requester and requester in members:
            return requester, ''
        return None, '无法确定你指的是谁，请输入完整群昵称或成员编号。'
    if re.fullmatch(r'#\d+', name):
        for uid, number in numbers.items():
            if number == int(name[1:]):
                return uid, ''
        return None, '该编号不在当前成员名单中，请填写完整群昵称。'
    hits = [uid for uid, display in members.items() if display == name]
    if len(hits) == 1:
        return hits[0], ''
    if len(hits) > 1:
        choices = '、'.join('#' + str(numbers[uid]) for uid in hits)
        return None, f'存在同名成员「{name}」：{choices}。请用 /member #编号。'
    return None, f'未找到完整昵称「{name}」。请检查该成员的完整群昵称。'

def summary_window(now, daily_time='09:00'):
    """Most recent completed Beijing daily interval, inclusive start/exclusive end."""
    hour, minute = map(int, daily_time.split(':'))
    current = datetime.fromtimestamp(now, BEIJING)
    end = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current < end:
        end -= timedelta(days=1)
    return end-timedelta(days=1), end

def route(prompt, now, members, requester=None, numbers=None, daily_time='09:00'):
    parts = prompt.strip().split(maxsplit=1)
    command = parts[0].lower() if parts else '/help'
    arg = parts[1].strip() if len(parts)>1 else ''
    if command in ('/all', '/help'):
        return Plan(reply=MENU)
    if command == '/eat':
        return Plan(reply='尚未统计')
    if command == '/status':
        return Plan(reply='/status')
    if command in ('/today', '/morning'):
        start, end = summary_window(now, daily_time)
        period = f'{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}（北京时间，结束时刻不包含）'
        task = ('先自然地向全群说早安，再' if command == '/morning' else '')
        task += '总结这段时间内提供的聊天：主要话题、明确结论和待办。时间范围：'+period+'。说明时间范围，只依据已采集记录；不编造天气、新闻或日程。最多300字。'+arg
        return Plan(prompt=task, since=int(start.timestamp()), until=int(end.timestamp())-1)
    if command == '/member':
        uid, error = resolve_member(arg, members, requester, numbers)
        if error:
            return Plan(reply=error)
        return Plan(prompt=f'总结成员「{members[uid]}」的这些发言，只陈述发言内容，不推断现实身份、敏感特征或动机。', sender=uid)
    if command.startswith('/'):
        return Plan(reply='未知命令。输入 /help 查看菜单。')
    return Plan(prompt=prompt)

def prepare(store, account, room, key, prompt, config, now, members, requester=None, until=None):
    # Only member queries need a persistent member-number lookup.
    parts = prompt.strip().split(maxsplit=1)
    command = parts[0].lower() if parts else ''
    numbers = store.member_numbers(account,room,members) if command == '/member' else None
    plan = route(prompt, now, members, requester, numbers, config.get('daily_time','09:00'))
    if plan.reply == '/status':
        return PREFIX+'助手 v3.5.1 · 当前群服务中\n模式：'+('只预览' if config.get('preview') else '自动回复')+'\n'+daily_status(store,account,room,config,now), '', []
    if plan.reply:
        return PREFIX+plan.reply, '', []
    end = min(x for x in (plan.until, until, now) if x is not None)
    records = store.recent(account,room,key,since=plan.since,until=end,sender=plan.sender,limit=plan.limit)
    records = [m for m in records if not m['text'].startswith(PREFIX)]
    command = prompt.strip().split(maxsplit=1)[0].lower() if prompt.strip() else ''
    if not records and (plan.sender or command in ('/today','/morning')):
        period = ''
        if command in ('/today','/morning'):
            start, finish = summary_window(now, config.get('daily_time','09:00'))
            period = f'{start:%m-%d %H:%M} 至 {finish:%m-%d %H:%M}（北京时间）：'
        return PREFIX+('早安！' if command == '/morning' else '')+period+'没有已采集的可用消息，暂时无法总结。', '', []
    return None, plan.prompt, records
