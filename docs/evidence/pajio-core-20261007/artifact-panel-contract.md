# App 图文成果闭环

2026-10-08（Asia/Shanghai）。本文件记录实现与验证，不代表已完成真机验收。

## 原生集成

```tsx
<ArtifactPanel
  connection={connection}
  artifactId={artifactId}
  onBack={goBack}
  onTask={openTask}
  onArtifact={openArtifact}
/>
```

`onTask`、`onArtifact` 可选；分别打开来源任务、上一版成果。组件按服务地址、用户、租户、身份与成果 ID 重挂载。父层提供滚动容器，组件内预览有固定可视高度及独立滚动。生成入口由 BriefPanel/任务结果负责，本组件打开与重试只读取。

## 协议

- 原生 GET `/api/artifacts/{id}`：验证 ID、任务 ID、版本、时间、1 MiB 上限、SHA-256 和元信息。
- 原生 GET `/api/artifacts/{id}/preview`：验证 `text/html`、字节数、SHA-256、UTF-8 与完整 HTML。认证与当前身份仅发给原生传输；拒绝重定向。
- 保存/分享先重新 GET 元信息，确认仍是同一 ID、任务、版本、哈希，再 GET `/download` 并核验 `application/octet-stream` 原件字节。无自动重试，无修改、重建成果副作用。
- 分享使用私有随机缓存目录，系统面板只接收本地文件 URI；在下载与移交之间再次检查活动身份；面板结束或失败后清理临时原件。
- 没有 ExpoSharing 的旧安装版明确提示更新，不影响其他页面加载。取消系统分享不声称保存成功。

## 预览隔离

原生认证取回的 HTML 被放进 `sandbox="allow-scripts"` 的 `srcdoc` iframe，未授予同源、表单、下载、弹窗或顶层导航权限。文件内容使用与后端一致的 CSP 内容限制；由于 CSP meta 不支持 sandbox 指令，sandbox 由 iframe 属性强制。外层页面不包含服务 URL、令牌、注入脚本或 conversation bridge。

WebView 所有导航都进入 `onShouldStartLoadWithRequest`；只允许 `about:blank` 与子框架 `about:srcdoc`。`originWhitelist=['*']` 是为了避免 React Native WebView 在自定义回调前将不匹配白名单的链接交给系统 Linking，并不是授权外链。文件访问、通用文件 URL 访问、第三方 cookie、共享 cookie、DOM storage、弹窗、混合内容、定位与链接预览均关闭。

界面展示版本、保存时间、来源、假设、限制和核对状态。SHA 通过仅表示文件与保存回执一致，不冒充内容已核对。成果自身的设计保留在 iframe 内，App 外壳使用现有日夜主题 token。

## 验证

- `artifact-client.test.ts` 9 项 + `workspace-export.test.ts` 5 项通过：错误/越权 ID、收据字段、认证身份冻结、MIME/字节/哈希、UTF-8、只读重试、不可变版本、导航边界与身份切换期间禁止分享。
- `npm run typecheck` 通过；4 个新文件 scoped ESLint 通过。
- 独立 Playwright Chromium 会话 `art`，只读隔离 fixture `127.0.0.1:8892/preview`：`本地交互` 点击后为 `已交互`；父页面读取、`fetch` 外网、`window.open` 均被沙箱/CSP 拦截；请求记录只有两次本地 `/preview` GET。该临时预览服务与浏览器验证结束即关闭。
- 主 QA 服务仍为 `127.0.0.1:8891`；`/_qa/manifest` 与审计日志可用于 App 点击核对。未访问真实 `.wearing` 数据、账号或模型。

待父任务完成：iOS/Android 原生 WebView 的嵌套滚动、触控、进程恢复与系统分享面板验收。Chromium 沙箱验证不是这些设备行为的替代。
