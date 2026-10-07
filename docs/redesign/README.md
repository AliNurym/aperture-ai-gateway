# Aperture design exploration — 6 October 2026

Fifteen alternative visual concepts are in `frontend/public/designs/01.png` through `15.png`, each 1536 × 1024. The gallery is `frontend/public/designs/index.html`; it works as a local file and at `/designs/index.html` through Vite. It supports full-size browsing, arrow-key navigation, light/dark filtering and comparing two concepts. `all-15.jpg` is the overview sheet.

These are concepts awaiting the user's final choice, not implemented application screens. The previous application is still active. Its 44 source files were restored from the exact pre-change snapshot and checked by SHA-256. Unrelated existing work was preserved.

## Preserved versions

- `backups/aperture-design-before-2026-10-06.zip`: original frontend source, public assets, index and package/config files before this redesign request.
- `frontend/legacy`: unpacked copy of the same source and assets.
- `backups/aperture-lime-draft-2026-10-06.zip`: early work on concept 01, retained separately after the user requested a choice of directions.

## Concept brief

Built-in Image Gen was used for all concepts. Each brief requested a complete desktop Aperture workspace with the same existing navigation and Python compute scenarios: Overview, Compute Studio, Agent workflows, Files & results, Agent passports, Worker network and Getting started. Shared screen copy: “Your next idea, ready to run.”, prepare Python workloads and connect a worker, Open Compute Studio, Build a workflow, honest offline gateway/worker state, three workload starting points, recent activity empty state and receipt guide. Each direction specifies distinct palette, typography, navigation model, layout, materials and computational artwork. No original UI screenshot was used as a design reference.

The direction-specific briefs and Russian descriptions are reflected in `frontend/public/designs/catalog.json`. Directions: Lime / Precision, Midnight / Cobalt, Paper / Editorial, Swiss / Signal, Mono / Brutalist, Glacier / Glass, Ink / Quiet, Terminal / Amber, Forest / Nordic, Carbon / Coral, Lilac / Playful, Bauhaus / Primary, Blueprint / Engineering, Cosmos / Violet, Clay / Atelier.

## Verification

All 15 image files were decoded and verified, their dimensions checked, and the overview sheet visually inspected. Gallery JavaScript syntax was checked with Node. The local Vite server at `http://127.0.0.1:3010/` was restarted outside the restricted shell after the original process stopped responding; an HTTP check confirmed status 200 and the correct gallery title. All 44 current source files were again checked against both the unpacked snapshot and the original ZIP and matched. Browser automation remains unavailable because tab acquisition was rejected by the browser URL policy, so browser interaction checks remain unverified. The gallery also opens directly from its folder without a server.

All 15 image URLs also returned HTTP 200 with PNG content. A static interaction audit found and fixed two keyboard-focus issues: stepping through concepts no longer moves focus from the navigation button to Close, and resetting comparison restores focus to a visible card or filter control. Updated script syntax was checked and the served page confirmed to include both changes; rendered browser interaction checks are still pending.

Next step: obtain the user's choice, then apply the selected system across all application screens and verify the implementation in the browser. The full redesign goal remains active.
