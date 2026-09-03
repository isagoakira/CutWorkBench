# Cut Workbench 完整使用教程

本教程从空目录开始，完成安装、Agent 接入、工程创建、本地/Agent 能力路由、编辑计划、验证、Manifest，以及剪映或 Adobe 工程的安全双向同步。

示例以 Windows PowerShell 和 Python 3.11+ 为准。所有路径都应替换成自己的实际位置。

## 1. 安装与健康检查

```powershell
git clone git@github.com:isagoakira/CutWorkBench.git
Set-Location CutWorkBench
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

选择独立运行目录。这里会保存项目 revision、journal、capability job 和同步会话，不要使用源码目录本身：

```powershell
$workbenchRoot = 'D:/cut-runtime'
cut-workbench --root $workbenchRoot list-tools
```

输出中应看到 `project.create`、`project.apply_plan`、`capability.request`、`project.verify` 和 `sync.open` 等工具。

若不希望安装包：

```powershell
$env:PYTHONPATH = 'src'
python -m cut_workbench.cli --root $workbenchRoot list-tools
```

## 2. 直接用 CLI 完成第一次调用

CLI 的 `call` 子命令与 MCP 调用同一个接口，适合安装验证和故障排查。

```powershell
$createRequest = @'
{
  "project_id": "tutorial-01",
  "title": "Tutorial project",
  "canvas": {"width": 1920, "height": 1080, "fps": 30},
  "editor_adapter": "unassigned"
}
'@

cut-workbench --root $workbenchRoot call project.create $createRequest
cut-workbench --root $workbenchRoot call project.inspect '{"project_id":"tutorial-01"}'
```

新工程从 revision 1 开始。每个成功的 `project.apply_plan` 都生成新的不可变 revision。

## 3. 接入 Codex 或其他 MCP Agent

在 Agent 的 MCP 配置中添加：

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

刷新 Agent 的 MCP 连接。让 Agent 在任何 mutation 前先调用 `project.inspect`。Agent 平台只调用 MCP；project schema、revision 和领域规则都留在 Workbench 中。

## 4. 配置本地分析 provider

没有 `--config` 时，Workbench 仍注册默认 `ffprobe` provider。安装 FFmpeg 后可调用：

```powershell
$probeRequest = @'
{
  "capability": "media.probe",
  "inputs": {"media_path": "D:/media/source.mp4"},
  "quality": "standard",
  "sensitivity": "local-only",
  "constraints": {}
}
'@

cut-workbench --root $workbenchRoot call capability.request $probeRequest
```

要接入 Whisper 或其他 sidecar，复制并修改 [runtime-config.json](../examples/runtime-config.json)：

```json
{
  "providers": [
    {"kind": "ffprobe", "executable": "ffprobe"},
    {
      "kind": "json-command",
      "provider_id": "local:whisper-sidecar",
      "capabilities": ["audio.transcribe.words"],
      "command": ["python", "D:/tools/whisper_sidecar.py"],
      "timeout": 3600
    }
  ],
  "routing": {
    "default_route": "agent",
    "rules": {
      "media.probe": {"standard": "local", "high": "local"},
      "audio.transcribe.words": {"standard": "local", "high": "agent"},
      "video.interpret.frames": {"standard": "agent", "high": "agent"}
    }
  }
}
```

启动时增加配置：

```powershell
cut-workbench --root $workbenchRoot --config D:/cut-config/runtime-config.json mcp
```

### sidecar 协议

`json-command` provider 向程序 stdin 写入一个 request JSON。sidecar 必须向 stdout 只写一个结果对象：

```json
{
  "payload": {"words": []},
  "evidence": ["D:/evidence/transcript.words.json"]
}
```

日志写到 stderr。非零退出码、超时或无效 JSON 都会形成失败 job，不会伪装成成功结果。

### Agent 原生任务

当策略选择 `agent`，`capability.request` 返回 `pending_agent` job。Agent 完成后调用 `capability.submit`：

```json
{
  "job_id": "返回的 job_id",
  "agent_id": "codex",
  "payload": {"result": "结构化结果"},
  "evidence": ["evidence/frame-review.json"]
}
```

`pending_agent` 是正常状态。没有真实结果和证据时不要回填。

## 5. 建立第一个可编辑剪辑工程

先计算素材 SHA-256：

```powershell
$sourcePath = 'D:/media/source.mp4'
$sourceHash = (Get-FileHash $sourcePath -Algorithm SHA256).Hash.ToLower()
```

先 `project.inspect` 获取当前 revision，再一次性提交来源、轨道、片段、字幕和审计决策。下面假设素材时长为 12 秒，请替换为真实值：

```powershell
$plan = @"
{
  "project_id": "tutorial-01",
  "expected_revision": 1,
  "actor": "agent:codex",
  "reason": "Register source and create editable base and caption tracks",
  "operations": [
    {
      "op": "register_source",
      "source_id": "SRC-001",
      "locator": "$sourcePath",
      "sha256": "$sourceHash",
      "media_profile": {"duration": 12.0}
    },
    {"op": "add_track", "track_id": "V1-BASE", "kind": "video", "purpose": "base"},
    {"op": "add_track", "track_id": "S1-CAPTIONS", "kind": "caption", "purpose": "captions"},
    {
      "op": "add_segment",
      "segment_id": "SEG-001",
      "source_id": "SRC-001",
      "track_id": "V1-BASE",
      "source_in": 1.0,
      "source_out": 8.0,
      "timeline_start": 0.0,
      "speed": 1.0,
      "role": "primary"
    },
    {
      "op": "add_caption",
      "caption_id": "CAP-001",
      "track_id": "S1-CAPTIONS",
      "start": 0.2,
      "end": 2.8,
      "text": "这是第一条可编辑字幕",
      "speech_evidence": "evidence/transcript.words.json"
    },
    {
      "op": "record_decision",
      "decision_id": "DEC-AUDIT-SRC001",
      "kind": "source_audit",
      "summary": "Full source audit at 2 fps",
      "source_id": "SRC-001",
      "evidence": ["evidence/SRC-001/contact-sheet-2fps.jpg"],
      "data": {
        "sample_fps": 2,
        "sample_count": 24,
        "coverage_range": {"start": 0, "end": 12.0},
        "escalations": []
      }
    }
  ],
  "evidence": ["evidence/editorial-selection.json"]
}
"@

cut-workbench --root $workbenchRoot call project.apply_plan $plan
```

如果其他调用者已产生新 revision，旧 `expected_revision` 会被拒绝。重新 inspect、理解差异，再构造下一份计划；不要盲目重试。

## 6. 添加效果并保持可拆分

同轨 Transform、Mask、Mask Blur、Keyframe 使用 `add_control`；独立效果使用 `effect` track：

```json
{
  "op": "add_control",
  "control_id": "CTRL-ZOOM-001",
  "target_segment_id": "SEG-001",
  "track_id": "V1-BASE",
  "kind": "transform",
  "active_range": {"start": 1.0, "end": 3.0},
  "properties": {"scale": 1.08, "anchor": [0.5, 0.5]},
  "keyframes": [],
  "editable": true,
  "baked": false
}
```

若目标平台无法保留某项能力，不要静默烘焙。先用 `record_downgrade` 保存原因、fallback 和批准者，再让 baked control 引用 `approved_exception_id`。

## 7. 验证和 Manifest

```powershell
cut-workbench --root $workbenchRoot call project.verify '{"project_id":"tutorial-01"}'
cut-workbench --root $workbenchRoot call project.manifest '{"project_id":"tutorial-01"}'
```

常见失败项：

- `source-audit-missing`：缺少覆盖完整素材、至少 2 fps 的审计证据。
- `source-hash-missing`：来源没有 64 位 SHA-256。
- `track-overlap`：同一视频/音频轨片段重叠。
- `track-gap`：base 轨存在未由 `intentional_gap` 决策解释的空洞。
- `visual-verification-missing`：进入 review/delivery/handoff 时没有与当前内容指纹一致的视觉证据。

Manifest 直接来自同一 revision，包含来源、粗剪映射、控件、字幕、决策、降级和验证状态。

## 8. 编译 VectCut 计划

```powershell
cut-workbench --root $workbenchRoot call vectcut.compile '{"project_id":"tutorial-01","draft_folder":"D:/drafts/tutorial-01"}'
```

该工具返回可审计调用计划，不自动联网或渲染。出现 unsupported control 或 opaque external entity 时会明确拒绝，避免静默丢失原生对象。

## 9. 剪映双向同步

剪映适配器需要与本机版本匹配的外部 codec，并强制 SHA-256 pin：

```powershell
cut-workbench `
  --root $workbenchRoot `
  --jianying-codec C:/tools/jy-draftc.exe `
  --jianying-install E:/JianYing/JianyingPro/11.3.0.14362 `
  --jianying-version 11.3.0.14362 `
  --jianying-codec-sha256 <VERIFIED_SHA256> `
  mcp
```

事务固定为：

1. `sync.open` 固定 Workbench revision、codec profile 和剪映基线快照。
2. 在 Workbench 和剪映中分别编辑。
3. `sync.preview` 比较基线 A、Agent 当前 B、人工草稿 C。
4. `sync.commit` 对每个冲突明确选择 `human` 或 `agent`。
5. 关闭剪映，使用不存在的新目标目录执行 `sync.publish`。
6. 打开 clone 做真实视觉检查；原草稿保留为回滚基线。

完整约束见 [jianying-sync.md](jianying-sync.md)。

## 10. Premiere Pro / After Effects 桥接

当前 Adobe 2023 CEP 面板能力：

- `premiere:cep-local`：活动 Sequence 快照和素材 source in/out 的 clone 写入。
- `after-effects:cep-local`：活动 Composition/Layer 快照和 opaque 审计；typed layer binding 尚未完成。

安装面板源码：

```powershell
$cepExtensions = "$env:APPDATA/Adobe/CEP/extensions"
New-Item -ItemType Directory -Force $cepExtensions | Out-Null
Copy-Item adapters/cep-local/premiere "$cepExtensions/com.cutworkbench.premiere" -Recurse
Copy-Item adapters/cep-local/after-effects "$cepExtensions/com.cutworkbench.aftereffects" -Recurse
```

未签名开发面板还需要为 Adobe 2023 启用 CEP `PlayerDebugMode` 并重启应用。打开 **窗口 → 扩展 → Cut Workbench Bridge**，输入私有 bridge 目录，保持 **Permit clone publish** 未勾选并点击 **Write snapshot**。

计算 profile 和实际安装面板目录的哈希：

```powershell
$premiereProfile = (Get-FileHash D:/cut-bridges/premiere/profile.json -Algorithm SHA256).Hash
$premierePanel = cut-workbench bridge-hash "$cepExtensions/com.cutworkbench.premiere"
```

启动 Premiere bridge：

```powershell
cut-workbench `
  --root $workbenchRoot `
  --premiere-bridge-root D:/cut-bridges/premiere `
  --premiere-bridge-kind cep `
  --premiere-profile-sha256 $premiereProfile `
  --premiere-version 23.0 `
  --premiere-panel-root "$cepExtensions/com.cutworkbench.premiere" `
  --premiere-panel-sha256 $premierePanel `
  mcp
```

同步仍使用 `sync.open → sync.preview → sync.commit → sync.publish`。只有 preview 审核完成后才在面板中勾选发布授权。目标工程必须是不存在的新 `.prproj` 或 `.aep` 文件。详见 [adobe-local-bridge.md](adobe-local-bridge.md)。

## 11. 本地 SRT 配音

Workbench 不绑定具体 TTS 引擎。可把 GPT-SoVITS、CosyVoice 等包装为 `json-command` provider：

```json
{
  "kind": "json-command",
  "provider_id": "local:gpt-sovits",
  "capabilities": ["audio.synthesize.tts"],
  "command": ["python", "D:/tools/tts_sidecar.py"],
  "timeout": 3600
}
```

Routing 中显式加入：

```json
"audio.synthesize.tts": {"standard": "local", "high": "local"}
```

建议一条 SRT cue 对应一个独立 WAV 和 audio segment；字幕保留在 caption track，配音放在命名 dialogue track。保存原始 SRT、参考音频、自然时长 WAV、拟合 WAV、RTF/VRAM/时长误差等 evidence。整轨 WAV 只作为试听或导出便利。

## 12. 交接、分支与恢复

`handed_off` revision 永久拒绝 mutation。继续修改时调用 `project.branch`：

```json
{
  "source_project_id": "tutorial-01",
  "new_project_id": "tutorial-01-revision-b",
  "revision": 5,
  "title": "Tutorial project revision B"
}
```

不要删除历史 revision、journal、原始媒体或外部编辑器基线。

## 13. 常见问题

### `RevisionConflict`

其他调用者已经提交新 revision。重新 `project.inspect`，理解变化后重建计划。

### capability 一直是 `pending_agent`

当前 routing 选择了 Agent，或本地 provider 不可用。让 Agent 完成并调用 `capability.submit`，或检查 config 中的 capability 名称和 command。

### 本地 provider 返回 invalid JSON

确保 stdout 只有一个结果 JSON，进度日志全部写 stderr。

### 剪映 publish 被拒绝

确认剪映已关闭、codec 哈希与版本匹配、目标目录不存在，并重新 preview 更新 fingerprint。

### Adobe profile/hash 不匹配

重新从面板写 snapshot，确认宿主版本，计算实际安装面板目录和 `profile.json` 的新哈希，再开启新会话。不要绕过 pin。

### VectCut compile 拒绝 opaque entity

编译器无法证明该原生对象能无损重建。继续使用外部编辑器 round trip，或实现 typed importer/writer；不要删除 opaque ledger 强行通过。

## 14. 最终检查清单

- 所有 source 都有真实 SHA-256、时长和完整 2 fps 审计证据。
- 当前 revision 与 Agent 使用的 `expected_revision` 一致。
- 底轨、处理、字幕、效果、对话音频仍可独立选择。
- capability job 已完成，或在交接中明确列为 pending。
- downgrade 有原因、fallback 和人工批准。
- 视觉证据与当前 content fingerprint 一致。
- 外部编辑器 publish 指向新 clone，源工程未变化。
- `project.verify` 通过，`project.manifest` 已保存。
- handed-off 后的继续工作从 branch 开始。
