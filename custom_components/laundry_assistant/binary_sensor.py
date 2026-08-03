"""Binary sensor: whether solar production would carry a cycle right now."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_SOLAR_SAVING_PER_CYCLE,
    ATTR_SOLAR_SURPLUS_W,
    ATTR_TYPICAL_DRAW_W,
    DOMAIN,
)
from .manager import LaundryApplianceManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: LaundryApplianceManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LaundrySolarSurplusSensor(manager, entry)])


class LaundrySolarSurplusSensor(BinarySensorEntity):
    """On when the current surplus has covered this appliance's typical draw
    for long enough that a passing cloud is not the reason.

    It only ever suggests. Switching the appliance on is out of scope: a
    washing machine has to be loaded first, and cutting power to one
    mid-cycle can leave it in a state it does not recover from.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "solar_covers_cycle"
    _attr_icon = "mdi:solar-power-variant"

    def __init__(self, manager: LaundryApplianceManager, entry: ConfigEntry) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_solar_covers_cycle"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "ha-laundry-assistant",
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._manager.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        # Without a solar sensor configured there is nothing to say, and an
        # entity permanently stuck at "off" would read as "never worth it".
        return self._manager.solar_entity is not None

    @property
    def is_on(self) -> bool:
        return bool(self._manager.solar_covers_cycle)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_SOLAR_SURPLUS_W: self._manager.solar_surplus_w,
            ATTR_TYPICAL_DRAW_W: self._manager.typical_draw_w,
            ATTR_SOLAR_SAVING_PER_CYCLE: self._manager.solar_saving_per_cycle,
        }
