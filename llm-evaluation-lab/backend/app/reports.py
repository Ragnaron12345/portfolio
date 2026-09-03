import json
from typing import Any

from sqlalchemy.orm import Session

from .analytics import comparison_payload, failure_payload, run_summary
from .models import ExperimentRun, Report


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "unavailable"
    if unit == "%":
        return f"{value * 100:.2f}%"
    if unit == "USD":
        return f"${value:.6f}"
    if unit == "ms":
        return f"{value:.1f} ms"
    if unit == "/ 5":
        return f"{value:.2f} / 5"
    return f"{value:.2f} {unit}"


def generate_report(session: Session, run: ExperimentRun) -> Report:
    comparison = comparison_payload(run)
    failures = failure_payload(run)
    regressions = failure_payload(run, regressions_only=True)
    summary = run_summary(run)
    lines = [
        f"# EvalForge report — {run.id}",
        "",
        f"- Status: **{run.status}**",
        f"- Experiment: {summary['experiment_name']}",
        f"- Dataset: {run.config_snapshot['dataset']['name']} v{run.config_snapshot['dataset']['version']}",
        f"- Dataset hash: `{run.config_snapshot['dataset']['hash']}`",
        f"- Created: {summary['created_at']}",
        f"- Git commit: `{run.git_commit or 'unavailable'}`",
        f"- Successful / total: {run.successful} / {run.total}",
        f"- Failed: {run.failed}",
        f"- Retried: {run.retried}",
        "",
        "## Immutable configuration",
        "",
        "```json",
        json.dumps(
            {key: value for key, value in run.config_snapshot.items() if key != "dataset"}
            | {"dataset": {key: value for key, value in run.config_snapshot["dataset"].items() if key != "cases"}},
            indent=2,
        ),
        "```",
        "",
        "## Metric comparison",
        "",
        f"Baseline: **{comparison['baseline']['label']}**  ",
        f"Candidate: **{comparison['candidate']['label']}**",
        "",
        "| Metric | Baseline | Candidate | Delta | Direction | n |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for metric in comparison["metrics"]:
        baseline = metric["baseline"]
        candidate = metric["candidate"]
        delta = metric["delta"]
        delta_text = "unavailable" if delta["absolute"] is None else f"{delta['absolute']:.4f} {delta['display_unit']}"
        lines.append(
            "| "
            + " | ".join(
                [
                    metric["label"] + (" (LLM judge)" if metric["metric_type"] == "judge" else ""),
                    _format_value(baseline["value"] if baseline else None, metric["unit"]),
                    _format_value(candidate["value"] if candidate else None, metric["unit"]),
                    delta_text,
                    f"{metric['better_direction']} is better",
                    str(candidate["sample_count"] if candidate else baseline["sample_count"] if baseline else 0),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Regressions and failures",
            "",
            "Pairwise classification: "
            f"{regressions['pairwise_counts']['improved']} improved, "
            f"{regressions['pairwise_counts']['unchanged']} unchanged, "
            f"{regressions['pairwise_counts']['regressed']} regressed.",
            f"Failure explorer entries: {failures['total']}. Candidate regressions: {regressions['total']}.",
            "",
        ]
    )
    for item in regressions["items"]:
        lines.append(
            f"- `{item['case_id']}` ({item['category']}): "
            f"{', '.join(item['failed_metrics']) or 'quality score decreased'}"
        )
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- Deterministic metrics measure configured references and constraints; "
            "they do not prove production quality.",
            "- Judge metrics are model-based opinions and can be biased or unstable. "
            "They are visually and structurally separated from deterministic metrics.",
            "- Cost is unavailable whenever provider token usage or snapshot pricing is unavailable.",
            "- Aggregate improvement does not erase the case-level regressions listed above.",
            "",
        ]
    )
    payload: dict[str, Any] = {
        "run": summary,
        "comparison": comparison,
        "failures": failures,
        "regressions": regressions,
        "caveats": [
            "Deterministic metrics are benchmark-specific.",
            "Judge metrics are model-based and may be biased or unstable.",
            "Cost requires token usage and snapshot pricing.",
        ],
    }
    report = session.query(Report).filter(Report.run_id == run.id).one_or_none()
    if report is None:
        report = Report(run_id=run.id, markdown="", json_payload={})
        session.add(report)
    report.markdown = "\n".join(lines)
    report.json_payload = payload
    session.commit()
    session.refresh(report)
    return report
