"""Recognize amaran lights from their Bluetooth advertisements.

A light added in the amaran app advertises the Bluetooth Mesh Proxy service
with its network ID, which is derived from the network key. Before setup that
only says "a Bluetooth Mesh network"; after setup it tells us the light belongs
to a network the user already added.
"""

from __future__ import annotations

from collections.abc import Mapping

from .protocol import mesh_network_id, normalize_hex_key

MESH_PROXY_SERVICE_UUID = "00001828-0000-1000-8000-00805f9b34fb"
_NETWORK_ID_TYPE = 0x00


def advertised_network_id(service_data: Mapping[str, bytes]) -> bytes | None:
    """Return the advertised network ID, or None for other advertisements."""

    data = service_data.get(MESH_PROXY_SERVICE_UUID)
    if not data or len(data) != 9 or data[0] != _NETWORK_ID_TYPE:
        return None
    return bytes(data[1:])


def network_id_for_key(net_key: str) -> bytes:
    """Return the network ID a light with this network key advertises."""

    return mesh_network_id(normalize_hex_key(net_key, field="network key"))
