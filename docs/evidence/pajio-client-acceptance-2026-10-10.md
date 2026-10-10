# Pajio 测试账号与真实设备验收

2026-10-10，Asia/Shanghai。用户没有现成 Pajio 账号，明确要求先用测试账号验收。本轮使用隔离的 acceptance-a、专用 Pajio Acceptance iPhone Air 模拟器，以及独立 Pajio Remote QA macOS 应用。没有替换用户原有客户端、清空真实账号或使用真实私密资料。

## 实际完成的用户路径

| 路径 | 实际结果 | 边界 |
| --- | --- | --- |
| 公开登录 | App 和独立桌面 QA 包完成正式 IdP 登录，进入测试账户 | 合成账户，不是外部用户开户验收 |
| App ↔ Android 文件 | 工作区选择 → 发送 → 设备目录 → 取回 → 工作区查看；内容散列一致 | iPhone 模拟器，96 KiB 合成文件 |
| App ↔ Linux 文件 | 相同的双向用户流程通过，内容散列一致 | 同上，不替代断网/大文件边界测试 |
| App → Linux 输入 | 同坐标保存计数 3 → 4 → 5；中文输入、方向键滚动、双确认后实际交还 ACK | 不把原生滚动手势或表情精确字形计作通过 |
| 桌面 → Android | 真实飞书首启后的登录画面；开始操作 → Home → Android 启动器；双确认交还成功 | 未登录飞书账号或授权额外系统权限 |
| 桌面 → Linux 输入 | 同坐标保存计数 5 → 6 → 7；中文 `桌面验收42` 显示；滚轮实际到第 2/3 段 | 合成 Firefox 本地测试页，非用户网页 |
| 桌面 v58 暂停入口 → 交还 | 正式地址重新加载 → 我的 → 设备 → 查看并交还；进入后仍保持暂停，重新连接、双确认后收到设备实际交还 ACK | 独立 macOS QA 包；不等于 Windows 或其他浏览器通过 |

传输文件大小 **98,304 bytes**，SHA-256 **3abc1bd6f648681262fafcc1f6ed148ecf0982dcd52c49a8885bd94fda605b91**。公开 API 回执与取回内容分别保存在 `pajio-device-files-ui-20261010/receipts.json`、`linux-receipts.json`。

## 验收中发现并修复

- Linux `xdotool mousemove --sync` 在同坐标等待位置变化，阻塞串行抓帧，触发既有画面时效保护。保留权限、锁、超时与帧门槛，仅去掉四处不必要的同步等待。独立 X11 事件测试、B → A 精确部署及上述 App/桌面同坐标输入复验均已完成。详见 `pajio-device-files-ui-20261010/diagnostic.md`。
- App 私密会话暂停后改走“查看并交还”，不能直接普通恢复。新 iOS 模拟器构建实际验证成功，Android 构建通过但未在实体 Android 上补验。详见 `pajio-control-return-20261010.md`。
- 桌面 WebRTC setup 异常以阶段与固定枚举呈现，不回显原始私密错误；设备入口 v58 补齐状态、身份与设备快照检查。源码与真实事件回归见 `pajio-desktop-remote-20261010/root-v58-review.md`。B → A 仅更新两个静态文件，无服务重启；鉴权响应散列与冻结源码一致。实际桌面路径最终明确显示“设备已确认交还，Pajio 可以继续操作”，截图为 `pajio-device-files-ui-20261010/desktop-linux-return-confirmed.jpg`。

## 构建与证据

- App 全量 818 项、Web 最终 256 项测试通过；类型检查与项目本地 ESLint 通过。新增 Linux 输入定向组合 49 项、Core 交还保护 15 项通过。各套件范围不同，不相加作为一个全仓总数。
- `Downloads/Pajio-test-20261010/Pajio-0.2.0-20261010-control-return-fix-simulator.app` 已安装到专用模拟器并完成上述 App 验收。
- 同目录 `Pajio-0.2.0-20261010-control-return-fix-arm64-test.apk` SHA-256 为 `32a525399d5d40fb0ae588f24cbfb4e75009e3f50f01282bb2b153521edaf478`，保持 Debug 测试签名及 16 KB 对齐。不是公开发行包。
- 忽略目录内保留合成界面截图；失败截图 `app-linux-control.png`、`desktop-linux-save.png` 不记作通过。修复后截图使用独立名称，保留失败诊断历史。

## 不能宣称已完成的内容

本轮最终只读检查于 13:01:16–21（Asia/Shanghai）完成：A/B Linux 与 Android 四台均在线、`agent_ready` 且 `device_confirmed=true`，没有暂停、待确认控制、待复核或未清理的媒体会话。详见 `pajio-device-files-ui-20261010/linux-input-final-state.json`；这是一时点状态，不能替代长期稳定性。

部署与验收全窗口探测实际覆盖 **11:02:20–13:02:09（Asia/Shanghai）**，共 **11,654** 次：HTTP 200 为 **11,637** 次，HTTP 502 为 **17** 次（A 8、B 9）；结束时各租户连续 20 次为 200，Hermes `reachable`。其中 Core 文案单文件更新窗口占 7 次 502，其余 10 次属于较早部署窗口。原始逐请求记录保留在忽略的运维目录，未上传账户令牌或探测凭据。

物理 iPhone/Android、Windows 桌面、TestFlight/正式发行签名、真实第三方账户登录、48 小时稳定性、真实并发与完整恢复演练未由本轮证明。模型费用仍为应用侧估算，不是供应商最终账单。Core 单文件更新曾出现 7 次瞬时 HTTP 502，随后各实例通过连续可达检查，不能称零停机。

完整资源注销、带来源的候选记忆、Agent 私密凭据使用及自动运营工程仍见 [统一开发顺序](../plans/pajio-unified-delivery-2026-10-10.md)。本轮的真实远控与文件闭环不代表上述能力已经实现。
