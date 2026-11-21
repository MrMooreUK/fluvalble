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
            for count in (4, 5):
                await page.evaluate(
                    """count => {
                    const card=document.querySelector('fluval-schedule-colours');
                    card.fixture={mode:'automatic',channels:Array.from({length:count},(_,i)=>'Emitter '+(i+1))};
                    card.raw={
                        auto:{sunrise:{hour:23,minute:30,ramp:60},sunset:{hour:18,minute:15,ramp:45},
                              sleep:{hour:22,minute:0},day_levels:Array(count).fill(50),night_levels:Array(count).fill(5)},
                        professional:[30,480,900,1380].map(minute=>Object.assign({minute},
                            Object.fromEntries(Array.from({length:count},(_,i)=>['channel_'+(i+1),(i+1)*10]))))
                    };
                    card.mode='auto';card.render();
                }""",
                    count,
                )
                assert await page.get_by_label("Sunrise starts", exact=True).input_value() == "23:30"
                assert await page.get_by_label("Sunrise ends", exact=True).input_value() == "00:30"
                assert await page.locator("input[type=range]").count() == count * 2
                await page.get_by_role("button", name="Professional", exact=True).click()
                assert await page.get_by_role("button", name="08:00", exact=True).count() == 1
                await page.get_by_role("button", name="08:00", exact=True).click()
                assert await page.get_by_label("Timepoint time").input_value() == "08:00"
                assert await page.locator("input[type=range]").count() == count
                assert "These tabs only select a schedule" in await page.locator("ha-card").inner_text()
            await page.add_script_tag(content=source)
            assert await page.evaluate("window.customCards.length") == 1
            await page.evaluate("""() => {
                const card=document.querySelector('fluval-schedule-colours');
                card.mode='auto';card.render();
                const editor=document.createElement('fluval-schedule-colours-editor');
                editor.devices=[{id:'fixture',name:'Fish tank'}];
                editor.setConfig({entry_id:'fixture',title:'My tank'});
                editor.addEventListener('config-changed',event=>{
                    window.savedConfig=event.detail.config;
                    card.setConfig(event.detail.config);
                });
                document.body.append(editor);
            }""")
            assert await page.locator("details").evaluate_all("(banks)=>banks.map(bank=>bank.open)") == [False, False]
            assert await page.get_by_label("Start Day and Night collapsed", exact=False).count() == 0
            await page.locator("summary").filter(has_text="Day").click()
            await page.evaluate("document.querySelector('fluval-schedule-colours').render()")
            assert await page.locator("details").evaluate_all("(banks)=>banks.map(bank=>bank.open)") == [True, False]
            # A redraw in the same JS task must retain native state even before
            # the asynchronous toggle event has been dispatched.
            await page.evaluate("""() => {
                const card=document.querySelector('fluval-schedule-colours');
                card.shadowRoot.querySelectorAll('details')[1].open=true;card.render();
            }""")
            assert await page.locator("details").evaluate_all("(banks)=>banks.map(bank=>bank.open)") == [True, True]
            await page.get_by_role("button", name="Professional", exact=True).click()
            await page.get_by_role("button", name="Automatic", exact=True).click()
            assert await page.locator("details").evaluate_all("(banks)=>banks.map(bank=>bank.open)") == [True, True]
            await page.locator("summary").filter(has_text="Day").click()
            await page.evaluate("document.querySelector('fluval-schedule-colours').render()")
            assert await page.locator("details").evaluate_all("(banks)=>banks.map(bank=>bank.open)") == [False, True]
            result = await page.evaluate("""() => {
                const card=document.querySelector('fluval-schedule-colours');
                const fresh=document.createElement('fluval-schedule-colours');
                fresh.setConfig({entry_id:'fresh',collapse_sections:false});
                fresh.fixture=card.fixture;fresh.raw=card.raw;fresh.render();
                const initial=[...fresh.shadowRoot.querySelectorAll('details')].map(bank=>bank.open);
                card.setConfig({entry_id:'fixture',title:'Renamed'});
                const redraw=[...card.shadowRoot.querySelectorAll('details')].map(bank=>bank.open);
                const fixture=card.fixture,raw=card.raw;
                card.setConfig({entry_id:'another'});
                card.fixture=fixture;card.raw=raw;card.render();
                const changed=[...card.shadowRoot.querySelectorAll('details')].map(bank=>bank.open);
                return {initial,redraw,changed};
            }""")
            assert result == {"initial": [False, False], "redraw": [False, True], "changed": [False, False]}
            batch = await page.evaluate("""async () => {
                const card=document.querySelector('fluval-schedule-colours');
                card.mode='professional';
                card.fixture={mode:'professional',channels:['Pink','Blue','Cold White','Pure White','Warm White']};
                card.raw.professional=[60,480,900,1200].map(minute=>({minute,
                    ...Object.fromEntries(card.fixture.channels.map((_,i)=>['channel_'+(i+1),50]))}));
                const count=card.fixture.channels.length,calls=[];
                card.edits={'professional:1':Array(count).fill(60),'professional:2':Array(count).fill(70)};
                card.timeEdits={'professional:1':1150,'professional:2':1100};card.selected=1;
                card._hass={callWS:async message=>{calls.push(structuredClone(message));return {
                    schedule:[60,1100,1150,1200].map((minute,index)=>({minute,
                        ...Object.fromEntries(card.fixture.channels.map((_,i)=>['channel_'+(i+1),[50,70,60,50][index]]))})),
                };}};
                await card.save();
                const success={calls,minutes:card.raw.professional.map(p=>p.minute),dirty:card.dirty,selected:card.selected};
                card.edits={'professional:1':Array(count).fill(20)};card.timeEdits={};
                card._hass={callWS:async ()=>{throw Error('Readback did not confirm');}};
                await card.save();
                const failure={dirty:card.dirty,message:card.message,level:card.raw.professional[1].channel_1};
                let finish;
                card._hass={callWS:()=>new Promise(resolve=>finish=resolve)};
                const pending=card.save();
                // Model entry selection while the old write acknowledgement is pending.
                card.entry='different-fixture';card.loadGeneration=(card.loadGeneration||0)+1;
                card.raw={professional:[{minute:30,channel_1:99}]};card.edits={};card.timeEdits={};
                card.message='New fixture';card.busy=false;
                finish(true);await pending;
                return {success,failure,stale:{message:card.message,minute:card.raw.professional[0].minute,
                    level:card.raw.professional[0].channel_1,busy:card.busy}};
            }""")
            assert len(batch["success"]["calls"]) == 1
            assert [edit["times"] for edit in batch["success"]["calls"][0]["changes"]] == [1150, 1100]
            assert batch["success"]["minutes"] == [60, 1100, 1150, 1200]
            assert batch["success"]["selected"] == 2
            assert batch["success"]["dirty"] is False
            assert batch["failure"] == {"dirty": True, "message": "Readback did not confirm", "level": 70}, batch
            assert batch["stale"] == {"message": "New fixture", "minute": 30, "level": 99, "busy": False}
            assert errors == []
            await page.close()
        await browser.close()
    print(
        "PASS: registration, picker, cached selection, 4/5-channel layouts, section state, Pro batch save, failed drafts and stale responses"
    )


asyncio.run(main())
