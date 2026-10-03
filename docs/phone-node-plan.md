# Wearing：手机与通信接入方案

更新：2026-10-02。首台手机确定为 Android 9 小米 6X，可 USB 连接；闲置 MacBook Air 是另一台电脑，芯片/系统待检测。手机不插实体卡。主流 Windows/macOS、Android/iPhone 作为适配目标，按驱动和权限条件分别验收。已实现多手机注册、资源路由、暂停/恢复与中文原生输入。小米 6X 已实测；详见[新验收记录](evidence/android-multiphone-2026-10-02.md)。

当前可执行的准备步骤见[接入指南](getting-started.md)。

## 两种能力分别解决

| 能力 | 资源 | 实际验收 |
| --- | --- | --- |
| 运行和操作 App | 无卡真机、云手机、远程托管设备 | 安装、登录、读界面、操作、核对结果、重连与接管 |
| 电话和短信 | 适用的可编程通信服务或独占运营商号码路线 | 号码获得、归属、收发、保号、找回与目标用途兼容性 |

通过网络使用手机 App 与本机能否插 SIM 是不同条件。某个 App 若要求手机号或特定设备能力，就把它作为该 App 的接入依赖，单独解决并验证。

## 手机控制连接器

本地 Mac/Windows 可通过已有设备工具连接手机，远程手机则由所在环境的接入端提供能力。Agent 的运行位置与设备所在位置分别配置。

现有候选：

- [Mobile MCP](https://github.com/mobile-next/mobile-mcp)：移动设备的界面读取、截图、输入和操作工具。
- [scrcpy](https://github.com/Genymobile/scrcpy)：安卓屏幕观察与人工控制，文档支持 USB/TCP/IP 及 macOS/Windows/Linux。
- [Appium UiAutomator2](https://github.com/appium/appium-uiautomator2-driver)：安卓重复操作与自动化验收。
- [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM)：手机视觉任务执行候选。

具体路线固定机型、系统、工具版本与目标 App，验证连接、操作、权限、睡眠/锁屏、重连、重启与人工接管。后续需让手机与用户接管共用执行锁，交还后读取当前状态；当前已有同一 OS 用户下跨 Wearing 数据目录的分设备锁，但用户本人、其他软件和其他 OS 用户并不受此锁控制。

## 当前不插卡条件下的通信路线

1. **可编程通信号码。** 服务商承载号码，通过 API/Webhook 接入 Wearing。先验证大陆用户能否申请、所需材料、号码类型、语音/SMS 功能和保号成本，再测试具体用途。
2. **目标服务的账号验证。** 单独检查平台接受的号码与认证方式；通信号能收普通短信不代表该网站的验证短信能到达。
3. **独占运营商号码/托管路线。** 如果目标任务必须使用移动运营商号码，调查用户实际可取得、可持续控制和可找回的独占资源及服务条款。尚未确认可用提供方，不列作已解决能力。
4. **eSIM。** 仅在设备能力、本人资格、首次激活及实际使用条件都得到确认后才成为候选。当前不作为默认方案。

Twilio 文档显示收到短信后可向应用的 webhook 发送消息事件，说明通信与本地实体卡可以分离；它不能证明用户已具备开户资格，也不能证明所有验证码可用。[消息 Webhook](https://www.twilio.com/docs/usage/webhooks/messaging-webhooks)

阿里无影 FAQ 明确不支持发短信，因此云 Android 的设备能力与通信能力仍要分别验收。[无影 FAQ](https://help.aliyun.com/zh/ecp/cloud-phone-faq)

## Root 的位置

Root 可纳入特定机型的可选工程方案。执行前需要明确任务、机型/版本、解锁条件、数据清除影响、备份和恢复流程；执行后重新测试所有目标 App 与远程维护。

设备完整性检查可能反映 Root 等状态，具体 App 是否接受由其实际行为决定。它不产生一个新的运营商号码，也不替代账号资格。[Android Play Integrity](https://developer.android.com/google/play/integrity/verdicts)

本轮只明确方案结构，没有授权或执行 Root、解锁、刷机或数据清除。

## 每条接入路线最终交付

条件检测 → 资源准备 → 必要人工步骤 → 自动安装/配置 → 连接器授权 → 真实任务验收 → 断线/重启恢复 → 长期维护与退出。

保留哪些步骤确实自动化、哪些需要本人处理的证据。待第二套适用设备或用户复现后，再将路线列为已验证接入包。

工具细节与先前测试设想保留在[手机控制研究](phone-control-research-2026-09-30.md)，当前产品主线见[整合总方案](implementation-blueprint.md)。
