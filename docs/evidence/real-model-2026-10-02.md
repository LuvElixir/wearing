# 真实模型连接验收 · 2026-10-02

用户在 Hermes 官方面板完成 DeepSeek 配置后，Wearing 已启动自己管理的本地 Gateway。`/api/runtime` 返回 `running=true`、`provider=deepseek`，`/api/status` 返回 `reachable`，实际页面显示“已连接”。

通过独立临时数据库的 Wearing 应用测试 `/api/conversation` → TaskService → Hermes `/v1/runs` → DeepSeek → 状态轮询 → 结果落库完整路径。没有向用户正式对话插入测试内容；原有一条草稿保持不变。

- 第一轮：发送纯文本连接测试，指定代号“蓝鲸四十七”；8.32 秒返回“收到，测试代号‘蓝鲸四十七’已记住，纯文本连接正常。”
- 第二轮：不再提供代号，询问刚才的代号；1.10 秒返回“蓝鲸四十七”。
- 两轮使用同一 Hermes session，均保留为 `completed_unverified`，没有伪造用户验收事件。两轮合计 1,760 tokens（含缓存读取），不是费用结算记录。
- 具体运行 ID、用量及结果见同目录 `real-model-2026-10-02.json`；不含 API key。

本次验证覆盖真实模型鉴权、回复、多轮上下文和 Wearing 服务集成。未验证电脑控制、手机控制、云端沙盒、邮箱或支付等外部行动。当前 Gateway 工具集仍为空；后续应逐项接入并实测。

此前 `runtime-and-loop-2026-10-02.md` 中 `needs_login` 属于当时验收状态，现由本记录补充更新。
