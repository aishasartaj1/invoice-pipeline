from __future__ import annotations
import base64
import json
import logging
import sys
from typing import Any
import structlog
from flask import Flask, Response, request
from .config import Settings
from .processor import AttachmentProcessor

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
        _settings = Settings.from_secret_manager()
    return _settings

@app.before_request
def _bind_request_context() -> None:
    trace = request.headers.get("X-Cloud-Trace-Context", "").split("/")[0]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(trace=trace or "local")

@app.get("/healthz")
def healthz() -> tuple[dict, int]:
    return {"status": "ok"}, 200

@app.post("/webhook/pubsub")
def pubsub_webhook() -> Response:
    """
    Receives Pub/Sub push notifications from attachment-events-sub.
    Each message contains: { email_id, filename, gcs_path }
    """
    envelope: dict[str, Any] = request.get_json(silent=True) or {}

    if "message" not in envelope or "data" not in envelope.get("message", {}):
        log.warning("pubsub_webhook.invalid_envelope")
        return Response("Bad Request", status=400)

    try:
        raw = base64.b64decode(envelope["message"]["data"]).decode("utf-8")
        message_data: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        log.error("pubsub_webhook.decode_failed", error=str(exc))
        return Response("Bad Request", status=400)

    required = {"email_id", "filename", "gcs_path"}
    if not required.issubset(message_data.keys()):
        log.warning("pubsub_webhook.missing_fields", keys=list(message_data.keys()))
        return Response("Bad Request: missing fields", status=400)

    log.info("pubsub_webhook.received",
             email_id=message_data["email_id"],
             filename=message_data["filename"])

    try:
        processor = AttachmentProcessor(get_settings())
        processor.process(message_data)
    except Exception as exc:
        log.exception("pubsub_webhook.processing_failed", error=str(exc))
        return Response("Internal Server Error", status=500)

    return Response(status=204)