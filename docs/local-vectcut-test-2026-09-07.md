# Local VectCut test record (2026-09-07)

Upstream: sun-guannan/VectCutAPI, commit d14e70749c9331424ab816a402bb45417c50cf68.

## Results

- Windows local service: 127.0.0.1:9001, Python 3.13; real HTTP draft creation/save succeeded.
- WSL Ubuntu 22.04: Python 3.11.15, independent service at 127.0.0.1:9002; real HTTP calls succeeded.
- All 92 unit tests passed on each platform.
- Real-media smoke tests on both: source ranges 1–3 and 4–6 seconds placed at timeline 0–2 and 2–4 seconds. Entity counts, timeline positions, source in-points, media existence, and source/copied-media SHA-256 passed.
- macOS has startup scripts, default paths, and deployment instructions, but no real Mac testing. WSL does not establish macOS Jianying acceptance.

## Five real-media segments

Workbench project taiyi-local-a020d4a0, revision 2.

Generated draft: `E:/JianYing/JianyingPro Drafts/dfd_cat_1788742445_c6e10a81`.

Order: MCP/Skill → WorkBuddy upload → web viewing → Claude Code recall → replace media with synchronization results.

Canvas: 2560×1600, 30 fps, duration 680.2 seconds. Exact video-stream durations were rounded down to frame boundaries, shortening the original rounded 680.28-second plan by 0.08 seconds. The original project was preserved and a branch created. All five media hashes matched, join rounding errors stayed within 1 microsecond, and project verification passed.

Receipt: runtime `vectcut-executions/2ca138dbebaa49caa413abce08a3796c.json`.

## Fixed issues

- Upstream defaults to CapCut/9000; explicitly configure the domestic Jianying template and port 9001.
- Health checks previously accepted arbitrary HTTP errors; now validate the result structure of a specific read-only endpoint.
- Save API success does not establish persistence; add save-task status, entity, and media-file checks.
- Millisecond rounding exceeded video-stream duration, causing upstream truncation; the real-media branch aligns to 30 fps.
- CLI autoloads runtime-config.json from the runtime directory to configure the actual local draft directory.

## Unverified

Upstream generates plaintext drafts with the jianying_pro_10 template. This record does not prove opening/playback in Jianying 11.3 or a refreshed draft index. File generation is distinct from final editor acceptance.
