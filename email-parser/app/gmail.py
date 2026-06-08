from __future__ import annotations
import base64
from dataclasses import dataclass
from typing import Any, Generator
import structlog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from .config import Settings

log = structlog.get_logger()
_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

@dataclass
class EmailAttachment:
    message_id: str
    filename: str
    mime_type: str
    size: int
    data: bytes

@dataclass
class EmailMessage:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    received_at: str
    attachments: list[EmailAttachment]

class GmailClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = self._build_service()

    def _build_service(self) -> Any:
        creds = Credentials(
            token=None,
            refresh_token=self._settings.gmail_refresh_token,
            client_id=self._settings.gmail_client_id,
            client_secret=self._settings.gmail_client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=_GMAIL_SCOPES,
        )
        creds.refresh(Request())
        log.info("gmail_client.authenticated")
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def list_new_message_ids(self, history_id: str) -> list[str]:
        message_ids: list[str] = []
        page_token = None
        try:
            while True:
                kwargs: dict[str, Any] = {
                    "userId": "me",
                    "startHistoryId": history_id,
                    "historyTypes": ["messageAdded"],
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                response = self._service.users().history().list(**kwargs).execute()
                for item in response.get("history", []):
                    for added in item.get("messagesAdded", []):
                        msg_id = added["message"]["id"]
                        if msg_id not in message_ids:
                            message_ids.append(msg_id)
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as exc:
            if exc.resp.status == 410:
                log.warning("gmail_client.history_expired", history_id=history_id)
                return []
            raise
        log.info("gmail_client.history_resolved", count=len(message_ids))
        return message_ids

    def fetch_message(self, message_id: str) -> EmailMessage:
        raw = self._service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        headers = {h["name"].lower(): h["value"] for h in raw["payload"].get("headers", [])}
        attachments = list(self._extract_attachments(message_id, raw["payload"]))
        return EmailMessage(
            message_id=message_id,
            thread_id=raw.get("threadId", ""),
            sender=headers.get("from", ""),
            subject=headers.get("subject", ""),
            received_at=headers.get("date", ""),
            attachments=attachments,
        )

    def _extract_attachments(self, message_id: str, part: dict) -> Generator[EmailAttachment, None, None]:
        mime_type = part.get("mimeType", "")
        filename = part.get("filename", "")
        if mime_type.startswith("multipart/"):
            for sub in part.get("parts", []):
                yield from self._extract_attachments(message_id, sub)
            return
        if not filename:
            return
        body = part.get("body", {})
        if "data" in body:
            data = base64.urlsafe_b64decode(body["data"] + "==")
        elif "attachmentId" in body:
            data = self._fetch_attachment_data(message_id, body["attachmentId"])
        else:
            return
        yield EmailAttachment(
            message_id=message_id,
            filename=filename,
            mime_type=mime_type,
            size=body.get("size", len(data)),
            data=data,
        )

    def _fetch_attachment_data(self, message_id: str, attachment_id: str) -> bytes:
        response = self._service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id
        ).execute()
        return base64.urlsafe_b64decode(response["data"] + "==")