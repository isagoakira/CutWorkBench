# Premiere Pro / After Effects 本机桥接开源方案调研

调研日期：2026-08-27。仅核验项目自身 GitHub 仓库、发布信息和 Adobe 官方文档。

## 结论

没有找到一个可直接采用、同时完成 Premiere Pro（PR）与 After Effects（AE）**双向工程同步、冲突合并和安全发布**的成熟开源框架。最合适的落地方式是复用两个本机桥接项目的连接层：PR 使用 UXP，AE 使用 CEP/ExtendScript；Cut Workbench 仍是版本、轨道映射、三方合并、审计与“另存为副本”发布的唯一控制面。Dynamic Link 仅作为 PR 引用 AE 合成的媒体关系，不能取代同步协议。

## 排名与建议

| 排名 | 方案 | PR 能力 | AE 能力 / 串联 | 本机传输与许可证 | 维护判断 | Workbench 适配结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | [CaYatur/PremiereProMCP](https://github.com/CaYatur/PremiereProMCP) + [JUNKDOGE-JOE/after-effects-mcp](https://github.com/JUNKDOGE-JOE/after-effects-mcp) | UXP 驱动实时工程、序列、片段、效果、导出；含 checkpoint | AE MCP 提供受控执行、撤销/恢复、读取回证；两者由 Workbench 以 Dynamic Link ID / 媒体关系关联 | 两端均为本机 stdio MCP；PR 侧为 MCP→WebSocket→UXP，AE 侧为 MCP→localhost CEP→ExtendScript；均 MIT | 两个仓库在本次核验前一月内仍有推送；但均是年轻项目，须先做版本验收 | **推荐作为 PoC 基底，不直接并入 MCP。** 提取其桥接/插件层，转换为 Workbench 的 `PremiereAdapter` 与 `AfterEffectsAdapter`，由 Workbench 管理稳定 ID、revision、冲突与克隆发布。 |
| 2 | [AdobeDocs/uxp-premiere-pro-samples](https://github.com/AdobeDocs/uxp-premiere-pro-samples) + 自建 AE CEP connector | 官方 PR 参考面板覆盖 project、sequence、track、clip、marker、effect、keyframe、导入/导出（含 OTIO） | 无 AE 实现；AE 由本机 CEP/ExtendScript 面板承接，Dynamic Link 实体作为 opaque | PR UXP 支持本地网络、WebSocket、文件系统；Apache-2.0 | Adobe 官方样例，持续更新 | **最稳的生产路线。** 开发量高于第 1 名，但 API、权限和版本边界最清晰，避免把第三方 agent 工具的宽权限面带入核心。 |
| 3 | [inlife/nexrender](https://github.com/inlife/nexrender) | 无 PR 编辑 | AE `aerender` 的本地模板注入、渲染、任务队列；不管理交互式 AE 工程同步 | Node CLI/HTTP，可完全自托管；MIT | 有近期 release，项目成熟 | **只作为 AE 渲染 worker。** 适合 Workbench 已冻结 revision 后批量渲染，不可替代 AE 编辑同步或 PR↔AE 串联。 |
| 不建议 | [qmasingarbe/pymiere](https://github.com/qmasingarbe/pymiere) | Python→HTTP→CEP/ExtendScript，能访问已打开 PR | 无 AE | 本机 HTTP；GPL-3.0 | README 明示已不再维护，且仅验证到 PR 23.1 | 可作旧版 PR 的研究参照，不应成为新适配器依赖：CEP 已被 PR UXP 取代，GPL-3.0 也不适合直接嵌入。 |

维护信息以各项目 GitHub 元数据的 `pushed_at` 为准：[PPMCP](https://api.github.com/repos/CaYatur/PremiereProMCP)、[AE MCP](https://api.github.com/repos/JUNKDOGE-JOE/after-effects-mcp)、[nexrender](https://api.github.com/repos/inlife/nexrender)、[Pymiere](https://api.github.com/repos/qmasingarbe/pymiere)、[Adobe 官方样例](https://api.github.com/repos/AdobeDocs/uxp-premiere-pro-samples)。这只证明近期活动，不等于已经通过本机版本验收。

## 推荐的本机拓扑

```text
Agent
  ↕ stdio MCP
Cut Workbench (revision / manifest / three-way merge / audit)
  ├─ localhost WS/HTTP → Premiere UXP panel → Premiere project/sequence
  └─ localhost bridge  → AE CEP panel → ExtendScript → AE project/composition
                                      └─ aerender / nexrender（仅渲染）

PR Dynamic Link item ─── 引用 ─── AE composition
```

Adobe 已在 PR 25.6 正式发布 UXP；DOM 可修改项目，且 UXP 支持 `fetch`、XHR、WebSocket，但插件必须显式声明网络权限，且 WebSocket 为客户端模式。因此应由 Workbench 监听，插件主动连接 `localhost`，不得由插件监听端口。[UXP API](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/) [Network Operations](https://developer.adobe.com/premiere-pro/uxp/resources/recipes/network/) [官方样例](https://github.com/AdobeDocs/uxp-premiere-pro-samples)

AE 当前应采用 CEP/ExtendScript 本机 connector，而不要假设与 PR 共用 UXP DOM。Dynamic Link 要求 PR 与 AE 主版本一致；它能让两端共享/替换合成并反映改动，但复杂合成会带来预览负担，Adobe 建议必要时 Render and Replace。因此 Workbench 只保存 Dynamic Link 的身份、两端 revision 和指纹，把未建模的合成/效果保留为 opaque。[Adobe Dynamic Link 文档](https://helpx.adobe.com/premiere/desktop/use-premiere-with-other-apps/working-with-other-adobe-applications/share-assets-between-after-effects-and-premiere-using-dynamic-link.html)

## 接入边界

1. 首版只映射 PR 的 A/V clip（时间线位置、入/出点、速度、基础变换）与 AE 的 composition/layer（变换、文字、关键帧）；嵌套序列、MOGRT、第三方效果和未知 native 字段一律 opaque 保留。
2. 写入采用预览→显式冲突决议→提交新 Workbench revision→`Save As` / 项目副本发布；绝不直接重写 `.prproj` 或 `.aep`。
3. 两个 connector 均需本机版本、插件 hash、当前项目路径/指纹、运行状态和读回快照检查；每个写操作必须能以稳定 locator 回读验证。
4. Dynamic Link 不是跨编辑器的双向 diff 通道：它只连接素材/合成。跨 PR/AE 的结构化变更必须经过 Workbench 的 adapter 与审计记录。
