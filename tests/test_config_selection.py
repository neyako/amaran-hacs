"""Imported fixture selection tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace
import types
import unittest
from unittest import mock

from custom_components.amaran import _active_fixtures, async_migrate_entry
from custom_components.amaran.state_store import _state_store_key
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
from custom_components.amaran.fixtures import (
    fixture_device_identifier,
    fixture_entries_for_selection,
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
            "Ace (Ace 25c) - Brightness, White temperature, Color, Battery",
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

    def test_selection_fan_out_returns_entry_per_selected_in_catalog_order(
        self,
    ) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        pano = _fixture("Pano", "Pano 60c", "AA:BB:CC:DD:EE:02", 0x000C)
        sixty = _fixture("60x", "60x S", "AA:BB:CC:DD:EE:03", 0x000D)
        import_data = {
            CONF_FIXTURE_CATALOG: [ace, pano, sixty],
            CONF_FIXTURES: [ace, pano, sixty],
            CONF_SOURCE_ADDRESS: 0x000F,
        }

        entries = fixture_entries_for_selection(
            import_data,
            [ace, pano, sixty],
            [fixture_unique_id(pano), fixture_unique_id(ace)],
        )

        self.assertEqual([entry[CONF_NAME] for entry in entries], ["Ace", "Pano"])
        for entry in entries:
            self.assertNotIn(CONF_FIXTURE_CATALOG, entry)
            self.assertNotIn(CONF_FIXTURES, entry)

    def test_selection_fan_out_skips_already_configured(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        pano = _fixture("Pano", "Pano 60c", "AA:BB:CC:DD:EE:02", 0x000C)
        sixty = _fixture("60x", "60x S", "AA:BB:CC:DD:EE:03", 0x000D)
        import_data = {
            CONF_FIXTURE_CATALOG: [ace, pano, sixty],
            CONF_FIXTURES: [ace, pano, sixty],
        }

        entries = fixture_entries_for_selection(
            import_data,
            [ace, pano, sixty],
            [
                fixture_unique_id(ace),
                fixture_unique_id(pano),
                fixture_unique_id(sixty),
            ],
            skip_ids=frozenset({fixture_unique_id(ace)}),
        )

        self.assertEqual([entry[CONF_NAME] for entry in entries], ["Pano", "60x"])

    def test_selection_fan_out_dedupes_repeated_ids(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        pano = _fixture("Pano", "Pano 60c", "AA:BB:CC:DD:EE:02", 0x000C)
        import_data = {
            CONF_FIXTURE_CATALOG: [ace, pano],
            CONF_FIXTURES: [ace, pano],
        }

        entries = fixture_entries_for_selection(
            import_data,
            [ace, pano],
            [
                fixture_unique_id(ace),
                fixture_unique_id(ace),
                fixture_unique_id(pano),
            ],
        )

        self.assertEqual([entry[CONF_NAME] for entry in entries], ["Ace", "Pano"])

    def test_selection_fan_out_empty_selection_returns_empty(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)
        import_data = {
            CONF_FIXTURE_CATALOG: [ace],
            CONF_FIXTURES: [ace],
        }

        self.assertEqual(
            fixture_entries_for_selection(import_data, [ace], []),
            [],
        )

    def test_device_identifier_prefers_fixture_mac(self) -> None:
        ace = _fixture("Ace", "Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B)

        self.assertEqual(
            fixture_device_identifier(ace),
            "AA:BB:CC:DD:EE:01",
        )


class GroupedEntryMigrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.registry = FakeEntityRegistry()
        self.stores: dict[str, dict] = {}
        registry_module = types.ModuleType("homeassistant.helpers.entity_registry")
        registry_module.async_get = lambda hass: self.registry
        registry_module.async_entries_for_config_entry = (
            lambda registry, entry_id: [
                entity for entity in registry.entities if entity.config_entry_id == entry_id
            ]
        )
        stores = self.stores

        class FakeStore:
            def __init__(self, hass, version, key) -> None:
                self.key = key

            async def async_load(self):
                return stores.get(self.key)

            async def async_save(self, data) -> None:
                stores[self.key] = data

            async def async_remove(self) -> None:
                stores.pop(self.key, None)

        patches = [
            mock.patch.dict(
                sys.modules, {"homeassistant.helpers.entity_registry": registry_module}
            ),
            mock.patch("custom_components.amaran.state_store.Store", FakeStore),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

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
        hass = SimpleNamespace(
            config_entries=manager, async_add_executor_job=_run_in_executor
        )

        migrated = await async_migrate_entry(hass, entry)

        self.assertTrue(migrated)
        self.assertTrue(entry.data[CONF_BATTERY_CAPABLE])
        self.assertEqual(entry.minor_version, 4)

    async def test_moves_only_the_old_default_source_address(self) -> None:
        light = {CONF_BLE_MAC: "AA:BB:CC:DD:EE:01", CONF_NODE_ADDRESS: 0x000B}
        entries = [
            SimpleNamespace(
                entry_id=f"light-{source}",
                data={**light, CONF_SOURCE_ADDRESS: source},
                options={},
                version=2,
                minor_version=3,
            )
            for source in (0x000F, 0x0020)
        ]
        self.registry.add("light-15", "AA:BB:CC:DD:EE:01_node_11_src_15")
        self.registry.add("light-15", "AA:BB:CC:DD:EE:01_node_11_src_15_battery")
        old_client = SimpleNamespace(data=light, node_address=0x000B, source_address=15)
        new_client = SimpleNamespace(data=light, node_address=0x000B, source_address=0x7FFF)
        self.stores[_state_store_key(old_client)] = {"power": True}
        hass = SimpleNamespace(config_entries=FakeConfigEntries(entries))

        for entry in entries:
            self.assertTrue(await async_migrate_entry(hass, entry))

        self.assertEqual(
            [(entry.data[CONF_SOURCE_ADDRESS], entry.minor_version) for entry in entries],
            [(0x7FFF, 4), (0x0020, 4)],
        )
        self.assertEqual(
            [entity.unique_id for entity in self.registry.entities],
            [
                "AA:BB:CC:DD:EE:01_node_11_src_32767",
                "AA:BB:CC:DD:EE:01_node_11_src_32767_battery",
            ],
        )
        self.assertEqual(self.stores, {_state_store_key(new_client): {"power": True}})

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
        hass = SimpleNamespace(
            config_entries=manager, async_add_executor_job=_run_in_executor
        )

        migrated = await async_migrate_entry(hass, entry)

        self.assertTrue(migrated)
        self.assertEqual(entry.data[CONF_SUPPORTED_COLOR_MODES], ["color_temp"])
        self.assertEqual(entry.minor_version, 4)

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
        hass = SimpleNamespace(
            config_entries=manager, async_add_executor_job=_run_in_executor
        )
        _install_config_entry_stub()

        migrated = await async_migrate_entry(hass, entry)

        self.assertTrue(migrated)
        self.assertEqual(entry.title, "Ace")
        self.assertEqual(entry.unique_id, fixture_unique_id(ace))
        self.assertEqual(entry.version, 2)
        self.assertEqual(entry.minor_version, 4)
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


class FakeEntityRegistry:
    def __init__(self) -> None:
        self.entities: list[SimpleNamespace] = []

    def add(self, entry_id: str, unique_id: str) -> None:
        self.entities.append(
            SimpleNamespace(
                entity_id=f"light.{len(self.entities)}",
                unique_id=unique_id,
                config_entry_id=entry_id,
            )
        )

    def async_update_entity(self, entity_id: str, *, new_unique_id: str) -> None:
        for entity in self.entities:
            if entity.entity_id == entity_id:
                entity.unique_id = new_unique_id


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



async def _run_in_executor(func, *args):
    return func(*args)

if __name__ == "__main__":
    unittest.main()
