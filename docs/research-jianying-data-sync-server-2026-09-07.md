# 剪映 `jianying_data_sync_server` 调研（2026-09-07）

## 结论

`jianying_data_sync_server_*` 不是剪映时间线、草稿或素材的实时同步接口。它是 Windows 版剪映主程序与 `JianyingProTray.exe` 之间的本地进程通信通道，由主程序的 `SystemTrayManager` 管理，用于同步登录状态、Cookie、实验配置与云传输控制。它不能作为 Cut Workbench 对已打开时间线执行增量剪辑的接入点。

本记录以本机剪映专业版 `11.3.0.14362` 为样本；除 Qt 的传输层说明外，命令语义来自本机受测二进制和剪映自身日志。剪映没有公开该协议或保证其跨版本兼容。

## 已证实的证据

| 事实 | 证据 | 置信度 |
| --- | --- | --- |
| 该名称是本地命名管道而非 TCP 地址。 | 运行中的 `\\.\pipe\` 包含 `jianying_data_sync_server__*`；`VECreator.dll` 同时包含 `jianying_data_sync_server_`、`QLocalServer` 和 `QLocalSocket` 符号。Qt 官方文档说明，Windows 上 `QLocalServer` / `QLocalSocket` 使用 named pipe。 | 已证实 |
| 该通道属于 `SystemTrayManager`。 | `VECreator.dll` 中管道名字紧邻 `SystemTrayManager::updateABSettingsMapData`、`SystemTrayManager::SyncUserInfo`、`SendMessageToServer` 和 `SendCommandToServer` 的符号与日志字符串。 | 已证实 |
| 接收端是剪映托盘进程。 | `JianyingProTray.exe` 的日志将收到的数据记录为 `tray::ipc::LocalFileIPC::OnDataReceived`，再交给 `tray::core::AppCore::NotifyTrayCommand`。 | 已证实 |
| 消息载荷是 JSON 命令封包。 | 托盘日志显示形式为 `{\"cmd\":\"…\",\"args\":\"…\"}`；其中 `args` 可以是二次 JSON 编码的对象。 | 已证实 |
| 草稿外部导入是另一条路径。 | `videoeditor.dll` 含 `copy_draft_external`；`User Data/Log/draft_acion_watch.json` 会记录该事件和新草稿元数据。该文件没有出现在 `SystemTrayManager` 的命令邻域中。 | 已证实“分离”；未证实完整调用链 |

Qt 的传输层依据：[QLocalSocket](https://doc.qt.io/qt-6.8/qlocalsocket.html) 明确说明 Windows 的本地 socket 是 named pipe；[QLocalServer](https://doc.qt.io/qt-6/qlocalserver.html) 说明其监听命名的本地连接。

## 已识别的私有命令

以下命令名来自 `VECreator.dll` 中 `SystemTrayManager` 邻近符号，且前四类可由托盘日志观察到。它们是私有实现细节，不是对第三方开放的 API。

| 命令 | 观察到的用途 |
| --- | --- |
| `update_ab_settings_map_data` | 主程序向托盘同步实验/AB 配置；日志中包含 `tray_transport_optimization_config`。 |
| `sync_user_info` | 同步账户头像、昵称、账号标识与云容量等用户态。 |
| `add_cookie` / `delete_cookie` / `sync_cookie` | 向托盘 Web/服务侧同步登录 Cookie。 |
| `resume_cloud_upload` / `resume_cloud_download` | 恢复云上传或下载任务。 |
| `show_ballon_tip` | 让托盘显示通知。 |
| `tray_quit` | 终止托盘进程。 |

没有发现任何与时间线片段、轨道、字幕、素材替换、草稿当前状态或撤销栈相关的命令名。因此即使能连接该管道，也不应向它发送猜测的命令。

## `127.0.0.1:7264` 的关系

主进程同时监听 `127.0.0.1:7264`，但它与 `jianying_data_sync_server_*` **不是同一传输**：前者是 TCP，后者由 Qt `QLocalServer` 实现的命名管道。对 `7264` 发出的只读 HTTP 探测没有获得 HTTP/DevTools 响应。主程序日志还出现了通用 `IPCServer.cpp`，但没有把该 TCP 端口映射到草稿或时间线功能的证据。

因此当前只能下结论：`7264` 是另一个未公开的内部 TCP 服务；其用途和帧格式未知，不能用于 Workbench 集成。把它称为“数据同步 server”或“实时剪辑 API”没有依据。

## 官方设计与可用接口

剪映公开站点存在 [剪映开放平台](https://open.capcut.cn/)，但公开页面是开发者后台/插件列表；在本次调研中未找到面向 Windows 剪映专业版、可让第三方读取或修改当前打开时间线的官方文档、SDK 或协议说明。公开 Qt 文档只说明底层 IPC 传输，不能说明剪映的私有命令语义。

这符合本机架构：剪映把托盘进程的账号、云传输和配置同步放在 `SystemTrayManager`，把草稿导入事件记录在 `draft_acion_watch.json`，但没有暴露稳定的编辑器命令面。

## 对 Cut Workbench 的决定

1. 不接入 `jianying_data_sync_server_*`：用途不匹配，且私有命令涉及账号、Cookie、云上传下载与进程生命周期。
2. 不把 TCP `7264` 视为可用接口；在没有协议文档和无副作用握手的情况下不做猜测或模糊测试。
3. 保留 Workbench 的 `jianying:live-local` / `sync.apply` 作为**需要真实剪映宿主桥接的抽象**；它不能由上述托盘 IPC 实现。
4. 当前稳定路径仍是：剪映关闭时创建安全草稿副本；已打开剪映时仅能进行 Workbench 侧规划、审阅和排队，不能安全地直接修改当前时间线。

## 后续可验证方向

- 若剪映开放平台为已认证开发者提供桌面编辑器插件 SDK，应以该 SDK 的正式协议接入 `jianying:live-local`。
- 若决定研究 `7264`，必须先取得厂商协议或在隔离测试账号/测试草稿中进行受控抓包；该工作属于私有协议逆向，不能作为跨版本、跨 Windows/macOS 的产品基础。
