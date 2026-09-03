# Cut Workbench

本地优先、Agent 中立、以可编辑工程为核心的视频剪辑控制层。

Cut Workbench 不试图再造一个非线性编辑器。它负责管理剪辑工程的版本、稳定 ID、证据、冲突、验证和交接，再通过 MCP 把 Codex、Claude 或其他 Agent 接到本地分析工具、剪映、Premiere Pro、After Effects 以及可选的 VectCutAPI。

核心目标只有一个：**自动化完成后，人工仍能回到轨道、片段、字幕、效果和原生工程中继续修改。**

## 为什么需要它

常见的 AI 剪辑工具要么绑定订阅服务，要么只输出成片，要么把 Agent、模型和编辑器耦合在一起。Cut Workbench 把这些职责拆开：

- Agent 负责理解、判断、规划和高精度视觉任务。
- Whisper、FFmpeg、ffprobe、PySceneDetect 等本地程序负责可重复的轻量任务。
- Workbench 保存不可变 revision、稳定实体、审计证据和冲突决议。
- 剪映、Premiere、AE 或 VectCut 保留真正可二次加工的工程结构。
- 更换 Agent 平台或本地模型时，工程数据和 MCP 工具面保持不变。

## 当前能力

| 能力 | 当前状态 |
| --- | --- |
| 版本化工程、原子编辑计划、分支与不可变交接 | 可用 |
| 命名视频/音频/字幕/效果/贴纸轨道 | 可用 |
| 可分离片段、Transform、Mask、Keyframe、Effect 控件 | 可用 |
| 本地/Agent capability 路由与持久化任务队列 | 可用 |
| Cut Protocol 结构验证、视觉证据门禁、Manifest | 可用 |
| VectCut 可编辑多轨调用计划 | 可用；执行需要单独运行本地 VectCutAPI |
| 剪映专业版 11.3 双向三方同步 | 可用；需要外部 codec sidecar |
| Premiere Pro 2023 CEP 桥接 | 可用；当前 typed 写入范围为素材入点/出点 |
| After Effects 2023 CEP 桥接 | 快照和 opaque 保留可用；typed layer 合并尚未完成 |
| Dynamic Link 结构化双向编辑 | 尚未完成，目前仅作为 opaque 原生关联保留 |

项目不捆绑模型权重、Adobe 软件、剪映 codec 或云端服务，也不要求本地 LLM。

## 架构概览

```text
Codex / Claude / 其他 Agent
             │
          MCP tools
             │
       Cut Workbench
      ┌──────┼──────────┐
      │      │          │
 revisions  capability  editor adapters
 + audit    router      ├─ Jianying
      │      │          ├─ Premiere CEP
      │      ├─ local   └─ After Effects CEP
      │      └─ agent
      └─ VectCut compile plan
```

Workbench revision 是唯一真相源。外部编辑器是协作者，VectCut 是编译目标，渲染文件不是可编辑工程的替代品。

## 环境要求

- Python 3.11 或更高版本。
- Windows PowerShell 示例可直接使用；核心 Python 代码没有第三方运行时依赖。
- `ffprobe` 为默认本地媒体探测 provider，需要自行安装 FFmpeg 并加入 `PATH`。
- 其他本地模型或分析器通过 JSON stdin/stdout sidecar 接入。
- 外部编辑器同步需要对应的本地编辑器和适配器组件。

## 安装

```powershell
git clone git@github.com:isagoakira/CutWorkBench.git
Set-Location CutWorkBench
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

验证安装：

```powershell
cut-workbench --root D:/cut-runtime list-tools
```

也可以不安装包，直接从源码运行：

```powershell
$env:PYTHONPATH = 'src'
python -m cut_workbench.cli --root D:/cut-runtime list-tools
```

## 本地部署

Workbench 核心不需要 Docker、数据库、Web 服务或本地 LLM。它作为一个本地 Python 进程运行，并通过 stdio MCP 与 Agent 通信；项目 revision、journal、能力任务和编辑器同步会话都保存在 `--root` 指定的运行目录。

不要把运行目录放进源码目录。推荐把代码、运行状态、项目素材和本地工具分开：

```text
D:/projects/CutWorkBench/     # 本仓库与 Python 虚拟环境
D:/cut-runtime/               # revision、journal、capability-jobs、同步会话
D:/video-projects/            # 原始素材、剪辑工程、字幕、交付文件
D:/cut-config/                # runtime-config.json 等本机配置
D:/tools/                     # Whisper、TTS、codec 等 sidecar
```

先创建运行目录并做健康检查：

```powershell
$workbenchRoot = 'D:/cut-runtime'
New-Item -ItemType Directory -Force $workbenchRoot | Out-Null
cut-workbench --root $workbenchRoot list-tools
```

部署完成后，Workbench 不会监听网络端口；通常由 Agent 按需启动 stdio MCP：

```powershell
cut-workbench --root D:/cut-runtime mcp
```

### 按需追加本地组件

| 组件 | 是否必需 | 接入方式 |
| --- | --- | --- |
| FFmpeg / `ffprobe` | 推荐 | 安装 FFmpeg 并加入 `PATH`；用于本地媒体探测。 |
| Whisper、镜头/静音/节拍检测 | 可选 | 作为 `json-command` sidecar 写入运行时配置。 |
| GPT-SoVITS、CosyVoice 等 TTS | 可选 | 使用 `audio.synthesize.tts` sidecar；见下方 TTS 配置。 |
| 剪映专业版 | 可选 | 额外提供本机 codec sidecar，并固定 codec 版本与 SHA-256。 |
| Premiere Pro / After Effects | 可选 | 安装仓库提供的 CEP 面板和本机文件桥；先做快照/preview，再允许克隆发布。 |
| TapNow | 可选 | 以本地 Agent 命令消费 generation job，不调用未公开的网页接口。 |
| VectCutAPI | 可选 | 单独启动本地 VectCutAPI；Workbench 仅编译并审计多轨调用计划。 |

推荐部署顺序是：**核心 MCP → FFmpeg → Whisper/TTS → 剪映 → Premiere/AE → TapNow 或 VectCutAPI**。每一层都可以单独验证，缺少某个可选组件不会阻塞核心工程、审计和 MCP 工作流。

## 接入 Agent

任何支持 stdio MCP 的 Agent 都可以使用同一启动命令：

```json
{
  "mcpServers": {
    "cut-workbench": {
      "command": "python",
      "args": ["-m", "cut_workbench.cli", "--root", "D:/cut-runtime", "mcp"],
      "cwd": "D:/projects/CutWorkBench",
      "env": {"PYTHONPATH": "src"}
    }
  }
}
```

如果需要本地 Whisper、镜头检测或自定义 TTS sidecar，在启动参数中增加 `--config D:/cut-config/runtime-config.json`。配置结构见 [examples/runtime-config.json](examples/runtime-config.json)。任何实现“一条 JSON 请求从 stdin 输入、一条 JSON 结果从 stdout 输出”的程序都能作为 `json-command` provider，不需要修改 Workbench 核心。

## 核心工作流

```text
project.create
      ↓
capability.request ──→ local result / pending_agent ──→ capability.submit
      ↓
project.inspect → project.apply_plan → new revision
      ↓
project.verify → project.manifest
      ↓
sync.open → sync.preview → sync.commit → sync.publish clone
```

关键规则：

- 每次修改前先 `project.inspect`，使用当前 revision 作为 `expected_revision`。
- 原始媒体不修改；片段只保存素材区间和时间线位置。
- 效果、字幕、处理副本和音频尽量保持独立轨道或独立控件。
- `pending_agent` 是正常状态，需要 Agent 完成后通过 `capability.submit` 回填证据。
- 外部编辑器同步必须先 preview；冲突必须明确选择 `human` 或 `agent`。
- `sync.publish` 只创建新副本，不覆盖原剪映、`.prproj` 或 `.aep` 工程。
- `handed_off` revision 不可再修改，需要先创建分支。

## MCP 工具

| 分组 | 工具 |
| --- | --- |
| 工程 | `project.create`、`project.inspect`、`project.apply_plan`、`project.branch` |
| 验证 | `project.verify`、`project.manifest` |
| 能力 | `capability.request`、`capability.pending`、`capability.submit` |
| 编译 | `vectcut.compile` |
| 外部编辑器 | `sync.open`、`sync.preview`、`sync.commit`、`sync.publish` |

用 `cut-workbench --root D:/cut-runtime list-tools` 可获取完整 JSON Schema。

## 本地分析与配音

轻量任务可以配置为本地 provider，高精度任务可以保留给 Agent。默认策略包括媒体探测、逐词转写、静音/节拍/镜头检测、帧理解、编辑规划与语义验证。

### 配置本地 TTS

本地 TTS 通过同一个 capability seam 接入。把 GPT-SoVITS、CosyVoice 或其他引擎包装成 JSON stdin/stdout sidecar，然后创建例如 `D:/cut-config/runtime-config.json`：

```json
{
  "providers": [
    {
      "kind": "ffprobe",
      "executable": "ffprobe"
    },
    {
      "kind": "json-command",
      "provider_id": "local:gpt-sovits",
      "capabilities": ["audio.synthesize.tts"],
      "command": ["python", "D:/tools/tts_sidecar.py"],
      "timeout": 3600
    }
  ],
  "routing": {
    "default_route": "agent",
    "rules": {
      "media.probe": {"standard": "local", "high": "local"},
      "audio.synthesize.tts": {"standard": "local", "high": "local"}
    }
  }
}
```

启动 Workbench 时加载它：

```powershell
cut-workbench --root D:/cut-runtime `
  --config D:/cut-config/runtime-config.json `
  mcp
```

`json-command` 不经过 shell，而是按 `command` 数组直接启动进程。Workbench 会向 sidecar 的 stdin 写入一个 JSON 对象；TTS 建议接受以下字段：

```json
{
  "capability": "audio.synthesize.tts",
  "inputs": {
    "text": "欢迎来到太忆空间。",
    "output_path": "D:/video-project/06_口播与音频/VO_S01_001.wav",
    "voice_id": "speaker-01",
    "reference_audio": "D:/voices/speaker-01.wav"
  },
  "quality": "standard",
  "sensitivity": "local-only",
  "constraints": {
    "sample_rate": 48000,
    "format": "wav"
  }
}
```

sidecar 的 stdout 必须只输出一个结果对象，运行日志应写入 stderr：

```json
{
  "payload": {
    "audio_path": "D:/video-project/06_口播与音频/VO_S01_001.wav",
    "duration_seconds": 2.84,
    "sample_rate": 48000,
    "voice_id": "speaker-01"
  },
  "evidence": [
    "D:/video-project/06_口播与音频/VO_S01_001.wav"
  ]
}
```

可以直接验证路由和 sidecar：

```powershell
cut-workbench --root D:/cut-runtime `
  --config D:/cut-config/runtime-config.json `
  call capability.request '{"capability":"audio.synthesize.tts","inputs":{"text":"测试配音","output_path":"D:/cut-runtime/tts-test.wav"},"quality":"standard","sensitivity":"local-only","constraints":{"format":"wav"}}'
```

`audio.synthesize.tts` 默认优先选择可用的本地 provider；如果配置中没有声明该 capability 的 provider，任务会降级进入 `pending_agent`，不会假装本地生成成功。建议每条字幕 cue 生成独立音频文件和独立 segment，并保存参考音频、自然时长版本、拟合后版本及测量证据；不要只留下一个不可拆分的整轨 WAV。

仓库不包含任何 TTS 模型、声音权重或特定机器的绝对路径。

## 外部编辑器

### 剪映

剪映适配器执行基线 A、当前 Workbench B、当前人工草稿 C 的三方合并。未知字幕、贴纸、效果和复合片段作为 opaque 外部实体保存，不会静默丢失。详见 [docs/jianying-sync.md](docs/jianying-sync.md)。

### Premiere Pro / After Effects

仓库提供本机 CEP 面板源码和受限文件桥接。面板默认不授权发布；只有人工检查 preview 并打开授权后，Workbench 才能向新工程副本写入 allowlist patch。面板包、宿主版本和 profile 都使用 SHA-256 pin。详见 [docs/adobe-local-bridge.md](docs/adobe-local-bridge.md)。

## 安全与可恢复性

- 所有工程 mutation 都产生新 revision 和 journal 记录。
- revision 冲突不会自动重试或覆盖并发修改。
- 未建模的编辑器对象以 opaque 数据保留。
- 不支持的编译能力会显式拒绝，或要求记录经过人工批准的 downgrade。
- 发布前后验证源工程哈希、副本存在性、面板身份、实际 patch 和结果快照。
- 主观视觉质量必须有真实视觉证据，不能由结构测试代替。

## 文档

- [完整使用教程](docs/usage-guide.md)
- [架构与稳定边界](docs/architecture.md)
- [实现规格与非目标](docs/spec.md)
- [剪映双向同步](docs/jianying-sync.md)
- [Premiere / After Effects 本机桥接](docs/adobe-local-bridge.md)
- [PR / AE 开源方案调研](docs/premiere-after-effects-open-source-research.md)
- [运行时配置示例](examples/runtime-config.json)
- [编辑计划示例](examples/edit-plan.json)

## 开发与测试

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python -m compileall -q src
```

## 当前限制

- 这是控制平面，不提供时间线 GUI、播放器或渲染器。
- VectCut MCP 工具当前只生成调用计划；执行需要单独的 transport/API。
- 剪映 codec 不在仓库中，必须由操作者提供并固定 SHA-256。
- Premiere CEP typed writer 目前只覆盖明确暴露的素材入/出点。
- AE layer、Dynamic Link、Premiere 速度/位置/Transform 的完整 typed 双向映射仍在路线图中。
- 云端 Agent、云模型和第三方生成服务产生的费用不由本项目承担；纯本地路线可以不调用它们。

## License

Apache-2.0，见 [pyproject.toml](pyproject.toml) 中的项目元数据。
