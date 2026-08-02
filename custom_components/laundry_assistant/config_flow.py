"""Config flow: one entry per appliance.

A washing machine and a tumble dryer are set up as separate entries. They
have different transition rules, different thresholds and separate history,
and keeping them apart means one can be recalibrated without disturbing the
other.

Everything tunable at run time - thresholds, price, reminder settings - is
controlled through the card or the services, not through this dialog. Only
the wiring (which sensor belongs to which appliance) lives here.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
)

from .const import (
    APPLIANCE_TYPE_DRYER,
    APPLIANCE_TYPE_WASHER,
    APPLIANCE_TYPES,
    CONF_APPLIANCE_TYPE,
    CONF_DOOR_ENTITY,
    CONF_POWER_ENTITY,
    DEFAULT_NAME_BY_LANGUAGE,
    DOMAIN,
)

POWER_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain="sensor", device_class="power")
)
DOOR_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
)


def _default_name(language: str | None, appliance_type: str) -> str:
    """Localized default for the free-text name field.

    Config flow schema defaults are static, so this is resolved once per
    form render from the instance language rather than via strings.json.
    """
    lang = (language or "en").split("-")[0]
    names = DEFAULT_NAME_BY_LANGUAGE.get(lang, DEFAULT_NAME_BY_LANGUAGE["en"])
    return names.get(appliance_type, appliance_type)


class LaundryAssistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Laundry Assistant."""

    VERSION = 1

    def __init__(self) -> None:
        self._appliance_type: str = APPLIANCE_TYPE_WASHER

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Pick the appliance type first - it decides the defaults offered
        in the next step, including the detection rules and thresholds."""
        return self.async_show_menu(step_id="user", menu_options=APPLIANCE_TYPES)

    async def async_step_washer(self, user_input: dict[str, Any] | None = None) -> Any:
        self._appliance_type = APPLIANCE_TYPE_WASHER
        return await self._async_step_appliance(user_input, step_id="washer")

    async def async_step_dryer(self, user_input: dict[str, Any] | None = None) -> Any:
        self._appliance_type = APPLIANCE_TYPE_DRYER
        return await self._async_step_appliance(user_input, step_id="dryer")

    async def _async_step_appliance(
        self, user_input: dict[str, Any] | None, step_id: str
    ) -> Any:
        if user_input is not None:
            power_entity = user_input[CONF_POWER_ENTITY]
            # Two entries watching the same plug would fight over the same
            # run history without ever disagreeing usefully.
            await self.async_set_unique_id(f"{DOMAIN}_{power_entity}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input["name"],
                data={
                    CONF_POWER_ENTITY: power_entity,
                    CONF_APPLIANCE_TYPE: self._appliance_type,
                    CONF_DOOR_ENTITY: user_input.get(CONF_DOOR_ENTITY),
                },
            )

        schema = vol.Schema(
            {
                vol.Required(
                    "name",
                    default=_default_name(self.hass.config.language, self._appliance_type),
                ): TextSelector(),
                vol.Required(CONF_POWER_ENTITY): POWER_SELECTOR,
                vol.Optional(CONF_DOOR_ENTITY): DOOR_SELECTOR,
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "LaundryAssistantOptionsFlow":
        return LaundryAssistantOptionsFlow()


class LaundryAssistantOptionsFlow(OptionsFlow):
    """Lets the wiring be changed after setup.

    Does not store config_entry itself - recent HA core versions provide it
    as a property, and assigning it manually now raises instead of warning.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        if user_input is not None:
            data = {
                **self.config_entry.data,
                CONF_POWER_ENTITY: user_input[CONF_POWER_ENTITY],
                CONF_DOOR_ENTITY: user_input.get(CONF_DOOR_ENTITY),
            }
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        schema_dict: dict[Any, Any] = {
            vol.Required(
                CONF_POWER_ENTITY, default=current.get(CONF_POWER_ENTITY)
            ): POWER_SELECTOR,
        }
        door_entity = current.get(CONF_DOOR_ENTITY)
        if door_entity:
            schema_dict[vol.Optional(CONF_DOOR_ENTITY, default=door_entity)] = DOOR_SELECTOR
        else:
            schema_dict[vol.Optional(CONF_DOOR_ENTITY)] = DOOR_SELECTOR

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))
