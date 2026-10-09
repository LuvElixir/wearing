# 模型预算预留与用量估算

2026-10-10。沿用每个租户 data directory 的 `usage.sqlite3` 和原来的试用次数、并发、语音时长账本；没有另建余额系统。当前实现是服务方配置费率下的模型预算控制，不是供应商账单同步，不是用户钱包，也不是对所有供应商真实费用的绝对封顶。

## 如何计入

1. 每次 SDK 实际调用前，在同一个 SQLite `BEGIN IMMEDIATE` 事务内检查调用次数、并发和金额余额，再记录预留。重复 request key 不会重复占用。同租户切换身份不会获得新预算。
2. 价格按实际 SDK `base_url` 的 hostname 和请求 `model` 精确匹配。完全未配置价格时，保留现有试用次数和并发限制；金额不可用，不以零元冒充免费。启用金额预算后，hostname/model 不匹配则在网络调用前拒绝，不能换成未定价模型绕过金额预算。
3. 单次预留使用服务方核实的模型 **最大输入上下文 tokens**，乘以两种输入费率中较高者，再加实际请求的输出上限。不会用字符数假装精确 tokens。输入上界必须覆盖供应商模型完整上下文，不能拿产品希望的平均输入长度代替。
4. SDK 守卫将单次输出约束为不超过 8192 tokens，并请求 chat stream 的 usage 事件。多 completion、`best_of > 1`、多上下文 batch 暂不接受，避免一次预留对应多份计费。配置的输出上界不足以覆盖请求时，在网络前拒绝。
5. 完整用量回执按每次预留时保存的版本、币种、费率计算金额。支持 DeepSeek `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`，以及 OpenAI 兼容 chat / Responses 的缓存明细。完整输入/输出 tokens 但缺少缓存拆分时，使用较高输入费率，并标注保守上界。
6. 缺失输入或输出、错误、取消、未消费完的 stream、进程退出等情况标为 `uncertain`，保持完整预留，不退款。即使收到部分 tokens，也不能据此释放未证明未消耗的额度。活进程不会因超时被冒充死亡；确认死进程后只释放并发槽位。
7. 完整回执超出输入/输出预留范围时仍记录真实 tokens 与估算金额，并暂停该模型同版本新调用，等待 operator 修正上界、建立新价格版本。未知回执只有人工核对供应商记录后才适合做后续账本对账；当前不提供自动退款或用户自行重置入口。

整数金额的单位是该币种的百万分之一（micros）。对一次调用的三部分费用求和后向上取整一次，避免浮点误差或把极小费用显示为零。原始提示、输出正文、凭据和明文 request key 不进入账本。

## 私有 operator 配置

调用 `UsageBook.configure_pricing(config)`，只从 operator 控制的私有配置文件加载。没有可写公共 API，没有 provider dotenv 费率开关；已有在 provider dotenv 之前固定账本路径和身份的保护保持不变。由部署侧保证账本及配置文件不暴露给租户 Agent 的文件工具。

以下是 **测试格式，费率为虚构值，域名不可用于真实模型调用**。实际配置必须将预算、币种、host、model、费率和完整上下文上界逐项替换为已核实值：

```json
{
  "version": "operator-20261010-v1",
  "currency": "CNY",
  "budget": "10.00",
  "models": [
    {
      "provider": "unit.invalid",
      "model": "synthetic-fixture",
      "input_per_million": "2.00",
      "cached_input_per_million": "0.20",
      "output_per_million": "8.00",
      "max_input_tokens": 1048576,
      "max_output_tokens": 8192
    }
  ]
}
```

- 单价均为该币种 **每百万 tokens** 的十进制字符串，最多六位小数，不接受浮点数、指数、NaN、负数。
- `budget` 是整个现有账本累计模型预算，并非增加这么多余额。修改总预算不会清空已估算、活跃和待核对预留；调低到占用以下会阻止后续已定价模型调用。
- 同一 `version` 的币种和模型价格列表不可修改；调价或修改上下文上界必须使用新版本。模型别名只在 operator 明确配置时覆盖，不做自动价格映射。
- 同一个账本不允许切换币种。不通过清空或替换生产账本完成币种迁移，以免绕过既有次数和支出记录。
- 未定价的历史/其他模型请求不会被新费率回填。API 会报告 `partial` 和 `unpriced_calls`；已配置金额预算无法代表这些未覆盖调用的真实支出。语音仍按时长/次数限制，此金额不包含语音、工具和设备费用。

在已安装相应代码的服务端 Python 环境中，由 operator 执行：

```python
import json
from pathlib import Path
from wearing.usage import UsageBook

# 两条路径均使用该租户实际部署路径；不能指向另一个租户或新建空账本。
runtime_data = Path("/path/to/existing/tenant/data")
private_config = Path("/path/to/operator/pricing.json")
book = UsageBook(runtime_data, enabled=True)
book.configure_pricing(json.loads(private_config.read_text()))
```

新增的 `usage_pricing.py` 必须与 `usage.py`、`usage_guard.py` 一并提供给 managed Hermes Python 的两条模型桥接入口；不新增模型调用或网络请求。未执行真实 operator 配置前，默认行为仍为原有试用限额、金额 `unavailable`。

## 当前供应商核实边界

root 部署任务在 2026-10-10 从 A 租户现有配置中仅过滤读取 `model.default=deepseek-flash`、`provider=deepseek`；这证明配置选择，不等于每一次 SDK 请求的实际 hostname/model。费率匹配以账本实际记录为准。

2026-10-10 直接读取的 [DeepSeek 官方价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 中，`deepseek-flash` 对应 DeepSeek-V4.1-Flash，上下文 1M，高峰每百万 input/cache/output 分别为 2/0.04/8 CNY，空闲减半。部署测试采用高峰费率做保守估算，不声称等于当时实收。代码没有内置这些价格、时段折扣或自动更新。operator 应核对账号当前适用单价，必要时以较高费率进行保守预算；最终账单还可能受价格变化、优惠、赠送余额和供应商计量规则影响。

## API 和 App

仍只有经过既有身份中间件的 `GET /api/usage`，响应 `Cache-Control: no-store`。未配置价格时保持原有 `cost: null, cost_status: unavailable`。

配置后 `cost` 提供 `basis: operator_rates`、`supplier_bill: false`、`scope: runtime_model_calls`、当前 `price_version`、`currency`、`unit: micros`，以及总预算、已按回执估算、活跃预留、待核对预留、已占用、剩余、未定价请求数、缺少缓存明细数、超界请求数。`cost_status: partial` 表示存在未定价请求，否则为 `estimated`。历史调用沿用各自的旧价格快照；API 所列版本为当前新调用配置。

App 拒绝不一致金额或被伪装成供应商账单的数据，分别展示上述占用和缺失范围，最小 1 micro 也不会显示成免费。不设置充值、自动扣款或预算重置按钮。

## 本轮验证

- 并发事务预算、跨身份共享、重复预留/结算、重启与死进程恢复、未知回执、stream 提前关闭和异步取消均保留正确占用。
- 价格版本不可变、调价保留旧快照、调低/调高总预算、币种拒绝、旧 SQLite 表并发升级、缓存拆分与向上取整、超界暂停、未配置价格时回退；配置金额后未知模型/供应商在请求前拒绝。
- 使用本机已安装的真实 OpenAI SDK + HTTP MockTransport 验证：预算先于网络预留、cache receipt 结算、强制输出上限、stream usage 请求、无回执保留、余额不足不触及网络。这组单元测试没有调用付费模型。
- `tests/test_usage*.py` 与 App `usage-model.test.ts`，App TypeScript 和目标 ESLint 校验。具体命令和本轮最终结果见任务回报。
- 后续已在现有 A/B 合成验收租户部署并配置真实 operator 预算 CNY 10、价格版本 `deepseek-official-20261010-peak-v1`。一次真实模型验收任务 `297591d3c0bb4304984a2bb2719f2697` 完成后，用量 API 记录已结算 1126 micros、活跃预留 0、待核对预留 0。该快照有 8 次未定价历史，未回填为免费；后续验收调用会继续累积。
- 已在独立 iOS 模拟器 App 经真实 OAuth 查看用量页；不是物理 iPhone 验收，也未完成供应商账单对账。私有原始证据为 `personal-compute/usage-live-proof.json` 和 `mobile-native-proof.json`。
