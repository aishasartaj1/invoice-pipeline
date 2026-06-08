from __future__ import annotations
import base64
import json
import logging
import os
import sys
import traceback
from typing import Any

import structlog
from flask import Flask, Response, request
from .config import Settings
from .gmail import GmailClient
from .processor import EmailProcessor

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()
app = Flask(__name__)

_settings: Settings | None = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        log.info("settings.loading")
        try:
            _settings = Settings.from_secret_manager()
            log.info("settings.loaded_ok")
        except Exception:
            log.error("settings.load_failed", traceback=traceback.format_exc())
            raise
    return _settings

@app.before_request
def _bind_request_context() -> None:
    trace = request.headers.get("X-Cloud-Trace-Context", "").split("/")[0]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(trace=trace or "local")

@app.get("/healthz")
def healthz() -> tuple[dict, int]:
    return {"status": "ok"}, 200

@app.get("/debug/settings")
def debug_settings() -> Response:
    results = {}
    project_id = os.environ.get("PROJECT_ID", "MISSING")
    results["PROJECT_ID"] = project_id
    from google.cloud import secretmanager
    sm = secretmanager.SecretManagerServiceClient()
    for var in ["GMAIL_CLIENT_ID_SECRET","GMAIL_CLIENT_SECRET_SECRET","GMAIL_REFRESH_TOKEN_SECRET","DB_PASSWORD_SECRET"]:
        secret_id = os.environ.get(var, "MISSING_ENV")
        if secret_id == "MISSING_ENV":
            results[var] = "ENV VAR NOT SET"
            continue
        try:
            name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
            resp = sm.access_secret_version(request={"name": name})
            val = resp.payload.data.decode("utf-8").strip()
            results[var] = f"OK (len={len(val)})"
        except Exception:
            results[var] = f"FAILED: {traceback.format_exc()}"
    return Response(json.dumps(results, indent=2), status=200, mimetype="application/json")

@app.post("/webhook/gmail")
def gmail_webhook() -> Response:
    envelope: dict[str, Any] = request.get_json(silent=True) or {}
    if "message" not in envelope or "data" not in envelope.get("message", {}):
        log.warning("gmail_webhook.invalid_envelope")
        return Response("Bad Request: missing message.data", status=400)
    try:
        raw = base64.b64decode(envelope["message"]["data"]).decode("utf-8")
        notification: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        log.error("gmail_webhook.decode_failed", error=str(exc))
        return Response("Bad Request: cannot decode message data", status=400)
    history_id = notification.get("historyId")
    email_address = notification.get("emailAddress")
    if not history_id or not email_address:
        log.warning("gmail_webhook.missing_fields")
        return Response("Bad Request: missing historyId or emailAddress", status=400)
    log.info("gmail_webhook.received", history_id=history_id, email_address=email_address)
    try:
        settings = get_settings()
        gmail = GmailClient(settings)
        processor = EmailProcessor(settings, gmail)
        processed = processor.process_history(history_id=history_id)
        log.info("gmail_webhook.done", messages_processed=processed)
    except Exception as exc:
        log.error("gmail_webhook.processing_failed", error=str(exc), traceback=traceback.format_exc())
        return Response("Internal Server Error", status=500)
    return Response(status=204)

@app.post("/admin/renew-watch")
def renew_watch() -> Response:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    try:
        settings = get_settings()
        creds = Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        creds.refresh(Request())
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        result = service.users().watch(userId="me", body={
            "topicName": f"projects/{settings.project_id}/topics/gmail-notifications",
        }).execute()
        log.info("gmail_watch.renewed", result=result)
        return Response(json.dumps(result), status=200, mimetype="application/json")
    except Exception:
        log.error("gmail_watch.renew_failed", traceback=traceback.format_exc())
        return Response(traceback.format_exc(), status=500)