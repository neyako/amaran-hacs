"""Imported fixture selection tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace
import types
import unittest

from custom_components.amaran import _active_fixtures, async_migrate_entry
from custom_components.amaran.const import (
    CONF_APP_KEY,
    CONF_BATTERY_CAPABLE,
    CONF_BLE_MAC,
    CONF_FIXTURE_CATALOG,
    CONF_FIXTURES,
    CONF_MODEL,
    CONF_NAME,
    CONF_NET_KEY,
    CONF_NODE_ADDRESS,
    CONF_PROXY_CANDIDATES,
    CONF_PROXY_ADDRESS,
    CONF_SELECTED_FIXTURE_IDS,
    CONF_SOURCE_ADDRESS,
    CONF_SUPPORTED_COLOR_MODES,
)
from custom_components.amaran.discovery import bluetooth_discovery_enabled
from custom_components.amaran.fixtures import (
    fixture_device_identifier,
    fixture_entry_data,
    fixture_for_unique_id,
    fixture_selection_choices,
    fixture_unique_id,
)

NET_KEY = "00112233445566778899aabbccddeeff"
APP_KEY = "ffeeddccbbaa99887766554433221100"


class FixtureSelectionTest(unittest.TestCase):
    def test_selection_choices_identify_fixture_and_node(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        pano = _fixture("Pano", "Pano 60c", "AA:BB:CC:DD:EE:02", 0x000C)

        choices = fixture_selection_choices([ace, pano])

        self.assertEqual(
            choices[fixture_unique_id(ace)],
            "Ace (Ace 25c) - Brightness, Color temperature, Color/HSI, Battery",
        )
        self.assertIs(
            fixture_for_unique_id([ace, pano], fixture_unique_id(pano)),
            pano,
        )

    def test_runtime_defaults_to_one_imported_fixture(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        pano = _fixture("Pano", "Pano 60c", "AA:BB:CC:DD:EE:02", 0x000C)
        entry = SimpleNamespace(
            data={
                CONF_FIXTURE_CATALOG: [ace, pano],
                CONF_FIXTURES: [ace],
            },
            options={},
        )

        self.assertEqual(_active_fixtures(entry), [ace])

    def test_legacy_group_only_activates_selected_fixtures(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        pano = _fixture("Pano", "Pano 60c", "AA:BB:CC:DD:EE:02", 0x000C)
        sixty = _fixture("60x", "60x S", "AA:BB:CC:DD:EE:03", 0x000D)
        entry = SimpleNamespace(
            data={
                CONF_FIXTURE_CATALOG: [ace, pano, sixty],
                CONF_FIXTURES: [ace],
            },
            options={
                CONF_SELECTED_FIXTURE_IDS: [
                    fixture_unique_id(ace),
                    fixture_unique_id(pano),
                ]
            },
        )

        self.assertEqual(_active_fixtures(entry), [ace, pano])

    def test_import_selection_builds_one_direct_fixture_entry(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        pano = _fixture("Pano", "Pano 60c", "AA:BB:CC:DD:EE:02", 0x000C)
        import_data = {
            CONF_FIXTURE_CATALOG: [ace, pano],
            CONF_FIXTURES: [ace, pano],
            CONF_SOURCE_ADDRESS: 0x000F,
            CONF_PROXY_CANDIDATES: [
                ace[CONF_BLE_MAC],
                pano[CONF_BLE_MAC],
            ],
        }

        data = fixture_entry_data(import_data, pano)

        self.assertEqual(data[CONF_NAME], "Pano")
        self.assertEqual(data[CONF_NODE_ADDRESS], 0x000C)
        self.assertEqual(data[CONF_SOURCE_ADDRESS], 0x000F)
        self.assertEqual(len(data[CONF_PROXY_CANDIDATES]), 2)
        self.assertNotIn(CONF_FIXTURE_CATALOG, data)
        self.assertNotIn(CONF_FIXTURES, data)

    def test_device_identifier_prefers_fixture_mac(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)

        self.assertEqual(
            fixture_device_identifier(ace),
            "AA:BB:CC:DD:EE:01",
        )


class DiscoveryConfigTest(unittest.TestCase):
    def test_bluetooth_discovery_disabled_by_default(self) -> None:
        hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(async_entries=lambda domain: []),
        )

        self.assertFalse(bluetooth_discovery_enabled(hass))

    def test_bluetooth_discovery_stays_disabled_when_option_is_present(self) -> None:
        entry = SimpleNamespace(data={}, options={"enable_discovery": True})
        hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(async_entries=lambda domain: [entry]),
        )

        self.assertFalse(bluetooth_discovery_enabled(hass))


class GroupedEntryMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_single_ace_entry_backfills_battery_capability(self) -> None:
        entry = SimpleNamespace(
            entry_id="ace",
            data={
                CONF_APP_KEY: APP_KEY,
                CONF_BLE_MAC: "AA:BB:CC:DD:EE:01",
                CONF_NAME: "Amaran Ace 25C",
                CONF_NET_KEY: NET_KEY,
                CONF_NODE_ADDRESS: 0x000B,
            },
            options={},
            title="Amaran Ace 25C",
            unique_id="aa_bb_cc_dd_ee_01",
            version=2,
            minor_version=1,
        )
        manager = FakeConfigEntries([entry])
        hass = SimpleNamespace(config_entries=manager)

        migrated = await async_migrate_entry(hass, entry)

        self.assertTrue(migrated)
        self.assertTrue(entry.data[CONF_BATTERY_CAPABLE])
        self.assertEqual(entry.minor_version, 3)

    async def test_existing_entry_recomputes_stale_color_modes(self) -> None:
        entry = SimpleNamespace(
            entry_id="verge-max",
            data={
                CONF_APP_KEY: APP_KEY,
                CONF_BLE_MAC: "AA:BB:CC:DD:EE:03",
                CONF_MODEL: "amaran Verge Max",
                CONF_NAME: "Verge Max",
                CONF_NET_KEY: NET_KEY,
                CONF_NODE_ADDRESS: 0x000D,
                CONF_SUPPORTED_COLOR_MODES: ["brightness"],
            },
            options={},
            title="Verge Max",
            unique_id="aa_bb_cc_dd_ee_03",
            version=2,
            minor_version=2,
        )
        manager = FakeConfigEntries([entry])
        hass = SimpleNamespace(config_entries=manager)

        migrated = await async_migrate_entry(hass, entry)

        self.assertTrue(migrated)
        self.assertEqual(entry.data[CONF_SUPPORTED_COLOR_MODES], ["color_temp"])
        self.assertEqual(entry.minor_version, 3)

    async def test_grouped_entry_splits_into_fixture_entries(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        pano = _fixture("Pano", "Pano 60c", "AA:BB:CC:DD:EE:02", 0x000C)
        entry = SimpleNamespace(
            entry_id="grouped",
            data={
                CONF_FIXTURE_CATALOG: [ace, pano],
                CONF_FIXTURES: [ace, pano],
                CONF_SOURCE_ADDRESS: 0x000F,
                CONF_PROXY_CANDIDATES: [
                    ace[CONF_BLE_MAC],
                    pano[CONF_BLE_MAC],
                ],
                CONF_PROXY_ADDRESS: ace[CONF_BLE_MAC],
            },
            options={},
            title="Amaran Sidus Mesh",
            unique_id="mesh-old",
            version=1,
            minor_version=3,
        )
        manager = FakeConfigEntries([entry])
        hass = SimpleNamespace(config_entries=manager)
        _install_config_entry_stub()

        migrated = await async_migrate_entry(hass, entry)

        self.assertTrue(migrated)
        self.assertEqual(entry.title, "Ace")
        self.assertEqual(entry.unique_id, fixture_unique_id(ace))
        self.assertEqual(entry.version, 2)
        self.assertEqual(entry.minor_version, 3)
        self.assertEqual(entry.data[CONF_PROXY_ADDRESS], "")
        self.assertNotIn(CONF_FIXTURE_CATALOG, entry.data)
        self.assertNotIn(CONF_FIXTURES, entry.data)
        self.assertEqual(len(manager.flow.calls), 1)
        split_data = manager.flow.calls[0]["data"]
        self.assertEqual(split_data[CONF_NAME], "Pano")
        self.assertNotIn(CONF_FIXTURE_CATALOG, split_data)
        self.assertNotIn(CONF_FIXTURES, split_data)


class FakeFlow:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def async_init(self, domain: str, *, context: dict, data: dict) -> dict:
        self.calls.append({"domain": domain, "context": context, "data": data})
        return {"type": "create_entry"}


class FakeConfigEntries:
    def __init__(self, entries: list[SimpleNamespace]) -> None:
        self._entries = entries
        self.flow = FakeFlow()

    def async_entries(self, domain: str) -> list[SimpleNamespace]:
        return self._entries

    def async_update_entry(self, entry: SimpleNamespace, **changes: object) -> None:
        for key, value in changes.items():
            setattr(entry, key, value)


def _install_config_entry_stub() -> None:
    homeassistant = sys.modules.setdefault(
        "homeassistant", types.ModuleType("homeassistant")
    )
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries",
        types.ModuleType("homeassistant.config_entries"),
    )
    config_entries.SOURCE_IMPORT = "import"
    homeassistant.config_entries = config_entries


def _fixture(name: str, model: str, mac: str, node_address: int) -> dict:
    return {
        CONF_APP_KEY: APP_KEY,
        CONF_BLE_MAC: mac,
        CONF_MODEL: model,
        CONF_NAME: name,
        CONF_NET_KEY: NET_KEY,
        CONF_NODE_ADDRESS: node_address,
        CONF_BATTERY_CAPABLE: "25c" in model.lower(),
    }


if __name__ == "__main__":
    unittest.main()
