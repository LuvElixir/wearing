# Mac 原生客户端验收

2026-10-04，当前 Apple Silicon Mac。本次交付为 Tauri 2 桌面技术预览，连接本机 Wearing 服务；不是正式签名安装包，也不是已上线的云端客户端。

## 实际构建

- 源码：`clients/desktop/`，Tauri 2.12.1，npm/Cargo 锁文件已保存。
- 工具：Rust 1.96.0、Node.js 24.16.0、Xcode Command Line Tools。
- 构建：`npm run build -- --debug --bundles app` 成功，生成 Apple Silicon `.app`。
- 留给用户的程序：`.wearing/desktop/Wearing.app`；可执行文件 SHA-256 为 `85819b6aa73ef49d2ef9960eacceeb276976c949cca35a1281b7b08bbdd7275c`。
- 应用包含现有头像、字标、连接入口与依赖许可证材料；不包含 Python、Hermes、设备驱动、个人记录或模型凭据。

## 实际操作

| 场景 | 结果和证据 |
| --- | --- |
| 启动与连接 | 读取本机 URL 设置，验证服务后打开既有今天页，状态为「已连接」。最终页面见 [当前桌面](images/native-desktop-2026-10-04/desktop-ready.png)。 |
| 菜单快记 | 从笔记进入「记一下」，回到今天并聚焦书写区；未提交草稿保留。前台 ⌘⇧空格也已触发同一操作。 |
| 同一份记录 | 桌面创建合成笔记 `life_06ca002402e049d48406bba13aa6db30`（revision 1），网页修改同一条至 revision 2，桌面显示更新标题。见 [网页修改后桌面同步](images/native-desktop-2026-10-04/desktop-web-edit-synced.png)。 |
| 原件 | 系统文件选择器选取合成图片，保存 `life_70fb51f0502c4ff28ae81752e1bff452`；原件 ID `asset_eb8b8fb7d5e844bf848c83642571bf6f`。下载字节与源文件一致，SHA-256 为 `14292cba724687eff346e4c6f3c7d3325f1e33e796d93635bdcff2b20bc1e129`。见 [原件入口](images/native-desktop-2026-10-04/desktop-originals.png)和[独立原图窗口](images/native-desktop-2026-10-04/original-window.png)。 |
| 连接失败 | 在连接设置输入不可用的 8764 端口，页面显示可重试说明；保存配置仍是原来的 8765 地址，只有 URL，权限 0600。见 [失败反馈](images/native-desktop-2026-10-04/connection-failed-fixed.png)。 |
| 单独退出 | 实际点击 Wearing 菜单「退出桌面端」后，进程检查没有桌面可执行进程；本机 `/api/status` 的 `hermes.state` 仍为 `reachable`。随后重新打开应用并留在今天页。 |
| 合成数据收尾 | 两条本轮合成记录已通过正常移除流程归档，分别推进至 revision 3 和 revision 2，可恢复；没有清除真实记录。 |

截图中的紫色顶栏为捕获工具的标记，不是 Wearing 界面设计。后台全局快捷键注册成功，但合成按键未证明后台唤起；不将前台通过推定为后台通过。

## 运行与检查

本机服务以显式 `--engine-autostart` 运行，恢复已经安装配置的本机核心。该选项默认关闭，不安装新依赖，不替换手工外部引擎连接。客户端退出不影响服务；停止后端会结束后端自己管理的核心，这是不同的生命周期。

- 全量 Python：401 passed、18 skipped，1 个既有 Authlib 警告。
- 后续启动、引擎和媒体回归：37 passed。
- 桌面 Rust：9 passed，覆盖地址校验、配置原子替换/权限/符号链接与服务验证等边界。
- JavaScript 语法、Python CLI 编译、Mac 最终构建和 `git diff --check` 通过。
- 原生连接命令限制调用窗口和内置页来源，网页不能取得文件系统或 Shell 命令。原件导航限制在当前服务来源；配置不存模型密钥。

## 视觉收尾与范围

使用 Impeccable 进行一次结构检测，结果为空；独立 finish review 初次发现连接窗口页脚裁切。将默认内部高度从 650 调整为 740，保留页面自然滚动，重新构建并捕获同一失败状态。复核结果 `remaining: clear`、`disposition: ship`，适用本机技术预览。[设计记录](../design-native-desktop.md)保留已确认的材料与操作规则。

未验收：后台全局唤起、Windows/Intel Mac、正式签名公证/升级、远端生产登录、真实麦克风/相机、手机原生 App、系统分享/日历/通知、多端离线冲突。未恢复腾讯云 VM，也未新增云资源。
