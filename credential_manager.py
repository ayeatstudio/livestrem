from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
CREDENTIAL_FILE = CONFIG_DIR / "credentials.json"


class CredentialManager:

    def __init__(
        self,
        credential_file: str | Path = CREDENTIAL_FILE,
    ):
        self.credential_file = Path(credential_file)

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> dict:

        if not self.credential_file.exists():
            return {
                "credentials": {}
            }

        try:
            with self.credential_file.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)

        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid credentials JSON:\n{exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                "Credentials root must be an object."
            )

        credentials = data.get(
            "credentials",
            {}
        )

        if not isinstance(credentials, dict):
            raise ValueError(
                "'credentials' must be an object."
            )

        return data

    # ---------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------

    def save(
        self,
        destination_id: str,
        stream_key: str,
        rtmp_url: str = "",
    ) -> None:

        data = self.load()

        data["credentials"][destination_id] = {
            "stream_key": stream_key,
            "rtmp_url": rtmp_url,
        }

        CONFIG_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.credential_file.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    def get(
        self,
        destination_id: str,
    ) -> dict | None:

        data = self.load()

        return data["credentials"].get(
            destination_id
        )

    # ---------------------------------------------------------
    # CHECK
    # ---------------------------------------------------------

    def exists(
        self,
        destination_id: str,
    ) -> bool:

        credential = self.get(
            destination_id
        )

        return bool(
            credential
            and credential.get("stream_key")
        )

    # ---------------------------------------------------------
    # MASK
    # ---------------------------------------------------------

    @staticmethod
    def mask_secret(
        secret: str,
    ) -> str:

        if not secret:
            return "NOT CONFIGURED"

        if len(secret) <= 4:
            return "****"

        return (
            secret[:2]
            + ("*" * (len(secret) - 4))
            + secret[-2:]
        )


# =============================================================
# TEST
# =============================================================

def main():

    print("=" * 60)
    print("CREDENTIAL MANAGER TEST")
    print("=" * 60)

    manager = CredentialManager()

    print("\nCredential file:")
    print(manager.credential_file)

    # Test credential only.
    # This is NOT a real stream key.

    test_key = "TEST_STREAM_KEY_123456"

    manager.save(
        destination_id="youtube_01",
        stream_key=test_key,
        rtmp_url="rtmp://test.example/live",
    )

    print("\nCredential saved.")

    credential = manager.get(
        "youtube_01"
    )

    if credential:

        print("\nCredential loaded.")

        print(
            "RTMP URL:",
            credential["rtmp_url"]
        )

        print(
            "Stream Key:",
            manager.mask_secret(
                credential["stream_key"]
            )
        )

    print("\nCredential exists:")

    print(
        manager.exists("youtube_01")
    )

    print("\n" + "=" * 60)
    print("CREDENTIAL MANAGER TEST SUCCESS")
    print("=" * 60)

    print(
        "No real stream key was used."
    )


if __name__ == "__main__":
    main()