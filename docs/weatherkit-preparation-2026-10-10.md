# Pajio WeatherKit 接入准备

2026-10-10 只读源码与官方资料核对。**尚未启用 WeatherKit、创建或读取其密钥、调用真实天气 API、构建天气版本或购买额外额度。** Apple Developer 已开通是用户提供的信息，本次没有进入账号后台核实具体 WeatherKit 开关。iPhone 签名与安装继续独立推进。

## 当前能复用什么

| 现状 | 源码位置 | 尚缺什么 |
| --- | --- | --- |
| Expo 57.0.26、React Native 0.86.3，已依赖 expo-location 57 | `clients/mobile/package.json` | 没有 WeatherKit 模块或服务适配 |
| 按钮触发一次前台定位，支持拒绝、超时、权限再核对；预览后可选择带入对话 | `clients/mobile/src/NativeConnections.tsx:71` | 天气应直接使用本次坐标，不要求用户先发一条聊天 |
| iOS Agent 本机能力已有 `location.read`，仅 App active 且已授权时执行 | `clients/mobile/src/native-action-runtime.ts:18`、`native-action-driver.ts:59` | 它不是后台持续定位，也不能保证用户睡觉时云端获得当前位置 |
| “今天”已有任务进展、今日日程、简报入口 | `clients/mobile/src/TodayPanel.tsx:40` | 没有天气卡片、更新/过期/归因状态 |
| 简报可选日程、待办、笔记、工作区、飞书 | `src/wearing/briefing_preferences.py:11`、`briefing_api.py:123` | 没有天气来源、天气 API 或天气额度；当前简报是持久 HTML，不宜直接塞进临时天气原始数据 |

对 `src/wearing`、`clients/mobile`、`tests` 的天气关键词检索没有发现已实现的天气数据接入。读取手机桌面的“天气”应用名称不代表天气能力已接通。

## Apple 当前要求

- **每月 500,000 次属于整个 Apple Developer Program membership**，不能按每个用户、App 或租户各算一份；未用完不滚存。原生与 REST 均需纳入该团队总量管理。[WeatherKit 官方说明](https://developer.apple.com/weatherkit/)、[账号服务说明](https://developer.apple.com/help/account/services/weatherkit)
- Swift WeatherKit 基础能力支持 iOS 16 起；部分新增信息要求更高系统版本。原生方案需 App ID 的 App Services 与 Capabilities 两处启用 WeatherKit，并把对应 entitlement/provisioning 纳入签名。开通 Developer 并不自动证明 App 已有天气权限。[启用指南](https://developer.apple.com/help/account/services/weatherkit)
- REST 方案需 Services ID、启用 WeatherKit 的私钥及 Key ID/Team ID，使用 ES256 JWT；私钥不可发到 App 或网页。应由受控服务请求 Apple，避免给可执行任意代码的租户 Agent 发团队密钥。[Services ID 与密钥](https://developer.apple.com/help/account/capabilities/create-a-services-identifier-and-private-key-for-weatherkit/)、[REST 认证](https://developer.apple.com/documentation/weatherkitrestapi/request-authentication-for-weatherkit-rest-api)
- 天气数据展示需要 Apple Weather 标识与数据来源法律链接。警报需带原发布机构和 Apple 详情链接，不能擅自改写其原文；普通天气摘要也不能省略归因。[归因要求](https://developer.apple.com/weatherkit/#attribution-requirements)、[WeatherAttribution](https://developer.apple.com/documentation/weatherkit/weatherattribution)
- 缓存只限暂时、有限且为改善 API 性能；不能建设长期天气数据库或批量预取。数据有效期取 REST `expireTime` / Swift `expirationDate`，不能自定一周缓存并继续当实时天气展示。[协议附件 8 §1.5–1.6](https://developer.apple.com/support/terms/apple-developer-program-license-agreement/)、[REST Metadata](https://developer.apple.com/documentation/weatherkitrestapi/metadata)、[Swift expirationDate](https://developer.apple.com/documentation/weatherkit/weathermetadata/expirationdate)

## 最小可落地方案

**建议首版用服务端 REST，先做“今天”的临时天气卡片，不改本轮签名目标。** 这是根据现有 Expo 与云端架构作出的工程选择，不是 Apple 要求所有 iPhone App 必须用 REST。

1. 用户在“今天”点“看看附近天气”，解释用途后请求已有前台一次定位；也可选择一个城市或跳过。拒绝定位不影响其他功能。不在首次登录强制索取、不默认精确后台追踪。沿用 Expo 57 的前台权限 API；天气需求接受系统近似位置。[Expo 57 Location](https://docs.expo.dev/versions/v57.0.0/sdk/location/)
2. 通过 Pajio 已登录连接请求固定天气适配接口。建议新增 `POST /api/weather/current`，只收坐标、语言、时区及位置选择方式，不接受任意上游 URL；这是**待实现合同**，当前不存在该路由。坐标放 body，访问日志不记录 body。复用 owner/身份校验及离线、账号切换/注销后晚回执丢弃规则。
3. Apple 私钥只放平台受控服务、最小权限读取；各 Core 通过内部鉴权访问天气适配，不能把私钥复制到每个用户 VM。已有注册 broker 不是天气 broker，不能声称复用它即已完成天气接入。
4. 第一屏只呈现当前温度、天气状况、当日高低温、地点层级和更新时间，附正确归因。一次请求按需取当前与日预报；地区未提供的分钟降水、警报不能显示为“无雨/无警报”。具体可用集合以官方 availability 与真实返回为准。[REST API 概览](https://developer.apple.com/documentation/weatherkitrestapi)
5. 按请求地点/数据集/语言/时区做有限内存缓存和同时请求合并，严格早于返回失效时间；登录用户的地点偏好仍按账号隔离。首版不跨用户合并精确位置，不记录位置轨迹，不将原始天气写任务、记忆、工作区或长期 HTML 简报。缓存过期且取新失败时显示“暂未更新”，不由模型补数字。
6. 天气显示与格式化不调用 LLM。后续要做“睡醒简报”时，可先在打开简报时单独加载即时天气卡片；若要把天气交给模型并长期保存派生内容，需先核对数据保留与增值产品归因，不能把普通提示词摘要自动当作获准长期留存的数据。

Swift 直连可以作为后续替代：创建本地 Expo module 封装 WeatherService，再用配置声明 entitlement；新增 Swift 代码需要重建原生包，Expo Go 和仅更新 JS 不能补齐。它减少服务端天气密钥链路，但仍共享团队额度，也不直接解决 Android/Web 和 App 关闭后的云端主动服务。本轮没有创建模块或编辑生成的 iOS 工程。[Expo Modules 官方步骤](https://docs.expo.dev/modules/get-started/)、[Expo 57 app config](https://docs.expo.dev/versions/v57.0.0/config/app/)

## 额度与落地验收

预算应统计平台实际发往 Apple 的请求、状态和重试，另加每账号节流、单飞请求、总量预警/停止线；不记录坐标与原始响应正文作为计量日志。团队其他 App 的用量不在 Pajio 本地计数里，要与 Apple 后台核对。不能把并发超时自动当免费请求，也不自动升级付费套餐。

作为容量算术示例，按每个活跃用户每天 4 次、30 天计算：1,000 人约 120,000 次；4,000 人约 480,000 次。后者几乎没有地区查询、失败重试、测试和团队其他 App 的余量。这是请求规划，不是已测计费口径或用户使用预测；首轮外测通常没有必要先买额度。

真正接通还需要：

- 确认正确 Team/Services ID/WeatherKit key；只授权天气所需能力，不开启付费。
- 实现受控服务、鉴权、额度计数、过期处理和卡片；初版无后台定位、无模型依赖。
- 用正式签名 iPhone 在国内网络实际请求：同意/拒绝/近似位置、换账号、离线、超时、429、缓存到期、昼夜归因、VoiceOver；核对数据集缺失显示。
- 用单次请求前后计量与 Apple 后台确认真实 quota 口径；不把 HTTP 200、模拟数据、单元测试或 Developer 开通当成完整天气验收。

本说明只有源码审计与准备设计，没有天气 API 或天气 UI 验收结果；因此不需要也没有为此重新运行 App 构建或修改当前真机签名流程。
