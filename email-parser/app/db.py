from __future__ import annotations
import contextlib
import traceback
from typing import Generator
import psycopg2
import psycopg2.pool
import structlog
from .config import Settings

log = structlog.get_logger()
_POOL_MIN = 1
_POOL_MAX = 10

class Database:
    def __init__(self, settings: Settings) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=_POOL_MIN,
            maxconn=_POOL_MAX,
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

    def get_last_history_id(self) -> str | None:
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT value FROM gmail_state WHERE key = 'last_history_id'")
                    row = cur.fetchone()
            return row[0] if row else None
        except Exception:
            log.error("database.get_history_id_failed", traceback=traceback.format_exc())
            return None

    def set_last_history_id(self, history_id: str) -> None:
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO gmail_state (key, value)
                        VALUES ('last_history_id', %s)
                        ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value, updated_at = NOW()
                    """, (history_id,))
        except Exception:
            log.error("database.set_history_id_failed", traceback=traceback.format_exc())

    def upsert_raw_email(self, *, email_id, gmail_message_id, thread_id,
                         sender, subject, received_at, gcs_folder) -> str:
        sql_insert = """
            INSERT INTO raw_emails (id, gmail_message_id, thread_id, sender,
                subject, received_at, gcs_folder)
            VALUES (%s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (gmail_message_id) DO NOTHING
        """
        sql_select = "SELECT id::text FROM raw_emails WHERE gmail_message_id = %s"
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql_insert, (email_id, gmail_message_id, thread_id,
                                             sender, subject, gcs_folder))
                    cur.execute(sql_select, (gmail_message_id,))
                    row = cur.fetchone()
        except Exception:
            log.error("database.upsert_failed",
                      gmail_message_id=gmail_message_id,
                      traceback=traceback.format_exc())
            raise
        if row is None:
            raise RuntimeError(f"raw_emails row not found for {gmail_message_id}")
        return row[0]

    def close(self) -> None:
        self._pool.closeall()