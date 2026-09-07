# macOS / Linux 本地剪映自动剪辑安装包

这套脚本把本地链路封装为一次安装：**Cut Workbench + 本地 VectCutAPI + FFmpeg/ffprobe + 剪映草稿目录**。服务只绑定 `127.0.0.1:9001`，不使用云端 VectCut Key，也不会启用 ASR。

## 平台边界

| 平台 | 安装脚本 | 可验证内容 | 最终剪映验收 |
| --- | --- | --- | --- |
| macOS | 支持 | 本地服务、草稿落盘、媒体流、视觉验收依赖 | 必须在剪映专业版草稿库确认可见、可播放 |
| Linux | 支持 | 本地服务、草稿落盘、媒体流、视觉验收依赖 | 无原生剪映专业版客户端，不作 GUI 验收承诺 |
| WSL | 支持用于测试 | 同 Linux；可验证脚本、服务和文件格式 | 不能替代 Windows/macOS 剪映 GUI 验收 |

生成草稿文件不等于当前剪映版本可以打开。真正使用前必须在装有剪映专业版的 macOS 或 Windows 机器上跑一次真实草稿冒烟测试。

## 安装前

1. macOS：安装剪映专业版，并至少打开一次、创建后关闭一个空草稿。默认草稿目录为 `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft`。
2. Linux/WSL：准备一个已有且可写的目标草稿目录，并在命令中通过 `--jianying-draft-folder` 显式传入。不要让 WSL 直接指向或修改 Windows 正在打开的剪映草稿库。
3. 准备 Python 3.11+、Git、curl、FFmpeg（含 `ffprobe`）。脚本可尝试用 Homebrew、apt、dnf 或 pacman 安装依赖。

安装状态默认保存在：

- macOS：`~/Library/Application Support/CutWorkbench`
- Linux/WSL：`${XDG_STATE_HOME:-$HOME/.local/state}/cut-workbench`

脚本以 `bash` 调用，无需依赖文件的可执行位。

## 一次安装

macOS（使用默认剪映草稿目录）：

```bash
bash ./scripts/posix/install-local-editing.sh \
  --install-prerequisites \
  --start-service
```

Linux/WSL（必须指定已有草稿目录）：

```bash
bash ./scripts/posix/install-local-editing.sh \
  --jianying-draft-folder /path/to/existing/jianying-drafts \
  --start-service
```

如 Python 3.11+ 不在 `PATH`，显式指定解释器：

```bash
bash ./scripts/posix/install-local-editing.sh \
  --python /path/to/python3.11 \
  --jianying-draft-folder /path/to/existing/jianying-drafts \
  --start-service
```

安装会创建：

- `runtime/runtime-config.json`：仅指向本机回环 VectCutAPI 与指定草稿目录；
- `agent-mcp-config.json`：导入 Codex、Claude Desktop 或其他 stdio MCP Agent 的条目；
- `installation.json`：安装回执与固定的上游版本；
- `service/`：本地 VectCutAPI 的状态与日志。

默认不会覆盖现有 VectCutAPI 或运行时配置；只有明确传 `--force-config` 才替换这些配置。它也不直接编辑已有草稿的 `draft_content.json`。

### Ubuntu 22.04 / WSL 的 Python 限制

Ubuntu 22.04 的系统 `python3` 通常是 3.10。即便使用 `--install-prerequisites`，脚本也会在创建任何虚拟环境之前明确拒绝低于 3.11 的解释器，而不是悄悄生成不兼容环境。请自行安装 Python 3.11+ 后用 `--python` 指向它，再运行安装。

## 日常操作与自检

重启后启动本地服务：

```bash
bash ./scripts/posix/start-local-editing.sh
```

检查 Python 环境、FFmpeg、草稿目录、固定 VectCut profile、服务健康状态和可选视觉验收包：

```bash
bash ./scripts/posix/doctor-local-editing.sh
```

对媒体做只读流检查：

```bash
bash ./scripts/posix/doctor-local-editing.sh --media-path /path/to/demo.mp4
```

停止脚本只会终止由 `start-local-editing.sh` 写入状态文件的那个 VectCutAPI 进程：

```bash
bash ./scripts/posix/stop-local-editing.sh
```

## 首次真实草稿验收

选取一个至少 6 秒的本地视频，执行：

```bash
bash ./scripts/posix/smoke-local-editing.sh --source /path/to/six-seconds-or-longer.mp4
```

该命令会创建一个新短草稿，验证两段真实裁切、时间线连续性、源素材 SHA-256、VectCutAPI 响应和草稿文件落盘。它不修改源素材或已有草稿。

在 macOS 上，随后打开剪映专业版，确认该草稿在草稿库可见且能播放。在 Linux/WSL 上，这一步只能证明本地服务/草稿文件链路；把生成目录迁到装有剪映专业版的机器之前，不应将结果标为“剪映已验收”。

## Agent 接入

将安装状态目录内的 `agent-mcp-config.json` 中 `cut-workbench` 项导入 Agent。它启动的是本地 stdio MCP；只有调用 `vectcut.execute` 才会经 `127.0.0.1:9001` 创建新的可编辑草稿。

这套安装包不包含 ASR、TTS、云渲染和 AI 特效。FFmpeg/ffprobe 与 OpenCV/Pillow 是独立本地依赖：前者用于流检测/渲染链路，后者用于关键帧联系表与视觉验收。可用 `--skip-visual-qa` 跳过后者，但 `doctor` 会将其显示为非关键缺失项。

## 已验证固定项与故障定位

- 自动建稿固定 VectCutAPI 提交 `d14e70749c9331424ab816a402bb45417c50cf68`。
- 自动生成的 profile 为 `jianying_pro_10`、`is_capcut_env=false`、本地端口 `9001`。
- `doctor` 中 `local-vectcut-service` 失败时，先运行 `start-local-editing.sh`，再查看安装状态目录 `service/vectcut.stderr.log`。
- 草稿目录检查失败时，传入真实存在、当前用户可写的目录；不要以创建一个空的“猜测路径”来绕过它。
