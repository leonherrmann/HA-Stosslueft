/**
 * Stoßlüften dashboard card.
 *
 * Plain custom element, no build step: the file you are reading is the file
 * Home Assistant serves. Everything on screen comes from the attributes of a
 * single sensor (`sensor.*_airing_score`), so the card only needs one entity.
 */

const CARD_VERSION = "0.1.0";

const RATING_COLORS = {
  excellent: "var(--stosslueft-excellent, #2e7d32)",
  good: "var(--stosslueft-good, #689f38)",
  fair: "var(--stosslueft-fair, #f9a825)",
  poor: "var(--stosslueft-poor, #ef6c00)",
  bad: "var(--stosslueft-bad, #c62828)",
};

const TRANSLATIONS = {
  en: {
    title: "Airing",
    inside: "Inside",
    outside: "Outside",
    difference: "Difference",
    suggested: "Suggested",
    minutes: "min",
    rooms: "Rooms",
    no_rooms: "No rooms configured yet.",
    airing_now: "Airing now",
    so_far: "so far",
    last_airing: "Last airing",
    at_night: "at night",
    today: "Today",
    unavailable: "Airing score unavailable",
    ratings: {
      excellent: "Excellent",
      good: "Good",
      fair: "Mixed",
      poor: "Poor",
      bad: "Bad",
    },
    reasons: {
      no_data: "No temperature data",
      rain: "It is raining — windows stay shut",
      cooling_available: "{delta} K cooler outside, {duration} min is enough",
      warming_available: "{delta} K warmer outside, airing warms the room",
      too_warm_outside: "{delta} K warmer outside — would heat the flat up",
      heat_loss: "{delta} K colder outside — would just waste heat",
      drying: "Damp inside ({humidity} %), the outside air is drier",
      would_add_moisture:
        "Damp inside ({humidity} %), but outside air is wetter still",
      already_comfortable: "Comfortable already, little to gain",
    },
  },
  de: {
    title: "Stoßlüften",
    inside: "Innen",
    outside: "Außen",
    difference: "Differenz",
    suggested: "Empfohlen",
    minutes: "Min.",
    rooms: "Räume",
    no_rooms: "Noch keine Räume eingerichtet.",
    airing_now: "Lüftung läuft",
    so_far: "bisher",
    last_airing: "Letzte Lüftung",
    at_night: "nachts",
    today: "Heute",
    unavailable: "Lüftungsbewertung nicht verfügbar",
    ratings: {
      excellent: "Ausgezeichnet",
      good: "Gut",
      fair: "Mittel",
      poor: "Schlecht",
      bad: "Nicht lüften",
    },
    reasons: {
      no_data: "Keine Temperaturdaten",
      rain: "Es regnet — Fenster bleiben zu",
      cooling_available: "{delta} K kühler draußen, {duration} Min. reichen",
      warming_available: "{delta} K wärmer draußen, Lüften wärmt den Raum",
      too_warm_outside: "{delta} K wärmer draußen — würde die Wohnung aufheizen",
      heat_loss: "{delta} K kälter draußen — würde nur Wärme verschwenden",
      drying: "Feucht drinnen ({humidity} %), die Außenluft ist trockener",
      would_add_moisture:
        "Feucht drinnen ({humidity} %), aber die Außenluft ist noch feuchter",
      already_comfortable: "Schon angenehm, wenig zu gewinnen",
    },
  },
};

const ARC_LENGTH = Math.PI * 80;

const HTML_ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) => HTML_ESCAPES[character],
  );
}

function formatNumber(value, digits = 1) {
  return typeof value === "number" ? value.toFixed(digits) : "–";
}

function formatSigned(value, digits = 1) {
  if (typeof value !== "number") return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}`;
}

function minutesSince(isoString) {
  if (!isoString) return null;
  const started = Date.parse(isoString);
  if (Number.isNaN(started)) return null;
  return Math.max(0, Math.round((Date.now() - started) / 60000));
}

class StoslueftCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._lastRendered = null;
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (entityId) =>
        entityId.startsWith("sensor.") &&
        hass.states[entityId].attributes.rooms !== undefined &&
        hass.states[entityId].attributes.recommend_threshold !== undefined,
    );
    return { type: "custom:stosslueft-card", entity: entity || "" };
  }

  static getConfigElement() {
    return document.createElement("stosslueft-card-editor");
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("You need to pick the airing score sensor.");
    }
    this._config = { show_rooms: true, show_last_session: true, ...config };
    this._lastRendered = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    const rooms = this._state()?.attributes.rooms?.length ?? 0;
    return 4 + (this._config.show_rooms ? Math.ceil(rooms / 2) : 0);
  }

  _state() {
    if (!this._hass || !this._config.entity) return null;
    return this._hass.states[this._config.entity] || null;
  }

  _t() {
    const language = (this._hass?.locale?.language || "en").split("-")[0];
    return TRANSLATIONS[language] || TRANSLATIONS.en;
  }

  _reasonText(attributes) {
    const strings = this._t();
    const template = strings.reasons[attributes.reason_key];
    if (!template) return attributes.reason || "";
    const placeholders = attributes.reason_placeholders || {};
    return template.replace(/\{(\w+)\}/g, (match, name) => {
      const value = placeholders[name];
      if (typeof value !== "number") return match;
      return name === "duration" ? String(Math.round(value)) : value.toFixed(1);
    });
  }

  _render() {
    const state = this._state();
    if (!state) {
      this.shadowRoot.innerHTML = this._shell(
        `<div class="unavailable">${escapeHtml(this._t().unavailable)}</div>`,
      );
      return;
    }

    // Redrawing on every hass update would fight with the user opening the
    // last-airing details, so only redraw when this entity actually moved.
    const fingerprint = `${state.last_updated}|${this._hass.locale?.language}`;
    if (fingerprint === this._lastRendered) return;
    this._lastRendered = fingerprint;

    const attributes = state.attributes;
    const score = Number(state.state);
    const rating = attributes.rating || "bad";
    const color = RATING_COLORS[rating] || RATING_COLORS.bad;

    this.shadowRoot.innerHTML = this._shell(
      [
        this._gauge(score, rating, color, attributes),
        this._stats(attributes),
        this._banner(attributes),
        this._config.show_rooms ? this._rooms(attributes) : "",
        this._config.show_last_session ? this._lastSession(attributes) : "",
      ].join(""),
    );

    this.shadowRoot.querySelectorAll("[data-entity]").forEach((element) => {
      element.addEventListener("click", () => {
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            detail: { entityId: element.dataset.entity },
            bubbles: true,
            composed: true,
          }),
        );
      });
    });
  }

  _shell(content) {
    const title = this._config.name ?? this._t().title;
    return `${this._styles()}<ha-card header="${escapeHtml(title)}"><div class="content">${content}</div></ha-card>`;
  }

  _gauge(score, rating, color, attributes) {
    const strings = this._t();
    const value = Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0;
    const filled = (ARC_LENGTH * value) / 100;
    // Mark where the "yes, go and open the windows" threshold sits, so the
    // number has something to be read against.
    const threshold = attributes.recommend_threshold ?? 65;
    const angle = Math.PI * (1 - threshold / 100);
    const markX = 100 + Math.cos(angle) * 80;
    const markY = 100 - Math.sin(angle) * 80;

    return `
      <div class="gauge">
        <svg viewBox="0 0 200 112" role="img" aria-label="${value}">
          <path class="track" d="M 20 100 A 80 80 0 0 1 180 100" />
          <path class="value" d="M 20 100 A 80 80 0 0 1 180 100"
                stroke="${color}"
                stroke-dasharray="${filled.toFixed(2)} ${ARC_LENGTH.toFixed(2)}" />
          <circle class="threshold" cx="${markX.toFixed(2)}" cy="${markY.toFixed(2)}" r="3" />
          <text class="score" x="100" y="96" style="fill:${color}">${value}</text>
        </svg>
        <div class="rating" style="color:${color}">${escapeHtml(strings.ratings[rating] || rating)}</div>
        <div class="reason">${escapeHtml(this._reasonText(attributes))}</div>
      </div>`;
  }

  _stats(attributes) {
    const strings = this._t();
    const items = [
      [strings.inside, `${formatNumber(attributes.indoor_temperature)} °C`],
      [strings.outside, `${formatNumber(attributes.outdoor_temperature)} °C`],
      [strings.difference, `${formatSigned(attributes.temperature_delta)} K`],
      [
        strings.suggested,
        `${attributes.duration_minutes ?? "–"} ${strings.minutes}`,
      ],
    ];
    return `<div class="stats">${items
      .map(
        ([label, value]) =>
          `<div class="stat"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(value)}</span></div>`,
      )
      .join("")}</div>`;
  }

  _banner(attributes) {
    if (!attributes.airing_active || !attributes.active_session) return "";
    const strings = this._t();
    const session = attributes.active_session;
    const rooms = session.rooms || [];

    const gained = rooms
      .filter(
        (room) =>
          typeof room.temperature_start === "number" &&
          typeof room.temperature_min === "number",
      )
      .map((room) => room.temperature_start - room.temperature_min);
    const average = gained.length
      ? gained.reduce((total, value) => total + value, 0) / gained.length
      : null;

    const parts = [strings.airing_now];
    const elapsed = minutesSince(session.started);
    if (elapsed !== null) parts.push(`${elapsed} ${strings.minutes}`);
    if (average !== null)
      parts.push(`−${formatNumber(average)} K ${strings.so_far}`);

    const openRooms = (session.open_rooms || [])
      .map((roomId) => rooms.find((room) => room.room_id === roomId))
      .filter(Boolean)
      .map((room) => room.name);

    return `
      <div class="banner">
        <ha-icon icon="mdi:weather-windy"></ha-icon>
        <div>
          <div class="banner-title">${escapeHtml(parts.join(" · "))}</div>
          ${openRooms.length ? `<div class="banner-rooms">${escapeHtml(openRooms.join(", "))}</div>` : ""}
        </div>
      </div>`;
  }

  _rooms(attributes) {
    const strings = this._t();
    const rooms = attributes.rooms || [];
    if (!rooms.length) {
      return `<div class="section"><div class="empty">${escapeHtml(strings.no_rooms)}</div></div>`;
    }
    const sorted = [...rooms].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    return `
      <div class="section">
        <div class="section-title">${escapeHtml(strings.rooms)}</div>
        ${sorted.map((room) => this._roomRow(room)).join("")}
      </div>`;
  }

  _roomRow(room) {
    const color = RATING_COLORS[room.rating] || RATING_COLORS.bad;
    const score = typeof room.score === "number" ? room.score : 0;
    const clickable = room.temperature_entity
      ? ` data-entity="${escapeHtml(room.temperature_entity)}"`
      : "";
    const cooldown =
      typeof room.last_cooldown === "number" &&
      Math.abs(room.last_cooldown) >= 0.05
        ? `<span class="chip">−${formatNumber(room.last_cooldown)} K</span>`
        : "";
    return `
      <div class="room${clickable ? " clickable" : ""}"${clickable}>
        <div class="room-head">
          <span class="room-name">${escapeHtml(room.name)}</span>
          ${room.window_open ? '<ha-icon class="open" icon="mdi:window-open-variant"></ha-icon>' : ""}
          ${cooldown}
          <span class="room-temp">${formatNumber(room.temperature)} °C</span>
          <span class="room-score" style="color:${color}">${score}</span>
        </div>
        <div class="bar"><span style="width:${Math.max(0, Math.min(100, score))}%;background:${color}"></span></div>
      </div>`;
  }

  _lastSession(attributes) {
    const session = attributes.last_session;
    if (!session) return "";
    const strings = this._t();
    const when = session.at_night ? ` (${strings.at_night})` : "";
    const rooms = (session.rooms || [])
      .filter((room) => typeof room.delta === "number")
      .sort((a, b) => b.delta - a.delta);

    return `
      <details class="section last">
        <summary>
          <span>${escapeHtml(strings.last_airing)}${escapeHtml(when)}</span>
          <span class="summary-value">−${formatNumber(session.delta)} K · ${Math.round(session.duration_minutes ?? 0)} ${escapeHtml(strings.minutes)}</span>
        </summary>
        ${rooms
          .map(
            (room) =>
              `<div class="last-room"><span>${escapeHtml(room.name)}</span><span>−${formatNumber(room.delta)} K</span></div>`,
          )
          .join("")}
        <div class="last-room total"><span>${escapeHtml(strings.today)}</span><span>−${formatNumber(attributes.cooldown_today)} K</span></div>
      </details>`;
  }

  _styles() {
    return `<style>
      /* Do not rely on inheriting the text colour: the card has to read in
         both the light and the dark theme on its own. */
      .content { padding: 0 16px 16px; color: var(--primary-text-color, #212121); }
      .gauge { text-align: center; }
      .gauge svg { width: 100%; max-width: 260px; }
      .track { fill: none; stroke: var(--divider-color, #e0e0e0); stroke-width: 12; stroke-linecap: round; }
      .value { fill: none; stroke-width: 12; stroke-linecap: round; transition: stroke-dasharray 0.4s ease; }
      .threshold { fill: var(--secondary-text-color, #727272); }
      .score { font-size: 42px; font-weight: 600; text-anchor: middle; }
      .rating { font-size: 18px; font-weight: 600; }
      .reason { color: var(--secondary-text-color, #727272); font-size: 14px; margin-top: 4px; }
      .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(70px, 1fr)); gap: 8px; margin: 16px 0 4px; }
      .stat { display: flex; flex-direction: column; align-items: center; }
      .stat .label { font-size: 12px; color: var(--secondary-text-color, #727272); }
      .stat .value { font-size: 16px; font-weight: 500; }
      .banner { display: flex; align-items: center; gap: 12px; margin-top: 16px; padding: 10px 12px;
                border-radius: 10px; background: var(--info-color, #039be5); color: #fff; }
      .banner ha-icon { --mdc-icon-size: 24px; }
      .banner-title { font-weight: 500; }
      .banner-rooms { font-size: 13px; opacity: 0.9; }
      .section { margin-top: 16px; }
      .section-title { font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em;
                       color: var(--secondary-text-color, #727272); margin-bottom: 8px; }
      .room { padding: 6px 0; border-radius: 8px; }
      .room.clickable { cursor: pointer; }
      .room.clickable:hover { background: var(--secondary-background-color, #f5f5f5); }
      .room-head { display: flex; align-items: center; gap: 8px; font-size: 14px; }
      .room-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .room-temp { color: var(--secondary-text-color, #727272); }
      .room-score { font-weight: 600; min-width: 26px; text-align: right; }
      .room .open { color: var(--info-color, #039be5); --mdc-icon-size: 18px; }
      .chip { font-size: 12px; padding: 1px 6px; border-radius: 10px;
              background: var(--secondary-background-color, #f5f5f5); color: var(--secondary-text-color, #727272); }
      .bar { height: 4px; border-radius: 2px; margin-top: 4px; background: var(--divider-color, #e0e0e0); overflow: hidden; }
      .bar span { display: block; height: 100%; border-radius: 2px; transition: width 0.4s ease; }
      details.last summary { cursor: pointer; display: flex; justify-content: space-between; gap: 8px;
                             font-size: 14px; padding: 6px 0; }
      .summary-value { font-weight: 500; }
      .last-room { display: flex; justify-content: space-between; font-size: 13px; padding: 3px 0;
                   color: var(--secondary-text-color, #727272); }
      .last-room.total { border-top: 1px solid var(--divider-color, #e0e0e0); margin-top: 4px;
                         padding-top: 6px; color: var(--primary-text-color, #212121); }
      .unavailable, .empty { color: var(--secondary-text-color, #727272); padding: 8px 0; }
    </style>`;
  }
}

class StoslueftCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _update() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        ({
          entity: "Airing score sensor",
          name: "Title",
          show_rooms: "Show the room breakdown",
          show_last_session: "Show the last airing",
        })[schema.name] || schema.name;
      this._form.addEventListener("value-changed", (event) => {
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: event.detail.value },
            bubbles: true,
            composed: true,
          }),
        );
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = [
      {
        name: "entity",
        required: true,
        selector: {
          entity: { filter: [{ integration: "stosslueft", domain: "sensor" }] },
        },
      },
      { name: "name", selector: { text: {} } },
      { name: "show_rooms", selector: { boolean: {} } },
      { name: "show_last_session", selector: { boolean: {} } },
    ];
    this._form.data = {
      show_rooms: true,
      show_last_session: true,
      ...this._config,
    };
  }
}

if (!customElements.get("stosslueft-card")) {
  customElements.define("stosslueft-card", StoslueftCard);
  customElements.define("stosslueft-card-editor", StoslueftCardEditor);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "stosslueft-card",
    name: "Stoßlüften",
    description:
      "Shows whether it is worth opening every window, room by room, and what the last airing achieved.",
    preview: true,
    documentationURL: "https://github.com/leonherrmann/HA-Stosslueft",
  });

  console.info(
    `%c STOSSLUEFT-CARD %c ${CARD_VERSION} `,
    "background:#2e7d32;color:#fff",
    "",
  );
}
