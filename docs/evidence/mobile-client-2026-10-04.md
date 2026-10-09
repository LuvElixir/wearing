# 手机客户端实际验收 · 2026-10-04

本轮新增 `clients/mobile`（Expo 57.0.26 / React Native 0.86.3），用官方 Expo Go 57.0.9 在小米 6X Android 9 上运行。**没有 Wearing 独立 APK/IPA；iOS 仅运行资源导出。**

## 隔离与方法

- 验收服务：本机回环 8766，数据在 `.wearing/qa/mobile-client-20261004`，模型入口设为不可用的隔离地址，`local_devices=False`。
- 网页适配预览 8788；手机通过既有授权 USB reverse 访问服务与 Metro 8081。
- 相机、麦克风由用户本轮明确授权。录音选「本次运行允许」。原件只在手机和 Mac 隔离目录，关闭整理（`organize=false`），没有转写、模型发送或真实对话消息。
- 相机/录音原件不纳入仓库；证明截图不含相机现场画面。测试服务数据保留可复查。

## 实际结果

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 网页适配离线文字/图片 | 断开服务、写入、重新打开后两条仍在；回连各生成一条唯一记录 | `offline-reopened.png`、`offline-original-reopened.png` |
| 网页图片原件 | 49,174 bytes，上传下载 SHA-256 与合成输入一致 | `14292cba724687eff346e4c6f3c7d3325f1e33e796d93635bdcff2b20bc1e129` |
| 同一笔记跨端编辑 | 手机布局改后，原网页同 ID revision 2；再造并发冲突到 revision 3，拒绝覆盖并保留当前输入 | `main-web-shared-record.png`、`edit-conflict-fixed.png` |
| 日程创建 | 用原生布局网页适配创建日程，出现在共享安排 | `mobile-agenda-fixed.png` |
| 真机 SQLite 离线恢复 | 移除仅 QA 8766 的 USB reverse；新建文字；force-stop Expo Go 后重开仍有 1 条；恢复连接后恰好一条服务端记录 | `phone-offline-reopened.png`，`life_03564452fa1b457291b56e5563d0e8c9` |
| 真机相机 | 系统相机拍摄、完成后复制进应用私有 originals；3000×4000 JPEG 1,201,532 bytes；后续成功上传 | 同一 capture 保存于隔离服务 |
| 真机录音 | 开始、停止、私有 m4a 留存；AAC mono 44,100 Hz，11.330771 秒，93,503 bytes | ffprobe 元数据验证；未转写 |
| 真机媒体重开/补传 | 上传失败后强制结束、重开，修复后重试成功，照片与录音归于同一唯一记录 | `phone-media-synced.png` |
| 记录继续聊（现代浏览器） | 链接携身份、ID、revision；原网页显示准确标题与记录上下文，消息仍待发送 | `mobile-context-fixed.png` |
| 记录继续聊（小米内嵌 WebView） | **未通过**：可见页面外壳，但记录上下文与交互初始化未正常完成；设备 WebView 为 74.0.3729.136，需专项兼容处理 | 设备 `dumpsys webviewupdate` 与实际元素观察；不能用现代浏览器结果替代 |

## 真机发现并修复

1. SDK 57 `File.copy` 为异步。之前立即读 `exists/size` 会误报未保存；改为等待复制完成，复拍通过。
2. 私有原件以 UUID 存储，Android `File.type` 可能为空。Expo fetch 的 Blob 标头会覆盖显式 MIME，引发 native headers 类型转换失败；native transport 改为传原件 ArrayBuffer，保留调用方 MIME。SDK 本身也会缓冲 File，此修改没有增加第二套永久原件。修复后旧队列原件直接补传成功。

## 构建与检查

- TypeScript：通过。
- 核心测试：15 passed，包括响应丢失幂等、原件续传、身份切换、并发同步、限额、原子队列、凭据续期、错误文案真实性及对话链接。
- Web export：通过，`index-a29945586dd21bfb29252211fcf20706.js`。
- Android Hermes export：通过，`index-ddae34e37b7cdcd618d72ff5b538683c.hbc`。
- iOS Hermes export：通过，`index-ae988b1eef4e09dce12497de43daa031.hbc`。
- Android 原生工程/Manifest 已生成检查，权限和网络例外见 mobile-client.md；Expo Go 宿主权限不等于正式 release Manifest 验收。
- `node --check` 根 app.js/life.js 与 `git diff --check` 通过。
- source/export SHA-256 清单保存在隔离目录 `build-manifest.json`。
- 依赖审计仍有 24 项（7 moderate / 17 high），发布前必须处理；未执行主版本回退式强制修复。

## 完成边界

UI 指定三项修复经独立复核为 `disposition: ship`，仅是该界面范围，见 [复核表](mobile-client-design-review-2026-10-04.md)。

待完成：旧 WebView 对话兼容、独立 Android APK、iOS 真机、系统分享/日历/通知、已有记录离线编辑合并、正式登录/签名/更新、安全与许可审计。Expo Go 开发预览依赖 Mac Metro 和 USB，不代表脱离电脑即可长期使用的正式 App。未恢复云机、未产生新的云资源费用。

验收后将手机切回实际本地 Wearing 8765。QA 与真实服务身份/队列分区，无测试记录迁入真实服务。临时 8766/8788 服务及 QA USB reverse 已关闭；8765 本地服务、8787 网页代码预览、8081 Metro 和对应 USB 连接保留。

## 原件元数据

```json
{
  "record_id": "life_a10f42d3bb8c4118bf44f984ec21269f",
  "revision": 1,
  "capture_state": "saved",
  "assets": [
    {
      "id": "asset_9e886ca5628445bf867e9321de898749",
      "name": "45933321-47f4-4b1c-b57b-e93cf28f325e.jpeg",
      "mime": "image/jpeg",
      "size": 1201532,
      "sha256": "e689d2261abb0f6fe7d76534a2aedbab67015f5a053d6191a579371126c011b0"
    },
    {
      "id": "asset_813522dd5f1941eb996fb679d6014241",
      "name": "随口说的.m4a",
      "mime": "audio/mp4",
      "size": 93503,
      "sha256": "b71fe8672fc64c941a03c47b93faac656c95dfb4b876d99daed335bbbb070df1"
    }
  ],
  "no_model_organization": true
}
```

![原生端同步结果](images/mobile-client-2026-10-04/phone-media-synced.png)
