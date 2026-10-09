# Linux 桌面真实验收与启动审计

时间：2026-10-10，北京时间。目标仅为授权的 Ubuntu 24.04 桌面试验 VM；本次未重启 VM、改宿主、改其他 VM 或防火墙。

## 已完成

- 专用 `pajio-desktop` 非登录账号，无 sudo/docker/libvirt/lxd 组；HOME 0700。用户管理器 lingering 已开启。
- `pajio-x11.service`、`pajio-desktop-session.service`、`pajio-browser.service` 均 enabled/active/running；检查时 `NRestarts=0`。
- Xvfb `:10` 为 1280×800×24，禁止 TCP，Xauthority 0600、所在 runtime 目录 0700。每次服务启动重新生成 cookie，cookie 不进入 argv、环境或日志。
- Xfce、中文 locale/fonts/IBus、AT-SPI 已启动。native status 报告 `linux-x11-atspi` ready，实际画面/节点可读。
- Firefox 157.0.1~build1 由 Mozilla 官方 APT 仓库安装。签名 key fingerprint 为 `35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3`。直连大包失败后，经管理员现有 SSH 通道转运同一官方包；包 SHA-256 与 VM 已验签 APT 元数据一致，为 `8fc31769ce9e9286235269c0c5e23afda9344c0545d87a357a0da0e14b36b2cc`。

## 真实输入与坐标结果

在专用 GTK 合成窗口进行真实调用，未涉及用户账号或业务数据：

| 检查 | 结果 |
| --- | --- |
| AT-SPI `EditableText` 写入，再重新读树 | 通过，读回固定合成文本 |
| XTEST `Ctrl+A` 与键盘输入，再重新读树 | 通过，读回 `Pajio keyboard 42` |
| AT-SPI 按钮点击 | 通过，标签由 `Not saved` 变为 `Saved probe` |
| 滚动 | 通过，前后 PNG 不同，`Scroll section 2` 由不可见变为 bounds `[40,191,620,300]` |
| 截图与元素坐标 | 客户区 700×500，桌面 origin `[5,56]`，PNG 尺寸一致 |

测试发现 Ubuntu 版 xdotool 在 Xfce reparented 窗口上重复计入边框，原报告为 `[10,85]`。原生 helper 已改用 `xwininfo` 的绝对客户区 origin，并将滚动指针位置转换为同一绝对坐标。对应回归测试覆盖该真实偏移。合成窗口已关闭。

私有原始证据位于部署工作目录 `personal-compute/gtk-report.json` 和 VM 的桌面用户 `.cache/pajio-native-validation/gtk-*.png`，不将画面或部署凭据纳入 Git。此结果是驱动到原生窗口的验收，不代表 Agent/relay/App 全链路通过。

代码回归：`test_linux_computer.py`、`test_linux_connector_service.py`、`test_connector_service.py`、`test_desktop_input.py` 共 **71 passed**。shell 启动/安装脚本语法检查通过；X11/session 的 `systemd-analyze --user verify` 通过。

实际 connector unit 暴露 `WorkingDirectory="/home/pajio-desktop"` 被 systemd 当作含字面引号路径的问题。生成器已改为不加引号的绝对路径，仅转义 `%`，拒绝控制字符与容易造成 unit 续行的结尾；ExecStart/Environment 保留各自引用规则。Ubuntu systemd 255 对包含空格、`%n`、`$HOME` 和字面引号的真实测试目录执行 `systemd-analyze --user verify` 返回 0。旧 unit 的迁移使用现有哈希校验 uninstall/install 流程并保留连接器配对/动作账本；随后由部署主任务显式 start，不直接删除 manifest。

## 浏览器待确认

专用 Firefox profile 仍显示首次启动使用条款/隐私声明对话框。没有点击接受、修改接受记录或绕过它。父任务已向用户请求明确确认。浏览器真实网页的编辑/点击/滚动验收尚未通过；不能用上述 GTK 结果替代。`probe-linux-native.py` 在测试页字段不可用时明确失败。

## 资源快照及边界

2026-10-10 审核时 VM 内存 total 3915 MiB、used 1017 MiB、available 2898 MiB，无 swap；磁盘 30 GiB 中 used 4.5 GiB、available 26 GiB。按 systemd cgroup，X11 约 40 MiB、桌面会话约 118 MiB、Firefox 约 504 MiB。进程 RSS 包含共享页，不能直接相加为物理内存。

这是首启页面和空闲桌面快照，未覆盖视频编码、复杂网站、多标签、中文输入或下载峰值。它不构成降低每设备 4 GiB 预算或增加用户数量的依据。

## 启动与持久化审计

1. lingering + enabled 用户 unit 证明已配置登录外启动；没有进行本轮 VM 冷启动，不能记为重启验收完成。宿主是否对该 VM 开机自启由宿主管理任务决定。
2. X11 cookie 和 D-Bus socket 是 runtime 数据，重启后重新创建。Firefox profile 和 HOME 是 VM 持久磁盘。服务使用稳定路径，不保存临时 cookie 到镜像。
3. native/media 环境使用 `pajio-desktop-bus`；`systemctl --user` 必须使用用户管理器 `bus`，二者不能混用。connector 已修正管理命令的环境，避免桌面总线导致找不到 systemd 服务。
4. 当前 `Requires` + `After` 可处理显式依赖启动/重启；`Restart=on-failure` 处理进程异常退出。干净退出、X server/DBus 异常连锁恢复必须做维护窗口故障注入。没有未经验证增加会不断重新打开用户已关闭浏览器的配置。
5. 冷启动验收须先暂停租户任务和接管、等待原生锁排空并记录控制 epoch，重启后验证 cookie 更新、旧媒体失效、文件散列保留、登录仅由用户确认、native/relay 就绪，明确交还后才恢复 Agent。不能以服务 active 自动恢复旧输入。
6. 安装脚本新增专用 VM 检查，拒绝 Proxmox 宿主与存在 `/var/lib/wearing/instance` 的核心 VM，并拒绝复用有交互式 shell 的同名桌面账号。本次只更新可复用源码，未借此重跑活跃桌面安装。

systemd 依赖语义核对：[官方 v255 systemd.unit 源文档](https://github.com/systemd/systemd/blob/v255/man/systemd.unit.xml)。
