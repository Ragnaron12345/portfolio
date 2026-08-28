from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[float, Field(ge=-1_000_000_000, le=1_000_000_000)]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LineItem(StrictSchema):
    description: str
    quantity: float
    unit_price: Money
    total: Money


class InvoiceExtraction(StrictSchema):
    document_type: Literal["invoice"]
    invoice_number: str
    invoice_date: date
    seller_name: str
    buyer_name: str | None
    currency: str
    subtotal: Money
    tax: Money
    total: Money
    line_items: list[LineItem]


class Transaction(StrictSchema):
    date: date
    description: str
    amount: Money


class BankStatementExtraction(StrictSchema):
    document_type: Literal["bank_statement"]
    account_holder: str
    iban_masked: str | None
    period_start: date
    period_end: date
    opening_balance: Money
    closing_balance: Money
    currency: str
    transactions: list[Transaction]


class CustomerApplicationExtraction(StrictSchema):
    document_type: Literal["customer_application"]
    full_name: str
    date_of_birth: date | None
    email: str | None
    phone: str | None
    country: str | None
    requested_product: str | None


ExtractionSchema = InvoiceExtraction | BankStatementExtraction | CustomerApplicationExtraction


class Classification(StrictSchema):
    document_type: Literal["invoice", "bank_statement", "customer_application", "unknown"]
    confidence: float = Field(ge=0, le=1)
    reason: str


class ReviewDecision(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


class EditApproveDecision(ReviewDecision):
    fields: dict[str, Any]


class EvaluationRequest(BaseModel):
    name: str = Field(default="Synthetic dataset comparison", min_length=1, max_length=200)
    configurations: list[Literal["baseline", "improved"]] = ["baseline", "improved"]


class PhoneValue(BaseModel):
    value: str

    @field_validator("value")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return "+" + "".join(character for character in value if character.isdigit())
