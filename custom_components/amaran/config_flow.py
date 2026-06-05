"""Config flow for Amaran Sidus."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.core import callback

from .const import (
    CONF_ADDRESS,
    CONF_APP_KEY,
    CONF_BLE_MAC,
    CONF_FIXTURE_CATALOG,
    CONF_IMPORT_JSON,
    CONF_IMPORT_METHOD,
    CONF_IV_INDEX,
    CONF_IMPORT_PATH,
    CONF_NAME,
    CONF_NET_KEY,
    CONF_NODE_ADDRESS,
    CONF_PROXY_ADDRESS,
    CONF_PROXY_CANDIDATES,
    CONF_PROXY_MAC,
    CONF_PROXY_SELECTION,
    CONF_SEQUENCE,
    CONF_SELECTED_FIXTURE,
    CONF_SETUP_METHOD,
    CONF_SOURCE_ADDRESS,
    CONF_TTL,
    CONF_TRANSPORT_MODE,
    DEFAULT_IV_INDEX,
    DEFAULT_NAME,
    DEFAULT_NODE_ADDRESS,
    DEFAULT_SEQUENCE,
    DEFAULT_SOURCE_ADDRESS,
    DEFAULT_TTL,
    DOMAIN,
    IMPORT_METHOD_JSON,
    IMPORT_METHOD_PATH,
    IMPORT_METHODS,
    PROXY_SELECTION_AUTO,
    PROXY_SELECTION_MANUAL,
    SETUP_METHOD_IMPORT,
    SETUP_METHOD_MANUAL,
    SETUP_METHODS,
    TRANSPORT_MODE_PERSISTENT,
)
from .fixtures import (
    FixtureImport,
    default_desktop_db_path,
    fixture_for_unique_id,
    fixture_entry_data,
    fixture_selection_choices,
    fixture_unique_id,
    light_capability_names,
    load_fixture_import,
    load_fixture_import_json,
)
from .discovery import bluetooth_discovery_enabled
from .protocol import normalize_hex_key


def _int_from_user(value: Any) -> int:
    if isinstance(value, int):
        return value
    return int(str(value).strip(), 0)


def _validate_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)

    data[CONF_NAME] = str(data.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
    data[CONF_ADDRESS] = str(data[CONF_ADDRESS]).strip()
    if not data[CONF_ADDRESS]:
        raise ValueError(CONF_ADDRESS)

    if ble_mac := data.get(CONF_BLE_MAC):
        data[CONF_BLE_MAC] = str(ble_mac).strip()

    _normalize_proxy_settings(data)
    data[CONF_NODE_ADDRESS] = _int_from_user(data[CONF_NODE_ADDRESS])
    data[CONF_SOURCE_ADDRESS] = _int_from_user(
        data.get(CONF_SOURCE_ADDRESS, DEFAULT_SOURCE_ADDRESS)
    )
    data[CONF_IV_INDEX] = _int_from_user(data.get(CONF_IV_INDEX, DEFAULT_IV_INDEX))
    data[CONF_SEQUENCE] = _int_from_user(data.get(CONF_SEQUENCE, DEFAULT_SEQUENCE))
    data[CONF_TTL] = _int_from_user(data.get(CONF_TTL, DEFAULT_TTL))

    if not 1 <= data[CONF_NODE_ADDRESS] <= 0x03FF:
        raise ValueError(CONF_NODE_ADDRESS)
    if not 1 <= data[CONF_SOURCE_ADDRESS] <= 0x03FF:
        raise ValueError(CONF_SOURCE_ADDRESS)
    if data[CONF_NODE_ADDRESS] == data[CONF_SOURCE_ADDRESS]:
        raise ValueError(CONF_SOURCE_ADDRESS)
    if not 0 <= data[CONF_IV_INDEX] <= 0xFFFFFFFF:
        raise ValueError(CONF_IV_INDEX)
    if not 0 <= data[CONF_SEQUENCE] <= 0xFFFFFF:
        raise ValueError(CONF_SEQUENCE)
    if not 0 <= data[CONF_TTL] <= 0x7F:
        raise ValueError(CONF_TTL)
    data[CONF_NET_KEY] = normalize_hex_key(
        str(data[CONF_NET_KEY]), field="network key"
    ).hex()
    data[CONF_APP_KEY] = normalize_hex_key(str(data[CONF_APP_KEY]), field="app key").hex()
    data[CONF_PROXY_CANDIDATES] = _proxy_candidates_from_fixtures([data])
    return data


def _validate_import_path_input(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    import_path = str(data[CONF_IMPORT_PATH]).strip()
    imported = load_fixture_import(import_path)

    data[CONF_IMPORT_PATH] = imported.source_path
    return _finalize_import_data(data, imported)


def _validate_import_json_input(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    imported = load_fixture_import_json(str(data[CONF_IMPORT_JSON]))
    return _finalize_import_data(data, imported)


def _finalize_import_data(
    user_input: dict[str, Any], imported: FixtureImport
) -> dict[str, Any]:
    data = dict(user_input)
    data[CONF_SOURCE_ADDRESS] = _int_from_user(
        data.get(CONF_SOURCE_ADDRESS, DEFAULT_SOURCE_ADDRESS)
    )
    data[CONF_IV_INDEX] = _int_from_user(data.get(CONF_IV_INDEX, DEFAULT_IV_INDEX))
    data[CONF_SEQUENCE] = _int_from_user(data.get(CONF_SEQUENCE, DEFAULT_SEQUENCE))
    data[CONF_TTL] = _int_from_user(data.get(CONF_TTL, DEFAULT_TTL))
    _normalize_proxy_settings(data)

    if not 1 <= data[CONF_SOURCE_ADDRESS] <= 0x03FF:
        raise ValueError(CONF_SOURCE_ADDRESS)
    if not 0 <= data[CONF_IV_INDEX] <= 0xFFFFFFFF:
        raise ValueError(CONF_IV_INDEX)
    if not 0 <= data[CONF_SEQUENCE] <= 0xFFFFFF:
        raise ValueError(CONF_SEQUENCE)
    if not 0 <= data[CONF_TTL] <= 0x7F:
        raise ValueError(CONF_TTL)
    data[CONF_FIXTURE_CATALOG] = imported.fixtures
    data[CONF_PROXY_CANDIDATES] = _proxy_candidates_from_fixtures(
        imported.fixtures,
        extra=data[CONF_PROXY_MAC],
    )
    data[CONF_IMPORT_PATH] = imported.source_path
    data.pop(CONF_IMPORT_JSON, None)
    data.pop(CONF_IMPORT_METHOD, None)
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


class AmaranSidusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an Amaran Sidus config flow."""

    VERSION = 2
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""

        return AmaranSidusOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._discovery: bluetooth.BluetoothServiceInfoBleak | None = None
        self._pending_import: dict[str, Any] | None = None

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> config_entries.ConfigFlowResult:
        """Handle Bluetooth discovery."""

        if not bluetooth_discovery_enabled(self.hass):
            return self.async_abort(reason="bluetooth_discovery_disabled")
        self._discovery = discovery_info
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose import or manual setup."""

        if user_input is not None:
            if CONF_IMPORT_PATH in user_input and str(
                user_input.get(CONF_IMPORT_PATH) or ""
            ).strip():
                return await self.async_step_import_path(user_input)
            if CONF_IMPORT_JSON in user_input and str(
                user_input.get(CONF_IMPORT_JSON) or ""
            ).strip():
                return await self.async_step_import_json(user_input)
            if CONF_ADDRESS in user_input:
                return await self.async_step_manual(user_input)
            method = user_input.get(CONF_SETUP_METHOD)
            if method == SETUP_METHOD_IMPORT:
                return await self.async_step_import()
            if method == SETUP_METHOD_MANUAL:
                return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SETUP_METHOD,
                        default=SETUP_METHOD_IMPORT,
                    ): vol.In(SETUP_METHODS)
                }
            ),
            errors={},
        )

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
            data_schema=self._manual_schema(),
            errors=errors,
        )

    async def async_step_import(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose import method."""

        if user_input is not None:
            if CONF_ADDRESS in user_input:
                return await self._async_create_fixture_entry(dict(user_input))
            method = user_input.get(CONF_IMPORT_METHOD)
            if method == IMPORT_METHOD_JSON:
                return await self.async_step_import_json()
            if method == IMPORT_METHOD_PATH:
                return await self.async_step_import_path()

        return self.async_show_form(
            step_id="import",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IMPORT_METHOD,
                        default=IMPORT_METHOD_JSON,
                    ): vol.In(IMPORT_METHODS)
                }
            ),
            errors={},
        )

    async def async_step_import_json(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle pasted JSON import."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _validate_import_json_input(user_input)
            except ValueError as err:
                errors["base"] = "invalid_input"
                if err.args:
                    errors[str(err.args[0])] = "invalid_input"
            else:
                self._pending_import = data
                return await self.async_step_select_fixture()

        return self.async_show_form(
            step_id="import_json",
            data_schema=self._import_json_schema(),
            errors=errors,
        )

    async def async_step_import_path(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle local amaran.db or JSON path import."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _validate_import_path_input(user_input)
            except ValueError as err:
                errors["base"] = "invalid_input"
                if err.args:
                    errors[str(err.args[0])] = "invalid_input"
            else:
                self._pending_import = data
                return await self.async_step_select_fixture()

        return self.async_show_form(
            step_id="import_path",
            data_schema=self._import_path_schema(),
            errors=errors,
        )

    async def async_step_select_fixture(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select the first fixture from an imported mesh catalog."""

        data = self._pending_import
        if data is None:
            return await self.async_step_import()

        catalog = list(data[CONF_FIXTURE_CATALOG])
        choices = fixture_selection_choices(catalog)
        if user_input is not None:
            fixture = fixture_for_unique_id(
                catalog, str(user_input[CONF_SELECTED_FIXTURE])
            )
            if fixture is None:
                return self.async_show_form(
                    step_id="select_fixture",
                    data_schema=self._fixture_selection_schema(choices),
                    errors={CONF_SELECTED_FIXTURE: "invalid_input"},
                )
            entry_data = fixture_entry_data(data, fixture)
            return await self._async_create_fixture_entry(entry_data)

        return self.async_show_form(
            step_id="select_fixture",
            data_schema=self._fixture_selection_schema(choices),
            errors={},
            description_placeholders={
                "light_count": str(len(catalog)),
                "source": str(data.get(CONF_IMPORT_PATH) or "pasted JSON"),
                "detected_lights": _detected_light_summary(catalog),
            },
        )

    async def _async_create_fixture_entry(
        self, data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Create one fixture-specific config entry."""

        await self.async_set_unique_id(fixture_unique_id(data))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=str(data[CONF_NAME]), data=data)

    @callback
    def _fixture_selection_schema(self, choices: dict[str, str]) -> vol.Schema:
        default_fixture = next(iter(choices))
        return vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_FIXTURE,
                    default=default_fixture,
                ): vol.In(choices)
            }
        )

    @callback
    def _manual_schema(self) -> vol.Schema:
        address = self._discovery.address if self._discovery else ""
        name = self._discovery.name if self._discovery else DEFAULT_NAME
        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=name or DEFAULT_NAME): str,
                vol.Required(CONF_ADDRESS, default=address): str,
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
        )

    @callback
    def _import_json_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_IMPORT_JSON): str,
                vol.Required(
                    CONF_SOURCE_ADDRESS, default=f"0x{DEFAULT_SOURCE_ADDRESS:04x}"
                ): str,
                vol.Optional(CONF_PROXY_MAC, default=""): str,
                vol.Required(CONF_IV_INDEX, default=str(DEFAULT_IV_INDEX)): str,
                vol.Required(CONF_SEQUENCE, default=str(DEFAULT_SEQUENCE)): str,
                vol.Required(CONF_TTL, default=str(DEFAULT_TTL)): str,
            }
        )

    @callback
    def _import_path_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_IMPORT_PATH,
                    default=default_desktop_db_path(),
                ): str,
                vol.Required(
                    CONF_SOURCE_ADDRESS, default=f"0x{DEFAULT_SOURCE_ADDRESS:04x}"
                ): str,
                vol.Optional(CONF_PROXY_MAC, default=""): str,
                vol.Required(CONF_IV_INDEX, default=str(DEFAULT_IV_INDEX)): str,
                vol.Required(CONF_SEQUENCE, default=str(DEFAULT_SEQUENCE)): str,
                vol.Required(CONF_TTL, default=str(DEFAULT_TTL)): str,
            }
        )


class AmaranSidusOptionsFlow(config_entries.OptionsFlow):
    """Handle Amaran Sidus options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage fixture proxy settings."""

        if user_input is not None:
            proxy_mac = str(user_input.get(CONF_PROXY_MAC) or "").strip()
            options = dict(self._config_entry.options)
            options.update(
                {
                    CONF_TRANSPORT_MODE: TRANSPORT_MODE_PERSISTENT,
                    CONF_PROXY_MAC: proxy_mac,
                    CONF_PROXY_SELECTION: (
                        PROXY_SELECTION_MANUAL if proxy_mac else PROXY_SELECTION_AUTO
                    ),
                    CONF_PROXY_ADDRESS: proxy_mac,
                }
            )
            return self.async_create_entry(
                title="",
                data=options,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self._options_schema(),
            errors={},
        )

    def _options_schema(self) -> vol.Schema:
        current_proxy_mac = self._config_entry.options.get(
            CONF_PROXY_MAC,
            self._config_entry.options.get(
                CONF_PROXY_ADDRESS,
                self._config_entry.data.get(
                    CONF_PROXY_MAC,
                    self._config_entry.data.get(CONF_PROXY_ADDRESS, ""),
                ),
            ),
        )
        return vol.Schema(
            {
                vol.Optional(CONF_PROXY_MAC, default=current_proxy_mac): str,
            }
        )


def _detected_light_summary(catalog: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for light in catalog:
        name = str(light.get(CONF_NAME) or "Amaran light")
        model = str(light.get("model") or "Unknown")
        capabilities = ", ".join(light_capability_names(light))
        lines.append(f"{name} ({model}): {capabilities}")
    return "\n".join(lines)
