const SCHEDULE_STORE_EVENT = "fluvalble-schedule-store";

class FluvalbleScheduleCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("hui-entities-card-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:fluvalble-schedule-card",
      title: "AquaSky Schedule",
      physical_preview: true,
      preview_duration: 60,
      step_seconds: 2,
      points: DEFAULT_POINTS,
    };
  }

  setConfig(config) {
    this.config = {
      title: "Fluval BLE Schedule",
      physical_preview: false,
      preview_duration: 60,
      step_seconds: 2,
      points: DEFAULT_POINTS,
      ...config,
    };
    this.store = getScheduleStore(this.config);
    this.previewMinute = this.previewMinute ?? this.store.selectedMinute;
    this._subscribeStore();
    this.attachShadow({ mode: "open" });
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.loadSavedSchedule();
    if (this.shadowRoot) {
      this.render();
    }
  }

  getCardSize() {
    return 5;
  }

  render() {
    const root = this.shadowRoot;
    if (!root) return;

    const points = this.store.points;
    const time = formatMinute(this.previewMinute);
    const graph = buildGraph(points);

    root.innerHTML = `
      <ha-card>
        <div class="card">
          <div class="header">
            <div>
              <div class="title">${escapeHtml(this.config.title)}</div>
              <div id="subtitle" class="subtitle">${time} preview · ${scheduleSourceLabel(this.store)}</div>
            </div>
            <label class="toggle">
              <input id="physical" type="checkbox" ${this.config.physical_preview ? "checked" : ""}>
              Physical preview
            </label>
          </div>

          <svg class="graph" viewBox="0 0 720 220" preserveAspectRatio="none">
            <line x1="0" y1="200" x2="720" y2="200" class="axis"></line>
            <line id="cursor" x1="${(this.previewMinute / 1440) * 720}" y1="12" x2="${(this.previewMinute / 1440) * 720}" y2="204" class="cursor"></line>
            ${graph}
          </svg>

          <div class="time-row">
            <span>00:00</span>
            <input id="time" type="range" min="0" max="1439" step="5" value="${this.previewMinute}">
            <span>24:00</span>
          </div>

          <div class="actions">
            <label class="mode-control">
              Schedule mode
              <select id="schedule-mode">
                <option value="manual" ${this.store.mode === "manual" ? "selected" : ""}>Manual</option>
                <option value="native" ${this.store.mode === "native" ? "selected" : ""}>Fixture native</option>
              </select>
            </label>
            <button id="apply">Apply Schedule</button>
            <button id="load-fixture">Load from fixture</button>
            <button id="flatten">Flatten Schedule</button>
            <button id="play">Play 24h preview</button>
            <button id="stop">Stop preview</button>
          </div>
        </div>
      </ha-card>
      <style>
        .card { padding: 16px; }
        .header { align-items: center; display: flex; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
        .title { font-size: 18px; font-weight: 600; }
        .subtitle { color: var(--secondary-text-color); font-size: 13px; margin-top: 2px; }
        .toggle { align-items: center; color: var(--secondary-text-color); display: flex; font-size: 13px; gap: 8px; white-space: nowrap; }
        .graph { background: var(--ha-card-background, var(--card-background-color)); border: 1px solid var(--divider-color); border-radius: 8px; height: 220px; width: 100%; }
        .axis { stroke: var(--divider-color); stroke-width: 1; }
        .cursor { stroke: var(--primary-text-color); stroke-dasharray: 4 4; stroke-width: 1.5; }
        .line { fill: none; stroke-width: 3; }
        .fill { opacity: .08; }
        .time-row { align-items: center; display: grid; gap: 10px; grid-template-columns: auto 1fr auto; margin: 12px 0; color: var(--secondary-text-color); font-size: 12px; }
        input[type="range"] { width: 100%; }
        .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
        .mode-control { align-items: center; color: var(--secondary-text-color); display: flex; font-size: 13px; gap: 8px; }
        select { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 6px; color: var(--primary-text-color); padding: 7px 10px; }
        button { background: var(--primary-color); border: 0; border-radius: 6px; color: var(--text-primary-color); cursor: pointer; padding: 8px 12px; }
        button#load-fixture { background: var(--secondary-background-color); color: var(--primary-text-color); }
        button#flatten { background: var(--warning-color, #f0a000); color: var(--primary-text-color); }
        button#stop { background: var(--error-color); }
      </style>
    `;

    root.getElementById("time").addEventListener("input", (event) => {
      this.previewMinute = Number(event.target.value);
      setSelectedMinute(this.config, this.previewMinute, this);
      this.updateLocalTimeDisplay();
    });
    root.getElementById("time").addEventListener("change", (event) => {
      this.previewMinute = Number(event.target.value);
      setSelectedMinute(this.config, this.previewMinute, this);
      if (this.config.physical_preview) {
        const channels = interpolate(this.store.points, this.previewMinute);
        this.store.lastManualChannels = channels;
        this.applyChannels(channels);
      }
    });
    root.getElementById("physical").addEventListener("change", (event) => {
      this.config.physical_preview = event.target.checked;
    });
    root.getElementById("schedule-mode").addEventListener("change", (event) => {
      setScheduleMode(this.config, event.target.value, this);
      persistSchedule(this.config, this, true);
      const labels = { manual: "Manual", native: "Fixture native" };
      this.toast(`Schedule mode set to ${labels[this.store.mode] || "Manual"}`);
    });
    root.getElementById("apply").addEventListener("click", () => {
      if (this.store.mode === "native") {
        saveScheduleNow(this.config, this).then(() => {
          this.toast("Schedule uploaded to the fixture");
        });
        return;
      }
      const channels = interpolate(this.store.points, this.previewMinute);
      this.store.lastManualChannels = channels;
      this.applyChannels(channels).then(() => {
        this.toast(`Schedule applied for ${formatMinute(this.previewMinute)}`);
      });
    });
    root.getElementById("load-fixture").addEventListener("click", () => {
      this.loadFixtureSchedule();
    });
    root.getElementById("flatten").addEventListener("click", () => {
      flattenSchedule(this.config, this);
      persistSchedule(this.config, this);
      this.render();
      this.toast("Schedule flattened to 0%");
    });
    root.getElementById("play").addEventListener("click", () => {
      this.startPreviewPlayback();
    });
    root.getElementById("stop").addEventListener("click", () => {
      this.stopPreviewPlayback();
    });
  }

  applyChannels(channels) {
    return this.callService("set_channels", {
      ...targetData(this.config),
      red: channels.red,
      green: channels.green,
      blue: channels.blue,
      white: channels.white,
      channel_5: channels.channel_5,
    });
  }

  callService(service, data) {
    if (!this._hass) return Promise.resolve();
    return this._hass.callService("fluvalble", service, data);
  }

  toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", {
      bubbles: true,
      composed: true,
      detail: { message },
    }));
  }

  startPreviewPlayback() {
    this.stopPreviewTimerOnly();
    this.store.previewRestoreMinute = this.store.selectedMinute;
    this.store.previewRestoreMode = this.store.mode || "manual";
    this.store.previewRestoreChannels = this.store.lastManualChannels
      || interpolate(this.store.points, this.store.selectedMinute);

    const startMinute = firstScheduleMinute(this.store.points);
    const durationMs = Math.max(1, Number(this.config.preview_duration || 60)) * 1000;
    const startedAt = Date.now();
    this.store.lastPreviewWriteMinute = null;
    this.store.lastPreviewChannels = null;
    this.store.playing = true;

    const tick = () => {
      if (!this.store.playing) return;
      const elapsed = (Date.now() - startedAt) % durationMs;
      const minute = Math.round((startMinute + ((elapsed / durationMs) * 1440)) % 1440);
      this.previewMinute = minute;
      setSelectedMinute(this.config, minute, this);
      this.updateLocalTimeDisplay();

      if (this.config.physical_preview) {
        const writeMinute = Math.floor(minute / 30) * 30;
        const channels = interpolate(this.store.points, writeMinute);
        if (
          !this.store.previewWriteInFlight
          && this.store.lastPreviewWriteMinute !== writeMinute
          && !sameChannels(this.store.lastPreviewChannels, channels)
        ) {
          this.store.lastPreviewWriteMinute = writeMinute;
          this.store.lastPreviewChannels = channels;
          this.store.previewWriteInFlight = true;
          this.applyChannels(channels).finally(() => {
            this.store.previewWriteInFlight = false;
          });
        }
      }
    };

    tick();
    this.store.previewTimer = setInterval(tick, 500);
  }

  stopPreviewPlayback() {
    this.stopPreviewTimerOnly();
    const stopped = this.callService("stop_preview", targetData(this.config));

    if ((this.store.previewRestoreMode || this.store.mode) === "native") {
      stopped.finally(() => {
        saveScheduleNow(this.config, this);
      });
      return;
    }

    this.previewMinute = 0;
    setSelectedMinute(this.config, this.previewMinute, this);
    this.updateLocalTimeDisplay();
    if (this.config.physical_preview && this.store.previewRestoreChannels) {
      this.applyChannels(this.store.previewRestoreChannels);
    }
  }

  stopPreviewTimerOnly() {
    if (this.store?.previewTimer) {
      clearInterval(this.store.previewTimer);
      this.store.previewTimer = null;
    }
    if (this.store) {
      this.store.playing = false;
    }
  }

  async loadSavedSchedule() {
    if (!this._hass || this.store.loading || this.store.loaded) return;
    this.store.loading = true;
    try {
      const result = await this._hass.callWS({
        type: "fluvalble/get_schedule",
        ...targetData(this.config),
      });
      if (Array.isArray(result?.points) && result.points.length) {
        this.store.points = normalizePoints(result.points);
      }
      this.store.fixture = result?.fixture || null;
      this.store.mode = ["native", "auto"].includes(result?.mode) ? "native" : "manual";
      this.store.scheduleSource = "local";
      this.store.loaded = true;
      notifyScheduleStore(this.config, null);
      this.render();
    } catch (error) {
      // Older HA sessions or a just-restarted integration may not have the websocket ready yet.
      console.warn("Unable to load saved Fluval schedule", error);
    } finally {
      this.store.loading = false;
    }
  }

  async loadFixtureSchedule() {
    if (!this._hass || this.store.loadingFixture) return;
    this.store.loadingFixture = true;
    try {
      const result = await this._hass.callWS({
        type: "fluvalble/get_schedule",
        ...targetData(this.config),
        refresh: true,
      });
      this.store.fixture = result?.fixture || null;
      const points = this.store.fixture?.professional;
      if (!Array.isArray(points) || !points.length) {
        if (this.store.fixture?.auto) {
          this.toast("The fixture reported an Auto schedule; only Professional curves can be loaded into this editor");
        } else {
          this.toast("No Professional schedule readback is available from the fixture");
        }
        return;
      }
      this.store.points = normalizePoints(points);
      this.store.mode = "native";
      this.store.scheduleSource = "fixture";
      notifyScheduleStore(this.config, this);
      this.render();
      this.toast(
        result.refresh_ok === false
          ? "Loaded the last fixture readback; the live refresh did not complete"
          : "Loaded the schedule confirmed by the fixture",
      );
    } catch (error) {
      console.warn("Unable to load the Fluval fixture schedule", error);
      this.toast("Unable to load a schedule from the fixture");
    } finally {
      this.store.loadingFixture = false;
    }
  }

  updateLocalTimeDisplay() {
    const root = this.shadowRoot;
    if (!root) return;
    const time = formatMinute(this.previewMinute);
    const x = (this.previewMinute / 1440) * 720;
    const subtitle = root.getElementById("subtitle");
    const cursor = root.getElementById("cursor");
    const timeInput = root.getElementById("time");
    if (subtitle) subtitle.textContent = `${time} preview · ${scheduleSourceLabel(this.store)}`;
    if (timeInput) timeInput.value = this.previewMinute;
    if (cursor) {
      cursor.setAttribute("x1", x);
      cursor.setAttribute("x2", x);
    }
  }

  _subscribeStore() {
    if (this._storeListener) return;
    this._storeListener = (event) => {
      if (event.detail?.key !== getStoreKey(this.config) || event.detail?.source === this) return;
      this.previewMinute = this.store.selectedMinute;
      this.render();
    };
    window.addEventListener(SCHEDULE_STORE_EVENT, this._storeListener);
  }

  disconnectedCallback() {
    this.stopPreviewTimerOnly();
    if (this._autoClock) {
      clearInterval(this._autoClock);
      this._autoClock = null;
    }
    if (this._storeListener) {
      window.removeEventListener(SCHEDULE_STORE_EVENT, this._storeListener);
      this._storeListener = null;
    }
  }
}

class FluvalbleEffectScheduleCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("hui-entities-card-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:fluvalble-effect-schedule-card",
      title: "Fluval Timed Effects",
    };
  }

  setConfig(config) {
    this.config = {
      title: "Fluval Timed Effects",
      ...config,
    };
    this.store = getScheduleStore(this.config);
    this.attachShadow({ mode: "open" });
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.loadSavedEffectSchedule();
    if (this.shadowRoot) this.render();
  }

  getCardSize() {
    return Math.max(3, this.store.effectWindows.length + 2);
  }

  render() {
    const root = this.shadowRoot;
    if (!root) return;
    const options = this.store.effectOptions || [];
    const supported = options.length > 0;
    const rows = buildEffectRows(this.store.effectWindows, options);
    const status = supported
      ? `${options.length} fixture-native effects · ${effectScheduleSourceLabel(this.store)}`
      : "Timed effects become available after a supported controller is identified";

    root.innerHTML = `
      <ha-card>
        <div class="card">
          <div class="header">
            <div>
              <div class="title">${escapeHtml(this.config.title)}</div>
              <div class="subtitle">${escapeHtml(status)}</div>
            </div>
            <button id="add" ${supported && this.store.effectWindows.length < 7 ? "" : "disabled"}>Add window</button>
          </div>
          <div class="rows">
            ${rows || '<div class="empty">No timed-effect windows configured.</div>'}
          </div>
          <div class="actions">
            <button id="apply" ${supported ? "" : "disabled"}>Apply to fixture</button>
            <button id="load">Load from fixture</button>
            <button id="clear" ${supported ? "" : "disabled"}>Clear fixture schedule</button>
          </div>
          ${this.store.effectReadbackComplete === false && this.store.effectProtocol === "classic"
            ? '<div class="notice">Classic controllers report only one timed-effect slot in normal state responses. The saved Home Assistant copy remains the complete editable schedule.</div>'
            : ""}
        </div>
      </ha-card>
      <style>
        .card { padding: 16px; }
        .header { align-items: center; display: flex; gap: 12px; justify-content: space-between; }
        .title { font-size: 18px; font-weight: 600; }
        .subtitle, .empty, .notice { color: var(--secondary-text-color); font-size: 13px; }
        .subtitle { margin-top: 2px; }
        .rows { display: grid; gap: 10px; margin-top: 14px; }
        .row { background: var(--secondary-background-color); border-radius: 8px; display: grid; gap: 10px; padding: 12px; }
        .main { align-items: center; display: grid; gap: 8px; grid-template-columns: auto minmax(150px, 1fr) auto auto auto; }
        .enabled { align-items: center; display: flex; font-size: 12px; gap: 5px; }
        .time { align-items: center; color: var(--secondary-text-color); display: flex; font-size: 12px; gap: 6px; }
        input[type="time"], select { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 6px; color: var(--primary-text-color); padding: 7px; }
        .weekdays { display: flex; flex-wrap: wrap; gap: 8px 12px; }
        .weekday { align-items: center; display: flex; font-size: 12px; gap: 4px; }
        .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
        .notice { border-left: 3px solid var(--warning-color, #f0a000); margin-top: 14px; padding-left: 10px; }
        button { background: var(--primary-color); border: 0; border-radius: 6px; color: var(--text-primary-color); cursor: pointer; padding: 8px 12px; }
        button:disabled { cursor: default; opacity: .45; }
        button.remove, button#load { background: var(--secondary-background-color); color: var(--primary-text-color); }
        button#clear { background: var(--error-color); }
        @media (max-width: 600px) {
          .main { grid-template-columns: auto 1fr; }
          .time { justify-content: flex-start; }
        }
      </style>
    `;

    root.getElementById("add").addEventListener("click", () => this.addWindow());
    root.getElementById("apply").addEventListener("click", () => this.applySchedule());
    root.getElementById("load").addEventListener("click", () => this.loadFixtureSchedule());
    root.getElementById("clear").addEventListener("click", () => this.clearSchedule());
    root.querySelectorAll("[data-effect-field]").forEach((input) => {
      input.addEventListener("change", (event) => {
        const index = Number(event.target.dataset.effectIndex);
        const field = event.target.dataset.effectField;
        this.store.effectWindows[index][field] = field === "enabled" ? event.target.checked : event.target.value;
        this.store.effectSource = "local";
        this.render();
      });
    });
    root.querySelectorAll("[data-effect-weekday]").forEach((input) => {
      input.addEventListener("change", (event) => {
        this.toggleWeekday(
          Number(event.target.dataset.effectIndex),
          event.target.dataset.effectWeekday,
          event.target.checked,
        );
      });
    });
    root.querySelectorAll(".remove").forEach((button) => {
      button.addEventListener("click", (event) => {
        this.store.effectWindows.splice(Number(event.target.dataset.effectIndex), 1);
        this.store.effectSource = "local";
        this.render();
      });
    });
  }

  toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", {
      bubbles: true,
      composed: true,
      detail: { message },
    }));
  }

  addWindow() {
    if (this.store.effectWindows.length >= 7 || !this.store.effectOptions.length) return;
    const used = new Set(this.store.effectWindows.flatMap((effectWindow) => effectWindow.weekdays));
    const weekday = WEEKDAYS.find(([value]) => !used.has(value));
    if (!weekday) {
      this.toast("Every weekday is already assigned to an effect window");
      return;
    }
    this.store.effectWindows.push({
      enabled: true,
      effect: this.store.effectOptions[0],
      start: "12:00",
      end: "12:10",
      weekdays: [weekday[0]],
    });
    this.store.effectSource = "local";
    this.render();
  }

  toggleWeekday(index, weekday, checked) {
    const effectWindow = this.store.effectWindows[index];
    if (!effectWindow) return;
    if (checked) {
      const usedElsewhere = this.store.effectWindows.some((candidate, candidateIndex) => (
        candidateIndex !== index && candidate.weekdays.includes(weekday)
      ));
      if (usedElsewhere) {
        this.toast(`${weekdayLabel(weekday)} is already assigned to another effect window`);
        this.render();
        return;
      }
      effectWindow.weekdays = [...new Set([...effectWindow.weekdays, weekday])];
    } else if (effectWindow.weekdays.length === 1) {
      this.toast("Each effect window requires at least one weekday");
      this.render();
      return;
    } else {
      effectWindow.weekdays = effectWindow.weekdays.filter((value) => value !== weekday);
    }
    this.store.effectSource = "local";
    this.render();
  }

  async loadSavedEffectSchedule() {
    if (!this._hass || this.store.loadingEffects || this.store.effectsLoaded) return;
    this.store.loadingEffects = true;
    try {
      const result = await this._hass.callWS({
        type: "fluvalble/get_schedule",
        ...targetData(this.config),
      });
      this.updateCapabilities(result?.fixture);
      if (Array.isArray(result?.effect_windows)) {
        this.store.effectWindows = normalizeEffectWindows(result.effect_windows);
      }
      this.store.effectSource = "local";
      this.store.effectsLoaded = true;
      this.render();
    } catch (error) {
      console.warn("Unable to load saved Fluval timed effects", error);
    } finally {
      this.store.loadingEffects = false;
    }
  }

  async loadFixtureSchedule() {
    if (!this._hass || this.store.loadingEffects) return;
    this.store.loadingEffects = true;
    try {
      const result = await this._hass.callWS({
        type: "fluvalble/get_schedule",
        ...targetData(this.config),
        refresh: true,
      });
      this.updateCapabilities(result?.fixture);
      this.render();
      const effects = result?.fixture?.effects;
      if (!Array.isArray(effects)) {
        this.toast("No timed-effect schedule readback is available from the fixture");
        return;
      }
      this.store.effectWindows = normalizeEffectWindows(effects);
      this.store.effectSource = "fixture";
      this.render();
      const qualifier = this.store.effectReadbackComplete ? "" : " (partial controller readback)";
      this.toast(`Loaded timed effects from the fixture${qualifier}`);
    } catch (error) {
      console.warn("Unable to load Fluval timed effects from the fixture", error);
      this.toast("Unable to load timed effects from the fixture");
    } finally {
      this.store.loadingEffects = false;
    }
  }

  updateCapabilities(fixture) {
    this.store.effectOptions = Array.isArray(fixture?.effect_options) ? fixture.effect_options : [];
    this.store.effectProtocol = fixture?.protocol || null;
    this.store.effectReadbackComplete = fixture?.effect_readback_complete ?? null;
  }

  async applySchedule() {
    const error = validateEffectWindows(this.store.effectWindows, this.store.effectOptions);
    if (error) {
      this.toast(error);
      return;
    }
    try {
      await this._hass.callService("fluvalble", "set_native_effect_schedule", {
        ...targetData(this.config),
        windows: this.store.effectWindows.map((effectWindow) => ({ ...effectWindow })),
      });
      this.store.effectSource = "uploaded";
      this.render();
      this.toast("Timed effects uploaded to the fixture");
    } catch (error) {
      console.warn("Unable to upload the Fluval timed-effect schedule", error);
      this.toast("Unable to upload timed effects");
    }
  }

  async clearSchedule() {
    try {
      await this._hass.callService("fluvalble", "set_native_effect_schedule", {
        ...targetData(this.config),
        windows: [],
      });
      this.store.effectWindows = [];
      this.store.effectSource = "uploaded";
      this.render();
      this.toast("Timed effects cleared from the fixture");
    } catch (error) {
      console.warn("Unable to clear the Fluval timed-effect schedule", error);
      this.toast("Unable to clear timed effects");
    }
  }
}

class FluvalbleSpectrumCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("hui-entities-card-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:fluvalble-spectrum-card",
      title: "AquaSky Spectrum",
      physical_preview: true,
      points: DEFAULT_POINTS,
    };
  }

  setConfig(config) {
    this.config = {
      title: "Fluval BLE Spectrum",
      points: DEFAULT_POINTS,
      ...config,
    };
    this.store = getScheduleStore(this.config);
    this._subscribeStore();
    this.attachShadow({ mode: "open" });
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this.shadowRoot) {
      this.render();
    }
  }

  getCardSize() {
    return 3;
  }

  render() {
    const root = this.shadowRoot;
    if (!root) return;

    const channels = interpolate(this.store.points, this.store.selectedMinute);
    const time = formatMinute(this.store.selectedMinute);

    root.innerHTML = `
      <ha-card>
        <div class="card">
          <div class="header">
            <div>
              <div class="title">${escapeHtml(this.config.title)}</div>
              <div class="subtitle">${time} selected from hourly graph</div>
            </div>
          </div>

          <div class="spectrum">${buildChannelBars(channels, true)}</div>
        </div>
      </ha-card>
      <style>
        .card { padding: 16px; }
        .header { align-items: center; display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
        .title { font-size: 18px; font-weight: 600; }
        .subtitle { color: var(--secondary-text-color); font-size: 13px; margin-top: 2px; }
        .spectrum { display: grid; gap: 12px; }
        .channel-bars { display: grid; gap: 10px; }
        .bar-row { align-items: center; display: grid; gap: 10px; grid-template-columns: 58px 1fr 44px; }
        .label { font-size: 13px; }
        .bar { background: var(--divider-color); border-radius: 8px; height: 18px; overflow: hidden; position: relative; }
        .bar > span { display: block; height: 100%; pointer-events: none; }
        .bar input { appearance: none; background: transparent; inset: 0; margin: 0; position: absolute; width: 100%; }
        .bar input::-webkit-slider-thumb { appearance: none; background: var(--primary-text-color); border: 2px solid var(--card-background-color); border-radius: 50%; box-shadow: 0 1px 4px rgba(0,0,0,.35); height: 18px; width: 18px; }
        .bar input::-moz-range-thumb { background: var(--primary-text-color); border: 2px solid var(--card-background-color); border-radius: 50%; box-shadow: 0 1px 4px rgba(0,0,0,.35); height: 16px; width: 16px; }
        .value { color: var(--secondary-text-color); font-size: 12px; text-align: right; }
      </style>
    `;

    root.querySelectorAll(".channel-slider").forEach((slider) => {
      slider.addEventListener("input", (event) => {
        const channel = event.target.dataset.channel;
        const value = Number(event.target.value);
        const row = event.target.closest(".bar-row");
        row.querySelector(".bar > span").style.width = `${value}%`;
        row.querySelector(".value").textContent = `${value}%`;
        updateSelectedChannels(this.config, { [channel]: value }, this);
        persistSchedule(this.config, this);
      });
    });
  }

  _subscribeStore() {
    if (this._storeListener) return;
    this._storeListener = (event) => {
      if (event.detail?.key !== getStoreKey(this.config) || event.detail?.source === this) return;
      this.render();
    };
    window.addEventListener(SCHEDULE_STORE_EVENT, this._storeListener);
  }

  disconnectedCallback() {
    if (this._storeListener) {
      window.removeEventListener(SCHEDULE_STORE_EVENT, this._storeListener);
      this._storeListener = null;
    }
  }
}

class FluvalbleWavelengthCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("hui-entities-card-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:fluvalble-wavelength-card",
      title: "AquaSky Wavelength Preview",
      physical_preview: true,
      points: DEFAULT_POINTS,
    };
  }

  setConfig(config) {
    this.config = {
      title: "Fluval BLE Wavelength Preview",
      points: DEFAULT_POINTS,
      ...config,
    };
    this.store = getScheduleStore(this.config);
    this._subscribeStore();
    this.attachShadow({ mode: "open" });
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this.shadowRoot) {
      this.render();
    }
  }

  getCardSize() {
    return 4;
  }

  render() {
    const root = this.shadowRoot;
    if (!root) return;

    const channels = interpolate(this.store.points, this.store.selectedMinute);
    const time = formatMinute(this.store.selectedMinute);

    root.innerHTML = `
      <ha-card>
        <div class="card">
          <div class="header">
            <div>
              <div class="title">${escapeHtml(this.config.title)}</div>
              <div class="subtitle">${time} selected from hourly graph</div>
            </div>
          </div>

          <div class="spectrum">${buildWavelengthSpectrum(channels)}</div>
        </div>
      </ha-card>
      <style>
        .card { padding: 16px; }
        .header { align-items: center; display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
        .title { font-size: 18px; font-weight: 600; }
        .subtitle { color: var(--secondary-text-color); font-size: 13px; margin-top: 2px; }
        .spectrum { display: grid; gap: 12px; }
        .spectrum-chart { background: linear-gradient(180deg, rgba(255,255,255,.03), rgba(0,0,0,.08)); border: 1px solid var(--divider-color); border-radius: 8px; height: 260px; width: 100%; }
        .spectrum-axis { stroke: var(--divider-color); stroke-width: 1; }
        .spectrum-grid { stroke: var(--divider-color); stroke-width: .7; opacity: .45; }
        .spectrum-curve { fill: none; stroke: var(--primary-text-color); stroke-linecap: round; stroke-linejoin: round; stroke-width: 3.5; }
        .spectrum-fill { fill: var(--primary-text-color); opacity: .18; }
        .spectrum-label { fill: var(--secondary-text-color); font-size: 11px; }
      </style>
    `;
  }

  _subscribeStore() {
    if (this._storeListener) return;
    this._storeListener = (event) => {
      if (event.detail?.key !== getStoreKey(this.config) || event.detail?.source === this) return;
      this.render();
    };
    window.addEventListener(SCHEDULE_STORE_EVENT, this._storeListener);
  }

  disconnectedCallback() {
    if (this._storeListener) {
      window.removeEventListener(SCHEDULE_STORE_EVENT, this._storeListener);
      this._storeListener = null;
    }
  }
}

const DEFAULT_POINTS = [
  { time: "00:00", red: 0, green: 0, blue: 0, white: 0, channel_5: 0 },
  { time: "10:00", red: 0, green: 0, blue: 0, white: 0, channel_5: 0 },
  { time: "11:00", red: 10, green: 10, blue: 25, white: 5, channel_5: 0 },
  { time: "16:00", red: 10, green: 10, blue: 25, white: 5, channel_5: 0 },
  { time: "19:00", red: 3, green: 0, blue: 8, white: 0, channel_5: 0 },
  { time: "20:00", red: 0, green: 0, blue: 0, white: 0, channel_5: 0 },
];

const CHANNELS = [
  ["red", "#ff4a3d", "Red"],
  ["green", "#45c767", "Green"],
  ["blue", "#4d7cff", "Blue"],
  ["white", "#dfe7ff", "White"],
  ["channel_5", "#b86cff", "Violet"],
];

const WEEKDAYS = [
  ["monday", "Mon"],
  ["tuesday", "Tue"],
  ["wednesday", "Wed"],
  ["thursday", "Thu"],
  ["friday", "Fri"],
  ["saturday", "Sat"],
  ["sunday", "Sun"],
];

function getStoreKey(config) {
  return config.store_key || config.entry_id || config.mac || "default";
}

function getScheduleStore(config) {
  window.__fluvalbleScheduleStores = window.__fluvalbleScheduleStores || {};
  const key = getStoreKey(config);
  if (!window.__fluvalbleScheduleStores[key]) {
    window.__fluvalbleScheduleStores[key] = {
      key,
      points: normalizePoints(config.points || DEFAULT_POINTS),
      selectedMinute: 660,
      mode: "manual",
      scheduleSource: "local",
      effectWindows: normalizeEffectWindows(config.effect_windows || []),
      effectOptions: [],
      effectProtocol: null,
      effectReadbackComplete: null,
      effectSource: "local",
    };
  }
  return window.__fluvalbleScheduleStores[key];
}

function setSelectedMinute(config, minute, source) {
  const store = getScheduleStore(config);
  store.selectedMinute = Number(minute) % 1440;
  notifyScheduleStore(config, source);
}

function currentMinute() {
  const now = new Date();
  return (now.getHours() * 60) + now.getMinutes();
}

function sameChannels(left, right) {
  if (!left || !right) return false;
  return CHANNELS.every(([key]) => clampPercent(left[key]) === clampPercent(right[key]));
}

function firstScheduleMinute(points) {
  if (!points.length) return 0;
  return [...points].sort((a, b) => a.minute - b.minute)[0].minute;
}

function updateSelectedChannels(config, values, source) {
  const store = getScheduleStore(config);
  store.scheduleSource = "local";
  CHANNELS.forEach(([key]) => {
    if (key in values) {
      applyChannelRamp(store, key, clampPercent(values[key]));
    }
  });
  store.points.sort((a, b) => a.minute - b.minute);
  notifyScheduleStore(config, source);
}

function flattenSchedule(config, source) {
  const store = getScheduleStore(config);
  store.scheduleSource = "local";
  store.points = store.points.map((point) => ({
    ...point,
    red: 0,
    green: 0,
    blue: 0,
    white: 0,
    channel_5: 0,
  }));
  notifyScheduleStore(config, source);
}

function applyChannelRamp(store, channel, targetValue) {
  const selectedMinute = store.selectedMinute;
  const originalPoints = store.points.map((point) => ({ ...point }));
  const startMinute = Math.max(0, selectedMinute - 60);
  const endMinute = Math.min(1439, selectedMinute + 60);
  const startValue = clampPercent(interpolate(originalPoints, startMinute)[channel]);
  const endValue = clampPercent(interpolate(originalPoints, endMinute)[channel]);
  const rampMinutes = uniqueSortedMinutes([
    startMinute,
    Math.max(0, selectedMinute - 45),
    Math.max(0, selectedMinute - 30),
    Math.max(0, selectedMinute - 15),
    selectedMinute,
    Math.min(1439, selectedMinute + 15),
    Math.min(1439, selectedMinute + 30),
    Math.min(1439, selectedMinute + 45),
    endMinute,
  ]);

  store.points = store.points.filter((point) => point.minute < startMinute || point.minute > endMinute);
  rampMinutes.forEach((minute) => {
    const point = {
      minute,
      ...interpolate(originalPoints, minute),
    };
    if (minute <= selectedMinute) {
      const progress = selectedMinute === startMinute ? 1 : (minute - startMinute) / (selectedMinute - startMinute);
      point[channel] = easedValue(startValue, targetValue, progress);
    } else {
      const progress = selectedMinute === endMinute ? 1 : (minute - selectedMinute) / (endMinute - selectedMinute);
      point[channel] = easedValue(targetValue, endValue, progress);
    }
    upsertSchedulePoint(store, point);
  });
}

function upsertSchedulePoint(store, point) {
  const existing = store.points.findIndex((candidate) => candidate.minute === point.minute);
  if (existing >= 0) {
    store.points[existing] = { ...store.points[existing], ...point };
  } else {
    store.points.push(point);
  }
}

function uniqueSortedMinutes(minutes) {
  return [...new Set(minutes.map((minute) => Math.max(0, Math.min(1439, Number(minute)))))]
    .sort((a, b) => a - b);
}

function easedValue(from, to, progress) {
  const eased = (1 - Math.cos(Math.max(0, Math.min(1, progress)) * Math.PI)) / 2;
  return clampPercent(Math.round(from + ((to - from) * eased)));
}

function setScheduleMode(config, mode, source) {
  const store = getScheduleStore(config);
  store.mode = mode === "native" ? "native" : "manual";
  store.scheduleSource = "local";
  notifyScheduleStore(config, source);
}

function notifyScheduleStore(config, source) {
  window.dispatchEvent(new CustomEvent(SCHEDULE_STORE_EVENT, {
    detail: {
      key: getStoreKey(config),
      source,
    },
  }));
}

function persistSchedule(config, source, force = false) {
  if (!source?._hass) return;
  const store = getScheduleStore(config);
  if (store.mode === "native" && !force) return;
  clearTimeout(store.saveTimer);
  store.saveTimer = setTimeout(() => {
    saveScheduleNow(config, source).catch((error) => {
      console.warn("Unable to save Fluval schedule", error);
    });
  }, 500);
}

function saveScheduleNow(config, source) {
  if (!source?._hass) return Promise.resolve();
  const store = getScheduleStore(config);
  clearTimeout(store.saveTimer);
  store.saveTimer = null;
  return source._hass.callService("fluvalble", "save_schedule", {
    ...targetData(config),
    points: denormalizePoints(store.points),
    mode: store.mode || "manual",
  }).then(() => {
    store.scheduleSource = store.mode === "native" ? "uploaded" : "local";
    notifyScheduleStore(config, source);
    if (source.shadowRoot) source.render();
  });
}

function scheduleSourceLabel(store) {
  if (store.scheduleSource === "fixture") return "confirmed fixture readback";
  if (store.scheduleSource === "uploaded") return "uploaded; awaiting fixture readback";
  return "Home Assistant copy";
}

function effectScheduleSourceLabel(store) {
  if (store.effectSource === "fixture") return "fixture readback";
  if (store.effectSource === "uploaded") return "uploaded and saved";
  return "saved Home Assistant copy";
}

function normalizeEffectWindows(windows) {
  if (!Array.isArray(windows)) return [];
  return windows.slice(0, 7).map((effectWindow) => ({
    enabled: effectWindow?.enabled !== false,
    effect: String(effectWindow?.effect || ""),
    start: validTime(effectWindow?.start) ? effectWindow.start : "12:00",
    end: validTime(effectWindow?.end) ? effectWindow.end : "12:10",
    weekdays: Array.isArray(effectWindow?.weekdays)
      ? effectWindow.weekdays.filter((day) => WEEKDAYS.some(([value]) => value === day))
      : [],
  }));
}

function buildEffectRows(windows, options) {
  const usedDays = windows.map((effectWindow) => new Set(effectWindow.weekdays));
  return windows.map((effectWindow, index) => `
    <div class="row">
      <div class="main">
        <label class="enabled">
          <input type="checkbox" data-effect-index="${index}" data-effect-field="enabled" ${effectWindow.enabled ? "checked" : ""}>
          Enabled
        </label>
        <select data-effect-index="${index}" data-effect-field="effect">
          ${options.map((effect) => `<option value="${escapeHtml(effect)}" ${effect === effectWindow.effect ? "selected" : ""}>${escapeHtml(effect)}</option>`).join("")}
        </select>
        <label class="time">From <input type="time" data-effect-index="${index}" data-effect-field="start" value="${escapeHtml(effectWindow.start)}"></label>
        <label class="time">To <input type="time" data-effect-index="${index}" data-effect-field="end" value="${escapeHtml(effectWindow.end)}"></label>
        <button class="remove" data-effect-index="${index}">Remove</button>
      </div>
      <div class="weekdays">
        ${WEEKDAYS.map(([day, label]) => {
          const assignedElsewhere = usedDays.some((used, candidateIndex) => candidateIndex !== index && used.has(day));
          return `<label class="weekday"><input type="checkbox" data-effect-index="${index}" data-effect-weekday="${day}" ${effectWindow.weekdays.includes(day) ? "checked" : ""} ${assignedElsewhere ? "disabled" : ""}>${label}</label>`;
        }).join("")}
      </div>
    </div>
  `).join("");
}

function validateEffectWindows(windows, options) {
  if (!Array.isArray(windows) || windows.length > 7) return "Fluval controllers support at most seven effect windows";
  const usedDays = new Set();
  for (const effectWindow of windows) {
    if (!options.includes(effectWindow.effect)) return "Choose an effect supported by this fixture";
    if (!validTime(effectWindow.start) || !validTime(effectWindow.end)) return "Every effect window requires valid start and end times";
    if (effectWindow.start === "00:00" && effectWindow.end === "00:00") return "An effect window cannot start and end at 00:00";
    if (!Array.isArray(effectWindow.weekdays) || !effectWindow.weekdays.length) return "Every effect window requires at least one weekday";
    for (const day of effectWindow.weekdays) {
      if (usedDays.has(day)) return `${weekdayLabel(day)} is assigned to more than one effect window`;
      usedDays.add(day);
    }
  }
  return null;
}

function validTime(value) {
  return typeof value === "string" && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value);
}

function weekdayLabel(value) {
  return WEEKDAYS.find(([day]) => day === value)?.[1] || value;
}

function denormalizePoints(points) {
  return points.map((point) => ({
    time: formatMinute(point.minute),
    red: clampPercent(point.red),
    green: clampPercent(point.green),
    blue: clampPercent(point.blue),
    white: clampPercent(point.white),
    channel_5: clampPercent(point.channel_5),
  }));
}

const SPECTRUM_ROWS = [
  [360, 0.0001, 0.001, 0.0007, 0],
  [365, 0.0005, 0.001, 0.0005, 0],
  [370, 0.0002, 0.0007, 0.0004, 0],
  [375, 0.0003, 0.0005, 0.0003, 0],
  [380, 0, 0.0004, 0.0001, 0],
  [385, 0.0002, 0.0003, 0.0001, 0],
  [390, 0.0002, 0.0001, 0.0001, 0],
  [395, 0.0001, 0.0001, 0.0001, 0.0016],
  [400, 0.0001, 0.0002, 0.0001, 0.0048],
  [405, 0, 0.0002, 0.0001, 0.0152],
  [410, 0, 0.0001, 0.0003, 0.044],
  [415, 0.0001, 0.0001, 0.0005, 0.1176],
  [420, 0, 0.0001, 0.0016, 0.2744],
  [425, 0.0001, 0.0001, 0.0041, 0.5848],
  [430, 0, 0.0001, 0.0106, 1.1664],
  [435, 0.0001, 0.0002, 0.025, 2.124],
  [440, 0.0001, 0.0002, 0.0596, 3.7952],
  [445, 0, 0.0003, 0.13, 6.332],
  [450, 0.0001, 0.0005, 0.2675, 8],
  [455, 0, 0.0008, 0.5191, 6.5072],
  [460, 0.0001, 0.002, 0.8444, 4.3784],
  [465, 0.0001, 0.0041, 0.9979, 3.1176],
  [470, 0.0001, 0.0086, 0.7846, 2.2096],
  [475, 0.0001, 0.0178, 0.5014, 1.556],
  [480, 0, 0.0352, 0.329, 1.2976],
  [485, 0, 0.0655, 0.2154, 1.272],
  [490, 0.0001, 0.1265, 0.1257, 1.38],
  [495, 0.0001, 0.2302, 0.0765, 1.6064],
  [500, 0.0001, 0.4056, 0.0511, 1.8936],
  [505, 0.0001, 0.6715, 0.0305, 2.2016],
  [510, 0.0003, 0.9189, 0.0186, 2.4536],
  [515, 0.0002, 0.9962, 0.0119, 2.644],
  [520, 0.0001, 0.8851, 0.0077, 2.8016],
  [525, 0, 0.6791, 0.0052, 2.9008],
  [530, 0.0001, 0.5055, 0.0036, 2.9656],
  [535, 0, 0.3871, 0.0028, 3.0168],
  [540, 0.0002, 0.2825, 0.0021, 3.0512],
  [545, 0, 0.1953, 0.0016, 3.0848],
  [550, 0.0003, 0.1384, 0.0014, 3.1112],
  [555, 0.0001, 0.097, 0.0013, 3.1416],
  [560, 0.0002, 0.0685, 0.001, 3.2],
  [565, 0.0002, 0.0477, 0.0008, 3.2472],
  [570, 0.0003, 0.0344, 0.0009, 3.2912],
  [575, 0.0003, 0.0239, 0.0008, 3.3464],
  [580, 0.0006, 0.0169, 0.0008, 3.3592],
  [585, 0.0007, 0.0119, 0.0009, 3.3608],
  [590, 0.0024, 0.009, 0.0006, 3.344],
  [595, 0.0092, 0.0078, 0.0009, 3.3024],
  [600, 0.0351, 0.0058, 0.0007, 3.2152],
  [605, 0.0952, 0.0043, 0.0006, 3.1072],
  [610, 0.1849, 0.0025, 0.0008, 2.9632],
  [615, 0.3393, 0.0032, 0.0006, 2.7864],
  [620, 0.5668, 0.0021, 0.0005, 2.6176],
  [625, 0.8469, 0.0019, 0.0008, 2.4224],
  [630, 0.9761, 0.0014, 0.0006, 2.2248],
  [635, 0.6209, 0.0018, 0.0008, 2.0208],
  [640, 0.2509, 0.0019, 0.0007, 1.8056],
  [645, 0.097, 0.0016, 0.0002, 1.6192],
  [650, 0.0408, 0.0021, 0.0006, 1.4448],
  [655, 0.0181, 0.0014, 0.0008, 1.2704],
  [660, 0.009, 0.0014, 0.0004, 1.1088],
  [665, 0.0046, 0.0025, 0.0009, 0.9672],
  [670, 0.0026, 0.0016, 0.0007, 0.8392],
  [675, 0.0023, 0.0011, 0.0007, 0.7328],
  [680, 0.0015, 0.0024, 0.0005, 0.6424],
  [685, 0.0016, 0.0006, 0.0006, 0.5368],
  [690, 0.0011, 0.0014, 0.0006, 0.4656],
  [695, 0.0006, 0.0014, 0.0009, 0.3936],
  [700, 0.0012, 0.0015, 0.001, 0.3472],
  [705, 0.0007, 0.0032, 0.001, 0.3],
  [710, 0.0014, 0.0008, 0.0015, 0.2544],
  [715, 0.0014, 0.0018, 0.0012, 0.2136],
  [720, 0.0008, 0.0028, 0.0012, 0.1856],
  [725, 0, 0.0031, 0.0013, 0.164],
  [730, 0.0034, 0.0042, 0.0005, 0.1312],
  [735, 0.0009, 0.0034, 0.0015, 0.1144],
  [740, 0.0029, 0.0025, 0.0016, 0.0984],
  [745, 0.002, 0.0024, 0.0016, 0.0824],
  [750, 0.0021, 0.0014, 0.0027, 0.0696],
  [755, 0.0022, 0.0014, 0.0012, 0.0608],
  [760, 0.0012, 0.0029, 0.0013, 0.0496],
  [765, 0.0025, 0.0017, 0.0019, 0.0416],
  [770, 0.0003, 0.0019, 0.0013, 0.036],
  [775, 0.0013, 0.0046, 0.0034, 0.0336],
  [780, 0.0012, 0.0061, 0.0021, 0.028],
  [785, 0.0026, 0.0048, 0.0008, 0.0216],
  [790, 0.0001, 0.0016, 0.0013, 0.0192],
  [795, 0.0015, 0.0028, 0.0009, 0.0168],
  [800, 0.0007, 0.0036, 0.0007, 0.0136],
];

const SPECTRUM_CHANNEL_MAX = {
  red: Math.max(...SPECTRUM_ROWS.map((row) => row[1])),
  green: Math.max(...SPECTRUM_ROWS.map((row) => row[2])),
  blue: Math.max(...SPECTRUM_ROWS.map((row) => row[3])),
  white: Math.max(...SPECTRUM_ROWS.map((row) => row[4])),
};

function normalizePoints(points) {
  return [...points].map((point) => ({
    minute: parseTime(point.time),
    red: Number(point.red ?? point.channel_1 ?? 0),
    green: Number(point.green ?? point.channel_2 ?? 0),
    blue: Number(point.blue ?? point.channel_3 ?? 0),
    white: Number(point.white ?? point.channel_4 ?? 0),
    channel_5: Number(point.channel_5 ?? 0),
  })).sort((a, b) => a.minute - b.minute);
}

function interpolate(points, minute) {
  let previous = points[points.length - 1];
  let next = points[0];
  points.forEach((point, index) => {
    if (point.minute <= minute) {
      previous = point;
      next = points[(index + 1) % points.length];
    }
  });
  let start = previous.minute;
  let end = next.minute;
  if (end <= start) end += 1440;
  const current = minute >= start ? minute : minute + 1440;
  const ratio = end === start ? 0 : (current - start) / (end - start);
  const result = {};
  CHANNELS.forEach(([key]) => {
    result[key] = Math.round(previous[key] + ((next[key] - previous[key]) * ratio));
  });
  return result;
}

function buildGraph(points) {
  return CHANNELS.map(([key, color]) => {
    const samples = [];
    for (let minute = 0; minute <= 1440; minute += 10) {
      const channels = interpolate(points, minute % 1440);
      const x = (minute / 1440) * 720;
      const y = 200 - (channels[key] / 100) * 180;
      samples.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
    return `<polyline class="line" stroke="${color}" points="${samples.join(" ")}"></polyline>`;
  }).join("");
}

function buildChannelBars(channels, editable = false) {
  return CHANNELS.map(([key, color, label]) => `
    <div class="bar-row">
      <div class="label">${label}</div>
      <div class="bar">
        <span style="width:${clampPercent(channels[key])}%;background:${color}"></span>
        ${editable ? `<input class="channel-slider" data-channel="${key}" type="range" min="0" max="100" step="1" value="${clampPercent(channels[key])}">` : ""}
      </div>
      <div class="value">${clampPercent(channels[key])}%</div>
    </div>
  `).join("");
}

function buildWavelengthSpectrum(channels) {
  const rows = buildSpectrumRows(channels);
  const path = rows.map((row) => `${row.x.toFixed(1)},${row.y.toFixed(1)}`).join(" ");
  const fill = `30,184 ${path} 690,184`;

  return `
    <svg class="spectrum-chart" viewBox="0 0 720 260" preserveAspectRatio="none">
      <defs>
        <linearGradient id="visible-spectrum" x1="0%" y1="0%" x2="100%" y2="0%">
          ${[360, 380, 440, 490, 510, 580, 645, 700, 800].map((wavelength) => `
            <stop offset="${(((wavelength - 360) / 440) * 100).toFixed(1)}%" stop-color="${wavelengthColor(wavelength)}"></stop>
          `).join("")}
        </linearGradient>
      </defs>
      <rect x="30" y="16" width="660" height="168" fill="url(#visible-spectrum)" opacity=".24"></rect>
      <line x1="30" y1="184" x2="690" y2="184" class="spectrum-axis"></line>
      <line x1="30" y1="16" x2="30" y2="184" class="spectrum-axis"></line>
      ${[400, 500, 600, 700, 800].map((wavelength) => {
        const x = spectrumX(wavelength);
        return `<line x1="${x}" y1="16" x2="${x}" y2="184" class="spectrum-grid"></line>
          <text x="${x}" y="204" text-anchor="middle" class="spectrum-label">${wavelength}</text>`;
      }).join("")}
      <text x="360" y="216" text-anchor="middle" class="spectrum-label">Wavelength (nm)</text>
      <polygon class="spectrum-fill" points="${fill}"></polygon>
      <polyline class="spectrum-curve" points="${path}"></polyline>
      <text x="42" y="32" text-anchor="start" class="spectrum-label">Relative emitted light</text>
    </svg>
  `;
}

function buildSpectrumRows(channels) {
  const gains = {
    red: clampPercent(channels.red) / 100,
    green: clampPercent(channels.green) / 100,
    blue: clampPercent(channels.blue) / 100,
    white: clampPercent(channels.white) / 100,
    channel_5: clampPercent(channels.channel_5) / 100,
  };
  const values = SPECTRUM_ROWS.map(([wavelength, red, green, blue, white]) => {
    const value = (
      ((red / SPECTRUM_CHANNEL_MAX.red) * gains.red)
      + ((green / SPECTRUM_CHANNEL_MAX.green) * gains.green)
      + ((blue / SPECTRUM_CHANNEL_MAX.blue) * gains.blue)
      + ((white / SPECTRUM_CHANNEL_MAX.white) * gains.white)
      + (gaussian(wavelength, 420, 16) * gains.channel_5)
    );
    return { wavelength, value };
  });
  return values.map((row) => {
    const normalized = Math.max(0, Math.min(1, row.value));
    return {
      wavelength: row.wavelength,
      normalized,
      x: spectrumX(row.wavelength),
      y: 184 - (normalized * 160),
    };
  });
}

function spectrumX(wavelength) {
  return 30 + (((wavelength - 360) / 440) * 660);
}

function wavelengthColor(wavelength) {
  if (wavelength < 380) return "#3c1a78";
  if (wavelength < 440) return "#5438ff";
  if (wavelength < 490) return "#1f7cff";
  if (wavelength < 510) return "#18b8a6";
  if (wavelength < 580) return "#48d45b";
  if (wavelength < 645) return "#ffcc33";
  if (wavelength < 700) return "#ff4a2f";
  return "#6d1010";
}

function gaussian(value, peak, width) {
  return Math.exp(-0.5 * ((value - peak) / width) ** 2);
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

function parseTime(value) {
  const [hour, minute] = String(value).split(":").map(Number);
  return ((hour % 24) * 60) + minute;
}

function formatMinute(value) {
  const minute = value % 1440;
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}

function targetData(config) {
  const data = {};
  if (config.entry_id) data.entry_id = config.entry_id;
  if (config.mac) data.mac = config.mac;
  return data;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

if (!customElements.get("fluvalble-schedule-card")) {
  customElements.define("fluvalble-schedule-card", FluvalbleScheduleCard);
}
if (!customElements.get("fluvalble-effect-schedule-card")) {
  customElements.define("fluvalble-effect-schedule-card", FluvalbleEffectScheduleCard);
}
if (!customElements.get("fluvalble-spectrum-card")) {
  customElements.define("fluvalble-spectrum-card", FluvalbleSpectrumCard);
}
if (!customElements.get("fluvalble-wavelength-card")) {
  customElements.define("fluvalble-wavelength-card", FluvalbleWavelengthCard);
}

window.customCards = window.customCards || [];
registerCustomCard({
  type: "fluvalble-schedule-card",
  name: "Fluval BLE Schedule",
  description: "24-hour channel graph and physical preview controls for Fluval BLE lights.",
});
registerCustomCard({
  type: "fluvalble-effect-schedule-card",
  name: "Fluval BLE Timed Effects",
  description: "Edit and upload fixture-native timed effects for Fluval BLE lights.",
});
registerCustomCard({
  type: "fluvalble-spectrum-card",
  name: "Fluval BLE Spectrum",
  description: "Channel bar spectrum and physical preview controls for Fluval BLE lights.",
});
registerCustomCard({
  type: "fluvalble-wavelength-card",
  name: "Fluval BLE Wavelength Preview",
  description: "Wavelength emission preview graph for the selected schedule time.",
});

function registerCustomCard(card) {
  if (!window.customCards.some((existing) => existing.type === card.type)) {
    window.customCards.push(card);
  }
}
