from __future__ import annotations

import io
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader

from app.config import Settings


class DocumentExtractionError(ValueError):
    pass


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    extraction_method: str
    text: str
    character_count: int
    ocr_quality: float | None
    latency_ms: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class OCRProvider(ABC):
    name: str

    @abstractmethod
    def extract(self, image: Image.Image) -> tuple[str, float]:
        raise NotImplementedError


class TesseractOCRProvider(OCRProvider):
    name = "tesseract"

    def extract(self, image: Image.Image) -> tuple[str, float]:
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as exc:  # pragma: no cover - deployment boundary
            raise DocumentExtractionError("OCR runtime is unavailable") from exc

        normalized = ImageOps.autocontrast(image.convert("L"))
        data = pytesseract.image_to_data(normalized, output_type=Output.DICT, config="--psm 6")
        words: list[str] = []
        confidences: list[float] = []
        for raw_text, raw_confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
            word = str(raw_text).strip()
            try:
                confidence = float(raw_confidence)
            except (TypeError, ValueError):
                confidence = -1
            if word:
                words.append(word)
            if confidence >= 0:
                confidences.append(confidence / 100)
        return " ".join(words), round(sum(confidences) / len(confidences), 4) if confidences else 0.0


class StaticOCRProvider(OCRProvider):
    """Deterministic OCR test adapter."""

    name = "static-test-ocr"

    def __init__(self, text: str, quality: float = 0.91) -> None:
        self.text = text
        self.quality = quality

    def extract(self, image: Image.Image) -> tuple[str, float]:  # noqa: ARG002
        return self.text, self.quality


def sniff_file(filename: str, declared_mime: str, prefix: bytes) -> tuple[str, str]:
    extension = Path(filename).suffix.casefold()
    allowed = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    if extension not in allowed:
        raise DocumentExtractionError("Unsupported file type. Use PDF, PNG, JPG, or JPEG.")
    signatures = {
        ".pdf": prefix.startswith(b"%PDF-"),
        ".png": prefix.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": prefix.startswith(b"\xff\xd8\xff"),
        ".jpeg": prefix.startswith(b"\xff\xd8\xff"),
    }
    if not signatures[extension]:
        raise DocumentExtractionError("File content does not match its extension.")
    expected = allowed[extension]
    accepted_mimes = {expected, "application/octet-stream"}
    if declared_mime and declared_mime.casefold() not in accepted_mimes:
        raise DocumentExtractionError(f"MIME type {declared_mime!r} does not match {extension}.")
    return extension, expected


def extract_document(
    path: Path,
    settings: Settings,
    *,
    ocr_provider: OCRProvider | None = None,
    force_ocr: bool = False,
) -> list[ExtractedPage]:
    provider = ocr_provider or TesseractOCRProvider()
    extension = path.suffix.casefold()
    if extension == ".pdf":
        return _extract_pdf(path, settings, provider, force_ocr=force_ocr)
    return [_extract_image(path.read_bytes(), 1, settings, provider)]


def _extract_pdf(
    path: Path,
    settings: Settings,
    provider: OCRProvider,
    *,
    force_ocr: bool,
) -> list[ExtractedPage]:
    try:
        import fitz
    except ImportError:
        return _extract_pdf_portable(path, settings, provider, force_ocr=force_ocr)

    try:
        document = fitz.open(path)
    except Exception as exc:
        raise DocumentExtractionError("Invalid or unsupported PDF.") from exc
    if document.page_count > settings.max_pages:
        document.close()
        raise DocumentExtractionError(f"PDF exceeds the {settings.max_pages}-page limit.")
    pages: list[ExtractedPage] = []
    try:
        for index, page in enumerate(document):
            started = time.perf_counter()
            native_text = page.get_text("text").strip()
            use_ocr = force_ocr or len(native_text) < settings.native_text_density_threshold
            if use_ocr:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                _guard_image(image, settings)
                text, quality = provider.extract(image)
                method = "ocr"
            else:
                text, quality, method = native_text, None, "native"
            pages.append(
                ExtractedPage(
                    page_number=index + 1,
                    extraction_method=method,
                    text=text.strip(),
                    character_count=len(text.strip()),
                    ocr_quality=quality,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            )
    finally:
        document.close()
    return pages


def _extract_pdf_portable(
    path: Path,
    settings: Settings,
    provider: OCRProvider,
    *,
    force_ocr: bool,
) -> list[ExtractedPage]:
    try:
        reader = PdfReader(str(path), strict=False)
    except Exception as exc:
        raise DocumentExtractionError("Invalid or unsupported PDF.") from exc
    if len(reader.pages) > settings.max_pages:
        raise DocumentExtractionError(f"PDF exceeds the {settings.max_pages}-page limit.")
    pages: list[ExtractedPage] = []
    for index, page in enumerate(reader.pages):
        started = time.perf_counter()
        native_text = "" if force_ocr else (page.extract_text() or "").strip()
        if len(native_text) < settings.native_text_density_threshold:
            try:
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(str(path))
                image = pdf[index].render(scale=2).to_pil()
                _guard_image(image, settings)
                text, quality = provider.extract(image)
                method = "ocr"
            except DocumentExtractionError:
                raise
            except Exception as exc:
                raise DocumentExtractionError("Native text was insufficient and OCR fallback failed.") from exc
        else:
            text, quality, method = native_text, None, "native"
        pages.append(
            ExtractedPage(
                page_number=index + 1,
                extraction_method=method,
                text=text.strip(),
                character_count=len(text.strip()),
                ocr_quality=quality,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        )
    return pages


def _extract_image(content: bytes, page_number: int, settings: Settings, provider: OCRProvider) -> ExtractedPage:
    started = time.perf_counter()
    try:
        image = Image.open(io.BytesIO(content))
        image.verify()
        image = Image.open(io.BytesIO(content)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise DocumentExtractionError("Invalid or unsafe image.") from exc
    _guard_image(image, settings)
    text, quality = provider.extract(image)
    return ExtractedPage(
        page_number=page_number,
        extraction_method="ocr",
        text=text.strip(),
        character_count=len(text.strip()),
        ocr_quality=quality,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def _guard_image(image: Image.Image, settings: Settings) -> None:
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
        raise DocumentExtractionError("Image dimensions exceed the safe pixel limit.")
