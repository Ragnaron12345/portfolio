from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ToolCall


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CustomerSummaryArgs(ToolArguments):
    customer_id: str = Field(pattern=r"^CUST-\d{4,10}$", max_length=20)


class CreateSupportTicketArgs(ToolArguments):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=5, max_length=4000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"

    @field_validator("title", "description")
    @classmethod
    def no_control_characters(cls, value: str) -> str:
        cleaned = value.strip()
        if any(ord(character) < 32 and character not in "\n\t" for character in cleaned):
            raise ValueError("control characters are not allowed")
        return cleaned


class ServiceStatusArgs(ToolArguments):
    service_name: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9 _-]+$")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    arguments_model: type[ToolArguments]
    description: str


@dataclass(frozen=True, slots=True)
class ToolPlan:
    name: str
    arguments: dict[str, Any]


SYNTHETIC_CUSTOMERS: dict[str, dict[str, Any]] = {
    "CUST-1001": {
        "customer_id": "CUST-1001",
        "display_name": "Maya Chen",
        "account_tier": "standard",
        "account_status": "active",
        "open_ticket_count": 0,
    },
    "CUST-1002": {
        "customer_id": "CUST-1002",
        "display_name": "Jonas Weber",
        "account_tier": "premium",
        "account_status": "active",
        "open_ticket_count": 1,
    },
    "CUST-1003": {
        "customer_id": "CUST-1003",
        "display_name": "Sofia Rossi",
        "account_tier": "standard",
        "account_status": "restricted",
        "open_ticket_count": 2,
    },
}

SERVICE_STATUSES: dict[str, dict[str, Any]] = {
    "mobile_app": {"status": "operational", "updated_at": "synthetic-demo"},
    "card_payments": {"status": "operational", "updated_at": "synthetic-demo"},
    "identity_verification": {"status": "degraded", "updated_at": "synthetic-demo"},
    "instant_transfers": {"status": "operational", "updated_at": "synthetic-demo"},
    "notifications": {"status": "operational", "updated_at": "synthetic-demo"},
}


class SafeToolRegistry:
    """Strict allowlist with no shell access and no arbitrary network access."""

    definitions = {
        "get_customer_summary": ToolDefinition(
            name="get_customer_summary",
            arguments_model=CustomerSummaryArgs,
            description="Read one synthetic demo customer's non-sensitive summary.",
        ),
        "create_support_ticket": ToolDefinition(
            name="create_support_ticket",
            arguments_model=CreateSupportTicketArgs,
            description="Create a synthetic support ticket; urgent priority requires human approval.",
        ),
        "get_service_status": ToolDefinition(
            name="get_service_status",
            arguments_model=ServiceStatusArgs,
            description="Read a synthetic service status from the local allowlist.",
        ),
    }

    def plan_from_message(self, message: str) -> list[ToolPlan]:
        lowered = message.casefold()
        customer_match = re.search(r"\bCUST[-_ ]?(\d{4,10})\b", message, re.I)
        if customer_match and any(word in lowered for word in ("summary", "customer", "account")):
            return [
                ToolPlan(
                    name="get_customer_summary",
                    arguments={"customer_id": f"CUST-{customer_match.group(1)}"},
                )
            ]

        if re.search(r"\b(create|open|raise)\b.*\b(ticket|case)\b", message, re.I | re.S):
            if "urgent" in lowered or "critical" in lowered:
                priority = "urgent"
            elif "high priority" in lowered or "high-priority" in lowered:
                priority = "high"
            elif "low priority" in lowered:
                priority = "low"
            else:
                priority = "normal"
            title = _ticket_title(message)
            return [
                ToolPlan(
                    name="create_support_ticket",
                    arguments={"title": title, "description": message.strip(), "priority": priority},
                )
            ]

        normalized = re.sub(r"[\s-]+", "_", lowered)
        mentions_known_service = any(name in normalized for name in SERVICE_STATUSES)
        asks_status = any(term in lowered for term in ("status", "down", "available", "operational"))
        if (
            "service status" in lowered
            or re.search(r"\bis .+ (down|available|operational)\b", lowered)
            or (mentions_known_service and asks_status)
        ):
            service = next((name for name in SERVICE_STATUSES if name in normalized), None)
            if service is None:
                match = re.search(r"service status(?: for| of)?\s+([A-Za-z0-9 _-]{2,80})", message, re.I)
                service = match.group(1).strip(" ?.!") if match else "unknown"
            return [ToolPlan(name="get_service_status", arguments={"service_name": service})]
        return []

    def invoke(
        self,
        db: Session,
        *,
        request_id: str,
        name: str,
        arguments: dict[str, Any],
        approved: bool = False,
    ) -> ToolCall:
        definition = self.definitions.get(name)
        if definition is None:
            raise ValueError("tool is not allowlisted")
        started = time.perf_counter()
        try:
            validated = definition.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            call = ToolCall(
                request_id=request_id,
                tool_name=name,
                arguments_json=arguments,
                status="validation_failed",
                requires_approval=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error="tool argument validation failed",
            )
            db.add(call)
            db.flush()
            raise ValueError("tool argument validation failed") from exc

        requires_approval = self._requires_approval(name, validated)
        call = ToolCall(
            request_id=request_id,
            tool_name=name,
            arguments_json=validated.model_dump(),
            status="pending_approval" if requires_approval and not approved else "running",
            requires_approval=requires_approval,
        )
        db.add(call)
        db.flush()
        if requires_approval and not approved:
            call.result_json = {"message": "Awaiting human approval before execution."}
            call.latency_ms = (time.perf_counter() - started) * 1000
            return call
        self._execute(call, validated)
        call.latency_ms = (time.perf_counter() - started) * 1000
        return call

    def execute_pending_for_request(self, db: Session, request_id: str) -> list[ToolCall]:
        pending = list(
            db.scalars(
                select(ToolCall).where(
                    ToolCall.request_id == request_id,
                    ToolCall.status == "pending_approval",
                )
            ).all()
        )
        for call in pending:
            definition = self.definitions[call.tool_name]
            validated = definition.arguments_model.model_validate(call.arguments_json)
            started = time.perf_counter()
            call.status = "running"
            self._execute(call, validated)
            call.latency_ms += (time.perf_counter() - started) * 1000
        return pending

    @staticmethod
    def _requires_approval(name: str, arguments: ToolArguments) -> bool:
        return (
            name == "create_support_ticket"
            and isinstance(arguments, CreateSupportTicketArgs)
            and arguments.priority == "urgent"
        )

    @staticmethod
    def _execute(call: ToolCall, arguments: ToolArguments) -> None:
        if call.tool_name == "get_customer_summary":
            args = CustomerSummaryArgs.model_validate(arguments)
            customer = SYNTHETIC_CUSTOMERS.get(args.customer_id)
            if customer is None:
                call.status = "failed"
                call.error = "synthetic customer not found"
                call.result_json = {"found": False, "customer_id": args.customer_id}
            else:
                call.status = "succeeded"
                call.result_json = {"found": True, **customer}
        elif call.tool_name == "create_support_ticket":
            args = CreateSupportTicketArgs.model_validate(arguments)
            call.status = "succeeded"
            call.result_json = {
                "ticket_id": f"TKT-{uuid4().hex[:10].upper()}",
                "status": "open",
                "priority": args.priority,
                "title": args.title,
                "synthetic": True,
            }
        elif call.tool_name == "get_service_status":
            args = ServiceStatusArgs.model_validate(arguments)
            canonical_name = re.sub(r"[\s-]+", "_", args.service_name.casefold())
            status = SERVICE_STATUSES.get(canonical_name)
            if status is None:
                call.status = "succeeded"
                call.result_json = {
                    "found": False,
                    "service_name": args.service_name,
                    "status": "unknown",
                    "message": "Which service should be checked? Current status cannot be inferred.",
                }
            else:
                call.status = "succeeded"
                call.result_json = {"found": True, "service_name": canonical_name, **status}
        else:  # pragma: no cover - guarded by allowlist
            raise ValueError("tool is not allowlisted")


def _ticket_title(message: str) -> str:
    cleaned = re.sub(r"\b(create|open|raise)\b\s+(?:a\s+)?(?:high[- ]priority\s+)?", "", message, flags=re.I)
    cleaned = re.sub(r"\bsupport\s+(ticket|case)\b\s*(?:for|about|:)?\s*", "", cleaned, flags=re.I)
    cleaned = " ".join(cleaned.strip(" .").split())
    return (cleaned or "Support request")[:160]
