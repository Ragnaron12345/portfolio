from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "synthetic_documents"
GROUND_TRUTH = ROOT / "data" / "ground_truth.json"
RANDOM = random.Random(20260828)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index in range(20):
        records.append(build_invoice(index))
    for index in range(20):
        records.append(build_statement(index))
    for index in range(20):
        records.append(build_application(index))
    for index in range(4):
        records.append(build_unknown(index))
    payload = {
        "name": "DocIntel synthetic ground truth",
        "version": "1.0",
        "description": "64 fully synthetic documents; 60 supported benchmark cases and 4 unknown routing cases.",
        "counts": {"invoice": 20, "bank_statement": 20, "customer_application": 20, "unknown": 4},
        "documents": records,
    }
    GROUND_TRUTH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {len(records)} documents and {GROUND_TRUTH}")


def build_invoice(index: int) -> dict[str, Any]:
    number = f"INV-2026-{index + 180:04d}"
    subtotal = round(900 + index * 37.5, 2)
    tax = round(subtotal * 0.19, 2)
    total = round(subtotal + tax, 2)
    edge_cases: list[str] = []
    needs_review = False
    review_reason = None
    if index in {3, 13}:
        total = round(total + 42, 2)
        edge_cases.append("incorrect_totals")
        needs_review = True
        review_reason = "Invoice total differs from subtotal + tax by 42.00 EUR."
    if index == 5:
        edge_cases.extend(["rotation", "low_contrast"])
    if index == 7:
        edge_cases.append("missing_fields")
        needs_review = True
        review_reason = "Seller name is missing."
    if index == 9:
        edge_cases.append("multi_page")
    if index == 11:
        edge_cases.append("duplicate_invoice")
    if index == 15:
        edge_cases.append("unusual_layout")
    if index == 18:
        edge_cases.append("odd_dates")
    if index == 19:
        edge_cases.append("empty_page")
    seller = "" if "missing_fields" in edge_cases else "Bluewater Supplies Ltd."
    date_value = "31.12.2025" if "odd_dates" in edge_cases else f"2026-05-{(index % 20) + 1:02d}"
    text = "\n".join(
        [
            "INVOICE",
            f"Invoice Number: {number}",
            f"Invoice Date: {date_value}",
            f"Seller: {seller}",
            "Buyer: Northwind Trading Ltd.",
            "Currency: EUR",
            "ITEM | Industrial valve | 10 | 60.00 | 600.00",
            f"ITEM | Service package | 1 | {subtotal - 600:.2f} | {subtotal - 600:.2f}",
            f"Subtotal: {subtotal:.2f}",
            f"Tax: {tax:.2f}",
            f"Total: {total:.2f}",
        ]
    )
    ground_truth = {
        "document_type": "invoice",
        "invoice_number": number,
        "invoice_date": "2025-12-31" if "odd_dates" in edge_cases else f"2026-05-{(index % 20) + 1:02d}",
        "seller_name": seller,
        "buyer_name": "Northwind Trading Ltd.",
        "currency": "EUR",
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "line_items": [
            {"description": "Industrial valve", "quantity": 10.0, "unit_price": 60.0, "total": 600.0},
            {
                "description": "Service package",
                "quantity": 1.0,
                "unit_price": round(subtotal - 600, 2),
                "total": round(subtotal - 600, 2),
            },
        ],
    }
    return write_record(
        identifier=f"INV-{10000 + index}",
        document_type="invoice",
        text="" if "empty_page" in edge_cases else text,
        ground_truth=ground_truth,
        edge_cases=edge_cases,
        needs_review=needs_review,
        review_reason=review_reason,
        index=index,
    )


def build_statement(index: int) -> dict[str, Any]:
    opening = round(2400 + index * 115.25, 2)
    transactions = [
        {"date": f"2026-04-{2 + index % 10:02d}", "description": "Salary", "amount": 2500.0},
        {"date": f"2026-04-{12 + index % 10:02d}", "description": "Rent", "amount": -1120.0},
        {"date": f"2026-04-{20 + index % 8:02d}", "description": "Utilities", "amount": -184.35},
    ]
    closing = round(opening + sum(item["amount"] for item in transactions), 2)
    edge_cases: list[str] = []
    needs_review = False
    review_reason = None
    if index in {2, 12}:
        edge_cases.extend(["image_only", "low_contrast"])
    if index == 4:
        edge_cases.append("rotation")
    if index == 6:
        transactions[-1]["date"] = "2026-05-04"
        edge_cases.append("odd_dates")
        needs_review = True
        review_reason = "A transaction date falls outside the statement period."
    if index == 8:
        closing += 99
        edge_cases.append("balance_mismatch")
        needs_review = True
        review_reason = "Opening balance plus transactions does not equal closing balance."
    if index == 10:
        edge_cases.append("multi_page")
    if index == 14:
        edge_cases.extend(["handwritten_annotation", "severe_blur"])
        needs_review = True
        review_reason = "OCR quality is too low around closing balance."
    if index == 17:
        edge_cases.append("unusual_layout")
    text_lines = [
        "BANK STATEMENT",
        f"Account Holder: Morgan Ellis {index + 1}",
        f"IBAN: DE89 **** **** {1000 + index:04d}",
        "Period Start: 2026-04-01",
        "Period End: 2026-04-30",
        "Currency: EUR",
        f"Opening Balance: {opening:.2f}",
    ]
    text_lines.extend(f"TX | {item['date']} | {item['description']} | {item['amount']:.2f}" for item in transactions)
    text_lines.append(f"Closing Balance: {closing:.2f}")
    ground_truth = {
        "document_type": "bank_statement",
        "account_holder": f"Morgan Ellis {index + 1}",
        "iban_masked": f"DE89 **** **** {1000 + index:04d}",
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
        "opening_balance": opening,
        "closing_balance": closing,
        "currency": "EUR",
        "transactions": transactions,
    }
    return write_record(
        identifier=f"STMT-{20000 + index}",
        document_type="bank_statement",
        text="\n".join(text_lines),
        ground_truth=ground_truth,
        edge_cases=edge_cases,
        needs_review=needs_review,
        review_reason=review_reason,
        index=index,
    )


def build_application(index: int) -> dict[str, Any]:
    edge_cases: list[str] = []
    needs_review = False
    review_reason = None
    email = f"alex.taylor{index + 1}@example.test"
    phone = f"+49 151 555 {1200 + index}"
    if index in {1, 11}:
        email = "alex.taylor.example.test"
        edge_cases.append("invalid_email")
        needs_review = True
        review_reason = "Email format is invalid."
    if index == 3:
        email = ""
        edge_cases.append("missing_fields")
    if index == 5:
        phone = "12"
        edge_cases.append("odd_phone")
        needs_review = True
        review_reason = "Phone length is outside the supported range."
    if index == 7:
        edge_cases.extend(["rotation", "low_contrast"])
    if index == 9:
        edge_cases.append("unusual_layout")
    if index == 13:
        edge_cases.append("multi_page")
    if index == 16:
        edge_cases.append("noisy_scan")
    text = "\n".join(
        [
            "CUSTOMER APPLICATION",
            f"Full Name: Alex Taylor {index + 1}",
            f"Date of Birth: 199{index % 10}-06-15",
            f"Email: {email}",
            f"Phone: {phone}",
            "Country: Germany",
            "Requested Product: Business Current Account",
        ]
    )
    ground_truth = {
        "document_type": "customer_application",
        "full_name": f"Alex Taylor {index + 1}",
        "date_of_birth": f"199{index % 10}-06-15",
        "email": email or None,
        "phone": phone,
        "country": "Germany",
        "requested_product": "Business Current Account",
    }
    return write_record(
        identifier=f"APP-{30000 + index}",
        document_type="customer_application",
        text=text,
        ground_truth=ground_truth,
        edge_cases=edge_cases,
        needs_review=needs_review,
        review_reason=review_reason,
        index=index,
    )


def build_unknown(index: int) -> dict[str, Any]:
    texts = [
        "WAREHOUSE SAFETY CHECKLIST\nForklift inspection complete\nEmergency exit clear",
        "RESTAURANT MENU\nSeasonal soup\nGrilled vegetables\nApple tart",
        "PROJECT MEETING NOTES\nTimeline discussion\nOwners assigned\nNext meeting Friday",
        "SHIPPING LABEL\nContainer 00918\nPort of Hamburg\nDock 4",
    ]
    return write_record(
        identifier=f"DOC-{40000 + index}",
        document_type="unknown",
        text=texts[index],
        ground_truth=None,
        edge_cases=["unsupported_type"],
        needs_review=True,
        review_reason="Unsupported or unclear document type; no extraction schema was forced.",
        index=index,
    )


def write_record(
    *,
    identifier: str,
    document_type: str,
    text: str,
    ground_truth: dict[str, Any] | None,
    edge_cases: list[str],
    needs_review: bool,
    review_reason: str | None,
    index: int,
) -> dict[str, Any]:
    folder = OUTPUT / document_type
    folder.mkdir(parents=True, exist_ok=True)
    extension = ".pdf" if index % 3 == 0 or "image_only" in edge_cases or "multi_page" in edge_cases else (
        ".jpg" if index % 3 == 1 else ".png"
    )
    filename = identifier + extension
    path = folder / filename
    image = render_page(text, edge_cases)
    if extension == ".pdf":
        pages = [image.convert("RGB")]
        if "multi_page" in edge_cases:
            pages.append(render_page("CONTINUATION\nSupporting detail page\nEnd of document", []).convert("RGB"))
        pages[0].save(path, "PDF", resolution=144, save_all=True, append_images=pages[1:])
    elif extension == ".jpg":
        image.convert("RGB").save(path, "JPEG", quality=82)
    else:
        image.save(path, "PNG")
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    field_count, required_count, numeric_count = counts_for(document_type, ground_truth)
    mime = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg"}[extension]
    return {
        "id": identifier,
        "filename": filename,
        "path": str(path.resolve()),
        "mime_type": mime,
        "sha256": sha256,
        "document_type": document_type,
        "classification_reason": (
            "The text does not contain enough structural signals for a supported document type."
            if document_type == "unknown"
            else "Multiple independent structural signals matched the supported schema."
        ),
        "source_text": text,
        "ground_truth": ground_truth,
        "edge_cases": edge_cases,
        "needs_review": needs_review,
        "review_reason": review_reason,
        "field_count": field_count,
        "required_field_count": required_count,
        "numeric_field_count": numeric_count,
    }


def render_page(text: str, edge_cases: list[str]) -> Image.Image:
    background = 248 if "low_contrast" in edge_cases else 255
    ink = 158 if "low_contrast" in edge_cases else 25
    image = Image.new("RGB", (1240, 1754), (background, background, background))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=26)
    title_font = ImageFont.load_default(size=34)
    y = 110
    for line_index, line in enumerate(text.splitlines()):
        current_font = title_font if line_index == 0 else font
        x = 120 if "unusual_layout" not in edge_cases else 160 + (line_index % 3) * 150
        draw.text((x, y), line, fill=(ink, ink, ink), font=current_font)
        y += 74 if line_index == 0 else 54
    if "noisy_scan" in edge_cases:
        for _ in range(80):
            x = RANDOM.randint(0, image.width - 1)
            y = RANDOM.randint(0, image.height - 1)
            draw.line((x, y, x + RANDOM.randint(2, 18), y), fill=(190, 190, 190), width=1)
    if "severe_blur" in edge_cases:
        image = ImageEnhance.Contrast(image).enhance(0.45)
    if "rotation" in edge_cases:
        image = image.rotate(2.5, expand=False, fillcolor=(background, background, background))
    return image


def counts_for(document_type: str, data: dict[str, Any] | None) -> tuple[int, int, int]:
    if not data:
        return 0, 0, 0
    if document_type == "invoice":
        return 9, 7, 3
    if document_type == "bank_statement":
        return 9, 6, 2 + len(data.get("transactions", []))
    return 7, 1, 0


if __name__ == "__main__":
    main()
