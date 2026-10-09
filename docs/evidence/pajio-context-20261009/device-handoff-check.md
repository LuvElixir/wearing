# 物理手机人工接管：核心实现与验收边界

日期：2026-10-09。结论：**已实现并接线所有权控制核心；生产私密远程接入仍默认关闭。没有完成用户 iPhone 到 Android 真机的视频、输入或登录端到端验收。**

本轮使用临时目录、合成设备编号、合成连接凭据与合成标记测试。没有启动或重启生产服务，没有查看真实手机画面、操作账号、读取密码、公开 ADB、安装驱动或修改真实配对。测试中的设备、MCP 响应及媒体清理回调为测试替身。

## 1. 已完成的实际接线

| 层次 | 本轮完成 | 源码入口 |
|---|---|---|
| 本机所有权 | 持久 epoch、精确 tenant/identity/actor/connector/resource 作用域、私密会话、超时/重启保持 paused | `src/wearing/device_gateway.py:57` |
| 本机手机 MCP | 实际调用前后检查同一网关；人工接管/暂停拒绝截图、节点与输入；切换期间返回的旧结果丢弃 | `src/wearing/phone_proxy.py:224,275,290` |
| 原生动作互斥 | 接管激活使用 phone_proxy 已持有的同一路径文件锁，等旧原生动作退出后才能确认私密状态 | `src/wearing/device_gateway.py:151,160` |
| 远程连接器 | NativeAdapter 的实际手机执行入口同样前后验证；受信配置才可发布私密能力 | `src/wearing/connectors/remote/adapter.py:22,40,47,164` |
| 云端控制 | RelayStore 持久接管状态；申请接管清空未完成结果、阻断 queued/executing、增加控制代次；enqueue/claim 和旧“恢复”不能穿过私密/paused 状态 | `src/wearing/cloud/device_access.py:79,88`；`src/wearing/cloud/relay.py:310,379,426` |
| 连接器控制循环 | 实际 poll 收发会话指令/ACK，先核对配对作用域再调用网关；网络错误、退出和取消触发暂停 | `src/wearing/connectors/remote/client.py:219,223,285,329` |
| HTTP | 根任务实现的 GET status、POST request/close/return 与真实 RelayStore 方法签名匹配，并已通过实际持久层测试 | `src/wearing/device_access_api.py:48`；`src/wearing/app.py:483` |

云端接管 epoch、命令 lease epoch、本机所有权 epoch 各司其职，接管通过云端 fence 和本机确认连接起来；不能把它们描述为已经覆盖整台宿主所有进程的安全隔离。实际本机手机 MCP 和远程 NativeAdapter 共享默认的 OS 用户级网关与动作锁；不以项目目录隔离出多个相互不知情的设备持有者。

### 实际状态转换

1. HTTP 从可信 worker 的 `pajio.storage_scope` 取得 opaque actor，客户端不能提交 actor/readiness。
2. `request` 需要服务端受信能力开关、已配对 Android 连接器、实际物理在线状态和正确控制代次；同 request_id 幂等。
3. 云端先进入 handoff_pending 并 fence Agent 操作，再发带 tenant/identity/actor/connector/resource/session/epoch/revision 的指令。
4. 本机网关进入 handoff_pending，等真实动作锁可用，再确认 human_private。只有连接器新 ACK 才使云端显示设备已确认。
5. 用户交还必须分别确认已退离认证页面与后续读取范围。HTTP 只记录 return_pending；用户提供的布尔值不能冒充媒体缓冲区清理完成。
6. 本机受信媒体适配器的清理回调完成，网关才进入新的 agent_ready epoch。云端还须收到对应会话/代次、且 gateway_epoch 严格增加的 ACK，普通控制代次也完成往返后才接受新的 Agent 命令。
7. close、断连、物理手机离线、过期、连接器重启均保持 paused；旧 ACK 不能恢复 Agent。重新人工接管必须新请求；没有自动交还。

复审实际主循环时修正了一个接管恢复问题：原 `availability` 会把暂停的 Agent 设备标为不可用，导致用户结束接管后无法再次申请。现新增连接器受信的 `human_availability`，只表达物理连通性；Agent 的暂停状态仍保留。该字段不能从用户 HTTP 提交，手机物理离线仍拒绝新接管并暂停活动会话。对应回归运行真实 `Connector.run` 的轮询组装和真实 RelayStore，网络与设备为合成适配器。

## 2. HTTP 与真实 RelayStore 的独立验证

新增 `tests/test_device_access_relay_integration.py`，不是 stub Relay：

- 服务端默认关闭时，即使连接器宣告 ready 也不可用；连接器未准备好也不可用。
- 当前可信 opaque owner 原样进入持久层；伪造 HTTP header 不能换 owner；错误 identity/resource/actor 返回 404，不返回 session 或 actor。
- 申请、关闭、待交还重复请求保持幂等；旧控制代次、旧 session/epoch 拒绝。
- body 严格禁止附带 text/frame/user_id/human_acks/media_cleared/gateway_epoch；错误响应不回显测试秘密。
- 普通用户路由没有 `/v1/poll`；错误连接器 token 不得确认私密或交还。
- 用户确认交还后仍无法 enqueue；必须新 gateway ACK 与正常控制 ACK 才释放 Agent。
- 断连后重新连接不能让旧 ACK 把 paused 恢复。

这些测试将可信 worker context 注入 FastAPI 测试应用，并复用真实路由、校验模型与持久 RelayStore；**不是生产登录、CSRF、公网 TLS 或媒体加密的验收**。生产 HTTP 的认证、CSRF 与可信 worker scope 仍由现有 create_app/网关提供。

## 3. 测试结果

执行：

```sh
.venv/bin/python -m pytest -q \
  tests/test_device_access_gateway.py \
  tests/test_device_access_api.py \
  tests/test_device_access_relay_integration.py \
  tests/test_device_relay.py tests/test_device_setup.py \
  tests/test_device_permissions.py tests/test_connector_service.py \
  tests/test_phone.py -k 'not real_mobile_proxy'
```

结果：**127 passed，1 deselected，58.83s**。唯一排除的是 `test_real_mobile_proxy_scopes_schemas_and_blocks_before_device_access`；它会调用已安装的真实 adb 来枚举设备，本轮没有真实设备 I/O 验收。

`py_compile` 已通过 gateway、cloud/device_access、relay、remote adapter/client、phone_proxy、device_access_api。测试覆盖真实入口调用，不只单独状态机；仍不能由这些合成测试推导出真人远程登录成功。

## 4. 明确未实现、不可开启的部分

1. **实时视频与人工输入通道**：没有 scrcpy/WebRTC 集成、移动解码器、触控/中文输入或 TURN 部署。没有密码传输 API。现有 Agent 命令账本仍可保存普通工具 params，绝不可用它传递人工密码/验证码。
2. **端点加密与媒体隔离**：没有实现控制 App 与设备网关之间的认证加密媒体/输入、短期票据、缓冲区清理或泄漏扫描。测试中的 `private_media.clear` 是受信回调替身，不是实际媒体清理证据。
3. **宿主全路径隔离**：同一 OS 用户的其他 shell/ADB/scrcpy、电脑截图、通知、剪贴板、其他自动化进程及实体触碰仍不能靠 Python 文件锁排除。不能宣称 Agent 在真实宿主所有路径下都无法获取秘密。
4. **媒体生命周期**：App 后台/锁屏/媒体断流的真实事件尚未接入。已有网关短期租约与 Connector 网络/进程暂停，但不是媒体心跳已完成。
5. **帧与坐标**：没有 frame_id、方向/内容区域映射、帧龄、输入序号、旧帧拒绝等真实实现。
6. **读取授权**：`scope_confirmed` 只是交还前确认的控制元数据，不是各个平台账号、类别、数量、期限的授权记录。实际平台读取任务必须另行绑定并验证明确范围；不能由这个布尔值获得任意平台数据访问权。
7. **iPhone 执行宿主**：没有通用第三方 App 自动控制能力。首轮仍是 iPhone/Android 控制端与独占 Android 执行手机分离。
8. **生产/真机**：未部署，没有真实 iPhone 到执行手机的登录、跨租户媒体/输入隔离、旋转、Wi-Fi/蜂窝切换或断线矩阵证据。

生产 `instance_relay` 使用默认 `human_access_ready=False`；默认 NativeAdapter 不注入 ready gateway 或媒体适配器。用户 HTTP 不能改变这两个条件。应如实显示暂未支持私密远程接入，不能显示一个可点击但不存在的登录遥控入口。

## 5. 下一阶段退出条件

遵循 `docs/plans/pajio-physical-device-access-2026-10-09.md`：阶段 0 隔离单机 QA，完成受信宿主、实际媒体/输入、合成密码泄漏与帧坐标验证；阶段 1 完成 iPhone 控制端到独占 Android 物理设备的完整端到端；之后才做各个平台授权范围读取与上下文候选。即使 UI 只读，也可能产生已读、浏览/播放历史和推荐信号，需在平台流程中体现。
