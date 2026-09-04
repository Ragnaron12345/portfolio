"""Static guardrails for versioned n8n exports.

The n8n CLI remains the authoritative import check. This fast, offline check
catches accidental secrets, broken connection targets, missing branches, and
unbounded transport retries before a container is started.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "workflows"
EXPECTED = {
    "00-shared-error-handler.json",
    "01-ai-support-triage.json",
    "02-invoice-processing.json",
    "03-incident-intelligence.json",
}
PRODUCTION = EXPECTED - {"00-shared-error-handler.json"}
SECRET_PATTERN = re.compile(
    r'''(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key["']?\s*[:=]\s*["'][^$][^"']+)''',
    re.IGNORECASE,
)


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AssertionError(f"{path.name} is not valid JSON: {error}") from error


def validate_graph(path: Path, workflow: dict[str, Any]) -> None:
    require(workflow.get("id"), f"{path.name}: missing stable workflow id")
    require(workflow.get("name"), f"{path.name}: missing workflow name")
    nodes = workflow.get("nodes")
    require(isinstance(nodes, list) and nodes, f"{path.name}: nodes must be non-empty")
    names = [node.get("name") for node in nodes]
    ids = [node.get("id") for node in nodes]
    require(len(names) == len(set(names)), f"{path.name}: node names must be unique")
    require(len(ids) == len(set(ids)), f"{path.name}: node ids must be unique")
    require(all(names) and all(ids), f"{path.name}: every node needs an id and meaningful name")

    name_set = set(names)
    for source, outputs in workflow.get("connections", {}).items():
        require(source in name_set, f"{path.name}: connection source {source!r} does not exist")
        for output_group in outputs.values():
            for output in output_group:
                for edge in output:
                    target = edge.get("node")
                    require(target in name_set, f"{path.name}: connection target {target!r} does not exist")

    audit_nodes = [node for node in nodes if "Audit" in str(node.get("name"))]
    require(audit_nodes, f"{path.name}: explicit audit node missing")
    for node in audit_nodes:
        body = str(node.get("parameters", {}).get("body", ""))
        require("outcome:" in body, f"{path.name}: audit node {node['name']!r} has no explicit outcome")


def validate_production(path: Path, workflow: dict[str, Any]) -> None:
    nodes = workflow["nodes"]
    node_types = [node["type"] for node in nodes]
    settings = workflow.get("settings", {})
    require(settings.get("errorWorkflow") == "ErrHandler202609", f"{path.name}: shared error handler missing")
    require("n8n-nodes-base.webhook" in node_types, f"{path.name}: webhook trigger missing")
    require("n8n-nodes-base.respondToWebhook" in node_types, f"{path.name}: explicit webhook response missing")
    require(node_types.count("n8n-nodes-base.if") >= 3, f"{path.name}: explicit decision/error branches missing")

    http_nodes = [node for node in nodes if node["type"] == "n8n-nodes-base.httpRequest"]
    internal_calls = [
        node for node in http_nodes if "/api/v1/internal/runs/" in str(node.get("parameters", {}).get("url"))
    ]
    require(len(internal_calls) == 1, f"{path.name}: expected one backend-owned internal run call")
    call = internal_calls[0]
    require(call.get("retryOnFail") is True, f"{path.name}: internal call retry is disabled")
    require(2 <= int(call.get("maxTries", 0)) <= 3, f"{path.name}: internal retry must be bounded at 2-3 tries")
    require(any("Audit" in str(node.get("name")) for node in http_nodes), f"{path.name}: audit HTTP node missing")
    require(
        any(node.get("onError") == "continueRegularOutput" for node in internal_calls),
        f"{path.name}: transport-error branch cannot receive exhausted retry output",
    )

    webhook = next(node for node in nodes if node["type"] == "n8n-nodes-base.webhook")
    require(
        webhook.get("parameters", {}).get("responseMode") == "responseNode",
        f"{path.name}: webhook must return the final execution object",
    )


def main() -> None:
    paths = sorted(WORKFLOW_DIR.glob("*.json"))
    names = {path.name for path in paths}
    require(names == EXPECTED, f"Workflow export set differs: expected={sorted(EXPECTED)}, actual={sorted(names)}")

    ids: set[str] = set()
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        require(not SECRET_PATTERN.search(raw), f"{path.name}: possible embedded secret")
        workflow = load(path)
        validate_graph(path, workflow)
        require(workflow["id"] not in ids, f"{path.name}: duplicate workflow id")
        ids.add(workflow["id"])
        if path.name in PRODUCTION:
            validate_production(path, workflow)
        else:
            types = {node["type"] for node in workflow["nodes"]}
            require("n8n-nodes-base.errorTrigger" in types, "Shared handler has no Error Trigger")
            require(
                any("Audit" in node.get("name", "") for node in workflow["nodes"]),
                "Shared handler does not persist an audit event",
            )

    print(f"Validated {len(paths)} n8n workflow exports: JSON, graph, retries, branches, audit, and secret guard.")


if __name__ == "__main__":
    main()
