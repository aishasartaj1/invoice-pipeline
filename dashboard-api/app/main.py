from __future__ import annotations
import logging
import sys
from flask import Flask, jsonify
from flask_cors import CORS
import structlog
from .config import Settings
from .db import Database

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()
app = Flask(__name__)
CORS(app)

_settings: Settings | None = None
_db: Database | None = None


def get_db() -> Database:
    global _settings, _db
    if _db is None:
        _settings = Settings.from_secret_manager()
        _db = Database(_settings)
    return _db


@app.get("/healthz")
def healthz():
    return {"status": "ok"}, 200


@app.get("/api/stats")
def stats():
    db = get_db()
    return jsonify(db.get_stats())


@app.get("/api/invoices")
def invoices():
    db = get_db()
    return jsonify(db.get_invoices())