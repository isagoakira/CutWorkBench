# Cut Workbench

一个纯免费、本地优先、Agent 中立的视频剪辑控制层。它把 Codex 等 Agent 的理解/规划能力、本地 Whisper/FFmpeg 等轻量分析、以及 VectCut 的可编辑多轨草稿连接起来，同时落实 Cut Protocol 的版本、证据、验证和交接闭环。

它不要求本地 LLM，也不把任何 Agent SDK 写进核心。Agent 通过 MCP 调用稳定工具；重能力可进入 `pending_agent` 队列，由当前 Agent 原生完成并回填。换到其他 Agent 平台时，工程模型、编辑计划和本地工具无需改动。

## 快速启动

```powershell
cd D:\Files\工作\智悦\太忆空间素材\cut-workbench
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
cut-workbench --root D:\cut-runtime list-tools
cut-workbench --root D:\cut-runtime mcp
```

若不安装包，也可以：

```powershell
$env:PYTHONPATH='src'
python -m cut_workbench.cli --root runtime list-tools
```

Agent 的 MCP 配置指向同一个命令：

```json
{
  "mcpServers": {
    "cut-workbench": {
      "command": "python",
      "args": ["-m", "cut_workbench.cli", "--root", "D:/cut-runtime", "mcp"],
      "cwd": "D:/Files/工作/智悦/太忆空间素材/cut-workbench",
      "env": {"PYTHONPATH": "src"}
    }
  }
}
```

## 工作流

1. `project.create` 建立画布和不可变 revision 1。
2. `capability.request` 请求逐词转写、静音/节拍/镜头检测或帧理解。策略决定本地执行还是等待 Agent。
3. `project.apply_plan` 原子提交来源、轨道、片段、字幕、控件、决策和证据。
4. `project.verify` 检查 2fps 全源审计、轨道结构和交付前视觉证据。
5. `vectcut.compile` 生成可审计的 VectCut 调用计划；底轨、处理副本、字幕和效果保持分离。
6. 本地 VectCutAPI 运行在默认 `http://127.0.0.1:9001` 时，用 `VectCutExecutor(VectCutHttpTransport())` 执行计划并保存剪映/CapCut 草稿。
7. `project.manifest` 输出与当前 revision 同源的 Cut Manifest；`handed_off` 后只能分支再改。

本地能力配置见 [examples/runtime-config.json](examples/runtime-config.json)，操作例子见 [examples/edit-plan.json](examples/edit-plan.json)，设计与闭环映射见 [docs/architecture.md](docs/architecture.md)。

## 测试

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m compileall -q src
```

运行时仅依赖 Python 标准库；ffprobe、Whisper 等通过外部进程接入。许可证为 Apache-2.0。
