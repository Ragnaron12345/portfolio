# API notes

The OpenAPI schema is served at `/api/v1/docs`. Required resource endpoints from the specification are implemented for datasets, models, prompts, retrieval configurations, experiments, runs, results, failures, comparisons, cancellation, and Markdown/JSON reports. `/api/v1/overview` and `/api/v1/runs` are read models used by the dashboard.

Starting a run returns HTTP 202. A second start for an already active experiment returns HTTP 409, preventing double-click duplication. Missing historical run IDs return HTTP 404 and the UI keeps the missing selection visible rather than selecting the newest run.
