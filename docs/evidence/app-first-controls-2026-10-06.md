# 关闭与展开控件、App 对话入口验收

日期：2026-10-06。仅开发与隔离 QA 环境。保留已有用户数据、品牌和模型配置，本轮没有启动云 VM 或消费模型额度。

## 实现

- `web/result-controls.css` 成为宿主和产物指引的同一控件来源。指引 v3 保留开放构图，提供输入、滑轨、关闭与折叠用法；视频仍只返回规划指引。
- 关闭为 44×44px 点击范围、30px 中性视觉面和 18px SVG；初始聚焦标题，键盘操作才出现关闭焦点环。修复宿主 `--rail:220px` 与颜色 token 冲突，关闭背景采用 `--control-rest`。
- 展开控件为原生 details/summary 与 16px 线条箭头，开合旋转 90 度，减少动态时取消过渡。
- `host=mobile` 精简网页导航；原生 Conversation 补加载、12 秒慢连接提示、错误重试、同源导航约束。未接系统分享或原生结果路由。

## 自动检查

| 检查 | 结果 |
| --- | --- |
| `pytest tests/test_artifacts.py -q` | 14 passed |
| `node --test tests/artifact-ui.test.cjs` | 1 passed |
| `node --check src/wearing/web/mobile-host.js` | 通过 |
| mobile `npm run typecheck` | 通过 |
| mobile `./node_modules/.bin/eslint src` | 通过 |
| mobile `npm test` | 17 passed；含原有同步/隔离测试，以及新增 App URL 与导航约束测试 |
| mobile `npm run export:android` | 导出成功；Android bundle 5.7 MB |
| mobile `npm run export:ios` | 导出成功；iOS bundle 5.4 MB |
| `git diff --check` | 通过 |

`npm run lint` 的 Expo 启动器被当前全局 npx 的 CommonJS/ESM 配置错误阻断；未修改全局 npm，改用项目本地 ESLint 检查源码。一次未限定目录的 ESLint 扫到了已有 dist-all 构建文件及 preview 脚本的既有 Buffer 规则问题，不记为全项目 lint 通过。

设计钩子的 4px 圆角提示经复核属于滑轨局部几何：轨道高度即 4px，圆角用于圆滑端点；DESIGN.md 已记录。保留其设计，不新增抑制规则。新 mobile-host 样式无确定性设计告警。

## 实际浏览器

使用隔离 QA 服务 `127.0.0.1:8789`，最新人工样板 v8：

- ID：`art_2af0ac64e3db4f45a691ad750109d84f`
- SHA-256：`3c095501e8da429ec29cf7b70dd7fba86c478bdc7b1d153a0951e54b2f5dd4f1`
- 桌面与 390×844 下内容可读；初始焦点为 artifact-title，关闭按钮实际 44×44px。
- Tab 可到关闭并显示局部焦点环；鼠标点击关闭后 dialog 关闭、焦点回到对应 v8 卡片。
- 展开依据后 native open=true，箭头最终变换为 matrix(0,1,-1,0,0,0)。内容可读，能收起。
- App 嵌入模式在 390px 下页面宽度与 viewport 一致，头部 52px，品牌和生活工具重复导航隐藏，文件/记忆/连接与输入区保留。这是浏览器 CSS 验证，不是原生 WebView 验证。

截图：

- [桌面](images/result-controls-desktop-20261006.png)
- [键盘焦点](images/result-controls-focus-20261006.png)
- [390px 结果](images/result-controls-mobile-20261006.png)
- [App 嵌入布局](images/mobile-host-layout-20261006.png)

## 未验证部分

ADB 只读确认小米 6X 在线，Android 9、WebView 74.0.3729.136、Expo Go 57.0.9。本轮未在手机界面执行 App 交互；iOS 也未真机验证。资源构建不是 APK/IPA，更不证明键盘、手势、生命周期与帧率已经达标。

仍缺原生对话/结果路由、草稿及滚动跨页面保留、系统返回、iOS 交互与签名分发。旧 WebView 的网页兼容性需要另行检查。现有产物记录的 render/content 保持 not_verified；本文件说明本轮人工样板验收范围，不代表未来模型输出自动达到同等质量。
