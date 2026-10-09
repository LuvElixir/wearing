# 返回后看懂进展 · 2026-10-06

## 本轮范围

导航：现在改圆环中心点，记忆改脑部线性轮廓，日历图标显示设备当天日期。保留标签、命中区域和轻量选中态；日期按当地午夜、App 回前台、网页可见/聚焦更新。`/experience` 已导出并在 390 × 844 浏览器检查：当天为 6，无横向溢出。

真实进展：ActivityBook 聚合已有任务与确认状态；版本化已读独立存储。网页入口、分组面板与原生 ActivityReview 使用相同 API。没有把已读当确认，没有增加执行或自动重跑动作。`completed_unverified` 显示“结果已返回”；运行摘要注明“上次记录”。`checked_at` 是读取时间。

## 自动化验证

- Python：`tests/test_activity.py` 28 条；与 lifecycle、goals、goal_updates、confirmations 合计 92 passed。同步 API handler 交给 FastAPI 线程池后，activity 28 条再次通过。
- Web：`tests/activity-ui.test.cjs` 15 条、`tests/now-ui.test.cjs` 8 条，共 23 passed。包含跨身份响应、先前点击晚返回、详情渲染倒序、已读与后台 GET 竞争、断网、原生跳转、无 app 全局变量的初始化。
- Mobile：typecheck、定向 ESLint、38 项 core/hold-voice 测试通过。iOS Metro/Hermes 资源导出通过（3751 modules，临时产物）。后续仅改读取时间文案和刷新状态，不改原生依赖。
- 日期 hook 的独立假时钟检查覆盖午夜、跨年、App/网页前台恢复、静态导出首次日期、23/25 小时 DST 与清理；7 场景通过。这是临时检查，不计为仓库持久测试。
- 同源预览代理实测 GET activity / POST seen、身份与 body 转发、错误方法拒绝、activity_task 深链重定向；不带消息正文。

## 实际浏览器过程

隔离服务 `127.0.0.1:8794`，独立数据库在 `.wearing/qa/product-standard-20261006`。Hermes 使用本机 MockTransport 合成回执；设备关闭。3 条内容明确标注“验收示例”：一条尚未送出、一条执行中、一条结果返回。QA 无租户 relay，因此测试夹具给 input-approvals 返回空列表，不改产品设备校验。

1. 初次 GET 的状态为 attention=1、active=1、results=1、unread=1；进展面板显示三组。
2. 关闭整个网页标签，再把合成执行回执改为 completed。后台轮询自行保存结果。
3. 新建标签回来显示 attention=1、active=0、results=2、unread=2；首页同时显示待处理与新结果。
4. 点新增结果卡，面板退出，焦点到正确的 `task-turn-89a5c944e1dc4374bbbce3f72708cd85`；随后 unread 变为 1。查看面板本身不清未读。
5. 停止并重启隔离服务，刷新后 unread 仍为 1；任务结果和已读未丢失。
6. 390px 手机宽度检查通过，无横向溢出；与桌面使用同一内容。

![手机导航与当天日期](images/ios-navigation-date-20261006.png)

![进展面板](images/activity-return-mobile-20261006.png)

## 尚未验证或交付

合成回执仅证明保存、恢复和回看链路，不证明旅行搜索或其他生活任务能力。本轮未调用真实模型、手机或外部服务，未恢复云 VM。原有 8765 服务未重启加载新后端路由，完整新后端通过隔离 8794 验收。新 App 体验页面仍为示例，原生真实进展是源码接入和导出证据；iPhone 真机、真实语音、推送、跨数小时确认与 TestFlight 不在已验收范围。

产品标准审视与后续优先项见 [产品审视](../plans/product-standard-review-2026-10-06.md)。
