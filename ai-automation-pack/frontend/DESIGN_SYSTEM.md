# Flowline interface system

## Source concepts

The production UI is implemented against these accepted visual references:

- `../docs/design-concepts/overview-desktop.png` (1586 × 992)
- `../docs/design-concepts/review-desktop.png` (1568 × 1003)
- `../docs/design-concepts/executions-mobile.png` (853 × 1844)

The design extends their exact language to the execution detail, mock-system,
audit and demo-launcher surfaces required by the product specification.

## Art direction

Flowline is an operations console, not a marketing dashboard. Its visual
material is execution evidence: compact data rows, stages, deterministic
validation, policy sources and operator decisions. A deep navy navigation rail
anchors white working planes. Cobalt communicates navigation and active state;
green, amber and red are reserved for operational meaning.

Signature motif: a fine trace rail with circular stage nodes. It appears in
live activity, execution detail and human review. Tables and divided planes are
preferred to generic card grids, glass, glow or decorative AI imagery.

## Tokens

### Color

- Navigation navy: `#031d35`
- Deep navy: `#021426`
- Selected navigation: `#103d76`
- Workspace: `#ffffff` (true white, matching the concepts)
- Secondary work surface: `#f7f9fc`
- Ink: `#0b172b`
- Muted ink: `#5b687b`
- Rule: `#d3dbe6`
- Strong rule: `#b7c1cf`
- Active cobalt: `#0b55e6`
- Active wash: `#edf4ff`
- Success: `#069653`
- Warning/review: `#d98900`
- Danger/failure: `#e21c32`

No decorative gradients are used in content. The subtle navy shell gradient is
the only gradient and follows the supplied concepts. Shadows are reserved for
modal/drawer elevation.

### Typography

- UI and headings: `Segoe UI`, Arial, sans-serif.
- IDs, correlations, timestamps and extracted values: `Cascadia Code`,
  `SFMono-Regular`, Consolas, monospace.
- Desktop page title: 29/36, 720, -0.025em.
- Mobile page title: 26/33, 720.
- Section title: 13–15/19–22, 700.
- Body: 11–13/17–20.
- Operational data: 9–12/15–19.
- Metric: 28/33, 650, tabular numerals.

### Geometry and rhythm

- Desktop navigation rail: 224px.
- Global status bar: 50px; mobile brand bar: 82px.
- Desktop content gutter: 20–26px; mobile: 16px (12px under 420px).
- Spacing scale: 4, 7, 9, 12, 14, 17, 20, 26, 34.
- Control height: 36–38px desktop; minimum 44px mobile.
- Radius: 5px for bounded controls and surfaces; no universal pills.
- Selected rows: cobalt wash and 3–4px leading rule.

## Component families

- `AppShell`: fixed desktop rail, API-backed health bar and mobile bottom nav.
- `MetricStrip`, `WorkflowHealth`, `ExecutionList`: numeric operational density.
- `Timeline`: completed, active, waiting and failed trace nodes.
- `ExecutionDetail`: workflow-specific support, invoice and incident evidence.
- `ReviewQueue`: newest-first queue, decision evidence, history and stable action bar.
- `MockSystems`: CRM, Jira, Slack and ERP records with originating execution IDs.
- `AuditLog`: searchable event table and readable detail plane.
- `RunDemoModal`: API-driven scenario selector and launcher.
- Shared loading rows, errors, empty states, status marks, fields and buttons.

## Data and safety rules

- The API client normalizes unknown transport payloads at one boundary.
- React text nodes escape external input; no `dangerouslySetInnerHTML` is used.
- Long JSON-looking model strings are replaced by a safe explanatory message.
- Malformed extraction output is never rendered. Exact backend review reasons are
  preserved.
- Incident causes are labelled as hypotheses in the UI.
- Rates and latency always display units.
- Protected side effects remain visibly gated by approval state.

## URL and polling state

- Selected execution: `/executions?execution=…`
- Workflow filter: `/executions?workflow=…`
- Selected review: `/reviews?review=…`
- Review status: `/reviews?status=…`
- Mock system: `/systems?system=…`
- Selected audit event: `/audit?event=…`

Polling runs every five seconds. Selection is read from the URL and is never
derived again during refresh, so an older selected record cannot jump to the
newest execution or review item.

## Responsive behavior

At `<=720px`, the desktop rail becomes a persistent five-destination bottom
navigation; the dark brand/health bar remains. Metric strips become compact or
horizontally scrollable, dense tables become purposeful record summaries, the
selected execution expands inline with a horizontal trace, and workflow
evidence remains available directly below the list. Review columns stack into
queue, evidence, trace/history and actions. Every interactive target is at least
44px where practical.

## Accessibility and motion

- Semantic headings, tables/list roles, labels and `aria-current` identify state.
- Modal focus is trapped; Escape and backdrop close it when safe.
- Status is expressed with text as well as color.
- Focus rings meet contrast requirements.
- Loading, error and success changes use appropriate live regions.
- `prefers-reduced-motion` removes non-essential transitions and animations.

## Above-the-fold copy lock

- Brand: `FLOWLINE`, `AI Automation Pack`
- Navigation: `Overview`, `Executions`, `Review Queue`, `Mock Systems`, `Audit Log`
- Primary page titles: `Workflow operations`, `Executions`, `Human review`,
  `Mock systems`, `Audit log`
- Primary action: `Run demo`

No decorative AI badge, hero pretitle, fake social proof or invented business
metric is introduced.
