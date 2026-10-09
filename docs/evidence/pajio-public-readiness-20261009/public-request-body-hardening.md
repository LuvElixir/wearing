# 公网 HTTP 请求读取保护

2026-10-09；仅源码与隔离 HTTP 测试，不代表已部署到腾讯云。原实例当前仍停机，见 [当前云状态](cloud-current.json)。

## 实现

- 新增 [request_body.py](../../../src/wearing/cloud/request_body.py)：纯 ASGI `receive` 包装，只有端点确实读取正文时才计数。拒绝歧义/损坏 Content-Length，声明超过上限时不读取正文；没有长度头的分块请求也按实际累计字节限制。
- HTTP 上传连续 **15 秒没有新数据**，或从开始读取算起累计 **120 秒**仍未结束，返回 `408 / request_body_timeout`。超限返回 `413 / request_too_large`；错误响应禁止缓存，不记录 body、token 或提供商回调。
- 保留普通 Worker 代理 1 MiB、工作区文件导入 20 MiB、素材 15 MiB、设备 relay 8 MiB、移动登录交接 2048 字节。门户空间切换与注销 JSON 上限 4096 字节；其余 `/auth/` 留 64 KiB，保留原编码供 Authlib/表单解析。
- gateway 仍先验证会话与权限，再读需要代理的内容；上传中的撤权照常中断，不派发上游。错误空间切换 JSON 返回 422，避免误报入口服务故障。
- relay 的受保护 POST 在 FastAPI 解析 body 之前检查唯一合法格式的连接凭据和持久撤销状态。操作事务在上传后仍再次校验，拒绝上传期间被撤销的连接。一次性配对入口保留自身校验与 body 边界。
- WebSocket 与 lifespan 直接透传；上传完成后的断开监听和返回内容流不受上传超时影响。没有新依赖，没有改变 OIDC、设备动作、会话撤权和上传字段协议。

## 验证

```sh
.venv/bin/python -m pytest -q tests/test_cloud_request_body.py tests/test_gateway.py tests/test_device_relay.py tests/test_gateway_voice.py tests/test_mobile_gateway.py tests/test_deletion_gateway.py tests/test_device_access_gateway.py tests/test_device_access_relay_integration.py tests/test_native_storage_boundary.py
```

**128 passed，42.44 秒，2 项既有依赖弃用提示**（Authlib/httpx、Starlette TestClient/httpx）。`compileall` 与所改路径的 `git diff --check` 通过。

新增回归覆盖：声明超限不读 body、实际分块超限、上限恰好通过、无效/重复长度、慢上传空闲与总期限、取消接收、表单解析、超过上传期限的流式响应、WS/lifespan 不被读取、匿名或未知连接凭据不消费正文、撤权发生在上传过程中时不派发/不执行、完整 20/15 MiB 上传、移动登录与注销请求超时、空间切换非法 JSON/大小与正常请求恢复。

HTTPS 租户测试 helper `tests/test_gateway.py::lab` 用作用域内 `pytest.MonkeyPatch.context()` 显式启用已有试用限额，退出后恢复原环境；导入该 helper 的语音/移动登录/注销测试也满足并行新增的云端启动闸门，不以测试绕过生产校验。

## 边界与资料

这是每个请求的读取保护。没有将进程内计数包装成全平台限流；分布式/IP/账户公平限流、连接并发上限、TLS 反向代理、数据库压力与真实弱网上传仍需在生产入口部署时配置和验证。15 秒空闲与 120 秒上传总期限还应通过外部手机网络实测确认；超时不会自动重发业务操作。

实现前核对了 [Starlette Requests](https://starlette.dev/requests/)、[纯 ASGI middleware](https://starlette.dev/middleware/#pure-asgi-middleware) 与 [HTTPX timeout](https://www.python-httpx.org/advanced/timeouts/)。HTTPX 的连接/读写/连接池超时约束上游 HTTP 客户端操作，不能替代入口从用户手机接收 body 的期限；本机实际 Starlette 为 1.7.0，已核对安装源码中的 `Request.stream` / middleware 接收行为。
