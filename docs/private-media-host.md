# 私密远程接管宿主

代码支持 Linux X11 和 Android。只有操作系统管理员创建的固定资源绑定能开启私密接管；App 不能指定宿主地址、ADB serial、显示器、驱动路径或媒体宿主凭据。

## 宿主部署

启动：

```sh
/opt/pajio-native/venv/bin/python -m wearing.private_media --config /etc/pajio/media-host.json --port 8792
```

该进程固定监听 `127.0.0.1:8792`。跨 VM 的信令必须由验证客户端证书的 TLS 代理转发；媒体与输入由设备 VM 和 App 之间的 WebRTC DTLS/SRTP/SCTP 通道传输，TURN 只转发密文。信令服务必须禁用请求/响应正文日志。每次 offer 的 TURN 凭据由可信 worker 短期签发，宿主文件不保存 TURN 长期密钥。

配置应由运行宿主的专用用户持有，权限 `0600`。以下均为占位值：

```json
{
  "token": "独立生成的至少32字符随机宿主凭据",
  "gateway_root": "/home/pajio-desktop/.wearing/device-gateway",
  "resources": [{
    "resource_id": "computer_example",
    "tenant_id": "tenant_example",
    "identity_id": "daily",
    "connector_id": "connector_example",
    "kind": "computer",
    "display": ":10",
    "max_fps": 15
  }]
}
```

X11 服务环境应设置同一 `HOME`、`DISPLAY`、`XAUTHORITY`。连接器、电脑驱动、私密媒体宿主使用同一 Gateway 数据库和同一 `~/.wearing/phone-locks/{resource_id}.lock`。执行 VM 的操作账户和承载模型/Agent 任意 shell 的账户、VM 必须隔离；同 UID 的不受限 shell 能修改数据库或读取凭据，这不属于本模块能够抵御的威胁模型。

连接器自动加载它的 `data/runtime/private-media.json`，同样要求私有所有权和 `0600`：

```json
{
  "endpoint": "http://127.0.0.1:8792",
  "token": "与宿主相同的随机凭据",
  "gateway_root": "/home/pajio-desktop/.wearing/device-gateway"
}
```

若连接器不与宿主同机，endpoint 必须为 HTTPS，可配置 `ca_file`、`client_cert`、`client_key`；不跟随重定向，不继承代理环境。生产布局应优先同机 loopback。

Android 正式视频绑定采用如下字段，`serial` 固定于单一设备：

```json
{
  "resource_id": "phone_example",
  "tenant_id": "tenant_example",
  "identity_id": "daily",
  "connector_id": "connector_example",
  "kind": "android",
  "serial": "127.0.0.1:5555",
  "adb": "/usr/bin/adb",
  "video_source": "scrcpy",
  "scrcpy_server": "/opt/pajio-native/scrcpy-server-v5.0.1",
  "unicode_ime": true,
  "max_fps": 24,
  "max_size": 0,
  "bitrate": 4000000
}
```

官方 [scrcpy 5.0.1 server](https://github.com/Genymobile/scrcpy/releases/tag/v5.0.1) SHA256：`764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536`。源码依据官方协议独立实现；服务二进制不满足该固定摘要就拒绝启动。Python 依赖使用项目 `private-media` extra；Android 需要 adb 和自建 `io.pajio.privateinput/.PrivateInputMethod`，构建、协议及安装见 [专用 IME](../native/private-input/README.md)。仅在该组件已安装验收后开启 `unicode_ime: true`。

原 u2 广播 IME 已被实机证实会将 Base64 文本留在系统广播历史，已移除。普通 `adb input text` 即使宿主走 stdin，设备子进程 argv 仍会包含文字，也已禁用。正式路径使用 `adb shell -T` 启动固定 APK 内的 SocketClient，正文为二进制 stdin；该客户端通过内核凭据检查 IME 服务端 UID，IME 也只接纳 root/shell UID。每个私密会话有随机 32 字节 nonce，禁止广播、clipboard、内容日志和输入重试。关闭时释放 nonce 租约、恢复原 IME 并终止本产品 IME 包。只对自有可变缓冲区作清零，不声称 Android 或目标应用的全部内存已擦除。

scrcpy 音频与控制通道关闭，仅接收连续 H264 视频。每个捕获会话变更都会更新几何版本，包括同尺寸旋转；每帧验证 Gateway。只保留一张最新解码帧，关闭时销毁 socket、转发、进程、解码线程及缓存。没有 `video_source: scrcpy` 的 Android 配置仅为 `adb-screencap` 降级模式，最高 3 fps、文本输入不可用，不可作为正式体验的验收结论。

## 信令与控制协议

宿主所有端点要求 `Authorization: Bearer <host token>`：

- `GET /v1/status`：探测原生资源的连接/几何和固定 server 文件，返回 `{ready, resources}`。它不证明某个具体 App 的输入可用。
- `POST /v1/offer`：`{scope:{tenant_id,identity_id,user_id,connector_id,resource_id},session_id,epoch,gateway_epoch,type:"offer",sdp,ice_servers}`。scope 来自 worker 的已认证上下文；精确匹配设备 Gateway 后返回 `{type:"answer",sdp,gateway_epoch,transport:"webrtc-dtls-srtp"}`。同一活跃租约只允许一个 viewer。
- `POST /v1/clear`：`{scope,session_id,gateway_epoch}`。只有 Gateway 处于 `awaiting_scope` 才执行不改变 ownership 的清理，成功返回 `{cleared:true,session_id,gateway_epoch}`。

App 通过公共的 `/api/devices/access/{resource}/transport` 和 `/offer`，不会获得宿主 token。WebView 仅收短期 ICE 配置和 SDP，不获得 App 的账户 bearer。

Data channel 名称 `pajio-control`，要求 ordered、reliable。每条 App 消息必须携带 `session_id`、relay `epoch`、`gateway_epoch`。

- 每 5 秒发送 `{type:"heartbeat", ...}`。15 秒无有效心跳会关闭并保持暂停。设备授权由连接器的已认证轮询续期，viewer 不能单独延长它。
- 宿主发送 `ready`（含 `capabilities`）、`frame`（含 `frame_id,width,height,geometry_revision,capture_fps,source`）。`frame_id` 最多有效 2 秒，几何版本变化立即失效。
- 输入：`{type:"input", ..., seq,frame_id,action, ...}`。`seq` 严格递增；坐标使用视频本身的像素，不能使用屏幕 CSS 坐标。
- `tap:{x,y}`；`swipe:{x,y,to_x,to_y,duration_ms}`；`pointer:{phase:"move"|"down"|"up",x,y,button:0|1|2}`；`scroll:{delta_x,delta_y}`；`key:{key,phase:"down"|"up"}`；`text:{text}`。这些字段与 action 同层，能力按 `ready.capabilities` 限制。
- 每条 JSON 最多 20 KiB；文本有 4096 UTF-8 字节的全局上限，还必须满足 `ready.capabilities.text_max_chars`（Unicode 码点数）和 `text_max_bytes`。X11 私密输入目前最多 32 码点，`text_disallow_controls:true` 表示拒绝 C0/DEL 控制字符，包括换行；Android 的 Unicode IME 保持最多 4096 UTF-8 字节，并声明 4096 码点的外层上限。App 发送前整串校验，不能通过截断或自动分段改变输入。宿主在任何按键前再次校验；超长或非法文本返回固定错误码 `text_too_long` / `text_invalid`，不回显正文。
- X11 与普通电脑驱动共用经过合成窗口测试的 30 ms 输入节奏，文字仅经 stdin；不读取私密字段内容来验证密码，也不使用剪贴板。32 码点上限用于约束持有原生锁的时长，不能通过延长 App 的 2.5 秒输入确认或视频时效门槛来掩盖阻塞。输入 ACK 表示原生提交完成，不是目标应用保存、验证或登录成功的证明。
- 最多排队 32 个输入；超过即暂停。每次原生输入前再次检查 scope、会话、epoch、帧时效与设备几何；执行后再次验证 ownership。
- 成功返回 `{type:"input_ack",seq}`；失败只回 `{type:"error",code,seq?}`。不回显输入，不记录输入，不自动重放不确定操作。

## 归还与隐私边界

明确归还时，连接器先把 Gateway 转为 `awaiting_scope`，阻止所有新 frame、input、offer，再等待可信宿主关闭通道、释放键鼠、丢弃队列和解码缓存。只有这一步实际成功且用户确认退出敏感页面、确认授权范围之后，才可转回 `agent_ready`。断网、超时、进程重启和清理失败均保持 `paused`。

清理媒体不是自动清除手机输入框，也不是证明所有底层系统内存均已擦除。宿主不擅自导航、提交表单或抹除用户输入；用户须先离开密码/验证码页面。Android 输入必须做设备级合成标记验收，不能单凭没有本产品日志就宣称绝无残留。2026-10-10 的云手机验收见 [实测记录](evidence/private-input-20261010/acceptance.md)；目标应用自身可能保存输入内容，测试不覆盖所有应用。云端 Agent 没有执行宿主的任意 shell 或原始 ADB 权限。

capture_fps 只统计独立捕获/解码时间，不把对同一缓存帧的重复发送算成新捕获。

Android 编码器可能在静止画面时停止输出。超过 0.75 秒无新帧，宿主读取一次实际设备 `screencap`，并使用该次读取的时间；从不把旧帧重新标为新帧。`capture_mode: adb-static-refresh` 明示这类刷新，动态画面仍由连续 H264 提供。刷新失败或几何变化中止会话；2 秒输入帧过期规则不变。静止刷新缓存也在关闭时清空。

显式归还先进入 `awaiting_scope`，此时捕获线程可能先于 `/v1/clear` 发现权限已失效。媒体关闭保留该状态，不会把已确认的归还流程覆盖为另一个 epoch 的暂停。只有可信 clear 的实际清理成功确认能完成归还；失败仍暂停。

关闭失败保留清理上下文。明确重连可以再次执行清理并核验其后置条件，不能让关闭过的 peer 恢复或重放输入。Android IME 的 socket ACK 丢失时，必须另证固定 APK 摘要一致、原 IME 读回一致、force-stop 成功及专用进程不存在。任一证据缺失均不允许新会话。受宿主认证保护的 `/v1/status` 仅增加每资源的 `closed/cleared/cleanup_attempts/cleanup_code`，不包含文字、画面、SDP 或异常正文。

目前 App 使用最近收到的帧元数据与视频本身宽高匹配，尚未把每一个解码画面与 RTP timestamp 严格绑定；几何变化会关闭输入，但不能宣称已经解决所有画面延迟下的坐标时序问题。

## 测试与验收

`tests/test_private_media.py` 覆盖实际 aiortc 本机视频解码、SCTP 输入、断开保持暂停、显式清空后归还、跨 scope、重放、旧帧/旋转、请求边界、输入不进入 argv、真实 H264 编解码与会话变化、线程清理、API 的可信身份来源。无 `aiortc` 时两项 transport 测试会跳过，应使用安装了 `private-media` 的环境验收。

本机 synthetic 测试不等于办公室 VM、跨公网 TURN、iOS WebView、真实 Android 中文输入已通过。生产验收须分别记录：原生窗口输入前后状态、实际接收帧率与延迟、跨公网断连/重连、归还后的 agent 阻断/恢复、Android 标记在日志/广播历史的检查、无残留媒体子进程与 ADB 转发。
