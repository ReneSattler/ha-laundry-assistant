"""Config and options flow."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.laundry_assistant.const import (
    APPLIANCE_TYPE_DRYER,
    APPLIANCE_TYPE_WASHER,
    CONF_APPLIANCE_TYPE,
    CONF_DOOR_ENTITY,
    CONF_POWER_ENTITY,
    DOMAIN,
)


async def _run_flow(hass, appliance_step, user_input):
    """Walk the menu and submit the appliance form."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": appliance_step}
    )
    assert result["step_id"] == appliance_step

    with patch(
        "custom_components.laundry_assistant.async_setup_entry", return_value=True
    ):
        return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_setting_up_a_washer(hass):
    result = await _run_flow(
        hass,
        APPLIANCE_TYPE_WASHER,
        {"name": "Washing machine", CONF_POWER_ENTITY: "sensor.washer_power"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Washing machine"
    assert result["data"][CONF_APPLIANCE_TYPE] == APPLIANCE_TYPE_WASHER
    assert result["data"][CONF_POWER_ENTITY] == "sensor.washer_power"
    assert result["data"][CONF_DOOR_ENTITY] is None


async def test_setting_up_a_dryer_with_a_door_sensor(hass):
    result = await _run_flow(
        hass,
        APPLIANCE_TYPE_DRYER,
        {
            "name": "Dryer",
            CONF_POWER_ENTITY: "sensor.dryer_power",
            CONF_DOOR_ENTITY: "binary_sensor.dryer_door",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_APPLIANCE_TYPE] == APPLIANCE_TYPE_DRYER
    assert result["data"][CONF_DOOR_ENTITY] == "binary_sensor.dryer_door"


async def test_the_same_power_sensor_cannot_be_used_twice(hass):
    """Two entries watching one plug would fight over the same history."""
    first = await _run_flow(
        hass, APPLIANCE_TYPE_WASHER, {"name": "A", CONF_POWER_ENTITY: "sensor.shared"}
    )
    assert first["type"] == FlowResultType.CREATE_ENTRY

    second = await _run_flow(
        hass, APPLIANCE_TYPE_DRYER, {"name": "B", CONF_POWER_ENTITY: "sensor.shared"}
    )
    assert second["type"] == FlowResultType.ABORT
    assert second["reason"] == "already_configured"


async def test_options_flow_changes_the_power_sensor(hass):
    created = await _run_flow(
        hass, APPLIANCE_TYPE_WASHER, {"name": "Washer", CONF_POWER_ENTITY: "sensor.old"}
    )
    entry = hass.config_entries.async_get_entry(created["result"].entry_id)

    with patch(
        "custom_components.laundry_assistant.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POWER_ENTITY: "sensor.new"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_POWER_ENTITY] == "sensor.new"
    # The appliance type is not part of the options form and must survive.
    assert entry.data[CONF_APPLIANCE_TYPE] == APPLIANCE_TYPE_WASHER
