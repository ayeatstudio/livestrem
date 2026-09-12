
# ============================================================
# Google Drive Provider
# Version : 3.1.0 FINAL
# Project : Streaming Engine
# ============================================================

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

CREDENTIALS_FILE = PROJECT_ROOT / "client_secret_1055589718706-2b9ttbadu5d9hqeuujf8iu2uhinvnvb9.apps.googleusercontent.com.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"


# ============================================================
# GOOGLE DRIVE CONFIG
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly"
]

DRIVE_API = "https://www.googleapis.com/drive/v3"

DOWNLOAD_URL = (
    "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
)

DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024

DEFAULT_TIMEOUT = 120

MAX_RETRIES = 4


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class DriveVideo:
    file_id: str
    name: str
    mime_type: str = "video/mp4"
    size: int = 0
    modified_time: str = ""
    created_time: str = ""
    md5_checksum: str = ""
    web_view_link: str = ""
    parents: Optional[List[str]] = None
    folder_name: str = ""

    def __post_init__(self):
        if self.parents is None:
            self.parents = []

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# PROVIDER
# ============================================================

class GoogleDriveProvider:
    """
    Google Drive video provider.

    Responsibilities:
        - Authentication
        - Folder discovery
        - Video discovery
        - Metadata retrieval
        - Authenticated HTTP Range downloading
        - Local file verification
    """

    def __init__(
        self,
        credentials_file: Optional[str] = None,
        token_file: Optional[str] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        download_timeout: int = DEFAULT_TIMEOUT,
    ):
        self.credentials_file = Path(
            credentials_file or CREDENTIALS_FILE
        )

        self.token_file = Path(
            token_file or TOKEN_FILE
        )

        self.chunk_size = int(chunk_size)
        self.download_timeout = int(download_timeout)

        self.logger = logging.getLogger("GoogleDriveProvider")

        self._service = None
        self._credentials: Optional[Credentials] = None

        self._lock = threading.RLock()

        self._authenticate()

    # ========================================================
    # AUTHENTICATION
    # ========================================================

    def _authenticate(self) -> None:
        with self._lock:

            credentials = None

            if self.token_file.exists():
                try:
                    credentials = Credentials.from_authorized_user_file(
                        str(self.token_file),
                        SCOPES,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Could not load token.json: %s",
                        exc,
                    )

            if credentials and credentials.expired and credentials.refresh_token:
                try:
                    credentials.refresh(Request())

                    self.token_file.write_text(
                        credentials.to_json(),
                        encoding="utf-8",
                    )

                except Exception as exc:
                    self.logger.warning(
                        "Token refresh failed: %s",
                        exc,
                    )
                    credentials = None

            if not credentials or not credentials.valid:

                if not self.credentials_file.exists():
                    raise FileNotFoundError(
                        f"Google credentials file not found: "
                        f"{self.credentials_file}"
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file),
                    SCOPES,
                )

                credentials = flow.run_local_server(
                    port=0
                )

                self.token_file.write_text(
                    credentials.to_json(),
                    encoding="utf-8",
                )

            self._credentials = credentials

            self._service = build(
                "drive",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )

    # ========================================================
    # CREDENTIAL REFRESH
    # ========================================================

    def _refresh_credentials_if_needed(self) -> None:

        if self._credentials is None:
            raise RuntimeError(
                "Google credentials are not initialized."
            )

        if (
            self._credentials.expired
            and self._credentials.refresh_token
        ):
            with self._lock:

                if (
                    self._credentials.expired
                    and self._credentials.refresh_token
                ):
                    self._credentials.refresh(Request())

                    try:
                        self.token_file.write_text(
                            self._credentials.to_json(),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass

    # ========================================================
    # SERVICE
    # ========================================================

    @property
    def service(self):
        if self._service is None:
            self._authenticate()

        return self._service

    @property
    def credentials(self):
        return self._credentials

    # ========================================================
    # FOLDER SEARCH
    # ========================================================

    def find_folder(
        self,
        folder_name: str,
    ) -> Optional[Dict[str, Any]]:

        query = (
            "mimeType='application/vnd.google-apps.folder' "
            "and trashed=false "
            f"and name='{folder_name.replace(chr(39), chr(92) + chr(39))}'"
        )

        response = (
            self.service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id,name,mimeType,parents)",
                pageSize=100,
            )
            .execute()
        )

        files = response.get("files", [])

        if not files:
            return None

        return files[0]

    # ========================================================
    # LIST FILES
    # ========================================================

    def list_files(
        self,
        folder_name: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:

        if folder_id is None and folder_name:
            folder = self.find_folder(folder_name)

            if not folder:
                return []

            folder_id = folder["id"]

        query_parts = [
            "trashed=false"
        ]

        if folder_id:
            query_parts.append(
                f"'{folder_id}' in parents"
            )

        query = " and ".join(query_parts)

        fields = (
            "nextPageToken,"
            "files("
            "id,"
            "name,"
            "mimeType,"
            "size,"
            "modifiedTime,"
            "createdTime,"
            "md5Checksum,"
            "webViewLink,"
            "parents"
            ")"
        )

        results = []

        page_token = None

        while True:

            response = (
                self.service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields=fields,
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )

            results.extend(
                response.get("files", [])
            )

            page_token = response.get(
                "nextPageToken"
            )

            if not page_token:
                break

        return results

    # ========================================================
    # NORMALIZE FILE
    # ========================================================

    def _normalize_file(
        self,
        data: Dict[str, Any],
        folder_name: str = "",
    ) -> DriveVideo:

        return DriveVideo(
            file_id=data.get("id", ""),
            name=data.get("name", ""),
            mime_type=data.get(
                "mimeType",
                "video/mp4",
            ),
            size=int(
                data.get("size") or 0
            ),
            modified_time=data.get(
                "modifiedTime",
                "",
            ),
            created_time=data.get(
                "createdTime",
                "",
            ),
            md5_checksum=data.get(
                "md5Checksum",
                "",
            ),
            web_view_link=data.get(
                "webViewLink",
                "",
            ),
            parents=data.get(
                "parents",
                [],
            ),
            folder_name=folder_name,
        )

    # ========================================================
    # VIDEO LIST
    # ========================================================

    def list_videos(
        self,
        folder_name: str,
    ) -> List[DriveVideo]:

        files = self.list_files(
            folder_name=folder_name
        )

        videos = []

        for item in files:

            mime = item.get(
                "mimeType",
                "",
            )

            name = item.get(
                "name",
                "",
            ).lower()

            is_video = (
                mime.startswith("video/")
                or name.endswith(
                    (
                        ".mp4",
                        ".mov",
                        ".mkv",
                        ".avi",
                        ".webm",
                        ".m4v",
                        ".ts",
                    )
                )
            )

            if not is_video:
                continue

            videos.append(
                self._normalize_file(
                    item,
                    folder_name,
                )
            )

        videos.sort(
            key=lambda x: x.name.lower()
        )

        return videos

    # ========================================================
    # GET FILE
    # ========================================================

    def get_file(
        self,
        file_id: str,
    ) -> DriveVideo:

        response = (
            self.service.files()
            .get(
                fileId=file_id,
                fields=(
                    "id,name,mimeType,size,"
                    "modifiedTime,createdTime,"
                    "md5Checksum,webViewLink,parents"
                ),
            )
            .execute()
        )

        return self._normalize_file(
            response
        )

    # ========================================================
    # DOWNLOAD HTTP RANGE
    # ========================================================

    def _download_http_range(
        self,
        video: DriveVideo,
        output_path: Path,
    ) -> Path:

        self._refresh_credentials_if_needed()

        if not self._credentials:
            raise RuntimeError(
                "Google credentials unavailable."
            )

        if not self._credentials.token:
            raise RuntimeError(
                "Google access token unavailable."
            )

        output_path = Path(output_path)

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp_path = output_path.with_suffix(
            output_path.suffix + ".part"
        )

        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass

        expected_size = int(video.size or 0)

        downloaded = 0

        session = requests.Session()

        try:

            while (
                expected_size == 0
                or downloaded < expected_size
            ):

                if expected_size > 0:
                    end = min(
                        downloaded + self.chunk_size - 1,
                        expected_size - 1,
                    )
                else:
                    end = (
                        downloaded
                        + self.chunk_size
                        - 1
                    )

                url = DOWNLOAD_URL.format(
                    file_id=video.file_id
                )

                headers = {
                    "Authorization": (
                        f"Bearer {self._credentials.token}"
                    ),
                    "Range": (
                        f"bytes={downloaded}-{end}"
                    ),
                }

                success = False

                for attempt in range(
                    1,
                    MAX_RETRIES + 1,
                ):

                    try:

                        response = session.get(
                            url,
                            headers=headers,
                            allow_redirects=True,
                            timeout=self.download_timeout,
                            stream=True,
                        )

                        if response.status_code not in (
                            200,
                            206,
                        ):

                            body = response.text[:500]

                            response.close()

                            raise RuntimeError(
                                "Google Drive HTTP error: "
                                f"status={response.status_code}, "
                                f"body={body!r}"
                            )

                        content_range = response.headers.get(
                            "Content-Range",
                            "",
                        )

                        content_length = response.headers.get(
                            "Content-Length"
                        )

                        # ------------------------------------
                        # Google should return 206 for Range.
                        # ------------------------------------

                        if response.status_code == 206:

                            expected_start = downloaded

                            if content_range:
                                try:
                                    range_part = (
                                        content_range
                                        .split(" ", 1)[1]
                                    )

                                    start_part = (
                                        range_part
                                        .split("-", 1)[0]
                                    )

                                    actual_start = int(
                                        start_part
                                    )

                                    if actual_start != expected_start:
                                        response.close()

                                        raise RuntimeError(
                                            "Google Drive returned "
                                            f"unexpected range start: "
                                            f"expected={expected_start}, "
                                            f"actual={actual_start}"
                                        )

                                except ValueError:
                                    pass

                        elif (
                            response.status_code == 200
                            and downloaded > 0
                        ):
                            response.close()

                            raise RuntimeError(
                                "Google Drive ignored Range request "
                                "after partial download."
                            )

                        written_this_request = 0

                        with open(
                            temp_path,
                            "ab",
                        ) as handle:

                            for chunk in response.iter_content(
                                chunk_size=1024 * 1024
                            ):

                                if not chunk:
                                    continue

                                handle.write(chunk)

                                written_this_request += len(
                                    chunk
                                )

                                downloaded += len(
                                    chunk
                                )

                        response.close()

                        if written_this_request <= 0:
                            raise RuntimeError(
                                "Google Drive returned an empty "
                                "download chunk."
                            )

                        success = True

                        break

                    except Exception as exc:

                        if attempt >= MAX_RETRIES:
                            raise

                        delay = float(
                            attempt * 2
                        )

                        self.logger.warning(
                            "Drive download retry "
                            f"{attempt}/{MAX_RETRIES} "
                            f"in {delay:.1f}s: {exc}"
                        )

                        time.sleep(delay)

                        self._refresh_credentials_if_needed()

                        headers["Authorization"] = (
                            f"Bearer {self._credentials.token}"
                        )

                if not success:
                    raise RuntimeError(
                        "Download chunk failed."
                    )

                # --------------------------------------------
                # Safety guard
                # --------------------------------------------

                if (
                    expected_size > 0
                    and downloaded > expected_size
                ):
                    raise RuntimeError(
                        "Drive download exceeded expected size: "
                        f"expected={expected_size}, "
                        f"actual={downloaded}"
                    )

            # =================================================
            # FINAL SIZE VALIDATION
            # =================================================

            actual_size = temp_path.stat().st_size

            if (
                expected_size > 0
                and actual_size != expected_size
            ):
                raise RuntimeError(
                    "Drive download size mismatch: "
                    f"expected={expected_size}, "
                    f"actual={actual_size}"
                )

            # =================================================
            # OPTIONAL MD5 VALIDATION
            # =================================================

            if video.md5_checksum:

                md5 = hashlib.md5()

                with open(
                    temp_path,
                    "rb",
                ) as handle:

                    while True:

                        chunk = handle.read(
                            8 * 1024 * 1024
                        )

                        if not chunk:
                            break

                        md5.update(chunk)

                actual_md5 = md5.hexdigest()

                if actual_md5.lower() != video.md5_checksum.lower():

                    raise RuntimeError(
                        "Drive download MD5 mismatch: "
                        f"expected={video.md5_checksum}, "
                        f"actual={actual_md5}"
                    )

            # =================================================
            # ATOMIC MOVE
            # =================================================

            temp_path.replace(
                output_path
            )

            return output_path

        finally:

            session.close()

            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    # ========================================================
    # DOWNLOAD TO TEMP
    # ========================================================

    def download_to_temp(
        self,
        video: DriveVideo,
        output_path: str,
    ) -> Path:

        return self._download_http_range(
            video,
            Path(output_path),
        )

    # ========================================================
    # DOWNLOAD
    # ========================================================

    def download(
        self,
        file_id: str,
        output_path: str,
        video: Optional[DriveVideo] = None,
    ) -> Path:

        if video is None:
            video = self.get_file(
                file_id
            )

        return self.download_to_temp(
            video,
            output_path,
        )

    # ========================================================
    # DOWNLOAD VIDEO
    # ========================================================

    def download_video(
        self,
        file_id: str,
        output_path: str,
    ) -> Path:

        return self.download(
            file_id,
            output_path,
        )

    # ========================================================
    # CREATE SOURCE
    # ========================================================

    def create_source(
        self,
        folder_name: str,
    ) -> List[DriveVideo]:

        return self.list_videos(
            folder_name
        )

    # ========================================================
    # SHUTDOWN
    # ========================================================

    def shutdown(self) -> None:

        with self._lock:

            self._service = None

            self._credentials = None


# ============================================================
# BACKWARD COMPATIBILITY
# ============================================================

GoogleDrive = GoogleDriveProvider


# ============================================================
# CLI TEST
# ============================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        ),
    )

    provider = GoogleDriveProvider()

    try:

        videos = provider.list_videos(
            "YouTube 01"
        )

        print()
        print("VIDEOS:")
        print("-" * 80)

        for video in videos:

            print(
                video.file_id,
                "|",
                video.name,
                "|",
                video.size,
            )

        print()
        print(
            "Total videos:",
            len(videos),
        )

    finally:

        provider.shutdown()

