# Jianying `jianying_data_sync_server` research (2026-09-07)

## Conclusion

`jianying_data_sync_server_*` is not a live synchronization interface for Jianying timelines, drafts, or media. It is a Windows local interprocess communication channel between the main application and `JianyingProTray.exe`, managed by `SystemTrayManager`, for login state, cookies, experiment settings, and cloud-transfer controls. It cannot provide Cut Workbench incremental editing of an open timeline.

The sample was local Jianying Pro `11.3.0.14362`. Apart from Qt transport documentation, command semantics came from tested local binaries and Jianying logs. Jianying has not published the protocol or guaranteed cross-version compatibility.

## Confirmed evidence

| Fact | Evidence | Confidence |
| --- | --- | --- |
| The name identifies a local named pipe, not TCP. | Running `\\.\pipe\` contained `jianying_data_sync_server__*`; `VECreator.dll` contained `jianying_data_sync_server_`, `QLocalServer`, and `QLocalSocket`. Qt documents named pipes for these on Windows. | Confirmed |
| The channel belongs to `SystemTrayManager`. | The pipe name in `VECreator.dll` was adjacent to symbols/log strings for `SystemTrayManager::updateABSettingsMapData`, `SystemTrayManager::SyncUserInfo`, `SendMessageToServer`, and `SendCommandToServer`. | Confirmed |
| The receiver is Jianying's tray process. | `JianyingProTray.exe` logs received data through `tray::ipc::LocalFileIPC::OnDataReceived`, then forwards it to `tray::core::AppCore::NotifyTrayCommand`. | Confirmed |
| Payloads are JSON command envelopes. | Tray logs show `{\"cmd\":\"…\",\"args\":\"…\"}`; `args` may be a JSON-encoded object inside JSON. | Confirmed |
| External draft import is a separate path. | `videoeditor.dll` contains `copy_draft_external`; `User Data/Log/draft_acion_watch.json` records that event and new draft metadata. The filename was not found in the `SystemTrayManager` command neighborhood. | Separation confirmed; complete call chain unconfirmed |

Transport references: [QLocalSocket](https://doc.qt.io/qt-6.8/qlocalsocket.html) explicitly describes Windows local sockets as named pipes; [QLocalServer](https://doc.qt.io/qt-6/qlocalserver.html) describes named local connection listeners.

## Identified private commands

These names come from symbols near `SystemTrayManager` in `VECreator.dll`; the first four categories were also observed in tray logs. They are private implementation details, not third-party APIs.

| Command | Observed purpose |
| --- | --- |
| `update_ab_settings_map_data` | Main application synchronizes experiment/AB settings to the tray; logs include `tray_transport_optimization_config`. |
| `sync_user_info` | Synchronize avatar, nickname, account identifiers, cloud capacity, and other user state. |
| `add_cookie` / `delete_cookie` / `sync_cookie` | Synchronize login cookies to tray web/service components. |
| `resume_cloud_upload` / `resume_cloud_download` | Resume cloud upload/download jobs. |
| `show_ballon_tip` | Show tray notifications. |
| `tray_quit` | Terminate the tray process. |

No command names were found for timeline segments, tracks, captions, media replacement, current draft state, or undo stacks. Pipe connectivity would therefore not justify sending guessed commands.

## Relationship to `127.0.0.1:7264`

The main process also listens on `127.0.0.1:7264`, but this is a different transport: TCP rather than the Qt `QLocalServer` named pipe. Read-only HTTP probes received no HTTP/DevTools response. Main logs also mention generic `IPCServer.cpp`, with no evidence linking the TCP port to drafts or timelines.

The supported conclusion is that `7264` is another unpublished internal TCP service with unknown purpose and framing, unsuitable for Workbench integration. Calling it a “data sync server” or “live editing API” lacks evidence.

## Official design and available interfaces

Jianying has a public [open platform](https://open.capcut.cn/), but its public pages are a developer console/plugin list. This investigation found no official Windows Jianying Pro documentation, SDK, or protocol for third-party reads/writes to the open timeline. Qt documentation explains transport only, not Jianying's private command semantics.

This matches the local architecture: tray account, cloud-transfer, and configuration synchronization belongs to `SystemTrayManager`; draft-import events go to `draft_acion_watch.json`; no stable editor command surface is exposed.

## Cut Workbench decisions

1. Do not integrate `jianying_data_sync_server_*`: it serves a different purpose and its private commands concern accounts, cookies, cloud transfers, and process lifecycle.
2. Do not treat TCP `7264` as available. Without protocol documentation and a side-effect-free handshake, do not guess or fuzz it.
3. Retain `jianying:live-local` / `sync.apply` as **an abstraction requiring a real Jianying host bridge**. Tray IPC cannot implement it.
4. The stable path remains safe draft copies while Jianying is closed. With the editor open, Workbench can plan, review, and queue, but cannot safely modify the current timeline directly.

## Verifiable next directions

- If the open platform supplies a desktop-editor plugin SDK to authenticated developers, integrate `jianying:live-local` through its formal protocol.
- Research into `7264` first requires vendor documentation or controlled capture with isolated test accounts/drafts. Private-protocol reverse engineering is not a cross-version Windows/macOS product foundation.
