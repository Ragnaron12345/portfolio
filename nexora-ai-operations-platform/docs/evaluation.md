# Evaluation

Nexora separates development regression from independent held-out evaluation.
The two checked-in datasets are:

- `data/eval_cases/cases.json`: 40 visible development/regression cases.
- `data/eval_cases/held_out.json`: 30 separately versioned paraphrase,
  multilingual, indirect-injection, missing-evidence, conflict, tool, and
  high-risk cases.

Persisted comparison artifacts are versioned under `data/eval_results`. The
full 30-case held-out baseline/improved run is
`deterministic-held-out-30-v1.json` and contains 60 per-case results plus run
provenance. Reproduce it against the local stack with:

```powershell
docker compose -f docker-compose.yml -f docker-compose.evaluation.yml up -d --build
python scripts/export_evaluation.py --output data/eval_results/deterministic-held-out-30-v1.json
```

The evaluation override pins mock mode even when a developer has provider
credentials in ignored local environment files, preventing accidental network
calls and keeping the checked-in comparison reproducible.

The held-out questions were not used to author query-expansion rules. Expansion
uses token-level domain vocabulary rather than matching benchmark sentences.
The split does not make the benchmark secret after publication; it records a
cleaner development protocol and should be replaced or rotated for future work.

## Running a comparison

Use `POST /api/v1/evals/run` with `dataset` set to `regression` or `held_out`:

```json
{
  "name": "Held-out comparison",
  "dataset": "held_out",
  "configurations": ["baseline", "improved"]
}
```

`baseline` uses semantic retrieval only. `improved` combines semantic similarity,
keyword coverage, token-level domain expansion, and opportunistic evidence
retrieval. Because several variables change together, results describe a pipeline
comparison, not an isolated reranker ablation.

## Pass gates

Each result records intent accuracy, escalation accuracy, citation correctness,
answer keyword correctness, groundedness, retrieval coverage, tool policy,
safety, structured-output validity, latency, tokens, model, and estimated cost.
A case passes only when its required correctness and safety gates pass.

Every run persists dataset hashes, evaluator and pipeline hashes, model registry,
runtime settings, knowledge snapshot, and per-case evidence. Identical concurrent
runs are deduplicated; knowledge drift invalidates the run.

## Honest interpretation

Deterministic mock scores are regression evidence, not production-quality claims.
The current held-out artifact records 16.67% pass rate for both configurations;
improved retrieval recall rises from 39.13% to 47.83% and groundedness from
25.56% to 32.22%. This is a surfaced generalization gap, not a release claim.
Provider-backed reporting should use repeated trials, uncertainty intervals,
failure-rate reporting, and pinned model identifiers. A strong portfolio report
shows regression and held-out results separately and discusses failures instead
of presenting a single 40/40 headline.


