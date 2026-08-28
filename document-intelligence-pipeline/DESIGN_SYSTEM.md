# DocIntel interface system

## Direction

DocIntel is a forensic editorial workbench. Documents, extracted evidence,
rules, timings, and reviewer decisions are the visual material. The shell uses
open planes and precise rules instead of nested cards.

Source concepts:

- `docs/design-concepts/documents-desktop.png`
- `docs/design-concepts/review-queue-desktop.png`
- `docs/design-concepts/evaluations-desktop.png`

## Tokens

- Workspace: `#f7f8fa`; surface: `#ffffff`; rail: `#11151a`.
- Ink: `#111318`; muted: `#69717c`; rule: `#d9dee6`.
- Operator blue: `#2855d9`; selection: `#edf3ff`.
- Success: `#199651`; review: `#d88700`; failure: `#d72e35`.
- No gradients. Shadows are limited to mobile overlays.
- Headings: `Arial Narrow`, `Roboto Condensed`, `Inter Tight`, sans-serif.
- UI: `Inter`, `Segoe UI`, Arial, sans-serif.
- Data: `IBM Plex Mono`, `Cascadia Code`, Consolas, monospace.
- Radii: 3px rows, 4px controls, 6px drawers. Never pill by default.
- Spacing: 4, 8, 12, 16, 20, 28, 36, 48.

## Component model

- Fixed 210px dark rail and open workspace.
- Dense tables for collections; leading blue rule for selected rows.
- Trace rail with square numbered nodes for pipeline stages and history.
- Definition lists for metadata; horizontal rules for sections.
- Drawers/split panes for details; no card-within-card nesting.
- SVG icon family: 18px, outline, 1.75px stroke, round caps/joins.

## Responsive

At 1100px the rail becomes an overlay and detail panes become full-width. At
760px tables become purposeful row summaries and split workflows become
list-to-detail. Touch targets remain at least 44px.

## Copy lock

Brand: `DOCINTEL`, `DOCUMENT INTELLIGENCE`. Navigation: `Overview`,
`Documents`, `Review queue`, `Evaluations`. Primary actions: `Upload document`,
`Open review`, `Edit and approve`, `Run evaluation`.
