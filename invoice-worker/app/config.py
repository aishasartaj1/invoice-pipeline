from __future__ import annotations
import os
from dataclasses import dataclass
from google.cloud import secretmanager

_SECRET_VERSION = "latest"

def _get_secret(client, name: str) -> str:
    response = client.access_secret_version(request={"name": f"{name}/versions/{_SECRET_VERSION}"})
    return response.payload.data.decode("utf-8").strip()

@dataclass(frozen=True)
class Settings:
    project_id: str
    gcs_bucket: str
    pubsub_subscription: str
    review_topic: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    gemini_model: str
    confidence_threshold: float

    @classmethod
    def from_secret_manager(cls) -> "Settings":
        project_id = _require_env("PROJECT_ID")
        sm = secretmanager.SecretManagerServiceClient()

        def secret(env_var: str) -> str:
            secret_id = _require_env(env_var)
            return _get_secret(sm, f"projects/{project_id}/secrets/{secret_id}")

        return cls(
            project_id=project_id,
            gcs_bucket=_require_env("GCS_BUCKET"),
            pubsub_subscription=_require_env("PUBSUB_SUBSCRIPTION"),
            review_topic=_require_env("REVIEW_TOPIC"),
            db_host=_require_env("DB_HOST"),
            db_port=int(os.environ.get("DB_PORT", "5432")),
            db_name=_require_env("DB_NAME"),
            db_user=_require_env("DB_USER"),
            db_password=secret("DB_PASSWORD_SECRET"),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            confidence_threshold=float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85")),
        )

    @property
    def db_dsn(self) -> str:
        socket_dir = "/cloudsql/invoice-pipeline-498415:us-central1:invoice-pipeline-db"
        return f"postgresql://{self.db_user}:{self.db_password}@/{self.db_name}?host={socket_dir}"

def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set")
    return value