# 运行时配置与调用链

Cut Workbench 启动时只选择一份 JSON 运行时配置。它同时提供三类信息：本地 capability provider、capability routing policy，以及本机 VectCutAPI 的连接参数。配置不是项目数据；工程 revision、journal、任务和同步会话始终保存在 `--root` 目录。

## 配置文件选择与覆盖顺序

CLI/MCP 启动时按以下顺序选择配置文件：

1. 传入 `--config <path>`：只读取该文件。
2. 未传 `--config` 且 `<root>/runtime-config.json` 存在：自动读取该文件。
3. 两者均不满足：使用内置默认值。

不会自动合并多个 JSON 文件。环境变量与标量 CLI 参数只覆盖 VectCut 的指定字段：

| 字段 | 高 → 低优先级 |
| --- | --- |
| VectCut 地址 | `--vectcut-url` → `vectcut.base_url` → `CUT_WORKBENCH_VECTCUT_URL` → `http://127.0.0.1:9001` |
| VectCut 草稿根目录 | `--vectcut-draft-folder` → `vectcut.draft_folder` → 当前平台的剪映默认草稿目录 |
| VectCut 超时 | `vectcut.timeout` → `120` 秒 |
| capability provider / routing | 选中的配置文件 → 内置默认 routing；`ffprobe` 始终默认注册 |

`vectcut.base_url` 和 `CUT_WORKBENCH_VECTCUT_URL` 必须为 `http://` 或 `https://` 的本机回环地址（`localhost`、`127.0.0.1` 或 `::1`）。远程主机和云端 VectCut 地址会在启动时被拒绝。

## 最小配置

只自动建稿时，只需声明 VectCut；默认 `ffprobe` 不会被删除：

```json
{
  "vectcut": {
    "base_url": "http://127.0.0.1:9001",
    "timeout": 120,
    "draft_folder": "E:/JianYing/JianyingPro Drafts"
  }
}
```

`draft_folder` 应指向当前本机剪映实际使用且可写的草稿根目录。`vectcut.execute` 始终创建一个新草稿；若目标草稿 ID 已存在，执行会拒绝覆盖。

## 加入本地 sidecar

需要本地转写、镜头检测或 TTS 时，把 provider 与 VectCut 放在同一份文件中：

```json
{
  "vectcut": {
    "base_url": "http://127.0.0.1:9001",
    "draft_folder": "E:/JianYing/JianyingPro Drafts"
  },
  "providers": [
    {
      "kind": "ffprobe",
      "executable": "D:/tools/ffmpeg/bin/ffprobe.exe"
    },
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
      "audio.transcribe.words": {"standard": "local", "high": "agent"}
    }
  }
}
```

`providers` 是数组。支持的 `kind` 为：

- `ffprobe`：可选 `executable`；若未声明，仍会注册系统 PATH 中的 `ffprobe`。
- `json-command`：需要 `provider_id`、`capabilities` 和 `command` 数组；请求通过 stdin 输入一个 JSON，结果通过 stdout 输出一个 JSON，日志写 stderr。

`routing` 是对象，包含可选 `default_route`（`local` 或 `agent`）和 capability/quality 到路由的 `rules`。若省略则使用内置策略。

## 启动与调用链

```powershell
# 自动读取 D:/cut-runtime/runtime-config.json
cut-workbench --root D:/cut-runtime mcp

# 使用一个明确的机器配置
cut-workbench --root D:/cut-runtime --config D:/cut-config/runtime-config.json mcp

# 对一次启动覆盖 VectCut 服务与草稿根目录
cut-workbench --root D:/cut-runtime `
  --config D:/cut-config/runtime-config.json `
  --vectcut-url http://127.0.0.1:9100 `
  --vectcut-draft-folder 'E:/JianYing/JianyingPro Drafts' `
  call vectcut.health '{}'
```

MCP 与 CLI `call` 使用相同的 `WorkbenchApp`。工程变更先经过 `project.inspect` 和 `project.apply_plan` 写入 revision；随后按目标选择以下路径：

```text
capability.request ─────────────→ 本地 provider 或 pending_agent → capability.submit
project revision ──────────────→ vectcut.health → compile → execute → 新剪映草稿
project revision + editor base ─→ sync.open → preview → commit → publish clone / apply live
```

`vectcut.compile` 只产生审计计划；只有 `vectcut.execute` 会调用本机 VectCutAPI。`sync.publish` 生成外部工程副本，`sync.apply` 只用于已连接、已授权的本地编辑器桥接，二者不互相替代。

## 启动前检查

1. `ffprobe -version` 可在启动 Workbench 的同一终端中执行。
2. 本机 VectCutAPI 已在配置端口监听：`cut-workbench --root D:/cut-runtime call vectcut.health '{}'`。
3. `draft_folder` 是实际剪映草稿根目录且具备写权限。
4. 使用 `cut-workbench --root D:/cut-runtime list-tools` 查看当前 MCP 完整 schema，而不是猜测工具参数。

完整可运行配置在 [examples/runtime-config.json](../examples/runtime-config.json)。
