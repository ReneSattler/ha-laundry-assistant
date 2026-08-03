"""Laundry Assistant - derives washing machine and tumble dryer cycle
phases, remaining time and cost from a smart plug's power measurements."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from aiohttp import web

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

# Lovelace's resource collection is not a stable public API - the import
# path and names have moved between core versions. Importing them unguarded
# would mean a single rename in core takes down the whole integration on any
# version that does not match; degrade to add_extra_js_url() instead.
try:
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.resources import ResourceStorageCollection
except ImportError:  # pragma: no cover - depends on the core version
    LOVELACE_DATA = None
    ResourceStorageCollection = None

from .const import (
    CONF_APPLIANCE_TYPE,
    CONF_DOOR_ENTITY,
    CONF_POWER_ENTITY,
    DOMAIN,
    MAX_ANOMALY_FACTOR,
    MIN_ANOMALY_FACTOR,
    PLATFORMS,
    SERVICE_APPLY_CALIBRATION,
    SERVICE_CANCEL_CALIBRATION,
    SERVICE_CLEAR_HISTORY,
    SERVICE_DISMISS_ANOMALIES,
    SERVICE_DISMISS_REMINDER,
    SERVICE_SET_ANOMALY_DETECTION,
    SERVICE_SET_NOTIFY_TARGET,
    SERVICE_SET_PRICE,
    SERVICE_SET_REMINDER,
    SERVICE_SET_THRESHOLDS,
    SERVICE_START_CALIBRATION,
)
from .manager import LaundryApplianceManager

_LOGGER = logging.getLogger(__name__)

ENTRY_ID_ONLY_SCHEMA = vol.Schema({vol.Required("entry_id"): cv.string})

SET_PRICE_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("price_per_kwh"): vol.All(vol.Coerce(float), vol.Range(min=0, max=10)),
        vol.Optional("currency"): cv.string,
    }
)
SET_REMINDER_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("enabled"): cv.boolean,
        vol.Optional("delay_minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
        vol.Optional("repeat_minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
        vol.Optional("max_repeats"): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
    }
)
SET_NOTIFY_TARGET_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Optional("target"): vol.Any(cv.string, None),
    }
)
SET_ANOMALY_DETECTION_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("enabled"): cv.boolean,
        vol.Optional("factor"): vol.All(
            vol.Coerce(float), vol.Range(min=MIN_ANOMALY_FACTOR, max=MAX_ANOMALY_FACTOR)
        ),
    }
)
SET_THRESHOLDS_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("thresholds"): dict,
    }
)

FRONTEND_URL_BASE = f"/{DOMAIN}_files"
CARD_FILENAME = "laundry-assistant-card.js"


class _CardFileView(HomeAssistantView):
    """Serves the bundled card with an explicit no-store Cache-Control
    header. The resource URL already carries a `?v=<version>` query string
    that changes on every release, so this is defense in depth against a
    browser heuristically caching the response."""

    url = f"{FRONTEND_URL_BASE}/{CARD_FILENAME}"
    name = f"{DOMAIN}:card_file"
    requires_auth = False

    def __init__(self, content: bytes) -> None:
        self._content = content

    async def get(self, request: web.Request) -> web.Response:
        return web.Response(
            body=self._content,
            content_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )


async def _async_ensure_lovelace_resource(hass: HomeAssistant, version: str) -> bool:
    """Register (or update, on a version change) a Lovelace resource for the
    card. Returns False when this instance manages resources via YAML or
    runs a core version whose Lovelace internals cannot be written to; the
    caller then falls back to add_extra_js_url()."""
    if LOVELACE_DATA is None or ResourceStorageCollection is None:
        return False

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or not isinstance(
        getattr(lovelace_data, "resources", None), ResourceStorageCollection
    ):
        return False

    resources = lovelace_data.resources
    await resources.async_get_info()

    base_url = f"{FRONTEND_URL_BASE}/{CARD_FILENAME}"
    new_url = f"{base_url}?v={version}"
    existing = next(
        (item for item in resources.async_items() if item["url"].startswith(base_url)),
        None,
    )
    if existing is None:
        await resources.async_create_item({"res_type": "module", "url": new_url})
    elif existing["url"] != new_url:
        await resources.async_update_item(existing["id"], {"url": new_url})
    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Self-host the Lovelace card so it loads automatically - no separate
    HACS download and no manual resource registration."""
    integration = await async_get_integration(hass, DOMAIN)
    card_path = Path(integration.file_path) / "frontend" / CARD_FILENAME
    content = await hass.async_add_executor_job(card_path.read_bytes)
    hass.http.register_view(_CardFileView(content))

    card_url = f"{FRONTEND_URL_BASE}/{CARD_FILENAME}?v={integration.version}"
    # Broad except on purpose: this touches Lovelace internals that are not
    # a stable public API, and it is only a convenience step. Letting it
    # escape would abort async_setup entirely, taking down every entity and
    # service with it.
    try:
        registered = await _async_ensure_lovelace_resource(hass, integration.version)
    except Exception:  # noqa: BLE001 - never let this break integration setup
        _LOGGER.exception(
            "Registering the Lovelace resource for the Laundry Assistant card "
            "failed unexpectedly; falling back to injecting it into the frontend"
        )
        registered = False

    if registered:
        _LOGGER.debug("Registered Lovelace resource for the card: %s", card_url)
    else:
        add_extra_js_url(hass, card_url)
        _LOGGER.warning(
            "Could not register a Lovelace resource for the Laundry Assistant "
            "card - this instance either manages Lovelace resources via YAML or "
            "runs a Home Assistant version whose Lovelace internals this "
            "integration cannot write to. Falling back to injecting the card "
            "directly. If the card does not show up in the card picker, add %s "
            "manually as a JavaScript module under Settings > Dashboards > "
            "Resources.",
            card_url,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    manager = LaundryApplianceManager(
        hass,
        entry.entry_id,
        entry.title,
        entry.data[CONF_POWER_ENTITY],
        entry.data[CONF_APPLIANCE_TYPE],
        entry.data.get(CONF_DOOR_ENTITY),
    )
    await manager.async_load()
    hass.data[DOMAIN][entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when the options flow changes which entities are watched."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager: LaundryApplianceManager = hass.data[DOMAIN][entry.entry_id]
    await manager.async_unload()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


def _get_manager(hass: HomeAssistant, entry_id: str) -> LaundryApplianceManager:
    manager = hass.data.get(DOMAIN, {}).get(entry_id)
    if manager is None:
        raise ServiceValidationError(f"Unknown Laundry Assistant entry_id: {entry_id}")
    return manager


def _async_register_services(hass: HomeAssistant) -> None:
    # Services are registered per domain but this runs once per config
    # entry - skip if a previous entry already registered them, so adding a
    # dryer next to a washer does not reset the handlers.
    if hass.services.has_service(DOMAIN, SERVICE_SET_PRICE):
        return

    async def handle_set_price(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_set_price(call.data["price_per_kwh"], call.data.get("currency"))

    async def handle_set_reminder(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_set_reminder(
            call.data["enabled"],
            call.data.get("delay_minutes"),
            call.data.get("repeat_minutes"),
            call.data.get("max_repeats"),
        )

    async def handle_set_notify_target(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_set_notify_target(call.data.get("target"))

    async def handle_set_thresholds(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        try:
            await manager.async_set_thresholds(call.data["thresholds"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def handle_start_calibration(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_start_calibration()

    async def handle_cancel_calibration(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_cancel_calibration()

    async def handle_apply_calibration(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        try:
            await manager.async_apply_calibration()
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def handle_dismiss_reminder(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_dismiss_reminder()

    async def handle_clear_history(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_clear_history()

    async def handle_set_anomaly_detection(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_set_anomaly_detection(
            call.data["enabled"], call.data.get("factor")
        )

    async def handle_dismiss_anomalies(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data["entry_id"])
        await manager.async_dismiss_anomalies()

    hass.services.async_register(
        DOMAIN, SERVICE_SET_PRICE, handle_set_price, schema=SET_PRICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_REMINDER, handle_set_reminder, schema=SET_REMINDER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_NOTIFY_TARGET,
        handle_set_notify_target,
        schema=SET_NOTIFY_TARGET_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_THRESHOLDS, handle_set_thresholds, schema=SET_THRESHOLDS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_START_CALIBRATION, handle_start_calibration, schema=ENTRY_ID_ONLY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_CALIBRATION,
        handle_cancel_calibration,
        schema=ENTRY_ID_ONLY_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_CALIBRATION, handle_apply_calibration, schema=ENTRY_ID_ONLY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_REMINDER, handle_dismiss_reminder, schema=ENTRY_ID_ONLY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_HISTORY, handle_clear_history, schema=ENTRY_ID_ONLY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ANOMALY_DETECTION,
        handle_set_anomaly_detection,
        schema=SET_ANOMALY_DETECTION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_ANOMALIES, handle_dismiss_anomalies, schema=ENTRY_ID_ONLY_SCHEMA
    )
