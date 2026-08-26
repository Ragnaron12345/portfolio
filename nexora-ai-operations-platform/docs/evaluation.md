# Evaluation

Nexora separates development regression from independent held-out evaluation.
The two checked-in datasets are:

- `data/eval_cases/cases.json`: 40 visible development/regression cases.
- `data/eval_cases/held_out.json`: 30 separately versioned paraphrase,
  multilingual, indirect-injection, missing-evidence, conflict, tool, and
  high-risk cases.

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
Provider-backed reporting should use repeated trials, uncertainty intervals,
failure-rate reporting, and pinned model identifiers. A strong portfolio report
shows regression and held-out results separately and discusses failures instead
of presenting a single 40/40 headline.


