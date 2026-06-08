from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Any
import structlog
import vertexai
from vertexai.generative_models import GenerativeModel, Part

log = structlog.get_logger()

@dataclass
class ClassificationResult:
    is_invoice: bool
    confidence: float
    reason: str

@dataclass
class ExtractionResult:
    inv_number: str | None
    inv_date: str | None
    grand_total: float | None
    currency: str
    from_vendor: str | None
    confidence: float
    null_field_count: int

class GeminiClient:
    def __init__(self, project_id: str, model: str = "gemini-1.5-flash-001") -> None:
        vertexai.init(project=project_id, location="us-central1")
        self._model = GenerativeModel(model)
        log.info("gemini_client.initialized", model=model)

    def classify(self, text: str, filename: str) -> ClassificationResult:
        """
        Step 1 — Pre-filter: is this attachment an invoice?
        Returns confidence 0.0-1.0 and a boolean decision.
        """
        prompt = f"""You are a document classifier. Determine if the following document is an invoice.

An invoice must have: a vendor/supplier, a total amount due, and a date or invoice number.

Filename: {filename}
Document text:
{text[:3000]}

Respond ONLY with valid JSON, no markdown, no explanation:
{{
  "is_invoice": true or false,
  "confidence": 0.0 to 1.0,
  "reason": "one sentence explanation"
}}"""

        try:
            response = self._model.generate_content(prompt)
            raw = response.text.strip()
            raw = re.sub(r"^```json\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            result = ClassificationResult(
                is_invoice=bool(data.get("is_invoice", False)),
                confidence=float(data.get("confidence", 0.0)),
                reason=str(data.get("reason", "")),
            )
            log.info("gemini.classify_done", filename=filename, is_invoice=result.is_invoice, confidence=result.confidence)
            return result
        except Exception as exc:
            log.exception("gemini.classify_failed", filename=filename, error=str(exc))
            return ClassificationResult(is_invoice=False, confidence=0.0, reason=f"Error: {exc}")

    def extract(self, text: str, filename: str) -> ExtractionResult:
        """
        Step 2 — Extract structured fields from confirmed invoice.
        """
        prompt = f"""You are an invoice data extraction expert. Extract the following fields from this invoice.

Filename: {filename}
Document text:
{text[:4000]}

Respond ONLY with valid JSON, no markdown, no explanation:
{{
  "inv_number": "invoice number or null",
  "inv_date": "date in YYYY-MM-DD format or null",
  "grand_total": numeric total amount or null,
  "currency": "3-letter currency code, default USD",
  "from_vendor": "vendor/supplier name or null",
  "confidence": 0.0 to 1.0
}}"""

        try:
            response = self._model.generate_content(prompt)
            raw = response.text.strip()
            raw = re.sub(r"^```json\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)

            null_field_count = sum(1 for f in ["inv_number", "inv_date", "grand_total", "from_vendor"] if data.get(f) is None)

            result = ExtractionResult(
                inv_number=data.get("inv_number"),
                inv_date=data.get("inv_date"),
                grand_total=float(data["grand_total"]) if data.get("grand_total") is not None else None,
                currency=data.get("currency", "USD") or "USD",
                from_vendor=data.get("from_vendor"),
                confidence=float(data.get("confidence", 0.0)),
                null_field_count=null_field_count,
            )
            log.info("gemini.extract_done", filename=filename, confidence=result.confidence, null_fields=null_field_count)
            return result
        except Exception as exc:
            log.exception("gemini.extract_failed", filename=filename, error=str(exc))
            return ExtractionResult(
                inv_number=None, inv_date=None, grand_total=None,
                currency="USD", from_vendor=None, confidence=0.0, null_field_count=4
            )