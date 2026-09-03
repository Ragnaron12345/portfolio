# EvalForge design system

The accepted visual references are:

- `docs/concepts/evalforge-overview.png` — primary overview surface at 1536×1024.
- `docs/concepts/evalforge-run-detail.png` — historical run comparison and immutable configuration drawer at 1536×1024.

## Direction

EvalForge is styled as an engineering instrument rather than a marketing SaaS page. The main motifs are a graphite navigation rail, open warm-gray canvas, horizontal metric bands, dense ruled tables, a fixed evidence/configuration drawer, tabular numbers, and semantic color used only for real state.

## Tokens

- Canvas `#f4f5f5`, surface `#fbfbfa`, strong surface `#ffffff`.
- Ink `#151b20`, muted `#68737b`, borders `#d5d9dc` / `#bfc5c9`.
- Navigation `#20272d`, selected navigation `#303b44`.
- Action cobalt `#1265d6`; verified success `#087a4f`; warning `#a76205`; error/regression `#c32f31`.
- Radius 5–7px for controls and panels. Tables and bands remain square-edged.
- Content typography: Segoe UI / Arial. Technical IDs: Cascadia Code / Consolas.
- Motion: progress only; reduced-motion preference disables the loading rotation.

## Component and state inventory

Navigation rail, top utility bar, page header, metric strip, data table, progress bar, status indicator, matrix preview, tab row, comparison table, metric definition popover, configuration drawer, filter bar, evidence inspector, prompt diff, dataset case list, retrieved chunk list, loading/empty/error states, and partial-success banner.

Run selection lives in `/runs/{run_id}`. Failure and RAG inspectors use `?runId=`. Polling never rewrites these values.

## Visible copy lock for the primary viewport

`EvalForge`, `AI Engineering`, `API`, `New experiment`, `Overview`, `Experiment builder`, `Runs`, `Failures`, `Prompt registry`, `Datasets`, `RAG inspector`, `Evaluation overview`, `Runs this week`, `Success rate`, `Average p95 latency`, `Total spend`, `Recent runs`, and `Regression watch`.

All numbers are dynamic API values. The interface uses `unavailable` when token usage, price, or an applicable metric is absent.
