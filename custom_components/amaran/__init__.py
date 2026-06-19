"""Amaran Sidus custom integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .const import (
    CONF_ADDRESS,
    CONF_BATTERY_CAPABLE,
    CONF_BLE_MAC,
    CONF_FIXTURE_CATALOG,
    CONF_FIXTURES,
    CONF_MODEL,
    CONF_NAME,
    CONF_PROXY_ADDRESS,
    CONF_PROXY_MAC,
    CONF_PROXY_SELECTION,
    CONF_SELECTED_FIXTURE_IDS,
    CONF_SUPPORTED_COLOR_MODES,
    DEFAULT_POWER_STATUS_CAPTURE_SECONDS,
    DEFAULT_PRESENCE_SCAN_DURATION_SECONDS,
    DEFAULT_PRESENCE_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MANUFACTURER,
    PROXY_SELECTION_AUTO,
    SERVICE_FIELD_CAPTURE_SECONDS,
    SERVICE_FIELD_ENTRY_ID,
    SERVICE_FIELD_NODE_ADDRESS,
    SERVICE_REQUEST_POWER_STATUS,
)
from .fixtures import (
    fixture_device_identifier,
    fixture_entry_data,
    fixture_unique_id,
    is_battery_capable_light,
    recompute_color_modes,
)
from .product_catalog import product_catalog

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate grouped mesh entries into fixture-specific config entries."""

    if entry.version > 2:
        return False
    if entry.version == 2 and entry.minor_version >= 3:
        return True

    data = dict(entry.data)
    _normalize_legacy_proxy_settings(data, entry.options)
    grouped = bool(data.get(CONF_FIXTURE_CATALOG) or data.get(CONF_FIXTURES))
    fixtures = _fixtures_for_entry(entry)
    if grouped and not fixtures:
        _LOGGER.error(
            "Grouped amaran entry %s has no active fixtures; delete and re-add it",
            entry.entry_id,
        )
        return False
    existing_fixture_ids = {
        fixture_unique_id(fixture)
        for candidate in hass.config_entries.async_entries(DOMAIN)
        if candidate.entry_id != entry.entry_id
        for fixture in _fixtures_for_entry(candidate)
    }
    migration_fixtures = [
        fixture
        for fixture in fixtures
        if fixture_unique_id(fixture) not in existing_fixture_ids
    ]
    if grouped and not migration_fixtures:
        _LOGGER.error(
            "Grouped amaran entry %s duplicates existing fixture entries; "
            "delete the grouped entry",
            entry.entry_id,
        )
        return False

    primary = migration_fixtures[0] if grouped else data
    primary_data = _fixture_entry_data_with_capabilities(data, primary)
    _migrate_fixture_device_identifier(hass, entry, primary_data)
    options = dict(entry.options)
    options.pop(CONF_SELECTED_FIXTURE_IDS, None)
    hass.config_entries.async_update_entry(
        entry,
        data=primary_data,
        options=options,
        title=str(primary_data[CONF_NAME]),
        unique_id=fixture_unique_id(primary_data),
        version=2,
        minor_version=3,
    )

    if grouped:
        from homeassistant import config_entries

        for fixture in migration_fixtures[1:]:
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data=_fixture_entry_data_with_capabilities(data, fixture),
            )
        _LOGGER.warning(
            "Migrated grouped amaran entry to %s light entries",
            len(migration_fixtures),
        )
    return True


def _fixture_entry_data_with_capabilities(
    import_data: dict[str, Any], fixture: dict[str, Any]
) -> dict[str, Any]:
    """Backfill stable capabilities missing from older fixture entries."""

    data = fixture_entry_data(import_data, fixture)
    data.setdefault(CONF_BATTERY_CAPABLE, is_battery_capable_light(data))
    recomputed = recompute_color_modes(data)
    if recomputed:
        data[CONF_SUPPORTED_COLOR_MODES] = list(recomputed)
    return data


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amaran Sidus from a config entry."""

    from homeassistant.components import bluetooth
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
    from homeassistant.core import callback

    from .client import (
        AmaranSidusClient,
        get_mesh_network,
    )

    fixtures = [dict(entry.data)]
    _migrate_fixture_device_identifier(hass, entry, fixtures[0])
    context_entries, context_fixtures = _matching_mesh_context(hass, entry, fixtures)
    add_executor_job = getattr(hass, "async_add_executor_job", None)
    if callable(add_executor_job):
        await add_executor_job(product_catalog)
    mesh_network = get_mesh_network(
        hass,
        entry,
        fixtures,
        context_entries=context_entries,
        context_fixtures=context_fixtures,
    )
    clients = [
        AmaranSidusClient(hass, entry, fixture, mesh_network=mesh_network)
        for fixture in fixtures
    ]

    for client in clients:
        await client.async_setup()

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = clients
    _async_register_services(hass)

    @callback
    def _async_discovered_device(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Wake shared BLE connection when any candidate advertises."""

        _LOGGER.debug(
            "Sidus BLE advertisement seen address=%s change=%s",
            service_info.address,
            change,
        )
        mesh_network.mark_proxy_advertisement_seen(service_info)
        for client in clients:
            client.mark_advertisement_seen(service_info)

    for callback_address in mesh_network.proxy_candidates:
        entry.async_on_unload(
            bluetooth.async_register_callback(
                hass,
                _async_discovered_device,
                {"address": callback_address},
                bluetooth.BluetoothScanningMode.ACTIVE,
                scan_interval=DEFAULT_PRESENCE_SCAN_INTERVAL_SECONDS,
                scan_duration=DEFAULT_PRESENCE_SCAN_DURATION_SECONDS,
            )
        )

    platforms = (Platform.LIGHT, Platform.SENSOR)
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    _migrate_fixture_device_identifier(hass, entry, fixtures[0])
    from .sensor import async_disable_transport_sensors

    await async_disable_transport_sensors(hass, clients)

    mesh_network.async_start_warmup("startup")

    async def _async_stop(_event: object) -> None:
        await mesh_network.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload an entry after options change."""

    await hass.config_entries.async_reload(entry.entry_id)


def _active_fixtures(entry: ConfigEntry) -> list[dict] | None:
    """Return selected fixtures from an imported mesh catalog."""

    active = entry.data.get(CONF_FIXTURES)
    catalog = entry.data.get(CONF_FIXTURE_CATALOG)
    selected_ids = entry.options.get(CONF_SELECTED_FIXTURE_IDS)
    if not catalog or not selected_ids:
        return active
    selected = set(selected_ids)
    return [
        fixture for fixture in catalog if fixture_unique_id(fixture) in selected
    ]


def _fixtures_for_entry(entry: ConfigEntry) -> list[dict]:
    """Return direct fixture data or active fixtures from a legacy group."""

    active = _active_fixtures(entry)
    return active if active is not None else [dict(entry.data)]


def _normalize_legacy_proxy_settings(data: dict, options: dict) -> None:
    """Remove old implicit per-fixture targets while preserving proxy_mac."""

    if CONF_PROXY_MAC in options or CONF_PROXY_MAC in data:
        return
    data[CONF_PROXY_ADDRESS] = ""
    data[CONF_PROXY_SELECTION] = PROXY_SELECTION_AUTO


def _migrate_fixture_device_identifier(
    hass: HomeAssistant, entry: ConfigEntry, fixture: dict
) -> None:
    """Keep existing fixture device while removing transport-shaped identity."""

    try:
        from homeassistant.helpers import device_registry as dr
    except ImportError:
        return

    if not hasattr(dr, "async_get") or not hasattr(
        dr, "async_entries_for_config_entry"
    ):
        return
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    if not devices:
        return
    desired_identifiers = {(DOMAIN, fixture_device_identifier(fixture))}
    fixture_address = str(
        fixture.get(CONF_BLE_MAC) or fixture.get(CONF_ADDRESS) or ""
    ).lower()
    matching = [
        device
        for device in devices
        if desired_identifiers == set(device.identifiers)
    ] or [
        device
        for device in devices
        if fixture_address
        and any(
            fixture_address in str(identifier).lower()
            for identifier in device.identifiers
        )
    ]
    if len(matching) != 1 and len(devices) == 1:
        matching = devices
    if len(matching) != 1:
        _LOGGER.warning(
            "Could not migrate light device identifier entry_id=%s devices=%s",
            entry.entry_id,
            len(devices),
        )
        return
    registry.async_update_device(
        matching[0].id,
        new_identifiers=desired_identifiers,
        manufacturer=MANUFACTURER,
        model=str(fixture.get(CONF_MODEL) or entry.title or "amaran light"),
        name=str(fixture.get(CONF_NAME) or entry.title),
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Amaran Sidus config entry."""

    from homeassistant.const import Platform

    platforms = (Platform.LIGHT, Platform.SENSOR)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        clients = hass.data[DOMAIN].pop(entry.entry_id, None) or []
        if clients:
            from .client import async_release_mesh_network

            await async_release_mesh_network(hass, entry, clients[0]._mesh_network)
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_REQUEST_POWER_STATUS)
    return unload_ok


def _async_register_services(hass: HomeAssistant) -> None:
    """Register debug-only services once."""

    if hass.services.has_service(DOMAIN, SERVICE_REQUEST_POWER_STATUS):
        return

    import voluptuous as vol
    from homeassistant.exceptions import HomeAssistantError

    async def _async_request_power_status(call: Any) -> None:
        try:
            client = _resolve_power_status_client(hass, call.data)
            capture_seconds = float(
                call.data.get(
                    SERVICE_FIELD_CAPTURE_SECONDS,
                    DEFAULT_POWER_STATUS_CAPTURE_SECONDS,
                )
            )
            await client.async_request_power_status(capture_seconds=capture_seconds)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to request Amaran power status: {err!r}"
            ) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_REQUEST_POWER_STATUS,
        _async_request_power_status,
        schema=vol.Schema(
            {
                vol.Optional(SERVICE_FIELD_ENTRY_ID): str,
                vol.Optional(SERVICE_FIELD_NODE_ADDRESS): vol.Any(str, int),
                vol.Optional(
                    SERVICE_FIELD_CAPTURE_SECONDS,
                    default=DEFAULT_POWER_STATUS_CAPTURE_SECONDS,
                ): vol.Coerce(float),
            }
        ),
    )


def _resolve_power_status_client(hass: HomeAssistant, data: dict[str, Any]) -> Any:
    """Resolve one loaded light for the power-status debug service."""

    from homeassistant.exceptions import HomeAssistantError

    entry_id = str(data.get(SERVICE_FIELD_ENTRY_ID) or "").strip()
    node_address = _parse_service_node_address(data.get(SERVICE_FIELD_NODE_ADDRESS))
    domain_data = hass.data.get(DOMAIN, {})
    if entry_id:
        clients = list(domain_data.get(entry_id) or [])
    else:
        clients = [
            client
            for entry_clients in domain_data.values()
            for client in (entry_clients or [])
        ]
    if node_address is not None:
        clients = [
            client
            for client in clients
            if int(getattr(client, "node_address", -1)) == node_address
        ]
    if len(clients) != 1:
        raise HomeAssistantError(
            "Select exactly one Amaran light with entry_id and/or node_address"
        )
    return clients[0]


def _parse_service_node_address(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return _validate_service_node_address(value)
    text = str(value).strip().lower()
    base = 16 if text.startswith("0x") else 10
    return _validate_service_node_address(int(text, base))


def _validate_service_node_address(value: int) -> int:
    if not 0 <= int(value) <= 0xFFFF:
        raise ValueError("node_address must be a 16-bit mesh address")
    return int(value)


def _matching_mesh_context(
    hass: HomeAssistant,
    entry: ConfigEntry,
    fixtures: list[dict],
) -> tuple[list[ConfigEntry], list[dict]]:
    """Return legacy/current entries and fixtures sharing one mesh context."""

    from .client import mesh_network_key

    context_key = mesh_network_key(entry, fixtures[0])
    entries: list[ConfigEntry] = []
    merged: list[dict] = []
    known_fixture_ids: set[str] = set()
    for candidate in hass.config_entries.async_entries(DOMAIN):
        candidate_fixtures = _fixtures_for_entry(candidate)
        if not candidate_fixtures:
            continue
        if mesh_network_key(candidate, candidate_fixtures[0]) != context_key:
            continue
        entries.append(candidate)
        for fixture in candidate_fixtures:
            fixture_id = fixture_unique_id(fixture)
            if fixture_id not in known_fixture_ids:
                merged.append(fixture)
                known_fixture_ids.add(fixture_id)
    return entries, merged
