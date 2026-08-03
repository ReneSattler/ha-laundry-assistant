"""The bundled card file and the strings that reference it."""
from __future__ import annotations

import json
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "laundry_assistant"
CARD = COMPONENT / "frontend" / "laundry-assistant-card.js"


def test_the_card_file_is_bundled():
    assert CARD.is_file()


def test_both_cards_are_registered():
    source = CARD.read_text(encoding="utf-8")
    for element in (
        "laundry-assistant-card",
        "laundry-assistant-settings-card",
        "laundry-assistant-card-editor",
        "laundry-assistant-settings-card-editor",
    ):
        assert f'customElements.define("{element}"' in source
    # Without this the cards never show up in the card picker.
    assert "window.customCards" in source


def test_the_card_filename_matches_what_the_integration_serves():
    source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert f'CARD_FILENAME = "{CARD.name}"' in source


def test_the_manifest_declares_what_the_card_hosting_needs():
    """async_setup uses hass.http and the frontend helpers; both have to be
    declared or they are not guaranteed to be loaded when it runs."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert "http" in manifest["dependencies"]
    assert "frontend" in manifest["dependencies"]


def test_every_phase_state_is_translated():
    """A phase with no translation shows up as a raw slug in the UI."""
    from custom_components.laundry_assistant.const import ALL_PHASES

    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        data = json.loads((COMPONENT / name).read_text(encoding="utf-8"))
        states = data["entity"]["sensor"]["phase"]["state"]
        assert set(states) == set(ALL_PHASES), f"{name} does not cover every phase"


def test_the_card_translates_every_phase_too():
    from custom_components.laundry_assistant.const import ALL_PHASES

    source = CARD.read_text(encoding="utf-8")
    for phase in ALL_PHASES:
        assert f"{phase}:" in source, f"the card has no label for '{phase}'"
