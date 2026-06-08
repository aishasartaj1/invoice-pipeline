from __future__ import annotations
import contextlib
from typing import Generator
import psycopg2
import psycopg2.pool
import structlog
from .config import Settings

log = structlog.get_logger()

class Database:
    def __init__(self, settings: Settings) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=5,
            dsn=settings.db_dsn,
            connect_timeout=10,
            options="-c statement_timeout=30000",
        )
        log.info("database.pool_created")

    @contextlib.contextmanager
    def _conn(self) -> Generator:
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def insert_invoice(self, *, email_id: str, inv_number: str | None,
                       inv_date: str | None, grand_total: float | None,
                       currency: str, from_vendor: str | None,
                       gcs_path: str, confidence: float, status: str) -> str:
        sql = """
            INSERT INTO invoices (
                email_id, inv_number, inv_date, grand_total,
                currency, from_vendor, gcs_path, confidence, status
            )
            VALUES (
                %s::uuid, %s,
                %s::date,
                %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (email_id, inv_number) DO UPDATE SET
                confidence = EXCLUDED.confidence,
                status = EXCLUDED.status,
                grand_total = EXCLUDED.grand_total
            RETURNING id::text
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    email_id, inv_number, inv_date, grand_total,
                    currency, from_vendor, gcs_path, confidence, status
                ))
                row = cur.fetchone()
        return row[0]

    def insert_metric(self, *, gcs_path: str, outcome: str,
                      confidence: float, null_field_count: int,
                      pre_filter_reason: str | None) -> None:
        sql = """
            INSERT INTO pipeline_metrics
                (gcs_path, outcome, confidence, null_field_count, pre_filter_reason)
            VALUES (%s, %s, %s, %s, %s)
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (gcs_path, outcome, confidence,
                                  null_field_count, pre_filter_reason))

    def update_job_status(self, *, gcs_path: str, status: str) -> None:
        sql = """
            INSERT INTO processing_jobs (gcs_path, status)
            VALUES (%s, %s)
            ON CONFLICT (gcs_path) DO UPDATE SET status = EXCLUDED.status, updated_at = now()
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (gcs_path, status))

    def close(self) -> None:
        self._pool.closeall()