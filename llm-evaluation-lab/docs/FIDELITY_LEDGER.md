# Design fidelity ledger

The generated concept at `docs/concepts/evalforge-overview.png` was used as the visual contract. The implemented native-size capture is `docs/images/evalforge-overview.png` at 1536 × 1024.

| Dimension | Concept | Implemented | Result |
| --- | --- | --- | --- |
| Layout | 212 px dark navigation rail, broad work canvas, narrow regression rail | 220 px navigation rail, fluid work canvas, 310 px regression rail | Faithful; proportions remain within the concept's intended hierarchy |
| Typography | Compact enterprise sans-serif with strong numerical hierarchy | Segoe UI with compact labels, 29 px page title, tabular metric numerals | Faithful; no decorative display type introduced |
| Palette | Graphite rail, warm near-white canvas, cobalt actions, semantic green/red/amber | Matching graphite/canvas/cobalt system with accessible semantic status fills | Faithful |
| Container model | Border-led metric band, data table and evidence rail; minimal card treatment | The same metric band/table/rail structure across Overview and detail pages | Faithful; avoids dashboard card grids |
| Copy | Product-oriented placeholders and example runs | Persisted run names, measured statistics, exact case IDs and regression labels | Intentionally changed to real application data |
| Interaction states | Active nav, statuses, progress, row actions and regression affordances | Active nav, links, progress, completed/partial/error states, filters and drawers | Faithful and extended to all documented workflows |
| Responsive behavior | Desktop concept only | 76 px tablet rail; mobile icon strip, stacked panels and locally scrollable data tables | Added without changing desktop composition |

Intentional deviations: documentation/theme/notification chrome and table pagination from the concept were omitted because they are not part of the demo specification; the three seeded runs fit on one screen. The implemented regression rail shows three persisted regressions instead of six illustrative placeholders.
