from __future__ import annotations

import platform
import sys


SUPPORTED_SYSTEMS = {"Darwin", "Linux"}


def unsupported_platform_message(system: str | None = None) -> str | None:
    current = system or platform.system()
    if current in SUPPORTED_SYSTEMS:
        return None
    return (
        f"QuantBench launch builds support macOS and Linux only; "
        f"detected {current or 'unknown'} on Python {sys.version_info.major}.{sys.version_info.minor}."
    )


def assert_supported_platform(system: str | None = None) -> None:
    message = unsupported_platform_message(system)
    if message:
        raise RuntimeError(message)
