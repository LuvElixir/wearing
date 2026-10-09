# Pajio 脱敏诊断与反馈 · 2026-10-08

## 集成

后端挂载（root 已完成）:

```python
from .diagnostics_api import install_diagnostic_routes
install_diagnostic_routes(
    app, store, runtime_for,
    probe_for=diagnostic_probe,  # async identity -> existing HermesClient.probe()
    devices_for=relay_inventory_or_none,  # sync identity -> owned relay.inventory
    deployment='local',  # cloud tenant uses cloud; isolated QA uses synthetic
)
```

`probe_for`只访问当前身份已经存在的 client；没有 client 返回`not_observed`，不启动引擎。无真实本机租约证据则不传`devices_for`，不从电脑/手机“已安装”推断“在线”。现有租户、登录、身份中间件仍是授权边界，端点没有独立弱化认证。

App 挂载（root 已完成）：

```tsx
<NativeDiagnosticsPanel connection={connection} fetcher={serviceFetch}
  onTasks={openTasks} onDevices={openDevices} onReconnect={openConnection}/>
```

`connection`变更会按服务、身份及会话重新挂载，取消旧请求。当前没有新增原生依赖；使用已安装 Expo SDK57 的 Constants、Network、Sharing 和 FileSystem。SDK57 versioned docs URL 本次不可访问，已检查官方 latest 页面其推荐版本为57，以及本机57.0.x的类型/实现。Constants版本来自 manifest，native build 来自嵌入平台信息，未知值保持 null；不读取设备名/序列号。

## 真实操作

- 用户选择问题类别，点击“生成诊断”才读取；不会在后台自动上传或发消息。
- `GET /api/diagnostics`只整理实际状态、执行至多5秒的只读 capability probe；不调用`refresh/start/stop`，不修改 task/events。缺失或失败来源保留为部分诊断。
- App 可完整预览 JSON，主动调用系统分享面板保存/发送。关闭分享面板不代表已保存、已发送或支持人员已接收。没有未实现的“提交成功”按钮。
- 离线或登录过期仍可生成本机报告；server=null、错误类别及系统网络状态明确保留，不能伪造远端任务状态。
- 无改动代码以外的持续后台心跳、健康历史、故障上报平台或支持收件服务；这些在缺口矩阵保留为后续软件任务。

## 白名单字段与证据含义

API schema 1包括report_id、scope校验用identity_id、captured_at、service、runtime、engine_probe、devices、tasks。

- `runtime`：现有运行环境`status()`的阶段、进程状态、安装状态、三个连接器的阶段/active/error_present、读取时间。异常时`state=unavailable`；丢弃URL、路径、命令、模型配置、错误正文。
- `engine_probe`：现有client实际`GET /v1/capabilities`的结果和本次观测时间。`reachable`只证明这次引擎HTTP能响应；`not_configured/not_observed/timeout/unavailable`分别保留。
- `devices`：当前身份最多30项资源，仅kind、connected/online/paused/control_pending/needs_review、服务端连接租约`last_seen_at`。没有设备名、connector/resource ID、serial、连接地址。未接真实来源时`not_observed`。
- `tasks`：当前身份最近30项；task/run ID、phase、attempt、创建/记录更新时间、最后状态事件时间、错误类别。已知生成UUID原样，任意上游ID用固定SHA256短引用，避免字段被当日志通道。
- `record_updated_at`可能随轮询变化。`last_state_event_at`只取created/accepted/已知状态转换/approval_answered等明确事件，不读message字段。运行阶段超过900秒无状态变化，只提示需要核对进展，**不能据此认定卡死**。等待用户确认不被报为卡住。
- 服务版本为本机安装包metadata；HTTP、task、runtime读取并非同一个原子快照。时间表示实际读取时刻，不代表持续监控。
- Native报告仅导出连接类别/协议类别/当前身份标记/授权有效性；不导出endpoint、userId、tenantId、credentialId、accessToken、CSRF、identity名称或原始identity_id。
- Native在分享前重新构建整个白名单，并核对当前identity；服务未来增加字段不会自动进入分享文件。网络接口状态并不证明互联网/本服务可达，尤其iOS的isInternetReachable与系统连接状态相同。

## 最近错误接点

```ts
observeDiagnosticError(capturedConnection, 'sync', error);
observeDiagnosticError(capturedConnection, 'record', error);
// VoiceSession.onDiagnostic: only errors; pass bounded code, no text/audio.
if (event.outcome === 'error') observeDiagnosticError(capturedConnection, 'voice', {code: event.code});
clearDiagnosticErrors(originalConnection); // local sign-out cleanup
```

允许source为sync/chat/voice/record/files/notifications/devices/diagnostics。仅保留固定category+observed_at，最多8个scope各8项，一天内、进程内，退出清理。绝不保存Error.message、stack、response body、音频或输入内容。调用不抛错影响主流程。root已接sync/record/voice与退出；其余按具体catch用**当次操作捕获的connection**接入，不能将旧请求错误写到切换后的身份。UI不声称覆盖未接入位置或上次启动历史。

## 验证

- `tests/test_diagnostics.py` **8项**：隐私canary、真实状态事件与轮询区别、等待/长期阶段、不安全runID哈希、probe超时/部分失败、30项上限和身份隔离、真实App TenantBoundary 401/403/404/409、task/events不变。
- `diagnostics-client.test.ts` **9项**：深层投影、secret/路径/地址剔除、跨身份拒绝、固定headers/无URL凭据、错误正文和malformed receipt保护、abort、错误环大小/过期、离线/会话过期、证据区别、用户分享取消/重试相同bytes。
- 相关eslint与全App tsc通过。QA+diagnostics+search 29项Python通过。未在此子任务中进行原生UI操作；root负责真实点击/构建验证。
- QA8891/PID6448已挂真实诊断/SearchBook业务路由，probe明确synthetic/not_configured；未发送任何真实推送、反馈、消息或调用外部模型。
