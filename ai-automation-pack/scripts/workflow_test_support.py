"""Small stdlib-only client used by the three end-to-end demo probes."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_BASE = os.getenv("AUTOMATION_API_BASE_URL", "http://localhost:8004").rstrip("/")
TERMINAL = {"completed", "completed_with_warning", "failed", "cancelled", "waiting_for_review"}


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 60,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} returned HTTP {error.code}: {raw}") from error
    except urllib.error.URLError as error:
        raise AssertionError(
            f"Cannot reach {API_BASE}. Start the stack with '.\\manage.ps1 Up'. Error: {error.reason}"
        ) from error


def load_case(filename: str, case_id: str) -> dict[str, Any]:
    data = json.loads((ROOT / "fixtures" / filename).read_text(encoding="utf-8"))
    for case in data["cases"]:
        if case["id"] == case_id:
            return case
    raise KeyError(f"Fixture {case_id!r} not found in {filename}")


def run_workflow(workflow: str, payload: dict[str, Any], *, timeout: float = 90) -> dict[str, Any]:
    started = time.monotonic()
    response = request_json("POST", f"/api/v1/runs/{workflow}", payload, timeout=timeout)
    execution_id = response.get("execution_id") or response.get("id")
    require(execution_id, f"{workflow} ingress did not return execution_id: {response}")

    latest = response
    while time.monotonic() - started < timeout:
        latest = request_json("GET", f"/api/v1/executions/{execution_id}", timeout=15)
        if latest.get("status") in TERMINAL:
            return latest
        time.sleep(0.35)
    raise AssertionError(
        f"{workflow} execution {execution_id} did not reach a review/terminal status within {timeout:.0f}s; "
        f"last state: {latest}"
    )


def list_items(path: str) -> list[dict[str, Any]]:
    data = request_json("GET", path, timeout=20)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise AssertionError(f"Expected a list or page from {path}, received: {data}")


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def deep_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()


def assert_n8n_audit(execution: dict[str, Any], prefix: str) -> None:
    actions = {
        str(item.get("action") or item.get("event_type") or "")
        for item in execution.get("audit_events", [])
    }
    require(
        any(action.startswith(prefix) for action in actions),
        f"Execution {execution.get('execution_id')} has no n8n audit matching {prefix!r}; actions={sorted(actions)}",
    )


def print_result(label: str, execution: dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "case": label,
                "execution_id": execution.get("execution_id") or execution.get("id"),
                "status": execution.get("status"),
                "stage": execution.get("current_stage") or execution.get("stage"),
                "decision": execution.get("decision_summary"),
                "retries": execution.get("retry_count"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

