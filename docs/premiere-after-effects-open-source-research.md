# Open-source research: local Premiere Pro / After Effects bridges

Research date: 2026-08-27. Sources were limited to the projects' GitHub repositories, release information, and official Adobe documentation.

## Conclusion

No mature open-source framework was found that could be adopted directly for **bidirectional project synchronization, conflict merging, and safe publication** across both Premiere Pro (PR) and After Effects (AE). The best implementation path reuses connection layers from two local bridge projects: UXP for PR and CEP/ExtendScript for AE. Cut Workbench remains the sole control plane for versions, track mapping, three-way merges, audits, and Save As/copy publication. Dynamic Link is a media relationship through which PR references AE compositions, not a replacement synchronization protocol.

## Ranking and recommendations

| Rank | Approach | PR capabilities | AE capabilities / connection | Local transport and license | Maintenance assessment | Workbench recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | [CaYatur/PremiereProMCP](https://github.com/CaYatur/PremiereProMCP) + [JUNKDOGE-JOE/after-effects-mcp](https://github.com/JUNKDOGE-JOE/after-effects-mcp) | UXP-driven live projects, sequences, clips, effects, export, checkpoints | Controlled execution, undo/recovery, readback evidence; Workbench links them through Dynamic Link IDs/media relationships | Both use local stdio MCP; PR: MCP→WebSocket→UXP; AE: MCP→localhost CEP→ExtendScript; both MIT | Both had pushes within the month before verification, but are young projects requiring version acceptance | **Recommended PoC foundation, not direct MCP incorporation.** Extract bridge/plugin layers as Workbench `PremiereAdapter` and `AfterEffectsAdapter`; Workbench owns stable IDs, revisions, conflicts, and clone publication. |
| 2 | [AdobeDocs/uxp-premiere-pro-samples](https://github.com/AdobeDocs/uxp-premiere-pro-samples) + custom AE CEP connector | Official reference panels cover projects, sequences, tracks, clips, markers, effects, keyframes, import/export including OTIO | No AE implementation; local CEP/ExtendScript panel handles AE, retaining Dynamic Link entities as opaque | PR UXP supports local networking, WebSocket, filesystem; Apache-2.0 | Official Adobe samples with ongoing updates | **Most dependable production path.** More development than rank 1, but clearer APIs, permissions, and version boundaries; avoids importing third-party agent tools' broad permissions into the core. |
| 3 | [inlife/nexrender](https://github.com/inlife/nexrender) | No PR editing | Local AE `aerender` template injection, rendering, job queue; no interactive AE project synchronization | Node CLI/HTTP, fully self-hostable; MIT | Recent releases; mature project | **AE render worker only.** Useful for batch rendering frozen Workbench revisions, not AE editing synchronization or PR↔AE integration. |
| Not recommended | [qmasingarbe/pymiere](https://github.com/qmasingarbe/pymiere) | Python→HTTP→CEP/ExtendScript access to open PR | None | Local HTTP; GPL-3.0 | README explicitly says unmaintained; tested only through PR 23.1 | Research reference for old PR versions, not a new adapter dependency: PR UXP has replaced CEP, and GPL-3.0 is unsuitable for direct embedding. |

Maintenance assessments use GitHub `pushed_at` metadata: [PPMCP](https://api.github.com/repos/CaYatur/PremiereProMCP), [AE MCP](https://api.github.com/repos/JUNKDOGE-JOE/after-effects-mcp), [nexrender](https://api.github.com/repos/inlife/nexrender), [Pymiere](https://api.github.com/repos/qmasingarbe/pymiere), [official Adobe samples](https://api.github.com/repos/AdobeDocs/uxp-premiere-pro-samples). Recent activity is not local version acceptance.

## Recommended local topology

```text
Agent
  ↕ stdio MCP
Cut Workbench (revision / manifest / three-way merge / audit)
  ├─ localhost WS/HTTP → Premiere UXP panel → Premiere project/sequence
  └─ localhost bridge  → AE CEP panel → ExtendScript → AE project/composition
                                      └─ aerender / nexrender (rendering only)

PR Dynamic Link item ─── references ─── AE composition
```

Adobe officially released UXP in PR 25.6. Its DOM can modify projects, and UXP supports `fetch`, XHR, and WebSocket. Plugins must explicitly declare networking permissions; WebSocket operates as a client. Workbench should listen and the plugin should connect to `localhost`, rather than the plugin listening on a port. [UXP API](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/) [Network Operations](https://developer.adobe.com/premiere-pro/uxp/resources/recipes/network/) [Official samples](https://github.com/AdobeDocs/uxp-premiere-pro-samples)

Use a local CEP/ExtendScript connector for AE rather than assuming a shared PR UXP DOM. Dynamic Link requires matching PR/AE major versions. It shares/replaces compositions and reflects changes, but complex compositions burden previews; Adobe recommends Render and Replace where needed. Workbench therefore stores Dynamic Link identity, both revisions, and fingerprints while preserving unmodeled compositions/effects as opaque data. [Adobe Dynamic Link documentation](https://helpx.adobe.com/premiere/desktop/use-premiere-with-other-apps/working-with-other-adobe-applications/share-assets-between-after-effects-and-premiere-using-dynamic-link.html)

## Integration boundaries

1. The first version maps PR A/V clips (timeline positions, in/out points, speed, basic transforms) and AE compositions/layers (transforms, text, keyframes). Nested sequences, MOGRT, third-party effects, and unknown native fields remain opaque.
2. Writes use preview → explicit conflict resolution → new Workbench revision → Save As/project-copy publication. Never rewrite `.prproj` or `.aep` directly.
3. Both connectors require local version, plugin hash, current project path/fingerprint, running-state, and readback-snapshot checks. Every write must be verifiable through a stable locator.
4. Dynamic Link connects media/compositions, not cross-editor bidirectional diffs. Structured PR/AE changes must pass through Workbench adapters and audit records.
