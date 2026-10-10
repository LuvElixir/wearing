# Pajio App 邀请码入口适配

日期：2026-10-10。范围仅 `clients/mobile`；未改 gateway、Web 或桌面客户端，未部署、构建安装包或推送。

本文记录移动端源码阶段。后续构建、真实 iOS 系统登录及发布结果见 [联合发布验收](pajio-invitation-release-2026-10-10.md)，以下阶段性限制不代表最终发布状态。

## 正式用户流程

- 未登录的 iOS / Android App 显示睡衣小熊、Pajio 字标、“使用邀请码加入”和“已有账号，登录”。正式入口没有地址、endpoint 或 token 表单，也不先展示业务导航。
- App 登录始终以 `https://pajio.luckyloading.com/` 为 origin。邀请码入口调用 `/auth/mobile/start?challenge=…&state=…&entry=invite`；已有账号维持原来的 `/auth/mobile/start?challenge=…&state=…`。
- 邀请码由 gateway 的系统浏览器页面接收；App 不接收、存储或拼接邀请码，不自造 return URL。原有 `pajio://auth` 回调、PKCE、state、一次性 exchange 和 SecureStore 流程保留。
- “账户与身份”只提供账号登录管理与服务返回的身份选择。未认证时同步 handler 不执行 bootstrap、草稿发送或业务快照请求。

## 服务与凭据隔离

- 正式 native 构建只恢复官方 origin。旧非官方连接会选择无凭据的官方入口；选择发生在读取 SecureStore bearer 之前。
- 旧服务的草稿、记录及原来的 vault 项没有被迁移或删除。它们仍留在原隔离 scope，不能作为新官方账户的待同步内容。
- 非官方 native 激活和旧 PKCE continuation 的 exchange 在正式构建中被拒绝。没有放宽 HTTPS、回调来源、租户 header、身份与账户隔离或重放控制。
- 自定义连接和 LAN 配对同时要求 `__DEV__ === true` 与显式构建开关 `EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS=true`。仅 EAS `development` profile 配置该开关；`preview` / `production` 不启用。
- `/connect` 路由在普通构建只显示返回登录入口，不解析或展示开发连接凭据。运行本地开发验收时，需要显式设置上述环境变量并使用 dev runtime。

## 验证

- 已读取 `clients/mobile/AGENTS.md` 与实际 `expo ~57.0.26` 版本，核对 [Expo 57 文档](https://docs.expo.dev/versions/v57.0.0/)、[文档索引](https://docs.expo.dev/llms.txt)、[WebBrowser](https://docs.expo.dev/versions/v57.0.0/sdk/webbrowser/) 和 [SecureStore](https://docs.expo.dev/versions/v57.0.0/sdk/securestore/)。
- `npm run typecheck`：通过。
- `node node_modules/eslint/bin/eslint.js src`：通过。
- `node --import tsx --test --test-reporter=dot src/*.test.ts`：完整移动端测试通过。随后把来源选择提前到 vault 读取之前，并补充恢复测试，最终相关 31 项通过；没有更改其他业务行为。
- 回归覆盖：邀请码固定 selector、已有登录兼容、PKCE / callback / 重复调用、正式 / 开发双门、仿冒 origin、官方账号保留、旧 origin 零 bearer 读取、隔离草稿不迁移、未登录不发请求、外部 origin 激活不改当前账户、原捕获与账号注销竞态。
- `git diff --check -- clients/mobile`：通过。

环境限制：`npm run lint` 的 Expo 包装命令被本机全局 `npx-cli.js` 的 ESM 配置错误阻断，因此改用项目自带 ESLint 直接 lint `src`；没有修改全局 npm。额外尝试对整个目录 lint 会误包含旧 `dist-*` 生成包及既有 CJS 插件问题，其结果不属于本次源码检查。

尚未宣称通过：新的 gateway 邀请码链路部署后的真实 App 系统浏览器往返、真实邀请码领取、取消后重试及物理 iPhone / Android 安装包验收。以上是代码与自动化测试证据。
