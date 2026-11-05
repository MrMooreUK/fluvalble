class FluvalScheduleColours extends HTMLElement {
  setConfig(config) { this.config = config; this.attachShadowOnce(); }
  attachShadowOnce() { if (!this.shadowRoot) this.attachShadow({mode:'open'}); }
  set hass(hass) { this._hass = hass; if (!this.started) { this.started = true; this.loadDevices(); } }
  async loadDevices() {
    try { this.devices = await this._hass.callWS({type:'fluvalble/colour_editor_devices'}); this.render(); }
    catch (error) { this.message = error.message; this.render(); }
  }
  async load() {
    this.busy = true; this.render();
    try {
      const response = await this._hass.callWS({type:'fluvalble/get_schedule', entry_id:this.entry, refresh:true});
      if (!response.refresh_ok) throw new Error('Unable to read the fixture. Try again.');
      this.fixture = response.fixture;
      // Use raw fixture readback for optimistic concurrency, supplied by backend.
      this.raw = response.colour_editor;
      this.target = this.mode === 'auto' ? 'day' : 0;
      this.selectTarget(); this.message = '';
    } catch (error) { this.message = error.message; }
    this.busy = false; this.render();
  }
  selectTarget() {
    const schedule = this.raw?.[this.mode];
    this.levels = !schedule ? null : this.mode === 'auto'
      ? [...schedule[this.target + '_levels']]
      : this.fixture.channels.map((_, i) => schedule[this.target]['channel_' + (i+1)]);
  }
  async save() {
    this.busy = true; this.render();
    try {
      await this._hass.callWS({type:'fluvalble/save_schedule_colours',entry_id:this.entry,
        schedule:this.mode,target:this.target,levels:this.levels,baseline:this.raw[this.mode]});
      await this.load(); this.message = 'Saved to light.';
    } catch (error) { this.message = error.message; }
    this.busy = false; this.render();
  }
  render() {
    this.attachShadowOnce();
    this.shadowRoot.innerHTML = `<style>:host{display:block}ha-card{padding:20px}h2{font-size:20px;margin:0 0 16px}label{display:block;margin:12px 0}select,button{font:inherit;padding:8px;border-radius:8px;background:var(--card-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color)}select{width:100%}input{width:100%;accent-color:var(--primary-color)}button{margin:12px 8px 0 0;cursor:pointer}p{color:var(--secondary-text-color);font-size:14px}.message{white-space:pre-wrap}</style><ha-card><h2>Schedule colours</h2><div id="content"></div></ha-card>`;
    const container = this.shadowRoot.querySelector('#content');
    const select = (label, items, value, change) => {
      const field = document.createElement('label'); field.textContent = label;
      const input = document.createElement('select');
      input.setAttribute('aria-label',label);
      for (const [id, name] of items) { const option = new Option(name, id); input.add(option); }
      input.value = String(value ?? ''); input.disabled = !!this.busy;
      input.onchange = () => change(input.value); field.append(input); container.append(field);
    };
    select('Light', [['','Select a light'],...(this.devices || []).map(x=>[x.id,x.name])], this.entry,
      value=>{this.entry=value;this.raw=null;this.levels=null;this.render();});
    select('Schedule', [['auto','Automatic'],['professional','Professional']], this.mode || 'auto',
      value=>{this.mode=value;this.raw=null;this.levels=null;this.render();});
    this.mode ||= 'auto';
    const button = (label, action, disabled=false) => {const el=document.createElement('button');el.textContent=label;el.disabled=disabled||this.busy;el.onclick=action;container.append(el);};
    button('Read from light',()=>this.load(),!this.entry);
    const schedule=this.raw?.[this.mode];
    if (schedule) {
      const targets=this.mode==='auto' ? [['day','Day'],['night','Night']] : schedule.map((x,i)=>[i,`${String(Math.floor(x.minute/60)).padStart(2,'0')}:${String(x.minute%60).padStart(2,'0')}`]);
      select('Colour bank', targets, this.target, value=>{this.target=this.mode==='auto'?value:Number(value);this.selectTarget();this.render();});
      (this.levels || []).forEach((level,i)=>{
        const label=document.createElement('label');const text=document.createElement('span');
        const update=()=>text.textContent=`${this.fixture.channels[i]}: ${this.levels[i]}%`;update();
        const slider=document.createElement('input');slider.type='range';slider.min=0;slider.max=100;slider.step=1;slider.value=level;slider.disabled=!!this.busy;
        slider.oninput=()=>{this.levels[i]=Number(slider.value);update();};label.append(text,slider);container.append(label);
      });
      button('Save to light',()=>this.save(),!this.levels);
    }
    const help=document.createElement('p');help.textContent='Select the saved schedule mode on your light, then read it here. Only channel levels are edited; existing times stay unchanged.';container.append(help);
    if(this.message){const msg=document.createElement('p');msg.className='message';msg.textContent=this.message;container.append(msg);}
  }
  getCardSize(){return 7;}
  static getConfigElement(){return document.createElement('fluval-schedule-colours-editor');}
  static getStubConfig(){return {type:'custom:fluval-schedule-colours'};}
}
class FluvalScheduleColoursEditor extends HTMLElement {
  setConfig(config){this.textContent='Choose the light and saved schedule directly on the card. No YAML configuration is required.';}
  set hass(hass){}
}
if(!customElements.get('fluval-schedule-colours-editor'))customElements.define('fluval-schedule-colours-editor',FluvalScheduleColoursEditor);
if(!customElements.get('fluval-schedule-colours'))customElements.define('fluval-schedule-colours',FluvalScheduleColours);
window.customCards=window.customCards||[];
if(!window.customCards.some(x=>x.type==='fluval-schedule-colours'))window.customCards.push({type:'fluval-schedule-colours',name:'Fluval schedule colours',description:'Edit channel levels in a saved hardware schedule.',preview:false});
