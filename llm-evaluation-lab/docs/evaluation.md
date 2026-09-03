# Evaluation protocol

The checked-in JSONL benchmark contains 56 synthetic cases across factual QA, missing-information handling, grounded QA, summarization, extraction, structured output, and prompt-injection/adversarial tasks. It contains no customer data.

Deterministic metrics are exact match, normalized exact match, keyword recall, forbidden claim rate, JSON parse rate, schema validity, expected citation hit, Recall@K, timeout rate, and provider error rate. Operational metrics include success rate, mean/p50/p95 latency, prompt/completion tokens, and estimated cost. Every response contains the unit, better direction, definition, sample count, and numerator/denominator where applicable.

Judge results use a structured 1–5 schema for correctness, groundedness, and relevance. The demonstration judge is deterministic and derived from applicable deterministic evidence; a live judge can be connected through the provider abstraction. Judge scores are opinions, can be biased, and should not be treated as ground truth.

Rate deltas are percentage points. Latency deltas are milliseconds plus relative percent. Cost deltas are USD plus relative percent. A negative latency or cost delta is an improvement because lower is better; color never depends on numeric sign alone.

Pairwise classification compares the exact first and last configuration snapshots and labels each case improved, unchanged, or regressed. Aggregate improvement never removes regressed cases from the explorer.
