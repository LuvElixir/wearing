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

## 浏览器授权后的真实验收（2026-10-10）

首次 GTK 验收时，Firefox 的首启条款仍未确认。用户随后明确回复“同意，继续验收”，本轮仅在 A 的专用 Firefox profile 中通过真实界面确认；可选技术/交互数据及自动崩溃报告均核对为关闭。B 的 Firefox 首启条款仍由其实际使用者确认，未克隆 A profile 或写入统一接受标记。

真实网页暴露了 GTK 用例未覆盖的问题：Firefox 的 AT-SPI EditableText 返回成功却没有改变字段；零延迟 XTEST 丢失中文。12 ms 候选虽能输入中文，混合 emoji/é/ASCII 仍出现错序，不予采用。最终改为共享的 30 ms 节奏、普通 Agent 单次最多 256 码点、私密接管最多 32 码点。普通输入验证准确字段内容，未知结果不自动重放；私密输入不读取密码字段。Firefox 的非 BMP ATK 表示按 [Mozilla 官方 DOMtoATK 源码](https://raw.githubusercontent.com/mozilla/gecko-dev/master/accessible/atk/DOMtoATK.cpp) 投影预期值，不删除实际内容中的 U+FEFF。

| 实际检查 | 结果与范围 |
| --- | --- |
| 混合文本替换 | 224 码点中文、ASCII、é、emoji、标点完整读回，约 3.77 秒；另验清空与短文本 |
| 最终部署版本的合成网页 | 精确 Unicode `set_value`、`type`、Save 计数加一，以及 Section 1 上移/消失、Section 2 进入视口全部通过 |
| 地址栏 | 建议列表导致 AX 索引改变时，以原节点身份匹配读回；真实地址输入通过 |
| 公网网页 | Firefox 实际访问 `https://example.com/`，读到 Example Domain 文档及正文；不是只用 curl 代替浏览器 |
| 浏览器持久化 | 真实界面添加 Example Domain 书签，仅重启 `pajio-browser.service`，新 PID 后可在书签搜索中找到它，首启条款未再次出现 |

最终普通网页探针报告为 `probe-recheck-20261010T091441.json`，helper SHA-256 为 `6cc336fd24c39eb5be29afd7058f696b6aa7406062a8e739150c3edb8ffe7da2`。原始数据在私有 `personal-compute/browser-acceptance-20261010/` 中；画面、部署配置、登录凭据不进入 Git。探针只验证本地合成网页，书签持久化是另一次真实 UI 验收；未验证第三方登录 cookie、跨 VM 恢复或所有网站。

保留失败证据：旧滚动探针错误要求屏外 Section 2 先出现在树中，已改为可见 Section 1 基线；一次空字段探针报 `linux_invalid_target`，没有重放输入。后续只读五次检查 count/caret/selection 均为 0/0/0，再以新操作运行完整探针通过；该次瞬时拒绝的根因尚未证明，不能归因于已修复的输入丢字。

本轮 Linux/私密媒体/连接器/桌面针对性回归 **176 passed**。A/B 两台 Linux 的 helper 与媒体输入源均按预像哈希核对、备份、窄更新；只重启两台的私密媒体服务，后续节点身份修正仅替换每次调用重新加载的 helper，无需重启核心、连接器或 VM。

## 资源快照及边界

2026-10-10 审核时 VM 内存 total 3915 MiB、used 1017 MiB、available 2898 MiB，无 swap；磁盘 30 GiB 中 used 4.5 GiB、available 26 GiB。按 systemd cgroup，X11 约 40 MiB、桌面会话约 118 MiB、Firefox 约 504 MiB。进程 RSS 包含共享页，不能直接相加为物理内存。

这是首启页面和空闲桌面快照，该初始资源快照未覆盖视频编码、复杂网站、多标签、中文输入或下载峰值；后续中文功能验收不构成峰值负载测试。它不构成降低每设备 4 GiB 预算或增加用户数量的依据。

## 启动与持久化审计

1. lingering + enabled 用户 unit 证明已配置登录外启动；没有进行本轮 VM 冷启动，不能记为重启验收完成。宿主是否对该 VM 开机自启由宿主管理任务决定。
2. X11 cookie 和 D-Bus socket 是 runtime 数据，重启后重新创建。Firefox profile 和 HOME 是 VM 持久磁盘。服务使用稳定路径，不保存临时 cookie 到镜像。
3. native/media 环境使用 `pajio-desktop-bus`；`systemctl --user` 必须使用用户管理器 `bus`，二者不能混用。connector 已修正管理命令的环境，避免桌面总线导致找不到 systemd 服务。
4. 当前 `Requires` + `After` 可处理显式依赖启动/重启；`Restart=on-failure` 处理进程异常退出。干净退出、X server/DBus 异常连锁恢复必须做维护窗口故障注入。没有未经验证增加会不断重新打开用户已关闭浏览器的配置。
5. 冷启动验收须先暂停租户任务和接管、等待原生锁排空并记录控制 epoch，重启后验证 cookie 更新、旧媒体失效、文件散列保留、登录仅由用户确认、native/relay 就绪，明确交还后才恢复 Agent。不能以服务 active 自动恢复旧输入。
6. 安装脚本新增专用 VM 检查，拒绝 Proxmox 宿主与存在 `/var/lib/wearing/instance` 的核心 VM，并拒绝复用有交互式 shell 的同名桌面账号。本次只更新可复用源码，未借此重跑活跃桌面安装。

systemd 依赖语义核对：[官方 v255 systemd.unit 源文档](https://github.com/systemd/systemd/blob/v255/man/systemd.unit.xml)。

## 私密远程输入补验

通过真实公网 TURN + WebRTC/SCTP，A 在 Firefox 合成字段、B 在独立 GTK 合成字段分别输入 32 码点中文/ASCII/emoji/é/标点。B 未操作 Firefox 首启条款，临时 GTK 验收进程结束后已关闭。两次 ready 均真实声明 32 码点、4096 字节和禁控制字符能力。

| 账户 | 首个解码帧 | 文本 ACK | 最大视频间隔 | 最大帧元数据间隔 | 交还后的合成值核对 |
| --- | --- | --- | --- | --- | --- |
| A / Firefox | 0.917 秒 | 0.689 秒 | 0.659 秒 | 0.668 秒 | 精确一致 |
| B / GTK | 0.971 秒 | 0.535 秒 | 0.634 秒 | 0.633 秒 | 精确一致 |

两次均明确交还后收到 `agent_ready / device_confirmed=true`，旧 offer 返回 409。私密会话期间没有读取字段；关闭和交还完成后，才对事先约定的合成测试字段做普通设备所有权锁保护的布尔核对。测试程序不保存媒体、输入正文或 SDP，不调用付费模型。元数据报告为 `a-private-unicode-proof.json` / `b-private-unicode-proof.json`。这是各一次实测时序，不是端到端延迟 SLA 或并发负载结果；App 原生操作单独记账。

## 本轮原生 App 与最终状态

新版 iPhone 模拟器 Release App 保留既有 OAuth 与数据，实际进入 A Linux 私密接管。输入 33 码点时显示长度提示，完整掩码草稿仍在，合成字段画面不变；随后改为 20 码点中英文/emoji/é 合成串，仅点一次发送，草稿清空，画面持续可用。没有点网页的 Save 按钮，不把输入成功称为表单保存成功。

双确认交还后 App 显示设备确认。独立服务端在普通设备锁与 Agent 许可下只读核对已约定的合成字段：原 32 码点前缀加合法 20 码点后缀完整一致，不含被拒绝的草稿；仅保存布尔结果和长度。验收期间没有读取真实密码或调用模型。证据为私有 `mobile-browser-input-fix-native-proof.json` 与 `browser-acceptance-20261010/native-app-exact-text-proof.json`。

本轮最终独立检查：A/B 核心各连续 3 次公网 HTTP 200 且 Hermes reachable，没有运行/排队/启动中的任务；四台执行设备均 `agent_ready / device_confirmed=true`，7 台 VM 固定服务健康。新检查保存在 `browser-acceptance-20261010/final-handoff-proof.json`，保留上轮历史检查；48 小时连续运行仍未完成。原生结果限于 iPhone 模拟器，本轮未补物理 iPhone/Android 安装与实际第三方账号登录。
