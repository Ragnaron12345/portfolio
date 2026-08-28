# Demo acceptance record

Validated against the production Docker Compose stack at a native
1536 × 1024 desktop viewport on 28 August 2026.

## Documentation scenarios

| Scenario | Evidence | Result |
|---|---|---|
| Clean invoice | Uploaded `INV-10002.png` through the live reverse proxy; Tesseract OCR extracted one page, strict invoice schema and all applicable rules passed, confidence 97.97%. | Pass |
| Incorrect invoice | Invoice with a EUR 42.00 arithmetic discrepancy entered review; total was corrected and the item was approved through both the API and rendered edit workflow. | Pass |
| Image-only statement | Synthetic corpus includes image-only, low-contrast statement cases; per-page records identify OCR and preserve quality/latency evidence. | Pass |
| Unknown document | Four unsupported documents are classified `unknown`, retain text, omit forced structured data, and enter human review with an explicit reason. | Pass |
| Evaluation persistence | Selected `Synthetic dataset · Run 0042`, reloaded the rendered app, and confirmed the same run remained selected. | Pass |
| Oversized upload | Backend test sends a payload above the configured 10 MB limit and asserts HTTP 413 with no persisted partial document. | Pass |

## Runtime checks

- PostgreSQL, FastAPI, and Nginx/React containers all reported healthy.
- The container contains PyMuPDF and local Tesseract; host paths are rebuilt
  from the mounted dataset root when demo records are seeded.
- Live evaluation completed over 60 supported documents and rendered all ten
  baseline/improved metrics, configuration descriptions, improvements, and
  remaining failures.
- Browser console contained no warnings or errors on the verified path.

## Visual fidelity ledger

1. Retained the concept's graphite 210 px operator rail, compact wordmark,
   four-icon navigation, and bottom-docked operator identity.
2. Retained the split operational workspace: dense document table on the left,
   persistent evidence inspector on the right, with no floating card grid.
3. Retained the semantic color grammar: blue for action/selection, green for
   accepted/pass, amber for review/warning, and red for failed states.
4. Retained the numbered vertical processing trace, per-stage timing, explicit
   skipped/failure states, and rule-level validation evidence.
5. Retained the Original / Extracted Text / Structured Data / Validation tabs,
   while adding live retry and OCR rerun actions required by the product brief.
6. Retained the editorial density, square geometry, thin rules, mono numeric
   evidence, and high-contrast cool-white surfaces; no gradients or decorative
   illustrations were introduced.
7. Above-fold copy is exact for `Documents`, `Upload document`, `Processed`,
   `Auto-accepted`, `Needs review`, `Failed`, `Search documents…`, `Original`,
   `Extracted Text`, `Structured Data`, `Validation`, and `Processing trace`.
   Counts, filename, reasons, and dates intentionally differ because they are
   produced by the live dataset and acceptance upload rather than hard-coded.

- Reference concept: `docs/design-concepts/documents-desktop.png`
- Verified implementation: `docs/qa/documents-1536x1024.png`
- Evaluation implementation: `docs/qa/evaluations-1536x1024.png`
