from __future__ import annotations
import os
from dataclasses import dataclass
from google.cloud import secretmanager

def _get_secret(client, name: str) -> str:
    response = client.access_secret_version(request={"name": f"{name}/versions/latest"})
    return response.payload.data.decode("utf-8").strip()

@dataclass(frozen=True)
class Settings:
    project_id: str
    db_name: str
    db_user: str
    db_password: str

    @classmethod
    def from_secret_manager(cls) -> "Settings":
        project_id = os.environ.get("PROJECT_ID", "invoice-pipeline-498415")
        sm = secretmanager.SecretManagerServiceClient()
        secret_id = os.environ.get("DB_PASSWORD_SECRET", "db-app-password")
        db_password = _get_secret(sm, f"projects/{project_id}/secrets/{secret_id}")
        return cls(
            project_id=project_id,
            db_name=os.environ.get("DB_NAME", "invoices"),
            db_user=os.environ.get("DB_USER", "invoice_app"),
            db_password=db_password,
        )

    @property
    def db_dsn(self) -> str:
        socket_dir = "/cloudsql/invoice-pipeline-498415:us-central1:invoice-pipeline-db"
        return f"postgresql://{self.db_user}:{self.db_password}@/{self.db_name}?host={socket_dir}"
