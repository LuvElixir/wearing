# App 品牌与交互调整：工程验证

验证日期：2026-10-07（Asia/Shanghai）。本报告针对当前工作区源码；不包含发布、真实用户研究或真机验收。

## 结果

| 检查 | 结果 | 原始日志 |
| --- | --- | --- |
| TypeScript 全量检查 | 通过，退出码 0 | [typecheck.log](logs/typecheck.log) |
| ESLint，仅 `clients/mobile/src`，包含 `src/app` | 通过，退出码 0；未扫描 dist | [eslint-source.log](logs/eslint-source.log) |
| 移动端 `src/*.test.ts` | 164 项通过，0 失败 | [mobile-tests.log](logs/mobile-tests.log) |
| 四组 App-host / 输入桥 / 草稿测试 | 49 项通过，0 失败 | [host-tests.log](logs/host-tests.log) |
| iOS 静态导出 | 通过，3804 modules，1 份 6.8 MB Hermes bundle | [ios-export.log](logs/ios-export.log) |

导出目录：`/tmp/facet-brand-reset-ios-20261007`。源码关键文件和导出文件哈希分别见 [source-sha256.json](logs/source-sha256.json)、[export-sha256.json](logs/export-sha256.json)。这些哈希记录本次检查后的文件版本；后续代码改动需要重新判断对应验证是否仍有效。

## 可复现命令

以下前三条和 iOS 导出在 `clients/mobile` 执行；host 测试在仓库根目录执行。全程直接使用项目安装的 CLI，没有调用或修复全局 npx。

```sh
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js src
node --import tsx --test src/*.test.ts
node node_modules/expo/bin/cli export --platform ios --output-dir /tmp/facet-brand-reset-ios-20261007
```

```sh
node --test tests/mobile-host-ui.test.cjs tests/native-composer-ui.test.cjs tests/now-ui.test.cjs tests/conversation-drafts-ui.test.cjs
```

首次 ESLint 命令误写为 `src app`；项目实际路由目录是 `src/app`，因此额外的 `app` 参数未匹配文件。已改为 `src` 重跑并通过；[首次路径错误日志](logs/eslint-initial-path-error.log)保留。iOS 导出日志仅出现 `NO_COLOR` 与 `FORCE_COLOR` 同时设置的提示，没有构建失败。

## 本轮覆盖的行为

- `results` 是包含失败、停止、结案的 API 分组，App 不再把它等同于成功。未核对返回内容使用文件图标；失败提供“查看原因”，停止和结案提供“查看记录”；仅 `verified` 使用核对勾选。
- 待处理、进行中、排队优先于历史；过期或读取失败的紧凑进展入口优先显示旧状态提示，不用旧运行标题掩盖读取失败。
- Today 使用全量 `counts.attention`，已加载项目不足时明确提示，不把本页部分数据当作完整列表。无日历记录仅说明“没有已同步日程”，不推断用户有空或正在休息。
- 新用户默认跟随系统；已保存的浅色/深色选择保留；主题桥接只传受控枚举，不重新载入 WebView 或替换草稿。
- 助手形象支持单星和小熊；既有明确穿搭选择迁移保留，读取失败不会覆盖未知偏好，重复保存和跨身份结果被隔离。
- host 测试涵盖普通网页版不进入 App 展示模式、原生输入范围与重放、草稿恢复、原对话导航、读取失败以及 App 缩放边界。

## 只读兼容复核

1. **已确认源码保持原生主题联动。** `StatusBar` 随明暗模式切换，日期选择器使用当前主题；主要新页面从 `AppColors` 读取颜色。单星为单一 SVG Path，没有图片分辨率依赖，也没有添加原生模块。
2. **数值对比度检查通过。** 正文和次级正文已有测试覆盖浅色/深色主要表面。另复算主操作文本对比度：浅色 15.14:1、深色 14.05:1；按下态 11.06:1 / 11.57:1；强调、注意和错误文本均高于 4.5:1。`outline` 对表面的 4.27:1 / 4.42:1 高于控件轮廓常用的 3:1 门槛，它不作为正文色使用。见 [contrast-review.tsv](logs/contrast-review.tsv)。这些数值不证明长时间阅读舒适。
3. **动作降级路径仍在。** Native Entrance 与操作反馈读取 Reduce Motion，host 的媒体查询会关闭循环与进入动画。未通过本轮静态检查证明所有真实设备动画流畅。
4. **待改的触控尺寸。** `mobile-host.css` 中事件状态胶囊的最小高度仍为 34px，搜索上一项/下一项按钮仍为 36px，低于本轮 44pt 目标。它们是既有规则，本次验证没有改动；后续可在 App host 作用域内扩大触控区域。
5. **需原生实测的布局。** 大字和 VoiceOver、窄屏横向空间、键盘避让、系统外观动态切换、真实 iPhone 语音、长对话滚动，以及断网后返回的屏幕状态，本轮没有完成现场验收。iOS export 是打包成功，不是安装运行或服务连通的证明。
6. **保留资产仍占包体。** 八套可选小熊 PNG 仍随 App 打包；这是保留既有个性化选择的结果。导出日志可核对文件大小，未据此推断全部位图会同时解码或造成运行卡顿。

本次验证没有修改后端、API 协议、普通网页版界面，也没有启动任务、修改用户记录、发布或推送代码。

## 补充：Impeccable detector

2026-10-07 补齐一次手动 detector 检查。Impeccable context 显示本会话没有自动设计检查 hook，因此只对本轮 App 容器 CSS 执行一次；原生审查规范明确说明 `detect.mjs` 不适用于原生 TSX，未扩大到其他页面。

```sh
node /Users/archieliew/.agents/skills/impeccable/scripts/detect.mjs --json src/wearing/web/mobile-host.css
```

结果：退出码 **2**，共 **6 项 advisory**，没有更高严重级别条目，stderr 为空。完整输出见 [impeccable-detector.json](logs/impeccable-detector.json) 和 [stderr 日志](logs/impeccable-detector.stderr.log)。

| 类型 | CSS 行号 | 检出值 |
| --- | --- | --- |
| 圆角不在所选 DESIGN.md 标尺内 | 34 | 20px、6px |
| 字号不在所选 DESIGN.md 标尺内 | 44 | 32px |
| 圆角不在所选 DESIGN.md 标尺内 | 52 | 18px |
| 圆角不在所选 DESIGN.md 标尺内 | 60 | 999px |
| 字号不在所选 DESIGN.md 标尺内 | 61 | 18px |

该 CSS 的 context 解析到仓库根 `DESIGN.md`，而非本轮 App 的 `clients/mobile/DESIGN.md`；其提示是与根网页标尺的差异，不能据此认定 App 运行错误或宣称设计检查零问题。context 还提示根 `PRODUCT.md` 的 Platform 字段不是支持的枚举值，因而按 web 处理。按照本轮收尾边界，仅记录这六项建议与文档上下文偏差，没有调整样式、修改设计文档或抑制检查，也没有追加其他测试。
