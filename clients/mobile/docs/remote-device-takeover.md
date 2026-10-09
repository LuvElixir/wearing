# App 私密远程接管

2026-10-10。范围限于 `clients/mobile`。这是实现说明与分层验收记录。公网 Linux 与 Android 链路已在 iOS 模拟器验证，物理手机与跨网络测试仍需独立完成。

## 入口与可见状态

- 我的 / 设置 → 设备 → 具体设备。使用当前身份的 `/api/devices` 清单；对每台设备请求 `/api/devices/access/{resource_id}`，仅服务端声明 `supported` 才显示接管入口。
- App 内独立接管页面使用 Expo Router `view=remote-device`。路由只包含设备标识、名称、类型；无 token、密码、TURN 凭据或 SDP。
- 用户点接管后请求暂停 Agent。仅服务端 `human_private + device_confirmed + 有效 session/epoch/gateway_epoch` 才请求短期 transport。
- native 层携带账户凭据完成 SDP 信令，App 自有内嵌 WebView 只接收本次会话和短期 ICE 配置。它不加载远程脚本、不开启存储、没有服务 bearer。
- WebRTC 收到可信 ready / frame metadata，并实际解码出尺寸一致的视频帧后，才显示“查看画面”。再点“开始操作”才打开输入。
- 所有按键、触控输入只有这一个会话和递增 seq，无离线队列、无自动重试；收到错误明确提示。

## 输入与生命周期

- 触控按 `object-fit: contain` 的真实画面矩形计算；黑边不发送点击。电脑为 pointer down / move / up，手机为 tap / swipe。支持键盘发送，Android 提供返回 / 主页 / 最近任务。
- 输入附最新 frame_id。画面过期、geometry_revision 或尺寸改变、触控取消、输入回执超时、通道异常均关闭画面与输入；重新连接必须再点击。
- 文本框关闭自动纠错和建议，掩码展示，不保存输入，发送时立刻清空。只有宿主声明安全的 `unicode` 文本通道才开放；旧 ASCII、`unavailable` 和未知通道均禁用，内嵌 WebView 也拒绝这些通道上的文本。Android 旧 adb argv / 广播 IME 通道不能用于私密输入。
- App 进入后台、Android 失焦、页面离开、账户切换或账户冻结时关闭媒体和输入，并尝试请求 pause。只有取得暂停回执才显示“设备保持暂停”；网络不确定时明确提示状态待核对。
- 从其他页面重新打开不会自动连接、更不会沿用旧操作。已存在未结束会话由用户主动重新接管时关闭，然后请求新 session。
- “交还 Pajio”要求确认已离开私密页面及允许继续操作。提交后停止显示私密画面与发送输入，等待相同会话新的 gateway epoch ACK。关闭连接、切后台、刷新均不会自动交还。
- 若轮询发现会话已被另一接管替换，只尝试关闭原会话，不能关闭后来出现的新 session。

## 同期体验完善

- 设备卡片按真实已授权 methods 列出能力，不能把已授权等同于在线、安装了某 App 或任务完成。
- 引导仍为点选 / 按需授权；末页可保存偏好后查看今日安排，也可选择进入首份简报准备页。准备页显示已有 API 返回的来源状态，用户再点生成。没有“已生成第一份内容”的乐观本地标记；结果按真实简报回执显示。
- 任务详情默认显示最近三条已知状态变化，可展开最近 100 条。未知技术事件、错误堆栈、原始输入不会被直接展示；目前这是任务状态轨迹，不假称逐操作录像。

## 已完成验证

- TypeScript `tsc --noEmit` 通过。
- `eslint src` 通过；定向已修改文件 lint 通过。标准 `expo lint` 被本机全局 npm/npx 的 ESM 包配置阻断；直接执行项目 ESLint 使用同一 Expo 配置。扫描整个目录会把历史 `dist-*` 编译产物和旧插件 lint 问题混入，未改写这些产物来“修复”检查。
- 全部 App 模型测试 768 项通过；其中远控测试覆盖服务端 ACK、会话边界、黑边、输入不重放、后台清屏、晚到信令、尺寸变化、不安全文本通道禁用且不回显、CSRF 等待期间离页不再发送接管。
- iOS Metro / Hermes 导出成功到被 Git 忽略的 `dist-remote-qa`。构建不是 iPhone 实机证据。

## 联调仍需完成

1. 真正安装的 iPhone / Android App 连接部署后的 Linux 与 Android 设备，观察首帧、帧率、RTT、触控和文字。
2. 从办公网切换到手机网络，验证直连 / TURN；断网、旋转、后台、账户撤权、宿主重启与重复打开。
3. 双用户越权、旧 epoch、被替换 session 的暂停边界；明确交还后 Agent 重新观察而非延续旧动作。
4. 当前 metadata 尚未与 RTP 帧逐帧绑定；两端尺寸与 frame_id 新鲜度只构成首版保护。Android PNG fallback 也不能证明检测到同尺寸 180° 旋转，应以实际驱动能力说明为准。
5. 不声称阻止用户操作系统截图 / 屏幕录制。文字输入与视频不进入 App 本地持久化或模型上下文，底层服务仍需独立审计日志配置。

## 2026-10-10 原生与公网验收

独立 iPhone Air / iOS 27 模拟器安装 Release，使用实际 OAuth 登录 acceptance-a，调用公网服务。Linux 首帧、默认只看、显式操作、原生触控落点与设备端光标核对通过（设备 x=156, y=639）；观察到 RTT 18–31 ms。接管期间 tenant relay 和 device gateway 两层拒绝 Agent 读取，未执行 Agent 截屏。明确勾选交还确认后，App 等待设备 ACK，显示 `agent_ready`。

一次约三分钟的查看期间触发 stale-video 安全暂停；App 没有自动重连或交还。用户明确重新连接后恢复，并成功交还。原因尚未分离为 metadata 或实际播放新鲜度，不把此结果称为长时稳定性通过，也没有提高阈值掩盖中断。

新安装 iOS / Android 默认使用 `https://pajio.luckyloading.com/`；保留所有已有存储连接与身份。普通账户登录位于连接页，开发身份和手动连接收在“高级 / 开发连接”内。三个测试覆盖默认、预览 origin 与已存本地 / 云端 / 开发连接保留；原生已确认升级后 OAuth 保留、开发入口折叠 / 展开均可用。

证据：被 Git 忽略的 `.wearing/on-prem/20261009/personal-compute/mobile-native-proof.json`，以及 mobile-linux-view-only.png、mobile-linux-returned.png、mobile-public-connection.png。源码 / 构建 / 原生运行分别记录，不视为实机或移动网络证据。


### Android 原生复验与聊天恢复

同一个 iOS 27 Release App 实际连接专属 Android 云手机：默认只看 → 明确操作 → Settings 搜索点击 → 安全键盘送达合成文字 `QAfinal20261010`，App 本机文本立即清空。按 iOS Home 后输入与画面关闭；设备端确认 paused，回到 App 不自动重连。再次点击“重新接管”后视频恢复，仍从只看开始；明确操作并按远程 Home 离开输入页，再两项确认交还，设备 ACK 后显示可以继续操作，退出 viewer。复验观察到 RTT 19–21 ms。首次重连曾因媒体宿主 IME 清理未确认而失败，后端修复后才完成以上完整流程，App 安全阈值未改。

聊天首屏还发现公网网关的全站请求/并发限额阻断静态脚本，导致原生 composer 没有握手。App 新增 12 秒握手超时提示与用户主动“重新打开”，保留草稿且不自动发送。服务端分别限制静态资源后，同一 App 的原生输入恢复，显式发送无工具合成消息并收到 `PAJIOOK`；握手错误和成功回执均有截图。身份 cookie 与 API 限权保持原有规则。

新增证据：mobile-android-final-text.png、mobile-android-final-paused.png、mobile-android-final-reconnected.png、mobile-android-final-returned.png、mobile-chat-handshake-retry.png、mobile-native-chat-accepted.png。云手机是远程目标；这些证据仍是 iOS 模拟器客户端，不能替代 Android 本机 App 验收。

追加前台持续观看：2026-10-09 18:33:58–18:38:09 UTC，251 秒仍保持 Linux live / view-only，RTT 采样20、19、64ms，没有后台切换、控制输入、stale-video暂停或条款接受。随后明确交还。App 这一版只显示 RTT，没有测量数值 FPS，因此不把此观察换算为帧率；早先一次暂停原因仍未确定。

### 首次引导与真实首份简报

同一 acceptance-a 测试账户真实走完“初始偏好”：角色、常用应用、兴趣等选择均可跳过，不要求文字输入，也未连接外部账户。明确保存后进入准备页，页面按服务端来源状态显示日程、待办、笔记均为空，文件空间有一个合成 QA 文件。点击“整理我的第一份简报”后先显示 running 回执，随后任务状态显示结果已返回，App 打开实际保存的 12.2 KB HTML 简报。未提前标记完成，也没有把尚未授权的来源显示为已读取。

任务 `f08d350adfa74d4eb6986c2cfcaa37fd`，简报 `brief_2511d09b374d46e0a8e59b8832e324d8`。证据为 mobile-first-brief-ready.png、mobile-first-brief-task.png、mobile-first-brief-artifact.png。原件的内容/呈现核对状态仍为 `not_verified`；本次人工可见的首屏阅读验证不改写该状态。

原件有一处“明天”的相对日期措辞与当前当地日期不一致，已保留。检查发现 App 请求目标日期与 Asia/Shanghai 正确，但服务端 prompt 缺少请求时刻按用户时区换算的本地当天。随后窄补明确请求本地时间、目标绝对日期及排队跨日的措辞规则；6 个回归覆盖上海 UTC 跨日、洛杉矶、过去/当天/未来目标及跨日幂等重放。相关简报测试共 49 项通过。这修复了缺失上下文，不能据此声称所有模型内容都已经正确。

### Android 独立安装包构建

2026-10-10 使用已有官方 SDK 36、JDK 17 和 Gradle 工具链，在隔离候选目录同步与当前 App 相同的源码、配置、插件和资源，运行 Expo prebuild，再执行 `:app:assembleRelease -PreactNativeArchitectures=arm64-v8a`。610 项构建任务成功，原生 WebView 与插件编译完成，包含 7,129,980 字节 Hermes bundle，不依赖 Metro。

安装包位于 `/Users/archieliew/Downloads/Pajio-test-20261010/Pajio-0.2.0-20261010-arm64-test.apk`，67,798,698 字节；SHA-256 `bf842764cbfab65b239ccc15bf758ebcdd78a43d6eca91310327b95ac8d8f943`。同目录 `build-proof.json` 保存源码逐文件 SHA、嵌入 bundle SHA 和验证边界。

APK v2 签名及 16 KB zipalign 检查通过，显示名 Pajio、包名 `io.luckyloading.wearing.mobile`、版本 0.2.0 / code 1、最低 API 24。当前签名为 Android Debug 测试证书，仅 arm64-v8a；没有进行这份最终包的 Android 真机安装验证，也不是正式分发签名。iOS 仍为独立模拟器 Release 构建，Apple 组织签名 / TestFlight 限制未改变。
