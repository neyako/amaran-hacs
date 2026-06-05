"""Sensitive-data redaction helpers."""

from __future__ import annotations

from typing import Any

from .const import CONF_APP_KEY, CONF_IMPORT_JSON, CONF_NET_KEY

REDACTED = "**REDACTED**"
SENSITIVE_KEYS = {CONF_APP_KEY, CONF_NET_KEY, CONF_IMPORT_JSON}


def redact_sensitive(value: Any) -> Any:
    """Recursively redact mesh keys and pasted JSON from diagnostics/log payloads."""

    if isinstance(value, dict):
        return {
            key: REDACTED if str(key) in SENSITIVE_KEYS else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    return value
