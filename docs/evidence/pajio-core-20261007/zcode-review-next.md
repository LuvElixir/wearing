# Web/Desktop follow-up · 2026-10-08

用户继续授权 ZCode 负责 Web/Desktop，App/backend只读；本文件由root工作记录提供，非外部资料。不要删改App/backend，不真实注销/外发/部署。保留dirty工作。

第十六轮实际审阅仍未通过：
1. gateway.py:417/494，CSRF来自 GET /auth/session 的 csrf，不存在 pajio-csrf cookie。测试应使用真实gateway合成ASGI响应，再驱动Web生产模块；不能给假cookie自证。
2. scoped-store真实业务键是 pajio:<64hex storage_scope>:wearing-chat-draft:v1:daily...，没有user_id。isOwned拼user_user_且includes不会清真实键；从可信session+bootstrap登记origin/user/tenant→storage_scope，精确前缀清理，其他账户保留。旧无归属凭据明确保留限制，不猜。
3. saveFence吞错，WearingStore.set失败仅返回false。必须确认受限凭证持久成功才能提交；登录失效后仍能找回，不能依赖成功业务bootstrap。凭证不进URL/日志。
4. registerWorkGate没有生产调用，只测试注册。store写入/语音/旧异步仍可能持续。冻结要同步提升generation，实际停止voice/send/polling，并阻止旧持久写回；启动在业务bootstrap前处理待查注销。当前start只打开设置触发不算启动恢复。不能全局冻结别的已切换账户。
5. not_submitted的重新查看按钮又queryStatus永远循环。需真实plan刷新；未知提交不自动重发，状态未知时业务不能假恢复。
6. validStatus以实际operator/App完整契约为准；不要只造符合自己校验器的数据。每项需实际模块联动测试，不能源码contains断言替代。

当前QA http://127.0.0.1:8891，合成fixture目录 /private/tmp/pajio-core-qa-jf1qwuko，root正在保留数据重启接以下新合同。收到就绪通知前勿写QA状态，8765不动。

随后继续Web/Desktop跟随App新增能力：
- briefing-preferences-contract.md：兴趣、重点、来源、条数、版本冲突、持久幂等；只读 BriefPreferencesPanel。
- workspace-text-edit-contract.md：md/txt编辑，imports原件另存，CAS、恢复版本、未知结果同key；只读 WorkspaceTextEditor/PersonalHub文件部分。
- health-history-contract.md：有界历史、状态变化、闭集隐私字段、报告SHA、预览与显式下载，不能声称后台持续在线或已发支持。
- native-sync-contract.md：仅App前台原生采集，Web/Desktop不能伪称能读iOS日历，可读现有同步来源与副本说明。
