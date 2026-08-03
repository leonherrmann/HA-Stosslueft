/**
 * Stoßlüften dashboard card.
 *
 * Plain custom element, no build step: the file you are reading is the file
 * Home Assistant serves. Everything on screen comes from the attributes of a
 * single sensor (`sensor.*_airing_score`), so the card only needs one entity.
 */

const CARD_VERSION = "0.2.0";

const RATING_COLORS = {
  good: "var(--stosslueft-good, #2e7d32)",
  neutral: "var(--stosslueft-neutral, #f9a825)",
  bad: "var(--stosslueft-bad, #c62828)",
};

function ratingColor(rating) {
  return RATING_COLORS[rating] || RATING_COLORS.bad;
}

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
      good: "Good",
      neutral: "Neutral",
      bad: "Bad",
    },
    reasons: {
      no_data: "No temperature data",
      rain: "It is raining — windows stay shut",
      cooling_available: "{delta} °C cooler outside, {duration} min is enough",
      warming_available: "{delta} °C warmer outside, airing warms the room",
      too_warm_outside: "{delta} °C warmer outside — would heat the flat up",
      heat_loss: "{delta} °C colder outside — would just waste heat",
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
      good: "Gut",
      neutral: "Neutral",
      bad: "Schlecht",
    },
    reasons: {
      no_data: "Keine Temperaturdaten",
      rain: "Es regnet — Fenster bleiben zu",
      cooling_available: "{delta} °C kühler draußen, {duration} Min. reichen",
      warming_available: "{delta} °C wärmer draußen, Lüften wärmt den Raum",
      too_warm_outside: "{delta} °C wärmer draußen — würde die Wohnung aufheizen",
      heat_loss: "{delta} °C kälter draußen — würde nur Wärme verschwenden",
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

/**
 * Shared plumbing for every card in this file: config handling, looking the
 * score sensor up, translations, and only redrawing when something moved.
 * Subclasses implement `_body(state)` and the static `defaults`.
 */
class StoslueftBaseCard extends HTMLElement {
  static defaults = {};

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._lastRendered = null;
  }

  /** Find an airing score sensor to preselect in the card picker. */
  static findScoreEntity(hass) {
    return (
      Object.keys(hass.states).find(
        (entityId) =>
          entityId.startsWith("sensor.") &&
          hass.states[entityId].attributes.rooms !== undefined &&
          hass.states[entityId].attributes.recommend_threshold !== undefined,
      ) || ""
    );
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("You need to pick the airing score sensor.");
    }
    this._config = { ...this.constructor.defaults, ...config };
    this._lastRendered = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
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
      this.shadowRoot.innerHTML = this._unavailable();
      return;
    }

    // Redrawing on every hass update would fight with the user opening the
    // last-airing details, so only redraw when something actually moved.
    const fingerprint = `${state.last_updated}|${this._hass.locale?.language}|${JSON.stringify(this._config)}`;
    if (fingerprint === this._lastRendered) return;
    this._lastRendered = fingerprint;

    this.shadowRoot.innerHTML = this._body(state);

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
}

class StoslueftCard extends StoslueftBaseCard {
  static defaults = { show_rooms: true, show_last_session: true };

  static getStubConfig(hass) {
    return {
      type: "custom:stosslueft-card",
      entity: StoslueftBaseCard.findScoreEntity(hass),
    };
  }

  static getConfigElement() {
    return document.createElement("stosslueft-card-editor");
  }

  getCardSize() {
    const rooms = this._state()?.attributes.rooms?.length ?? 0;
    return 4 + (this._config.show_rooms ? Math.ceil(rooms / 2) : 0);
  }

  _unavailable() {
    return this._shell(
      `<div class="unavailable">${escapeHtml(this._t().unavailable)}</div>`,
    );
  }

  _body(state) {
    const attributes = state.attributes;
    const rating = attributes.rating || "bad";
    const color = ratingColor(rating);
    return this._shell(
      [
        this._gauge(Number(state.state), rating, color, attributes),
        this._stats(attributes),
        this._banner(attributes),
        this._config.show_rooms ? this._rooms(attributes) : "",
        this._config.show_last_session ? this._lastSession(attributes) : "",
      ].join(""),
    );
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
      [strings.difference, `${formatSigned(attributes.temperature_delta)} °C`],
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
      parts.push(`−${formatNumber(average)} °C ${strings.so_far}`);

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
    const color = ratingColor(room.rating);
    const score = typeof room.score === "number" ? room.score : 0;
    const clickable = room.temperature_entity
      ? ` data-entity="${escapeHtml(room.temperature_entity)}"`
      : "";
    const cooldown =
      typeof room.last_cooldown === "number" &&
      Math.abs(room.last_cooldown) >= 0.05
        ? `<span class="chip">−${formatNumber(room.last_cooldown)} °C</span>`
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
          <span class="summary-value">−${formatNumber(session.delta)} °C · ${Math.round(session.duration_minutes ?? 0)} ${escapeHtml(strings.minutes)}</span>
        </summary>
        ${rooms
          .map(
            (room) =>
              `<div class="last-room"><span>${escapeHtml(room.name)}</span><span>−${formatNumber(room.delta)} °C</span></div>`,
          )
          .join("")}
        <div class="last-room total"><span>${escapeHtml(strings.today)}</span><span>−${formatNumber(attributes.cooldown_today)} °C</span></div>
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

/** One row: verdict, score and the two temperatures. No gauge, no rooms. */
class StoslueftCompactCard extends StoslueftBaseCard {
  static defaults = { show_score: true };

  static getStubConfig(hass) {
    return {
      type: "custom:stosslueft-compact-card",
      entity: StoslueftBaseCard.findScoreEntity(hass),
    };
  }

  static getConfigElement() {
    return document.createElement("stosslueft-compact-card-editor");
  }

  getCardSize() {
    return 1;
  }

  _unavailable() {
    return `${this._styles()}<ha-card><div class="row"><span class="muted">${escapeHtml(this._t().unavailable)}</span></div></ha-card>`;
  }

  _body(state) {
    const strings = this._t();
    const attributes = state.attributes;
    const rating = attributes.rating || "bad";
    const color = ratingColor(rating);
    const airing = attributes.airing_active;

    return `${this._styles()}
      <ha-card>
        <div class="row" data-entity="${escapeHtml(this._config.entity)}"
             title="${escapeHtml(this._reasonText(attributes))}">
          <ha-icon icon="mdi:window-open-variant" style="color:${color}"></ha-icon>
          ${this._config.name ? `<span class="name">${escapeHtml(this._config.name)}</span>` : ""}
          <span class="verdict" style="color:${color}">${escapeHtml(strings.ratings[rating] || rating)}</span>
          ${this._config.show_score ? `<span class="score">${escapeHtml(state.state)}</span>` : ""}
          <span class="spacer"></span>
          ${airing ? '<ha-icon class="airing" icon="mdi:weather-windy"></ha-icon>' : ""}
          <span class="temps">
            ${formatNumber(attributes.indoor_temperature)}
            <span class="arrow">→</span>
            ${formatNumber(attributes.outdoor_temperature)} °C
          </span>
        </div>
      </ha-card>`;
  }

  _styles() {
    return `<style>
      .row { display: flex; align-items: center; gap: 10px; padding: 12px 16px; cursor: pointer;
             color: var(--primary-text-color, #212121); }
      .row:hover { background: var(--secondary-background-color, #f5f5f5); }
      ha-icon { --mdc-icon-size: 24px; flex: none; }
      .name { font-weight: 500; }
      .verdict { font-weight: 600; }
      .score { color: var(--secondary-text-color, #727272); font-size: 14px; }
      .spacer { flex: 1; }
      .airing { color: var(--info-color, #039be5); --mdc-icon-size: 18px; }
      .temps { white-space: nowrap; font-variant-numeric: tabular-nums; }
      .arrow { color: var(--secondary-text-color, #727272); margin: 0 2px; }
      .muted { color: var(--secondary-text-color, #727272); }
    </style>`;
  }
}

/** A row of traffic-light chips: the flat, then one per room. */
class StoslueftChipsCard extends StoslueftBaseCard {
  static defaults = { show_overall: true, show_names: false };

  static getStubConfig(hass) {
    return {
      type: "custom:stosslueft-chips-card",
      entity: StoslueftBaseCard.findScoreEntity(hass),
    };
  }

  static getConfigElement() {
    return document.createElement("stosslueft-chips-card-editor");
  }

  getCardSize() {
    return 1;
  }

  _unavailable() {
    return `${this._styles()}<div class="chips"><span class="muted">${escapeHtml(this._t().unavailable)}</span></div>`;
  }

  _body(state) {
    const strings = this._t();
    const attributes = state.attributes;
    const wanted = this._config.rooms;
    const rooms = (attributes.rooms || []).filter(
      (room) => !Array.isArray(wanted) || wanted.includes(room.room_id),
    );

    const chips = [];
    if (this._config.show_overall) {
      chips.push(
        this._chip({
          label: this._config.name ?? strings.title,
          score: state.state,
          rating: attributes.rating,
          entity: this._config.entity,
          icon: attributes.airing_active
            ? "mdi:weather-windy"
            : "mdi:home-thermometer-outline",
          showLabel: true,
        }),
      );
    }
    for (const room of rooms) {
      chips.push(
        this._chip({
          label: room.name,
          score: room.score,
          rating: room.rating,
          entity: room.temperature_entity,
          icon: room.window_open
            ? "mdi:window-open-variant"
            : "mdi:window-closed-variant",
          showLabel: this._config.show_names,
        }),
      );
    }
    return `${this._styles()}<div class="chips">${chips.join("")}</div>`;
  }

  _chip({ label, score, rating, entity, icon, showLabel }) {
    const color = ratingColor(rating);
    const clickable = entity ? ` data-entity="${escapeHtml(entity)}"` : "";
    // The name is always in the tooltip, even when it is not on screen --
    // otherwise a row of icons is unreadable.
    return `
      <div class="chip${entity ? " clickable" : ""}"${clickable} title="${escapeHtml(label)}">
        <ha-icon icon="${escapeHtml(icon)}" style="color:${color}"></ha-icon>
        ${showLabel ? `<span class="label">${escapeHtml(label)}</span>` : ""}
        <span class="score" style="color:${color}">${escapeHtml(score ?? "–")}</span>
      </div>`;
  }

  _styles() {
    return `<style>
      .chips { display: flex; flex-wrap: wrap; gap: 8px; }
      .chip { display: flex; align-items: center; gap: 6px; height: 36px; padding: 0 12px;
              border-radius: 18px; background: var(--ha-card-background, var(--card-background-color, #fff));
              box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,.12));
              color: var(--primary-text-color, #212121); font-size: 14px; }
      .chip.clickable { cursor: pointer; }
      .chip.clickable:hover { background: var(--secondary-background-color, #f5f5f5); }
      ha-icon { --mdc-icon-size: 20px; flex: none; }
      .label { white-space: nowrap; }
      .score { font-weight: 600; font-variant-numeric: tabular-nums; }
      .muted { color: var(--secondary-text-color, #727272); }
    </style>`;
  }
}

/**
 * A single badge for the view's badge row: the whole flat, or one room.
 *
 * Note this is a *badge*, not a card, and it only works in a view's `badges:`
 * list. Home Assistant's heading cards accept their own entity and button
 * heading badges only -- there is no registry for custom ones -- so for a
 * badge inside a section heading, point a built-in entity heading badge at
 * `sensor.*_<room>_airing_score` instead.
 */
class StoslueftBadge extends StoslueftBaseCard {
  static defaults = { show_name: true };

  static getStubConfig(hass) {
    return { entity: StoslueftBaseCard.findScoreEntity(hass) };
  }

  static getConfigElement() {
    return document.createElement("stosslueft-badge-editor");
  }

  _unavailable() {
    return `${this._styles()}<div class="badge"><span class="muted">–</span></div>`;
  }

  _body(state) {
    const strings = this._t();
    const attributes = state.attributes;
    const roomId = this._config.room;

    let view;
    if (roomId) {
      const room = (attributes.rooms || []).find(
        (candidate) => candidate.room_id === roomId,
      );
      if (!room) return this._unavailable();
      view = {
        label: this._config.name ?? room.name,
        score: room.score,
        rating: room.rating,
        entity: room.temperature_entity,
        icon: room.window_open
          ? "mdi:window-open-variant"
          : "mdi:window-closed-variant",
      };
    } else {
      view = {
        label: this._config.name ?? strings.title,
        score: state.state,
        rating: attributes.rating,
        entity: this._config.entity,
        icon: attributes.airing_active
          ? "mdi:weather-windy"
          : "mdi:home-thermometer-outline",
      };
    }

    const color = ratingColor(view.rating);
    return `${this._styles()}
      <div class="badge${view.entity ? " clickable" : ""}"
           ${view.entity ? `data-entity="${escapeHtml(view.entity)}"` : ""}
           title="${escapeHtml(view.label)}">
        <ha-icon icon="${escapeHtml(view.icon)}" style="color:${color}"></ha-icon>
        <span class="value" style="color:${color}">${escapeHtml(view.score ?? "–")}</span>
        ${this._config.show_name ? `<span class="label">${escapeHtml(view.label)}</span>` : ""}
      </div>`;
  }

  _styles() {
    return `<style>
      :host { display: inline-block; }
      .badge { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 12px;
               border-radius: 18px; box-sizing: border-box;
               background: var(--ha-card-background, var(--card-background-color, #fff));
               box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,.12));
               border: var(--ha-card-border-width, 1px) solid transparent;
               color: var(--primary-text-color, #212121); font-size: 14px; line-height: 1; }
      .badge.clickable { cursor: pointer; }
      .badge.clickable:hover { background: var(--secondary-background-color, #f5f5f5); }
      ha-icon { --mdc-icon-size: 18px; flex: none; }
      .value { font-weight: 600; font-variant-numeric: tabular-nums; }
      .label { color: var(--secondary-text-color, #727272); white-space: nowrap; }
      .muted { color: var(--secondary-text-color, #727272); }
    </style>`;
  }
}

const EDITOR_LABELS = {
  entity: "Airing score sensor",
  name: "Title",
  show_rooms: "Show the room breakdown",
  show_last_session: "Show the last airing",
  show_score: "Show the score number",
  show_overall: "Show a chip for the whole flat",
  show_names: "Show room names on the chips",
  rooms: "Rooms (leave empty for all)",
  room: "Room (leave empty for the whole flat)",
  show_name: "Show the name",
};

const ENTITY_FIELD = {
  name: "entity",
  required: true,
  selector: {
    entity: { filter: [{ integration: "stosslueft", domain: "sensor" }] },
  },
};

/** Visual editor driven by an `ha-form` schema the subclass supplies. */
class StoslueftEditorBase extends HTMLElement {
  static schema = [ENTITY_FIELD];
  static defaults = {};

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
        EDITOR_LABELS[schema.name] || schema.name;
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
    this._form.schema = this._schema();
    this._form.data = { ...this.constructor.defaults, ...this._config };
  }

  /** Overridden where the schema depends on the picked entity. */
  _schema() {
    return this.constructor.schema;
  }
}

/** Offer the configured rooms as a dropdown, read off the score sensor. */
function roomOptions(hass, entityId) {
  const rooms = hass?.states?.[entityId]?.attributes?.rooms || [];
  return rooms.map((room) => ({ value: room.room_id, label: room.name }));
}

class StoslueftCardEditor extends StoslueftEditorBase {
  static defaults = StoslueftCard.defaults;
  static schema = [
    ENTITY_FIELD,
    { name: "name", selector: { text: {} } },
    { name: "show_rooms", selector: { boolean: {} } },
    { name: "show_last_session", selector: { boolean: {} } },
  ];
}

class StoslueftCompactCardEditor extends StoslueftEditorBase {
  static defaults = StoslueftCompactCard.defaults;
  static schema = [
    ENTITY_FIELD,
    { name: "name", selector: { text: {} } },
    { name: "show_score", selector: { boolean: {} } },
  ];
}

class StoslueftChipsCardEditor extends StoslueftEditorBase {
  static defaults = StoslueftChipsCard.defaults;
  static schema = [
    ENTITY_FIELD,
    { name: "name", selector: { text: {} } },
    { name: "show_overall", selector: { boolean: {} } },
    { name: "show_names", selector: { boolean: {} } },
  ];

  _schema() {
    const options = roomOptions(this._hass, this._config?.entity);
    if (!options.length) return this.constructor.schema;
    return [
      ...this.constructor.schema,
      { name: "rooms", selector: { select: { options, multiple: true } } },
    ];
  }
}

class StoslueftBadgeEditor extends StoslueftEditorBase {
  static defaults = StoslueftBadge.defaults;
  static schema = [
    ENTITY_FIELD,
    { name: "name", selector: { text: {} } },
    { name: "show_name", selector: { boolean: {} } },
  ];

  _schema() {
    const options = roomOptions(this._hass, this._config?.entity);
    if (!options.length) return this.constructor.schema;
    // Inserted after the entity so the room reads as a narrowing of it.
    return [
      ENTITY_FIELD,
      { name: "room", selector: { select: { options } } },
      ...this.constructor.schema.slice(1),
    ];
  }
}

const CARDS = [
  {
    tag: "stosslueft-card",
    element: StoslueftCard,
    editor: StoslueftCardEditor,
    name: "Stoßlüften",
    description:
      "Shows whether it is worth opening every window, room by room, and what the last airing achieved.",
  },
  {
    tag: "stosslueft-compact-card",
    element: StoslueftCompactCard,
    editor: StoslueftCompactCardEditor,
    name: "Stoßlüften (compact)",
    description: "One row: the verdict, the score and inside vs. outside.",
  },
  {
    tag: "stosslueft-chips-card",
    element: StoslueftChipsCard,
    editor: StoslueftChipsCardEditor,
    name: "Stoßlüften (chips)",
    description: "A traffic-light chip for the flat and one for every room.",
  },
];

const DOCS_URL = "https://github.com/leonherrmann/HA-Stosslueft";

if (!customElements.get("stosslueft-card")) {
  window.customCards = window.customCards || [];
  for (const card of CARDS) {
    customElements.define(card.tag, card.element);
    customElements.define(`${card.tag}-editor`, card.editor);
    window.customCards.push({
      type: card.tag,
      name: card.name,
      description: card.description,
      preview: true,
      documentationURL: DOCS_URL,
    });
  }

  // Badges live in their own registry and only work in a view's `badges:`
  // list -- heading cards accept built-in heading badges only.
  customElements.define("stosslueft-badge", StoslueftBadge);
  customElements.define("stosslueft-badge-editor", StoslueftBadgeEditor);
  window.customBadges = window.customBadges || [];
  window.customBadges.push({
    type: "stosslueft-badge",
    name: "Stoßlüften",
    description: "Airing score for the flat, or for one room.",
    preview: true,
    documentationURL: DOCS_URL,
  });

  console.info(
    `%c STOSSLUEFT-CARD %c ${CARD_VERSION} `,
    "background:#2e7d32;color:#fff",
    "",
  );
}
