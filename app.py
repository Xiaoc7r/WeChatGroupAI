import os
import sys
import json
import base64
import queue
import threading
import time
import ctypes
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import win32crypt
from core import Store, normalize, trigger, ask, PREFIX, PollWindow
from features import problem_hint, MENU
from engine import Engine, group_settings, make_gui, SendUnconfirmed, SessionPaused

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
CONFIG = DATA / 'config.json'

def save_config(cfg):
    data = dict(cfg)
    data['api_key'] = base64.b64encode(win32crypt.CryptProtectData(cfg['api_key'].encode(), 'WeChatGroupAI', None, None, None, 0)).decode()
    temporary=CONFIG.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temporary,CONFIG)

def load_config():
    if not CONFIG.exists():
        return {}
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    data['api_key'] = win32crypt.CryptUnprotectData(base64.b64decode(data['api_key']), None, None, None, 0)[1].decode()
    return data

class App:
    def __init__(self, root):
        self.root, self.events = root, queue.Queue()
        self.stop = threading.Event()
        self.thread = None
        self.commands = queue.Queue()
        self.ready = False
        self.closing = False
        self.active_group = None
        self.active_groups = []
        root.title('微信群 AI v4.1 · 最多 3 个群')
        root.geometry('920x820')
        root.minsize(700,600)
        root.option_add('*Font', ('Microsoft YaHei UI',10))
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
        dashboard=ttk.Frame(root,padding=(16,12))
        dashboard.pack(side='top',fill='x')
        ttk.Label(dashboard,text='微信群 AI 助手',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        self.status=tk.StringVar(value='异常暂停（需手动恢复）' if (DATA/'safety-pause.json').exists() else '未启动')
        self.status_label=ttk.Label(dashboard,textvariable=self.status,wraplength=850,font=('Microsoft YaHei UI',13,'bold'))
        self.status_label.pack(anchor='w',pady=4)
        def color_status(*_):
            text=self.status.get()
            color='#23703b' if text.startswith('运行中') else '#a32b24' if text.startswith('异常') else '#1f5b99' if text.startswith('启动中') else '#995b00' if text.startswith('停止中') else '#555555'
            self.status_label.configure(foreground=color)
        self.status.trace_add('write',color_status)
        color_status()
        self.guide=tk.StringVar(value='登录微信后，保存并启动。')
        ttk.Label(dashboard,textvariable=self.guide,wraplength=850,foreground='#1f5b99').pack(anchor='w')
        self.pending_tip=tk.StringVar(value='')
        pending_label=ttk.Label(dashboard,textvariable=self.pending_tip,wraplength=850,foreground='#9b5400')
        self.notice=tk.StringVar(value='')
        notice_label=ttk.Label(dashboard,textvariable=self.notice,wraplength=850,foreground='#9b5400')
        controls=ttk.Frame(dashboard)
        controls.pack(fill='x',pady=6)
        for value,label in ((self.pending_tip,pending_label),(self.notice,notice_label)):
            def show_notice(*_,v=value,w=label):
                if v.get():w.pack(anchor='w',before=controls)
                else:w.pack_forget()
            value.trace_add('write',show_notice)
        self.start_btn=ttk.Button(controls,text='保存并启动',command=self.start)
        self.start_btn.pack(side='left')
        ttk.Button(controls,text='停止机器人',command=self.halt).pack(side='left',padx=6)
        ttk.Button(controls,text='怎样离开服务器？',command=lambda:messagebox.showinfo('保持群回复','不要关闭微信或助手。\n在服务器桌面右键“断开专用文件”→以管理员身份运行，让远程连接自动断开。\n普通关闭远程窗口可能使自动发送失效。服务器重启后仍需重新登录启动。')).pack(side='right')
        self.schedule_status=tk.StringVar(value='每日任务：启动后显示执行状态')
        ttk.Label(dashboard,textvariable=self.schedule_status,wraplength=850).pack(anchor='w')
        self.pages=ttk.Notebook(root)
        self.pages.pack(fill='both',expand=True,padx=12,pady=(0,12))
        setup_page=ttk.Frame(self.pages)
        self.use_page=ttk.Frame(self.pages,padding=12)
        self.pages.add(setup_page,text='① 连接设置')
        self.pages.add(self.use_page,text='② 试用与回答')
        use_canvas=tk.Canvas(self.use_page,highlightthickness=0)
        use_scroll=ttk.Scrollbar(self.use_page,orient='vertical',command=use_canvas.yview)
        use_scroll.pack(side='right',fill='y')
        use_canvas.pack(side='left',fill='both',expand=True)
        use_canvas.configure(yscrollcommand=use_scroll.set)
        use_content=ttk.Frame(use_canvas)
        use_id=use_canvas.create_window((0,0),window=use_content,anchor='nw')
        use_content.bind('<Configure>',lambda e:use_canvas.configure(scrollregion=use_canvas.bbox('all')))
        use_canvas.bind('<Configure>',lambda e:use_canvas.itemconfigure(use_id,width=e.width))
        canvas=tk.Canvas(setup_page,highlightthickness=0)
        scroll=ttk.Scrollbar(setup_page,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        frame = ttk.Frame(canvas,padding=20)
        frame_id=canvas.create_window((0,0),window=frame,anchor='nw')
        frame.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(frame_id,width=e.width))
        ttk.Label(frame,text='运行状态见页面顶部；启动、停止均不发群通知。',wraplength=700).pack(anchor='w',pady=(8,12))
        form = ttk.Frame(frame)
        form.pack(fill='x')
        self.vars = {}
        fields = [('api_key','DeepSeek API Key',''),('model','模型名称','deepseek-flash'),('account','微信号目录（可选）',''),('style','回答风格（可修改）','简洁自然，像群友说话，先说重点，不写官话。')]
        for i,(key,label,default) in enumerate(fields):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky='w',pady=5)
            var = tk.StringVar(value=cfg.get(key,default))
            self.vars[key]=var
            ttk.Entry(form,textvariable=var,show='*' if key=='api_key' else '').grid(row=i,column=1,sticky='ew',padx=(12,0))
        form.columnconfigure(1,weight=1)
        ttk.Button(form,text='多行编辑风格',command=self.edit_style).grid(row=3,column=2,padx=5)
        groups_frame=ttk.LabelFrame(frame,text='服务群（最多 3 个）',padding=8)
        groups_frame.pack(fill='x',pady=8)
        for column,text in enumerate(('启用','完整群名','本微信号在该群的昵称')):
            ttk.Label(groups_frame,text=text).grid(row=0,column=column,sticky='w',padx=4)
        saved_groups=cfg.get('groups') or [{'group':cfg.get('group',''),'nickname':cfg.get('nickname','')}]
        self.group_vars=[]
        for index in range(3):
            old=saved_groups[index] if index<len(saved_groups) else {}
            enabled=tk.BooleanVar(value=index<len(saved_groups))
            group=tk.StringVar(value=old.get('group',''))
            nickname=tk.StringVar(value=old.get('nickname',''))
            name_entry=ttk.Entry(groups_frame,textvariable=group)
            nick_entry=ttk.Entry(groups_frame,textvariable=nickname)
            def toggle(e=enabled,widgets=(name_entry,nick_entry)):
                for widget in widgets:widget.configure(state='normal' if e.get() else 'disabled')
            ttk.Checkbutton(groups_frame,variable=enabled,command=toggle).grid(row=index+1,column=0,sticky='w')
            name_entry.grid(row=index+1,column=1,sticky='ew',padx=4,pady=3)
            nick_entry.grid(row=index+1,column=2,sticky='ew',padx=4,pady=3)
            toggle()
            self.group_vars.append({'enabled':enabled,'group':group,'nickname':nickname})
        groups_frame.columnconfigure(1,weight=1);groups_frame.columnconfigure(2,weight=1)
        self.vars['group']=self.group_vars[0]['group']
        self.vars['nickname']=self.group_vars[0]['nickname']
        options=ttk.Frame(frame)
        options.pack(fill='x',pady=6)
        self.daily=tk.BooleanVar(value=cfg.get('daily_enabled',True))
        ttk.Checkbutton(options,text='每日早安总结（北京时间）',variable=self.daily).pack(side='left')
        self.daily_time=tk.StringVar(value=cfg.get('daily_time','09:00'))
        hour, minute = cfg.get('daily_time','09:00').split(':')
        self.daily_hour=tk.StringVar(value=hour)
        self.daily_minute=tk.StringVar(value=minute)
        ttk.Combobox(options,textvariable=self.daily_hour,values=[f'{n:02d}' for n in range(24)],width=3,state='readonly').pack(side='left',padx=(4,0))
        ttk.Label(options,text='时').pack(side='left')
        ttk.Combobox(options,textvariable=self.daily_minute,values=[f'{n:02d}' for n in range(60)],width=3,state='readonly').pack(side='left')
        ttk.Label(options,text='分').pack(side='left')
        for var in (self.daily_hour,self.daily_minute):
            var.trace_add('write',lambda *_:self.daily_time.set(self.daily_hour.get()+':'+self.daily_minute.get()))
        self.period_tip=tk.StringVar()
        self.daily_time.trace_add('write',self.update_period_tip)
        self.update_period_tip()
        ttk.Label(frame,textvariable=self.period_tip).pack(anchor='w',pady=4)
        ttk.Label(options,text='@后等待秒数').pack(side='left',padx=(14,0))
        self.context_wait=tk.StringVar(value=str(cfg.get('context_wait',3)))
        ttk.Spinbox(options,from_=0,to=15,textvariable=self.context_wait,width=4).pack(side='left',padx=4)
        ttk.Button(options,text='功能说明',command=lambda:messagebox.showinfo('v3 功能',MENU+'\n\n每日任务仅在程序运行时执行；错过超过5分钟不补发。预览模式下每日任务也只预览。')).pack(side='right')
        ttk.Label(frame,text='微信号目录可留空，多个账号时需指定。',wraplength=700).pack(anchor='w',pady=(8,0))
        self.preview=tk.BooleanVar(value=cfg.get('preview',True))
        self.runtime_preview = self.preview.get()
        mode=ttk.LabelFrame(use_content,text='回复方式（切换立即生效）',padding=8)
        mode.pack(fill='x',pady=(0,8))
        ttk.Radiobutton(mode,text='试用：自动触发只预览，不发群',variable=self.preview,value=True,command=self.change_preview).pack(anchor='w')
        ttk.Radiobutton(mode,text='正式使用：群友 @ 和每日总结自动发群',variable=self.preview,value=False,command=self.change_preview).pack(anchor='w')
        buttons=ttk.Frame(frame)
        buttons.pack(fill='x')
        self.api_btn=ttk.Button(buttons,text='测试 API',command=self.test_api)
        self.api_btn.pack(side='left')
        self.api_result=tk.StringVar(value='未测试')
        ttk.Label(frame,textvariable=self.api_result,wraplength=700).pack(anchor='w',pady=4)
        ttk.Button(buttons,text='打开数据目录',command=lambda:os.startfile(DATA)).pack(side='right')
        manual=ttk.LabelFrame(use_content,text='自己试一下 · 不用群友配合',padding=8)
        manual.pack(fill='x',pady=(10,0))
        self.test_group=tk.StringVar(value=cfg.get('group',''))
        ttk.Label(manual,text='测试目标群').pack(anchor='w')
        self.group_selector=ttk.Combobox(manual,textvariable=self.test_group,state='readonly')
        self.group_selector.pack(fill='x',pady=(0,6))
        self.test_prompt=tk.StringVar(value='总结最近的群聊：大家聊了什么，有什么结论？')
        ttk.Entry(manual,textvariable=self.test_prompt).pack(fill='x')
        shortcuts=ttk.Frame(manual)
        shortcuts.pack(fill='x',pady=4)
        for label,command in [('菜单','/all'),('今天','/today'),('成员','/member @昵称'),('早安','/morning'),('状态','/status'),('吃什么','/eat')]:
            ttk.Button(shortcuts,text=label,command=lambda c=command:self.test_prompt.set(c)).pack(side='left',padx=2)
        ttk.Label(shortcuts,text='← 只填写命令，再选择预览或发送').pack(side='left',padx=6)
        test_buttons=ttk.Frame(manual)
        test_buttons.pack(fill='x',pady=(6,0))
        ttk.Button(test_buttons,text='仅生成预览',command=lambda:self.manual(False)).pack(side='left')
        ttk.Button(test_buttons,text='生成并发到当前群',command=lambda:self.manual(True)).pack(side='left',padx=8)
        ttk.Label(manual,text='“生成并发送”会实际发群，不受上面的“只预览”限制；可在输入框指定回答口吻。',wraplength=740).pack(anchor='w',pady=(4,0))
        self.last_answer=''
        ttk.Button(use_content,text='复制当前回答 / 报错',command=self.copy_answer).pack(anchor='e',pady=4)
        self.tabs=ttk.Notebook(use_content)
        self.tabs.pack(fill='both',expand=True)
        self.answer=scrolledtext.ScrolledText(self.tabs,height=10,wrap='word',state='disabled')
        self.log=scrolledtext.ScrolledText(self.tabs,height=10,wrap='word',state='disabled')
        self.tabs.add(self.answer,text='AI 回答（生成后显示）')
        self.tabs.add(self.log,text='运行日志')
        ttk.Label(frame,text='仅目标群文本发送给 DeepSeek；Key 加密保存。',foreground='#666666').pack(anchor='w',pady=8)
        for var in [*self.vars.values(),self.daily,self.daily_time,self.context_wait,*[v for row in self.group_vars for v in row.values()]]:
            var.trace_add('write',self.mark_dirty)
        self.root.after(150,self.drain)
        self.root.protocol('WM_DELETE_WINDOW',self.close)

    def update_period_tip(self,*_):
        cutoff=self.daily_time.get()
        self.period_tip.set(f'总结周期：前一天 {cutoff} → 当天 {cutoff}；未到时间则取上一完整周期。')

    def mark_dirty(self,*_):
        running=self.thread is not None and self.thread.is_alive()
        self.pending_tip.set('有未保存修改，停止后重新启动生效。' if running else '有未保存修改。')

    def update_guide(self):
        if self.ready and not self.stop.is_set():
            self.guide.set(f'服务群：{"、".join(g["group"] for g in self.active_groups) or self.active_group}。'+('回复仅预览。' if self.runtime_preview else '自动回复中；@微信号 /help 查看菜单。'))
        elif self.stop.is_set():
            self.guide.set('正在停止处理；不会发送群通知。')

    def cfg(self):
        return {**{k:v.get().strip() for k,v in self.vars.items()},'preview':self.preview.get(),
                'daily_enabled':self.daily.get(),'daily_time':self.daily_time.get().strip(),
                'context_wait':self.context_wait.get().strip(),
                'groups':[{k:row[k].get().strip() for k in ('group','nickname')} for row in self.group_vars if row['enabled'].get()]}

    def copy_answer(self):
        if self.last_answer:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_answer)
            self.emit('已复制当前回答 / 报错。')

    def edit_style(self):
        window=tk.Toplevel(self.root)
        window.title('回答风格 · 最多12000字')
        window.geometry('740x560')
        editor=scrolledtext.ScrolledText(window,wrap='word')
        editor.pack(fill='both',expand=True,padx=12,pady=12)
        editor.insert('1.0',self.vars['style'].get())
        def accept():
            value=editor.get('1.0','end').strip()
            if len(value)>12000:
                messagebox.showerror('风格太长','最多12000字，请精简。',parent=window)
                return
            self.vars['style'].set(value)
            window.destroy()
        ttk.Button(window,text='应用到表单（群内回复需重新启动）',command=accept).pack(pady=8)

    def change_preview(self):
        self.runtime_preview=self.preview.get()
        self.update_guide()
        if CONFIG.exists():
            try:
                saved=load_config()
                saved['preview']=self.runtime_preview
                save_config(saved)
            except Exception:
                self.emit('回复方式已切换，但未保存成功；下次启动请重新检查。')
        self.emit('群内触发模式：'+('只预览，不发群' if self.runtime_preview else '自动回复到运行中的群'))

    def manual(self, send):
        if not self.ready or self.stop.is_set():
            messagebox.showinfo('先启动','请先点击“保存并启动”，等待日志显示已连接，再测试。')
            return
        cfg=self.cfg()
        if cfg['groups']!=self.active_groups:
            messagebox.showerror('群设置尚未生效','群名称已修改，请先停止并重新启动，避免发错群。')
            return
        prompt=self.test_prompt.get().strip()
        if not prompt:
            return
        if self.commands.qsize()>=8:
            messagebox.showinfo('请稍等','已有多条请求排队，请等待回答。')
            return
        target=self.test_group.get()
        if target not in [g['group'] for g in self.active_groups]:
            messagebox.showerror('选择群','请先选择一个已启动的目标群。')
            return
        self.commands.put((target,prompt,send,cfg['style']))
        self.emit(f'已提交手动测试 → {target}（'+('将发送到群' if send else '仅预览')+'）')

    def emit(self,text):
        self.events.put(('log',text))

    def drain(self):
        try:
            for _ in range(60):
                kind,text=self.events.get_nowait()
                if kind=='done':
                    self.ready=False
                    self.start_btn.configure(state='normal')
                    self.status.set(text or '已停止')
                    self.guide.set('自动操作已暂停，请查看错误并手动处理。' if text.startswith('异常') else '已停止回复。')
                    self.schedule_status.set('每日任务：机器人已停止，暂停执行')
                    if self.closing:
                        self.root.destroy()
                        os._exit(0)
                elif kind=='api':
                    self.api_result.set(text)
                    self.api_btn.configure(state='normal')
                elif kind=='notice':
                    self.notice.set(text)
                elif kind=='status':
                    if self.stop.is_set():continue
                    self.status.set(text)
                    self.update_guide()
                elif kind=='schedule':
                    self.schedule_status.set(text)
                elif kind=='answer':
                    self.last_answer=text
                    self.answer.configure(state='normal')
                    self.answer.delete('1.0','end')
                    self.answer.insert('end',text)
                    self.answer.configure(state='disabled')
                    self.tabs.select(self.answer)
                    self.pages.select(self.use_page)
                else:
                    self.log.configure(state='normal')
                    self.log.insert('end',time.strftime('%H:%M:%S ')+text+'\n')
                    if int(self.log.index('end-1c').split('.')[0])>1200:
                        self.log.delete('1.0','201.0')
                    self.log.see('end')
                    self.log.configure(state='disabled')
        except queue.Empty:
            pass
        self.root.after(150,self.drain)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        cfg=self.cfg()
        if not all(cfg[k] for k in ('api_key','model')):
            messagebox.showerror('配置未完成','请填写 API Key、模型、目标群和微信号群昵称。')
            return
        try:
            cfg['groups']=group_settings(cfg)
            import re
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',cfg['daily_time']):
                raise ValueError('每日时间请填写 HH:MM，例如09:00。')
            cfg['context_wait']=int(cfg['context_wait'])
            if not 0<=cfg['context_wait']<=15:
                raise ValueError('等待秒数须为0～15。')
            if len(cfg['style'])>12000:
                raise ValueError('回答风格最多12000字，请点击多行编辑精简。')
        except ValueError as e:
            messagebox.showerror('配置错误',str(e))
            return
        if (DATA/'safety-pause.json').exists():
            if not messagebox.askyesno('手动恢复','上次异常已暂停。请先在官方微信完成登录或安全验证，并确认可正常收发。\n已经处理好，恢复助手吗？'):
                return
            cfg['resume_confirmed']=True
        try:
            save_config({k:v for k,v in cfg.items() if k!='resume_confirmed'})
        except Exception:
            messagebox.showerror('保存失败','无法写入配置。请确认程序目录可写；本次没有启动。')
            return
        self.commands=queue.Queue()
        self.pending_tip.set('')
        self.notice.set('')
        self.ready=False
        self.active_groups=[dict(g) for g in cfg['groups']]
        self.active_group=self.active_groups[0]['group']
        self.group_selector.configure(values=[g['group'] for g in self.active_groups])
        self.test_group.set(self.active_group)
        self.runtime_preview=cfg['preview']
        self.stop.clear()
        self.start_btn.configure(state='disabled')
        self.status.set('启动中 · 正在连接微信…')
        self.guide.set('正在连接，请不要重复启动。连接成功后，到“试用与回答”先测试菜单。')
        self.thread=threading.Thread(target=self.run,args=(cfg,),daemon=True)
        self.thread.start()

    def halt(self):
        if not self.thread or not self.thread.is_alive():
            if not self.status.get().startswith('异常'):self.status.set('已停止')
            return
        self.stop.set()
        self.status.set('停止中 · 正在取消未发送的请求…')
        self.update_guide()

    def close(self):
        if self.thread and self.thread.is_alive():
            if not messagebox.askyesno('退出助手','退出会停止群回复和每日总结，不会发送群通知。确定退出？'):
                return
            self.closing=True
            self.halt()
            return
        self.root.destroy()
        os._exit(0)

    def test_api(self):
        if str(self.api_btn['state']) == 'disabled':
            return
        cfg=self.cfg()
        if not cfg['api_key']:
            self.api_result.set('失败：请填写 API Key。')
            return
        self.api_result.set('测试中…')
        self.api_btn.configure(state='disabled')
        def test():
            try:
                ask(cfg,'只回复：连接成功',[])
                self.events.put(('api','成功：API 连接正常（未上传群聊）。'))
            except Exception as e:
                self.events.put(('api','失败：'+str(e).replace(cfg['api_key'],'[Key]')[:350]))
        threading.Thread(target=test,daemon=True).start()

    @staticmethod
    def send_verified(db,gui,room,group,text):
        fresh=db.nickname_map(refresh=True)
        matches=[u for u,n in fresh.items() if n==group]
        if matches != [room]:
            raise RuntimeError('群名变动或存在同名联系人，停止本次发送')
        result=gui.send_msg(text,who=group,verify=True)
        if not result:
            reason=result.get('message','检查微信窗口') if hasattr(result,'get') else '检查微信窗口或远程桌面会话'
            if '消息已操作发送，但数据库未确认' in str(reason):
                raise SendUnconfirmed('发送操作已完成，数据库确认超时；请查看群消息，不自动重发。')
            raise RuntimeError('发送未确认，不自动重试：'+str(reason))

    def run(self,cfg):
        store=None;executor=None;engine=None;initialized=False;normal=False;end_state='已停止'
        try:
            import pythoncom
            pythoncom.CoInitialize();initialized=True
            from wechatauto.db import WeChatDB, auto_detect_db_dir, _find_account_dirs
            from wechatauto.param import WxParam
            WxParam.ENABLE_FILE_LOGGER=False
            directory=auto_detect_db_dir()
            if not directory:raise RuntimeError('找不到微信数据，请先手动登录微信。')
            accounts=[Path(x).name for x in _find_account_dirs(directory) if (Path(x)/'db_storage').is_dir()]
            account=cfg.get('account')
            if not account:
                if len(accounts)!=1:raise RuntimeError('请选择微信号目录：'+', '.join(accounts))
                account=accounts[0]
            if account not in accounts:raise RuntimeError('微信号目录不匹配。')
            cache=DATA/'wechat_cache'/account
            cache.mkdir(parents=True,exist_ok=True)
            class SelectedAccountDB(WeChatDB):
                def _try_other_accounts(self):return False
                def _select_account_by_keys(self,candidates):return False
                def _stable_key_dirs(self):return [str(DATA/'key_cache')]
            gui=make_gui()
            gui.check_session()
            db=SelectedAccountDB(db_dir=directory,account=account,workdir=str(cache))
            if db.account!=account:raise RuntimeError('接入库切换了账号，已停止。')
            gui._cached_db=db
            store=Store(DATA/'history.sqlite3')
            executor=ThreadPoolExecutor(max_workers=1)
            engine=Engine(self,cfg,db,gui,store,executor,DATA/'safety-pause.json')
            engine.initialize()
            while not self.stop.is_set():
                engine.tick()
                self.stop.wait(3)
            normal=True
        except Exception as e:
            end_state='异常暂停 · 请查看下方错误'
            detail=str(e).replace(cfg['api_key'],'[Key]')[:500]
            if isinstance(e,SessionPaused):
                # A restart never silently clears the pause; start() requires explicit recovery.
                pause=DATA/'safety-pause.json'
                if not pause.exists():
                    pause.write_text(json.dumps({'reason':'微信会话或发送异常，需要手动检查。','time':time.time()},ensure_ascii=False),encoding='utf-8')
                self.events.put(('notice','已暂停自动操作；请完成微信登录或验证后手动重新启动。'))
            self.emit('已停止：'+detail)
            self.events.put(('answer',detail+'\n\n'+problem_hint(e)))
        finally:
            self.ready=False
            try:
                if engine:engine.close(normal=normal)
            except Exception as e:self.emit('停止清理异常：'+str(e).replace(cfg['api_key'],'[Key]')[:200])
            if store:store.db.close()
            if executor:executor.shutdown(wait=False,cancel_futures=True)
            if initialized:pythoncom.CoUninitialize()
            self.events.put(('done',end_state))

if __name__=='__main__':
    mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\WeChatGroupAI_single_instance')
    if ctypes.windll.kernel32.GetLastError()==183:
        ctypes.windll.user32.MessageBoxW(None,'程序已经打开，请查看任务栏。','微信群 AI',0)
        sys.exit(0)
    root=tk.Tk()
    App(root)
    root.mainloop()
