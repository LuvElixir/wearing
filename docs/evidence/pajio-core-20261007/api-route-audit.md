# API 挂载核对 · 2026-10-08

## 结论

当前没有发现“模块已实现但忘记挂在主 App”的接口。18 个独立安装函数均在 `create_app` 调用，含17个 `*_api.py` 和 `workspace_upload.py`。隔离构造实际得到127个 HTTP/WebSocket 路由、1个静态文件挂载；相同 method/path 重复为0，较早动态路由遮挡后续静态 API 为0。完整清单见 `api-route-inventory.json`。

这是挂载和路由顺序核对，不代表127个接口都已业务/真机验收。没有运行 lifespan，没有执行 API handler、后台 tick、模型、doctor、runtime start/stop；Store 全在自动清理的独立临时目录，socket.connect 与进程创建被禁止。

## 独立模块

| 模块 | 安装函数 | 已挂载 |
|---|---|---|
| `activity_api.py` | `install_activity_routes` | 是 |
| `artifact_api.py` | `install_artifact_routes` | 是 |
| `briefing_api.py` | `install_briefing_routes` | 是 |
| `capture_api.py` | `install_capture_routes` | 是 |
| `cloud_apps_api.py` | `install_cloud_app_routes` | 是 |
| `confirmation_api.py` | `install_confirmation_routes` | 是 |
| `diagnostics_api.py` | `install_diagnostic_routes` | 是 |
| `identity_export_api.py` | `install_identity_export_routes` | 是 |
| `life_api.py` | `install_life_routes` | 是 |
| `messaging_api.py` | `install_messaging_routes` | 是 |
| `notifications_api.py` | `install_notification_routes` | 是 |
| `schedule_api.py` | `install_schedule_routes` | 是 |
| `search_api.py` | `install_search_routes` | 是 |
| `skills_api.py` | `install_skill_routes` | 是 |
| `speech_api.py` | `install_speech_routes` | 是 |
| `usage_api.py` | `install_usage_routes` | 是 |
| `workspace_api.py` | `install_workspace_page_routes` | 是 |
| `workspace_upload.py` | `install_workspace_import_routes` | 是 |

## App 请求覆盖

只读核对 `clients/mobile/src` 中业务 clients 与主 App routes：

- Core：bootstrap、life/assets/transcribe、capture/retry、memory GET/PATCH、activity/seen、conversation/tasks/goals/schedules。
- PersonalHub：workspace旧摘要、page/metadata/file、import，runtime与identity。
- 原生独立面板：skills/detail/enabled/install、cloud-apps/feishu读/授权/撤销、messaging列表与配置/启停/断开、devices配对/权限/控制/审批/核对、notifications登记/停用/resolve、briefings、artifacts、data-exports、usage、search问答/记录/任务、confirmations/resume、diagnostics。
- 本机设备 prepare/bind/pause/resume 和 permissions 路由在 `app.py` 内联存在；云模式走既有 relay 分支，不把 HTTP200 静态盘点作为设备实际可控证据。
- 原生登录 `/auth/mobile/exchange` 由 `cloud/gateway.py` 提供，非 worker；gateway 同时挂 `/auth/mobile/start`、session、logout、tenant，通用 HTTP 代理覆盖 GET/HEAD/POST/PUT/PATCH/DELETE。原生语音 WebSocket 在 gateway 与 dev_mobile 各有独立 Voice route，不能用普通 HTTP proxy 替代。

## 真实缺口与非漏挂区别

- 技能只有安装/详情/启停，**没有卸载接口与按钮**，不能写成“已移除”。已更正外测矩阵。
- 账户级删除/租户 deprovision 尚没有业务模块，因此不是漏挂一个路由。控制面会员/所有权与删除作业需要补齐，见后续账户删除调查。
- 系统分享接收、云到 iPhone 原生命令、结果选择回传、持续同步与安静时段等由矩阵单独追踪；不能凭路由数量声称这些能力已实现。

诊断/搜索本轮真实业务 handler 在独立 QA 有合成测试（无外部 socket/进程）与现场API回执。原生点击验收仍由 root 单独记录。
