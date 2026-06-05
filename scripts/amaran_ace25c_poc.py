#!/usr/bin/env python3
"""Standalone Amaran Ace 25C Bluetooth Mesh proxy proof-of-concept."""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.amaran.const import MESH_PROXY_IN_UUID
from custom_components.amaran.protocol import (
    access_payload,
    brightness_payload_percent,
    build_mesh_proxy_pdu,
    cct_payload_percent,
    normalize_hex_key,
    power_payload,
)

DEFAULT_DESKTOP_DB = (
    Path.home()
    / "Library/Application Support/amaran Desktop/EXAMPLE_secure_id/amaran.db"
)
DEFAULT_SOURCE_ADDRESS = 0x000F
REDACTED = "**REDACTED**"


def _load_desktop_fixture(
    db_path: Path, fixture_mac: str | None
) -> tuple[str, str, int, dict[str, str | int | None]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if fixture_mac:
            fixture = conn.execute(
                """
                select uuid, mac_address, code, name, node_address, device_key,
                       device_uuid, state
                from fixtures
                where upper(mac_address) = upper(?)
                """,
                (fixture_mac,),
            ).fetchone()
        else:
            fixture = conn.execute(
                """
                select uuid, mac_address, code, name, node_address, device_key,
                       device_uuid, state
                from fixtures
                where code = '400U5'
                order by update_time desc
                limit 1
                """
            ).fetchone()

        if fixture is None:
            raise RuntimeError(f"fixture not found in {db_path}")

        mesh = conn.execute(
            """
            select net_key, app_key, uuid
            from mesh
            where fixtures_ordered_list like ?
            order by update_time desc
            limit 1
            """,
            (f"%{fixture['code']}-{str(fixture['mac_address'])[-6:].replace(':', '')}%",),
        ).fetchone()
        if mesh is None:
            mesh = conn.execute(
                "select net_key, app_key, uuid from mesh order by update_time desc limit 1"
            ).fetchone()
        if mesh is None:
            raise RuntimeError(f"mesh row not found in {db_path}")

        info = dict(fixture)
        info["mesh_uuid"] = mesh["uuid"]
        return mesh["net_key"], mesh["app_key"], int(fixture["node_address"]), info


def _list_desktop_fixtures(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        mesh = conn.execute("select uuid, net_key, app_key from mesh").fetchall()
        print("Meshes:")
        for row in mesh:
            print(f"  {row['uuid']} mesh_keys={REDACTED}")

        fixtures = conn.execute(
            """
            select mac_address, code, name, node_address, device_key, device_uuid, state
            from fixtures
            order by node_address
            """
        ).fetchall()
        print("\nFixtures:")
        for row in fixtures:
            print(
                "  "
                f"node={row['node_address']} mac={row['mac_address']} "
                f"code={row['code']} name={row['name']} "
                f"device_key={REDACTED} state={row['state']}"
            )


def _mesh_address(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed <= 0xFFFF:
        raise argparse.ArgumentTypeError("mesh address must be 0..0xffff")
    return parsed


def _bounded_int(name: str, value: str, low: int, high: int) -> int:
    parsed = int(value, 0)
    if not low <= parsed <= high:
        raise argparse.ArgumentTypeError(f"{name} must be {low}..{high}")
    return parsed


def _build_commands(args: argparse.Namespace) -> list[tuple[str, bytes]]:
    commands: list[tuple[str, bytes]] = []
    if args.power:
        commands.append((f"power_{args.power}", power_payload(args.power == "on")))
    if args.cct is not None:
        percent = args.brightness if args.brightness is not None else 100
        commands.append(
            (
                f"cct_{args.cct}k_{percent}pct",
                cct_payload_percent(percent=percent, kelvin=args.cct, gm=args.gm),
            )
        )
    elif args.brightness is not None:
        commands.append(
            (
                f"brightness_{args.brightness}pct",
                brightness_payload_percent(args.brightness),
            )
        )
    return commands


async def _scan() -> None:
    from bleak import BleakScanner

    devices = await BleakScanner.discover(timeout=8.0, return_adv=True)
    for address, (device, adv) in sorted(devices.items()):
        services = ", ".join(adv.service_uuids or [])
        print(f"{address:38} {device.name or '-':20} {services}")


async def _send(address: str, pdus: list[tuple[str, bytes]]) -> None:
    from bleak import BleakClient

    async with BleakClient(address, timeout=12.0) as client:
        for label, pdu in pdus:
            await client.write_gatt_char(MESH_PROXY_IN_UUID, pdu, response=False)
            print(f"sent {label}: {pdu.hex()}")
            await asyncio.sleep(0.05)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="scan BLE devices and exit")
    parser.add_argument(
        "--desktop-db",
        type=Path,
        default=DEFAULT_DESKTOP_DB,
        help="amaran Desktop SQLite DB path",
    )
    parser.add_argument(
        "--list-desktop-fixtures",
        action="store_true",
        help="list mesh and fixture records from the desktop DB",
    )
    parser.add_argument(
        "--load-desktop-keys",
        action="store_true",
        help="load net/app key and node address from the desktop DB",
    )
    parser.add_argument(
        "--fixture-mac",
        help="optional light MAC to load from the desktop DB",
    )
    parser.add_argument("--address", help="BLE address or macOS CoreBluetooth UUID")
    parser.add_argument("--net-key", help="Bluetooth Mesh network key, 32 hex chars")
    parser.add_argument("--app-key", help="Bluetooth Mesh app key, 32 hex chars")
    parser.add_argument("--node-address", type=_mesh_address, help="mesh destination")
    parser.add_argument(
        "--source-address",
        type=_mesh_address,
        default=DEFAULT_SOURCE_ADDRESS,
        help="mesh source",
    )
    parser.add_argument(
        "--iv-index",
        type=lambda value: _bounded_int("iv-index", value, 0, 0xFFFFFFFF),
        default=0,
    )
    parser.add_argument(
        "--sequence",
        type=lambda value: _bounded_int("sequence", value, 0, 0xFFFFFF),
        default=100000,
    )
    parser.add_argument(
        "--ttl", type=lambda value: _bounded_int("ttl", value, 0, 0x7F), default=7
    )
    parser.add_argument("--power", choices=("on", "off"))
    parser.add_argument(
        "--brightness",
        type=lambda value: _bounded_int("brightness", value, 0, 100),
        help="brightness percentage",
    )
    parser.add_argument(
        "--cct",
        type=lambda value: _bounded_int("cct", value, 2300, 10000),
        help="color temperature in kelvin",
    )
    parser.add_argument(
        "--gm",
        type=lambda value: _bounded_int("gm", value, -10, 10),
        default=0,
        help="green/magenta offset, -10..+10",
    )
    parser.add_argument("--send", action="store_true", help="write packets with Bleak")
    args = parser.parse_args()

    if args.list_desktop_fixtures:
        _list_desktop_fixtures(args.desktop_db)
        return

    if args.scan:
        asyncio.run(_scan())
        return

    if args.load_desktop_keys:
        net_key, app_key, node_address, fixture = _load_desktop_fixture(
            args.desktop_db, args.fixture_mac
        )
        args.net_key = args.net_key or net_key
        args.app_key = args.app_key or app_key
        args.node_address = args.node_address if args.node_address is not None else node_address
        print(
            "Loaded desktop fixture: "
            f"node={node_address} mac={fixture['mac_address']} "
            f"code={fixture['code']} name={fixture['name']}"
        )

    if args.node_address is None:
        args.node_address = 0x0002

    commands = _build_commands(args)
    if not commands:
        parser.error("choose at least one of --power, --brightness, or --cct")

    print("Sidus payloads:")
    for label, sidus in commands:
        print(f"  {label}: {sidus.hex()} access={access_payload(sidus).hex()}")

    if not args.net_key or not args.app_key:
        print("\nNo mesh keys supplied; cannot build encrypted proxy PDUs.")
        print("Provisioned Sidus lights ignore raw FF02/7FCB writes.")
        return

    net_key = normalize_hex_key(args.net_key, field="network key")
    app_key = normalize_hex_key(args.app_key, field="app key")
    proxy_pdus: list[tuple[str, bytes]] = []
    sequence = args.sequence
    print("\nMesh Proxy PDUs:")
    for label, sidus in commands:
        pdu = build_mesh_proxy_pdu(
            net_key=net_key,
            app_key=app_key,
            src=args.source_address,
            dst=args.node_address,
            seq=sequence,
            iv_index=args.iv_index,
            sidus_payload=sidus,
            ttl=args.ttl,
        )
        print(f"  seq={sequence:#08x} {label}: {pdu.hex()}")
        proxy_pdus.append((label, pdu))
        sequence += 1

    if args.send:
        if not args.address:
            parser.error("--send requires --address")
        asyncio.run(_send(args.address, proxy_pdus))


if __name__ == "__main__":
    main()
