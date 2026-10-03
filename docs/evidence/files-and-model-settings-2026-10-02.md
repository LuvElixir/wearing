# 模型设置与文件空间验收

日期：2026-10-02。执行环境：开发 Mac / macOS arm64。此记录只覆盖本轮已实际运行的功能。

## 模型设置

- Wearing 原生表单显示 DeepSeek、当前模型 `deepseek-flash` 与“已保存，留空保留原密钥”。浏览器未得到密钥值。
- 在浏览器点击“保存并应用”，使用现有模型且密钥留空；页面显示成功，本地引擎重新连接。保存前后 `.env` 字节哈希一致。
- 随后的真实文件任务仍使用 DeepSeek 成功完成。其他服务商列出入口，但本轮没有分别调用验收。
- 自动测试验证：凭据通过 stdin；错误和校验响应不含凭据；验证失败和写入失败保留或恢复原配置；运行中不能切换模型。

## 实际文件闭环

使用独立的开发验收对话数据库，向 Wearing 发出只在文件空间写三行 Markdown、再读回的指令。主对话仍为 0 条，已有草稿保留。

Hermes run：`run_f502c3c939bf486185c1bdff1fd80b60`。首次 SSE 查询看到了以下成功事件：

1. `list_allowed_directories`（seq 12）；
2. `tool_describe`（seq 14，上游工具描述助手）；
3. `write_file`（seq 16）；
4. `read_text_file`（seq 18）。

最终记录仍为 `completed_unverified`，没有调用“用户核对”接口冒充用户确认。开发验收另行核对了磁盘文件及浏览器真实下载结果。

产物：`workspace/Wearing-第一份文件.md`，89 bytes。SHA-256：`26a422f899c01e99be4c81a0c1cecb892f7c59a7c641bdc29d70ee69e28b48b6`。浏览器下载文件与磁盘内容逐字节一致。

注意：Hermes SSE transport 缓冲保留 300 秒，过期后无法重放完整工具事件。本记录的工具字段来自本轮首次读取；Wearing 当前没有持久保存完整 SSE。后续接入电脑控制前，应补事件消费与证据保留，不能依赖延迟查询还原动作。

## 自动化与界面检查

52 项 pytest 通过，包含实际 pinned Hermes 适配器和 Filesystem MCP 的非模型集成测试；Node 动画生命周期检查通过。文件集成测试验证六项工具的精确筛选、实际写入与读回、目录外读取/写入拒绝、符号链接和 `..` 路径拒绝、其他 MCP 不会自动启用。下载接口返回附件，HTML 文件不直接执行。最终重启 Wearing 与引擎后，文件能力重新发现成功；原文件 run 仍返回 HTTP 200 / completed，文件和主对话数据均保留。

实际桌面浏览器已验证模型表单、保留已有密钥保存、文件列表与下载。

- [模型设置截图](screenshots/wearing-model-settings-20261002.png)
- [文件交付截图](screenshots/wearing-files-20261002.png)
- [结构化证据](files-and-model-settings-2026-10-02.json)

## 边界

此能力是独立目录的文本文件操作。不是系统级沙盒，不包含桌面操控、手机、邮箱、支付或云端任务。写入会覆盖同名文件，尚无历史版本或单次写入审批。Windows、另一台 MacBook Air、小米 6X 和其他模型提供商尚未实机验收。
