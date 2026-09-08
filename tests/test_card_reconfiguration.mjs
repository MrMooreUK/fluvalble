// Isolated card lifecycle checks; no Home Assistant or browser is contacted.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const root = new URL("../custom_components/fluvalble/www/", import.meta.url);
const spectra = readFileSync(new URL("fluvalble-spectrum-data.js", root), "utf8")
  .replace(/export /g, "");
const cards = readFileSync(new URL("fluvalble-schedule-card.js", root), "utf8")
  .replace(/^import .*;\r?\n/, "");

for (const name of ["schedule", "effect-schedule", "spectrum", "wavelength"]) {
  test(`${name} card can be reconfigured without replacing its shadow root`, () => {
    const registry = new Map();
    const listeners = new Set();
    const context = vm.createContext({
      HTMLElement: class {
        attachShadow() {
          // Enforce the DOM's single-shadow-root constraint.
          if (this.shadowRoot) throw new Error("NotSupportedError");
          return (this.shadowRoot = {});
        }
      },
      customElements: {
        get: (key) => registry.get(key),
        define: (key, value) => registry.set(key, value),
      },
      window: {
        addEventListener: (_event, listener) => listeners.add(listener),
        removeEventListener: (_event, listener) => listeners.delete(listener),
      },
    });
    vm.runInContext(`${spectra}\n${cards}`, context);
    const Card = registry.get(`fluvalble-${name}-card`);
    const card = new Card();
    let renders = 0;
    card.render = () => { renders += 1; };
    card.setConfig({ entry_id: "first", title: "First" });
    const shadow = card.shadowRoot;
    const listenerCount = listeners.size;
    card.setConfig({ entry_id: "second", title: "Second" });
    assert.equal(card.shadowRoot, shadow);
    assert.equal(card.config.title, "Second");
    assert.equal(renders, 2);
    assert.equal(listeners.size, listenerCount);
  });
}
