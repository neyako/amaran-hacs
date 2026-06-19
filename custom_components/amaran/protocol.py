"""Amaran Sidus command packing and Bluetooth Mesh proxy encryption."""

from __future__ import annotations

from dataclasses import dataclass
import re

from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from .const import (
    PROXY_FILTER_TYPE_REJECT,
    SIDUS_ACCESS_OPCODE,
)

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_ZERO_128 = b"\x00" * 16


@dataclass(frozen=True)
class MeshKeys:
    """Derived Bluetooth Mesh network values."""

    nid: int
    encryption_key: bytes
    privacy_key: bytes
    aid: int


@dataclass(frozen=True)
class SidusStatus:
    """Decoded Telink 0x26 status report."""

    power: bool
    brightness: int
    color_temp_kelvin: int | None
    hs_color: tuple[float, float] | None
    color_mode: str
    source_address: int
    destination_address: int
    sequence: int


@dataclass(frozen=True)
class SidusPowerInfo:
    """Decoded Sidus power/battery report."""

    power_supply_mode: str
    battery_time_minutes: int
    battery_percentage: int
    battery_voltage: int
    external_voltage: int
    command_type: int
    operation_type: int
    source_address: int
    destination_address: int
    sequence: int


@dataclass(frozen=True)
class DecodedAccessMessage:
    """Decoded unsegmented Mesh Proxy access payload."""

    source_address: int
    destination_address: int
    sequence: int
    access_payload: bytes
    sidus_payload: bytes | None
    sidus_status: SidusStatus | None
    sidus_power_info: SidusPowerInfo | None


def normalize_hex_key(value: str, *, field: str = "key") -> bytes:
    """Return a 16-byte key from user-supplied hex."""

    compact = value.replace(" ", "").replace(":", "").replace("-", "")
    if len(compact) != 32 or not _HEX_RE.match(compact):
        raise ValueError(f"{field} must be 32 hex characters")
    return bytes.fromhex(compact)


def sidus_checksum(payload: bytes) -> int:
    """Checksum used by the 10-byte Sidus MCU payload."""

    if len(payload) != 10:
        raise ValueError("Sidus payload must be 10 bytes")
    return sum(payload[1:]) & 0xFF


def _finalize_sidus(payload: bytearray) -> bytes:
    payload[0] = sidus_checksum(payload)
    return bytes(payload)


def _round_half_up(value: float) -> int:
    return int(value + 0.5)


def _clamp_intensity(intensity: int | float) -> int:
    return max(0, min(1000, _round_half_up(float(intensity))))


def _ha_brightness_to_intensity(brightness: int) -> int:
    brightness = max(0, min(255, int(brightness)))
    return _round_half_up(brightness / 255 * 1000)


def _intensity_to_ha_brightness(intensity: int) -> int:
    intensity = max(0, min(1000, int(intensity)))
    return _round_half_up(intensity / 1000 * 255)


def brightness_payload(intensity: int) -> bytes:
    """Build the Telink brightness payload, cmd_type 0x8f."""

    value = _clamp_intensity(intensity)
    payload = bytearray(10)
    payload[7] = (value & 0x03) << 6
    payload[8] = (value >> 2) & 0xFF
    payload[9] = 0x8F
    return _finalize_sidus(payload)


def brightness_payload_percent(percent: int) -> bytes:
    """Build a brightness payload from a 0..100 percentage."""

    percent = max(0, min(100, int(percent)))
    return brightness_payload(percent * 10)


def brightness_payload_ha(brightness: int) -> bytes:
    """Build a brightness payload from Home Assistant's 0..255 brightness."""

    return brightness_payload(_ha_brightness_to_intensity(brightness))


def cct_payload(
    *,
    intensity: int,
    kelvin: int,
    gm: int = 0,
) -> bytes:
    """Build the Telink CCT/GM payload, cmd_type 0x82.

    ``gm`` is the reference implementation's offset scale: -10..+10, 0 neutral.
    """

    value = _clamp_intensity(intensity)
    telink_cct = (int(kelvin) + 5) // 10
    telink_cct = max(80, min(2000, telink_cct))
    gm_value = max(0, min(20, _round_half_up(float(gm)) + 10))

    low = (value & 0x03) << 62
    high = 0x8200 | ((value >> 2) & 0xFF)
    if telink_cct < 1001:
        low |= telink_cct << 52
        high |= (telink_cct >> 12) & 0xFF
    else:
        low |= ((telink_cct + 0x18) & 0x3FF) << 52
        low |= 0x0000040000000000
    low |= (gm_value & 0x7F) << 45

    payload = bytearray(10)
    for index in range(8):
        payload[index] = (low >> (index * 8)) & 0xFF
    payload[8] = high & 0xFF
    payload[9] = (high >> 8) & 0xFF
    return _finalize_sidus(payload)


def cct_payload_percent(*, percent: int, kelvin: int, gm: int = 0) -> bytes:
    """Build a CCT payload from 0..100 brightness percentage and kelvin."""

    percent = max(0, min(100, int(percent)))
    return cct_payload(intensity=percent * 10, kelvin=kelvin, gm=gm)


def cct_payload_ha(*, brightness: int, kelvin: int, gm: int = 0) -> bytes:
    """Build a CCT payload from Home Assistant brightness and kelvin."""

    return cct_payload(
        intensity=_ha_brightness_to_intensity(brightness),
        kelvin=kelvin,
        gm=gm,
    )


def hsi_payload(
    *, hue: int, saturation: int, intensity: int
) -> bytes:
    """Build the Telink HSI/RGB payload, cmd_type 0x81."""

    value = _clamp_intensity(intensity)
    hue_value = max(0, min(360, int(hue))) & 0x1FF
    saturation_value = max(0, min(100, int(saturation))) & 0x7F

    payload = bytearray(10)
    payload[5] = (saturation_value & 0x03) << 6
    payload[6] = ((hue_value & 0x07) << 5) | ((saturation_value >> 2) & 0x1F)
    payload[7] = ((hue_value >> 3) & 0x3F) | ((value & 0x03) << 6)
    payload[8] = (value >> 2) & 0xFF
    payload[9] = 0x81
    return _finalize_sidus(payload)


def hsi_payload_ha(
    *, hue: int | float, saturation: int | float, brightness: int
) -> bytes:
    """Build an HSI payload from HA hue/saturation and brightness."""

    return hsi_payload(
        hue=_round_half_up(float(hue)),
        saturation=_round_half_up(float(saturation)),
        intensity=_ha_brightness_to_intensity(brightness),
    )


def power_payload(on: bool) -> bytes:
    """Build the Telink on/off payload, cmd_type 0x8c."""

    payload = bytearray(10)
    payload[8] = 0x01 if on else 0x00
    payload[9] = 0x8C
    return _finalize_sidus(payload)


def status_request_payload() -> bytes:
    """Build the Telink status request payload, cmd_type 0x0e."""

    payload = bytearray(10)
    payload[9] = 0x0E
    return _finalize_sidus(payload)


def power_status_request_payload() -> bytes:
    """Build the Sidus power/battery status request payload, cmd_type 0x0a."""

    payload = bytearray(10)
    payload[9] = 0x0A
    return _finalize_sidus(payload)


def decode_sidus_status_payload(
    sidus_payload: bytes,
    *,
    source_address: int,
    destination_address: int,
    sequence: int,
) -> SidusStatus | None:
    """Decode a Telink 0x26 status report payload."""

    if len(sidus_payload) < 10:
        return None
    payload = sidus_payload[:10]
    if payload[0] != sidus_checksum(payload):
        return None

    command = payload[9] & 0x7F
    low = sum(payload[index] << (index * 8) for index in range(8))
    high = payload[8] | (payload[9] << 8)
    power = bool((low >> 8) & 0x01)
    if command == 0x02:
        cct_raw = (low >> 52) & 0x3FF
        cct_flag = (low >> 42) & 0x01
        telink_cct = cct_raw + 1000 if cct_flag else cct_raw
        intensity = ((high << 2) | ((low >> 62) & 0x03)) & 0x3FF
        return SidusStatus(
            power=power,
            brightness=_intensity_to_ha_brightness(intensity),
            color_temp_kelvin=int(telink_cct * 10),
            hs_color=None,
            color_mode="color_temp",
            source_address=source_address,
            destination_address=destination_address,
            sequence=sequence,
        )

    if command == 0x01:
        saturation = ((payload[6] & 0x1F) << 2) | ((payload[5] >> 6) & 0x03)
        hue = ((payload[7] & 0x3F) << 3) | ((payload[6] >> 5) & 0x07)
        intensity = (payload[8] << 2) | ((payload[7] >> 6) & 0x03)
        return SidusStatus(
            power=power,
            brightness=_intensity_to_ha_brightness(min(1000, intensity)),
            color_temp_kelvin=None,
            hs_color=(float(min(360, hue)), float(min(100, saturation))),
            color_mode="hs",
            source_address=source_address,
            destination_address=destination_address,
            sequence=sequence,
        )
    return None


def decode_sidus_power_info_payload(
    sidus_payload: bytes,
    *,
    source_address: int,
    destination_address: int,
    sequence: int,
) -> SidusPowerInfo | None:
    """Decode the SDK-confirmed Sidus 0x0a power/battery report payload."""

    if len(sidus_payload) < 10:
        return None
    payload = sidus_payload[:10]
    if payload[0] != sidus_checksum(payload):
        return None

    command_type = payload[9] & 0x7F
    if command_type != 0x0A:
        return None

    power_state = (payload[2] >> 7) & 0x01
    battery_time = payload[3] | ((payload[4] & 0x01) << 8)
    battery_percentage = (payload[4] >> 1) & 0x7F
    battery_voltage = payload[5] | (payload[6] << 8)
    external_voltage = payload[7] | (payload[8] << 8)
    operation_type = (payload[9] >> 7) & 0x01
    return SidusPowerInfo(
        power_supply_mode="battery" if power_state else "ac",
        battery_time_minutes=battery_time,
        battery_percentage=battery_percentage,
        battery_voltage=battery_voltage,
        external_voltage=external_voltage,
        command_type=command_type,
        operation_type=operation_type,
        source_address=source_address,
        destination_address=destination_address,
        sequence=sequence,
    )


def access_payload(sidus_payload: bytes, opcode: int = SIDUS_ACCESS_OPCODE) -> bytes:
    """Wrap a 10-byte Sidus payload in the app's one-byte access opcode."""

    if len(sidus_payload) != 10:
        raise ValueError("Sidus payload must be 10 bytes")
    if not 0 <= opcode <= 0x7F:
        raise ValueError("Only one-octet mesh access opcodes are supported")
    return bytes([opcode]) + sidus_payload


def derive_mesh_keys(net_key: bytes, app_key: bytes) -> MeshKeys:
    """Derive Bluetooth Mesh K2/K4 values used by the proxy network PDU."""

    nid, encryption_key, privacy_key = _k2(net_key)
    aid = _k4(app_key)
    return MeshKeys(
        nid=nid,
        encryption_key=encryption_key,
        privacy_key=privacy_key,
        aid=aid,
    )


def build_mesh_proxy_pdu(
    *,
    net_key: bytes,
    app_key: bytes,
    src: int,
    dst: int,
    seq: int,
    iv_index: int,
    sidus_payload: bytes,
    ttl: int = 7,
) -> bytes:
    """Encrypt one unsegmented access message as a Mesh Proxy Network PDU."""

    if not 0 <= src <= 0xFFFF or not 0 <= dst <= 0xFFFF:
        raise ValueError("mesh addresses must be 16-bit values")
    if not 0 <= seq <= 0xFFFFFF:
        raise ValueError("mesh sequence must be a 24-bit value")
    if not 0 <= iv_index <= 0xFFFFFFFF:
        raise ValueError("IV index must be a 32-bit value")
    if not 0 <= ttl <= 0x7F:
        raise ValueError("TTL must be a 7-bit value")

    keys = derive_mesh_keys(net_key, app_key)

    access = access_payload(sidus_payload)
    seq_bytes = seq.to_bytes(3, "big")
    src_bytes = src.to_bytes(2, "big")
    dst_bytes = dst.to_bytes(2, "big")
    iv_bytes = iv_index.to_bytes(4, "big")

    access_nonce = b"\x01\x00" + seq_bytes + src_bytes + dst_bytes + iv_bytes
    upper_transport = AESCCM(app_key, tag_length=4).encrypt(access_nonce, access, None)

    lower_transport = bytes([(1 << 6) | keys.aid]) + upper_transport
    ctl_ttl = ttl
    network_nonce = b"\x00" + bytes([ctl_ttl]) + seq_bytes + src_bytes + b"\x00\x00" + iv_bytes
    network_plaintext = dst_bytes + lower_transport
    encrypted_network = AESCCM(keys.encryption_key, tag_length=4).encrypt(
        network_nonce, network_plaintext, None
    )

    privacy_random = encrypted_network[:7]
    pecb_input = b"\x00" * 5 + iv_bytes + privacy_random
    pecb = _aes_ecb(keys.privacy_key, pecb_input)
    clear_header = bytes([ctl_ttl]) + seq_bytes + src_bytes
    obfuscated_header = bytes(clear_header[i] ^ pecb[i] for i in range(6))

    ivi_nid = ((iv_index & 1) << 7) | keys.nid
    network_pdu = bytes([ivi_nid]) + obfuscated_header + encrypted_network
    return b"\x00" + network_pdu


def build_proxy_filter_pdu(
    *,
    net_key: bytes,
    app_key: bytes,
    src: int,
    seq: int,
    iv_index: int,
    filter_type: int = PROXY_FILTER_TYPE_REJECT,
    addresses: tuple[int, ...] = (),
) -> bytes:
    """Encrypt a Bluetooth Mesh Proxy Configuration PDU (Mesh Profile 6.5).

    With ``filter_type`` set to the reject list and no ``addresses``, the proxy
    forwards every mesh message to the client. The integration needs this so the
    light's status and battery reports reach Home Assistant; the proxy's default
    empty accept list otherwise drops every message addressed to ``src``.
    """

    if not 0 <= src <= 0xFFFF:
        raise ValueError("mesh source address must be a 16-bit value")
    if not 0 <= seq <= 0xFFFFFF:
        raise ValueError("mesh sequence must be a 24-bit value")
    if not 0 <= iv_index <= 0xFFFFFFFF:
        raise ValueError("IV index must be a 32-bit value")

    keys = derive_mesh_keys(net_key, app_key)

    if addresses:
        # Add Addresses To Filter (opcode 0x01).
        config = bytes([0x01]) + b"".join(
            int(addr).to_bytes(2, "big") for addr in addresses
        )
    else:
        # Set Filter Type (opcode 0x00).
        config = bytes([0x00, filter_type & 0xFF])

    seq_bytes = seq.to_bytes(3, "big")
    src_bytes = src.to_bytes(2, "big")
    iv_bytes = iv_index.to_bytes(4, "big")

    # Proxy Configuration is a control message (CTL=1) with TTL 0. It uses the
    # proxy nonce (type 0x03), a 64-bit NetMIC, and an unassigned destination.
    ctl_ttl = 0x80
    proxy_nonce = b"\x03\x00" + seq_bytes + src_bytes + b"\x00\x00" + iv_bytes
    network_plaintext = b"\x00\x00" + config
    encrypted_network = AESCCM(keys.encryption_key, tag_length=8).encrypt(
        proxy_nonce, network_plaintext, None
    )

    privacy_random = encrypted_network[:7]
    pecb = _aes_ecb(keys.privacy_key, b"\x00" * 5 + iv_bytes + privacy_random)
    clear_header = bytes([ctl_ttl]) + seq_bytes + src_bytes
    obfuscated_header = bytes(clear_header[i] ^ pecb[i] for i in range(6))

    ivi_nid = ((iv_index & 1) << 7) | keys.nid
    network_pdu = bytes([ivi_nid]) + obfuscated_header + encrypted_network
    # Proxy PDU type 0x02 = Proxy Configuration.
    return b"\x02" + network_pdu


def is_proxy_filter_status(proxy_pdu: bytes) -> bool:
    """Return true for a Proxy Configuration Filter Status PDU (type 0x02)."""

    return len(proxy_pdu) >= 1 and (proxy_pdu[0] & 0x3F) == 0x02


def decode_mesh_proxy_access(
    *,
    net_key: bytes,
    app_key: bytes,
    iv_index: int,
    proxy_pdu: bytes,
) -> DecodedAccessMessage | None:
    """Decode one unsegmented Mesh Proxy Data Out network PDU if possible."""

    if len(proxy_pdu) < 15 or (proxy_pdu[0] & 0x3F) != 0x00:
        return None
    network_pdu = proxy_pdu[1:]
    if len(network_pdu) < 14:
        return None

    keys = derive_mesh_keys(net_key, app_key)
    if (network_pdu[0] & 0x7F) != keys.nid:
        return None

    iv_bytes = iv_index.to_bytes(4, "big")
    obfuscated_header = network_pdu[1:7]
    encrypted_network = network_pdu[7:]
    pecb = _aes_ecb(
        keys.privacy_key,
        b"\x00" * 5 + iv_bytes + encrypted_network[:7],
    )
    clear_header = bytes(obfuscated_header[index] ^ pecb[index] for index in range(6))
    ctl_ttl = clear_header[0]
    if ctl_ttl & 0x80:
        return None

    sequence = int.from_bytes(clear_header[1:4], "big")
    source_address = int.from_bytes(clear_header[4:6], "big")
    network_nonce = (
        b"\x00"
        + bytes([ctl_ttl])
        + clear_header[1:4]
        + clear_header[4:6]
        + b"\x00\x00"
        + iv_bytes
    )
    try:
        network_plaintext = AESCCM(keys.encryption_key, tag_length=4).decrypt(
            network_nonce,
            encrypted_network,
            None,
        )
    except ValueError:
        return None
    if len(network_plaintext) < 4:
        return None

    destination_address = int.from_bytes(network_plaintext[:2], "big")
    lower_transport = network_plaintext[2:]
    transport_header = lower_transport[0]
    if (transport_header & 0x80) or not ((transport_header >> 6) & 0x01):
        return None
    if (transport_header & 0x3F) != keys.aid:
        return None

    access_nonce = (
        b"\x01\x00"
        + clear_header[1:4]
        + clear_header[4:6]
        + network_plaintext[:2]
        + iv_bytes
    )
    try:
        decoded_access = AESCCM(app_key, tag_length=4).decrypt(
            access_nonce,
            lower_transport[1:],
            None,
        )
    except ValueError:
        return None

    sidus_payload = (
        decoded_access[1:11]
        if len(decoded_access) >= 11 and decoded_access[0] == SIDUS_ACCESS_OPCODE
        else None
    )
    sidus_status = (
        decode_sidus_status_payload(
            sidus_payload,
            source_address=source_address,
            destination_address=destination_address,
            sequence=sequence,
        )
        if sidus_payload is not None
        else None
    )
    sidus_power_info = (
        decode_sidus_power_info_payload(
            sidus_payload,
            source_address=source_address,
            destination_address=destination_address,
            sequence=sequence,
        )
        if sidus_payload is not None
        else None
    )
    return DecodedAccessMessage(
        source_address=source_address,
        destination_address=destination_address,
        sequence=sequence,
        access_payload=decoded_access,
        sidus_payload=sidus_payload,
        sidus_status=sidus_status,
        sidus_power_info=sidus_power_info,
    )


def _aes_cmac(key: bytes, data: bytes) -> bytes:
    cmac = CMAC(algorithms.AES(key))
    cmac.update(data)
    return cmac.finalize()


def _aes_ecb(key: bytes, block: bytes) -> bytes:
    if len(block) != 16:
        raise ValueError("AES-ECB block must be 16 bytes")
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(block) + encryptor.finalize()


def _s1(data: bytes) -> bytes:
    return _aes_cmac(_ZERO_128, data)


def _k2(net_key: bytes, p: bytes = b"\x00") -> tuple[int, bytes, bytes]:
    salt = _s1(b"smk2")
    t = _aes_cmac(salt, net_key)
    t1 = _aes_cmac(t, p + b"\x01")
    t2 = _aes_cmac(t, t1 + p + b"\x02")
    t3 = _aes_cmac(t, t2 + p + b"\x03")
    return t1[-1] & 0x7F, t2, t3


def _k4(app_key: bytes) -> int:
    salt = _s1(b"smk4")
    t = _aes_cmac(salt, app_key)
    return _aes_cmac(t, b"id6\x01")[-1] & 0x3F
