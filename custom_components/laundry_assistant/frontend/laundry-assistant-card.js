/*
 * Laundry Assistant - Lovelace cards.
 *
 * Two cards, both driven entirely by the attributes of one
 * `sensor.*_phase` entity:
 *
 *   laundry-assistant-card           read-only status: phase timeline,
 *                                    live power curve, cycle figures
 *   laundry-assistant-settings-card  price, reminder, thresholds,
 *                                    calibration
 *
 * Written as plain custom elements against HTMLElement rather than Lit:
 * the integration bundles this file itself, so it cannot rely on any
 * particular frontend version exposing a bundler-free Lit build.
 */

const DOMAIN = "laundry_assistant";

const STRINGS = {
  en: {
    idle: "Idle",
    intake: "Water intake",
    heating: "Heating",
    washing: "Washing",
    draining: "Draining",
    spinning: "Spinning",
    drying: "Drying",
    cooldown: "Cooling down",
    running: "Running",
    finished: "Finished",
    notRunning: "Not running",
    remaining: "Remaining",
    elapsed: "Elapsed",
    cycleEnergy: "This cycle",
    cycleCost: "Cost this cycle",
    lastCycle: "Last cycle",
    thisWeek: "This week",
    cycles: "cycles",
    unknown: "unknown",
    power: "Current power",
    settings: "Laundry - settings",
    price: "Price per kWh",
    reminder: "Remind me when the load is left in the drum",
    reminderDelay: "Delay after the cycle ends",
    reminderRepeat: "Repeat every",
    reminderMax: "At most",
    times: "times",
    minutes: "min",
    notifyTarget: "Notification target",
    none: "- none -",
    thresholds: "Power band thresholds",
    standby: "Standby",
    low: "Low",
    medium: "Medium",
    high: "High",
    apply: "Apply",
    calibration: "Calibration",
    calibrationIdle: "Records complete runs and proposes thresholds from them.",
    calibrationRecording: "Recording: {done} of {needed} runs.",
    calibrationReady: "Proposal ready.",
    startCalibration: "Start",
    cancelCalibration: "Cancel",
    applyCalibration: "Adopt proposal",
    slowUpdates:
      "The power sensor only updates every {seconds} s. Phases shorter than that are missed - set TelePeriod 10 or PowerDelta 10 on Tasmota devices.",
    reminderPending: "A reminder is pending.",
    dismiss: "Dismiss",
    noEntity: "Entity not found",
    anomalyTitle: "Unusual cycle",
    anomalyDetection: "Warn about unusual cycles",
    anomalySensitivity: "Report a deviation beyond",
    factorSuffix: "x normal",
    solarBanner: "Solar would carry a cycle right now - saves about {saving} {currency}.",
    solarEntity: "Solar production sensor",
    consumptionEntity: "House consumption sensor",
    feedInTariff: "Feed-in tariff",
    programs: "Recognised programs",
    unnamedProgram: "Unnamed",
    runsSuffix: "runs",
    save: "Save",
  },
  de: {
    idle: "Bereit",
    intake: "Wasseraufnahme",
    heating: "Heizen",
    washing: "Waschen",
    draining: "Abpumpen",
    spinning: "Schleudern",
    drying: "Trocknen",
    cooldown: "Abkühlen",
    running: "Läuft",
    finished: "Fertig",
    notRunning: "Läuft nicht",
    remaining: "Restzeit",
    elapsed: "Laufzeit",
    cycleEnergy: "Dieser Durchgang",
    cycleCost: "Kosten dieser Durchgang",
    lastCycle: "Letzter Durchgang",
    thisWeek: "Diese Woche",
    cycles: "Durchgänge",
    unknown: "unbekannt",
    power: "Aktuelle Leistung",
    settings: "Wäsche - Einstellungen",
    price: "Preis pro kWh",
    reminder: "Erinnern, wenn die Wäsche liegen bleibt",
    reminderDelay: "Verzögerung nach Ende",
    reminderRepeat: "Wiederholen alle",
    reminderMax: "Höchstens",
    times: "mal",
    minutes: "Min",
    notifyTarget: "Benachrichtigung an",
    none: "- keine -",
    thresholds: "Schwellwerte der Leistungsbänder",
    standby: "Standby",
    low: "Niedrig",
    medium: "Mittel",
    high: "Hoch",
    apply: "Übernehmen",
    calibration: "Kalibrierung",
    calibrationIdle: "Zeichnet komplette Läufe auf und schlägt daraus Schwellwerte vor.",
    calibrationRecording: "Zeichnet auf: {done} von {needed} Läufen.",
    calibrationReady: "Vorschlag liegt vor.",
    startCalibration: "Starten",
    cancelCalibration: "Abbrechen",
    applyCalibration: "Vorschlag übernehmen",
    slowUpdates:
      "Der Leistungssensor aktualisiert nur alle {seconds} s. Kürzere Phasen werden übersehen - bei Tasmota TelePeriod 10 oder PowerDelta 10 setzen.",
    reminderPending: "Eine Erinnerung ist aktiv.",
    dismiss: "Verwerfen",
    noEntity: "Entität nicht gefunden",
    anomalyTitle: "Ungewöhnlicher Durchgang",
    anomalyDetection: "Vor ungewöhnlichen Durchgängen warnen",
    anomalySensitivity: "Melden ab Abweichung von",
    factorSuffix: "x normal",
    solarBanner: "Die Sonne würde jetzt einen Durchgang tragen - spart etwa {saving} {currency}.",
    solarEntity: "Sensor PV-Erzeugung",
    consumptionEntity: "Sensor Hausverbrauch",
    feedInTariff: "Einspeisevergütung",
    programs: "Erkannte Programme",
    unnamedProgram: "Unbenannt",
    runsSuffix: "Läufe",
    save: "Speichern",
  },
};

const PHASE_COLORS = {
  intake: "var(--info-color, #039be5)",
  heating: "var(--error-color, #db4437)",
  washing: "var(--primary-color, #03a9f4)",
  draining: "var(--info-color, #039be5)",
  spinning: "var(--warning-color, #ffa600)",
  drying: "var(--primary-color, #03a9f4)",
  cooldown: "var(--info-color, #039be5)",
  running: "var(--primary-color, #03a9f4)",
  finished: "var(--success-color, #43a047)",
  idle: "var(--disabled-text-color, #bdbdbd)",
};

// The locale of whichever card rendered last. Number formatting has to
// follow the instance language - a German dashboard showing "0.79 kWh"
// instead of "0,79 kWh" looks like a bug to the person reading it - but
// threading hass through every formatting call site would be noise.
let activeLocale = "en";

function lang(hass) {
  const code = (hass && (hass.locale?.language || hass.language)) || "en";
  return STRINGS[code.split("-")[0]] ? code.split("-")[0] : "en";
}

function t(hass, key, vars) {
  let text = STRINGS[lang(hass)][key] ?? STRINGS.en[key] ?? key;
  if (vars) {
    Object.keys(vars).forEach((name) => {
      text = text.replace(`{${name}}`, vars[name]);
    });
  }
  return text;
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]
  );
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return null;
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")} h`;
  return `${m} min`;
}

function formatNumber(value, digits) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Number(value).toLocaleString(activeLocale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

// Number inputs only accept a dot as the decimal separator regardless of
// locale, so the value written into one has to bypass formatNumber.
function inputNumber(value, digits) {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return Number(value).toFixed(digits);
}

class LaundryBaseCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("An entity is required (the appliance's phase sensor)");
    }
    this._config = config;
    this._rendered = false;
  }

  /* Rendering replaces the card's entire DOM, which destroys whatever the
   * user was focused on. The phase sensor updates on every power reading -
   * several times a minute while an appliance runs - so without a guard,
   * editing any field during a cycle means losing focus mid-keystroke, over
   * and over. On Android that also dismisses the keyboard each time.
   *
   * Two independent brakes, because neither is sufficient alone:
   *
   *   _isEditingField()  blocks while a field genuinely holds focus
   *   _suppressRender    blocks from the first touch until shortly after
   *                      the resulting service call has come back
   *
   * The second exists because the moment a native control opens its own UI
   * (a number keypad, a select dialog) the underlying element can lose DOM
   * focus, so the focus check alone would let a render through at exactly
   * the wrong moment.
   */
  connectedCallback() {
    if (this._guardsAttached) return;
    this._guardsAttached = true;

    // Delegated, and bound to the host element rather than its children:
    // _render() replaces innerHTML wholesale, so anything bound to a child
    // would be thrown away on the first update. The host survives.
    const startSuppression = (event) => {
      if (event.target.closest?.("input, select, textarea")) {
        this._suppressRender = true;
        this._scheduleRenderResume(60000);
      }
    };
    // pointerdown covers mouse, touch and pen anywhere standards-compliant.
    // touchstart and focusin are redundant fallbacks: some embedded
    // WebViews - the Home Assistant Companion App on Android among them -
    // do not reliably dispatch pointer events for native form controls.
    // "input" is the last resort, because a range slider's thumb drag has
    // its own built-in gesture handling and may dispatch none of the other
    // three, yet every live-updating label beside a slider already relies
    // on "input" firing during the drag.
    this.addEventListener("pointerdown", startSuppression);
    this.addEventListener("touchstart", startSuppression, { passive: true });
    this.addEventListener("focusin", startSuppression);
    this.addEventListener("input", startSuppression);
  }

  disconnectedCallback() {
    clearTimeout(this._suppressRenderTimeout);
  }

  /** Whether a field the user could still be part-way through editing holds
   * focus.
   *
   * Checkboxes, selects and range sliders are deliberately excluded: those
   * are one-shot interactions - once toggled, chosen or dragged there is
   * nothing left to be part-way through - but they commonly keep DOM focus
   * afterwards. Counting them as "editing" would block the render that is
   * supposed to show the result, so a toggled switch would not reveal its
   * dependent section until focus happened to move elsewhere.
   *
   * Uses document.activeElement rather than a shadow root's: this card
   * renders into the light DOM. The containment check matters - without it
   * a field in a completely different card would freeze this one.
   */
  _isEditingField() {
    const active = document.activeElement;
    if (!active || !this.contains(active)) return false;
    if (active.tagName === "TEXTAREA") return true;
    if (active.tagName === "INPUT") return !["checkbox", "range"].includes(active.type);
    return false;
  }

  /** Lifts suppression after delayMs and forces one fresh render, unless a
   * field still holds focus - the hass setter keeps blocking those. */
  _scheduleRenderResume(delayMs) {
    clearTimeout(this._suppressRenderTimeout);
    this._suppressRenderTimeout = setTimeout(() => {
      this._suppressRender = false;
      if (!this._isEditingField()) this._render();
    }, delayMs);
  }

  /** Lifts suppression once a service call has actually come back.
   *
   * Re-rendering the instant "change" fires would rebuild the card from
   * attributes that have not caught up with the edit yet, so the value
   * visibly snaps back to its old number for a moment. Waiting for the
   * round trip avoids that. The 8 s timer is a safety net for a call that
   * never settles; without it the card would stay frozen.
   */
  _releaseRenderSuppression(pendingCall) {
    clearTimeout(this._suppressRenderTimeout);
    if (!pendingCall || typeof pendingCall.then !== "function") {
      this._scheduleRenderResume(1000);
      return;
    }
    this._suppressRenderTimeout = setTimeout(() => this._scheduleRenderResume(0), 8000);
    pendingCall.then(
      () => this._scheduleRenderResume(400),
      () => this._scheduleRenderResume(400)
    );
  }

  set hass(hass) {
    this._hass = hass;
    activeLocale = lang(hass);
    if (!this._suppressRender && !this._isEditingField()) {
      this._render();
    }
  }

  get _stateObj() {
    if (!this._hass || !this._config) return null;
    return this._hass.states[this._config.entity] || null;
  }

  get _attrs() {
    return this._stateObj ? this._stateObj.attributes : {};
  }

  get _entryId() {
    return this._attrs.entry_id;
  }

  _callService(service, extra) {
    if (!this._entryId) return Promise.resolve();
    const pending = this._hass.callService(DOMAIN, service, {
      entry_id: this._entryId,
      ...(extra || {}),
    });
    // Every settings control commits through here, so this is the one place
    // that has to know when it is safe to rebuild the DOM again.
    this._releaseRenderSuppression(pending);
    return pending;
  }

  _shellStyles() {
    return `
      <style>
        ha-card { padding: 12px 16px 16px; }
        .header { display: flex; align-items: center; gap: 12px; }
        .bubble {
          width: 38px; height: 38px; border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          background: rgba(var(--rgb-primary-color, 3,169,244), 0.16);
          flex-shrink: 0;
        }
        .bubble ha-icon { --mdc-icon-size: 20px; color: var(--primary-color); }
        .title { font-size: 16px; font-weight: 500; }
        .subtitle { font-size: 13px; color: var(--secondary-text-color); }
        .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }
        .tile {
          background: var(--secondary-background-color); border-radius: 12px;
          padding: 8px 12px;
        }
        .tile .value { font-size: 14px; font-weight: 500; }
        .tile .label { font-size: 12px; color: var(--secondary-text-color); }
        .row {
          display: flex; align-items: center; gap: 10px;
          background: var(--secondary-background-color);
          border-radius: 12px; padding: 10px 12px; margin-top: 8px;
        }
        .row .grow { flex: 1; font-size: 14px; }
        .banner {
          display: flex; align-items: center; gap: 10px; margin-top: 12px;
          border-radius: 12px; padding: 10px 12px; font-size: 12px;
          background: rgba(var(--rgb-warning-color, 255,166,0), 0.16);
          color: var(--primary-text-color);
        }
        .banner ha-icon { --mdc-icon-size: 18px; color: var(--warning-color); flex-shrink: 0; }
        .banner.alert { background: rgba(var(--rgb-error-color, 219,68,55), 0.14); align-items: flex-start; }
        .banner.alert ha-icon { color: var(--error-color); }
        .banner.solar { background: rgba(var(--rgb-success-color, 76,175,80), 0.16); }
        .banner.solar ha-icon { color: var(--success-color); }
        .footer {
          display: flex; justify-content: space-between; align-items: center;
          margin-top: 14px; padding-top: 10px;
          border-top: 1px solid var(--divider-color); font-size: 12px;
          color: var(--secondary-text-color);
        }
        button.action {
          border: 1px solid var(--divider-color); background: none;
          color: var(--primary-text-color); border-radius: 10px;
          padding: 6px 12px; font-size: 13px; cursor: pointer;
        }
        button.action:hover { background: var(--secondary-background-color); }
        input.num {
          width: 74px; text-align: right; font-size: 13px; padding: 4px 6px;
          border: 1px solid var(--divider-color); border-radius: 8px;
          background: var(--card-background-color); color: var(--primary-text-color);
        }
        select.pick {
          font-size: 13px; padding: 4px 6px; border-radius: 8px;
          border: 1px solid var(--divider-color);
          background: var(--card-background-color); color: var(--primary-text-color);
        }
        .missing { padding: 16px; color: var(--error-color); }
      </style>
    `;
  }

  _renderMissing() {
    this.innerHTML = `${this._shellStyles()}<ha-card><div class="missing">${escapeHtml(
      t(this._hass, "noEntity")
    )}: ${escapeHtml(this._config ? this._config.entity : "")}</div></ha-card>`;
  }
}

class LaundryStatusCard extends LaundryBaseCard {
  static getConfigElement() {
    return document.createElement("laundry-assistant-card-editor");
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) =>
        id.startsWith("sensor.") &&
        hass.states[id].attributes.appliance_type &&
        hass.states[id].attributes.known_phases
    );
    return { entity: entity || "" };
  }

  getCardSize() {
    return 5;
  }

  /**
   * Build the timeline segments.
   *
   * While a run is active the completed phases are shown with the time they
   * actually took, and the phases still to come share whatever the estimate
   * says is left. When nothing is running the last completed run is shown
   * instead, so the card is not empty between cycles.
   */
  _segments() {
    const a = this._attrs;
    const done = (a.phase_timeline || []).map((entry) => ({
      phase: entry.phase,
      seconds: entry.seconds,
      state: "done",
    }));

    if (!a.run_active) {
      const last = a.last_run;
      if (!last || !last.timeline || !last.timeline.length) return [];
      return last.timeline.map((entry) => ({
        phase: entry.phase,
        seconds: entry.seconds,
        state: "done",
      }));
    }

    const elapsedInPhase = Math.max(
      0,
      (a.elapsed_seconds || 0) - done.reduce((sum, s) => sum + s.seconds, 0)
    );
    const current = [{ phase: this._stateObj.state, seconds: elapsedInPhase, state: "active" }];

    const seen = new Set(done.map((s) => s.phase));
    seen.add(this._stateObj.state);
    const upcoming = (a.known_phases || []).filter((p) => !seen.has(p));
    const remaining = a.remaining_seconds;
    const share = upcoming.length && remaining ? remaining / upcoming.length : 0;

    return [
      ...done,
      ...current,
      ...upcoming.map((phase) => ({ phase, seconds: share, state: "upcoming" })),
    ];
  }

  _renderTimeline() {
    const segments = this._segments();
    if (!segments.length) return "";
    const total = segments.reduce((sum, s) => sum + Math.max(s.seconds, 1), 0);

    const bars = segments
      .map((s) => {
        const width = (Math.max(s.seconds, 1) / total) * 100;
        const color = PHASE_COLORS[s.phase] || "var(--primary-color)";
        const opacity = s.state === "upcoming" ? 0.28 : s.state === "done" ? 0.55 : 1;
        return `<div style="width:${width.toFixed(2)}%;background:${color};opacity:${opacity}"></div>`;
      })
      .join("");

    const labels = segments
      .filter((s) => s.state !== "upcoming")
      .map((s) => escapeHtml(t(this._hass, s.phase)))
      .join(" &middot; ");

    return `
      <div style="display:flex;height:16px;border-radius:6px;overflow:hidden;margin-top:14px;gap:1px">
        ${bars}
      </div>
      <div style="font-size:11px;color:var(--secondary-text-color);margin-top:4px">${labels}</div>
    `;
  }

  _renderCurve() {
    const curve = this._attrs.power_curve || [];
    if (curve.length < 2) return "";
    const max = Math.max(...curve, 1);
    const points = curve
      .map((w, i) => {
        const x = (i / (curve.length - 1)) * 100;
        const y = 30 - (w / max) * 28;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
    return `
      <svg viewBox="0 0 100 30" preserveAspectRatio="none"
           style="width:100%;height:38px;display:block;margin-top:10px">
        <polyline points="${points}" fill="none" stroke="var(--primary-color)"
                  stroke-width="0.8" vector-effect="non-scaling-stroke" />
      </svg>
    `;
  }

  _renderBanners() {
    const a = this._attrs;
    let html = "";
    if (a.update_interval_ok === false) {
      html += `
        <div class="banner">
          <ha-icon icon="mdi:alert"></ha-icon>
          <div>${escapeHtml(
            t(this._hass, "slowUpdates", { seconds: a.update_interval_seconds })
          )}</div>
        </div>`;
    }
    if (a.reminder_pending) {
      html += `
        <div class="banner">
          <ha-icon icon="mdi:bell-ring"></ha-icon>
          <div style="flex:1">${escapeHtml(t(this._hass, "reminderPending"))}</div>
          <button class="action" data-action="dismiss">${escapeHtml(
            t(this._hass, "dismiss")
          )}</button>
        </div>`;
    }
    // Only worth suggesting while nothing is running - during a cycle it is
    // too late to act on.
    if (!a.run_active && a.solar_covers_cycle && a.solar_saving_per_cycle) {
      html += `
        <div class="banner solar">
          <ha-icon icon="mdi:solar-power-variant"></ha-icon>
          <div>${escapeHtml(
            t(this._hass, "solarBanner", {
              saving: formatNumber(a.solar_saving_per_cycle, 2),
              currency: a.currency || "",
            })
          )}</div>
        </div>`;
    }
    const messages = a.anomaly_messages || [];
    if (messages.length) {
      html += `
        <div class="banner alert">
          <ha-icon icon="mdi:alert-decagram"></ha-icon>
          <div style="flex:1">
            <div style="font-weight:500;margin-bottom:2px">${escapeHtml(
              t(this._hass, "anomalyTitle")
            )}</div>
            ${messages.map((m) => `<div>${escapeHtml(m)}</div>`).join("")}
          </div>
          <button class="action" data-action="dismiss-anomalies">${escapeHtml(
            t(this._hass, "dismiss")
          )}</button>
        </div>`;
    }
    return html;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const state = this._stateObj;
    if (!state) {
      this._renderMissing();
      return;
    }

    const a = this._attrs;
    const currency = a.currency || "";
    const remaining = a.run_active ? formatDuration(a.remaining_seconds) : null;
    const icon =
      a.appliance_type === "dryer" ? "mdi:tumble-dryer" : "mdi:washing-machine";

    const programName = (a.current_program || {}).name;
    const subtitle = a.run_active
      ? [
          programName ? escapeHtml(programName) : null,
          t(this._hass, state.state),
          remaining,
        ]
          .filter(Boolean)
          .join(" &middot; ")
      : t(this._hass, state.state);

    this.innerHTML = `
      ${this._shellStyles()}
      <ha-card>
        <div class="header">
          <div class="bubble"><ha-icon icon="${icon}"></ha-icon></div>
          <div style="flex:1">
            <div class="title">${escapeHtml(state.attributes.friendly_name || "")}</div>
            <div class="subtitle">${subtitle}</div>
          </div>
          <div style="text-align:right">
            <div class="title">${formatNumber(a.watts, 0)} W</div>
            <div class="subtitle">${escapeHtml(t(this._hass, "power"))}</div>
          </div>
        </div>
        ${this._renderCurve()}
        ${this._renderTimeline()}
        <div class="tiles">
          <div class="tile">
            <div class="value">${formatNumber(a.cycle_energy_kwh, 2)} kWh</div>
            <div class="label">${escapeHtml(t(this._hass, "cycleEnergy"))}</div>
          </div>
          <div class="tile">
            <div class="value">${formatNumber(a.cycle_cost, 2)} ${escapeHtml(currency)}</div>
            <div class="label">${escapeHtml(t(this._hass, "cycleCost"))}</div>
          </div>
          <div class="tile">
            <div class="value">${
              a.run_active ? formatDuration(a.elapsed_seconds) : "-"
            }</div>
            <div class="label">${escapeHtml(t(this._hass, "elapsed"))}</div>
          </div>
          <div class="tile">
            <div class="value">${remaining || escapeHtml(t(this._hass, "unknown"))}</div>
            <div class="label">${escapeHtml(t(this._hass, "remaining"))}</div>
          </div>
        </div>
        ${this._renderBanners()}
        <div class="footer">
          <span>${escapeHtml(t(this._hass, "thisWeek"))}</span>
          <span>${a.week_cycles || 0} ${escapeHtml(
            t(this._hass, "cycles")
          )} &middot; ${formatNumber(a.week_energy_kwh, 1)} kWh &middot; ${formatNumber(
            a.week_cost,
            2
          )} ${escapeHtml(currency)}</span>
        </div>
      </ha-card>
    `;

    const dismiss = this.querySelector('[data-action="dismiss"]');
    if (dismiss) {
      dismiss.addEventListener("click", () => this._callService("dismiss_reminder"));
    }
    const dismissAnomalies = this.querySelector('[data-action="dismiss-anomalies"]');
    if (dismissAnomalies) {
      dismissAnomalies.addEventListener("click", () =>
        this._callService("dismiss_anomalies")
      );
    }
  }
}

class LaundrySettingsCard extends LaundryBaseCard {
  static getConfigElement() {
    return document.createElement("laundry-assistant-settings-card-editor");
  }

  static getStubConfig(hass) {
    return LaundryStatusCard.getStubConfig(hass);
  }

  getCardSize() {
    return 7;
  }

  _notifyTargets() {
    // The notify services a mobile app registers are the only sensible
    // targets; anything else in the notify domain is a broadcast.
    const services = (this._hass.services || {}).notify || {};
    return Object.keys(services)
      .filter((name) => name.startsWith("mobile_app_"))
      .sort();
  }

  _renderPrograms() {
    const programs = this._attrs.programs || [];
    if (!programs.length) return "";
    const rows = programs
      .map(
        (program) => `
        <div style="display:flex;align-items:center;gap:8px;margin-top:8px">
          <input class="num" style="flex:1;text-align:left" type="text"
                 data-program="${escapeHtml(program.id)}"
                 placeholder="${escapeHtml(t(this._hass, "unnamedProgram"))}"
                 value="${escapeHtml(program.name || "")}">
          <span style="font-size:12px;color:var(--secondary-text-color);white-space:nowrap">
            ${formatDuration(program.duration_seconds)} &middot; ${program.runs} ${escapeHtml(
              t(this._hass, "runsSuffix")
            )}
          </span>
        </div>`
      )
      .join("");

    return `
      <div class="row" style="flex-direction:column;align-items:stretch">
        <div style="font-size:14px">${escapeHtml(t(this._hass, "programs"))}</div>
        ${rows}
      </div>`;
  }

  _renderCalibration() {
    const a = this._attrs;
    const state = a.calibration_state;
    let text = t(this._hass, "calibrationIdle");
    let buttons = `<button class="action" data-action="start-cal">${escapeHtml(
      t(this._hass, "startCalibration")
    )}</button>`;

    if (state === "recording") {
      text = t(this._hass, "calibrationRecording", {
        done: a.calibration_runs || 0,
        needed: a.calibration_runs_required || 3,
      });
      buttons = `<button class="action" data-action="cancel-cal">${escapeHtml(
        t(this._hass, "cancelCalibration")
      )}</button>`;
    } else if (state === "ready") {
      const p = a.calibration_proposal || {};
      text = `${t(this._hass, "calibrationReady")} ${p.standby} / ${p.low} / ${p.medium} / ${p.high} W`;
      buttons = `
        <button class="action" data-action="apply-cal">${escapeHtml(
          t(this._hass, "applyCalibration")
        )}</button>
        <button class="action" data-action="cancel-cal">${escapeHtml(
          t(this._hass, "cancelCalibration")
        )}</button>`;
    }

    return `
      <div class="row" style="flex-wrap:wrap">
        <div class="grow" style="min-width:100%">
          <div style="font-size:14px">${escapeHtml(t(this._hass, "calibration"))}</div>
          <div style="font-size:12px;color:var(--secondary-text-color);margin-top:2px">${escapeHtml(
            text
          )}</div>
        </div>
        <div style="display:flex;gap:8px;margin-top:8px">${buttons}</div>
      </div>
    `;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const state = this._stateObj;
    if (!state) {
      this._renderMissing();
      return;
    }

    const a = this._attrs;
    const th = a.thresholds || {};
    const targets = this._notifyTargets();
    const options = [`<option value="">${escapeHtml(t(this._hass, "none"))}</option>`]
      .concat(
        targets.map(
          (name) =>
            `<option value="${escapeHtml(name)}"${
              a.notify_target === name ? " selected" : ""
            }>${escapeHtml(name)}</option>`
        )
      )
      .join("");

    this.innerHTML = `
      ${this._shellStyles()}
      <ha-card>
        <div class="header">
          <div class="bubble"><ha-icon icon="mdi:tune"></ha-icon></div>
          <div>
            <div class="title">${escapeHtml(t(this._hass, "settings"))}</div>
            <div class="subtitle">${escapeHtml(state.attributes.friendly_name || "")}</div>
          </div>
        </div>

        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "price"))}</div>
          <input class="num" type="number" step="0.01" min="0" data-field="price"
                 value="${inputNumber(a.price_per_kwh, 2)}">
          <span style="font-size:13px;color:var(--secondary-text-color)">${escapeHtml(
            a.currency || ""
          )}</span>
        </div>

        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "reminder"))}</div>
          <ha-switch data-field="reminder-enabled"${
            a.reminder_enabled ? " checked" : ""
          }></ha-switch>
        </div>
        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "reminderDelay"))}</div>
          <input class="num" type="number" min="1" max="1440" data-field="reminder-delay"
                 value="${a.reminder_delay_minutes}">
          <span style="font-size:13px;color:var(--secondary-text-color)">${escapeHtml(
            t(this._hass, "minutes")
          )}</span>
        </div>
        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "reminderRepeat"))}</div>
          <input class="num" type="number" min="1" max="1440" data-field="reminder-repeat"
                 value="${a.reminder_repeat_minutes}">
          <span style="font-size:13px;color:var(--secondary-text-color)">${escapeHtml(
            t(this._hass, "minutes")
          )}</span>
        </div>
        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "reminderMax"))}</div>
          <input class="num" type="number" min="1" max="10" data-field="reminder-max"
                 value="${a.reminder_max_repeats}">
          <span style="font-size:13px;color:var(--secondary-text-color)">${escapeHtml(
            t(this._hass, "times")
          )}</span>
        </div>

        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "notifyTarget"))}</div>
          <select class="pick" data-field="notify">${options}</select>
        </div>

        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "anomalyDetection"))}</div>
          <ha-switch data-field="anomaly-enabled"${
            a.anomaly_detection_enabled ? " checked" : ""
          }></ha-switch>
        </div>
        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "anomalySensitivity"))}</div>
          <input class="num" type="number" min="1.1" max="5" step="0.1"
                 data-field="anomaly-factor" value="${inputNumber(a.anomaly_factor, 1)}">
          <span style="font-size:13px;color:var(--secondary-text-color)">${escapeHtml(
            t(this._hass, "factorSuffix")
          )}</span>
        </div>

        <div class="row" style="flex-wrap:wrap">
          <div class="grow" style="min-width:100%;margin-bottom:8px">${escapeHtml(
            t(this._hass, "thresholds")
          )}</div>
          ${["standby", "low", "medium", "high"]
            .map(
              (band) => `
            <div style="display:flex;align-items:center;gap:6px;margin-right:10px">
              <span style="font-size:12px;color:var(--secondary-text-color)">${escapeHtml(
                t(this._hass, band)
              )}</span>
              <input class="num" style="width:64px" type="number" min="0" step="1"
                     data-field="th-${band}" value="${th[band]}">
            </div>`
            )
            .join("")}
          <button class="action" style="margin-top:8px" data-action="save-th">${escapeHtml(
            t(this._hass, "apply")
          )}</button>
        </div>

        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "solarEntity"))}</div>
          <input class="num" style="width:190px;text-align:left" type="text"
                 data-field="solar-entity" placeholder="sensor.pv_power"
                 value="${escapeHtml(a.solar_entity || "")}">
        </div>
        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "consumptionEntity"))}</div>
          <input class="num" style="width:190px;text-align:left" type="text"
                 data-field="consumption-entity" placeholder="sensor.house_power"
                 value="${escapeHtml(a.consumption_entity || "")}">
        </div>
        <div class="row">
          <div class="grow">${escapeHtml(t(this._hass, "feedInTariff"))}</div>
          <input class="num" type="number" step="0.01" min="0"
                 data-field="feed-in" value="${inputNumber(a.feed_in_tariff, 2)}">
          <span style="font-size:13px;color:var(--secondary-text-color)">${escapeHtml(
            a.currency || ""
          )}</span>
        </div>

        ${this._renderPrograms()}
        ${this._renderCalibration()}
      </ha-card>
    `;

    this._wire();
  }

  _wire() {
    const num = (field) => Number(this.querySelector(`[data-field="${field}"]`).value);

    const price = this.querySelector('[data-field="price"]');
    price.addEventListener("change", () =>
      this._callService("set_price", { price_per_kwh: Number(price.value) })
    );

    const pushReminder = (enabled) =>
      this._callService("set_reminder", {
        enabled,
        delay_minutes: num("reminder-delay"),
        repeat_minutes: num("reminder-repeat"),
        max_repeats: num("reminder-max"),
      });

    const toggle = this.querySelector('[data-field="reminder-enabled"]');
    toggle.addEventListener("change", (ev) => pushReminder(ev.target.checked));
    ["reminder-delay", "reminder-repeat", "reminder-max"].forEach((field) => {
      this.querySelector(`[data-field="${field}"]`).addEventListener("change", () =>
        pushReminder(toggle.checked)
      );
    });

    const notify = this.querySelector('[data-field="notify"]');
    notify.addEventListener("change", () =>
      this._callService("set_notify_target", { target: notify.value || null })
    );

    const anomalyToggle = this.querySelector('[data-field="anomaly-enabled"]');
    const pushAnomaly = (enabled) =>
      this._callService("set_anomaly_detection", {
        enabled,
        factor: num("anomaly-factor"),
      });
    anomalyToggle.addEventListener("change", (ev) => pushAnomaly(ev.target.checked));
    this.querySelector('[data-field="anomaly-factor"]').addEventListener("change", () =>
      pushAnomaly(anomalyToggle.checked)
    );

    this.querySelector('[data-action="save-th"]').addEventListener("click", () =>
      this._callService("set_thresholds", {
        thresholds: {
          standby: num("th-standby"),
          low: num("th-low"),
          medium: num("th-medium"),
          high: num("th-high"),
        },
      })
    );

    const pushSolar = () =>
      this._callService("set_solar", {
        solar_entity: this.querySelector('[data-field="solar-entity"]').value || null,
        consumption_entity:
          this.querySelector('[data-field="consumption-entity"]').value || null,
        feed_in_tariff: num("feed-in"),
      });
    ["solar-entity", "consumption-entity", "feed-in"].forEach((field) => {
      this.querySelector(`[data-field="${field}"]`).addEventListener("change", pushSolar);
    });

    this.querySelectorAll("[data-program]").forEach((input) => {
      input.addEventListener("change", () =>
        this._callService("set_program_name", {
          program_id: input.dataset.program,
          name: input.value,
        })
      );
    });

    const bind = (action, service) => {
      const el = this.querySelector(`[data-action="${action}"]`);
      if (el) el.addEventListener("click", () => this._callService(service));
    };
    bind("start-cal", "start_calibration");
    bind("cancel-cal", "cancel_calibration");
    bind("apply-cal", "apply_calibration");
  }
}

class LaundryCardEditorBase extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    activeLocale = lang(hass);
    // Same problem as the cards: rebuilding the DOM while the appliance
    // dropdown is open closes it. There is only one control here and it is
    // a select, so a plain focus check is enough - no suppression machinery
    // needed, because a select commits in a single interaction.
    const active = document.activeElement;
    if (active && this.contains(active)) return;
    this._render();
  }

  _candidates() {
    if (!this._hass) return [];
    return Object.keys(this._hass.states)
      .filter(
        (id) =>
          id.startsWith("sensor.") &&
          this._hass.states[id].attributes.appliance_type &&
          this._hass.states[id].attributes.known_phases
      )
      .sort();
  }

  _render() {
    if (!this._hass || !this._config) return;
    const options = this._candidates()
      .map(
        (id) =>
          `<option value="${escapeHtml(id)}"${
            this._config.entity === id ? " selected" : ""
          }>${escapeHtml(this._hass.states[id].attributes.friendly_name || id)}</option>`
      )
      .join("");

    this.innerHTML = `
      <div style="padding:8px 0">
        <label style="display:block;font-size:13px;margin-bottom:6px">Appliance</label>
        <select style="width:100%;padding:8px;border-radius:8px;
                       border:1px solid var(--divider-color);
                       background:var(--card-background-color);
                       color:var(--primary-text-color)">
          <option value="">-</option>
          ${options}
        </select>
      </div>
    `;

    this.querySelector("select").addEventListener("change", (ev) => {
      this._config = { ...this._config, entity: ev.target.value };
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        })
      );
    });
  }
}

class LaundryStatusCardEditor extends LaundryCardEditorBase {}
class LaundrySettingsCardEditor extends LaundryCardEditorBase {}

customElements.define("laundry-assistant-card", LaundryStatusCard);
customElements.define("laundry-assistant-settings-card", LaundrySettingsCard);
customElements.define("laundry-assistant-card-editor", LaundryStatusCardEditor);
customElements.define("laundry-assistant-settings-card-editor", LaundrySettingsCardEditor);

window.customCards = window.customCards || [];
window.customCards.push(
  {
    type: "laundry-assistant-card",
    name: "Laundry Assistant",
    description: "Phase timeline, live power curve and cycle cost for a washer or dryer.",
    preview: true,
  },
  {
    type: "laundry-assistant-settings-card",
    name: "Laundry Assistant - Settings",
    description: "Price, reminder, band thresholds and calibration.",
    preview: true,
  }
);
