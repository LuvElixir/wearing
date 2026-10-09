# 持久账户删除作业核心与操作者入口

2026-10-08。实现：`src/wearing/account_deletion.py`、`account_deletion_cli.py`、`account_deletion_fixture.py`。独立作业核心已实现并通过22项隔离测试；**未挂 App 按钮、未挂 gateway/API、未配置真实控制面/云删除适配器，因此不代表真实账户可注销或外测门槛已解除。**

## 登记与请求

```python
jobs = DeletionJobs(private_journal_path, initialize=True, mode='operator')
jobs.register(tenant_id, 'private', [user_id],
              owner_user_id=user_id, instance_id=instance_id)
plan = jobs.preview(user_id)
job = jobs.request(user_id, stable_request_key, plan['revision'])
receipt = jobs.run(job['id'], adapter=None)  # waiting / adapter_unconfigured
```

`private` 必须显式 owner，删除时要求全部成员（含inactive）只有本人、固定instance已登记。一个instance不能登记给两个tenant。`shared` 普通成员只生成 `leave_shared`，保留共同内容；shared owner需先转移。`unknown`、归属冲突、额外历史成员全部阻止请求。不能用活跃成员数量推断私有归属。

登记是独立操作者记录，**不是自动读取现有ControlStore得出的权威归属**。部署时必须与真实控制面事务/锁及实例资产清单接合。公共请求不得传classification/owner/成员列表/磁盘路径。当前没有向web开放该登记入口。

计划包含固定revision；变化后旧请求409。同user/request_key恢复同job，不会重做新作业；同key不同revision冲突。入作业后相关登记被锁，避免本journal内执行中改归属。真实控制面并发grant仍需生产adapter用同一控制面锁与冻结检查保护，不能把本journal锁当成跨系统锁。

## 生命周期与适配器契约

全账户 `freeze_account → revoke_user_devices`；每个个人租户依次 `freeze_tenant → revoke_credentials → revoke_devices → drain_actions → stop_instance → erase_primary → erase_indexes → erase_backups → finalize_tenant`；共享空间仅 `leave_shared`；最后 `finalize_account`。

- 每步先写入running并提交SQLite，再调用adapter。operation_id由job/plan/序号/阶段固定摘要产生；进程崩溃后复用同一编号，adapter必须查询/恢复原操作，不能重发未去重的外部销毁。
- adapter同步接口：`execute(Operation) -> Receipt`；Operation含user、scope快照、tenant/instance、phase、mode和固定operation_id。没有文件路径、provider凭据或客户端自由命令。
- `Receipt(op, 'done', evidence=<64hex>)`才能推进；`retry`需固定code；`retained`还需未来retained_until。错误编号/结构/模式不符均不推进，异常只存 `adapter_failed`，不保存异常正文/路径/token。
- 没有adapter固定 `waiting/adapter_unconfigured`；没有自动默认删除实现。
- `run_one`每job跨进程FileLock，第二操作者得到job_already_running。`run(max_steps=50)`有界顺序执行，waiting立即返回，重启/失败后再次run恢复原步骤；已成功步骤不会再次调用。
- `completed`只可能所有步骤已有合法done回执。供应商撤销失败、仍有在执行动作、备份保留未结束均不可completed。不同数据源分开记录；primary已清而backup保留，状态清楚可读。
- 本模块信任已安装的operator adapter为完成证据负责；它不接受浏览器上传“done”回执。尚无生产adapter、控制面迁移和冻结路由，因此不声称真实系统已能安全注销。

## CLI

独立入口 `python -m wearing.account_deletion_cli --journal <独立私有目录> [--mode operator|synthetic] <command>`：

- `init`：只初始化独立journal，拒绝采用含其他文件的目录。
- `register --tenant … --classification private|shared|unknown --owner … --member … --instance … [--revision …]`：operator登记。
- `plan --user …`、`request --user … --request-key … --plan-revision …`、`status --job …`。
- `resume --job …`：operator默认没有adapter，只返回未配置。
- `--mode synthetic fixture`：新建程序自己的临时合成数据，包括两个单人空间和共享空间；打印新fixture_root。
- `--mode synthetic resume --job … --synthetic-root <上述新fixture_root>`：只允许合成适配器；不能在operator模式使用该参数。

没有云资源删除参数、控制面DSN、实例路径或任意shell参数。当前不会调用任何云API。

## 临时文件系统适配器边界

`SyntheticDeletionAdapter.create(registrations)` 自己通过mkdtemp生成 `pajio-delete-fixture-*`，有模式/nonce标记。构造器拒绝任意目录、root软链和非私有目录；每次执行核对root inode及marker。业务注册的tenant ID映射为固定摘要目录，不进入文件路径拼接。

临时沙盒里的冻结/撤销/停止是**显式synthetic状态**，文件清除则确实对该沙盒的primary/indexes/backups执行。按dirfd、不跟随软链，拒绝硬链接/FIFO/跨设备与过深/超量目录；先检查再清除，不触碰共享或其他用户目录。finalize再次检查残留，不能根据旧步骤回执盲目成功。

合成effect记录与operation_id绑定。模拟“效果已发生但写入job回执前进程退出”，重新执行只取同一effect，不重复动作。其他路径完全不可由该adapter采用。它不能证明systemd进程停止、真正的OAuth撤销、云盘物理擦除或备份已清。

## 验证

`python -m pytest tests/test_account_deletion.py -q`：**22 passed**。涵盖精确个人/共享范围、owner/inactive成员/unknown拒绝、stale plan、请求幂等、登记执行锁、instance唯一、无adapter不completed、真实临时文件清除且其他字节保留、崩溃恢复、provider/inflight/retention等待、错误回执/脱敏、并发操作者、softlink/hardlink/FIFO/穿越/残留拒绝、CLI状态回读。测试禁止外部socket与子进程。

## 接入生产前必须补的软件

1. ControlStore所有权/冻结/删除请求的Postgres迁移和RLS、独立operator消费；新近身份验证与受限注销回执。现web角色不能改会员和路由，必须保留边界。
2. 真实adapter按固定登记停worker/relay、撤凭据/会话/推送与设备，验证停止及云卷/快照归属；本journal没有做这些外部动作。
3. operator协调原子冻结与授权版本；旧HTTP/WSS/在途操作/重启都拒绝恢复，不能靠文件锁覆盖多个服务。
4. 本地账号缓存清理、共享成员user-scope推送撤销、IdP关联/导出/备份保留的最终UI回执。日志仅保留必要作业证明，需明确journal自身数据保留/清理政策。

上述未完成事项已继续列在外测矩阵，不能将22项fixture测试改写成“账户删除已交付”。
