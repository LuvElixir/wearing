# Pajio Web / Desktop 真实设备接管交接

> 历史交接：2026-10-10 用户已改为所有客户端由 Codex 负责。ZCode 仅完成当时进行中的 v57 任务；后续 v58 及实现由 Codex 接手。现行顺序见 [统一开发计划](pajio-unified-delivery-2026-10-10.md)。下文保留当时边界与验收要求。

用户本轮要求继续推进云手机和桌面端。延续分工：ZCode 实现 Web / Desktop；Codex 实现 App、共享后端和设备，最后独立验收。当前基线 `4e7dad7`，并行修改须保留，尤其主计划当前已有他人未提交的句尾改动。

## 本轮交付目标

桌面 Pajio 用户能看到自己真实的 Linux / Android 设备，查看画面，明确开始操作，输入和触控，断线后安全重连，明确交还并等待设备确认。沿用真实公开服务鉴权，不用假在线状态或旧暂停按钮冒充远程控制。

## 只读依据

- `clients/mobile/src/NativeRemoteDevicePanel.tsx`
- `clients/mobile/src/remote-device-model.ts`
- `clients/mobile/src/remote-viewer-document.ts`
- `clients/mobile/src/remote-text-input.ts`
- `docs/private-media-host.md`、`docs/device-gateway.md`（若存在，以源码合同为准）
- `src/wearing/device_access.py` 与 `src/wearing/app.py` 中 `/api/devices/access/` 路由；实际文件名先搜索。
- `docs/evidence/personal-compute-delivery-2026-10-10.md`

现有生产 A/B 已有真实 Linux / Android、短期 TURN、DTLS/SRTP/SCTP、设备确认与重放拒绝。私密接管时 Agent 必须暂停读取和输入。源码和已有通道可以只读研究，不得改 App/Python/部署配置，也不要操作真实用户数据。

## 实现范围与体验

1. `src/wearing/web/` 增加独立远程接管模块与真实设备入口，接入已有账户、身份、注销冻结和模态交接。保持 App WebView 宿主分支不加载新功能。
2. 复用现有公开 API 状态机：request → 等设备 ACK → transport/offer → 视频 ready → 用户显式开始操作 → 双确认 return → 等设备 ACK。未知状态、断网、过期、页面隐藏/关闭、换身份/退出立即停止输入与视频；不自动恢复 Agent，不自动重发输入。
3. 支持浏览器与 Tauri WKWebView 的 WebRTC；鼠标/触控、滚动、键盘按设备能力展示。Linux 输入 32 码点及 4096 字节、Android 4096 字节，按 ready 能力整体预检；超长保留未发草稿，不截断、不分段、不回显私密文本。禁止 clipboard/日志/本地持久化/截图留存。
4. 布局适合桌面大屏，远程画面按真实宽高等比，控制状态始终明确，云手机竖屏有足够显示高度。交还不能只关弹窗，要有设备确认；意外关闭保持暂停。
5. 检查 `clients/desktop/` 连接公开服务的入口与跳转边界。复用现有云端登录，保持 OAuth 跳转、原生 IPC 隔离、证书验证。不得向公网网页授予原生命令能力或放宽任意 origin。必要修复仅限桌面壳及测试。

## 验收和交付

- 先以隔离合成 QA / mock 合同做行为回归：请求竞态、过期/旧帧、换身份/退出、超长草稿、未知输入无重放、旋转、明确交还与 cleanup 失败。
- 保留现有 Web tests；执行对应 Node tests 和 Rust tests/build。
- 真实公网 A/B 验收由 Codex 协调，先源码冻结后报告，避免同时抢设备。不要用过期 8892 的合成响应冒充现行服务器能力。
- 可构建独立标识的 QA 桌面包，不覆盖当前正在使用的 Pajio；记录构建路径、源码、测试、剩余问题到 `docs/evidence/pajio-desktop-remote-20261010/zcode-delivery.md`。
- 不 deploy、不 Git commit/push、不改 Codex memories。不要为通过测试降低鉴权、帧时效、输入 ACK 和设备交还门禁。
