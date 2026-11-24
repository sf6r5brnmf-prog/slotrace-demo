'use strict';
// Gran Premio: tablero con agujas, configuración y sonidos. Los datos viven en el servidor (Mac).
const $=id=>document.getElementById(id);
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined&&text!==null)e.textContent=text;return e;}
const COLORS=['#edf2f7','#ffe23b','#ff4d50','#3d96ff','#50dc92','#ff963d'],TEAM=['Blanco','Amarillo','Rojo','Azul','Verde','Naranja'];
let state=null,roster=null,lastVersion=null,screenName='',busy=false,picked=new Set(),carPick={},pickInit=false,configDraft=null;
function toast(t){const b=$('toast');b.textContent=t;b.style.display='block';clearTimeout(toast.t);toast.t=setTimeout(()=>b.style.display='none',3800);}
const fmt=s=>s==null?'—':s.toFixed(2)+' s';
// Color del equipo: en el Gran Premio es el lugar del registro (0–5); en el torneo, el COCHE que trae en esta manga.
function teamIdx(slot,car){const g=state?.gp;if(g&&g.mode==='torneo'){const c=car||(g.pilots.find(x=>x.slot===slot)||{}).car||1;return (c-1)%6;}return slot;}
function clock(ms){if(ms==null)return'--:--';const t=Math.ceil(ms/1000),m=Math.floor(t/60),s=t%60;return m+':'+String(s).padStart(2,'0');}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'No se pudo.');return d;}

/* ---------------- Sonido ---------------- */
const SFX=['motor_pasa','frenazo','rechinido','aplausos','semaforo','abucheo','bandera_final'];
const sfx={};SFX.forEach(n=>{const a=new Audio('sfx/'+n+'.mp3');a.preload='auto';sfx[n]=a;});
let soundDevice=false;try{soundDevice=localStorage.getItem('gp-sound')==='on';}catch(e){}
let soundUnlocked=false;
function volume(){const c=state?.gp?.config||state?.config;return c?(c.sound_enabled?c.sound_volume/100:0):0.8;}
function play(name,offset=0){
  if(!soundDevice||!soundUnlocked)return;const v=volume();if(!v)return;
  const base=sfx[name];if(!base)return;const a=base.paused||base.currentTime===0?base:base.cloneNode();
  a.volume=Math.min(1,v);try{a.currentTime=Math.max(0,offset);}catch(e){}a.play().catch(()=>{});
}
window.PELU_SFX={play,names:SFX}; // listo para la pluma (frenazo) y el derrape (rechinido)
function syncSoundButton(){const b=$('soundToggle');b.textContent=soundDevice&&soundUnlocked?'🔊 Sonido en este equipo':'🔇 Activar sonido aquí';b.classList.toggle('on',soundDevice&&soundUnlocked);}
$('soundToggle').addEventListener('click',()=>{
  if(soundDevice&&soundUnlocked){soundDevice=false;}else{soundDevice=true;soundUnlocked=true;
    // Desbloquear audio con el clic (Safari/Chrome lo exigen).
    Object.values(sfx).forEach(a=>{a.muted=true;a.play().then(()=>{a.pause();a.currentTime=0;a.muted=false;}).catch(()=>{a.muted=false;});});}
  try{localStorage.setItem('gp-sound',soundDevice?'on':'off');}catch(e){}syncSoundButton();
});
document.addEventListener('pointerdown',()=>{if(soundDevice&&!soundUnlocked){soundUnlocked=true;Object.values(sfx).forEach(a=>{a.muted=true;a.play().then(()=>{a.pause();a.currentTime=0;a.muted=false;}).catch(()=>{a.muted=false;});});syncSoundButton();}},{once:false});
let lastEvent=null,lastLapSound=0;
function handleEvents(g){
  const evs=g?.events||[];const max=evs.length?evs[evs.length-1].id:0;
  if(lastEvent===null){lastEvent=max;return;}
  const now=state.server_time;
  evs.filter(e=>e.id>lastEvent).forEach(e=>{
    if(now-e.at>4)return;
    tick(e);
    if(e.type==='countdown'){const ms=g.run?.countdown_ms??3000;const lead=PeluLights.soundLead(ms);if(lead>=0)setTimeout(()=>play('semaforo'),lead*1000);else play('semaforo',-lead);}
    else if(e.type==='lap'){const t=performance.now();if(t-lastLapSound>350){play('motor_pasa');lastLapSound=t;}}
    else if(e.type==='best')play('aplausos');
    else if(e.type==='false_start')play('abucheo');
    else if(e.type==='winner'||e.type==='finish')play('bandera_final');
    else if(e.type==='podium')play('aplausos');
    else if(e.type==='red_flag'||e.type==='yellow_flag')play('frenazo');
    else if(e.type==='dsq'){play('abucheo');toast('⛔ '+(e.name||'')+' DESCALIFICADO');}
    else if(e.type==='eliminado')play('abucheo');
  });
  lastEvent=Math.max(lastEvent,max);
}
function tick(e){
  const map={lap:'⏱',best:'★',false_start:'⚠',suspicious:'⚠',winner:'🏁',finish:'🏁',go:'🟢',countdown:'🚦',podium:'🏆',last_lap:'⏳',quali_done:'✔',final_done:'🏁',red_flag:'🚩',yellow_flag:'🟨',dsq:'⛔',pit_entry:'🔧',pit_exit:'🔧',eliminado:'❌'};
  if(e.type==='lap')return;
  const t=$('ticker'),row=el('div','tick tick-'+e.type,(map[e.type]||'•')+' '+(e.name?e.name+' · ':'')+e.text);t.prepend(row);while(t.children.length>4)t.lastChild.remove();
}

/* ---------------- Agujas (compartidas en gauges.js) ---------------- */
const {Gauge}=window.PeluGauges;
const gauges=window.PeluGauges.watch(new Map());

/* ---------------- Configuración ---------------- */
const SECTIONS=[
 ['Qualy (uno por uno)',[['quali_enabled','Hacer qualy','bool'],['quali_minutes','Minutos por piloto','num',.25],['quali_order','Orden de salida en qualy','sel',[['registro','Como están registrados'],['azar','Al azar']]],['quali_finish_lap','Al acabarse el tiempo, terminar la vuelta en curso','bool'],['quali_any_car','Contar cualquier coche (solo hay uno en pista)','bool'],['quali_source','Quién cuenta las vueltas en qualy','sel',[['scx','Tarjeta SCX'],['ir','Sensor IR de la ESP32']]]]],
 ['Eliminatorias (todos juntos)',[['heats_rounds','Número de rondas (0 = sin eliminatorias)','num',1],['heats_minutes','Minutos por ronda','num',.25]]],
 ['Final',[['finalists','Cuántos pasan a la final','num',1],['final_laps','Vueltas de la final','num',1],['final_wait_s','Segundos de espera para que crucen los demás','num',1]]],
 ['Salida',[['lights_enabled','Semáforo con cuenta regresiva','bool'],['lights_seconds','Segundos de semáforo','num',1],['false_start_penalty_laps','Castigo por salida en falso (vueltas)','num',1],['false_start_throttle','Gatillo que cuenta como salida en falso (0 = no revisar gatillo)','num',1],['first_pass_is_start','El primer paso por meta es la salida (no cuenta vuelta)','bool'],['min_lap_s','Vuelta mínima válida (s) · más cortas = ⚠ sospechosas, no cuentan (la misma en Práctica y Carrera)','num',.1]]],
 ['Tablero',[['fuel_enabled','Mostrar vida de llanta','bool'],['tire_name','Llanta (nombre o tipo que sale en las tarjetas)','text'],['tire_red_pct','Zona roja de la llanta (%) · abajo de esto: CAMBIA LLANTAS / ENTRA A PITS','num',1],['track_length_m','Largo de la pista (m)','num',.1],['scale','Escala (1:N)','num',1],['speed_max_kmh','Velocímetro hasta (km/h)','num',10],['fuel_layout','Acomodo de bytes de la vida de llanta (D6 de la Pit Box)','sel',[['nibbles','D0–D2 por nibbles (slotbaer)'],['nibbles_bajo','D0–D2 nibble bajo primero'],['bytes','D0–D5 un byte por coche']]]]],
 ['Sonido',[['sound_enabled','Sonidos encendidos','bool'],['sound_volume','Volumen (0–100)','num',5]]],
 ['Bandera amarilla del piloto (también en Práctica y Carrera)',[['pilot_flag_enabled','Un piloto puede sacar bandera amarilla con clics seguidos en su botón de cambio de carril','bool'],['pilot_flag_clicks','Clics seguidos para sacarla','num',1],['pilot_flag_window_s','En cuántos segundos (todos los clics)','num',.1],['pilot_flag_max','Máximo de banderas por piloto en cada carrera (Práctica, Carrera, cada qualy, cada ronda y la final)','num',1],['pilot_flag_dsq','Descalificar al que pida una más del máximo','bool']]],
 ['Torneo por mangas (7 o más pilotos)',[['torneo_cars','Coches por manga (2 a 6 · con 6 necesitas las dos centralitas)','num',1],['torneo_minutes','Minutos por manga (se suman vueltas)','num',.25],['torneo_agrupar','Cómo se arman las mangas','sel',[['nivel','Agrupar por nivel: expertos con expertos, novatos con novatos (recomendado)'],['mezcla','Mezclar niveles en cada manga (serpentina)']]],['torneo_final_laps','Vueltas de la final (cuando es una sola carrera de 6)','num',1]]],
 ['Tiempo en pits · cambio de llantas (también en Práctica y Carrera)',[['pit_exit_source','Cómo se marca la salida de pits (la entrada la dice la Pit Box al cruzar por el carril)','sel',[['estimado','Estimada: cuando la llanta deja de subir en la Pit Box y acelera'],['auto','Automática: sensor IR de salida si lo hay; si no, estimada'],['ir','Solo el sensor IR de la salida de pits (cuando lo pongas)']]],['pit_exit_throttle','Gatillo que cuenta como que ya salió (0–15)','num',1],['pit_exit_low_throttle','Gatillo que cuenta como detenido en pits (0–15)','num',1],['pit_exit_fuel_idle_s','Segundos sin que suba la vida de llanta para dar por terminado el cambio','num',.1],['pit_exit_throttle_hold_s','Segundos con el gatillo arriba para confirmar la salida','num',.05],['pit_exit_timeout_s','Tope de tiempo en pits (s): si no sale, se cierra sola','num',1]]],
];
function renderConfig(cfg){
  const f=$('configForm');f.replaceChildren();
  SECTIONS.forEach(([title,fields])=>{const box=el('fieldset','cfg-box');box.append(el('legend','',title));
    fields.forEach(([k,label,type,extra])=>{const row=el('label','cfg-row'+(type==='bool'?' cfg-bool':''));let input;
      if(type==='bool'){input=el('input');input.type='checkbox';input.checked=!!cfg[k];row.append(input,el('span','',label));}
      else if(type==='text'){input=el('input');input.type='text';input.maxLength=24;input.value=cfg[k]??'';input.placeholder='Media';row.append(el('span','',label),input);}
      else if(type==='sel'){input=el('select');extra.forEach(([v,t])=>{const o=el('option','',t);o.value=v;input.append(o);});input.value=cfg[k];row.append(el('span','',label),input);}
      else{input=el('input');input.type='number';input.step=String(extra);input.value=cfg[k];input.inputMode='decimal';row.append(el('span','',label),input);}
      input.dataset.key=k;input.dataset.type=type;box.append(row);});
    f.append(box);});
  // Handicap · ajuste de tiempo por vuelta: se guarda en data/vueltas.json (el mismo de Práctica y Carrera).
  const h=hcCfg(),box=el('fieldset','cfg-box hc-cfg');box.append(el('legend','','Handicap · ajuste de tiempo por vuelta (también en Práctica, Carrera y Mi coche)'));
  const en=el('label','cfg-row cfg-bool'),cb=el('input');cb.type='checkbox';cb.checked=!!h.enabled;cb.id='hcEnabled';en.append(cb,el('span','','Usar handicap (se suma o resta a cada vuelta según la clase del coche)'));box.append(en);
  PeluHandicap.CLASES.forEach(([k,n])=>{const row=el('div','cfg-row hc-row'),i=el('input');i.id='hcCfg_'+k;i.dataset.hc=k;const lb=el('label','',PeluHandicap.ICON[k]+' '+n+' · segundos por vuelta');lb.htmlFor=i.id;row.append(lb,i);box.append(row);PeluHandicap.upgrade(i).setValue(h.seg[k]??0);});
  box.append(el('p','muted','Toca + / − para elegir si SUMA o RESTA segundos, y escribe el número (0 a 10). Si resta, una vuelta ajustada nunca baja de 1 s.'));
  // Por nivel del piloto + nivel automático por tiempo: se guarda al momento (data/vueltas.json), igual que en el menú.
  const nb=el('div','hc-nivel');nb.id='gpHcNivel';box.append(nb);
  PeluHandicap.nivelSettings(nb,h,async part=>{try{await saveHandicap(part);$('configMsg').textContent='Guardado.';}catch(e){$('configMsg').textContent=e.message;}},m=>{$('configMsg').textContent=m;});
  box.append(el('p','muted','Los de fábrica (Con imán +0.5 s, Modificado +1 s, Sin imán 0 s) son ejemplos: cámbialos. La clase de cada coche se elige en «Nuevo Gran Premio», junto al número de coche. Queda fijo al arrancar la primera parte del Gran Premio.'));
  f.append(box);
}
function hcCfg(){return state?.handicap_cfg||{enabled:true,seg:{sin_iman:0,con_iman:0.5,modificado:1},clases:{},nivel_on:true,seg_nivel:{novato:-0.3,intermedio:0,experto:0.3},nivel_auto:'sugerir'};}
function readHandicap(){const seg={};let bad=false;$('configForm').querySelectorAll('[data-hc]').forEach(i=>{const v=i.hcField?i.hcField.getValue():Number(String(i.value).replace(',','.'));if(!Number.isFinite(v)||v<-10||v>10)bad=true;seg[i.dataset.hc]=Math.round(v*100)/100;});
  if(bad)throw Error('El ajuste por vuelta debe ser un número de 0 a 10 segundos (el botón + / − elige si suma o resta).');return {enabled:$('hcEnabled').checked,seg};}
async function saveHandicap(part){const d=await post('/api/vueltas-config',{handicap:part});if(state)state.handicap_cfg=d.handicap;return d.handicap;}
function readConfig(){const out={};$('configForm').querySelectorAll('[data-key]').forEach(i=>{const k=i.dataset.key;out[k]=i.dataset.type==='bool'?i.checked:i.dataset.type==='sel'||i.dataset.type==='text'?i.value:Number(i.value);});
  ['torneo_cars','torneo_final_laps','heats_rounds','finalists','final_laps','final_wait_s','lights_seconds','false_start_penalty_laps','false_start_throttle','scale','speed_max_kmh','fuel_red_pct','tire_red_pct','sound_volume','pilot_flag_clicks','pilot_flag_max'].forEach(k=>{if(k in out)out[k]=Math.round(out[k]);});out.preset='personal';return out;}
$('saveConfig').addEventListener('click',async()=>{try{const hc=readHandicap();const d=await post('/api/gp/config',{config:readConfig()});await saveHandicap(hc);state.config=d.config;renderConfig(d.config);renderSetup(true);$('configMsg').textContent='Guardado ✓';toast('Configuración guardada');}catch(e){$('configMsg').textContent=e.message;}});
$('resetConfig').addEventListener('click',async()=>{if(!confirm('¿Regresar todo a los valores de fábrica? (se conserva la asignación de coches)'))return;try{const d=await post('/api/gp/config',{reset_defaults:true});await saveHandicap({enabled:true,seg:{sin_iman:0,con_iman:0.5,modificado:1}});state.config=d.config;renderConfig(d.config);renderSetup(true);$('configMsg').textContent='Valores de fábrica ✓';}catch(e){$('configMsg').textContent=e.message;}});
SFX.forEach(n=>{const b=el('button','',n.replace('_',' '));b.type='button';b.addEventListener('click',()=>{if(!soundDevice||!soundUnlocked){$('soundToggle').click();}play(n);});$('sfxTest').append(b);});
// 💥 Explosión al sensor (sintetizada en explosion.js): mismo interruptor y volumen que los demás sonidos.
if(window.PeluExplosion){PeluExplosion.config({canPlay:()=>soundDevice&&soundUnlocked,volume});
  const xb=el('button','','💥 explosión');xb.type='button';xb.addEventListener('click',()=>{if(!soundDevice||!soundUnlocked){$('soundToggle').click();}PeluExplosion.test();});$('sfxTest').append(xb);}
document.querySelectorAll('.tab[data-tab]').forEach(t=>t.addEventListener('click',()=>{document.querySelectorAll('.tab[data-tab]').forEach(x=>x.classList.toggle('active',x===t));['newTab','configTab','torneoTab'].forEach(id=>$(id).hidden=id!==t.dataset.tab);if(t.dataset.tab==='configTab')renderConfig(state.config);if(t.dataset.tab==='torneoTab'&&window.PeluTorneo)PeluTorneo.renderSetup(true);}));

/* ---------------- Preparación ---------------- */
function formatText(c){
  const parts=[];if(c.quali_enabled)parts.push('Qualy '+c.quali_minutes+' min c/u (mejor vuelta)');
  if(c.heats_rounds)parts.push(c.heats_rounds+' ronda'+(c.heats_rounds>1?'s':'')+' de '+c.heats_minutes+' min (se suman vueltas)');
  parts.push('Final: pasan '+c.finalists+', gana el primero en '+c.final_laps+' vueltas');return parts.join(' → ');
}
function renderSetup(force){
  const c=state.config,pb=$('presetButtons');
  if(force||!pb.children.length){pb.replaceChildren();Object.entries(state.presets).forEach(([k,p])=>{const b=el('button','preset'+(c.preset===k?' active':''));b.type='button';b.append(el('strong','',p.label),el('small','',(p.quali_minutes+' min qualy · '+p.heats_rounds+'×'+p.heats_minutes+' min · final '+p.final_laps+' v')));b.addEventListener('click',async()=>{try{const d=await post('/api/gp/config',{apply_preset:k});state.config=d.config;renderSetup(true);toast(p.label+' listo');}catch(e){toast(e.message);}});pb.append(b);});
    const b=el('button','preset'+(c.preset==='personal'?' active':''));b.type='button';b.append(el('strong','','Personalizado'),el('small','','Cambia todo en Configuración'));b.addEventListener('click',()=>document.querySelector('.tab[data-tab="configTab"]').click());pb.append(b);}
  const hcs=hcCfg();$('formatSummary').textContent=formatText(c)+(hcs.enabled?' · Handicap: Sin imán '+PeluHandicap.segTxt(hcs.seg.sin_iman)+', Con imán '+PeluHandicap.segTxt(hcs.seg.con_iman)+', Modificado '+PeluHandicap.segTxt(hcs.seg.modificado):' · Handicap apagado');
  if(!roster)return;
  if(!pickInit){roster.slots.forEach((p,i)=>{if(p)picked.add(i);carPick[i]=c.cars?.[String(i)]||i+1;});pickInit=true;}
  const box=$('pilotPick');
  const hsig=String(roster.version)+'|'+JSON.stringify(hcCfg())+'|'+((PeluGarage.data||{}).version)+'|'+JSON.stringify(carPick);
  if((force||box.dataset.v!==hsig)&&!box.contains(document.activeElement)){box.dataset.v=hsig;box.replaceChildren();
    roster.slots.forEach((p,i)=>{if(!p)return;const card=el('label','pick'+(picked.has(i)?' on':''));card.style.setProperty('--team',COLORS[i]);
      const cb=el('input');cb.type='checkbox';cb.checked=picked.has(i);cb.addEventListener('change',()=>{cb.checked?picked.add(i):picked.delete(i);card.classList.toggle('on',cb.checked);});
      const img=el('img');img.src=p.avatar;img.alt='';const name=el('span','pick-name');name.append(el('strong','',p.name),el('small','','Equipo '+TEAM[i]));
      const sel=el('select','pick-mando');sel.setAttribute('aria-label','Mando de '+p.name);for(let k=1;k<=6;k++){const o=el('option','','🎮 Mando '+k);o.value=k;sel.append(o);}sel.value=carPick[i];sel.addEventListener('click',e=>e.preventDefault&&e.stopPropagation());
      // Handicap: clase del coche elegido (se guarda al momento en la Mac).
      const hsel=el('select','hc-class');hsel.setAttribute('aria-label','Clase del coche de '+p.name);const hh=hcCfg();
      PeluHandicap.CLASES.forEach(([k,n])=>{const o=el('option','',PeluHandicap.ICON[k]+' '+n+(hh.enabled?' · '+PeluHandicap.segTxt(hh.seg[k]):''));o.value=k;hsel.append(o);});
      // 🏎️ Garage: si el piloto lleva un coche del Garage, la clase la pone SU coche (en el mando que le toque).
      const syncH=()=>{const gc=PeluGarage.uso(i);hsel.value=gc?gc.clase:(hcCfg().clases?.[String(carPick[i])]||'sin_iman');hsel.disabled=!!gc;hsel.title=gc?'La clase la pone el coche del Garage: '+gc.nombre:'';};syncH();
      sel.addEventListener('change',()=>{carPick[i]=Number(sel.value);renderSetup(true);});
      hsel.addEventListener('click',e=>e.preventDefault&&e.stopPropagation());
      hsel.addEventListener('change',async()=>{const c={};c[String(carPick[i])]=hsel.value;try{await saveHandicap({clases:c});toast('Coche '+carPick[i]+': '+PeluHandicap.NOMBRE[hsel.value]);}catch(e){toast(e.message);syncH();}});
      // Nivel del piloto (se guarda en el registro): suma o resta por vuelta además de la clase del coche.
      const nv=p.nivel||'intermedio',nsel=el('select','nv-sel');nsel.setAttribute('aria-label','Nivel de '+p.name);
      PeluHandicap.NIVELES.forEach(([k,n])=>{const o=el('option','',PeluHandicap.NIVEL_ICON[k]+' '+n+(hh.enabled&&hh.nivel_on!==false?' · '+PeluHandicap.segTxt((hh.seg_nivel||{})[k]||0):''));o.value=k;nsel.append(o);});nsel.value=nv;
      nsel.addEventListener('click',e=>e.preventDefault&&e.stopPropagation());
      nsel.addEventListener('change',()=>setNivel(i,nsel.value));
      const sels=el('span','pick-sel');sels.append(sel,hsel,nsel);
      const names={};roster.slots.forEach((x,k)=>{if(x)names[String(k)]=x.name;});
      sels.append(PeluGarage.pilot(i,p.name,names,()=>renderSetup(true),m=>toast(m)));
      if(p.sugerido&&p.sugerido.nivel!==nv){const sg=el('small','pick-sug');sg.append(document.createTextNode('Sugerido: '+PeluHandicap.NIVEL_ICON[p.sugerido.nivel]+' '+PeluHandicap.nivelTxt(p.sugerido.nivel)+' ('+Number(p.sugerido.s).toFixed(2)+' s) '));
        const ok=el('button','chip-button','Aceptar');ok.type='button';ok.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();setNivel(i,p.sugerido.nivel);});sg.append(ok);name.append(sg);}
      card.append(cb,img,name,sels);box.append(card);});
    if(!roster.slots.some(Boolean))box.append(el('p','muted','No hay pilotos. Regístralos en el menú → Pilotos.'));
    else{const bar=el('div','sortear-bar');const b=el('button','sortear-btn','🎲 Sortear mandos');b.type='button';b.id='gpSortear';
      b.addEventListener('click',()=>{const ids=[...picked].filter(k=>roster.slots[k]);if(!ids.length){toast('Marca a los pilotos que corren y luego sortea.');return;}
        const toca=PeluGarage.sortear(ids.length);ids.forEach((k,n)=>{carPick[k]=toca[n];});b.blur();renderSetup(true);
        toast('🎲 Mandos: '+ids.map(k=>roster.slots[k].name+' → '+carPick[k]).join(' · '));});
      bar.append(b,el('small','muted','A cada piloto marcado le toca un mando distinto. Su coche del Garage va con él.'));box.prepend(bar);}}
  const tr=$('throttleRow');if(!tr.children.length)for(let k=1;k<=6;k++){const s=el('span','thr');s.dataset.car=k;s.append(el('b','',k),el('i'));tr.append(s);}
  const th=state.scx.throttle||[];tr.querySelectorAll('.thr').forEach((s,i)=>{const v=th[i];s.classList.toggle('none',v==null);s.classList.toggle('hot',v>0);s.querySelector('i').style.width=(v?v/15*100:0)+'%';s.title=v==null?'Sin mando':'Gatillo '+v;});
}
$('createGp').addEventListener('click',async()=>{
  const ids=[...picked].filter(i=>roster.slots[i]);$('setupError').textContent='';
  if(ids.length<2){$('setupError').textContent='Elige al menos 2 pilotos.';return;}
  const cars={};ids.forEach(i=>cars[String(i)]=carPick[i]);
  $('createGp').disabled=true;try{apply(await post('/api/gp',{action:'create',slots:ids,cars}));}catch(e){$('setupError').textContent=e.message;}finally{$('createGp').disabled=false;}
});

/* ---------------- Carrera ---------------- */
async function act(action,extra={}){
  if(busy)return;busy=true;$('gpError').textContent='';
  try{apply(await post('/api/gp',Object.assign({action,id:state.gp.id},extra)));}
  catch(e){if(action==='start'&&/SCX/.test(e.message)&&confirm(e.message+'\n\n¿Arrancar de todos modos?')){busy=false;return act('start',{force:true});}$('gpError').textContent=e.message;}
  finally{busy=false;}
}
$('btnStart').addEventListener('click',()=>act('start'));
$('btnEnd').addEventListener('click',()=>{if(confirm('¿Terminar esta parte ahora? Se guardan las vueltas que lleven.'))act('end_run');});
$('btnRepeat').addEventListener('click',()=>{if(confirm('¿Repetir esta parte desde cero? Se borran sus vueltas.'))act('repeat');});
$('btnSkip').addEventListener('click',()=>{if(confirm('¿Saltar a este piloto en la qualy? Saldrá al final.'))act('skip');});
$('btnNext').addEventListener('click',()=>act('next'));
$('btnCancel').addEventListener('click',()=>{if(confirm('¿Cancelar el Gran Premio completo? Se guarda una copia en data/gp.'))act('cancel');});
$('btnClose').addEventListener('click',()=>act('close'));

const KIND={quali:'QUALY',heat:'ELIMINATORIAS',final:'FINAL'};
function renderStepper(g){
  const st=$('stepper');
  if(g.mode==='torneo'&&window.PeluTorneo){PeluTorneo.stepper(g,st);return;}
  st.replaceChildren();
  const groups=[];g.runs.forEach((r,i)=>{let last=groups[groups.length-1];if(!last||last.kind!==r.kind){last={kind:r.kind,runs:[]};groups.push(last);}last.runs.push(i);});
  groups.forEach(gr=>{const li=el('li','step');const cur=gr.runs.includes(g.current)&&g.status==='active',done=g.status==='done'||gr.runs.every(i=>g.runs[i].phase==='done');
    li.classList.toggle('current',cur);li.classList.toggle('done',done&&!cur);
    li.append(el('b','',KIND[gr.kind]),el('small','',gr.kind==='final'?g.config.final_laps+' vueltas':gr.runs.filter(i=>g.runs[i].phase==='done').length+'/'+gr.runs.length));st.append(li);});
}
function cardFor(slot){
  const dash=$('dash');let card=dash.querySelector('[data-slot="'+slot+'"]');
  const hon=!!state.gp?.handicap?.on;
  if(card&&card.dataset.hon!==String(hon)){gauges.delete(slot);card.remove();card=null;}
  const pcar=String((state.gp.pilots.find(x=>x.slot===slot)||{}).car);   // torneo: el mismo piloto puede traer otro coche en la siguiente manga
  if(card&&card.dataset.car!==pcar){gauges.delete(slot);card.remove();card=null;}
  if(card&&(!card.querySelector('[data-k="last"] .greal')||!card.querySelector('[data-k="last"] .gkmh')||!card.querySelector('[data-k="best"] .gkmh')||!card.querySelector('.gtire'))){gauges.delete(slot);card.remove();card=null;}
  if(!card){
    const p=state.gp.pilots.find(x=>x.slot===slot);card=el('article','gcard');card.dataset.slot=slot;card.dataset.hon=String(hon);card.dataset.car=pcar;card.style.setProperty('--team',COLORS[teamIdx(slot)]);
    const top=el('div','gtop');const pos=el('div','gpos','—');const img=el('img','gav');img.src=p.avatar;img.alt='';
    const nm=el('div','gname'),pide=el('span','pide sin','⇄');pide.dataset.car=p.car;pide.setAttribute('role','status');const fl=el('span','gflags');fl.title='Banderas amarillas que pidió en esta parte (triple clic en su botón de cambio de carril)';const hcl=el('span','hclase',hon&&p.clase?PeluHandicap.detalle(p):'');hcl.hidden=!(hon&&p.clase);nm.append(el('strong','',p.name),el('small','','Coche '+p.car+' · '+TEAM[teamIdx(slot)]+(p.nivel?' · '+PeluHandicap.NIVEL_ICON[p.nivel]+' '+PeluHandicap.nivelTxt(p.nivel):'')+(p.coche_nombre?' · 🏎️ '+p.coche_nombre:'')),hcl,pide,fl);
    const badge=el('span','gbadge');top.append(pos,img,nm,badge);
    const cv=el('canvas','gcanvas');const stats=el('div','gstats');
    [['Vueltas','laps'],['Última','last'],['Mejor','best']].forEach(([l,k])=>{const b=el('div');b.append(el('span','',l),el('strong','','—'));b.dataset.k=k;if(k!=='laps'){const real=el('small','greal');real.hidden=true;const kmh=el('small','gkmh');kmh.hidden=true;b.append(real,kmh);}stats.append(b);});
    const sus=el('p','gsus');sus.hidden=true;sus.setAttribute('role','note');
    const gpits=el('p','gpits');gpits.hidden=true;gpits.setAttribute('role','status');
    const gtire=el('div','gtire');gtire.setAttribute('role','status');
    card.append(top,cv,stats,gtire,gpits,sus);dash.append(card);gauges.set(slot,new Gauge(cv));
  }
  return card;
}
function setText(node,t){t=String(t);if(node.textContent!==t)node.textContent=t;}
function renderDash(g){
  const run=g.run,cfg=g.config,fuel=state.scx.fuel||[];
  let rows;
  if(run.kind==='quali'){
    // En qualy se ven todos: el que corre en vivo y los demás con su mejor vuelta.
    const live=run.rows[0];const q=g.quali;
    rows=q.map((r,i)=>{const p=g.pilots.find(x=>x.slot===r.slot);
      if(live&&r.slot===live.slot)return Object.assign({},live,{pos:r.best!=null||live.best!=null?null:null,active:true});
      return {slot:r.slot,laps:r.laps,last:null,best:r.best,best_h:r.best_h,h_s:r.h_s,clase:r.clase,sospechosas_n:r.sospechosas_n||0,dsq:!!r.dsq,banderas:r.banderas||0,kmh:r.best?cfg.track_length_m/r.best*3.6*cfg.scale:null,fuel:cfg.fuel_enabled?fuel[p.car-1]:null,waiting:!r.done,done:r.done,skipped:r.skipped,pits:r.pits||(live&&r.slot===live.slot?live.pits:null)};});
    // posiciones por mejor vuelta (incluye al que corre)
    // Con handicap: mejor vuelta + segundos de su clase.
    const qb=r=>g.handicap?.on?r.best_h:r.best;
    const bests=rows.filter(r=>!r.dsq).map(qb).filter(b=>b!=null).sort((a,b)=>a-b);rows.forEach(r=>r.pos=qb(r)!=null&&!r.dsq?bests.indexOf(qb(r))+1:null);
    rows.sort((a,b)=>(!!a.dsq-!!b.dsq)||(a.pos??99)-(b.pos??99)||g.order.indexOf(a.slot)-g.order.indexOf(b.slot));
  }else rows=run.rows;
  const dash=$('dash');const keep=new Set(rows.map(r=>r.slot));
  [...dash.children].forEach(c=>{if(!keep.has(Number(c.dataset.slot))){gauges.delete(Number(c.dataset.slot));c.remove();}});
  dash.classList.toggle('few',rows.length<=4);
  rows.forEach((r,i)=>{
    const card=cardFor(r.slot);if(dash.children[i]!==card)dash.insertBefore(card,dash.children[i]||null);
    setText(card.querySelector('.gpos'),r.dsq?'DSQ':r.finish_pos?('P'+r.finish_pos):r.pos?('P'+r.pos):'—');
    // Bandera amarilla del piloto: «🟨 2/4» por parte; DSQ si se pasó del máximo.
    const fl=card.querySelector('.gflags'),fc=flagCfg(cfg),used=r.banderas||0,ft=r.dsq?'⛔ DSQ':(!fc.enabled&&!used)?'':'🟨 '+used+'/'+fc.max;
    setText(fl,ft);fl.hidden=!ft;fl.classList.toggle('dsq',!!r.dsq);fl.classList.toggle('full',!r.dsq&&used>=fc.max);card.classList.toggle('dsq',!!r.dsq);
    const target=run.kind==='final'?' / '+(run.target_laps):'';
    setText(card.querySelector('[data-k="laps"] strong'),(r.laps??0)+target);
    const hon=!!g.handicap?.on;   // con handicap: tiempo ajustado con «H» y el real abajo; km/h con el real
    PeluHandicap.setTime(card.querySelector('[data-k="last"] strong'),r.last,r.h_s,hon,card.querySelector('[data-k="last"] .greal'));
    PeluHandicap.setTime(card.querySelector('[data-k="best"] strong'),r.best,r.h_s,hon,card.querySelector('[data-k="best"] .greal'));
    PeluGauges.fillAvgKmh(card.querySelector('[data-k="last"] .gkmh'),r.last,cfg);
    PeluGauges.fillAvgKmh(card.querySelector('[data-k="best"] .gkmh'),r.best,cfg);
    let badge='',cls='';
    if(r.dsq){badge='DESCALIFICADO';cls='dsq';}
    else if(r.finished){badge=r.finish_pos===1?'🏁 GANADOR':'🏁 TERMINÓ';cls='fin';}
    else if(r.false_start){badge='SALIDA EN FALSO'+(r.penalty?' −'+r.penalty:'');cls='bad';}
    else if(run.kind==='quali'&&r.active){badge=run.phase==='running'||run.phase==='finishing'?'EN PISTA':run.phase==='countdown'?'AL SEMÁFORO':'SIGUE';cls='on';}
    else if(run.kind==='quali'&&r.skipped){badge='SALTADO';}
    else if(run.kind==='quali'&&r.waiting){badge='ESPERA TURNO';}
    else if(run.kind==='quali'&&r.done){badge='QUALY LISTA';}
    else if(run.phase==='ready'&&r.grid){badge='SALE '+r.grid+'º';}
    const pits=r.pits||{},inPits=!!pits.en_pits&&run.phase!=='done'&&run.phase!=='ready';
    if(inPits){badge='EN PITS · '+pitElapsed(pits).toFixed(1)+' s';cls='pits';}
    const b=card.querySelector('.gbadge');setText(b,badge);b.className='gbadge '+cls;b.hidden=!badge;
    card.classList.toggle('en-pits',inPits);
    card.classList.toggle('active',!!r.active||(run.kind!=='quali'&&(run.phase==='running'||run.phase==='finishing')&&!r.finished));
    card.classList.toggle('dim',run.kind==='quali'&&!r.active);
    const pitBox=card.querySelector('.gpits'),pitText=pitLine(pits);pitBox.hidden=!pitText;setText(pitBox,pitText);
    // Vueltas sospechosas (más cortas que la vuelta mínima): no cuentan; se muestran para revisarlas.
    const sb=card.querySelector('.gsus'),st=susText(r.sospechosas,r.sospechosas_n,cfg.min_lap_s);sb.hidden=!st;setText(sb,st);
    const stt=susTitle(r.sospechosas);if(sb.title!==stt)sb.title=stt;
    const fuelVal=cfg.fuel_enabled?(r.fuel??null):null;
    const showKmh=run.kind==='quali'&&!r.active?(r.best?cfg.track_length_m/r.best*3.6*cfg.scale:null):r.kmh;
    // Aguja en vivo con el gatillo del mando (gatillo.js); en qualy, los que esperan muestran su mejor vuelta.
    const pc=(g.pilots.find(x=>x.slot===r.slot)||{}).car,gg=gauges.get(r.slot);gg.car=run.kind==='quali'&&!r.active?null:(pc||null);
    gg.set(run.phase==='ready'&&!(run.kind==='quali'&&!r.active)?null:showKmh,fuelVal,cfg.speed_max_kmh,PeluGauges.tireRed(cfg));
    // Vida de llanta (= nivel de la Pit Box en %) con vueltas y km del juego actual; en rojo: CAMBIA LLANTAS / ENTRA A PITS.
    PeluGauges.fillTire(card.querySelector('.gtire'),fuelVal,cfg,{pits,inPits,finished:!!r.finished||run.phase==='done'||(run.kind==='quali'&&!r.active),off:!cfg.fuel_enabled});
  });
}
const SRC={scx:'Pit Box',ir:'Sensor IR','scx-sim':'Simulada'};
function flagCfg(c){c=c||{};return {enabled:c.pilot_flag_enabled!==false,max:Number.isInteger(c.pilot_flag_max)?c.pilot_flag_max:4};}
function fmtPit(s){if(s==null||!Number.isFinite(Number(s)))return '—';return Number(s).toFixed(1)+' s';}
function pitElapsed(pits){if(!pits||!pits.en_pits)return null;if(pits.entry_at)return Math.max(0,(Date.now()/1000)-pits.entry_at);return Number(pits.elapsed_s)||0;}
function pitLine(pits){
  if(!pits)return '';
  if(pits.en_pits){const t=pitElapsed(pits),n=pits.completadas||0;return '🔧 CAMBIO DE LLANTAS · '+t.toFixed(1)+' s'+(n?(' · '+n+' cambio'+(n===1?'':'s')+' antes'):'');}
  const n=pits.completadas||0;if(!n)return '';
  return 'Cambios de llantas: '+n+' · último '+fmtPit(pits.ultima_s)+' · total en pits '+fmtPit(pits.total_s);
}
function minText(m){const n=Number(m);return Number.isFinite(n)?String(Math.round(n*100)/100):'10';}
function susText(list,total,min){
  list=list||[];const n=Number.isInteger(total)&&total>=list.length?total:list.length;if(!n)return '';
  const times=list.slice(-4).reverse().map(x=>Number(x.s).toFixed(2)+' s');
  return '⚠ '+n+' vuelta'+(n===1?'':'s')+' sospechosa'+(n===1?'':'s')+' (<'+minText(min)+' s)'+(times.length?': '+times.join(' · ')+(n>times.length?' · …':''):'')+' · no cuenta'+(n===1?'':'n');
}
function susTitle(list){return (list||[]).slice(-20).reverse().map(x=>Number(x.s).toFixed(2)+' s · '+(x.hora?new Date(x.hora*1000).toLocaleTimeString('es-MX'):'')+' · '+(SRC[x.src]||x.src||'')+(x.car?' · coche '+x.car:'')).join('\n');}
function table(title,head,rows){const box=el('div','tbox');box.append(el('h3','',title));const t=el('table'),th=el('tr');head.forEach(h=>th.append(el('th','',h)));const thead=el('thead');thead.append(th);const tb=el('tbody');rows.forEach(r=>{const tr=el('tr');r.forEach(v=>tr.append(el('td','',v)));tb.append(tr);});t.append(thead,tb);box.append(t);return box;}
function renderTables(g,target){
  const name=s=>g.pilots.find(p=>p.slot===s).name,box=$(target);
  if(g.mode==='torneo'&&window.PeluTorneo){PeluTorneo.tables(g,box);return;}
  box.replaceChildren();
  // Handicap: columnas extra con el tiempo ajustado (H) y la clase de cada coche.
  const hon=!!g.handicap?.on,hn=r=>hon&&r.clase?' · '+PeluHandicap.detalle(r):'',fh=x=>x==null?'—':x.toFixed(2)+' s H';
  if(g.final.length&&g.runs[g.runs.length-1].phase!=='ready')box.append(table('Final'+(hon?' · con handicap (vueltas, luego tiempo total ajustado)':''),hon?['Pos','Piloto','Vueltas','Mejor','Mejor (H)','Total (H)']:['Pos','Piloto','Vueltas','Mejor'],g.final.map(r=>[r.dsq?'DSQ':r.pos??'—',r.name+(r.false_start?' ⚠':'')+(r.dsq?' · DESCALIFICADO':'')+hn(r),r.laps,fmt(r.best)].concat(hon?[fh(r.best_h),fh(r.total_h)]:[]))));
  if(g.heats.length&&g.runs.some(r=>r.kind==='heat'&&r.phase!=='ready'))box.append(table('Eliminatorias · suma de vueltas'+(hon?' · desempata el tiempo total con handicap':''),(hon?['Pos','Piloto','Vueltas','Mejor','Total (H)']:['Pos','Piloto','Vueltas','Mejor']).concat(g.heats[0].rounds.map((_,i)=>'R'+(i+1))),g.heats.map((r,i)=>[r.dsq?'DSQ':i+1,name(r.slot)+(r.dsq?' · DESCALIFICADO':'')+hn(r),r.laps,fmt(r.best)].concat(hon?[fh(r.total_h)]:[]).concat(r.rounds))));
  if((g.sospechosas||[]).length){const t=table('⚠ Vueltas sospechosas · no cuentan (menos de '+minText(g.config.min_lap_s)+' s)',['Parte','Piloto','Tiempo','Hora','Fuente'],g.sospechosas.slice(-30).reverse().map(x=>[x.parte,x.name+(x.car?' · coche '+x.car:''),fmt(x.s),x.hora?new Date(x.hora*1000).toLocaleTimeString('es-MX'):'',SRC[x.src]||x.src||'']));t.classList.add('sus-box');box.append(t);}
  if(g.quali.length)box.append(table('Qualy · mejor vuelta'+(hon?' + handicap':''),hon?['Pos','Piloto','Mejor','Mejor (H)','Vueltas']:['Pos','Piloto','Mejor','Vueltas'],g.quali.map((r,i)=>[r.dsq?'DSQ':r.best!=null?i+1:'—',name(r.slot)+(r.skipped?' (saltado)':'')+(r.dsq?' · DESCALIFICADO':'')+hn(r),fmt(r.best)].concat(hon?[fh(r.best_h)]:[]).concat([r.laps]))));
}
function renderLights(g){
  // Semáforo compartido con Práctica y Carrera (lights.js).
  const run=g.run;
  PeluLights.render(run?run.phase:null,run?run.countdown_ms:0,run?(run.countdown_total||g.config.lights_seconds||3)*1000:3000,run?run.label:'');
}
function renderRace(g){
  const run=g.run;renderStepper(g);const resuming=!!(run.red&&run.phase==='countdown');
  const yellow=run.red&&run.red.kind==='yellow';
  const hints={red:yellow?'🟨 BANDERA AMARILLA (la pidió '+(run.red.by_name||'un piloto')+'): carrera detenida. Las vueltas no cuentan. Aprieta Reanudar para el semáforo; el reloj sigue donde se quedó.':'🚩 BANDERA ROJA: carrera detenida. Las vueltas no cuentan. Aprieta Reanudar para el semáforo; el reloj sigue donde se quedó.',ready:run.kind==='quali'?'Pon el coche de '+(run.rows[0]?.name||'')+' en la pista y aprieta Empezar. Corre solo él.':'Todos a la pista, en el orden de salida. Aprieta Empezar.',countdown:'¡Semáforo! No aceleres antes del verde.',running:run.kind==='final'?'Gana el primero en completar '+run.target_laps+' vueltas.':run.kind==='heat'?'Se suman las vueltas. Desempata la mejor vuelta.':'Cuenta la mejor vuelta.',finishing:run.kind==='final'?'Bandera a cuadros: los demás terminan al cruzar la meta.':'Se acabó el tiempo: termina tu vuelta.',done:'Terminado. Revisa los tiempos y aprieta Siguiente.'};
  setText($('runEyebrow'),KIND[run.kind]+' · '+(resuming?'REANUDACIÓN':({ready:'LISTOS',countdown:'SEMÁFORO',running:'EN CARRERA',finishing:'ÚLTIMA VUELTA',done:'TERMINADO',red:yellow?'BANDERA AMARILLA':'BANDERA ROJA'})[run.phase]));
  setText($('runTitle'),run.kind==='quali'?run.label.replace('Qualy','Qualy de '+(run.rows[0]?.name||'')):run.label);
  // Handicap: aviso aparte (no alarga la indicación) y la regla de desempate correcta.
  const hon=!!g.handicap?.on;if(hon)hints.running=run.kind==='final'?'Primero en completar '+run.target_laps+' vueltas cruza primero; con handicap gana el menor tiempo total ajustado.':run.kind==='heat'?'Se suman las vueltas. Con handicap desempata el tiempo total ajustado.':'Cuenta la mejor vuelta + handicap.';
  let hb=$('runHandicap');if(!hb){hb=el('p','hc-banner');hb.id='runHandicap';$('dash').before(hb);}
  hb.hidden=!hon;setText(hb,hon?'⚖ Handicap por vuelta · '+g.handicap.resumen+' · H = tiempo con handicap (el real va abajo)':'');
  const hcHint='';
  setText($('runHint'),(resuming?'Semáforo de reanudación: nadie acelera antes del verde. El reloj sigue desde donde se quedó.':hints[run.phase]||'')+hcHint);
  if(run.kind==='final'){const lead=run.rows[0];setText($('clockLabel'),'VUELTAS DEL LÍDER');setText($('clock'),(lead?lead.laps:0)+' / '+run.target_laps);}
  else{setText($('clockLabel'),run.red?'TIEMPO · PARO':run.phase==='finishing'?'TERMINA LA VUELTA':'TIEMPO');setText($('clock'),run.red?clock(run.remaining_ms):run.phase==='ready'||run.phase==='countdown'?clock((run.kind==='quali'?g.config.quali_minutes:g.config.heats_minutes)*60000):clock(run.remaining_ms));}
  $('clock').classList.toggle('low',run.remaining_ms!=null&&run.remaining_ms<10000&&run.phase==='running');
  $('clock').classList.toggle('paro',!!run.red);
  $('btnStart').hidden=run.phase!=='ready';$('btnEnd').hidden=!['running','finishing','countdown','red'].includes(run.phase);
  $('btnRepeat').hidden=run.phase==='ready';$('btnSkip').hidden=!(run.kind==='quali'&&run.phase==='ready');$('btnNext').hidden=run.phase!=='done';
  $('btnNext').textContent=g.mode==='torneo'&&window.PeluTorneo?PeluTorneo.nextLabel(g):g.current+1>=g.runs.length?'Ver podio 🏆':'Siguiente: '+g.runs[g.current+1].label+' →';
  if(window.PeluTorneo)PeluTorneo.renderRace(g);
  setText($('gpNotice'),g.notice||'');
  renderDash(g);renderTables(g,'tables');renderLights(g);
  PeluParo.render({canStop:['running','finishing','countdown'].includes(run.phase),red:!!run.red,resuming,n:run.red?.n,
    kind:run.red?.kind||'red',by:run.red?.by_name||null,used:run.red?.used??null,max:run.red?.max??null,
    frozenMs:run.kind==='final'?run.elapsed_ms:(run.remaining_ms??run.elapsed_ms),label:'GRAN PREMIO · '+run.label});
}
PeluParo.onStop=async()=>{if(!state?.gp)return;apply(await post('/api/gp',{action:'red_flag',id:state.gp.id}));};
PeluParo.onResume=async()=>{if(!state?.gp)return;apply(await post('/api/gp',{action:'resume',id:state.gp.id}));};
function renderDone(g){
  const pod=$('podium');pod.replaceChildren();const top=g.final.filter(r=>!r.dsq).slice(0,3);   // un descalificado no sube al podio
  [1,0,2].forEach(i=>{const r=top[i];if(!r)return;const b=el('div','pod pod'+(i+1));b.style.setProperty('--team',COLORS[teamIdx(r.slot,r.car)]);const img=el('img');img.src=r.avatar;img.alt='';b.append(img,el('strong','',r.name),el('span','',['🥇','🥈','🥉'][i]+' P'+(i+1)+' · '+r.laps+' v · '+(g.handicap?.on?'total '+(r.total_h==null?'—':r.total_h.toFixed(2)+' s')+' H · '+PeluHandicap.detalle(r):'mejor '+fmt(r.best))));pod.append(b);});
  if(window.PeluTorneo)PeluTorneo.renderDone(g);
  const hb=$('podiumHandicap');if(hb){hb.hidden=!g.handicap?.on;hb.textContent=g.handicap?.on?'Con handicap · H = tiempo real + ajuste por vuelta ('+g.handicap.resumen+'). El orden real de cruce está en el CSV.':'';}
  renderTables(g,'doneTables');
}
function show(name){if(screenName===name)return;screenName=name;document.body.classList.toggle('racing',name==='race');['setupScreen','raceScreen','doneScreen'].forEach(id=>$(id).hidden=id!==name+'Screen');window.scrollTo(0,0);}
function apply(data){
  state=data;const g=data.gp;
  const sc=data.scx,chip=$('scxStatus');chip.textContent=sc.connected?('● SCX '+(sc.simulated?'simulada':'conectada')+(sc.fuel_consumo===false?' · desgaste de llanta apagado en Pit Box':'')):'● SCX sin datos';chip.className='chip '+(sc.connected?'ok':'bad');chip.title=sc.error||sc.port||'';
  handleEvents(g);
  if(!g||g.status==='cancelled'){show('setup');renderSetup(false);if(window.PeluTorneo)PeluTorneo.renderSetup(false);$('gpSubtitle').textContent='Qualy · Eliminatorias · Final. Sin features: pura carrera.';PeluLights.hide();PeluParo.hide();return;}
  $('gpSubtitle').textContent=g.mode==='torneo'&&window.PeluTorneo?PeluTorneo.formatText(g):formatText(g.config);
  if(g.status==='done'){show('done');if(lastVersion!==g.version)renderDone(g);lastVersion=g.version;PeluLights.hide();PeluParo.hide();return;}
  show('race');renderRace(g);lastVersion=g.version;
}
let polling=false,fails=0;
async function poll(){
  if(polling)return;polling=true;const ctrl=new AbortController(),to=setTimeout(()=>ctrl.abort(),2500);
  try{const r=await fetch('/api/gp',{cache:'no-store',signal:ctrl.signal});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json();fails=0;$('connection').textContent='● En vivo';$('connection').className='chip ok';PeluAvisos.show(d.boot,d.avisos);if(PeluAvisos.restarted(d.boot)){lastVersion=null;toast('El servidor de la Mac se reinició. Ya está conectado otra vez.');}apply(d);}
  catch(e){fails++;if(fails>3){$('connection').textContent=fails>20?PeluAvisos.offlineText(99):'Sin respuesta de la Mac · reintentando';$('connection').className='chip bad';const sc=$('scxStatus');sc.textContent='● SCX sin datos (no hay conexión con la Mac)';sc.className='chip bad';}}
  finally{clearTimeout(to);polling=false;}
}
async function setNivel(i,nivel){try{await post('/api/slot',{slot:i,action:'nivel',nivel});toast('Nivel de '+(roster.slots[i]||{}).name+': '+PeluHandicap.nivelTxt(nivel));await pollRoster();renderSetup(true);}catch(e){toast(e.message);}}
// 🏎️ Garage: coches en pista por mando (Nuevo Gran Premio y Torneo los muestran).
PeluGarage.onChange(()=>{if(state&&screenName==='setup')renderSetup(true);});PeluGarage.start(5000);
async function pollRoster(){try{const r=await fetch('/api/roster',{cache:'no-store'});if(r.ok){roster=await r.json();if(state&&screenName==='setup')renderSetup(false);}}catch(e){}}
syncSoundButton();pollRoster().then(poll);setInterval(poll,250);setInterval(pollRoster,3000);
window.PELU_GP={get state(){return state;}};
