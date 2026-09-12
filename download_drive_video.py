import os
import io

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.http import MediaIoBaseDownload


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

CREDENTIALS_FILE = (
    "client_secret_1055589718706-2b9ttbadu5d9hqeuujf8iu2uhinvnvb9"
    ".apps.googleusercontent.com.json"
)

TOKEN_FILE = "token.json"

FILE_ID = "15HZs0uIJN7PMQ9rcnsVv0vMdaq1ZSv7L"

OUTPUT_DIR = "cache"
OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "Episode 1 –The Boy Who Loved the Morning Sky.mp4"
)


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


def download_video():
    print("=" * 60)
    print("Cloud Live Streaming - Drive Video Download Test")
    print("=" * 60)

    print("\nAuthenticating Google Drive...")

    creds = authenticate()

    service = build(
        "drive",
        "v3",
        credentials=creds
    )

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Authentication: OK")
    print("Getting video information...")

    file_info = service.files().get(
        fileId=FILE_ID,
        fields="id,name,size,mimeType"
    ).execute()

    print(f"\nName: {file_info['name']}")
    print(f"Type: {file_info['mimeType']}")
    print(f"Size: {file_info.get('size', 'Unknown')} bytes")

    print("\nStarting download...")

    request = service.files().get_media(
        fileId=FILE_ID
    )

    with io.FileIO(OUTPUT_FILE, "wb") as fh:
        downloader = MediaIoBaseDownload(
            fh,
            request,
            chunksize=10 * 1024 * 1024
        )

        done = False

        while not done:
            status, done = downloader.next_chunk()

            if status:
                print(
                    f"Downloaded: "
                    f"{status.progress() * 100:.1f}%"
                )

    print("\n" + "=" * 60)
    print("DOWNLOAD SUCCESS")
    print("=" * 60)
    print(f"Saved to:")
    print(os.path.abspath(OUTPUT_FILE))


if __name__ == "__main__":
    download_video()