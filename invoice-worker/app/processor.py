from __future__ import annotations
import io
import json
import structlog
from google.cloud import pubsub_v1, storage
from pypdf import PdfReader
from .config import Settings
from .db import Database
from .gemini import GeminiClient

log = structlog.get_logger()

class AttachmentProcessor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._gcs = storage.Client()
        self._pubsub = pubsub_v1.PublisherClient()
        self._db = Database(settings)
        self._gemini = GeminiClient(settings.project_id, settings.gemini_model)

    def process(self, message_data: dict) -> None:
        """
        Full pipeline for one attachment:
        1. Download from GCS
        2. Extract text
        3. Classify (is it an invoice?)
        4. Extract fields if confirmed invoice
        5. Route based on confidence
        6. Write to DB + metrics
        """
        email_id = message_data["email_id"]
        filename = message_data["filename"]
        gcs_path = message_data["gcs_path"]

        log.info("processor.start", email_id=email_id, filename=filename, gcs_path=gcs_path)
        self._db.update_job_status(gcs_path=gcs_path, status="processing")

        # 1. Download attachment from GCS
        try:
            data = self._download_from_gcs(gcs_path)
        except Exception as exc:
            log.exception("processor.gcs_download_failed", gcs_path=gcs_path)
            self._db.update_job_status(gcs_path=gcs_path, status="failed")
            self._db.insert_metric(gcs_path=gcs_path, outcome="gcs_error",
                                   confidence=0.0, null_field_count=0, pre_filter_reason=str(exc))
            raise

        # 2. Extract text
        text = self._extract_text(data, filename)
        if not text.strip():
            log.warning("processor.no_text", filename=filename)
            self._db.update_job_status(gcs_path=gcs_path, status="skipped")
            self._db.insert_metric(gcs_path=gcs_path, outcome="no_text",
                                   confidence=0.0, null_field_count=0, pre_filter_reason="No extractable text")
            return

        # 3. Classify
        classification = self._gemini.classify(text, filename)
        if not classification.is_invoice or classification.confidence < 0.5:
            log.info("processor.not_invoice", filename=filename, reason=classification.reason)
            self._db.update_job_status(gcs_path=gcs_path, status="skipped")
            self._db.insert_metric(gcs_path=gcs_path, outcome="not_invoice",
                                   confidence=classification.confidence,
                                   null_field_count=0, pre_filter_reason=classification.reason)
            return

        # 4. Extract fields
        extraction = self._gemini.extract(text, filename)

        # 5. Route based on confidence
        if extraction.confidence >= self._settings.confidence_threshold:
            status = "processed"
            outcome = "extracted"
        else:
            status = "review"
            outcome = "low_confidence"
            self._publish_review_event(email_id=email_id, filename=filename,
                                       gcs_path=gcs_path, confidence=extraction.confidence)

        # 6. Write to DB
        self._db.insert_invoice(
            email_id=email_id,
            inv_number=extraction.inv_number,
            inv_date=extraction.inv_date,
            grand_total=extraction.grand_total,
            currency=extraction.currency,
            from_vendor=extraction.from_vendor,
            gcs_path=gcs_path,
            confidence=extraction.confidence,
            status=status,
        )
        self._db.insert_metric(
            gcs_path=gcs_path,
            outcome=outcome,
            confidence=extraction.confidence,
            null_field_count=extraction.null_field_count,
            pre_filter_reason=None,
        )
        self._db.update_job_status(gcs_path=gcs_path, status=status)

        log.info("processor.done", email_id=email_id, filename=filename,
                 status=status, confidence=extraction.confidence)

    def _download_from_gcs(self, gcs_path: str) -> bytes:
        # gcs_path format: gs://bucket/emails/msg_id/filename
        path = gcs_path.replace(f"gs://{self._settings.gcs_bucket}/", "")
        blob = self._gcs.bucket(self._settings.gcs_bucket).blob(path)
        return blob.download_as_bytes()

    def _extract_text(self, data: bytes, filename: str) -> str:
        fname = filename.lower()
        try:
            if fname.endswith(".pdf"):
                reader = PdfReader(io.BytesIO(data))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            elif fname.endswith((".txt", ".csv")):
                return data.decode("utf-8", errors="ignore")
            else:
                # Try UTF-8 decode for other text-like files
                return data.decode("utf-8", errors="ignore")
        except Exception as exc:
            log.warning("processor.text_extraction_failed", filename=filename, error=str(exc))
            return ""

    def _publish_review_event(self, *, email_id: str, filename: str,
                               gcs_path: str, confidence: float) -> None:
        payload = json.dumps({
            "email_id": email_id,
            "filename": filename,
            "gcs_path": gcs_path,
            "confidence": confidence,
        }).encode("utf-8")
        self._pubsub.publish(self._settings.review_topic, data=payload).result(timeout=10)
        log.info("processor.review_published", email_id=email_id, filename=filename)