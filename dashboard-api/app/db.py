from __future__ import annotations
import contextlib
from typing import Generator
import psycopg2
import psycopg2.pool
import psycopg2.extras
import structlog
from .config import Settings

log = structlog.get_logger()

class Database:
    def __init__(self, settings: Settings) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=5,
            dsn=settings.db_dsn,
            connect_timeout=10,
        )
        log.info("database.pool_created")

    @contextlib.contextmanager
    def _conn(self) -> Generator:
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def get_stats(self) -> dict:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_invoices,
                        COUNT(*) FILTER (WHERE status = 'processed') AS processed,
                        COUNT(*) FILTER (WHERE status = 'review') AS needs_review,
                        COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                        COALESCE(SUM(grand_total), 0) AS total_value,
                        COALESCE(ROUND(AVG(confidence)::numeric, 2), 0) AS avg_confidence,
                        COALESCE(SUM(grand_total) FILTER (WHERE status = 'processed'), 0) AS processed_value
                    FROM invoices
                """)
                row = cur.fetchone()
                cur.execute("""
                    SELECT DATE(created_at) as date, COUNT(*) as count, COALESCE(SUM(grand_total),0) as value
                    FROM invoices
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                    LIMIT 7
                """)
                daily = cur.fetchall()
        return {
            "total_invoices": int(row["total_invoices"]),
            "processed": int(row["processed"]),
            "needs_review": int(row["needs_review"]),
            "failed": int(row["failed"]),
            "total_value": float(row["total_value"]),
            "avg_confidence": float(row["avg_confidence"]),
            "processed_value": float(row["processed_value"]),
            "daily": [{"date": str(d["date"]), "count": int(d["count"]), "value": float(d["value"])} for d in daily],
        }

    def get_invoices(self) -> list:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        i.id, i.inv_number, i.inv_date, i.grand_total, i.currency,
                        i.from_vendor, i.status, i.confidence, i.gcs_path,
                        i.created_at, r.sender, r.subject
                    FROM invoices i
                    LEFT JOIN raw_emails r ON r.id = i.email_id
                    ORDER BY i.created_at DESC
                    LIMIT 100
                """)
                rows = cur.fetchall()
        return [
            {
                "id": str(r["id"]),
                "inv_number": r["inv_number"],
                "inv_date": str(r["inv_date"]) if r["inv_date"] else None,
                "grand_total": float(r["grand_total"]) if r["grand_total"] else None,
                "currency": r["currency"],
                "from_vendor": r["from_vendor"],
                "status": r["status"],
                "confidence": float(r["confidence"]) if r["confidence"] else None,
                "gcs_path": r["gcs_path"],
                "created_at": str(r["created_at"]),
                "sender": r["sender"],
                "subject": r["subject"],
            }
            for r in rows
        ]
