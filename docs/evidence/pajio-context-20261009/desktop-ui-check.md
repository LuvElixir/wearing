# Desktop native import acceptance — 2026-10-09

Root operated the isolated **Pajio Context QA.app** using CUA accessibility actions and screenshot-derived native coordinates. This record describes observed UI behavior, not a scripted DOM simulation. The WKWebView modal exposes a collapsed accessibility tree; coordinates use the actual 2360 × 1640 screenshot, and the file chooser uses native accessibility controls.

- App: `/tmp/pajio-desktop-qa-target-20261009/debug/bundle/macos/Pajio Context QA.app`.
- Isolated identifier: `io.luckyloading.pajio.desktop.chatimportqa20261009`.
- Service: `http://127.0.0.1:8892/`, identity `qa`, synthetic data only. No model or physical-phone action.
- Input: [合成选定聊天.zip](fixtures/合成选定聊天.zip), 546 bytes, three synthetic messages, two authors, one attachment declared but not imported.

## Observed sequence

1. Clicked **选择聊天 ZIP 或 TXT** in the desktop modal. The actual macOS `NSOpenPanel` opened. Used its Go to Folder sheet to select the fixture, then clicked Open.
2. Preview showed three messages, two authors, the original 2026年10月9日 10:30–10:32 timestamps without inferred timezone, and `附件/说明.txt` marked not imported. The [pre-confirmation audit](desktop-preview-audit.json) still contained only the three earlier iOS / ZCode POSTs; this desktop preview added no POST.
3. Selected **测试用户**, visibly checked, then clicked **确认导入 3 条消息**. UI reported successful import into the current identity.
4. The instance became unavailable to CUA before the next action; root reopened the same isolated app path. The cause of that window/process disappearance was not established. Reopened app automatically connected to 8892. From **连接与设置 → 导入选定聊天**, the same saved batch appeared. This verifies persistence through reopening; it is not recorded as a deliberate refresh shortcut success.
5. Opened the batch. Detail displayed both authors, `本人：测试用户`, batch ID `chi_93944870a13d452a9fb8b752fb0dd3c4`, and `message-1`, `message-2`, `message-3` with their synthetic text and original times.
6. Clicked **移除这批聊天**. UI presented a second confirmation and source/index deletion scope, noting existing generated content may retain references. Clicked **确认移除这批聊天** for this self-created synthetic batch.
7. UI reported **已移除这批聊天来源** and an empty batch list. A read-only check of the synthetic QA database confirmed body and summary null, body bytes zero, and zero message-index rows. The request-key tombstone remains.
8. Clicked the top-right close button. The modal closed and the main QA chat became visible; no parent settings modal remained open.

## Correlated service evidence

- POST: `2026-10-09T05:23:36.343662+00:00`, HTTP 200.
- Created batch: `chi_93944870a13d452a9fb8b752fb0dd3c4` at `2026-10-09T05:23:36.350998+00:00`.
- Stable request key: `7d79f823f6874bcd83da1317952b0291`.
- DELETE: `2026-10-09T05:26:12.042933+00:00`, HTTP 200.
- [Shared HTTP audit snapshot](desktop-flow-requests.json): shared QA audit, not exclusively desktop. Only the above POST / DELETE pair is attributed to this root desktop sequence by observed UI and timestamps.
- [Read-only deletion check](desktop-delete-check.json).

## Display follow-up and limits

Root found two display issues during this successful functional flow: missing body padding caused text to touch the modal edge, and the list displayed a raw ISO import timestamp. ZCode corrected both in `chat-import.js?v=6` / `pajio.css?v=20`. Root quit and reopened only this isolated QA app, then reopened the modal and visually confirmed the corrected body inset and spacing. ZCode separately verified the readable local import timestamp in the browser and added a formatting regression; root did not create another batch solely to repeat that display check. Message timestamps still remain faithful to the imported file.

The first part of this sequence began on the already-running pre-freeze page; after reopening, the then-current assets were loaded. It does not prove every intermediate bundle was the final frozen revision. Lifecycle / account / storage failure boundaries are covered separately by [independent real-module review](web-review-check.md) and behavioral regression. These clicks do not establish real WeChat compatibility, real account import, private remote login, or a production release.
