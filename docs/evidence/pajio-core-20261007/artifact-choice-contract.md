# 结果选择继续处理 · 2026-10-08

App 在图文预览下提供产品原生选项区，用户点选后看完整 instruction，再「确认选择，继续处理」。HTML 保持 opaque sandbox，没有 postMessage / 任意工具 / 主应用凭据桥。发布方通过 `ArtifactDraft.choices` 声明最多8项 `{id,label,instruction}`，选项ID唯一，长度限制分别40/80/1000。

## 持久协议

- `GET /api/artifacts/{id}/choices`：`artifact_id,artifact_revision,revision,newer_id,choices,selection`。旧结果没有choices时返回空数组，不伪造控件。
- `POST /api/artifacts/{id}/choices`：`request_key`（16–100字母数字下划线横线）、`choice_id`、`artifact_revision`、`selection_revision`。均严格校验，不接收客户端instruction、命令、任务ID或owner。
- 回执：`artifact_id,revision,request_key,choice_id,task_id,source_task_id,created_at,task_status,queue_state`。201只说明选择和后续消息已原子保存，初始是queued，不是已经执行。
- 现有 GoalCoordinator 消费相同 message_handoffs 队列。后续消息包含原结果和任务ID、明确选择和完整要求，沿用当前身份对话。原任务历史保留，不把旧run强行重新执行。既有执行/关键行为授权规则不变，选择不是付款、外发、删除等额外permit。
- 同一事务写选择、任务、消息、队列、task principal与事件。服务重启或断响应后同request_key取得原回执；同key不同请求409。
- selection_revision变化、新版本发布、原任务仍活动/状态不明、上一选择仍排队/活动都返回409，不能自动更换版本再提交。
- 账户owner来自可信请求scope；cloud缺scope拒绝，客户端不能提供。选择记录按 identity+owner 隔离，结果本身仍沿用身份空间可见性。新任务只绑定提交者owner，不借用原作者的手机权限。
- App 在POST前先把精确请求写入本账户/身份/结果的SQLite key；保存失败不发送。未知网络结果保留请求，用户显式取回；校验失败的200按未知结果处理。仅完整匹配回执后清本地请求，身份切换迟到结果不更新新UI。

## Web/Desktop

ZCode 只读 `artifact_choices.py`、`artifact_api.py`、App `artifact-choices.ts` 和 `ArtifactChoicePanel.tsx` 后在产品框架内提供同样选项和二次确认。不要给生成HTML注入凭据/原生bridge。需覆盖reload、断响应同请求、409输入保留、旧版本入口、精确原任务绑定。后端无需ZCode修改。

## 当前证据

- 结果发布/选择/消息队列集合45项 Python 测试通过（临时数据库、MockTransport，无模型/外部实际动作）；客户端选择7项 + 原产物9项共16项通过。
- 模型schema的 $defs 已提升到发布工具根，JSON Schema验证嵌套choices有效。
- 后续原生点击与实际模型上下文使用另行记录；以上不代表真实供应商或设备执行已验收。
