<img width="960" height="1962" alt="7ca56d978ad638747a0c1be76e0587a2" src="https://github.com/user-attachments/assets/e012b3b9-2f0d-4cbd-8067-a045241c1fca" /># WeChatGroupAI

Windows 微信群 AI 助手、总结聊天。带图形管理界面，适合小范围群聊使用。

## 微信风控

极严，玩了一周就消耗一个小号，不玩了

<img width="1279" height="1422" alt="6ea2bbad22cc36aae00fecc999ea5663" src="https://github.com/user-attachments/assets/d677730e-458f-48a4-9414-1d8ca094807c" />

## 运行

1. 准备 Windows x64、Python 3.12 x64（包含 Python Launcher、Tkinter），安装并登录官方微信客户端。
2. 下载本仓库并解压，双击 `Install.cmd` 安装依赖。
3. 双击 `Start.cmd`，填写自己的 API Key、可用模型名称、目标群名和微信昵称，保存并启动。
4. 先预览回答，确认后切换自动回复。启动和停止通知在预览模式下也会发送。

模型名称需要与自己的 API 账户支持范围一致。若出现 `win32ui` DLL 错误，请安装微软官方 Visual C++ x64 运行库。

## 注意

- 当前发布的是源码和可运行脚本，不含独立 EXE；没有提供任何账号或 API Key。
- 非微信官方机器人接口，依赖桌面会话和客户端兼容性，不保证长期在线或账号无风险。请取得群成员同意。
- 仅将选定群的相关文本发送给 DeepSeek；API 调用可能收费。不识别图片、语音或未采集的历史。
- 本地运行数据在 `data/`，Key 使用 Windows 用户加密。不要公开此目录，即使 Key 已加密。
- Windows 服务器远程离开可使用 `Disconnect-Keep-WeChat.cmd`（管理员运行）。桌面可能保持解锁；重启后仍需登录、启动。正常关闭远程窗口可能影响发送。
- “发送未确认”不等于“没有发送”：先检查群消息，避免重复。断网、强制结束进程无法保证停止通知。

当前版本：v3.5.1。主要依赖：[wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica)、Requests、pywin32；依赖通过安装脚本获取，没有打包第三方代码。源码暂未指定开源许可证。
