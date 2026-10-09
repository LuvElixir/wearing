# Pajio 首次认识流程：本轮验收记录

2026-10-09，Asia/Shanghai。本轮完成原生 App 与共享后端的首次认识流程，并在合成 QA 环境完成 iPhone Air 模拟器点击验收。独立复核后的飞书连接状态补修已通过 695 项 App 回归；包含补修的 iOS / Android 均重新构建成功，Android 最终包已核验，iOS 最终包已安装并重新启动检查。Android 尚未安装到真实设备。Web / Desktop 由 ZCode 依据 App 和冻结接口实现；最后补修后通过 200 项 Web 回归与 14 项独立检查，root 在独立桌面 QA 实例完成保存、跳转与退出复验。此结论限于本轮引导功能，不代表整个产品、真实第三方授权或外部分发已经验收。

产品判断与待验证假设见 [设计方案](../../plans/pajio-onboarding-2026-10-09.md)，状态、枚举与安全边界见 [API 契约](../pajio-core-20261007/onboarding-contract.md)，Web / Desktop 工作范围见 [ZCode 交接](zcode-handoff.md)。

## 交付范围

原生流程为：见个面 → 日常角色 → 常用应用 → 兴趣与表达 → 可选资料连接 → 核对并确认。全部选择可留空，没有必填文字输入，不要求用户先说明目标。可返回、稍后继续、跳过、恢复草稿，并可从“我的”重开。

保存的是用户明确点选的有限枚举。常用微信或飞书等选项不代表应用已连接；偏好不代表人格、长期目标或行动授权。只有完成确认的资料进入后续任务上下文，草稿不生效。首登保存不自动调用模型、创建任务、启用通知或打开定时简报。

本轮复用现有日夜主题、睡衣熊和真实连接能力，没有把更换睡衣变成信息采集条件。日历来源和飞书未连接分支可直接继续，不要求授权才能进入产品。

后续独立复核发现飞书存在 `revocation_pending=true` 与 `state=connected` 同时出现时，界面仍显示成功文案的问题。补修统一采用“原授权正在撤销”优先级，并阻止此时发起新授权；确认页和来源分支保持同一语义。涉及 `OnboardingConnections.tsx`、`onboarding-connection-state.ts` 及其测试，新增两项回归。此前截图和 revision 3 保存结果仍属于有效历史观察，但没有覆盖这个撤销中的分支。

## 自动化与构建

| 检查 | 结果 | 证据与范围 |
| --- | --- | --- |
| App 全量测试 | 补修后 695 / 695 通过，0 失败、0 跳过 | [补修后日志](app-tests-final.log)；保留 [补修前 693 项日志](app-tests.log)。测试覆盖本轮与既有 App 回归，不等于 695 个原生交互用例 |
| 后端有界回归 | 125 通过，3.40 秒 | 本轮执行结果和准确命令已记入 [API 契约](../pajio-core-20261007/onboarding-contract.md#verification) |
| TypeScript 与 lint | 补修后通过，相关测试 16 项通过 | 最终全量回归另见上行；先前候选的类型 / lint 日志保留在测试包目录，不能替代新版安装包证据 |
| iOS Release 模拟器构建 | 补修后 `BUILD SUCCEEDED`，安装 exit 0 | 本次重新构建日志 `/private/tmp/pajio-onboarding-ios-build-final-20261009.log`；02:11 CUA 重新启动及只读冒烟通过 |
| Android ARM64 Release 构建 | 补修后 `BUILD SUCCESSFUL` | 新包 `0ce1a572…1b65fca76`；类型、ESLint、候选内引导测试 13 项及包校验通过 |
| 候选源码一致性 | 补修后 iOS、Android 清单均 281 项，差异 0 | 两份清单逐项重算 SHA-256，与当前 `clients/mobile/src` 一致；包含源代码及测试文件 |
| Web 回归 | 最后补修后 200 / 200 通过 | [最终日志](web-tests-final.log)，包含设置面板交接与关闭态显示回归 |
| Web 独立检查 | 14 / 14 通过 | [独立报告](independent-web-review.md)，内存 DOM / API 故障场景；运行前后源码哈希一致 |

App 测试脚本是 `tsx --test src/*.test.ts`。保存的日志尾部为：

```text
tests 695
pass 695
fail 0
cancelled 0
skipped 0
todo 0
duration_ms 5777.681791
```

后端回归命令：

```sh
.venv/bin/python -m pytest -q tests/test_onboarding.py tests/test_onboarding_independent_review.py tests/test_briefings.py tests/test_briefing_preferences.py tests/test_briefing_automation.py tests/test_briefing_automation_review.py tests/test_briefing_automation_export_review.py tests/test_identity_export.py tests/test_identity_export_documents.py tests/test_task_list_data_lifecycle.py
```

后端覆盖严格枚举及类型、账户与身份隔离、CAS 冲突、重复请求、跳过后的晚回执、已完成资料取消编辑、老账户识别、真实路由的认证/CSRF、简报优先级，以及合成私有租户主目录、索引、备份的实际删除。独立复核还通过真实 TaskService 到 mock 模型传输的路径，验证任务可信 owner 与资料一致，以及导出不泄漏其他 owner 或内部请求日志。这些测试未调用真实模型供应商。

候选的 `npm run lint` 包装器曾受本机全局 npm 的 ESM / `require` 冲突影响而失败；改用候选内 `./node_modules/.bin/eslint src` 通过。未修改全局 npm 安装。此处不把包装器失败记为通过。

## iOS 原生验收

环境：iPhone Air 模拟器、合成 QA 服务 `127.0.0.1:8891`、身份 `qa`。以下流程由 root 在飞书撤销状态补修前的 Release 候选上通过 CUA 执行；PNG 与 JSON 是其中保留下来的观察点，并非每一步的完整录像。补修后安装与只读冒烟另记于表后。

| 操作 | 实际观察 |
| --- | --- |
| 已用账户启动 | 不自动强弹引导；可从“我的”主动进入 |
| 首次跳过 | 保存为 `skipped`、空数组与 null，revision 1 |
| 点选并中断 | 选择 `employed`、`business` 与 `wechat`、`feishu`，关闭后重开恢复草稿 |
| 继续选择 | 兴趣为 `design`、`reading`，详略为 `brief`，语气为 `warm` |
| 可选连接分支 | 原生日历显示尚未申请权限的状态；飞书显示未授权状态。本轮没有实际申请或授予权限 |
| 第一次完成 | 确认后进入“今天”；GET 读回 `completed`、step 5、revision 2，与页面选择一致 |
| 浅色 / 深色 | 确认页两套主题可读，见 [浅色](confirm-day.png) 与 [深色](confirm-night.png)。两张截图滚动位置不同 |
| 长页面 | CUA 的原生 AX 滚动可用，底部操作仍可到达 |
| 已完成资料取消编辑 | 将 `brief` 在本机改为 `detailed` 后退出；服务端仍为 revision 2、`brief`，未将未确认编辑覆盖生效资料 |
| 最终候选安装与重启 | 安装成功；重启后老账户仍不强弹。从“我的”重开恢复本机 `detailed` 草稿 |
| 最终确认 | 改回 `brief`；AX 核对表达样例为“我们可以一起确认时间，再整理要准备的材料。”。继续 [资料步骤](connections-day-final.png) 与核对步骤、确认进入“今天”，GET 为 revision 3，值精确一致 |

补修后最终 iOS 安装命令 exit 0。02:11（Asia/Shanghai），root 通过 CUA 从更新后的 Pajio 图标重新启动：已用账号仍不强制弹引导；进入“我的 → 初始偏好”显示 6/6 核对页，角色、应用、兴趣、简短 / 温和选择均为已保存值；本机来源未启用、飞书尚未连接显示真实；点击“稍后继续”正常退回“我的”。这次是更新后的启动与只读冒烟，没有重做真实授权，也没有再次提交完成快照。撤销中与已连接冲突分支由新增自动化用例验证，本轮未通过真实飞书撤权制造该状态。

第一次完成的接口证据为 [native-saved-profile.json](native-saved-profile.json)，最后一次确认是 [native-saved-profile-final.json](native-saved-profile-final.json)：

```json
{
  "schema": 1,
  "identity_id": "qa",
  "revision": 3,
  "status": "completed",
  "step": 5,
  "values": {
    "roles": ["employed", "business"],
    "apps": ["wechat", "feishu"],
    "interests": ["design", "reading"],
    "reply_detail": "brief",
    "reply_tone": "warm"
  },
  "source": "self_selected",
  "confirmed_at": "2026-10-08T17:50:11.415600+00:00",
  "updated_at": "2026-10-08T17:50:11.415600+00:00",
  "recommend_onboarding": false
}
```

JSON 时间为 UTC，对应本地 2026-10-09 01:50。revision 3 是最终再次确认产生的新版本；此前退出编辑仍保持 revision 2 的测试是独立的取消保存检查。

补修后的表达选择页于 02:22 重新截图，见 [最终表达选项](expression-day-final.png)：兴趣与简短 / 温和选中态可见，完整样例文案另由原生 AX 核对；当前截图的样例下半段在可滚动区域下方，不能用此图单独证明完整样例显示。此前 01:49 截图实际为资料连接页，已更正命名为 `connections-day-final.png`，未将它当作表达页证据。

新空账户自动推荐、账户切换、未知请求结果、冲突与晚回执等分支有自动化覆盖；本轮 CUA 使用既有合成身份，没有清空其数据冒充全新注册。屏幕阅读语义参与 CUA 定位，但未完成独立 VoiceOver 用户测试、全部动态字号或全部设备尺寸的可访问性验收。

## Web 与桌面独立复验

Web / Desktop 代码由 ZCode 实施，root 与独立复核者负责检查和补验。当前资源版本为 onboarding.js v7、account-deletion.js v7、app.js v51、pajio.css v18。浏览器实际未知保存结果恢复、409 冲突处理、单选切换等结果与未验范围见 [ZCode 交付](zcode-delivery.md)；独立 14 项检查不冒充真实浏览器或桌面操作。

桌面使用独立 identifier `io.luckyloading.pajio.desktop.onboardingqa20261009`、独立数据目录 `/tmp/pajio-desktop-qa-data-20261009`，只连接合成服务 8891。root 于本地 02:38 左右通过 CUA 实际点击确认，GET 核实 revision 13→14、completed 且全部值与基线一致，记录为 [第一次桌面保存](desktop-saved-profile.json)。该次发现原设置面板仍遮挡已打开的“今天”，交由 ZCode 修复。

02:48，root 重开独立桌面实例加载 v7：设置→初始偏好只显示一个引导面板；点击“确认并进入 Pajio”后直接显示“今天”，没有旧设置面板遮挡；GET 核实 revision 14→15、completed、基线值保持一致，记录为 [最终桌面保存](desktop-saved-profile-final.json)。随后从设置重开已保存的 6/6 摘要，点击关闭正常回到“今天”，无残留模态。桌面窗口标题为 Pajio，URL 与 AX 身份均确认为 QA。操作截图与 AX 观察保留在当前任务工具记录，没有把浏览器截图标为桌面证据。

该桌面验证没有连接真实日历或飞书，也没有发送模型任务。WKWebView 模态时 AX 树不完整，root 通过新鲜截图的实际像素坐标完成操作，因此不能从这次成功推导读屏或完整键盘路径已经通过。

## 安装产物

### iOS

补修后已成功构建、安装并启动的 App 位于：

```text
/var/folders/32/vzdw9zp96ps4lgrqy7rz55cw0000gn/T/pajio-native-candidate-veejd0vv/ios-simulator-derived-data/Build/Products/Release-iphonesimulator/Pajio.app
```

这是模拟器 Release 产物，使用临时签名；不是可给外部 iPhone 安装的分发包，也不是 TestFlight 交付。更新后的 281 项候选源码记录在 [ios-source-manifest.json](ios-source-manifest.json)，最终构建日志已确认 `BUILD SUCCEEDED`，安装 exit 0，更新后启动与只读冒烟通过。

### Android

已包含飞书撤销状态补修的最终测试包：

```text
/Users/archieliew/Downloads/Pajio-test-20261009/Pajio-0.2.0-arm64-standalone-test.apk
```

- 68,174,658 字节；实际重新计算 SHA-256：`0ce1a572ca4fff91e3f8dbd2c643999c85d8ec1dba728897ba2d1801b65fca76`。
- Pajio 0.2.0，versionCode 1；保留包名 `io.luckyloading.wearing.mobile` 以保持现有安装与数据兼容。
- ARM64，最低 Android API 24、target API 36；Release 构建使用 Android Debug 测试签名，不是正式商店分发签名。
- APK v2 签名验证通过；ZIP 16 KB 对齐通过，25 个原生库的 ELF 装载段对齐检查通过。
- 内置 Hermes JavaScript 运行时 bundle，与 Gradle 输出一致，不依赖 Metro。Agent 服务仍需要后端连接。
- `debuggable=false`、`allowBackup=false`、`usesCleartextTraffic=false`；既有 loopback HTTP 例外未改变。
- `adb devices` 没有已连接设备，因此本轮没有安装或验收这份 APK 的 Android 真机行为。

测试包同目录保存 `README.md`、`build-verification.json`、`android-source-manifest.json`、准确构建命令、签名/对齐/包信息/类型/lint/Gradle 日志。上一日的包未被覆盖。

这份最终包包含 281 项源文件，对应源码无差异；最终 bundle SHA-256 为 `7daabd74525f51b1f2cfdd786374097166067db66e671ab4360cb6b5c369527e`。候选内 13 项引导测试、TypeScript 与 ESLint 均通过。旧包的 68,168,758 字节与哈希 `bca4018317b7d038ca1d1a54114c30c6a9d2a5639413be2f4faf51365a9074fa` 仅作历史记录，已不作为最终交付。

## 证据完整性与未验范围

补修后 [App 全量日志](app-tests-final.log) SHA-256 为 `abb13ab88dafcb8dee54f6ceef0088231767495098bb701f96c93933b3d61797`（67,286 字节），与 `/tmp/pajio-onboarding-app-tests-final-20261009.log` 一致。补修后 iOS / Android 清单各 281 项，与当前源码逐项匹配。最终 iOS 构建日志 SHA-256 为 `cceacea97145284dfaa3688cd2e7691e9a01a943e00b360b958a4887f1793118`（679,843 字节）。

历史证据保留：补修前 [App 日志](app-tests.log) SHA-256 为 `a482e6d396a0a1cffa09b0299a59ac6318770319caa66517a1dfdd9e1de21916`（66,968 字节）；补修前 iOS 构建日志 SHA-256 为 `dd5c1c71bb63c89f9c178c933a48ecdd4a2e3187a30e30bc9c646ccaac9a75b7`（677,844 字节）。当时两端各 279 项清单核对通过，不将旧清单描述为补修后的源码。

本轮没有向生产服务 8765 写入业务数据或重启其后端，没有操作真实账户数据或授予第三方权限，没有实际模型调用、消息推送、Git push、部署或对外发布。ZCode 曾观察生产桌面前端的关闭态面板问题；该前端读取共享工作树，不能把本轮描述为“从未接触生产桌面界面”。正式验收使用隔离 8891 实例。原生授权成功后的真实数据同步、供应商模型对画像的使用质量、Android 真机、新 iPhone 注册全流程与外部分发仍需各自验收。

90 秒是设计预算，本轮没有计时用户实验。完成率、授权意愿、首次回答质量、补问减少、画像纠正率与留存均未获得真实用户验证。[设计方案的首轮观察办法](../../plans/pajio-onboarding-2026-10-09.md#首轮观察办法) 已具体化为 6–8 位非设计参与者、每人最多 15 分钟的形成性测试，观察选择理解、连接是否有真实资料与首次任务价值；这一规模用于发现问题，不能估算市场完成率或留存。不能从测试通过、界面完成或模拟器可用推导出“市场验证”。
