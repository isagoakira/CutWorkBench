# Premiere Pro / After Effects 本机桥接

Cut Workbench 通过同一个受限的本机文件桥接协议接入 Premiere Pro 和 After Effects；它不连接 ChatCut、VectCut 或 Adobe 云端。Workbench 仍是 revision、三方合并、冲突决议和发布审计的唯一真相源。

## 当前可运行范围

- 这台机器的 Premiere Pro 2023 / After Effects 2023 均为 23.0，因此首个宿主实现是 CEP/ExtendScript：`premiere:cep-local` 和 `after-effects:cep-local`。
- Premiere 的未来 UXP 路由 `premiere:uxp-local` 也可复用同一 Workbench 协议，但仓库尚未提供 UXP panel；不要把它配置到这台 23.0 Premiere。
- 可安装的 CEP 面板源在 `adapters/cep-local/`。Premiere 当前只公开读快照与源入/出点的 clone 写入；AE 面板会公开无关键帧 Layer Transform 路径，但 Workbench 尚未有 AE typed-layer binding，当前只用于保留与审计人工改动。其它对象、效果、文本动画、关键帧与 Dynamic Link 都会作为 opaque 外部实体保留，不会被 Agent 改写。
- 一个运行实例可同时配置剪映、Premiere 和 AE。`project.create.editor_adapter` 选择本项目的同步 adapter；`sync.open` 会据此路由，之后会话会钉住 adapter。
- 适配器只允许发布该次外部快照中声明的 `property_paths`，且只允许 `set` patch。面板默认只读，勾选本机面板中的授权项后才会处理 clone publish。

启动示例：

```powershell
$env:PYTHONPATH = 'src'
python -m cut_workbench.cli `
  --root D:/cut-runtime `
  --premiere-bridge-root D:/cut-bridges/premiere `
  --premiere-bridge-kind cep `
  --premiere-profile-sha256 <PREMIERE_PROFILE_SHA256> `
  --premiere-version 23.0 `
  --premiere-panel-root "$env:APPDATA/Adobe/CEP/extensions/com.cutworkbench.premiere" `
  --premiere-panel-sha256 <PREMIERE_PANEL_SHA256> `
  --after-effects-bridge-root D:/cut-bridges/after-effects `
  --after-effects-profile-sha256 <AE_PROFILE_SHA256> `
  --after-effects-version 23.0 `
  --after-effects-panel-root "$env:APPDATA/Adobe/CEP/extensions/com.cutworkbench.aftereffects" `
  --after-effects-panel-sha256 <AE_PANEL_SHA256> `
  mcp
```

每次审核/更新 panel 后，固定 profile 与面板目录的 SHA-256，再作为启动 pin 传入。先用面板的 **Write snapshot** 写出 `profile.json`，再计算两个 pin：

```powershell
(Get-FileHash D:/cut-bridges/premiere/profile.json -Algorithm SHA256).Hash
python -m cut_workbench.cli bridge-hash "$env:APPDATA/Adobe/CEP/extensions/com.cutworkbench.premiere"
```

Profile、宿主版本或面板目录内容任一改变但未更新启动 pin 时，Workbench 会拒绝读取或发布；这是本机 connector 更新的显式审批点。`profile.writable` 表示该已固定版本的面板具备 clone 功能，不是每次发布的授权。

## 安装 CEP 面板（本机开发模式）

不要直接修改 `.prproj` / `.aep`。将两个面板目录分别复制到当前用户的 CEP extensions 目录：

```powershell
$extensions = "$env:APPDATA/Adobe/CEP/extensions"
Copy-Item adapters/cep-local/premiere "$extensions/com.cutworkbench.premiere" -Recurse
Copy-Item adapters/cep-local/after-effects "$extensions/com.cutworkbench.aftereffects" -Recurse
```

由于这是未签名的本机开发面板，Adobe 2023 必须启用 CEP 的 `PlayerDebugMode`，随后重启相应 Adobe 应用。在 Premiere 的 `窗口 > 扩展` 与 AE 的 `窗口 > 扩展` 打开 **Cut Workbench Bridge**。这项注册表改动和复制安装由操作者自行执行；面板不监听端口，也不调用任何云服务。

在每个面板中输入与命令行相同的 bridge 目录，先保持未勾选状态完成 `sync.open` / `sync.preview`。面板会把这个实时选择写入未 pin 的 `authorization.json`；只有审核过 preview 后才勾选 **Permit clone publish**，然后执行 `sync.commit`、`sync.publish`。Workbench 在排队命令和面板在执行命令时都会检查该授权；面板不会覆盖源工程。

建立项目时使用相应 adapter，例如：

```json
{
 "project_id": "brand-film-pr",
  "title": "Brand film",
  "canvas": {"width": 1920, "height": 1080, "fps": 30},
  "editor_adapter": "premiere:cep-local"
}
```

## Panel 与 Workbench 的本机文件协议

桥接目录仅应对当前 Windows 用户可读写。不要把它放到同步盘、共享目录或网络挂载卷，也不要让 panel 监听非 loopback 端口。

### `profile.json`（panel 写入）

```json
{
  "protocol_version": 1,
  "adapter_id": "premiere:cep-local",
  "editor_version": "23.0",
  "writable": true
}
```

### `snapshot.json`（panel 写入）

每次人工修改、切换活动工程/序列或收到读取请求时覆盖此文件。`snapshot` 是 Workbench 标准外部快照：必须含 `adapter_id`、稳定 `draft_id`、内容 `fingerprint`、tracks、materials、entities 和 `native_summary`。每一个可由 Agent 修改的字段都要在 `entities.*.property_paths` 中给出稳定路径。

```json
{
  "protocol_version": 1,
  "adapter_id": "premiere:cep-local",
  "draft_path": "D:/Projects/rough-cut.prproj",
  "snapshot": {
    "schema_version": 1,
    "adapter_id": "premiere:cep-local",
    "draft_id": "sequence-guid",
    "fingerprint": "sha256-or-host-state-fingerprint",
    "tracks": {},
    "materials": {},
    "entities": {},
    "native_summary": {}
  }
}
```

### `authorization.json`（panel 写入）

这是一次性、本机交互授权，不是代码完整性信号，因此不参与 profile hash pin。`publish_enabled: false` 时，Workbench 不会写 publish command；即使 command 已存在，面板也不会处理它。

```json
{
  "protocol_version": 1,
  "adapter_id": "premiere:cep-local",
  "publish_enabled": false
}
```

### `commands/<request_id>.json`（Workbench 写入）

`sync.publish` 创建命令时，panel 必须先重新读取当前工程并核对 `expected_fingerprint`。不一致时不能写入工程；应返回一个失败回执并要求重新 `sync.preview`。

```json
{
  "protocol_version": 1,
  "request_id": "...",
  "kind": "publish-clone",
  "adapter_id": "premiere:cep-local",
  "source_path": "D:/Projects/rough-cut.prproj",
  "destination_path": "D:/Projects/rough-cut-agent.prproj",
  "expected_fingerprint": "...",
  "patches": [{"op": "set", "path": "/...", "value": 1.25}]
}
```

### `responses/<request_id>.json`（panel 写入）

在 Premiere 中先 `Save As` 为 `destination_path`，或在 AE 中另存新 `.aep`，再对副本应用 patch，并从副本读取新的指纹。源工程不得保存或改写。

```json
{
  "protocol_version": 1,
  "request_id": "...",
  "status": "published",
  "source_path": "D:/Projects/rough-cut.prproj",
  "destination_path": "D:/Projects/rough-cut-agent.prproj",
  "source_fingerprint": "...",
  "result_fingerprint": "...",
  "applied_patches": [],
  "adapter_id": "premiere:cep-local",
  "result_snapshot": {
    "schema_version": 1,
    "adapter_id": "premiere:cep-local",
    "draft_id": "sequence-guid",
    "fingerprint": "...",
    "tracks": {},
    "materials": {},
    "entities": {},
    "native_summary": {}
  }
}
```

Workbench 会验证副本文件已经产生、源工程字节未变，以及 `result_snapshot.fingerprint` 与回执一致，才把副本纳入下一轮闭环。

## 当前硬限制与下一步

- Premiere 当前不向 Agent 公开时间线位置、速度或 Transform 写入；CEP 面板只对明确的 source in/out 生成路径。
- AE 面板只对无关键帧的 Layer Transform 生成路径；在 Workbench 增加 typed-layer binding 前，这些路径不会被 Agent 生成 patch。关键帧、表达式、文本和效果仍是 opaque。
- Dynamic Link 目前只会随两边 native summary 进入外部账本；它不是跨工程结构化 diff，也不能自动双向修改 PR 项目项和 AE comp。
- 下一步是把 Dynamic Link 关联建成显式 typed ledger，以及为 Premiere UXP 25.6+ 实现同一受限协议。

直接改写 `.prproj` 或 `.aep`、从 Agent 接受任意 ExtendScript/eval、提交未经 allowlist 的 native patch、覆盖原工程，均不在本桥接协议允许范围内。
