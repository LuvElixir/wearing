# Web 静态部署记录 · 2026-10-10

范围仅限按清单冻结的 Web 静态文件。当前 A/B 已部署 root 接手修正的 app58，保留 remote6 / CSS22；服务端回执和公网 HTTP 校验完成。此前 ZCode 版本、仅修正 index.html 换行的独立 attempt，以及 v4 的历史回归与失败证据均保留在下文。**静态部署不等于真实 Desktop UI 或媒体验收完成。**

## v4 激活与原像

| 租户 | UTC 时间 | 未变更的服务 PID | 结果 |
|---|---|---:|---|
| core-b | 2026-10-10T03:23:24.452015+00:00 | 13307 | deployed + status 一致 |
| core-a | 2026-10-10T03:25:56.981629+00:00 | 4285 | deployed + status 一致 |

部署脚本固定目标租户、instance、machine 摘要与四文件范围，核对 inspect 原像后写入；本地及远端均先保存不可覆盖的 durable intent。逐文件同目录 fsync + atomic replace，index.html 最后替换；四文件之间存在短暂混合版本窗口，不声称整体原子。未重启 Python、Core、Relay 或设备服务。

| 文件 | SHA-256 |
|---|---|
| `web/remote-device.js` | `68da063781d9cf6a7c62178f2f4918172ff5652bb3b770fccecf4d7f1c2415d4` |
| `web/pajio.css` | `8d7313f842206367ec81e8964578d61d8952d14fc01ce4cd956f5b92f7ae81cc` |
| `web/app.js` | `8cc1b0943462e12e1892e84445e19232926e1c2869ee8ebb70154f24436997e7` |
| `web/index.html` | `d4c70219203d8ef318985232154c7110c5b694cce5e9b40efea87f9260198890` |

原像路径：
- core-b: `/var/backups/pajio-web-v4/core-b-cf13afccde054b2982c086fb0e01d757`
- core-a: `/var/backups/pajio-web-v4/core-a-15d29475cd8e473c84e2ed9fbb3e363a`

私有部署脚本、intent、inspect/deploy/status、HTTP 证明及汇总位于 `.wearing/on-prem/20261009/personal-compute/device-files-20261010/`，不纳入提交。汇总 `web-static-v4-summary.json` 包含各证据 SHA。

## 实测 HTTP

- B 激活后：B 首页和三资源均返回 200，四个响应正文 SHA 与冻结清单一致；此时 A 旧版首页及资源仍为 200，HTTP 原像 SHA 随后与 A inspect 对齐。
- A 激活后：A/B 分别使用原有 QA bearer 会话请求首页，后续资源使用该响应建立的 HttpOnly 会话 cookie；四个响应正文 SHA 都与清单一致。
- 两租户版本引用精确为 `app.js?v=54`、`remote-device.js?v=4`、`pajio.css?v=21`；`/api/status` 均为 200。响应保留 `private, no-store`。
- 匿名 `/` 返回 303 `/auth/login`，匿名新资源返回 401；登录入口返回 302，官方 IdP 登录表单返回 200。没有填写账号密码或提交登录表单。
- HTTP 脚本只保存路径、响应码、内容摘要和版本，认证头、cookie、OAuth 查询串和页面正文均未落盘。

以上是有限时点 HTTP 与落盘验证；连续可用性以根任务持续探针为准。没有启动或操作真实 Desktop UI，也没有执行 WebRTC 接管，不能据此声明桌面登录、远控功能或原生 App 文件流程已经端到端验收。

## 已知问题与恢复

独立最终审查发现 v4 `app.js` 把旧设备“暂停/恢复”入口整体换成仅支持输入设备的“远程接管”，观察类及未提供私密媒体的旧设备因此失去暂停入口。修复由 ZCode 负责；A 已在暂停通知到达前完成部署，之后没有继续写入。后续修正版须独立 manifest、intent、备份和回执，不覆盖 v4 记录。

需要精确恢复时，在私有证据目录运行 `python3 -I web-overlay.py core-a rollback` 或对应 `core-b rollback`。恢复只在当前文件仍等于本次候选或原像时执行，发现第三方变化即拒绝；新增 remote-device.js 可恢复为不存在。未知回执只执行 status，不能重复 deploy。

## 修正版激活：remote6 / app55 / CSS22

ZCode 最终 attempt4 冻结后重新独立审查：三处 WebRTC setup 异常（constructor、addTransceiver、createDataChannel）均由同一 try/catch 处理，固定阶段与白名单诊断可见、原始 message 不回显、close 仍只执行一次；attach 兜底也使用固定文案。此证明不扩大为所有 API catch 均已改造。独立三分支回归通过，定向 21/21、Web 全套 246/246 通过。暂停/恢复入口修复同时包含在本次 app55。

| 文件 | 此次修正版激活时的 SHA-256 |
|---|---|
| `web/remote-device.js` | `9086adb692f09632f4021ece682d714c09a3227aad50cad6bcc0b1bacf127874` |
| `web/pajio.css` | `dd5c280cc115c405b3fa657373c00e31d444283139fd6a2bcbbf23106288cdac` |
| `web/app.js` | `0e65cd2a3ce653deae557f2c34f67e836d0eb791bdb5b838f36bf2c381d890fc` |
| `web/index.html` | `cea1ce0bc89e871c0a9a805ef0be70c9b61d4f4259c5e5dc203cfd4da6651301` |

| 目标 | UTC 部署时间 | 未变更的 Python 服务 PID |
|---|---|---:|
| core-b | 2026-10-10T04:06:06.308395+00:00 | 13307 |
| core-a | 2026-10-10T04:07:06.505593+00:00 | 4285 |

B 与 A 的 inspect 原像均与 v4 冻结哈希一致；B 完成 deploy/status 和公网校验后才执行 A。最终两租户分别验证：认证首页及三资源均 200，四个正文 SHA 精确匹配上表，引用 remote-device.js?v=6 / app.js?v=55 / pajio.css?v=22；API status 均为 200。匿名首页仍 303、匿名资源仍 401、官方 IdP 登录表单为 200；Cache-Control 保持 private, no-store。

没有重启 Python 服务，没有操作设备或 GUI，没有提交第三方登录表单。测试账号登录仅通过既有 bearer 首页建立内存 cookie，未落盘凭据。该验证仍不是 WKWebView 实流或原生 App 文件交互验收。

独立私有目录为 `.wearing/on-prem/20261009/personal-compute/web-static-v5-20261010/`；目录中的 v5 是提前准备的部署 attempt 名称，实际 remote-device 资源版本为 6。正式 manifest、不可覆盖 intent、原像备份、deploy/status 和 HTTP 证明独立保留；共享远端锁与旧版一致。

该四文件 attempt 的回滚入口是其目录中的 `python3 -I web-overlay.py core-a rollback` 或对应 core-b，恢复到本次 inspect 的 v4 原像。执行前必须先处理下述更新的单文件 attempt；若确需回到 v4 之前，再核对并使用旧目录回滚，不能直接覆盖第三方变化。

修正版原像备份：
- core-b: `/var/backups/pajio-web-v5/core-b-578c4cf1703547eeb825ee2284a196ad`
- core-a: `/var/backups/pajio-web-v5/core-a-3aafd98f234745868bc862c7bc5a965f`

`web-static-final-summary.json` 汇总证据 SHA：`51f4ce6a4a765440701bd7689266f74902e57ee2b3ac4e96635915d54a683259`。

## 后续单文件修正：index.html 换行

ZCode 将 `decisions.js?v=5` 与 `data-exports.js?v=3` 两个 script 标签之间的字面 `\n` 改成真实 LF。独立复核把该唯一 LF 还原为两个字符后，全文 SHA 精确恢复到前述 `cea1ce0b…`，因此这次内容差异仅为该换行；remote-device.js、app.js、pajio.css 的完整 SHA 均保持上表值。此次换行修正的 index.html SHA 为 `053abe67abbfd24236fa1565c903fa444a60145086f5e39150ed8c4537286d11`。

本次复用已审查 overlay，仅把本地与远程固定写入清单收窄为 `web/index.html`，采用新的 release、独立目录、唯一 intent 和备份，仍使用共享 `/var/lock/pajio-web-v4.lock`。10 项离线守卫测试通过，包括单文件范围、原像变化拒绝、替换后故障回滚、未知回执不重投与旧 intent 不覆盖。原部署记录均保留。

在另一任务完成 Core 版本激活并明确释放窗口后，按 B→A 执行；此处的 PID 与前一表不同，来自那次独立 Core 激活，**本次静态更新没有重启服务**。

| 目标 | UTC 部署时间 | 本次静态更新前后不变的 Core PID | 结果 |
| --- | --- | ---: | --- |
| core-b | 2026-10-10T04:24:34.182008+00:00 | 14640 | inspect 原像匹配、deploy/status 为 deployed、公网校验通过 |
| core-a | 2026-10-10T04:25:38.066625+00:00 | 5886 | B 校验后才部署；相同原像与回执检查通过 |

最终 A/B 认证首页的响应正文 SHA 均为新 index.html 摘要；三个静态资源 HTTP 200、正文 SHA 未变，引用仍为 remote6 / app55 / CSS22。认证 API status 为 200；匿名首页 303、匿名资源 401、官方 IdP 登录表单 200，private/no-store 保留。没有操作 GUI、设备或重启 Python；本段仅记录静态 HTTP 验收。

私有证据目录：`.wearing/on-prem/20261009/personal-compute/web-index-newline-20261010/`。`summary.json` SHA 为 `1fa3f4401ab950869efd0e65322622f2ce7a520a081edc7bef4e19e2cc79b654`，其中索引单文件 manifest、差异、inspect/intent/deploy/status、离线测试和 HTTP 证明。

本次原像备份：

- core-b：`/var/backups/pajio-web-index-newline-20261010/core-b-e117a5e112ee49b381a3f1532c481bbb`
- core-a：`/var/backups/pajio-web-index-newline-20261010/core-a-25676bed25454ae4a6c9431dfab9e368`

需要回到此次换行修正之前时，须先回滚下述较新的 app58 attempt，再在本次单文件证据目录执行 `python3 -I web-overlay.py core-a rollback` 或对应 core-b；它仅把 index.html 恢复为 `cea1ce0b…`，不改三个资源。之后才可按前文依次回滚四文件修正版与 v4。任何未知部署结果只查询 status，不重复 deploy；发现非本次候选或原像的文件变化则拒绝覆盖。

## app58：私密暂停后的显式交还与异步快照

Web/Desktop 开发已由 root 接手。root 在当前候选中补齐私密暂停后的“查看并交还”分派，并修正异步期间可变按钮数据、身份和设备代次的检查。独立审查确认：操作前冻结 resource、generation、paused/pending、kind、identity/epoch；读取 access 后和发起动作前都重新核对。`supported` 必须为明确布尔，只有 `supported:false` 的旧设备走普通恢复；私密 paused/human_private 打开明确交还面板，瞬态和未知状态不发恢复请求。

15 项独立回归由实际生产渲染生成按钮数据，并注册生产 click/chat 处理函数，覆盖身份、代次、设备移除/类型变化及 dataset 在 await 期间改变；DOM、busy 和网络仍为测试替身，不将其写成浏览器操作验收。root 全 Web 回归 256/256 通过，独立双文件 overlay 守卫 10/10 通过。

| 本次写入文件 | SHA-256 |
| --- | --- |
| `web/app.js` | `fec56f2e069916c21e38febdbb0cf621ad59d8964b52deaa7a1367f640f084c4` |
| `web/index.html` | `132e683a5b98b33ff6457eed4e5baced1a03159b56848e61f13b17e79e32a53b` |

remote-device.js 保持 `9086adb6…`，pajio.css 保持 `dd5c280c…`，完整摘要同前表。两站实际 inspect 原像均为 app `0e65cd2a…`、index `053abe67…`。新 attempt 只写 app/index，app 先、index 后；两文件分别原子替换，不声称组合更新原子。B deploy/status 与 HTTP 验证通过后才部署 A。

| 目标 | UTC 部署时间 | 未变更的 Core PID | 结果 |
| --- | --- | ---: | --- |
| core-b | 2026-10-10T04:53:15.358217+00:00 | 14640 | deployed + status + HTTP 校验通过 |
| core-a | 2026-10-10T04:54:11.962593+00:00 | 5886 | deployed + status + HTTP 校验通过 |

最终两账户认证 HTML/app 正文 SHA 与新清单一致；remote/CSS 正文 SHA 未变，引用精确为 app58 / remote6 / CSS22，四资源均 200，API status 均 200。匿名首页仍 303、匿名资源 401、官方 IdP 登录表单 200，private/no-store 保留。部署过程未重启任何服务、未操作设备控制状态、GUI 或媒体。已打开页面需重新加载才使用新版本；本段不宣称 app58 的真实 UI 已复验。

独立私有目录为 `.wearing/on-prem/20261009/personal-compute/web-control-return-v58-20261010/`。`summary.json` SHA：`1c8ecbe007b9ca548cce77c45272d42f06fda2ff33cc625afaeac2a8ce2e3a90`，包含 manifest、审查、两套测试、唯一 intent、inspect/deploy/status 与 HTTP 证明摘要。它沿用共享远端锁，保留全部此前 attempt。

原像备份：

- core-b：`/var/backups/pajio-web-control-return-v58-20261010/core-b-676a686bb69c415a92a442997df38ec1`
- core-a：`/var/backups/pajio-web-control-return-v58-20261010/core-a-e4de2c50ff6e46b1b33db37d5d539095`

当前回滚入口是该 app58 目录的 `python3 -I web-overlay.py core-a rollback` 或对应 core-b，精确恢复 app55 与换行修正后的 index。需要更早版本时，先完成此回滚，再按换行 attempt、四文件修正版、v4 的逆序逐层核对；未知结果只查 status，不重投 deploy。
