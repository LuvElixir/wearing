# Personal Agent：Windows、支付卡与视觉研究记录

核查日期：2026-09-30。条件：大陆常住用户，没有海外手机号、海外银行卡、U 卡或境外居留。当前完成公开资料核查与视觉概念；没有租机、开户、上传身份资料或付款。

本文件是具体供应商与报价的研究记录；当前产品按用户条件匹配资源连接器，已有闲置 MacBook Air 可作为验证资源。以下候选不代表通用设备配置或已经办妥的账号。[当前整合方案](implementation-blueprint.md)

## 调查时的候选

- 云电脑候选 VPS Mart Basic：4 核、8 GB，按月付 18.99 美元。采用该连接路线时，需先检验持续桌面会话与 Agent 驱动。
- 支付优先核实 UPay Premier 446614。已找到具体卡种、费用与申请流程，仍需确认大陆常住地址和真实证件适用性。
- 当前产品名称已确定为 Wearing，视觉已选第 1 个钴蓝卷袖角色；小标志继续简化。工程路线以[落地总方案](implementation-blueprint.md)为准。

## Windows 的真实月付成本

| 服务与配置 | 月付标价 | 授权与 IP | 判断 |
| --- | ---: | --- | --- |
| VPS Mart Express Plus：3 核 / 6 GB / 100 GB SSD | $14.99 | Windows Server 授权、1 个独立 IP | 较低预算候选 |
| VPS Mart Basic：4 核 / 8 GB / 140 GB SSD | $18.99 | Windows Server 授权、1 个独立 IP | 首轮推荐候选，性能待测 |
| Hostwinds Unmanaged Windows：2 核 / 4 GB / 75 GB | $30.99 | Windows VPS 套餐 | 对照候选 |
| Hostwinds Unmanaged Windows：4 核 / 8 GB / 150 GB | $62.99 | Windows VPS 套餐 | 当前价格优势较小 |

VPS Mart 已在真实页面切换 **1mo** 并读取价格。默认页面是长期付款报价，不能直接引用为月付。Express Plus 和 Basic 均标明无设置费；机房选择、税费及最终订单仍需检查。来源：[VPS Mart](https://www.vps-mart.com/Windows-VPS)、[Hostwinds](https://www.hostwinds.com/vps/unmanaged-windows)。

Cloudzy 的 Windows 页面存在较低的推广价，但说明使用试用授权或自备授权；Contabo 则需要加购 Windows 授权，故没有把二者的主机基础价列成可长期使用的完整 Windows 成本。来源：[Cloudzy](https://cloudzy.com/windows-vps/)、[Contabo](https://contabo.com/en-us/windows-servers-vps/)。

8 GB 方案相对 $89 的 Mac，主机标价少 $70.01/月，约 79%。此比较不包括模型、税费或额外网络服务。Windows Server 可以提供图形桌面，但不是 Windows 11；服务器 IP 也不会变为住宅 IP。

### 租机后的最小验收

1. 验证底座、浏览器工具、Windows 原生桌面驱动确实兼容。
2. 打开实际所需网站，保持登录状态；进行不涉及真实付款的任务。
3. 人类断开 RDP 后，Agent 仍能截图、输入、处理系统弹窗并继续任务。
4. 人工接管时停止 Agent 输入，交还后能恢复；浏览器与任务状态可追溯。
5. 重启后检查桌面、网络、任务、浏览器资料恢复。

API 与浏览器自动化可优先承担适合的业务动作，桌面视觉操作按实际成功率接入。系统选择不预先决定模型厂商。

## U 卡候选与证据强度

### 首要核实：UPay Premier 446614

这里是 **upay.com**，并非另一家 UUPAY。官方限制页按卡种分别列举受限国籍：Premier 未列中国，Platinum 493875 则列有中国。这支持将 Premier 列入候选，但不能由此推断大陆常住地址一定可申请。来源：[卡种与地区限制](https://support.upay.com/hc/en-us/articles/26613460878620-Restricted-Prohibited-Countries-List)。

费用表列出 Premier 开卡 10 USDT、充值 2%、无月费/年费，发卡国家新加坡，SGD 卡币种并标注 USD Settlement。跨币种实际结算成本需另外确认，不能将 2% 当作所有支付的总成本。表内宣传支持 ChatGPT、Claude、Apple Pay、Google Pay 和 3DS，仍需独立核对目标商户资格与实际支付结果。来源：[官方费用表](https://support.upay.com/hc/en-us/articles/14954332664732-Virtual-Card-Fee-Structure)；本地留存 [费用图](research-evidence/upay-virtual-card-fees.png)。

官方认证步骤要求选择居住地区、证件签发地与类型、上传证件并进行活体检测。卡申请还需姓名、电话、邮箱和完整地址；教程把支付开卡费放在提交持卡资料之前。应先确认资格与被拒退款规则，再进入付款步骤。来源：[认证指南](https://support.upay.com/hc/en-us/articles/14176919893660-Identity-Verification-Guide)、[申请教程](https://support.upay.com/hc/en-us/articles/13979224012444-Card-Application-Tutorial)。

尚需官方明确答复的完整问题，已整理为可直接使用的文本（未发送）：

> 我是中国大陆国籍，长期居住在中国大陆，使用真实大陆地址，没有境外居留或海外银行卡。现在能否新申请 Premier 446614？可用大陆身份证还是必须护照？能否使用 +86 手机号？是否需要境外地址或额外居住证明？若审核不通过，开卡费如何退回？目前是否存在外汇转换、跨境、拒付及退款费用？

资格确认后的路线：完成真实身份验证 → 申请指定卡种 → 核对支持资产与充值网络、以小额验证 → 在符合账户条件的商户测试支付 → 核对扣款和续费。充值指南在卡页提供币种与金额选择，支持哪些网络以实际充值地址页为准。来源：[充值指南](https://support.upay.com/hc/en-us/articles/10848476475036-Card-Collateral-Recharge-Guide)。身份验证和活体步骤需要开户人本人完成。

### 备选研究结果

| 候选 | 本轮发现 | 当前判断 |
| --- | --- | --- |
| WasabiCard | 搜索缓存曾显示大陆护照；当前文档已改写，具体国籍、居住地、区号资格取决于卡 BIN 配置 | 不能依据过期缓存承诺大陆可开卡，保留次级候选 |
| Infini | 新的 KYC 限制名单未列中国，但另一份当前可访问的认证指南仍写明不要提交中国大陆地区 | 官方资料存在冲突，需澄清后才进入开户候选 |
| PokePay | 官方服务限制页列中国 | 排除当前路线 |
| UUPAY | 较新的官方文章说明当前不支持大陆 KYC | 不采用旧文章的开卡推荐 |

WasabiCard 的通用费用页列 USDT 换 USD 1.5%、账户到卡充值 1%，部分卡种还涉及跨境或小额交易费；外部 USDT/USDC 提现列 5%。完整成本取决于卡种和进出金方式，目前不足以认为比 UPay 更合适。来源：[持卡人接口与资格字段](https://wsb.gitbook.io/wasabicard-doc/api/card/card-holder)、[费用说明](https://wasabicard.com/en/help-center/articles/15501873)。

Infini 资料：[KYC/KYB 限制列表](https://help.infini.money/en/articles/16211782-infini-kyc-kyb-restricted-countries-and-regions-list)、[认证流程](https://help.infini.money/zh-CN/articles/13126715-身份认证流程-含kyc-kyb)。排除项来源：[PokePay 服务限制](https://pokepay.com/hk/service_restrictions.html)、[UUPAY 新版说明](https://uupay.com/zh-cn/blog/comprehensive-guide-to-crypto-card-fees-and-application/)。

### 对产品整合的影响

支付接入按具体卡种和商户能力记录，不假定一张卡包办订阅、广告、收款及交易。Google Ads 官方说明预付卡不能用于自动付款；仍需确认所选卡实际分类和账单地区可用方式。网店结算与投资账户继续作为独立资源推进。来源：[Google Ads 支付方式](https://support.google.com/google-ads/answer/2375433?hl=en)。

## 产品定义当前状态

核心关系已明确：属于用户的行动者，同时也是用户向外延伸的另一个自己。需求、产品结构与推进建议见[产品定义](product-definition.md)。产品名称为 Wearing，视觉已选第 1 个钴蓝卷袖角色；详见[VI 工作区](../design/vi/README.md)和[落地总方案](implementation-blueprint.md)。
