# Web onboarding 独立回归复核

- 最终运行时间（UTC）：2026-10-08T18:47:16+00:00 至 2026-10-08T18:47:17+00:00。
- 执行环境：Node.js v24.16.0；本机工作区 `/Users/archieliew/Documents/facet`。
- 最终结果：Web Node 套件 200/200 通过；独立行为回归 14/14 通过，均为 0 失败、0 跳过。
- 审查边界：只读 Web 实现。仅维护本报告、完整测试日志和独立审查脚本证据，未编辑 Web/App 产品代码。

## 最终运行与可重复执行

在 ghost panel CSS 与父设置对话框交接修复均落地后，重新运行两套测试。相关源文件运行前后 SHA-256 一致。

```sh
node --test --test-reporter=tap tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs
PAJIO_REVIEW_ROOT=/Users/archieliew/Documents/facet node --test --test-reporter=tap docs/evidence/pajio-onboarding-20261009/independent-web-review.cjs
```

本次直接执行 evidence 目录中的独立脚本。完整原始 TAP 输出、展开后的命令、退出码、时间及源码哈希保存在同目录 [web-tests-final.log](web-tests-final.log)。

| 套件 | Tests | Pass | Fail | Skipped | 退出码 | 耗时 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 全 Web Node 测试 | 200 | 200 | 0 | 0 | 0 | 778.297583 ms |
| 独立 onboarding VM 回归 | 14 | 14 | 0 | 0 | 0 | 411.833042 ms |

## 验证范围

| 场景 | 本次验证结果 |
| --- | --- |
| 任意多选顺序 | 通过：角色、应用、兴趣按语义匹配成功回执 |
| 未知保存后恢复 | 通过：从 pending.body 恢复原始请求、步骤和选择，可以渲染 |
| 持久化失败 | 通过：不发送 POST，不声称选择已安全保存 |
| 冲突检查点 | 通过：解决冲突以 fresh revision 保存，重载不再次误报 |
| 晚回执后的旧 GET | 通过：保留精确请求，允许重试 |
| 同 revision 不同内容 | 通过：保留精确请求，不吞掉冲突 |
| 回复单选 | 通过：其他长度及语气可直接换选 |
| 非聊天入口 | 通过：指定 memory 入口不被自动引导覆盖 |
| 飞书撤销中 | 通过：不再显示已连接成功 |
| 注销冻结 | 通过：禁止新 onboarding 写入与 POST |
| 注销清理 | 通过：删除当前账户两类 journal，保留另一账户 |
| 身份切换 | 通过：释放旧忙态，旧请求 catch/finally 不污染新身份 |
| 确认页读取飞书状态 | 通过：只读查询不使保存忙态卡住 |
| 保存中关闭再打开 | 通过：恢复仍可操作，旧回执不造成 busy 卡死 |

## 静态接线复核

- `onboarding.js` 将面板会话围栏与 load/save/feishu 操作票据分开，避免来源查询使保存收尾失效；reset 清除忙态。
- `account-deletion.js` 在当前账户作用域前缀内识别两类 onboarding journal。真实 scoped-store 与清理函数已由独立脚本加载验证。
- `app.js` 初始化在 `openFromLink` 和 `activity_task` 处理之后调用自动引导；`maybeOffer` 也检查显式恢复参数、非聊天页面和已打开对话框。此处包含静态复核，不是实际浏览器路由测试。

- 最终 `pajio.css` 的布局规则使用 `.ob-panel[open]`，不再对关闭的 dialog 强制 `display:flex`；`index.html` 资源版本与最终文件哈希一并记录。此项仅为静态核验，ghost panel 的实际消失须以真实 UI 记录为准。

- 最后面板交接修复已只读核对：点击 `#onboarding-entry` 时先检查并关闭已打开的 `settings-panel`，再调用引导 `open()`；这项新增行为回归随 200 项 Web 套件通过。最终入口资源为 `onboarding.js?v=7` 与 `pajio.css?v=18`。

## 证据限度

这些测试运行真实 onboarding、scoped-store 和 account-deletion 源码，但使用内存存储、模拟 DOM 与 API，并模拟 app.js 的身份 epoch 围栏。证明的是所列状态转换与故障恢复行为，不能替代真实浏览器/桌面 UI 验收。

本报告没有操作真实用户账户、进行真实飞书 OAuth、读取外部正文或测试安装包。root 另行记录的桌面实际保存验收不计入本报告的 VM 证明。实际 UI、键盘与读屏行为、授权回跳及桌面构建应以独立的真实界面验收记录为准。测试通过也不代表新手引导价值或市场效果已验证。

## 最终源码 SHA-256

以下文件在最终两套测试开始前与结束后分别读取哈希，前后完全一致；绑定此次复核所见工作树。后续修改需要重新核验。

| 文件 | SHA-256 |
| --- | --- |
| `src/wearing/web/onboarding.js` | `6796b82eb72352b740357b2f919041ab29e7a299c9054612113b89f849b4ab1e` |
| `src/wearing/web/scoped-store.js` | `9d9fdcffd3548fd4eecd804bae64d917580403a0afec403bc7fbee2f1175caca` |
| `src/wearing/web/account-deletion.js` | `fa9e743b6b42ddef5b6078b41e516b509680147e4b25a00e892c6a5da9e664af` |
| `src/wearing/web/app.js` | `605802f9cb2c1814955d9e13bcc3c41217f524ac0934108a441719aff9eff949` |
| `src/wearing/web/index.html` | `65aa223f8dee00d88ede783d487f13ae79a1aa11e8025f4cbe4a5eaa74ad1e9c` |
| `src/wearing/web/pajio.css` | `851674fb0a8d722f0c204642358e137af8f59add6241febae7ae3a0961554039` |
| `src/wearing/web/life.js` | `f4313e2a0f247e0070491f1760a87c98609344553e80e6b4dde71c25bce8bea4` |
| `docs/evidence/pajio-onboarding-20261009/independent-web-review.cjs` | `b77eaac88f4b9cac4163318141d56e194a8d9ae653e2fbb3d28eb984df9521f2` |
