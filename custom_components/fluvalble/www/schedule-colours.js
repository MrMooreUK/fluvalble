const css = `
:host{display:block;color:var(--primary-text-color,#202124);font-family:var(--paper-font-body1_-_font-family,Roboto,Arial,sans-serif)}
*{box-sizing:border-box}ha-card{display:block;background:var(--ha-card-background,var(--card-background-color,#fff));border:1px solid var(--divider-color,#ddd);border-radius:var(--ha-card-border-radius,16px);overflow:hidden}
header{padding:22px 24px 16px}h2{font-size:20px;font-weight:500;margin:0 0 5px}.subtitle,.muted{color:var(--secondary-text-color,#667085);font-size:13px}.tabs{display:flex;border-bottom:1px solid var(--divider-color,#ddd);padding:0 20px;gap:24px}
button{font:inherit;cursor:pointer;border:0;background:none;color:inherit}button:disabled{opacity:.45;cursor:default}.tab{padding:13px 2px;font-size:14px;border-bottom:3px solid transparent}.tab.active{color:var(--primary-color,#03a9f4);border-color:var(--primary-color,#03a9f4)}
.body{padding:20px 24px}.bank{border:1px solid var(--divider-color,#ddd);border-radius:12px;margin-bottom:14px;overflow:hidden}.bank summary{cursor:pointer;list-style:none;padding:16px;display:flex;align-items:center;gap:12px}.bank summary::after{content:'⌄';margin-left:auto;color:var(--secondary-text-color)}.bank[open] summary::after{content:'⌃'}.bank-title{font-size:15px;font-weight:500}.bank-icon{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;background:var(--secondary-background-color,#f4f6f8);font-size:20px}.channels{padding:0 16px 10px}.channel{padding:10px 0}.row{display:flex;align-items:center;justify-content:space-between;font-size:14px;margin-bottom:10px}.value{font-variant-numeric:tabular-nums;color:var(--secondary-text-color)}input[type=range]{appearance:none;width:100%;height:6px;border-radius:4px;outline:none;background:linear-gradient(to right,var(--primary-color,#03a9f4) var(--fill),var(--divider-color,#ddd) var(--fill));cursor:pointer}input[type=range]::-webkit-slider-thumb{appearance:none;width:18px;height:18px;background:var(--primary-color,#03a9f4);border:3px solid var(--card-background-color,#fff);border-radius:50%;box-shadow:0 0 0 1px var(--primary-color,#03a9f4)}
.points{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 20px}.point{padding:10px 14px;border:1px solid var(--divider-color,#ddd);border-radius:10px;font-size:14px;font-variant-numeric:tabular-nums}.point.active{border-color:var(--primary-color,#03a9f4);color:var(--primary-color,#03a9f4);background:color-mix(in srgb,var(--primary-color,#03a9f4) 10%,transparent)}
.section-title{font-size:15px;font-weight:500;margin:0 0 16px}.note{font-size:13px;color:var(--secondary-text-color);line-height:1.5;margin:4px 0}.empty{padding:24px 0;line-height:1.6}.footer{border-top:1px solid var(--divider-color,#ddd);padding:16px 24px;display:flex;align-items:center;gap:10px}.status{font-size:12px;color:var(--secondary-text-color);flex:1}.status.dirty{color:var(--primary-color,#03a9f4)}.action{font-size:14px;font-weight:500;border-radius:20px;padding:10px 16px;color:var(--primary-color,#03a9f4)}.primary{background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff)}.message{font-size:13px;line-height:1.5;margin:0 0 16px;padding:12px;border-radius:8px;background:var(--secondary-background-color,#f4f6f8)}select{width:100%;padding:12px;font:inherit;background:var(--card-background-color,#fff);color:inherit;border:1px solid var(--divider-color,#ddd);border-radius:8px}
input[type=time]{font:inherit;color:inherit;background:var(--secondary-background-color,#f4f6f8);border:1px solid var(--divider-color,#ddd);border-radius:8px;padding:8px;margin-left:12px;max-width:150px}.row>label:has(input[type=time]){display:flex;align-items:center;justify-content:space-between;width:100%}
@media(max-width:380px){header,.body{padding:16px}.footer{padding:12px;gap:0}.action{padding:10px}.status{max-width:110px}}
`;
class FluvalScheduleColours extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this.mode='auto';this.edits={};this.timeEdits={};this.selected=0;}
  setConfig(config){const changed=this.entry!==config.entry_id;this.config=config;this.entry=config.entry_id;if(changed){this.started=false;this.busy=false;this.message='';this.fixture=null;this.raw=null;this.edits={};this.timeEdits={};this.loadGeneration=(this.loadGeneration||0)+1;}this.render();if(changed&&this._hass&&this.entry){this.started=true;this.load(false);}}
  set hass(value){this._hass=value;if(!this.started&&this.entry){this.started=true;this.load(false);}}
  static getConfigElement(){return document.createElement('fluval-schedule-colours-editor');}
  static getStubConfig(){return {type:'custom:fluval-schedule-colours'};}
  getCardSize(){return 7;}
  get dirty(){return Object.keys(this.edits).length>0;}
  async load(discard=true,refresh=false){
    if(discard&&this.dirty&&!window.confirm('Discard unsaved channel changes and reload from the light?'))return;
    const generation=this.loadGeneration=(this.loadGeneration||0)+1;
    this.busy=true;this.message='';this.render();
    try{
      const data=await this.request({type:'fluvalble/get_schedule',entry_id:this.entry,refresh},refresh?35000:10000);
      if(generation!==this.loadGeneration)return;
      if(refresh&&!data.refresh_ok)throw Error('Could not read the light. Check its connection and try Reload.');
      this.fixture=data.fixture;this.raw=data.colour_editor;this.edits={};this.timeEdits={};this.selected=0;
    }catch(error){if(generation!==this.loadGeneration)return;this.message=error.message||String(error);}
    this.busy=false;this.render();
  }
  request(message,timeout){
    let timer;return Promise.race([this._hass.callWS(message),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('The fixture request timed out. Try Reload when the light is available.')),timeout);})]).finally(()=>clearTimeout(timer));
  }
  banks(){if(!this.raw?.[this.mode])return [];return this.mode==='auto'?['day','night']:this.raw.professional.map((_,i)=>i);}
  key(target){return this.mode+':'+target;}
  levels(target){
    const draft=this.edits[this.key(target)];if(draft)return draft;
    if(this.mode==='auto')return this.raw.auto[target+'_levels'];
    return this.fixture.channels.map((_,i)=>this.raw.professional[target]['channel_'+(i+1)]);
  }
  async save(){
    if([...this.shadowRoot.querySelectorAll('input[type=time]')].some(input=>!input.reportValidity()))return;
    this.busy=true;this.message='';this.render();
    try{
      for(const [key,levels] of Object.entries({...this.edits})){
        const [mode,targetValue]=key.split(':');const target=mode==='auto'?targetValue:Number(targetValue);
        const times=this.timeEdits[key];
        await this._hass.callWS({type:'fluvalble/save_schedule_colours',entry_id:this.entry,schedule:mode,target,levels,baseline:this.raw[mode],...(times===undefined?{}:{times})});
        // Backend confirms this one write. Advance the baseline for the next
        // bank without discarding any still-unsaved drafts.
        if(mode==='auto')this.raw.auto[target+'_levels']=[...levels];
        else levels.forEach((v,i)=>this.raw.professional[target]['channel_'+(i+1)]=v);
        if(times!==undefined){if(mode==='auto')Object.assign(this.raw.auto,structuredClone(times));else this.raw.professional[target].minute=times;}
        delete this.edits[key];
        delete this.timeEdits[key];
      }
      this.message='Changes saved to the light.';
    }catch(error){this.message=error.message||String(error);}
    this.busy=false;this.render();
  }
  render(){
    this.shadowRoot.innerHTML='<style>'+css+'</style><ha-card><header><h2></h2><div class="subtitle">Hardware schedule · times and colours</div></header><nav class="tabs" aria-label="Schedule mode"></nav><div class="body"></div><footer class="footer"></footer></ha-card>';
    this.shadowRoot.querySelector('h2').textContent=this.config?.title||this.fixture?.name||'Fluval schedule';
    const body=this.shadowRoot.querySelector('.body');
    const button=(parent,text,handler,className,disabled=false)=>{
      const el=document.createElement('button');el.type='button';el.textContent=text;el.className=className;el.disabled=this.busy||disabled;el.onclick=handler;parent.append(el);return el;
    };
    const tabs=this.shadowRoot.querySelector('.tabs');
    for(const [mode,label] of [['auto','Automatic'],['professional','Professional']]){
      const tab=button(tabs,label,()=>{
        if(this.dirty&&!window.confirm('Discard unsaved channel changes and switch schedule view?'))return;
        this.edits={};this.timeEdits={};this.mode=mode;this.selected=0;this.message='';this.render();
      },'tab'+(this.mode===mode?' active':''));
      tab.setAttribute('aria-pressed',String(this.mode===mode));
    }
    if(this.message){const msg=document.createElement('div');msg.className='message';msg.setAttribute('role','status');msg.textContent=this.message;body.append(msg);}
    if(!this.entry){const note=document.createElement('div');note.className='empty muted';note.textContent='Choose a Fluval light in this card’s visual configuration to get started.';body.append(note);}
    else if(!this.raw?.[this.mode]){
      const note=document.createElement('div');note.className='empty muted';
      note.textContent=this.busy?'Loading saved schedule…':'No saved '+(this.mode==='auto'?'Automatic':'Professional')+' schedule is available in Home Assistant. Select the matching mode on the light, then Reload to read it over Bluetooth.';
      body.append(note);
    }else{
      const format=minute=>String(Math.floor(minute/60)).padStart(2,'0')+':'+String(minute%60).padStart(2,'0');
      const minute=value=>{const [h,m]=value.split(':').map(Number);return h*60+m;};
      const field=(parent,labelText,value,onchange)=>{
        const row=document.createElement('div');row.className='row';
        const label=document.createElement('label');label.textContent=labelText;
        const input=document.createElement('input');input.type='time';input.step=60;input.value=format(value);input.disabled=this.busy;input.required=true;input.setAttribute('aria-label',labelText);
        input.onchange=()=>{if(input.value&&input.checkValidity())onchange(minute(input.value));};
        label.append(input);row.append(label);parent.append(row);return input;
      };
      const autoTiming=()=>{
        const timing=structuredClone(this.timeEdits['auto:day']||this.raw.auto);
        return {sunrise:timing.sunrise,sunset:timing.sunset,sleep:timing.sleep};
      };
      const changeAuto=(update)=>{
        const times=autoTiming();update(times);this.timeEdits['auto:day']=times;
        this.edits['auto:day']=[...this.levels('day')];this.updateFooter();
      };
      const channels=(parent,target)=>{
        const panel=document.createElement('div');panel.className='channels';parent.append(panel);
        this.fixture.channels.forEach((name,i)=>{
          const field=document.createElement('div');field.className='channel';
          const row=document.createElement('div');row.className='row';
          const label=document.createElement('label');const id='channel-'+target+'-'+i;label.htmlFor=id;label.textContent=name;
          const value=document.createElement('span');value.className='value';value.textContent=this.levels(target)[i]+'%';row.append(label,value);
          const input=document.createElement('input');input.type='range';input.id=id;input.min=0;input.max=100;input.step=1;input.value=this.levels(target)[i];input.disabled=this.busy;input.style.setProperty('--fill',input.value+'%');
          input.oninput=()=>{
            const levels=[...this.levels(target)];levels[i]=Number(input.value);this.edits[this.key(target)]=levels;
            value.textContent=input.value+'%';input.style.setProperty('--fill',input.value+'%');this.updateFooter();
          };
          field.append(row,input);panel.append(field);
        });
      };
      if(this.mode==='auto'){
        for(const [target,title,icon] of [['day','Day','☀'],['night','Night','☾']]){
          const bank=document.createElement('details');bank.className='bank';bank.open=target==='day';
          const summary=document.createElement('summary');const glyph=document.createElement('span');glyph.className='bank-icon';glyph.textContent=icon;
          const name=document.createElement('span');name.className='bank-title';name.textContent=title;summary.append(glyph,name);bank.append(summary);channels(bank,target);body.append(bank);
          const timing=document.createElement('div');timing.className='channels';bank.insertBefore(timing,bank.querySelector('.channels'));
          const times=autoTiming();const nameTime=target==='day'?'sunrise':'sunset';const window=times[nameTime];const anchor=window.hour*60+window.minute;
          const start=target==='day'?anchor:(anchor-window.ramp+1440)%1440;
          const end=target==='day'?(anchor+window.ramp)%1440:anchor;
          const updateWindow=(which,value)=>changeAuto(draft=>{
            const current=draft[nameTime];const anchor=current.hour*60+current.minute;
            let a=target==='day'?anchor:(anchor-current.ramp+1440)%1440;
            let b=target==='day'?(anchor+current.ramp)%1440:anchor;
            if(which==='start')a=value;else b=value;
            const stored=target==='day'?a:b;draft[nameTime]={hour:Math.floor(stored/60),minute:stored%60,ramp:(b-a+1440)%1440};
          });
          field(timing,target==='day'?'Sunrise starts':'Sunset starts',start,value=>updateWindow('start',value));
          field(timing,target==='day'?'Sunrise ends':'Sunset ends',end,value=>updateWindow('end',value));
          if(target==='night'){
            if(times.sleep)field(timing,'Night lighting off',times.sleep.hour*60+times.sleep.minute,value=>changeAuto(draft=>{draft.sleep={hour:Math.floor(value/60),minute:value%60};}));
          }
        }
      }else{
        const title=document.createElement('div');title.className='section-title';title.textContent='Scheduled timepoints';body.append(title);
        const points=document.createElement('div');points.className='points';points.setAttribute('aria-label','Timepoints');body.append(points);
        this.raw.professional.forEach((point,i)=>{
          const time=format(this.timeEdits[this.key(i)]??point.minute);
          const b=button(points,time,()=>{this.selected=i;this.render();},'point'+(i===this.selected?' active':''));
          b.setAttribute('aria-pressed',String(i===this.selected));
        });
        field(body,'Timepoint time',this.timeEdits[this.key(this.selected)]??this.raw.professional[this.selected].minute,value=>{
          this.timeEdits[this.key(this.selected)]=value;this.edits[this.key(this.selected)]=[...this.levels(this.selected)];this.render();
        });
        channels(body,this.selected);
      }
      const note=document.createElement('p');note.className='note';note.textContent='Changes stay here until saved. Times use the light’s local clock. Keep timepoints in order; sunrise and sunset can last up to four hours.';body.append(note);
    }
    this.updateFooter();
  }
  updateFooter(){
    const footer=this.shadowRoot.querySelector('footer');footer.innerHTML='';
    const status=document.createElement('span');status.className='status'+(this.dirty?' dirty':'');
    status.textContent=this.busy?'Working…':this.dirty?'Unsaved changes':this.raw?'Read from fixture':'Not loaded';footer.append(status);
    for(const [text,action,primary,disabled] of [['Reload',()=>this.load(true,true),false,!this.entry],['Save changes',()=>this.save(),true,!this.dirty]]){
      const b=document.createElement('button');b.type='button';b.textContent=text;b.className='action'+(primary?' primary':'');b.disabled=this.busy||disabled;b.onclick=action;footer.append(b);
    }
  }
}
class FluvalScheduleColoursEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});}
  setConfig(config){this.config=config;this.render();}
  set hass(value){this._hass=value;if(!this.started){this.started=true;FluvalScheduleColours.prototype.request.call(this,{type:'fluvalble/colour_editor_devices'},10000).then(devices=>{this.devices=devices;this.render();}).catch(error=>{this.error=error.message;this.render();});}}
  render(){
    this.shadowRoot.innerHTML='<style>'+css+'</style>';
    if(!this.devices){this.shadowRoot.append(document.createTextNode(this.error||'Loading Fluval lights…'));if(this.error){const retry=document.createElement('button');retry.textContent='Retry';retry.onclick=()=>{this.started=false;this.error='';this.hass=this._hass;};this.shadowRoot.append(retry);}return;}
    const label=document.createElement('label');label.textContent='Fluval light';const select=document.createElement('select');select.setAttribute('aria-label','Fluval light');
    select.add(new Option('Select a light',''));this.devices.forEach(d=>select.add(new Option(d.name,d.id)));select.value=this.config?.entry_id||'';
    select.onchange=()=>{this.config={...this.config,entry_id:select.value};this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this.config},bubbles:true,composed:true}));};
    label.append(select);this.shadowRoot.append(label);
  }
}
for(const [name,component] of [['fluval-schedule-colours-editor',FluvalScheduleColoursEditor],['fluval-schedule-colours',FluvalScheduleColours]])if(!customElements.get(name))customElements.define(name,component);
window.customCards=window.customCards||[];
if(!window.customCards.some(x=>x.type==='fluval-schedule-colours'))window.customCards.push({type:'fluval-schedule-colours',name:'Fluval schedule colours',description:'Edit times and colours in a saved hardware schedule.',preview:false});
