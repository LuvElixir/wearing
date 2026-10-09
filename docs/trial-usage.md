# Pajio 外测执行限额

当前版本是运行实例级的试用执行预算，不是付费会员或金额账单。默认本地开发保持原行为；运营侧明确设置 `PAJIO_TRIAL_LIMITS=1` 后才安装模型/语音限额。每个租户应使用独立数据目录。一个数据目录下所有身份共享额度，避免通过切换身份重置试用。

## 统计与执行

- 默认持久化上限：200 次模型 SDK 请求，100 次语音识别、合计 3600 秒；模型并发 2，语音并发 2。没有自动日重置。使用前可由服务器管理员调用 `UsageBook(data_dir).configure(UsagePolicy(...))` 修改；App 没有修改额度或购买入口。
- `usage.sqlite3` 使用 SQLite `BEGIN IMMEDIATE`，跨线程/进程串行完成预算检查与预占。所有发出的尝试都计数，失败、超时与显式重试不是免费请求。
- 请求幂等键哈希和终态 CAS 防止重复预占、重复结算。实时语音使用身份和 take ID。录音文件先读既有转写缓存；用户显式重试发起新尝试。任务本身仍沿用 TaskService 的规范消息/运行请求幂等。
- 模型的 SDK stream 直到读完/关闭才释放并发；中断保留次数。未知结果保留为 `uncertain`。重启仅将已死亡进程拥有的 `active` 改为 `uncertain`，保留消耗、释放并发；活进程不会因时间过去而被误释放。
- 语音先预留时长（实时输入最多 180 秒，文件按解码音频长度）；有确定文字结果后按传入 PCM 的时长结算，退回未使用的预留秒数。中断和未知结果保留整段预留秒数。秒数是本地音频测量，不是供应商账单。
- 输入/输出 tokens 只取单次供应商响应的 `usage`，不会重复相加 Hermes session 累计字段。缺失值为 `null`；真实返回 0 才显示 0。所有费用为 `null / unavailable`，没有单价推测。

## 付费边界覆盖

`usage_guard.py` 在受管 Hermes 进程安装 OpenAI SDK `SyncAPIClient.request` / `AsyncAPIClient.request` 包装。以已固定运行时的 OpenAI 2.24.0 接口验证。每次 SDK POST 前预占；options 禁止 SDK 内部自动重试和重定向。Hermes 本身的恢复重试经过同一入口重新计数。支持标准 OpenAI-compatible chat/completions（包括同 SDK 的视觉/辅助调用），并将每次输出请求限制到 8192 tokens。SDK responses/completions/embeddings 入口同样计数。

试用模式下主/子 Agent 只接受 `chat_completions` API 模式，并关闭跨 provider fallback；原生 Anthropic、Bedrock、Codex、MoA 等未接入模式停止新调用。辅助客户端选择和重试派发也拒绝非 OpenAI SDK facade，防止通过原生辅助传输漏计。新增供应商或升级 Hermes/SDK 必须更新边界测试后再启用。

**这不是所有第三方服务的总账。** Web 搜索、设备连接、OAuth API 等调用未折算成模型次数/金额。独立外部 Hermes 无法注入该 guard；外测模式须由 host `start_guard` 拒绝这类新执行，仍允许原有状态读取/停止。所有额度页数据只来自当前租户的本机账本；这不是供应商账户历史账单。

## 接入点

Host 装配：

```python
usage = UsageBook(settings.data_dir)
install_usage_routes(app, usage)
app.state.usage = usage
```

`GET /api/usage` 沿用 identity/auth 中间件，只读。已有 `start_guard` 在新执行入口调用 `usage.check('model')`，`UsageError` 以 `429` 和 `.detail` 返回；应保留先前的确认恢复/其他准入检查。不要对 GET、结果读取、stop/pause 加额度闸门。运行时通过可信环境 `PAJIO_USAGE_DATA_DIR` / `PAJIO_USAGE_IDENTITY` 归属调用，不能从模型提供的工具参数选择账户。

原生端 `<UsagePanel connection={connection}/>` 为用量页面，区分未启用/试用两种状态，支持刷新与重试。语音协议 `quota_exhausted`、`quota_busy`、`quota_duplicate`、`quota_unavailable` 要映射为可读文案；服务端同时返回 `message`。录音文件 HTTP 路径以可读 429 返回，原件保留。

## 验证

`tests/test_usage.py` 覆盖原子竞争、身份共享、幂等、崩溃恢复、活进程保守占用、语音秒数和取消，以及未启用时的原行为。`tests/test_usage_sdk.py` 通过实际已安装 SDK + `httpx.MockTransport` 验证非流式、流式、async、关闭、503 禁止自动重试、并发和额度耗尽前零网络。测试不使用真实凭据或供应商请求。
