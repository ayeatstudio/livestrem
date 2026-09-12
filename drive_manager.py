from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


# ============================================================
# DRIVE MANAGER
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly"
]


@dataclass
class DriveFile:
    file_id: str
    name: str
    mime_type: str
    size: Optional[int] = None


class DriveManager:
    """
    Google Drive read-only manager.

    Responsibilities:
    - Connect to Google Drive using OAuth credentials.
    - Search folders.
    - List files.
    - Find video files.
    - Download files to local cache.

    Safety:
    - Read-only Drive scope.
    - Does not upload files.
    - Does not delete files.
    - Does not modify Drive files.
    - Does not start FFmpeg.
    - Does not start streaming.
    """

    VIDEO_MIME_TYPES = {
        "video/mp4",
        "video/x-matroska",
        "video/webm",
        "video/quicktime",
        "video/x-msvideo",
        "video/mpeg",
    }

    def __init__(
        self,
        credentials: Credentials,
    ):
        self.credentials = credentials

        self.service = build(
            "drive",
            "v3",
            credentials=self.credentials,
            cache_discovery=False,
        )

    # ---------------------------------------------------------
    # FILE LIST
    # ---------------------------------------------------------

    def list_files(
        self,
        query: Optional[str] = None,
        page_size: int = 100,
    ) -> list[DriveFile]:

        base_query = (
            "trashed = false"
        )

        if query:
            base_query += (
                f" and ({query})"
            )

        response = (
            self.service.files()
            .list(
                q=base_query,
                pageSize=page_size,
                fields=(
                    "files("
                    "id,"
                    "name,"
                    "mimeType,"
                    "size"
                    ")"
                ),
                orderBy="name",
            )
            .execute()
        )

        files = []

        for item in response.get(
            "files",
            [],
        ):

            size = item.get("size")

            files.append(
                DriveFile(
                    file_id=item["id"],
                    name=item["name"],
                    mime_type=item["mimeType"],
                    size=(
                        int(size)
                        if size is not None
                        else None
                    ),
                )
            )

        return files

    # ---------------------------------------------------------
    # FOLDER
    # ---------------------------------------------------------

    def find_folder(
        self,
        folder_name: str,
        parent_id: Optional[str] = None,
    ) -> Optional[DriveFile]:

        escaped_name = (
            folder_name
            .replace("\\", "\\\\")
            .replace("'", "\\'")
        )

        query = (
            "mimeType = "
            "'application/vnd.google-apps.folder'"
            f" and name = '{escaped_name}'"
        )

        if parent_id:
            query += (
                f" and '{parent_id}' in parents"
            )

        files = self.list_files(
            query=query,
            page_size=100,
        )

        if not files:
            return None

        return files[0]

    # ---------------------------------------------------------
    # FOLDER FILES
    # ---------------------------------------------------------

    def list_folder_files(
        self,
        folder_id: str,
    ) -> list[DriveFile]:

        query = (
            f"'{folder_id}' in parents"
        )

        return self.list_files(
            query=query,
            page_size=1000,
        )

    # ---------------------------------------------------------
    # VIDEO FILES
    # ---------------------------------------------------------

    def list_videos(
        self,
        folder_id: str,
    ) -> list[DriveFile]:

        query = (
            f"'{folder_id}' in parents"
            " and trashed = false"
        )

        files = self.list_files(
            query=query,
            page_size=1000,
        )

        videos = []

        for file in files:

            if (
                file.mime_type
                in self.VIDEO_MIME_TYPES
            ):
                videos.append(file)
                continue

            suffix = (
                Path(file.name)
                .suffix
                .lower()
            )

            if suffix in {
                ".mp4",
                ".mkv",
                ".webm",
                ".mov",
                ".avi",
                ".mpeg",
                ".mpg",
            }:
                videos.append(file)

        return videos

    # ---------------------------------------------------------
    # FILE
    # ---------------------------------------------------------

    def get_file(
        self,
        file_id: str,
    ) -> DriveFile:

        response = (
            self.service.files()
            .get(
                fileId=file_id,
                fields=(
                    "id,"
                    "name,"
                    "mimeType,"
                    "size"
                ),
            )
            .execute()
        )

        size = response.get("size")

        return DriveFile(
            file_id=response["id"],
            name=response["name"],
            mime_type=response["mimeType"],
            size=(
                int(size)
                if size is not None
                else None
            ),
        )

    # ---------------------------------------------------------
    # DOWNLOAD
    # ---------------------------------------------------------

    def download_file(
        self,
        file_id: str,
        destination: str | Path,
    ) -> Path:

        destination = Path(
            destination
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        request = (
            self.service.files()
            .get_media(
                fileId=file_id
            )
        )

        with destination.open(
            "wb"
        ) as file_handle:

            downloader = (
                MediaIoBaseDownload(
                    file_handle,
                    request,
                )
            )

            done = False

            while not done:

                _status, done = (
                    downloader.next_chunk()
                )

        return destination

    # ---------------------------------------------------------
    # DOWNLOAD IF MISSING
    # ---------------------------------------------------------

    def ensure_cached(
        self,
        drive_file: DriveFile,
        cache_directory: str | Path,
    ) -> Path:

        cache_directory = Path(
            cache_directory
        )

        cache_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = (
            cache_directory
            / drive_file.name
        )

        if (
            destination.exists()
            and destination.is_file()
            and destination.stat().st_size > 0
        ):
            return destination

        return self.download_file(
            drive_file.file_id,
            destination,
        )


# ============================================================
# TEST
# ============================================================

def main():
    print("=" * 60)
    print("DRIVE MANAGER TEST")
    print("=" * 60)

    print()
    print(
        "DriveManager requires authenticated "
        "Google Drive credentials."
    )

    print()
    print("Safety checks:")
    print(
        "- Google Drive scope: READ ONLY"
    )
    print(
        "- Upload: NOT SUPPORTED"
    )
    print(
        "- Delete: NOT SUPPORTED"
    )
    print(
        "- Modify: NOT SUPPORTED"
    )
    print(
        "- FFmpeg: NOT STARTED"
    )
    print(
        "- RTMP streaming: NOT STARTED"
    )

    print()
    print(
        "Result: DRIVE MANAGER READY"
    )

    print()
    print("=" * 60)
    print("DRIVE MANAGER TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()