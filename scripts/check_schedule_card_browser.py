"""Run isolated browser checks: python scripts/check_schedule_card_browser.py.

Requires Playwright and its Chromium browser in the development environment.
No Home Assistant, Bluetooth device or user browser is contacted.
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def main():
    source = (Path(__file__).resolve().parents[1] / "custom_components/fluvalble/www/schedule-colours.js").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        for early in (True, False):
            page = await browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.set_content("<body></body>")
            if not early:
                await page.evaluate("customElements.define('home-assistant', class extends HTMLElement {})")
            await page.add_script_tag(content=source)
            if early:
                assert await page.evaluate("!window.customCards && !customElements.get('fluval-schedule-colours')")
                # Model the registry handover installed by HA's scoped registry.
                # The real HA 2026.9.2 image was also used to reproduce the race.
                await page.evaluate("""() => {
                    const native=customElements, definitions=new Map();
                    Object.defineProperty(window,'customElements',{value:{
                        get:name=>definitions.get(name),
                        define:(name,component)=>{native.define(name,component);definitions.set(name,component);}
                    }});
                    customElements.define('home-assistant', class extends HTMLElement {});
                }""")
            await page.wait_for_function("!!customElements.get('fluval-schedule-colours')")
            result = await page.evaluate("""async () => {
                const metadata=window.customCards[0];
                const Card=customElements.get(metadata.type);
                // HA's picker awaits this before replacing its spinner.
                const config=await Card.getStubConfig();
                const card=document.createElement(metadata.type);
                const calls=[];
                card.setConfig(config);
                card.hass={callWS:async message=>{
                    calls.push(message);
                    return {refresh_ok:null,fixture:{channels:[]},colour_editor:{auto:null,professional:null}};
                }};
                document.body.append(card);
                const pickerRequests=calls.length;
                card.setConfig({entry_id:'fixture'});
                await new Promise(resolve=>setTimeout(resolve,0));
                return {config,pickerRequests,calls,busy:card.busy};
            }""")
            assert result["config"]["type"] == "custom:fluval-schedule-colours"
            assert result["pickerRequests"] == 0
            assert len(result["calls"]) == 1 and result["calls"][0]["refresh"] is False
            assert result["busy"] is False
            await page.add_script_tag(content=source)
            assert await page.evaluate("window.customCards.length") == 1
            assert errors == []
            await page.close()
        await browser.close()
    print("PASS: early/late registration, registry replacement, picker stub, duplicate import, cached selection")


asyncio.run(main())
