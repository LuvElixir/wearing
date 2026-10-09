# 连接器常驻

设备配对后，让连接器随当前用户登录运行。Mac 使用系统 LaunchAgent，Windows 使用系统任务计划程序；不新增本机监听端口。云端 Wearing 继续在独立 VM 中运行，电脑睡眠、退出登录或手机拔线只会使设备暂时不可用。

```sh
wearing connector service install --root 连接目录
wearing connector service status --root 连接目录
wearing connector service stop --root 连接目录
wearing connector service start --root 连接目录
```

`install` 不重复创建同一连接目录的任务，也不覆盖明确的停止状态。Mac 任务及日志保存在当前用户的 Library；Windows 任务在 `\Wearing\`，以当前已登录用户、最低权限运行，无需保存登录密码。Windows 安装会限制连接目录 ACL 为当前用户与 SYSTEM。OS 任务只保存 Python 和连接目录路径，令牌仍在私有配对文件中。

`status` 根据运行锁、最新心跳和本机账本报告进程、连接与进行中动作，旧的“connected”文件不算当前在线。`stop` 先持久化停止意图，阻止新动作；已经调用设备的动作会继续交回回执。退出时通知云端断开，尚未开始的命令标记为 blocked，无法确认的执行标记为 unknown。如果网络已断，云端依靠连接租约过期识别离线。启动或登录不会绕过停止意图；用户明确执行 `start` 才恢复。

重启继续使用原配对令牌、独立电脑 ID、资源权限、暂停记录与动作账本。重新建立云端连接后使用新连接代次，旧代次不能停止新连接。结果不明的原动作不会被重新执行。启动中或停止中请先查看状态。

```sh
wearing connector service uninstall --root 连接目录
```

移除常驻先请求停止；进程仍在完成动作时会要求稍后重试。移除仅删除本连接器的系统任务和常驻登记，不删除配对、密钥、动作账本和历史，不撤销云端配对。后台任务被改为其他程序或用户时，操作拒绝覆盖它。

首轮试验中已有的 Wearing Mac 任务可以明确迁移管理，必须与当前 Python、命令和连接目录完全相同：

```sh
wearing connector service install --root 连接目录 --adopt-existing com.wearing.connector.tencent-first
```

目前是 CLI 安装能力，还没有签名安装包、自动更新或跨天恢复验收。Windows 的 XML、命令引用和归属校验有自动测试，仍需 Windows 真机验证。电脑输入权限、ADB/手机系统授权、首次账号登录仍需分别准备。更换 Python 安装路径前应先移除旧常驻；随后使用新安装重新登记，配对与历史可继续保留。

系统参考：[Apple LaunchAgent 生命周期](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)、[Microsoft 任务主体与登录类型](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal?view=windowsserver2025-ps)、[任务设置](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset?view=windowsserver2025-ps)。
