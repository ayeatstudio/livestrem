from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import os

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

CREDENTIALS_FILE = (
    "client_secret_1055589718706-2b9ttbadu5d9hqeuujf8iu2uhinvnvb9"
    ".apps.googleusercontent.com.json"
)

TOKEN_FILE = "token.json"


def authenticate():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES
        )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            SCOPES
        )

        creds = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent"
        )

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return creds


def main():
    print("=" * 60)
    print("Cloud Live Streaming - Google Drive Test")
    print("=" * 60)

    print("\nConnecting to Google Drive...")

    creds = authenticate()

    service = build(
        "drive",
        "v3",
        credentials=creds
    )

    print("Google Drive authentication: OK")

    print("\nFiles in Google Drive:")
    print("-" * 60)

    response = service.files().list(
        pageSize=20,
        fields="files(id,name,mimeType,size,modifiedTime)"
    ).execute()

    files = response.get("files", [])

    if not files:
        print("No files found.")
    else:
        for index, file in enumerate(files, 1):
            print(f"{index}. {file['name']}")
            print(f"   ID: {file['id']}")
            print(f"   Type: {file['mimeType']}")
            print(f"   Size: {file.get('size', 'N/A')}")
            print()

    print("=" * 60)
    print("GOOGLE DRIVE TEST SUCCESS")
    print("=" * 60)


if __name__ == "__main__":
    main()