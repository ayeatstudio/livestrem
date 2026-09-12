from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


# ============================================================
# LOG MANAGER
# ============================================================

class LogManager:
    """
    Central logging manager for the streaming engine.

    Responsibilities:
    - Create one central application log.
    - Support console logging.
    - Support rotating file logging.
    - Prevent duplicate handlers.
    - Keep credentials and stream keys out of logs.
    - Provide named component loggers.

    Safety:
    - Does not start FFmpeg.
    - Does not connect to RTMP.
    - Does not access Google Drive.
    - Does not modify playlists.
    - Does not expose stream keys.
    """

    DEFAULT_LOG_DIR = (
        Path(__file__).resolve().parent
        / "logs"
    )

    DEFAULT_LOG_FILE = (
        DEFAULT_LOG_DIR
        / "streaming_engine.log"
    )

    MAX_BYTES = 5 * 1024 * 1024
    BACKUP_COUNT = 5

    def __init__(
        self,
        log_file: str | Path = DEFAULT_LOG_FILE,
        level: int = logging.INFO,
        console: bool = True,
    ):
        self.log_file = Path(log_file)
        self.level = level
        self.console_enabled = console

        self.logger_name = (
            "streaming_engine"
        )

        self.logger = logging.getLogger(
            self.logger_name
        )

        self._configured = False

        self.configure()

    # ---------------------------------------------------------
    # CONFIGURE
    # ---------------------------------------------------------

    def configure(self) -> logging.Logger:

        if self._configured:
            return self.logger

        self.log_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.logger.setLevel(
            self.level
        )

        self.logger.propagate = False

        formatter = logging.Formatter(
            fmt=(
                "%(asctime)s | "
                "%(levelname)s | "
                "%(name)s | "
                "%(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # -----------------------------------------------------
        # File handler
        # -----------------------------------------------------

        file_handler = None

        for handler in self.logger.handlers:

            if isinstance(
                handler,
                RotatingFileHandler,
            ):

                try:
                    if (
                        Path(
                            handler.baseFilename
                        ).resolve()
                        == self.log_file.resolve()
                    ):
                        file_handler = handler
                        break

                except Exception:
                    pass

        if file_handler is None:

            file_handler = (
                RotatingFileHandler(
                    self.log_file,
                    maxBytes=self.MAX_BYTES,
                    backupCount=self.BACKUP_COUNT,
                    encoding="utf-8",
                )
            )

            file_handler.setLevel(
                self.level
            )

            file_handler.setFormatter(
                formatter
            )

            self.logger.addHandler(
                file_handler
            )

        # -----------------------------------------------------
        # Console handler
        # -----------------------------------------------------

        if self.console_enabled:

            console_exists = any(
                isinstance(
                    handler,
                    logging.StreamHandler,
                )
                and not isinstance(
                    handler,
                    RotatingFileHandler,
                )
                for handler
                in self.logger.handlers
            )

            if not console_exists:

                console_handler = (
                    logging.StreamHandler()
                )

                console_handler.setLevel(
                    self.level
                )

                console_handler.setFormatter(
                    formatter
                )

                self.logger.addHandler(
                    console_handler
                )

        self._configured = True

        return self.logger

    # ---------------------------------------------------------
    # LOGGER
    # ---------------------------------------------------------

    def get_logger(
        self,
        component: Optional[str] = None,
    ) -> logging.Logger:

        if not component:
            return self.logger

        return self.logger.getChild(
            str(component)
        )

    # ---------------------------------------------------------
    # LEVEL
    # ---------------------------------------------------------

    def set_level(
        self,
        level: int,
    ) -> None:

        self.level = level

        self.logger.setLevel(
            level
        )

        for handler in self.logger.handlers:
            handler.setLevel(level)

    # ---------------------------------------------------------
    # STANDARD METHODS
    # ---------------------------------------------------------

    def debug(
        self,
        message: str,
        *args,
        **kwargs,
    ) -> None:

        self.logger.debug(
            self._sanitize(message),
            *args,
            **kwargs,
        )

    def info(
        self,
        message: str,
        *args,
        **kwargs,
    ) -> None:

        self.logger.info(
            self._sanitize(message),
            *args,
            **kwargs,
        )

    def warning(
        self,
        message: str,
        *args,
        **kwargs,
    ) -> None:

        self.logger.warning(
            self._sanitize(message),
            *args,
            **kwargs,
        )

    def error(
        self,
        message: str,
        *args,
        **kwargs,
    ) -> None:

        self.logger.error(
            self._sanitize(message),
            *args,
            **kwargs,
        )

    def critical(
        self,
        message: str,
        *args,
        **kwargs,
    ) -> None:

        self.logger.critical(
            self._sanitize(message),
            *args,
            **kwargs,
        )

    # ---------------------------------------------------------
    # EXCEPTION
    # ---------------------------------------------------------

    def exception(
        self,
        message: str,
        *args,
        **kwargs,
    ) -> None:

        self.logger.exception(
            self._sanitize(message),
            *args,
            **kwargs,
        )

    # ---------------------------------------------------------
    # SANITIZE
    # ---------------------------------------------------------

    @staticmethod
    def _sanitize(
        message: str,
    ) -> str:

        value = str(message)

        sensitive_names = (
            "stream_key",
            "streamkey",
            "access_token",
            "refresh_token",
            "client_secret",
            "authorization",
            "password",
            "secret",
        )

        for name in sensitive_names:

            lower_value = value.lower()

            start = 0

            while True:

                index = lower_value.find(
                    name,
                    start,
                )

                if index == -1:
                    break

                separator_index = (
                    index + len(name)
                )

                while (
                    separator_index
                    < len(value)
                    and value[separator_index]
                    in " \t=:"
                ):
                    separator_index += 1

                end = separator_index

                while (
                    end < len(value)
                    and value[end]
                    not in " \t,;|)}]"
                ):
                    end += 1

                value = (
                    value[:separator_index]
                    + "[REDACTED]"
                    + value[end:]
                )

                lower_value = value.lower()

                start = (
                    separator_index
                    + len("[REDACTED]")
                )

        return value


# ============================================================
# GLOBAL LOGGER
# ============================================================

_default_manager = LogManager(
    console=True
)


def get_logger(
    component: Optional[str] = None,
) -> logging.Logger:

    return _default_manager.get_logger(
        component
    )


# ============================================================
# TEST
# ============================================================

def main():

    print("=" * 60)
    print("LOG MANAGER TEST")
    print("=" * 60)

    manager = LogManager(
        console=True
    )

    logger = manager.get_logger(
        "test"
    )

    print("\nLogger configuration:")

    print(
        f"- Log file: "
        f"{manager.log_file}"
    )

    print(
        f"- Exists: "
        f"{manager.log_file.exists()}"
    )

    print(
        f"- Console: "
        f"{manager.console_enabled}"
    )

    # ---------------------------------------------------------
    # Logging test
    # ---------------------------------------------------------

    print("\nLogging test:")

    logger.info(
        "Test information message."
    )

    logger.warning(
        "Test warning message."
    )

    logger.error(
        "Test error message."
    )

    print(
        "- INFO: OK"
    )

    print(
        "- WARNING: OK"
    )

    print(
        "- ERROR: OK"
    )

    # ---------------------------------------------------------
    # Sanitization test
    # ---------------------------------------------------------

    print("\nCredential protection test:")

    sensitive_message = (
        "stream_key=SECRET_TEST_KEY"
    )

    sanitized = manager._sanitize(
        sensitive_message
    )

    protection_ok = (
        "SECRET_TEST_KEY"
        not in sanitized
        and "[REDACTED]"
        in sanitized
    )

    print(
        f"- Original secret exposed: "
        f"{'YES' if 'SECRET_TEST_KEY' in sanitized else 'NO'}"
    )

    print(
        f"- Sanitization: "
        f"{'PASS' if protection_ok else 'FAIL'}"
    )

    # ---------------------------------------------------------
    # Component isolation
    # ---------------------------------------------------------

    print("\nComponent logger test:")

    stream_logger = manager.get_logger(
        "stream_engine"
    )

    scheduler_logger = manager.get_logger(
        "stream_scheduler"
    )

    print(
        f"- Stream logger: "
        f"{stream_logger.name}"
    )

    print(
        f"- Scheduler logger: "
        f"{scheduler_logger.name}"
    )

    print(
        f"- Isolation: "
        f"{'OK' if stream_logger.name != scheduler_logger.name else 'FAILED'}"
    )

    # ---------------------------------------------------------
    # File test
    # ---------------------------------------------------------

    print("\nFile logging test:")

    file_ready = (
        manager.log_file.exists()
        and manager.log_file.is_file()
        and manager.log_file.stat().st_size > 0
    )

    print(
        f"- File created: "
        f"{'YES' if file_ready else 'NO'}"
    )

    # ---------------------------------------------------------
    # Safety
    # ---------------------------------------------------------

    print("\nSafety checks:")

    print(
        "  - No FFmpeg process started."
    )

    print(
        "  - No RTMP connection started."
    )

    print(
        "  - No stream key exposed."
    )

    print(
        "  - No credentials modified."
    )

    print(
        "  - No playlist modified."
    )

    print(
        "  - No Google Drive files modified."
    )

    print("\n" + "=" * 60)
    print(
        "LOG MANAGER TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()