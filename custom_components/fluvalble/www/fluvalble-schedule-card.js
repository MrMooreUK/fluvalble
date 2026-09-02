import { SPECTRUM_PROFILES } from "./fluvalble-spectrum-data.js";

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
    if (this.store.editorMode === "auto") {
      this.renderAutoEditor();
      return;
    }

    const points = this.store.points;
    const time = formatMinute(this.previewMinute);
    const graph = buildGraph(points, scheduleChannelDefinitions(this.store));

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
              Schedule type
              <select id="editor-mode">
                <option value="professional" selected>Professional</option>
                <option value="auto">Auto</option>
              </select>
            </label>
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
            <button id="preview-fixture">Preview fixture time</button>
            <button id="play-fixture">Play fixture schedule</button>
            <button id="play">Play editor preview</button>
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

    root.getElementById("editor-mode").addEventListener("change", (event) => {
      this.store.editorMode = event.target.value === "auto" ? "auto" : "professional";
      notifyScheduleStore(this.config, this);
      this.render();
    });

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
    root.getElementById("preview-fixture").addEventListener("click", () => {
      this.previewNativeSchedule("professional", this.previewMinute);
    });
    root.getElementById("play-fixture").addEventListener("click", () => {
      this.startNativePreviewPlayback("professional");
    });
    root.getElementById("stop").addEventListener("click", () => {
      this.stopPreviewPlayback();
    });
  }

  renderAutoEditor() {
    const root = this.shadowRoot;
    if (!root) return;
    const schedule = this.store.autoSchedule;
    const channels = autoChannelLabels(this.store);
    const sleepEnabled = Boolean(schedule.sleep);

    root.innerHTML = `
      <ha-card>
        <div class="card">
          <div class="header">
            <div>
              <div class="title">${escapeHtml(this.config.title)}</div>
              <div class="subtitle">Fixture-native Auto schedule · ${autoScheduleSourceLabel(this.store)}</div>
            </div>
          </div>

          <div class="toolbar">
            <label class="control">
              Schedule type
              <select id="editor-mode">
                <option value="professional">Professional</option>
                <option value="auto" selected>Auto</option>
              </select>
            </label>
          </div>

          <div class="time-grid">
            <label class="control">Sunrise
              <input type="time" data-auto-field="sunrise" value="${escapeHtml(schedule.sunrise)}">
            </label>
            <label class="control">Sunrise ramp
              <span class="number"><input type="number" min="0" max="240" step="1" data-auto-field="sunrise_ramp" value="${schedule.sunrise_ramp}"> min</span>
            </label>
            <label class="control">Sunset
              <input type="time" data-auto-field="sunset" value="${escapeHtml(schedule.sunset)}">
            </label>
            <label class="control">Sunset ramp
              <span class="number"><input type="number" min="0" max="240" step="1" data-auto-field="sunset_ramp" value="${schedule.sunset_ramp}"> min</span>
            </label>
          </div>

          <div class="sleep-row">
            <label class="check"><input id="sleep-enabled" type="checkbox" ${sleepEnabled ? "checked" : ""}> Enable sleep time</label>
            <input id="sleep-time" type="time" value="${escapeHtml(schedule.sleep || "23:00")}" ${sleepEnabled ? "" : "disabled"}>
          </div>

          <div class="levels-grid">
            <section>
              <h3>Day levels</h3>
              ${buildAutoLevelRows("day", schedule.day_levels, channels)}
            </section>
            <section>
              <h3>Night levels</h3>
              ${buildAutoLevelRows("night", schedule.night_levels, channels)}
            </section>
          </div>

          <div class="fixture-preview">
            <div><strong>Stored fixture preview</strong> · <span id="native-preview-time">${formatMinute(this.previewMinute)}</span></div>
            <div class="time-row">
              <span>00:00</span>
              <input id="native-preview-minute" type="range" min="0" max="1439" step="5" value="${this.previewMinute}">
              <span>24:00</span>
            </div>
            <div class="note">Uses only the Auto schedule already stored on the fixture. Unsaved editor values are never uploaded by preview.</div>
          </div>

          <div class="note">The controller stores this schedule and runs it from its own clock. Saving switches the fixture to Automatic mode.</div>
          <div class="actions">
            <button id="save-auto">Save Auto to fixture</button>
            <button id="load-fixture">Load Auto from fixture</button>
            <button id="preview-fixture">Preview fixture time</button>
            <button id="play-fixture">Play fixture schedule</button>
            <button id="stop">Stop preview</button>
          </div>
        </div>
      </ha-card>
      <style>
        .card { padding: 16px; }
        .header { align-items: center; display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
        .title { font-size: 18px; font-weight: 600; }
        .subtitle, .note { color: var(--secondary-text-color); font-size: 13px; margin-top: 3px; }
        .toolbar { display: flex; margin-bottom: 16px; }
        .time-grid, .levels-grid { display: grid; gap: 14px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .control { color: var(--secondary-text-color); display: grid; font-size: 13px; gap: 6px; }
        input, select { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 6px; box-sizing: border-box; color: var(--primary-text-color); padding: 8px 10px; width: 100%; }
        input[type="checkbox"] { width: auto; }
        .number { align-items: center; display: grid; gap: 6px; grid-template-columns: minmax(0, 1fr) auto; }
        .sleep-row { align-items: center; display: flex; gap: 12px; margin: 16px 0; }
        .check { align-items: center; display: flex; gap: 7px; white-space: nowrap; }
        .sleep-row input[type="time"] { max-width: 150px; }
        .fixture-preview { border: 1px solid var(--divider-color); border-radius: 8px; margin-top: 16px; padding: 12px; }
        .time-row { align-items: center; color: var(--secondary-text-color); display: grid; font-size: 12px; gap: 10px; grid-template-columns: auto 1fr auto; margin-top: 10px; }
        .time-row input { padding: 0; }
        section { border: 1px solid var(--divider-color); border-radius: 8px; padding: 12px; }
        h3 { font-size: 14px; margin: 0 0 12px; }
        .level-row { align-items: center; display: grid; gap: 10px; grid-template-columns: 92px minmax(0, 1fr) 42px; margin-top: 9px; }
        .level-row label { font-size: 13px; }
        .level-row input { padding: 0; }
        .level-value { color: var(--secondary-text-color); font-size: 12px; text-align: right; }
        .note { margin-top: 14px; }
        .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
        button { background: var(--primary-color); border: 0; border-radius: 6px; color: var(--text-primary-color); cursor: pointer; padding: 8px 12px; }
        button#load-fixture { background: var(--secondary-background-color); color: var(--primary-text-color); }
        button#stop { background: var(--error-color); }
        @media (max-width: 620px) { .time-grid, .levels-grid { grid-template-columns: 1fr; } }
      </style>
    `;

    root.getElementById("editor-mode").addEventListener("change", (event) => {
      this.store.editorMode = event.target.value === "auto" ? "auto" : "professional";
      notifyScheduleStore(this.config, this);
      this.render();
    });
    root.querySelectorAll("[data-auto-field]").forEach((input) => {
      input.addEventListener("change", (event) => {
        const field = event.target.dataset.autoField;
        schedule[field] = field.endsWith("_ramp")
          ? clampRamp(event.target.value)
          : event.target.value;
        this.store.autoSource = "local";
        notifyScheduleStore(this.config, this);
      });
    });
    root.getElementById("sleep-enabled").addEventListener("change", (event) => {
      schedule.sleep = event.target.checked ? root.getElementById("sleep-time").value : null;
      this.store.autoSource = "local";
      notifyScheduleStore(this.config, this);
      this.render();
    });
    root.getElementById("sleep-time").addEventListener("change", (event) => {
      schedule.sleep = event.target.value;
      this.store.autoSource = "local";
      notifyScheduleStore(this.config, this);
    });
    root.querySelectorAll("[data-auto-level]").forEach((slider) => {
      slider.addEventListener("input", (event) => {
        const period = event.target.dataset.autoLevel;
        const index = Number(event.target.dataset.channelIndex);
        schedule[`${period}_levels`][index] = clampPercent(event.target.value);
        event.target.closest(".level-row").querySelector(".level-value").textContent = `${clampPercent(event.target.value)}%`;
        this.store.autoSource = "local";
        notifyScheduleStore(this.config, this);
      });
    });
    root.getElementById("save-auto").addEventListener("click", () => {
      this.saveAutoSchedule();
    });
    root.getElementById("load-fixture").addEventListener("click", () => {
      this.loadFixtureSchedule();
    });
    root.getElementById("native-preview-minute").addEventListener("input", (event) => {
      this.previewMinute = Number(event.target.value);
      setSelectedMinute(this.config, this.previewMinute, this);
      this.updateLocalTimeDisplay();
    });
    root.getElementById("preview-fixture").addEventListener("click", () => {
      this.previewNativeSchedule("auto", this.previewMinute);
    });
    root.getElementById("play-fixture").addEventListener("click", () => {
      this.startNativePreviewPlayback("auto");
    });
    root.getElementById("stop").addEventListener("click", () => {
      this.stopPreviewPlayback();
    });
  }

  async saveAutoSchedule() {
    const error = validateAutoSchedule(this.store.autoSchedule);
    if (error) {
      this.toast(error);
      return;
    }
    try {
      await this.callService("set_native_auto_schedule", {
        ...targetData(this.config),
        schedule: autoSchedulePayload(this.store.autoSchedule),
      });
      this.store.autoSource = "uploaded";
      this.store.fixture = { ...(this.store.fixture || {}), auto: null };
      notifyScheduleStore(this.config, this);
      this.render();
      this.toast("Auto schedule uploaded to the fixture");
    } catch (error) {
      console.warn("Unable to save the Fluval Auto schedule", error);
      this.toast("Unable to save the Auto schedule to the fixture");
    }
  }

  hasFixtureSchedule(scheduleType) {
    if (scheduleType === "auto") return Boolean(this.store.fixture?.auto);
    return Array.isArray(this.store.fixture?.professional) && this.store.fixture.professional.length > 0;
  }

  async previewNativeSchedule(scheduleType, minute, quiet = false) {
    if (!this.hasFixtureSchedule(scheduleType)) {
      this.toast(`Load the fixture's ${scheduleType === "auto" ? "Auto" : "Professional"} schedule before previewing it`);
      return false;
    }
    try {
      await this.callService("preview_native_schedule", {
        ...targetData(this.config),
        minute: Math.max(0, Math.min(1439, Math.round(Number(minute) || 0))),
        schedule_type: scheduleType,
      });
      this.store.nativePreviewActive = true;
      if (!quiet) this.toast(`Previewing the stored fixture schedule at ${formatMinute(minute)}`);
      return true;
    } catch (error) {
      console.warn("Unable to preview the Fluval fixture schedule", error);
      this.stopNativePreviewTimerOnly();
      this.toast("Unable to preview the schedule stored on the fixture");
      return false;
    }
  }

  startNativePreviewPlayback(scheduleType) {
    if (!this.hasFixtureSchedule(scheduleType)) {
      this.toast(`Load the fixture's ${scheduleType === "auto" ? "Auto" : "Professional"} schedule before previewing it`);
      return;
    }
    if (this.store.playing) {
      this.toast("Stop the editor preview before starting fixture preview");
      return;
    }
    this.stopPreviewTimerOnly();
    this.stopNativePreviewTimerOnly();
    const durationMs = Math.max(1, Number(this.config.preview_duration || 60)) * 1000;
    const startedAt = Date.now();
    this.store.nativePreviewPlaying = true;

    const tick = () => {
      if (!this.store.nativePreviewPlaying) return;
      const elapsed = Date.now() - startedAt;
      if (elapsed >= durationMs) {
        this.stopPreviewPlayback();
        return;
      }
      const minute = Math.min(1439, Math.round((elapsed / durationMs) * 1439));
      this.previewMinute = minute;
      setSelectedMinute(this.config, minute, this);
      this.updateLocalTimeDisplay();
      if (!this.store.nativePreviewWriteInFlight) {
        this.store.nativePreviewWriteInFlight = true;
        this.previewNativeSchedule(scheduleType, minute, true).finally(() => {
          this.store.nativePreviewWriteInFlight = false;
        });
      }
    };

    tick();
    const intervalMs = Math.max(500, Number(this.config.step_seconds || 2) * 1000);
    this.store.nativePreviewTimer = setInterval(tick, intervalMs);
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

  async startPreviewPlayback() {
    if (this.store.nativePreviewActive || this.store.nativePreviewPlaying) {
      this.stopNativePreviewTimerOnly();
      try {
        await this.callService("stop_preview", targetData(this.config));
        this.store.nativePreviewActive = false;
      } catch (error) {
        console.warn("Unable to stop fixture preview before editor playback", error);
        this.toast("Stop fixture preview before starting editor playback");
        return;
      }
    }
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
    const wasNativePreview = Boolean(this.store.nativePreviewActive || this.store.nativePreviewPlaying);
    this.stopPreviewTimerOnly();
    this.stopNativePreviewTimerOnly();
    const stopped = this.callService("stop_preview", targetData(this.config));
    this.store.nativePreviewActive = false;

    if (wasNativePreview) {
      stopped
        .then(() => this.toast("Fixture schedule preview stopped"))
        .catch((error) => {
          console.warn("Unable to stop the Fluval fixture preview", error);
          this.store.nativePreviewActive = true;
          this.toast("Unable to stop fixture schedule preview");
        });
      return;
    }

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

  stopNativePreviewTimerOnly() {
    if (this.store?.nativePreviewTimer) {
      clearInterval(this.store.nativePreviewTimer);
      this.store.nativePreviewTimer = null;
    }
    if (this.store) {
      this.store.nativePreviewPlaying = false;
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
      if (this.store.editorMode === "auto") {
        const auto = this.store.fixture?.auto;
        if (!auto) {
          this.toast("No Auto schedule readback is available from the fixture");
          return;
        }
        this.store.autoSchedule = normalizeAutoSchedule(auto);
        this.store.autoSource = "fixture";
        notifyScheduleStore(this.config, this);
        this.render();
        this.toast(
          result.refresh_ok === false
            ? "Loaded the last Auto readback; the live refresh did not complete"
            : "Loaded the Auto schedule confirmed by the fixture",
        );
        return;
      }
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
    const nativePreviewTime = root.getElementById("native-preview-time");
    const nativePreviewInput = root.getElementById("native-preview-minute");
    if (subtitle) subtitle.textContent = `${time} preview · ${scheduleSourceLabel(this.store)}`;
    if (timeInput) timeInput.value = this.previewMinute;
    if (nativePreviewTime) nativePreviewTime.textContent = time;
    if (nativePreviewInput) nativePreviewInput.value = this.previewMinute;
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
    this.stopNativePreviewTimerOnly();
    if (this.store?.nativePreviewActive) {
      this.callService("stop_preview", targetData(this.config));
      this.store.nativePreviewActive = false;
    }
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

          <div class="spectrum">${buildChannelBars(channels, true, scheduleChannelDefinitions(this.store))}</div>
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
    this.loadFixtureProfile();
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

          <div class="spectrum">${buildWavelengthSpectrum(
            channels,
            this.store.fixture?.spectrum_profile || this.config.spectrum_profile,
          )}</div>
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
        .spectrum-unavailable { color: var(--secondary-text-color); padding: 24px 8px; text-align: center; }
      </style>
    `;
  }

  async loadFixtureProfile() {
    if (
      !this._hass
      || this.store.fixture?.spectrum_profile
      || this.config.spectrum_profile
      || this.store.loaded
      || this.store.spectrumProfileLoaded
      || this.store.loadingSpectrumProfile
    ) return;
    this.store.loadingSpectrumProfile = true;
    try {
      const result = await this._hass.callWS({
        type: "fluvalble/get_schedule",
        ...targetData(this.config),
      });
      this.store.fixture = result?.fixture || null;
      this.store.spectrumProfileLoaded = true;
      notifyScheduleStore(this.config, this);
      this.render();
    } catch (error) {
      console.warn("Unable to load Fluval spectrum profile", error);
    } finally {
      this.store.loadingSpectrumProfile = false;
    }
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
  { time: "00:00", channel_1: 0, channel_2: 0, channel_3: 0, channel_4: 0, channel_5: 0 },
  { time: "10:00", channel_1: 0, channel_2: 0, channel_3: 0, channel_4: 0, channel_5: 0 },
  { time: "11:00", channel_1: 10, channel_2: 10, channel_3: 25, channel_4: 5, channel_5: 0 },
  { time: "16:00", channel_1: 10, channel_2: 10, channel_3: 25, channel_4: 5, channel_5: 0 },
  { time: "19:00", channel_1: 3, channel_2: 0, channel_3: 8, channel_4: 0, channel_5: 0 },
  { time: "20:00", channel_1: 0, channel_2: 0, channel_3: 0, channel_4: 0, channel_5: 0 },
];

const DEFAULT_AUTO_SCHEDULE = {
  sunrise: "08:00",
  sunrise_ramp: 60,
  sunset: "20:00",
  sunset_ramp: 60,
  sleep: null,
  day_levels: [80, 70, 60, 50, 0],
  night_levels: [0, 5, 0, 0, 0],
};

const NATIVE_SERVICE_CHANNELS = ["channel_1", "channel_2", "channel_3", "channel_4", "channel_5"];

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
      editorMode: config.schedule_type === "auto" ? "auto" : "professional",
      mode: "manual",
      scheduleSource: "local",
      autoSchedule: normalizeAutoSchedule(config.auto_schedule || DEFAULT_AUTO_SCHEDULE),
      autoSource: "local",
      nativePreviewActive: false,
      nativePreviewPlaying: false,
      nativePreviewWriteInFlight: false,
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
    if (store.mode === "native") {
      store.fixture = { ...(store.fixture || {}), professional: null };
    }
    notifyScheduleStore(config, source);
    if (source.shadowRoot) source.render();
  });
}

function scheduleSourceLabel(store) {
  if (store.scheduleSource === "fixture") return "confirmed fixture readback";
  if (store.scheduleSource === "uploaded") return "uploaded; awaiting fixture readback";
  return "Home Assistant copy";
}

function autoScheduleSourceLabel(store) {
  if (store.autoSource === "fixture") return "confirmed fixture readback";
  if (store.autoSource === "uploaded") return "uploaded; awaiting fixture readback";
  return "unsaved editor copy";
}

function normalizeAutoSchedule(schedule) {
  const levels = (value, fallback) => {
    const normalized = Array.isArray(value) ? value.slice(0, 5).map(clampPercent) : [...fallback];
    while (normalized.length < 5) normalized.push(0);
    return normalized;
  };
  return {
    sunrise: validTime(schedule?.sunrise) ? schedule.sunrise : DEFAULT_AUTO_SCHEDULE.sunrise,
    sunrise_ramp: clampRamp(schedule?.sunrise_ramp ?? DEFAULT_AUTO_SCHEDULE.sunrise_ramp),
    sunset: validTime(schedule?.sunset) ? schedule.sunset : DEFAULT_AUTO_SCHEDULE.sunset,
    sunset_ramp: clampRamp(schedule?.sunset_ramp ?? DEFAULT_AUTO_SCHEDULE.sunset_ramp),
    sleep: validTime(schedule?.sleep) ? schedule.sleep : null,
    day_levels: levels(schedule?.day_levels, DEFAULT_AUTO_SCHEDULE.day_levels),
    night_levels: levels(schedule?.night_levels, DEFAULT_AUTO_SCHEDULE.night_levels),
  };
}

function autoChannelLabels(store) {
  const labels = Array.isArray(store.fixture?.channels) && store.fixture.channels.length
    ? store.fixture.channels
    : ["Channel 1", "Channel 2", "Channel 3", "Channel 4", "Channel 5"];
  return labels.slice(0, 5);
}

function scheduleChannelDefinitions(store) {
  const labels = autoChannelLabels(store);
  return CHANNELS.slice(0, labels.length).map(([key, color, fallback], index) => [
    key,
    color,
    labels[index] || fallback,
  ]);
}

function buildAutoLevelRows(period, levels, labels) {
  return labels.map((label, index) => `
    <div class="level-row">
      <label>${escapeHtml(label)}</label>
      <input type="range" min="0" max="100" step="1" data-auto-level="${period}" data-channel-index="${index}" value="${clampPercent(levels[index])}">
      <span class="level-value">${clampPercent(levels[index])}%</span>
    </div>
  `).join("");
}

function autoSchedulePayload(schedule) {
  const levelMap = (levels) => Object.fromEntries(
    NATIVE_SERVICE_CHANNELS.map((channel, index) => [channel, clampPercent(levels[index])]),
  );
  return {
    sunrise: schedule.sunrise,
    sunrise_ramp: clampRamp(schedule.sunrise_ramp),
    sunset: schedule.sunset,
    sunset_ramp: clampRamp(schedule.sunset_ramp),
    sleep: schedule.sleep || null,
    day: levelMap(schedule.day_levels),
    night: levelMap(schedule.night_levels),
  };
}

function validateAutoSchedule(schedule) {
  if (!validTime(schedule.sunrise) || !validTime(schedule.sunset)) return "Choose valid sunrise and sunset times";
  if (schedule.sleep && !validTime(schedule.sleep)) return "Choose a valid sleep time or disable it";
  if (![schedule.sunrise_ramp, schedule.sunset_ramp].every((value) => Number.isInteger(Number(value)) && Number(value) >= 0 && Number(value) <= 240)) {
    return "Sunrise and sunset ramps must be between 0 and 240 minutes";
  }
  if (![schedule.day_levels, schedule.night_levels].every((levels) => Array.isArray(levels) && levels.length === 5)) {
    return "Day and night schedules require all fixture channel levels";
  }
  return null;
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
    channel_1: clampPercent(point.red),
    channel_2: clampPercent(point.green),
    channel_3: clampPercent(point.blue),
    channel_4: clampPercent(point.white),
    channel_5: clampPercent(point.channel_5),
  }));
}


function normalizePoints(points) {
  return [...points].map((point) => ({
    minute: parseTime(point.time),
    red: Number(point.channel_1 ?? point.red ?? 0),
    green: Number(point.channel_2 ?? point.green ?? 0),
    blue: Number(point.channel_3 ?? point.blue ?? 0),
    white: Number(point.channel_4 ?? point.white ?? 0),
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

function buildGraph(points, definitions = CHANNELS) {
  return definitions.map(([key, color]) => {
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

function buildChannelBars(channels, editable = false, definitions = CHANNELS) {
  return definitions.map(([key, color, label]) => `
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

function buildWavelengthSpectrum(channels, profileName) {
  const rows = buildSpectrumRows(channels, profileName);
  if (!rows.length) {
    return `<div class="spectrum-unavailable">
      Wavelength data is unavailable until this card is linked to a fixture with an APK-known product ID.
    </div>`;
  }
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

function buildSpectrumRows(channels, profileName) {
  const profile = SPECTRUM_PROFILES[profileName];
  if (!profile) return [];
  const gains = {
    red: clampPercent(channels.red) / 100,
    green: clampPercent(channels.green) / 100,
    blue: clampPercent(channels.blue) / 100,
    white: clampPercent(channels.white) / 100,
    channel_5: clampPercent(channels.channel_5) / 100,
  };
  const maxima = profile.channel_keys.map((_, column) => (
    Math.max(...profile.rows.map((row) => row[column + 1])) || 1
  ));
  const values = profile.rows.map((row) => {
    const [wavelength] = row;
    const value = profile.channel_keys.reduce((total, channel, column) => (
      total + ((row[column + 1] / maxima[column]) * gains[channel])
    ), 0);
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

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

function clampRamp(value) {
  return Math.max(0, Math.min(240, Math.round(Number(value) || 0)));
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
  description: "Edit fixture-native Auto and Professional schedules for Fluval BLE lights.",
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
