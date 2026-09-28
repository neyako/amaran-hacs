"""Read lights and their keys from the amaran account.

The amaran phone and desktop apps sync every light, including the Bluetooth
Mesh keys, to the Sidus account service. Setup signs in once, reads that list,
and keeps only the keys. The password and session token are never stored.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# From country_region_data.json in the amaran Android app (1.0.71): accounts
# live in one of three regions, picked by the country chosen at sign-up.
EU_COUNTRIES = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
        "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
        "SE", "SI", "SK",
    }
)
CN_COUNTRIES = frozenset({"CN", "HK", "MO", "TW"})

CODE_OK = 20000
CODE_OTHER_REGION = 4001
# Wrong password, unknown account.
CODES_BAD_LOGIN = frozenset({20002, 20014})
# Sign-in answers "invalid parameters" (10001) without these app headers.
APP_HEADERS = {"platform": "2", "request_source": "4"}
REQUEST_TIMEOUT_SECONDS = 20


class CloudAuthError(Exception):
    """The account service rejected the sign-in."""


class CloudError(Exception):
    """The account service returned something unexpected."""


def region_url(country: str | None) -> str:
    """Return the account service URL for a country code."""

    country = (country or "").upper()
    if country in CN_COUNTRIES:
        region = "cn"
    elif country in EU_COUNTRIES:
        region = "eu"
    else:
        region = "us"
    return f"https://{region}.sidus.link/"


async def async_fetch_import_payload(
    session: Any, account: str, password: str, country: str | None
) -> dict[str, Any]:
    """Sign in and return lights in the same shape as the export script."""

    area = (country or "US").upper()
    is_email = "@" in account
    for _attempt in range(2):
        base_url = region_url(area)
        reply = await _async_request(
            session,
            "post",
            base_url + "uc/user/login",
            headers=APP_HEADERS,
            json={
                "email": account if is_email else "",
                "phone_number": "" if is_email else account,
                "password": password,
                "area": area,
            },
        )
        code = reply.get("code")
        data = reply.get("data") or {}
        _LOGGER.debug(
            "amaran sign-in area=%s code=%s msg=%s", area, code, reply.get("msg")
        )
        if code == CODE_OK and data.get("token"):
            token = str(data["token"])
            break
        if code in CODES_BAD_LOGIN:
            raise CloudAuthError
        other_areas = [
            str(user["area"]).upper()
            for user in data.get("OtherRegionUser") or []
            if user.get("area")
        ]
        if code != CODE_OTHER_REGION or not other_areas:
            raise CloudError(f"sign-in failed with code {code}")
        area = other_areas[0]
    else:
        raise CloudError("sign-in kept moving between regions")

    reply = await _async_request(
        session,
        "get",
        base_url + "amaran/pack/query",
        headers={**APP_HEADERS, "Token": token},
    )
    if reply.get("code") != CODE_OK or not isinstance(reply.get("data"), dict):
        raise CloudError(f"light list failed with code {reply.get('code')}")
    return import_payload(reply["data"])


def import_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Convert the account light list into export-script JSON."""

    meshes = {
        mesh.get("mesh_uuid"): mesh
        for mesh in (data.get("meshs") or {}).get("existing") or []
        if mesh.get("net_key") and mesh.get("app_key")
    }
    lights = []
    for light in (data.get("fixtures") or {}).get("existing") or []:
        mesh = meshes.get(light.get("mesh_uuid"))
        if mesh is None:
            continue
        lights.append(
            {
                "name": " ".join(str(light.get("name") or "").split()),
                "code": light.get("code"),
                "mac_address": light.get("mac_address"),
                "node_address": light.get("node_address"),
                "mesh_uuid": mesh["mesh_uuid"],
                "net_key": mesh["net_key"],
                "app_key": mesh["app_key"],
            }
        )
    return {"fixtures": lights}


async def _async_request(
    session: Any, method: str, url: str, **kwargs: Any
) -> dict[str, Any]:
    async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
        async with session.request(method, url, **kwargs) as response:
            try:
                reply = await response.json(content_type=None)
            except ValueError as err:
                raise CloudError("reply was not JSON") from err
    if not isinstance(reply, dict):
        raise CloudError("reply was not an object")
    return reply
