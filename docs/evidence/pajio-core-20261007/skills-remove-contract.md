# 技能移除闭环 · 2026-10-08

App 路径：我的 → 技能 → 已安装 → 技能详情 → 移除技能 → 阅读当前身份范围 → 确认移除。预览和取消不修改文件。仅确认后调用真实移除；失败保留同一 operation_id 可重试，成功须核对完整回执以及技能已从新目录消失。

## 接口

`GET /api/skills/removal?id=<installed-id>` 返回：

```json
{
  "id": "documents/letter",
  "name": "letter",
  "revision": "<64位配置SHA256>",
  "package_revision": "<64位整包SHA256>",
  "operation_id": "<32位随机十六进制>"
}
```

`POST /api/skills/remove` 提交上面除 name 外的四项。沿用登录、身份、CSRF、Origin 边界；不接受 identity_id、source 或绝对路径。服务端只解析当前身份 runtime.home/skills 下的已安装包。

成功响应：

```json
{
  "removed": true,
  "id": "documents/letter",
  "operation_id": "<原operation_id>",
  "recovery_id": "<同operation_id>",
  "snapshot": {"revision": "<配置SHA256>", "installed": [], "catalog": []}
}
```

App 校验 removed 严格为 true、id/operation_id/recovery_id 精确一致，并确认 snapshot.installed 不再含该 id。不得收到任意200就先删UI。配置不变，因此 snapshot.revision 不要求变化。安装和启停接口保持兼容。

## 文件与运行保护

- 同身份 `.pajio-skills.lock` 串行安装/启停/移除。
- 移除同时持有该 Store 的 `BEGIN IMMEDIATE`，与真实任务 `reserve_start` 同一写入锁。当前身份处于 starting/running/waiting_for_approval/stopping/connection_lost/ambiguous 或已接收排队状态时返回423；完成后可重新确认。其他身份文件独立。
- 必需技能、auto_load 配置引用、内建 source 与 installed 重叠、包内嵌套技能或从另一技能包内移除子技能均拒绝。
- 配置 revision 和整包 package_revision 精确比较。整包摘要覆盖相对路径、目录、文件权限和内容，包括脚本/隐藏文件；最大20MiB、1000个文件。脚本改变也会409；不会运行包内脚本。
- 输入路径遍历、软链目录/文件、特殊文件、恢复目录链接均拒绝。catalog 原版、配置和其他技能不修改。
- 包通过同文件系统原子 rename 移到当前身份 `hermes/.pajio-skill-recovery/<operation_id>/package`，没有递归删除。receipt.json 在移动前落盘，记录原 id、配置/整包 revision、operation_id 和身份。恢复位置不会被 Agent 的 skills 目录发现。
- 移动后更新 skills 根目录 mtime，令运行时目录缓存发现变化。对已结束会话里的历史文字不作伪造清理。
- 移动后响应丢失或进程异常，原 operation_id 可由 receipt + package 恢复同一成功回执；不会重做移动。若技能后来重新安装，旧 operation_id 返回409，需要新预览。恢复目录保留供人工恢复，本轮未提供一键恢复或自动清理。

## 验证

- `tests/test_skills_api.py`：26项通过，覆盖原安装/启停兼容、整包冲突、软链/嵌套/自动加载/必需技能、全部活跃状态和排队、真实Store启动并发、丢回执后恢复、跨身份/CSRF、重新安装后的旧凭据拒绝。
- 其中实际固定版本 Hermes 子进程检查移除前可发现技能，移除后恢复副本不被发现；测试技能及数据库均临时创建。
- `clients/mobile/src/skills-model.test.ts`：6项通过，覆盖只读预览、精确提交、错误及伪成功回执、相同操作重试。
- App全量 TypeScript typecheck 和 SkillsPanel/model/test 定向ESLint通过。
- 本轮没有操作用户已安装的真实技能，没有改 Web/Desktop。原生模拟器点击验收由集成轮完成，不能用单元测试替代。

## Web/Desktop 同步

ZCode 只读上述 App 文件和本合同，在各自技能详情提供同样两步交互与回执校验。确认文案说明当前身份、后续任务与保留恢复副本；不得把远程任意错误正文直接显示，也不得将423当成已移除。出现未知网络结果时保留原 operation_id，用户可重试或刷新目录核对。
