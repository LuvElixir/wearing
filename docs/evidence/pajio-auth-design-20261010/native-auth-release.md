# 原生注册与认证页面发布证据

日期：2026-10-10。本文只记录已执行的控制网关发布和边界检查；真实用户注册、App 会话交换仍未验收。手机画面和系统认证窗口的视觉验收由主任务单独记录。

## 固定范围与版本

发布只包含以下 10 个文件，服务器逐文件 SHA-256 与冻结候选一致。原生 App 构建、Core 服务中的内嵌页面样式、IdP 主题、账号/邀请码记录及设备资源均不在此发布范围内。

| 文件 | SHA-256 |
|---|---|
| `src/wearing/cloud/auth_pages.py` | `854982d428e8563605280d55cbf316bec6c9fe37deff63f086717c878bef40e6` |
| `src/wearing/cloud/gateway.py` | `a129e0cf387b08e790e51aaed815a64cf670a2de96682db3de001499eb812fa2` |
| `src/wearing/cloud/join.py` | `c67ea7c5fd93269de085a3c5e70d987f8a3b66d572fff7d511bc644c374280cd` |
| `src/wearing/cloud/mobile_auth.py` | `2b77770e544bca3a844c18407f71edff3ba986af81c90c1ac0a8d16a01cbe9ab` |
| `src/wearing/cloud/native_enrollment.py` | `6caecf3a5bc2c544664c90433a6032f771be7da961f1f0d2db32159cd83e32c5` |
| `src/wearing/cloud/registration.py` | `9203de8f3e4ffca072b17e7d79cc8d245ee7230989aa54f248aa9c39718a4b9a` |
| `src/wearing/cloud/request_body.py` | `2dfbf3d2aa1607497239d58a4e784834adbe4e4d0664d2d9c364a11907da1eae` |
| `src/wearing/web/auth/auth.css` | `979077348fee2882ab904f86053eaf18b50a9e80c5ddbcdfe9e6179289d17bfb` |
| `src/wearing/web/auth/auth.js` | `4f570fff8c2641a082fe6306b92d2d679b214e22c6cdb13c185e7fbf96643eeb` |
| `src/wearing/web/pajio-wordmark.svg` | `d51db3a58563826d79788529c2bd6cf9a3aeabefa0d36e360456ad8d25f9466a` |

冻结 manifest：`c805484df4d45d5657888e8a631600564ae93c7750b04cf45b8f6c60cae15b9d`。受控 host helper：`a0e5a6eaeab7acc333efbf5dde95219ab3b791dbb34d4b448f868c9944331a88`；本机 runner：`dae05eff1abee9e920b4f1e6f35f863679538a5a470edc47cb2370e3c968844e`。

## 执行结果

1. 独立审批精确绑定 manifest、helper 和阶段。stage 先保存所有原文件，再逐文件原子替换；回读全部 10 个 SHA 正确。此时服务进程仍为原 PID。
2. 按顺序重启注册 broker、控制 gateway。最终分别为 PID 47989、47994，均 active/running，启动时间更新，服务用户与组保持原值。没有重启 IdP、用户 Core 或设备。
3. 最终只读核对：受保护模块、配置文件哈希、服务定义及数据库 schema/角色权限元数据与发布前相同。检查仅涉及元数据，没有查询或导出用户业务行。该发布没有数据库迁移。
4. 私有 broker 的两个 native 路由对空 JSON 返回 422 `invalid_request`；网关 verify/register/status/cancel 四个原生路由也返回同样拒绝。公开 HTTPS 的四个路由复核一致。畸形请求在操作创建前被拒绝，未使用邀请码、未创建账号。
5. 公开 `/join` 返回 200 并包含新平面认证页面标记和脚本引用；`/auth/art/auth.js` 返回 200，正文哈希与候选严格一致。记录了 CSP 存在、HTML UTF-8 解码成功；这些检查不替代浏览器视觉与 CSP 行为验收。

## 切换可用性

每 2 秒探测公开 `/join`，共 48 条回执：**47 次 200、1 次 502**。最后 8 次连续为 200。502 出现在切换期间，未隐藏或以重试结果替换。本记录只覆盖这次有限观察窗口，不表示长期稳定性或无中断发布。

## 恢复与证据边界

每阶段都有独立持久 intent 与完成回执，未知结果只允许查询，不自动重放。原文件备份保留在受限服务器目录 `/var/backups/pajio-native-auth/native-auth-20261010-v1/preimages`。显式 rollback 会先比较当前文件与候选/原像、验证备份，再恢复同一文件集合并重启同两个服务；不恢复数据库快照、不删除后续账号或会话。旧版本没有新原生注册恢复路由，因此发生回滚时，待确认注册的恢复能力需单独处理。

私有原始回执位于 `.wearing/on-prem/20261009/native-auth-release-20261010/`，不纳入公开文档。最终 `deployment-summary.json` SHA-256 为 `03b1d13861dbe867688a9dd75069ab58ebc72755ce49acf438f70da0fbb2b9e6`。这里仅保留文件版本、HTTP 状态、进程状态和验证范围；不包含密钥、令牌、邀请码、真实用户名、密码或原始响应中的身份材料。

**仍未验收：真实邀请码注册、真实账号创建、原生一次性交换成功及后续账号会话使用。** 完成态不能从源码测试、畸形请求拒绝或页面 200 推断。
