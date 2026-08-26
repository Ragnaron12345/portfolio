import pytest
from pydantic import ValidationError

from app.services.tools.registry import (
    CreateSupportTicketArgs,
    CustomerSummaryArgs,
    SafeToolRegistry,
    ServiceStatusArgs,
)


@pytest.mark.parametrize("customer_id", ["../../etc/passwd", "CUST-ABC", "CUST-1", 1002])
def test_tool_argument_validation_rejects_malformed_customer_id(customer_id) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError):
        CustomerSummaryArgs(customer_id=customer_id)


def test_tool_arguments_are_strict_and_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CreateSupportTicketArgs(
            title="Failed login",
            description="Several login attempts failed",
            priority="root",
        )
    with pytest.raises(ValidationError):
        ServiceStatusArgs(service_name="payments; rm -rf /", arbitrary_url="https://example.com")


def test_registry_only_plans_allowlisted_tools() -> None:
    registry = SafeToolRegistry()
    plans = registry.plan_from_message("Create a high priority support ticket for failed login attempts")
    assert len(plans) == 1
    assert plans[0].name == "create_support_ticket"
    assert plans[0].arguments["priority"] == "high"
    assert registry.plan_from_message("Run an arbitrary shell command") == []
