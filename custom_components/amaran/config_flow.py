"""Config flow for amaran lights."""

from __future__ import annotations

from functools import partial
from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .cloud import CloudAuthError, CloudError, async_fetch_import_payload
from .const import (
    CONF_ACCOUNT,
    CONF_ADDRESS,
    CONF_APP_KEY,
    CONF_BLE_MAC,
    CONF_ENABLE_PRESENCE_CHECKING,
    CONF_FIXTURE_CATALOG,
    CONF_IMPORT_JSON,
    CONF_IV_INDEX,
    CONF_NAME,
    CONF_NET_KEY,
    CONF_NODE_ADDRESS,
    CONF_PASSWORD,
    CONF_PROXY_ADDRESS,
    CONF_PROXY_CANDIDATES,
    CONF_PROXY_MAC,
    CONF_PROXY_SELECTION,
    CONF_SELECTED_FIXTURE_IDS,
    CONF_SEQUENCE,
    CONF_SOURCE_ADDRESS,
    CONF_TRANSPORT_MODE,
    CONF_TTL,
    DEFAULT_ENABLE_PRESENCE_CHECKING,
    DEFAULT_IV_INDEX,
    DEFAULT_NAME,
    DEFAULT_NODE_ADDRESS,
    DEFAULT_SEQUENCE,
    DEFAULT_SOURCE_ADDRESS,
    DEFAULT_TTL,
    DOMAIN,
    PROXY_SELECTION_AUTO,
    PROXY_SELECTION_MANUAL,
    TRANSPORT_MODE_PERSISTENT,
)
from .discovery import bluetooth_discovery_enabled
from .fixtures import (
    FixtureImport,
    fixture_entries_for_selection,
    fixture_selection_choices,
    fixture_unique_id,
    load_fixture_import_json,
    load_fixture_import_payload,
)
from .protocol import normalize_hex_key

ADVANCED = "advanced"


def _int_from_user(value: Any) -> int:
    if isinstance(value, int):
        return value
    return int(str(value).strip(), 0)


def _bool_from_user(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("", "0", "false", "off", "no"):
            return False
        if normalized in ("1", "true", "on", "yes"):
            return True
    return bool(value)


def _validate_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)

    data[CONF_NAME] = str(data.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
    data[CONF_ADDRESS] = str(data[CONF_ADDRESS]).strip()
    if not data[CONF_ADDRESS]:
        raise ValueError(CONF_ADDRESS)

    if ble_mac := data.get(CONF_BLE_MAC):
        data[CONF_BLE_MAC] = str(ble_mac).strip()

    try:
        data[CONF_NODE_ADDRESS] = _int_from_user(data[CONF_NODE_ADDRESS])
    except ValueError as err:
        raise ValueError(CONF_NODE_ADDRESS) from err
    _validate_advanced(data)
    if not 1 <= data[CONF_NODE_ADDRESS] <= 0x03FF:
        raise ValueError(CONF_NODE_ADDRESS)
    if data[CONF_NODE_ADDRESS] == data[CONF_SOURCE_ADDRESS]:
        raise ValueError(CONF_SOURCE_ADDRESS)
    for key, field in ((CONF_NET_KEY, "network key"), (CONF_APP_KEY, "app key")):
        try:
            data[key] = normalize_hex_key(str(data[key]), field=field).hex()
        except ValueError as err:
            raise ValueError(key) from err
    data[CONF_PROXY_CANDIDATES] = _proxy_candidates_from_fixtures([data])
    return data


def _validate_advanced(data: dict[str, Any]) -> None:
    """Normalize the advanced connection fields in place."""

    _normalize_proxy_settings(data)
    for key, default, maximum, minimum in (
        (CONF_SOURCE_ADDRESS, DEFAULT_SOURCE_ADDRESS, 0x03FF, 1),
        (CONF_IV_INDEX, DEFAULT_IV_INDEX, 0xFFFFFFFF, 0),
        (CONF_SEQUENCE, DEFAULT_SEQUENCE, 0xFFFFFF, 0),
        (CONF_TTL, DEFAULT_TTL, 0x7F, 0),
    ):
        try:
            data[key] = _int_from_user(data.get(key, default))
        except ValueError as err:
            raise ValueError(key) from err
        if not minimum <= data[key] <= maximum:
            raise ValueError(key)


def _finalize_import_data(
    user_input: dict[str, Any], imported: FixtureImport
) -> dict[str, Any]:
    data = dict(user_input)
    _validate_advanced(data)
    data[CONF_FIXTURE_CATALOG] = imported.fixtures
    data[CONF_PROXY_CANDIDATES] = _proxy_candidates_from_fixtures(
        imported.fixtures,
        extra=data[CONF_PROXY_MAC],
    )
    data.pop(CONF_IMPORT_JSON, None)
    return data


def _proxy_candidates_from_fixtures(
    fixtures: list[dict[str, Any]], *, extra: str = ""
) -> list[str]:
    candidates: list[str] = []
    for fixture in fixtures:
        for key in (CONF_BLE_MAC, CONF_ADDRESS):
            value = str(fixture.get(key) or "").strip()
            if value:
                candidates.append(value)
    if extra:
        candidates.append(extra)
    return list(dict.fromkeys(candidates))


def _normalize_proxy_settings(data: dict[str, Any]) -> None:
    """Store optional manual proxy MAC and force one persistent mesh session."""

    proxy_mac = str(
        data.get(CONF_PROXY_MAC) or data.get(CONF_PROXY_ADDRESS) or ""
    ).strip()
    data[CONF_PROXY_MAC] = proxy_mac
    data[CONF_PROXY_ADDRESS] = proxy_mac
    data[CONF_PROXY_SELECTION] = (
        PROXY_SELECTION_MANUAL if proxy_mac else PROXY_SELECTION_AUTO
    )
    data[CONF_TRANSPORT_MODE] = TRANSPORT_MODE_PERSISTENT


def _import_error(err: ValueError) -> str:
    field = err.args[0] if err.args else ""
    if field == CONF_IMPORT_JSON:
        return "invalid_json"
    if field == "fixtures":
        return "no_lights"
    return "invalid_advanced"


def _address_conflicts(
    catalog: list[dict[str, Any]], source_address: int
) -> dict[str, str]:
    """Return lights using the address Home Assistant sends from, by ID."""

    return {
        fixture_unique_id(light): str(light.get(CONF_NAME) or "amaran light")
        for light in catalog
        if int(light.get(CONF_NODE_ADDRESS) or 0) == source_address
    }


class AmaranSidusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an amaran config flow."""

    VERSION = 2
    MINOR_VERSION = 3

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""

        return AmaranSidusOptionsFlow()

    def __init__(self) -> None:
        self._pending_import: dict[str, Any] | None = None
        self._import_source = ""

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> config_entries.ConfigFlowResult:
        """Handle Bluetooth discovery."""

        if not bluetooth_discovery_enabled(self.hass):
            return self.async_abort(reason="bluetooth_discovery_disabled")
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose how to add lights."""

        return self.async_show_menu(
            step_id="user", menu_options=["cloud", "import_json", "manual"]
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Read lights from the amaran account; credentials are not stored."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                payload = await async_fetch_import_payload(
                    async_get_clientsession(self.hass),
                    str(user_input[CONF_ACCOUNT]).strip(),
                    str(user_input[CONF_PASSWORD]),
                    self.hass.config.country,
                )
                imported = await self.hass.async_add_executor_job(
                    partial(load_fixture_import_payload, payload, source="account")
                )
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except (CloudError, ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "no_lights"
            else:
                self._pending_import = _finalize_import_data({}, imported)
                self._import_source = "your amaran account"
                return await self.async_step_select_fixture()

        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT): TextSelector(
                        TextSelectorConfig(autocomplete="username")
                    ),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_import_json(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle a pasted amaran Desktop export."""

        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_IMPORT_JSON: user_input[CONF_IMPORT_JSON],
                **user_input.get(ADVANCED, {}),
            }
            try:
                imported = await self.hass.async_add_executor_job(
                    load_fixture_import_json, str(data[CONF_IMPORT_JSON])
                )
                self._pending_import = _finalize_import_data(data, imported)
            except ValueError as err:
                errors["base"] = _import_error(err)
            else:
                self._import_source = "your export"
                return await self.async_step_select_fixture()

        return self.async_show_form(
            step_id="import_json",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IMPORT_JSON): TextSelector(
                        TextSelectorConfig(multiline=True)
                    ),
                    vol.Required(ADVANCED): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_SOURCE_ADDRESS,
                                    default=f"0x{DEFAULT_SOURCE_ADDRESS:04x}",
                                ): str,
                                vol.Optional(CONF_PROXY_MAC, default=""): str,
                                vol.Required(
                                    CONF_IV_INDEX, default=str(DEFAULT_IV_INDEX)
                                ): str,
                                vol.Required(
                                    CONF_SEQUENCE, default=str(DEFAULT_SEQUENCE)
                                ): str,
                                vol.Required(CONF_TTL, default=str(DEFAULT_TTL)): str,
                            }
                        ),
                        {"collapsed": True},
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_import(
        self, import_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Create an extra light selected in the same setup."""

        return await self._async_create_fixture_entry(dict(import_data))

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle manual setup."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _validate_user_input(user_input)
            except ValueError as err:
                errors["base"] = "invalid_input"
                if err.args:
                    errors[str(err.args[0])] = "invalid_input"
            else:
                return await self._async_create_fixture_entry(data)

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_BLE_MAC, default=""): str,
                    vol.Optional(CONF_PROXY_MAC, default=""): str,
                    vol.Required(
                        CONF_NODE_ADDRESS, default=str(DEFAULT_NODE_ADDRESS)
                    ): str,
                    vol.Required(
                        CONF_SOURCE_ADDRESS, default=f"0x{DEFAULT_SOURCE_ADDRESS:04x}"
                    ): str,
                    vol.Required(CONF_NET_KEY): str,
                    vol.Required(CONF_APP_KEY): str,
                    vol.Required(CONF_IV_INDEX, default=str(DEFAULT_IV_INDEX)): str,
                    vol.Required(CONF_SEQUENCE, default=str(DEFAULT_SEQUENCE)): str,
                    vol.Required(CONF_TTL, default=str(DEFAULT_TTL)): str,
                }
            ),
            errors=errors,
        )

    async def async_step_select_fixture(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select one or more lights from an imported catalog."""

        data = self._pending_import
        if data is None:
            return await self.async_step_user()

        catalog = list(data[CONF_FIXTURE_CATALOG])
        conflicts = _address_conflicts(catalog, data[CONF_SOURCE_ADDRESS])
        skip_ids = frozenset(self._async_current_ids()) | conflicts.keys()
        choices = {
            fixture_id: label
            for fixture_id, label in fixture_selection_choices(catalog).items()
            if fixture_id not in skip_ids
        }
        if not choices:
            return self.async_abort(reason="already_configured")

        placeholders = {
            "light_count": str(len(choices)),
            "source": self._import_source,
            "notes": (
                f"\n\nCan't add {', '.join(conflicts.values())}: it uses address "
                f"{data[CONF_SOURCE_ADDRESS]}, which Home Assistant sends from."
                if conflicts
                else ""
            ),
        }
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_FIXTURE_IDS, default=list(choices)
                ): cv.multi_select(choices)
            }
        )

        if user_input is not None:
            selected_ids = list(user_input.get(CONF_SELECTED_FIXTURE_IDS) or [])
            entries = fixture_entries_for_selection(
                data, catalog, selected_ids, skip_ids=skip_ids
            )
            if entries:
                for extra in entries[1:]:
                    await self.hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": config_entries.SOURCE_IMPORT},
                        data=extra,
                    )
                return await self._async_create_fixture_entry(entries[0])
            return self.async_show_form(
                step_id="select_fixture",
                data_schema=schema,
                errors={"base": "no_selection"},
                description_placeholders=placeholders,
            )

        return self.async_show_form(
            step_id="select_fixture",
            data_schema=schema,
            description_placeholders=placeholders,
        )

    async def _async_create_fixture_entry(
        self, data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Create one light config entry."""

        await self.async_set_unique_id(fixture_unique_id(data))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=str(data[CONF_NAME]), data=data)


class AmaranSidusOptionsFlow(config_entries.OptionsFlow):
    """Handle amaran options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the preferred connection light and presence checking."""

        entry = self.config_entry
        if user_input is not None:
            proxy_mac = str(user_input.get(CONF_PROXY_MAC) or "").strip()
            return self.async_create_entry(
                data={
                    **entry.options,
                    CONF_TRANSPORT_MODE: TRANSPORT_MODE_PERSISTENT,
                    CONF_PROXY_MAC: proxy_mac,
                    CONF_PROXY_SELECTION: (
                        PROXY_SELECTION_MANUAL if proxy_mac else PROXY_SELECTION_AUTO
                    ),
                    CONF_PROXY_ADDRESS: proxy_mac,
                    CONF_ENABLE_PRESENCE_CHECKING: _bool_from_user(
                        user_input.get(CONF_ENABLE_PRESENCE_CHECKING),
                        default=DEFAULT_ENABLE_PRESENCE_CHECKING,
                    ),
                }
            )

        current_proxy_mac = entry.options.get(
            CONF_PROXY_MAC,
            entry.options.get(
                CONF_PROXY_ADDRESS,
                entry.data.get(CONF_PROXY_MAC, entry.data.get(CONF_PROXY_ADDRESS, "")),
            ),
        )
        current_presence_checking = entry.options.get(
            CONF_ENABLE_PRESENCE_CHECKING,
            entry.data.get(
                CONF_ENABLE_PRESENCE_CHECKING, DEFAULT_ENABLE_PRESENCE_CHECKING
            ),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PROXY_MAC, default=current_proxy_mac): str,
                    vol.Optional(
                        CONF_ENABLE_PRESENCE_CHECKING,
                        default=_bool_from_user(
                            current_presence_checking,
                            default=DEFAULT_ENABLE_PRESENCE_CHECKING,
                        ),
                    ): bool,
                }
            ),
        )
