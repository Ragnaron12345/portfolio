from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Run and export a persisted Nexora evaluation artifact.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8001/api/v1")
    parser.add_argument("--dataset", choices=("regression", "held_out"), default="held_out")
    parser.add_argument("--name", default="Held-out portfolio comparison")
    parser.add_argument("--output", action="append", required=True, type=Path)
    args = parser.parse_args()

    payload = {
        "name": args.name,
        "dataset": args.dataset,
        "configurations": ["baseline", "improved"],
    }
    health = _request_json(f"{args.api_base.rstrip('/')}/health")
    if health.get("provider_mode") != "mock":
        raise RuntimeError(
            "artifact export requires NEXORA_AI_PROVIDER_MODE=mock; "
            "start the stack with docker-compose.evaluation.yml"
        )
    run = _request_json(f"{args.api_base.rstrip('/')}/evals/run", payload)
    if run.get("status") != "completed":
        run_id = run.get("id")
        if not run_id:
            raise RuntimeError("evaluation response did not contain a run id")
        run = _wait_for_run(args.api_base, str(run_id))
    if (run.get("config") or {}).get("provider_mode") != "mock":
        raise RuntimeError("evaluation run was not persisted in mock mode")

    repository = Path(__file__).resolve().parents[1]
    case_file = "held_out.json" if args.dataset == "held_out" else "cases.json"
    dataset_path = repository / "data" / "eval_cases" / case_file
    result_count = len(run.get("results") or [])
    artifact = {
        "schema_version": "1.0.0",
        "artifact_id": f"deterministic-{args.dataset.replace('_', '-')}-{result_count // 2}-v1",
        "title": f"Nexora deterministic {args.dataset.replace('_', ' ')} baseline/improved comparison",
        "provenance": {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "generated_from_persisted_results": True,
            "execution_profile": "local_deterministic_mock",
            "workspace_revision": _git_revision(repository),
            "dataset": {
                "split": args.dataset,
                "path": str(dataset_path.relative_to(repository)).replace("\\", "/"),
                "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            },
            "configurations": ["baseline", "improved"],
            "provider_network_calls": False,
        },
        "run": run,
        "interpretation": [
            "This artifact is deterministic regression evidence for the pinned dataset and runtime, not production accuracy.",
            "The held-out split was separate during query-expansion development but is public after repository publication.",
            "Latency is machine-specific and provider cost is zero in deterministic mock mode.",
        ],
    }
    rendered = json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    for output in args.output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote {output} ({result_count} persisted results)")


def _request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "nexora-evaluation-exporter"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"evaluation API returned {exc.code}: {detail}") from exc


def _wait_for_run(api_base: str, run_id: str) -> dict[str, Any]:
    for _attempt in range(120):
        run = _request_json(f"{api_base.rstrip('/')}/evals/runs/{run_id}")
        if run.get("status") in {"completed", "failed"}:
            return run
        time.sleep(1)
    raise TimeoutError(f"evaluation run {run_id} did not complete within 120 seconds")


def _git_revision(repository: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        capture_output=True,
        check=False,
        text=True,
    )
    return completed.stdout.strip() or None


if __name__ == "__main__":
    main()
