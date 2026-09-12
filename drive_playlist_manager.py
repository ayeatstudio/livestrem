from __future__ import annotations

from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


BASE_DIR = Path(__file__).resolve().parent

TOKEN_FILE = BASE_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly"
]


DESTINATION_FOLDERS = {
    "youtube_01": "YouTube 01",
    "youtube_02": "YouTube 02",
    "youtube_03": "YouTube 03",
    "youtube_04": "YouTube 04",

    "facebook_01": "Facebook 01",
    "facebook_02": "Facebook 02",

    "instagram_01": "Instagram 01",
}


VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/x-matroska",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/mpeg",
}


class GoogleDriveFolderManager:

    def __init__(self):

        if not TOKEN_FILE.exists():
            raise FileNotFoundError(
                f"Google Drive token not found:\n"
                f"{TOKEN_FILE}"
            )

        self.credentials = (
            Credentials.from_authorized_user_file(
                str(TOKEN_FILE),
                SCOPES,
            )
        )

        self.service = build(
            "drive",
            "v3",
            credentials=self.credentials,
        )

    # ---------------------------------------------------------
    # SEARCH FOLDER
    # ---------------------------------------------------------

    def find_folder(
        self,
        folder_name: str,
        parent_id: str | None = None,
    ):

        query_parts = [
            "mimeType = "
            "'application/vnd.google-apps.folder'",
            f"name = '{folder_name}'",
            "trashed = false",
        ]

        if parent_id:
            query_parts.append(
                f"'{parent_id}' in parents"
            )

        query = " and ".join(
            query_parts
        )

        response = (
            self.service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id,name,mimeType)",
                pageSize=100,
            )
            .execute()
        )

        files = response.get(
            "files",
            []
        )

        if not files:
            return None

        return files[0]

    # ---------------------------------------------------------
    # LIST VIDEOS
    # ---------------------------------------------------------

    def list_videos(
        self,
        folder_id: str,
    ) -> list[dict]:

        query = (
            f"'{folder_id}' in parents "
            "and trashed = false"
        )

        response = (
            self.service.files()
            .list(
                q=query,
                spaces="drive",
                fields=(
                    "files("
                    "id,"
                    "name,"
                    "mimeType,"
                    "size,"
                    "modifiedTime,"
                    "createdTime"
                    ")"
                ),
                orderBy="name",
                pageSize=1000,
            )
            .execute()
        )

        files = response.get(
            "files",
            []
        )

        videos = [
            file
            for file in files
            if file.get("mimeType")
            in VIDEO_MIME_TYPES
        ]

        return videos

    # ---------------------------------------------------------
    # DISCOVER STRUCTURE
    # ---------------------------------------------------------

    def discover(
        self,
        root_folder_name: str = "Streaming Engine",
    ):

        print(
            f"Searching root folder: "
            f"{root_folder_name}"
        )

        root = self.find_folder(
            root_folder_name
        )

        if not root:

            print(
                "\nROOT FOLDER NOT FOUND"
            )

            print(
                f'Create a Google Drive folder named '
                f'"{root_folder_name}" first.'
            )

            return {}

        print(
            f"\nRoot folder found:"
        )

        print(
            f"Name: {root['name']}"
        )

        print(
            f"ID: {root['id']}"
        )

        print(
            "\nDestination folders:"
        )

        result = {}

        for destination_id, folder_name in (
            DESTINATION_FOLDERS.items()
        ):

            folder = self.find_folder(
                folder_name,
                root["id"],
            )

            if not folder:

                print(
                    f"- {destination_id} | "
                    f"{folder_name} | "
                    f"NOT FOUND"
                )

                result[destination_id] = {
                    "folder_name": folder_name,
                    "folder_id": None,
                    "videos": [],
                }

                continue

            videos = self.list_videos(
                folder["id"]
            )

            print(
                f"- {destination_id} | "
                f"{folder['name']} | "
                f"videos={len(videos)}"
            )

            for index, video in enumerate(
                videos,
                start=1,
            ):

                size = video.get(
                    "size",
                    "N/A"
                )

                print(
                    f"    {index}. "
                    f"{video['name']} | "
                    f"{size} bytes"
                )

            result[destination_id] = {
                "folder_name": folder["name"],
                "folder_id": folder["id"],
                "videos": videos,
            }

        return result


# =============================================================
# TEST
# =============================================================

def main():

    print("=" * 60)
    print("GOOGLE DRIVE FOLDER PLAYLIST MANAGER TEST")
    print("=" * 60)

    manager = (
        GoogleDriveFolderManager()
    )

    result = manager.discover()

    print("\n" + "=" * 60)
    print("FOLDER DISCOVERY TEST COMPLETE")
    print("=" * 60)

    found = 0
    missing = 0
    total_videos = 0

    for destination_id, data in (
        result.items()
    ):

        if data["folder_id"]:

            found += 1

            total_videos += len(
                data["videos"]
            )

        else:

            missing += 1

    print(
        f"Folders found: {found}"
    )

    print(
        f"Folders missing: {missing}"
    )

    print(
        f"Total videos discovered: "
        f"{total_videos}"
    )

    print(
        "\nNo streaming was started."
    )


if __name__ == "__main__":
    main()