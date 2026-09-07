# Windows 本地剪映自动剪辑安装包

这套安装包把当前已验证的本地链路包装成普通用户可执行的脚本：**剪映专业版 + 本仓库 + 一次安装**。工程、素材和草稿始终保留在本机；不会调用云端 VectCut，也不需要 `VECTCUT_API_KEY`。

## 它会安装什么

| 组件 | 用途 | 是否由剪映自带 |
| --- | --- | --- |
| Cut Workbench | 可编辑剪辑工程、版本、轨道与验收 | 否 |
| 本地 VectCutAPI | 将 Workbench 工程编译成新的剪映草稿 | 否 |
| FFmpeg / ffprobe | 审阅版渲染、时长与音视频流检测 | 否 |
| OpenCV / Pillow | 高频关键帧联系表与视觉验收 | 否，可跳过 |
| 剪映专业版 | 打开和继续人工编辑生成的草稿 | 是，用户需先安装 |

Agent 不需要内置 FFmpeg、视觉库或剪辑工具；只需支持 stdio MCP，并按下文导入生成的 MCP 配置。

## 安装前

1. 安装剪映专业版，并至少打开一次、创建后关闭一个空草稿。
2. 下载或克隆本仓库到本机并解压。若下载 ZIP，不需要预装 Git；安装脚本会在需要时通过 `winget` 安装 Git。
3. 打开 PowerShell，进入仓库根目录。

默认草稿目录是 `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft`。如果你的剪映草稿目录自定义过，安装时必须显式传入，脚本不会猜测或扫描其他磁盘。

## 一次安装

```powershell
PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\install-local-editing.ps1 `
  -InstallPrerequisites `
  -StartService
```

`-InstallPrerequisites` 仅在缺少依赖时使用 `winget` 安装 Git、Python 3.11+ 和 FFmpeg。若已安装，可以省略。默认安装位置为 `%LOCALAPPDATA%\CutWorkbench`，不会覆盖已有剪映草稿或 VectCutAPI 配置；需要重写本机配置时才传 `-ForceConfig`。

草稿目录自定义时：

```powershell
PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\install-local-editing.ps1 `
  -InstallPrerequisites `
  -JianyingDraftFolder 'D:\JianyingPro\User Data\Projects\com.lveditor.draft' `
  -StartService
```

安装完成后会生成：

- `%LOCALAPPDATA%\CutWorkbench\runtime\runtime-config.json`：本机 Workbench/VectCut/草稿目录配置；
- `%LOCALAPPDATA%\CutWorkbench\agent-mcp-config.json`：可复制到 Codex、Claude Desktop 或其他 MCP Agent 的服务配置；
- `%LOCALAPPDATA%\CutWorkbench\installation.json`：安装回执；
- `%LOCALAPPDATA%\CutWorkbench\service\`：本地 VectCutAPI 的受管日志与服务状态。

## 日常启动、停止与自检

每次重启电脑后，先启动本机自动建稿服务：

```powershell
.\scripts\windows\start-local-editing.ps1
```

检查所有关键依赖、草稿目录权限、本地服务和视觉验收包：

```powershell
.\scripts\windows\doctor-local-editing.ps1
```

对一个素材执行只读音视频流检查（不会转写、不会创建草稿）：

```powershell
.\scripts\windows\doctor-local-editing.ps1 -MediaPath 'D:\videos\demo.mp4'
```

停止脚本只会终止由 `start-local-editing.ps1` 记录的那个本地 VectCutAPI 进程：

```powershell
.\scripts\windows\stop-local-editing.ps1
```

## 首次真实草稿验收

在剪映中首次使用前，对任意至少 6 秒的本地视频运行一次冒烟测试。该命令会创建一个新的短草稿，不会修改原素材或现有草稿：

```powershell
.\scripts\windows\smoke-local-editing.ps1 -Source 'D:\videos\six-seconds-or-longer.mp4'
```

脚本会验证两段真实裁切、时间线连续性、源素材 SHA-256、调用本机 VectCutAPI 和草稿文件落盘。随后需人工在剪映专业版草稿库确认该草稿可见且可播放；“文件已生成”不等于“当前剪映版本可正常打开”。

## Agent 接入

将安装生成的 `agent-mcp-config.json` 中的 `cut-workbench` 条目导入你的 Agent 配置。它启动的只是本地 stdio MCP：工程修改写入 Workbench revision，`vectcut.execute` 才会通过 `127.0.0.1:9001` 新建一个可编辑剪映草稿。

本安装包不会直接修改 `draft_content.json`，不会覆盖原草稿，也不会切换到云端 VectCut。

## 已知兼容边界

- 自动建稿固定使用实测的 VectCutAPI 提交 `d14e70749c9331424ab816a402bb45417c50cf68` 和 `jianying_pro_10` 草稿模板。
- 因剪映版本和草稿格式可能变化，首次安装必须运行上面的真实草稿验收。
- 这是一条 Windows-first 路线；macOS 仍可按仓库主 README 的本地部署说明配置，但暂不承诺一键安装脚本。
- 不包含 ASR、TTS、云渲染或 AI 特效；它们是独立的可选能力，不是本地静音屏录剪辑的前置条件。
