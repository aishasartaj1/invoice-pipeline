from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.cloud import secretmanager

def get_secret(project_id, secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    return client.access_secret_version(request={"name": name}).payload.data.decode("utf-8").strip()

project_id = "invoice-pipeline-498415"
creds = Credentials(
    token=None,
    refresh_token=get_secret(project_id, "gmail-refresh-token"),
    client_id=get_secret(project_id, "gmail-client-id"),
    client_secret=get_secret(project_id, "gmail-client-secret"),
    token_uri="https://oauth2.googleapis.com/token",
    scopes=["https://www.googleapis.com/auth/gmail.readonly"]
)
creds.refresh(Request())
service = build("gmail", "v1", credentials=creds)
result = service.users().watch(userId="me", body={
    "topicName": f"projects/{project_id}/topics/gmail-notifications",
    "labelIds": ["INBOX"]
}).execute()
print("Watch set up:", result)