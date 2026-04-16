// blaueis-ac-card.js — iteration 3
// Custom Lovelace card for Blaueis Midea vane-angle control.
// Ships two elements:
//   <blaueis-vane-slider>      the discrete slider primitive
//   <blaueis-air-direction>    the card (composes 2 sliders, wires to HA)
//
// No build step — imports Lit from esm.sh at load time. Iteration 5 will
// bundle it; iteration 3 is for design validation on real HA entities.

import { LitElement, html, css } from 'https://esm.sh/lit@3.2.0';

// ─────────────────────────────────────────────────────────────────────────
// blaueis-vane-slider
// ─────────────────────────────────────────────────────────────────────────

class BlaueisVaneSlider extends LitElement {
  static properties = {
    orientation: { type: String,  reflect: true },
    axis:        { type: String,  reflect: true },
    target:      { type: Number,  reflect: true },
    actual:      { type: Number,  reflect: true },
    swinging:    { type: Boolean, reflect: true },
    disabled:    { type: Boolean, reflect: true },
  };

  static POSITIONS = [1, 25, 50, 75, 100];
  static LABELS_BY_AXIS = {
    lr:  ['L',   '25', '50', '75', 'R'  ],
    ud:  ['top', '25', '50', '75', 'btm'],
    raw: ['1',   '25', '50', '75', '100'],
  };

  constructor() {
    super();
    this.orientation = 'horizontal';
    this.axis = 'lr';
    this.target = null;
    this.actual = 50;
    this.swinging = false;
    this.disabled = false;
  }

  _labels() {
    return BlaueisVaneSlider.LABELS_BY_AXIS[this.axis]
        ?? BlaueisVaneSlider.LABELS_BY_AXIS.raw;
  }

  _highlightTarget() {
    return !this.disabled && !this.swinging && this.target != null;
  }

  _select(value) {
    if (this.disabled) return;
    this.target = value;
    this.dispatchEvent(new CustomEvent('target-change', {
      detail: { value }, bubbles: true, composed: true,
    }));
  }

  _actualPct() {
    const a = this.actual ?? 0;
    if (a <= 1)   return 10;
    if (a >= 100) return 90;
    return 10 + ((a - 1) / 99) * 80;
  }

  static styles = css`
    :host {
      display: inline-block;
      --cell-bg: #3a3a3c;
      --cell-hover: #48484a;
      --cell-selected: #0a84ff;
      --cell-text: rgba(255, 255, 255, 0.78);
      --cell-text-selected: #fff;
      --caret-color: #30d158;
    }
    :host([disabled]) {
      --cell-hover: #3a3a3c;
      opacity: 0.38;
      pointer-events: none;
    }

    .container { position: relative; display: flex; }
    :host([orientation="horizontal"]) { width: 100%; display: block; }
    :host([orientation="horizontal"]) .container { flex-direction: column; width: 100%; }
    :host([orientation="vertical"])   .container { flex-direction: row;    height: 18rem; }

    .track {
      display: grid;
      gap: 2px;
      background: rgba(0, 0, 0, 0.25);
      border-radius: 10px;
      padding: 2px;
    }
    :host([orientation="horizontal"]) .track {
      grid-template-columns: repeat(5, 1fr);
      width: 100%;
    }
    :host([orientation="vertical"]) .track {
      grid-template-rows: repeat(5, 1fr);
      width: 3.5rem;
      height: 100%;
    }

    .cell {
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--cell-bg);
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.75rem;
      color: var(--cell-text);
      user-select: none;
      transition: background 0.15s;
    }
    .cell:hover { background: var(--cell-hover); }
    .cell.selected {
      background: var(--cell-selected);
      color: var(--cell-text-selected);
    }
    .cell.selected::after {
      content: ' ●';
      margin-left: 2px;
      opacity: 0.75;
      font-size: 0.6rem;
    }

    :host([orientation="horizontal"]) .cell { aspect-ratio: 1.4 / 1; }
    :host([orientation="vertical"])   .cell { min-height: 2rem; }

    .caret-rail { position: relative; }
    :host([orientation="horizontal"]) .caret-rail {
      height: 1.6rem;
      margin-top: 4px;
      width: 100%;
    }
    :host([orientation="vertical"]) .caret-rail {
      width: 2.4rem;
      margin-left: 4px;
      height: 100%;
    }

    .caret, .caret-val {
      position: absolute;
      color: var(--caret-color);
      font-family: ui-monospace, monospace;
      transition: top 0.45s cubic-bezier(0.4, 0.0, 0.2, 1),
                  left 0.45s cubic-bezier(0.4, 0.0, 0.2, 1);
    }
    .caret { font-weight: 700; font-size: 1.05rem; line-height: 1; }
    .caret-val { font-size: 0.62rem; opacity: 0.75; }

    :host([orientation="horizontal"]) .caret     { top: 0; transform: translateX(-50%); }
    :host([orientation="horizontal"]) .caret-val { top: 1.15rem; transform: translateX(-50%); }
    :host([orientation="vertical"])   .caret     { left: 0; transform: translateY(-50%) rotate(-90deg); transform-origin: center; }
    :host([orientation="vertical"])   .caret-val { left: 1.1rem; transform: translateY(-50%); width: max-content; }

    .swing-badge {
      position: absolute;
      top: -0.9rem;
      right: 0;
      font-size: 0.6rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #ff9f0a;
      opacity: 0.85;
    }
  `;

  render() {
    const pct = this._actualPct();
    const labels = this._labels();
    const showTarget = this._highlightTarget();
    const axisStyle = this.orientation === 'vertical'
      ? `top: ${pct}%;`
      : `left: ${pct}%;`;

    return html`
      <div class="container">
        ${this.swinging ? html`<div class="swing-badge">Swinging</div>` : ''}
        <div class="track" role="group" aria-label="Vane angle">
          ${BlaueisVaneSlider.POSITIONS.map((pos, i) => html`
            <div
              class="cell ${showTarget && this.target === pos ? 'selected' : ''}"
              role="button"
              tabindex="0"
              aria-pressed=${showTarget && this.target === pos}
              @click=${() => this._select(pos)}
              @keydown=${(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), this._select(pos))}
            >${labels[i]}</div>
          `)}
        </div>
        <div class="caret-rail" aria-hidden="true">
          <div class="caret" style=${axisStyle}>▲</div>
          <div class="caret-val" style=${axisStyle}>${Math.round(this.actual)}</div>
        </div>
      </div>
    `;
  }
}

customElements.define('blaueis-vane-slider', BlaueisVaneSlider);

// ─────────────────────────────────────────────────────────────────────────
// blaueis-air-direction (the card)
// ─────────────────────────────────────────────────────────────────────────

class BlaueisAirDirection extends LitElement {
  static properties = {
    hass:          { attribute: false },
    _config:       { state: true },
    _lrCommitted:  { state: true },
    _udCommitted:  { state: true },
  };

  constructor() {
    super();
    this._lrCommitted = false;
    this._udCommitted = false;
  }

  // ── Lovelace card API ────────────────────────────────────
  setConfig(config) {
    const required = ['lr_target', 'ud_target', 'lr_actual', 'ud_actual'];
    for (const k of required) {
      if (!config[k]) throw new Error(`blaueis-air-direction: missing config.${k}`);
    }
    this._config = config;
  }

  getCardSize() { return 3; }

  // ── State helpers ────────────────────────────────────────
  _num(entity_id) {
    const s = this.hass?.states?.[entity_id];
    if (!s) return null;
    const n = parseFloat(s.state);
    return Number.isNaN(n) ? null : n;
  }

  _bool(entity_id) {
    if (!entity_id) return false;
    const s = this.hass?.states?.[entity_id];
    if (!s) return false;
    const v = String(s.state).toLowerCase();
    return v === 'true' || v === 'on' || v === '1';
  }

  _deviceOff() {
    const eid = this._config.climate;
    if (!eid) return false;
    const s = this.hass?.states?.[eid];
    return s?.state === 'off' || s?.state === 'unavailable';
  }

  _callSelect(entity_id, value) {
    this.hass.callService('select', 'select_option', {
      entity_id,
      option: String(value),
    });
  }

  _onLR(e) {
    this._lrCommitted = true;
    this._callSelect(this._config.lr_target, e.detail.value);
  }

  _onUD(e) {
    this._udCommitted = true;
    this._callSelect(this._config.ud_target, e.detail.value);
  }

  // ── Styles ───────────────────────────────────────────────
  static styles = css`
    :host { display: block; }
    .card {
      background: var(--ha-card-background, var(--card-background-color, #2c2c2e));
      color: var(--primary-text-color, #fff);
      border-radius: var(--ha-card-border-radius, 14px);
      padding: 1.25rem 1rem 1rem;
      box-shadow: var(--ha-card-box-shadow, none);
      border: var(--ha-card-border-width, 0) solid var(--divider-color, transparent);
    }
    .title {
      font-size: 0.75rem;
      opacity: 0.55;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-bottom: 1rem;
    }
    .body {
      display: flex;
      gap: 2rem;
      align-items: stretch;
    }
    .col.lr { flex: 1; min-width: 0; }
    .col.ud { flex: 0 0 auto; }
    .axis-label {
      font-size: 0.7rem;
      opacity: 0.5;
      margin-bottom: 0.5rem;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
  `;

  render() {
    if (!this._config || !this.hass) {
      return html`<div class="card">Loading…</div>`;
    }

    const cfg = this._config;
    const lrTarget = this._num(cfg.lr_target);
    const udTarget = this._num(cfg.ud_target);
    const lrActual = this._num(cfg.lr_actual) ?? 50;
    const udActual = this._num(cfg.ud_actual) ?? 50;
    const swingH   = this._bool(cfg.swing_h);
    const swingV   = this._bool(cfg.swing_v);
    const disabled = this._deviceOff();

    return html`
      <div class="card">
        <div class="title">${cfg.title ?? 'Air direction'}</div>
        <div class="body">
          <div class="col lr">
            <div class="axis-label">← Horizontal →</div>
            <blaueis-vane-slider
              orientation="horizontal"
              axis="lr"
              .target=${this._lrCommitted ? lrTarget : null}
              .actual=${lrActual}
              ?swinging=${swingH}
              ?disabled=${disabled}
              @target-change=${this._onLR}
            ></blaueis-vane-slider>
          </div>
          <div class="col ud">
            <div class="axis-label">↕ Vertical</div>
            <blaueis-vane-slider
              orientation="vertical"
              axis="ud"
              .target=${this._udCommitted ? udTarget : null}
              .actual=${udActual}
              ?swinging=${swingV}
              ?disabled=${disabled}
              @target-change=${this._onUD}
            ></blaueis-vane-slider>
          </div>
        </div>
      </div>
    `;
  }
}

customElements.define('blaueis-air-direction', BlaueisAirDirection);

// ─────────────────────────────────────────────────────────────────────────
// blaueis-ac-card — the full hero tile (iteration 4a)
// Sections: Climate (embedded HA thermostat card) + Air direction
// ─────────────────────────────────────────────────────────────────────────

class BlaueisAcCard extends LitElement {
  static properties = {
    hass:          { attribute: false },
    _config:       { state: true },
    _climateCard:  { state: true },
    _lrCommitted:  { state: true },
    _udCommitted:  { state: true },
  };

  constructor() {
    super();
    this._lrCommitted = false;
    this._udCommitted = false;
    this._climateCard = null;
  }

  setConfig(config) {
    // Only `climate` is required. Every other entity is opt-in; absent config
    // keys or missing entities cause the matching control to not render.
    // Paradigm: default hidden unless explicitly confirmed (by cap or by user).
    if (!config.climate) {
      throw new Error('blaueis-ac-card: config.climate (entity_id) is required');
    }
    this._config = config;
    this._climateCard = null;  // force recreate on config change
  }

  getCardSize() { return 6; }

  async _ensureClimateCard() {
    if (this._climateCard || !this._config?.climate) return;
    if (typeof window.loadCardHelpers !== 'function') return;  // standalone test env
    try {
      const helpers = await window.loadCardHelpers();
      const el = helpers.createCardElement({
        type: this._config.climate_card_type ?? 'thermostat',
        entity: this._config.climate,
      });
      if (this.hass) el.hass = this.hass;
      this._climateCard = el;
    } catch (err) {
      console.warn('blaueis-ac-card: failed to create climate card:', err);
    }
  }

  updated(changed) {
    if (changed.has('_config')) {
      this._ensureClimateCard();
    }
    if (changed.has('hass') && this._climateCard && this.hass) {
      this._climateCard.hass = this.hass;
    }
  }

  _num(eid) {
    const s = this.hass?.states?.[eid];
    if (!s) return null;
    const n = parseFloat(s.state);
    return Number.isNaN(n) ? null : n;
  }

  _bool(eid) {
    if (!eid) return false;
    const s = this.hass?.states?.[eid];
    if (!s) return false;
    const v = String(s.state).toLowerCase();
    return v === 'true' || v === 'on' || v === '1';
  }

  _deviceOff() {
    const s = this.hass?.states?.[this._config.climate];
    return s?.state === 'off' || s?.state === 'unavailable';
  }

  _callSelect(eid, value) {
    this.hass.callService('select', 'select_option', {
      entity_id: eid, option: String(value),
    });
  }

  _onLR(e) { this._lrCommitted = true; this._callSelect(this._config.lr_target, e.detail.value); }
  _onUD(e) { this._udCommitted = true; this._callSelect(this._config.ud_target, e.detail.value); }

  // Climate state + service helpers for the header controls
  _climateState() {
    const eid = this._config.climate;
    const s = this.hass?.states?.[eid];
    const modes = (s?.attributes?.hvac_modes ?? []).filter((m) => m !== 'off');
    const swingModes = s?.attributes?.swing_modes ?? [];
    const current = s?.state ?? 'unavailable';
    return {
      entity: eid,
      state: current,
      modes,
      swingModes,
      currentMode: current,
      isOn: !['off', 'unavailable', undefined, null, ''].includes(current),
      exists: !!s,
    };
  }

  // Capability gate: return true only when the entity is configured AND
  // present in hass.states (i.e. integration confirmed its existence,
  // typically via B5).
  _entityPresent(eid) {
    return !!(eid && this.hass?.states?.[eid]);
  }

  _togglePower() {
    const cs = this._climateState();
    if (!cs.entity) return;
    this.hass.callService('climate', cs.isOn ? 'turn_off' : 'turn_on', {
      entity_id: cs.entity,
    });
  }

  _setMode(mode) {
    if (!this._config.climate) return;
    this.hass.callService('climate', 'set_hvac_mode', {
      entity_id: this._config.climate,
      hvac_mode: mode,
    });
  }

  // Read swing state from the climate entity's swing_mode attribute.
  // This bypasses the broken `select.*_swing_*` entities (glossary has
  // `valid_set: [False, True]` which produces un-sendable "True"/"False"
  // options — integration bug tracked separately).
  _swingState() {
    const s = this.hass?.states?.[this._config.climate];
    const mode = s?.attributes?.swing_mode ?? 'off';
    return {
      mode,
      h: mode === 'horizontal' || mode === 'both',
      v: mode === 'vertical'   || mode === 'both',
    };
  }

  _toggleSwing(axis) {
    if (!this._config.climate) return;
    const { h, v } = this._swingState();
    const nh = axis === 'h' ? !h : h;
    const nv = axis === 'v' ? !v : v;
    const nextMode =
      nh && nv ? 'both' :
      nh       ? 'horizontal' :
      nv       ? 'vertical' :
                 'off';
    this.hass.callService('climate', 'set_swing_mode', {
      entity_id: this._config.climate,
      swing_mode: nextMode,
    });
  }

  static styles = css`
    :host { display: block; }
    .card {
      background: var(--ha-card-background, var(--card-background-color, #2c2c2e));
      color: var(--primary-text-color, #fff);
      border-radius: var(--ha-card-border-radius, 14px);
      padding: 1rem;
      box-shadow: var(--ha-card-box-shadow, none);
      border: var(--ha-card-border-width, 0) solid var(--divider-color, transparent);
    }
    .card-title {
      font-size: 0.9rem;
      font-weight: 500;
      opacity: 0.8;
      margin-bottom: 0.75rem;
      padding: 0 0.25rem;
    }

    /* Header row: power button (left), mode chips (right) */
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      padding: 0.25rem 0.25rem 0.75rem;
    }
    .power-btn {
      width: 2.4rem;
      height: 2.4rem;
      border-radius: 50%;
      border: none;
      background: var(--disabled-color, rgba(127, 127, 127, 0.25));
      color: var(--secondary-text-color);
      font-size: 1.1rem;
      line-height: 1;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.15s, color 0.15s;
      flex: 0 0 auto;
    }
    .power-btn:hover { filter: brightness(1.15); }
    .power-btn.on {
      background: var(--state-climate-cool-color, #0a84ff);
      color: #fff;
    }
    .mode-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem;
      justify-content: flex-end;
      flex: 1 1 auto;
    }
    .mode-chip {
      background: var(--ha-chip-background-color, rgba(127, 127, 127, 0.2));
      color: var(--primary-text-color);
      border: 1px solid var(--divider-color, rgba(127, 127, 127, 0.3));
      padding: 0.4rem 0.75rem;
      border-radius: 14px;
      font-size: 0.72rem;
      cursor: pointer;
      text-transform: capitalize;
      transition: background 0.15s, color 0.15s, border-color 0.15s;
    }
    .mode-chip:hover {
      background: var(--divider-color, rgba(127, 127, 127, 0.35));
    }
    .mode-chip.selected {
      background: var(--primary-color, #0a84ff);
      color: var(--text-primary-color, #fff);
      border-color: var(--primary-color, #0a84ff);
    }

    .section { margin-top: 1rem; }
    .section:first-of-type { margin-top: 0; }
    .section-label {
      font-size: 0.68rem;
      opacity: 0.5;
      margin: 0 0 0.5rem 0.25rem;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }
    .climate-loading {
      padding: 2rem;
      text-align: center;
      opacity: 0.5;
      font-size: 0.85rem;
    }
    /* Strip the embedded climate card's outer chrome so it lives flush
       inside our section. The inner <ha-card> it creates gets --ha-card-*
       overrides to remove its own background + padding. */
    .climate-slot {
      --ha-card-background: transparent;
      --ha-card-box-shadow: none;
      --ha-card-border-width: 0;
    }
    .air-body {
      display: flex;
      gap: 1.5rem;
      align-items: stretch;
      padding: 0 0.25rem;
    }
    .air-body .col.lr { flex: 1; min-width: 0; }
    .air-body .col.ud { flex: 0 0 auto; }
    .axis-label {
      font-size: 0.68rem;
      opacity: 0.5;
      margin-bottom: 0.4rem;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }

    /* Swing auto — two big arrow buttons below the vane panel */
    .swing-row {
      display: flex;
      gap: 0.9rem;
      margin-top: 1rem;
      padding: 0 0.25rem;
      flex-wrap: wrap;
    }
    .swing-btn {
      width: 3.5rem;
      height: 3rem;
      border-radius: 12px;
      border: 1px solid var(--divider-color, rgba(127, 127, 127, 0.3));
      background: var(--ha-chip-background-color, rgba(127, 127, 127, 0.15));
      color: var(--primary-text-color);
      cursor: pointer;
      font-size: 1.5rem;
      line-height: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: background 0.15s, color 0.15s, border-color 0.15s;
      padding: 0;
    }
    .swing-btn:hover {
      background: var(--divider-color, rgba(127, 127, 127, 0.3));
    }
    .swing-btn.active {
      background: var(--primary-color, #0a84ff);
      color: var(--text-primary-color, #fff);
      border-color: var(--primary-color, #0a84ff);
    }
    .swing-btn:disabled {
      opacity: 0.35;
      cursor: not-allowed;
    }
    .swing-icon { display: inline-block; line-height: 1; }
    .swing-icon.swing-v { transform: rotate(90deg); }
  `;

  render() {
    if (!this._config || !this.hass) {
      return html`<div class="card">Loading…</div>`;
    }
    const cfg = this._config;
    const cs = this._climateState();
    const ss = this._swingState();
    const disabled = this._deviceOff();

    // ── Capability gates (default hidden) ───────────────────────
    const hasPower   = cs.exists;
    const hasModes   = cs.exists && cs.modes.length > 0;
    const hasLrSlider = this._entityPresent(cfg.lr_target);
    const hasUdSlider = this._entityPresent(cfg.ud_target);
    const hasLrActual = this._entityPresent(cfg.lr_actual);
    const hasUdActual = this._entityPresent(cfg.ud_actual);
    const hasSwingH  = cs.swingModes.includes('horizontal');
    const hasSwingV  = cs.swingModes.includes('vertical');
    const hasAirDir  = hasLrSlider || hasUdSlider || hasSwingH || hasSwingV;

    const lrTarget = hasLrSlider ? this._num(cfg.lr_target) : null;
    const udTarget = hasUdSlider ? this._num(cfg.ud_target) : null;
    const lrActual = hasLrActual ? (this._num(cfg.lr_actual) ?? 50) : 50;
    const udActual = hasUdActual ? (this._num(cfg.ud_actual) ?? 50) : 50;

    return html`
      <div class="card">
        ${hasPower || hasModes ? html`
          <div class="header">
            ${hasPower ? html`
              <button
                class="power-btn ${cs.isOn ? 'on' : ''}"
                title=${cs.isOn ? 'Power off' : 'Power on'}
                aria-pressed=${cs.isOn}
                @click=${this._togglePower}
              >⏻</button>
            ` : html`<span></span>`}
            ${hasModes ? html`
              <div class="mode-chips">
                ${cs.modes.map((m) => html`
                  <button
                    class="mode-chip ${cs.currentMode === m ? 'selected' : ''}"
                    aria-pressed=${cs.currentMode === m}
                    @click=${() => this._setMode(m)}
                  >${m.replace('_', ' ')}</button>
                `)}
              </div>
            ` : ''}
          </div>
        ` : ''}

        <div class="section">
          <div class="climate-slot">
            ${this._climateCard
              ? this._climateCard
              : html`<div class="climate-loading">Loading climate…</div>`}
          </div>
        </div>

        ${hasAirDir ? html`
          <div class="section">
            <div class="section-label">Air direction</div>
            ${hasLrSlider || hasUdSlider ? html`
              <div class="air-body">
                ${hasLrSlider ? html`
                  <div class="col lr">
                    <div class="axis-label">← Horizontal →</div>
                    <blaueis-vane-slider
                      orientation="horizontal" axis="lr"
                      .target=${this._lrCommitted ? lrTarget : null}
                      .actual=${lrActual}
                      ?swinging=${ss.h}
                      ?disabled=${disabled}
                      @target-change=${this._onLR}
                    ></blaueis-vane-slider>
                  </div>
                ` : ''}
                ${hasUdSlider ? html`
                  <div class="col ud">
                    <div class="axis-label">↕ Vertical</div>
                    <blaueis-vane-slider
                      orientation="vertical" axis="ud"
                      .target=${this._udCommitted ? udTarget : null}
                      .actual=${udActual}
                      ?swinging=${ss.v}
                      ?disabled=${disabled}
                      @target-change=${this._onUD}
                    ></blaueis-vane-slider>
                  </div>
                ` : ''}
              </div>
            ` : ''}
            ${hasSwingH || hasSwingV ? html`
              <div class="swing-row">
                ${hasSwingH ? html`
                  <button
                    class="swing-btn ${ss.h ? 'active' : ''}"
                    aria-pressed=${ss.h}
                    title="Swing horizontal"
                    ?disabled=${disabled}
                    @click=${() => this._toggleSwing('h')}
                  ><span class="swing-icon swing-h">↔</span></button>
                ` : ''}
                ${hasSwingV ? html`
                  <button
                    class="swing-btn ${ss.v ? 'active' : ''}"
                    aria-pressed=${ss.v}
                    title="Swing vertical"
                    ?disabled=${disabled}
                    @click=${() => this._toggleSwing('v')}
                  ><span class="swing-icon swing-v">↔</span></button>
                ` : ''}
              </div>
            ` : ''}
          </div>
        ` : ''}
      </div>
    `;
  }
}

customElements.define('blaueis-ac-card', BlaueisAcCard);

// ─────────────────────────────────────────────────────────────────────────
// HA card-picker registration
// ─────────────────────────────────────────────────────────────────────────
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'blaueis-air-direction',
  name: 'Blaueis Air Direction',
  description: 'Vane angle control for Blaueis Midea AC',
  preview: false,
});
window.customCards.push({
  type: 'blaueis-ac-card',
  name: 'Blaueis AC Card',
  description: 'Full climate + air direction tile for Blaueis Midea AC',
  preview: false,
});

console.info(
  '%c BLAUEIS-AC-CARD %c iteration-3 ',
  'background: #0a84ff; color: #fff; font-weight: 700; padding: 2px 6px; border-radius: 3px 0 0 3px;',
  'background: #30d158; color: #000; padding: 2px 6px; border-radius: 0 3px 3px 0;',
);
