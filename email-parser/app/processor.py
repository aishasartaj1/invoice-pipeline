from __future__ import annotations
import json
import traceback
import uuid
from dataclasses import dataclass
import structlog
from google.cloud import pubsub_v1, storage
from .config import Settings
from .db import Database
from .gmail import EmailAttachment, EmailMessage, GmailClient

log = structlog.get_logger()

@dataclass
class AttachmentEvent:
    email_id: str
    filename: str
    gcs_path: str

    def to_json(self) -> bytes:
        return json.dumps({
            "email_id": self.email_id,
            "filename": self.filename,
            "gcs_path": self.gcs_path,
        }).encode("utf-8")

class EmailProcessor:
    def __init__(self, settings: Settings, gmail: GmailClient) -> None:
        self._settings = settings
        self._gmail = gmail
        self._gcs = storage.Client()
        self._bucket = self._gcs.bucket(settings.gcs_bucket)
        self._pubsub = pubsub_v1.PublisherClient()
        self._db = Database(settings)

    def process_history(self, history_id: str) -> int:
        # Use stored history ID so we never miss messages
        stored_id = self._db.get_last_history_id()
        start_id = stored_id if stored_id else str(max(1, int(history_id) - 100))
        log.info("processor.history_start", start_id=start_id, notification_id=history_id)

        message_ids = self._gmail.list_new_message_ids(start_id)
        if not message_ids:
            self._db.set_last_history_id(history_id)
            return 0

        processed = 0
        for message_id in message_ids:
            try:
                self._process_message(message_id)
                processed += 1
            except Exception as exc:
                log.error("processor.message_failed",
                          message_id=message_id,
                          error=str(exc),
                          traceback=traceback.format_exc())

        self._db.set_last_history_id(history_id)
        return processed

    def _process_message(self, message_id: str) -> None:
        log.info("processor.message_start", message_id=message_id)
        message = self._gmail.fetch_message(message_id)
        if not message.attachments:
            log.info("processor.no_attachments", message_id=message_id)
            return
        uploaded = []
        for attachment in message.attachments:
            gcs_path = self._upload_attachment(message.message_id, attachment)
            uploaded.append((attachment, gcs_path))
        email_id = self._upsert_raw_email(message)
        futures = []
        for attachment, gcs_path in uploaded:
            event = AttachmentEvent(email_id=email_id, filename=attachment.filename, gcs_path=gcs_path)
            future = self._pubsub.publish(self._settings.pubsub_topic, data=event.to_json(), email_id=email_id)
            futures.append((attachment.filename, future))
        for filename, future in futures:
            try:
                future.result(timeout=10)
                log.info("processor.pubsub_published", message_id=message_id, filename=filename)
            except Exception as exc:
                log.error("processor.pubsub_failed",
                          message_id=message_id,
                          filename=filename,
                          error=str(exc),
                          traceback=traceback.format_exc())
                raise
        log.info("processor.message_done", message_id=message_id, attachments=len(uploaded))

    def _upload_attachment(self, message_id: str, attachment: EmailAttachment) -> str:
        object_name = f"emails/{message_id}/{attachment.filename}"
        blob = self._bucket.blob(object_name)
        blob.upload_from_string(attachment.data, content_type=attachment.mime_type)
        gcs_path = f"gs://{self._settings.gcs_bucket}/{object_name}"
        log.info("processor.gcs_uploaded", message_id=message_id,
                 filename=attachment.filename, gcs_path=gcs_path)
        return gcs_path

    def _upsert_raw_email(self, message: EmailMessage) -> str:
        email_id = str(uuid.uuid4())
        gcs_folder = f"gs://{self._settings.gcs_bucket}/emails/{message.message_id}/"
        result_id = self._db.upsert_raw_email(
            email_id=email_id,
            gmail_message_id=message.message_id,
            thread_id=message.thread_id,
            sender=message.sender,
            subject=message.subject,
            received_at=message.received_at,
            gcs_folder=gcs_folder,
        )
        log.info("processor.raw_email_upserted",
                 gmail_message_id=message.message_id, email_id=result_id)
        return result_id