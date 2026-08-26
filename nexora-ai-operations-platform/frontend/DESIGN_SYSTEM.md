# Nexora interface system

## Art direction

**Concept:** an editorial AI operations command center where every decision can
be followed through a precise trace rail.

Primary direction: **Technical Elegance**. Supporting trait: **Quiet
Precision**.

Visual principles:

1. Data is the visual material: tables, timings, confidence factors and source
   evidence create the hierarchy.
2. Open planes beat stacked cards: use rules, columns, rails and restrained
   surface changes before containers.
3. Orange marks operator intent; semantic colors report system state only.

Signature motif: a one-pixel vertical trace rail with circular stage nodes,
used for pipeline execution, live traces, ingestion and review history.

Anti-goals: purple AI gradients, glow, glass, bento grids, chat-bubble
decoration, fake marketing metrics, universal rounded cards, black-and-gold
"luxury" styling and motion without causal meaning.

## Source concepts

- `design-concepts/overview-desktop.png`
- `design-concepts/request-console-desktop.png`
- `design-concepts/review-queue-desktop.png`
- `design-concepts/knowledge-base-desktop.png`
- `design-concepts/evaluations-desktop.png`
- `design-concepts/responsive-mobile.png`

## Tokens

### Color

- Workspace / true cool white: `#f7f8f8`
- Elevated work surface: `#ffffff`
- Sidebar: `#101417`
- Sidebar selected: `#20262b`
- Ink: `#111518`
- Muted ink: `#687078`
- Rule: `#d9dde0`
- Strong rule: `#bdc3c8`
- Operator orange: `#f04b23`
- Orange hover: `#d93d17`
- Link blue: `#1769e0`
- Success: `#148a4b`
- Warning: `#c96c13`
- Danger: `#d93636`
- Selection: `#edf4ff`

No gradients. Shadows are reserved for drawers and mobile navigation only.

### Typography

- Display/headings: `Arial Narrow`, `Roboto Condensed`, `Inter Tight`, sans-serif.
- UI body: `Inter`, `Segoe UI`, Arial, sans-serif.
- Operational data: `IBM Plex Mono`, `Cascadia Code`, Consolas, monospace.
- Page title: 36/40, 700, -0.035em.
- Section title: 18/24, 700, -0.015em.
- Body: 14/21, 450.
- Control: 13/18, 600.
- Data: 12/18, 500.
- Metric: 28/32, 650, -0.03em.

### Geometry and rhythm

- Desktop sidebar: 232px; detail drawer: 380-440px.
- Content gutter: 28px desktop, 16px tablet, 14px mobile.
- Spacing scale: 4, 8, 12, 16, 20, 28, 36, 48.
- Control height: 38px desktop; 44px mobile.
- Radius: 2px rules/tables, 4px controls, 6px overlays; never pill-shaped
  unless representing a compact state.
- Border: 1px. Active sidebar and selected rows use a 3px orange leading rule.

### Motion

- Hover/focus: 120ms ease-out.
- Drawer/navigation: 220ms cubic-bezier(.22,1,.36,1).
- New trace node: 300ms ease-out opacity/scale.
- Reduced-motion mode removes transforms and non-essential transitions.

## Container model

The shell uses a fixed rail plus an open workspace. Feature regions are split
with borders and background shifts, not nested cards. Dense information uses
tables; processes use trace rails; metadata uses definition lists; actions sit
in stable toolbars. Drawers are the only elevated desktop surface.

## Component families

- `AppShell`, desktop `Sidebar`, mobile `Topbar` and navigation drawer.
- `PageHeader`, `Toolbar`, `MetricStrip`, `DataTable`, `StatusMark`.
- `TraceRail` for request stages, live traces, ingestion and history.
- `Panel`, only for bounded graphs/forms; nesting panels is prohibited.
- `Field`, `Select`, `TextArea`, primary/secondary/danger buttons.
- `DetailDrawer`, `EmptyState`, `LoadingRows`, `ErrorBanner`.
- SVG icon family: 18px, outline, 1.75px stroke, round caps/joins.

## Responsive rules

- At <= 1040px the sidebar collapses to an overlay and detail drawers become a
  full-height sheet.
- At <= 720px metric strips scroll horizontally, tables switch to purposeful
  row summaries, toolbars wrap, and split views become list -> detail flows.
- Mobile touch targets are at least 44px. Primary actions span available width
  when that improves task completion.
- Charts keep a 240px minimum plot height; labels are reduced, never scaled as
  raster.

## Above-the-fold copy lock

- Brand: `NEXORA`, `AI Operations`
- Navigation: `Overview`, `Request Console`, `Review Queue`, `Knowledge Base`,
  `Evaluations`
- Overview: `Operations overview`, `New request`
- Console: `Request Console`, `Run request`
- Reviews: `Review Queue`
- Knowledge: `Knowledge Base`, `Upload document`
- Evals: `Evaluations`, `Run evaluation`

No decorative pretitle, badge or explanatory hero copy may be added.
