from __future__ import annotations
import os
from dataclasses import dataclass, field
from google.cloud import secretmanager

_SECRET_VERSION = "latest"

def _get_secret(client, name: str) -> str:
    response = client.access_secret_version(request={"name": f"{name}/versions/{_SECRET_VERSION}"})
    return response.payload.data.decode("utf-8").strip()

@dataclass(frozen=True)
class Settings:
    project_id: str
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str
    gmail_user: str
    gcs_bucket: str
    pubsub_topic: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    @classmethod
    def from_secret_manager(cls) -> "Settings":
        project_id = _require_env("PROJECT_ID")
        sm = secretmanager.SecretManagerServiceClient()

        def secret(env_var: str) -> str:
            secret_id = _require_env(env_var)
            return _get_secret(sm, f"projects/{project_id}/secrets/{secret_id}")

        return cls(
            project_id=project_id,
            gmail_client_id=secret("GMAIL_CLIENT_ID_SECRET"),
            gmail_client_secret=secret("GMAIL_CLIENT_SECRET_SECRET"),
            gmail_refresh_token=secret("GMAIL_REFRESH_TOKEN_SECRET"),
            gmail_user=_require_env("GMAIL_USER"),
            gcs_bucket=_require_env("GCS_BUCKET"),
            pubsub_topic=_require_env("PUBSUB_TOPIC"),
            db_host=_require_env("DB_HOST"),
            db_port=int(os.environ.get("DB_PORT", "5432")),
            db_name=_require_env("DB_NAME"),
            db_user=_require_env("DB_USER"),
            db_password=secret("DB_PASSWORD_SECRET"),
        )

    @property
    def db_dsn(self) -> str:
        socket_dir = "/cloudsql/invoice-pipeline-498415:us-central1:invoice-pipeline-db"
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@/{self.db_name}?host={socket_dir}"
        )

def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set")
    return value