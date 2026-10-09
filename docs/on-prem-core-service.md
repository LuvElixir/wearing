# Pajio 核心服务部署

正式入口：`https://pajio.luckyloading.com`；OIDC issuer：`https://id.pajio.luckyloading.com/realms/pajio`。

入口服务、PostgreSQL 和 Keycloak 位于独立控制 VM；两个初始验收租户分别位于自己的 KVM VM。外部入口只代理产品与登录路径，不代理 Proxmox、SSH、数据库或 Keycloak 管理界面。注册暂时关闭；登录账号与租户 membership 必须由操作者登记。

公网 TLS 在现有公司入口终止，入口经控制 VM 自己的 WireGuard 通道、双向 TLS 到达应用代理。控制服务到租户同样使用双向 TLS，同时保留每实例 Bearer 和固定 tenant 校验。控制 VM 只有访问指定租户服务端口的权限；租户仍不能访问办公网、宿主或其他租户。管理隧道与应用隧道使用不同密钥。

## 运行配置

- [网关服务](../deploy/control/pajio-gateway.service)：数据库网页角色、私有客户端证书及固定配置目录；普通用户运行、失败重启和资源限制。
- [身份服务模板](../deploy/control/pajio-identity.service.in)：Keycloak 生产模式、独立 PostgreSQL 数据库。只有首次初始化使用 realm import 和临时 bootstrap admin；运行期间不保留导入明文账号文件。
- [租户服务](../deploy/tenant/wearing-tenant.service)：保持现有受管 Hermes 生命周期和每租户数据目录，强制试用调用限制。模型调用次数是接纳上限，不是供应商金额账单。

`PAJIO_UPSTREAM_CA_FILE`、`PAJIO_UPSTREAM_CERT_FILE`、`PAJIO_UPSTREAM_KEY_FILE` 必须同时配置。私钥为服务用户所有、权限 0600；缺项、错误格式或宽松私钥权限导致网关启动失败。HTTP 与语音 WebSocket 使用同一个验证上下文；保持服务端证书和名称校验。此信任配置仅供操作者设置，不从用户请求接收。

控制数据库使用独立 web/operator/migration 角色和 Unix socket 的 SCRAM 认证；应用不使用 PostgreSQL 管理员。身份服务使用另一独立数据库和角色。迁移后必须运行 `wearing gateway database check`。

凭据、私有 CA、生产连接串和账号只存在受限部署目录及相应服务器中。Ubuntu 租户需预装 `libatomic1`，否则受管 Node.js 无法通过启动校验。安装包来自 `uv.lock` 固定版本与散列；Hermes 使用运行时固定源码散列。不得将开发 Mac 的整份 `.env`、记忆或会话复制到租户。

Hermes 的受管解释器与主服务的 Python 版本可以不同。桥接只加载 `wearing` 包本身，不能把主服务整个 `site-packages` 插到受管解释器的搜索路径；否则可能误用另一 Python ABI 的扩展模块。

## 上线核对

必须分别记录：匿名请求拒绝、真实 OIDC 两账号、原生 PKCE 单次交接、实例路由、真实模型/工具结果、跨租户拒绝、重启恢复、备份恢复、实际 App 行为。登录成功但租户尚未启动时产生的 502 不是业务验收通过。部署记录保留该阶段结果，不用后续成功覆盖失败经过。

公网证书由 Certbot 续期。私有服务证书有效期 90 天；续期与轮换需独立维护，不能把公网续期当作内部证书也会自动更新。单台物理机仍是故障单点，邀请测试不代表已具备大规模公开运营条件。
