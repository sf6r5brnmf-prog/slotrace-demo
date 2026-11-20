'use strict';
// «Mi coche»: el teléfono de cada piloto. Solo lectura: no hay Empezar ni nada que cambie la carrera.
// Usa /api/micoche (solo los datos de ese piloto), las mismas agujas (gauges.js), el mismo semáforo (lights.js)
// y los mismos avisos de conexión/reinicio (avisos.js) que las pantallas grandes.
(function(){
const $=id=>document.getElementById(id);
const KEY='micoche-piloto';
function fmtPit(s){if(s==null||!Number.isFinite(Number(s)))return '—';return Number(s).toFixed(1)+' s';}
function pitElapsed(pits){if(!pits||!pits.en_pits)return null;if(pits.entry_at)return Math.max(0,(Date.now()/1000)-pits.entry_at);return Number(pits.elapsed_s)||0;}
function pitLine(pits){if(!pits)return '';if(pits.en_pits){const t=pitElapsed(pits),n=pits.completadas||0;return '🔧 CAMBIO DE LLANTAS · '+t.toFixed(1)+' s'+(n?(' · '+n+' cambio'+(n===1?'':'s')+' antes'):'');}const n=pits.completadas||0;if(!n)return '';return 'Cambios de llantas: '+n+' · último '+fmtPit(pits.ultima_s)+' · total en pits '+fmtPit(pits.total_s);}

const fmt=s=>s==null?'—':Number(s).toFixed(2)+' s';
function clock(ms){if(ms==null)return'—';const t=Math.ceil(ms/1000),m=Math.floor(t/60),s=t%60;return m+':'+String(s).padStart(2,'0');}
function setText(node,t){t=t==null?'':String(t);if(node&&node.textContent!==t)node.textContent=t;}
function avatarSrc(path){return path?path+(path.includes('?')?'&':'?')+'v=mica2':'';}
function toast(t){const b=$('toast');b.textContent=t;b.style.display='block';clearTimeout(toast.t);toast.t=setTimeout(()=>b.style.display='none',4200);}

let roster=null,choice=null,state=null,screen='',fails=0,polling=false,timer=null,ctrl=null,started=0,lastFinish=performance.now();
let rosterFails=0,lastEventId=null,soundDeadline=null,lastLapsKey='';

/* ---------- piloto elegido en este teléfono ---------- */
function loadChoice(){try{const v=JSON.parse(localStorage.getItem(KEY)||'null');if(v&&Number.isInteger(v.slot)&&typeof v.name==='string')return v;}catch(e){}return null;}
function saveChoice(c){choice=c;try{if(c)localStorage.setItem(KEY,JSON.stringify(c));else localStorage.removeItem(KEY);}catch(e){}}
function urlFor(c){return 'micoche.html'+(c?'?piloto='+encodeURIComponent(c.name):'');}
function setUrl(c){try{const u=urlFor(c);if(location.pathname+location.search!==u)history.replaceState(null,'',u);}catch(e){}}
function norm(s){return String(s||'').trim().toLocaleLowerCase('es-MX');}
function resolve(){
  // ?piloto=Ernesto (o ?piloto=1) manda sobre lo guardado: así cada marcador / ícono abre a su piloto.
  const slots=roster.slots||[];
  const param=new URLSearchParams(location.search).get('piloto');
  if(param){
    let i=slots.findIndex(p=>p&&norm(p.name)===norm(param));
    if(i<0&&/^[1-6]$/.test(param.trim())&&slots[Number(param)-1])i=Number(param)-1;
    if(i>=0){saveChoice({slot:i,name:slots[i].name});return {ok:true};}
    return {ok:false,note:'No encontré al piloto «'+param+'» en el registro. Elige tu piloto.'};
  }
  const c=loadChoice();if(!c)return {ok:false};
  if(slots[c.slot]&&norm(slots[c.slot].name)===norm(c.name)){choice=c;return {ok:true};}
  const i=slots.findIndex(p=>p&&norm(p.name)===norm(c.name));
  if(i>=0){saveChoice({slot:i,name:slots[i].name});return {ok:true};}
  saveChoice(null);return {ok:false,note:'«'+c.name+'» ya no está en el registro de pilotos. Elige tu piloto otra vez.'};
}
function show(name){if(screen===name)return;screen=name;$('chooseScreen').hidden=name!=='choose';$('carScreen').hidden=name!=='car';window.scrollTo(0,0);}
function renderChooser(note){
  show('choose');PeluLights.hide();PeluParo.hide();document.body.style.removeProperty('--team');
  const n=$('chooseNote');n.hidden=!note;setText(n,note||'');
  const list=$('pilotList'),slots=roster?.slots||[],colors=roster?.colors||[];
  const sig=JSON.stringify(slots.map(p=>p&&[p.name,p.avatar]));if(list.dataset.sig===sig)return;list.dataset.sig=sig;list.replaceChildren();
  slots.forEach((p,i)=>{if(!p)return;
    const b=document.createElement('button');b.type='button';b.className='mc-pilot';b.dataset.slot=i;b.style.setProperty('--team',colors[i]?.hex||'#d5ff42');
    const img=document.createElement('img');img.src=avatarSrc(p.avatar);img.alt='';img.addEventListener('error',()=>img.removeAttribute('src'),{once:true});
    const nm=document.createElement('strong');nm.textContent=p.name;const sm=document.createElement('small');sm.textContent=colors[i]?.name||'';
    b.append(img,nm,sm);b.addEventListener('click',()=>pick(i));list.append(b);});
  $('chooseEmpty').hidden=slots.some(Boolean);
}
function pick(i){const p=roster.slots[i];if(!p)return;saveChoice({slot:i,name:p.name});setUrl(choice);state=null;lastEventId=null;lastLapsKey='';show('car');renderWaiting('Conectando…','Buscando tu coche en la sesión.');schedule(0);keepAwake();}
$('changePilot').addEventListener('click',()=>{saveChoice(null);setUrl(null);state=null;$('pilotList').dataset.sig='';renderChooser();});

/* ---------- sonido (mismo interruptor por equipo que las otras pantallas) ---------- */
const SFX={};['semaforo','abucheo','bandera_final','aplausos'].forEach(n=>{const a=new Audio('sfx/'+n+'.mp3');a.preload='auto';SFX[n]=a;});
let sfxDevice=false;try{sfxDevice=localStorage.getItem('gp-sound')==='on';}catch(e){}
let sfxUnlocked=false;
function volume(){const d=state?.dashboard;return d&&d.sound_enabled===false?0:Math.max(0,Math.min(1,(Number.isFinite(d?.sound_volume)?d.sound_volume:80)/100));}
function play(name,offset=0){if(!sfxDevice||!sfxUnlocked)return;const v=volume();if(!v)return;const a=SFX[name];if(!a)return;try{a.pause();a.currentTime=offset>0?offset:0;}catch(e){}a.volume=v;a.play().catch(()=>{});}
function unlock(){Object.values(SFX).forEach(a=>{a.muted=true;a.play().then(()=>{a.pause();a.currentTime=0;a.muted=false;}).catch(()=>{a.muted=false;});});}
function syncSound(){const b=$('soundToggle'),on=sfxDevice&&sfxUnlocked;b.textContent=on?'🔊 Sonido en este equipo':'🔇 Activar sonido aquí';b.classList.toggle('on',on);}
$('soundToggle').addEventListener('click',()=>{if(sfxDevice&&sfxUnlocked)sfxDevice=false;else{sfxDevice=true;sfxUnlocked=true;unlock();}try{localStorage.setItem('gp-sound',sfxDevice?'on':'off');}catch(e){}syncSound();});
document.addEventListener('pointerdown',()=>{if(sfxDevice&&!sfxUnlocked){sfxUnlocked=true;unlock();syncSound();}keepAwake();});
syncSound();

/* ---------- pantalla siempre encendida (Wake Lock; si no hay, se avisa cómo) ---------- */
let wake=null;
async function keepAwake(){
  if(!('wakeLock' in navigator)){setText($('wakeNote'),'Solo lectura: Empezar está en la pantalla grande. Para que no se apague el teléfono: Ajustes → Pantalla → Bloqueo automático → Nunca (mientras corres).');return;}
  if(document.hidden||wake||screen!=='car')return;
  try{wake=await navigator.wakeLock.request('screen');wake.addEventListener('release',()=>{wake=null;});}catch(e){wake=null;}
}

/* ---------- agujas ---------- */
const gauges=PeluGauges.watch(new Map());const gauge=new PeluGauges.Gauge($('gauge'));gauges.set(0,gauge);

/* ---------- render ---------- */
function renderWaiting(title,text){$('waitBox').hidden=false;$('dashBox').hidden=true;setText($('waitTitle'),title);setText($('waitText'),text);}
function renderPilot(p,d){
  document.body.style.setProperty('--team',p.color);
  const img=$('meAvatar'),src=avatarSrc(p.avatar);if(img.getAttribute('src')!==src){img.src=src;img.alt='Avatar de '+p.name;}
  setText($('meName'),p.name);
  setText($('meCar'),d?(d.por_turnos?'Equipo '+p.color_name+' · por turnos':'Coche '+d.car+' · '+p.color_name):p.color_name);
  // Bandera amarilla del piloto: «🟨 2/4» (las que pidió en esta carrera) o DSQ. Solo se ve; aquí no se quita nada.
  const fl=$('meFlags'),b=d&&d.banderas,ft=!b?'':b.dsq?'⛔ DESCALIFICADO':(!b.on&&!b.usadas)?'':b.texto;
  setText(fl,ft);fl.hidden=!ft;fl.classList.toggle('dsq',!!(b&&b.dsq));fl.classList.toggle('full',!!(b&&!b.dsq&&b.usadas>=b.max));
  if(choice&&choice.name!==p.name)saveChoice({slot:p.slot,name:p.name});
}
function render(v){
  const p=v.piloto,s=v.sesion,d=v.datos,dash=v.dashboard||{};
  renderPilot(p,d);
  const bar=$('phaseBar');
  setText($('sessionTitle'),s?s.titulo:'Puto el último');
  let phaseText=s?s.fase_texto:'Sin sesión';
  if(d&&s&&s.fuente!=='gp'&&d.por_turnos&&s.fase==='running'&&!d.en_pista)phaseText='Corre otro piloto · espera tu turno';
  setText($('phaseText'),phaseText);
  setText($('stageText'),s&&s.fuente==='gp'?(s.etapa||'')+(s.target_laps?' · meta a '+s.target_laps+' vueltas':''):'');
  const paro=!!s&&!!s.paro&&!s.paro.reanudando;
  bar.classList.toggle('go',!!s&&!paro&&!s.paro&&(s.fase==='running'||s.fase==='finishing'));bar.classList.toggle('lights',!!s&&s.fase==='countdown');bar.classList.toggle('paro',paro);
  $('mePos').parentElement.hidden=v.estado!=='en_sesion';
  const pos=d&&d.dsq?'DSQ':d&&d.pos?'P'+d.pos:'—';setText($('mePos'),pos);
  const total=d&&s?(s.etapa_tipo==='quali'?d.total:s.participantes):0;setText($('mePosOf'),d&&d.dsq?'descalificado':d&&d.pos?'de '+total:(v.estado==='en_sesion'?'sin vueltas':''));
  if(v.estado==='sin_sesion'){renderWaiting('Esperando una sesión','Cuando arranquen una Práctica, Carrera o Gran Premio en la pantalla grande, aquí aparece tu coche. No tienes que hacer nada.');}
  else if(v.estado==='no_estas'){renderWaiting('No estás en esta carrera',(s?s.titulo+' está corriendo sin ti. ':'')+'Si te agregan, tu coche aparece aquí solo.');}
  else if(v.estado==='espera_turno'||v.estado==='fuera'){
    const q=d&&d.qualy;let t=s&&s.aviso?s.aviso:'';
    if(q&&q.best!=null)t+=' Tu qualy: mejor '+fmt(q.best)+(q.pos?' (P'+q.pos+' de '+q.total+')':'')+'.';
    renderWaiting(v.estado==='espera_turno'?'Espera tu turno':(s&&s.gp_terminado?'Gran Premio terminado':'Hoy te toca ver'),t.trim());
  }else{
    $('waitBox').hidden=true;$('dashBox').hidden=false;
    const ready=s.fase==='ready'||s.fase==='countdown';
    // Aguja en vivo con el gatillo de mi mando (gatillo.js); sin datos de la tarjeta, la velocidad de la última vuelta.
    const myCar=Number.isInteger(d.car)&&(!d.por_turnos||d.en_pista)?d.car:null;gauge.car=myCar;
    const pe=$('mePide'),pc=myCar?String(myCar):'';if(pe.dataset.car!==pc){if(pc)pe.dataset.car=pc;else delete pe.dataset.car;pe.classList.add('sin');}
    gauge.set(ready&&s.fuente==='gp'?null:d.kmh,d.fuel,dash.speed_max_kmh,PeluGauges.tireRed(dash));
    setText($('stLaps'),String(d.laps??0)+(s.target_laps?' / '+s.target_laps:''));
    setText($('stLast'),fmt(d.last));setText($('stBest'),fmt(d.best));
    PeluGauges.fillAvgKmh($('stLastKmh'),d.last,dash);PeluGauges.fillAvgKmh($('stBestKmh'),d.best,dash);
    let gl='Diferencia',gv='—';
    if(d.gap_vueltas!=null){gl='Al líder';gv=d.gap_vueltas===0?'Misma v.':'−'+d.gap_vueltas+' v';}
    else if(d.gap!=null){gl='Al mejor';gv='+'+d.gap.toFixed(2);}
    else if(d.pos===1)gv='Líder';
    setText($('stGapLabel'),gl);setText($('stGap'),gv);
    // Vida de llanta = el nivel de la Pit Box en % (antes «combustible»). Verde >50, amarilla 20–50, roja <20.
    const lvl=PeluGauges.tireLevel(d.fuel,dash),low=lvl==='roja',inPits=!!(d.pits&&d.pits.en_pits);
    setText($('stFuel'),d.fuel==null?'—':d.fuel+'%');$('stFuel').classList.toggle('low',low);$('stFuel').classList.toggle('mid',lvl==='amarilla');$('stFuel').classList.toggle('ok',lvl==='verde');
    PeluGauges.fillTire($('meTire'),d.fuel,dash,{pits:d.pits,inPits,finished:!!d.finished,off:dash.fuel_enabled===false});
    if(s.fuente==='gp'&&s.target_laps){setText($('stClockLabel'),'Meta');setText($('stClock'),s.target_laps+' v');}
    else if(s.fuente==='gp'){setText($('stClockLabel'),s.fase==='finishing'?'Última vuelta':'Tiempo');setText($('stClock'),s.fase==='finishing'?'🏁':clock(s.remaining_ms));}
    else{setText($('stClockLabel'),'Coche');setText($('stClock'),d.por_turnos?'Turnos':String(d.car));}
    const alerts=[];
    if(d.finished&&d.finish_pos&&s.fuente==='gp')alerts.push(['fin',d.finish_pos===1?'🏁 ¡GANASTE!':'🏁 Terminaste P'+d.finish_pos]);
    if(d.dsq)alerts.push(['bad','⛔ DESCALIFICADO: pediste más banderas amarillas de las permitidas. Tus vueltas ya no cuentan en esta '+(s.fuente==='gp'?'parte':'sesión')+'.']);
    else if(d.banderas&&d.banderas.on&&d.banderas.usadas>=d.banderas.max&&s.fase!=='ended'&&s.fase!=='done')alerts.push(['warn','🟨 Ya usaste tus '+d.banderas.max+' banderas amarillas'+(d.banderas.descalifica?'. Una más y quedas descalificado.':'.')]);
    if(d.false_start)alerts.push(['bad','⚠ Salida en falso'+(d.penalty?' · castigo −'+d.penalty+' vuelta'+(d.penalty===1?'':'s'):'')]);
    if(low&&!d.finished&&!(d.pits&&d.pits.en_pits))alerts.push(['fuel','🔴 CAMBIA LLANTAS / ENTRA A PITS']);
    if(d.pits&&d.pits.en_pits)alerts.push(['pits','🔧 Cambio de llantas · '+pitElapsed(d.pits).toFixed(1)+' s']);
    const sus=d.sospechosas;
    if(sus&&sus.n>0){const m=Number.isFinite(Number(sus.min))?String(Math.round(Number(sus.min)*100)/100):'10',t=(sus.lista||[]).slice(0,3).map(x=>fmt(x.s));
      alerts.push(['warn','⚠ '+sus.n+' vuelta'+(sus.n===1?'':'s')+' sospechosa'+(sus.n===1?'':'s')+' (<'+m+' s) no cont'+(sus.n===1?'ó':'aron')+(t.length?': '+t.join(' · '):'')]);}
    if(d.ultimo&&s.fase!=='ready')alerts.push(['bad',v.sesion.titulo.includes('chelas')?'🍻 Vas último: invitas las chelas':'⚑ Vas último']);
    if(s.fuente!=='gp'&&d.por_turnos&&d.turno_tuyo&&(s.fase==='ready'||s.fase==='paused'))alerts.push(['info','👉 Te toca: pon tu coche en la pista']);
    if(s.fase==='ready'&&d.grid)alerts.push(['info','Sales '+d.grid+'º en la parrilla']);
    if(s.aviso)alerts.push(['info',s.aviso]);
    const pitsEl=$('mePits'),pitsText=d.pits?pitLine(d.pits):'';
    if(pitsEl){pitsEl.hidden=!pitsText;if(pitsEl.textContent!==pitsText)pitsEl.textContent=pitsText;}
    const box=$('alerts'),sig=JSON.stringify(alerts);
    if(box.dataset.sig!==sig){box.dataset.sig=sig;box.replaceChildren(...alerts.map(([c,t])=>{const e=document.createElement('div');e.className='mc-alert '+c;e.textContent=t;return e;}));}
    const ev=$('events'),evs=(d.eventos||[]).slice().reverse(),es=JSON.stringify(evs.map(e=>e.id));
    if(ev.dataset.sig!==es){ev.dataset.sig=es;ev.replaceChildren(...evs.map(e=>{const x=document.createElement('div');x.textContent=({best:'★ ',false_start:'⚠ ',suspicious:'⚠ ',winner:'🏁 ',finish:'🏁 ',quali_done:'✔ ',yellow_flag:'🟨 ',dsq:'⛔ ',pit_entry:'🔧 ',pit_exit:'🔧 '}[e.type]||'• ')+e.text;return x;}));}
    const laps=d.vueltas_lista||[],lk=JSON.stringify(laps);$('lapsBox').hidden=!laps.length;
    if(lk!==lastLapsKey){lastLapsKey=lk;$('lapRows').replaceChildren(...laps.map(l=>{const tr=document.createElement('tr');[l.n,fmt(l.s)+(l.valid===false?' ✕':''),l.kmh==null?'—':Math.round(l.kmh)].forEach(x=>{const td=document.createElement('td');td.textContent=x;tr.append(td);});return tr;}));}
    handleEvents(d.eventos||[],v.server_time);
  }
  renderLights(v);
}
function renderParo(v){
  // Bandera roja: el teléfono solo la muestra (sin botones). Se ve aunque este piloto no esté en la parte que corre.
  const s=v.sesion;
  if(!s||!s.paro||v.estado==='sin_piloto'||v.estado==='sin_sesion'){PeluParo.hide();return;}
  const frozen=s.fuente==='gp'&&!s.target_laps?(s.remaining_ms??s.elapsed_ms):s.elapsed_ms;
  PeluParo.render({readOnly:true,red:true,resuming:!!s.paro.reanudando,n:s.paro.n,frozenMs:frozen,label:s.titulo+(s.etapa?' · '+s.etapa:''),kind:s.paro.tipo||'red',by:s.paro.pidio||null,used:s.paro.usadas??null,max:s.paro.max??null});
}
function renderLights(v){
  const s=v.sesion;renderParo(v);
  if(v.estado!=='en_sesion'||!s){PeluLights.hide();return;}
  if(s.fase==='countdown'){
    PeluLights.render('countdown',s.countdown_ms,(s.countdown_total||3)*1000,s.semaforo_label||'');
    const dl=Date.now()+(s.countdown_ms||0);
    if(s.countdown_ms>300&&(soundDeadline===null||Math.abs(dl-soundDeadline)>1500)){
      const lead=PeluLights.soundLead(s.countdown_ms);if(lead>=0)setTimeout(()=>play('semaforo'),lead*1000);else play('semaforo',-lead);
    }
    soundDeadline=dl;
  }else PeluLights.render(s.fase);
}
PeluLights.onDeadline=()=>schedule(0);
function handleEvents(evs,now){
  const max=evs.length?evs[evs.length-1].id:0;
  if(lastEventId===null){lastEventId=max;return;}
  evs.filter(e=>e.id>lastEventId).forEach(e=>{if(now&&e.at&&now-e.at>4)return;
    if(e.type==='false_start'||e.type==='dsq')play('abucheo');else if(e.type==='best')play('aplausos');else if(e.type==='winner'||e.type==='finish')play('bandera_final');});
  lastEventId=Math.max(lastEventId,max);
}

/* ---------- conexión con la Mac ---------- */
function online(){
  setText($('connection'),'● En vivo');$('connection').className='chip ok';
  $('offline').hidden=true;document.body.classList.remove('mc-stale');
}
function offline(n){
  if(n<3)return;
  setText($('connection'),PeluAvisos.offlineText(n));$('connection').className='chip bad';
  setText($('offlineTitle'),'No hay conexión con la Mac');setText($('offlineText'),PeluAvisos.RED+' Esta pantalla se reconecta sola; no tienes que recargar.');
  $('offline').hidden=false;document.body.classList.add('mc-stale');PeluLights.hide();PeluParo.hide();
}
function stale(v){
  // Respuesta vieja que llegó tarde (mismo arranque del servidor, misma sesión, versión menor): se ignora.
  const a=state?.sesion,b=v.sesion;
  return !!(a&&b&&state.boot===v.boot&&a.fuente===b.fuente&&a.id===b.id&&(b.version<a.version||(b.control??0)<(a.control??0)));
}
function apply(v){
  PeluAvisos.show(v.boot,v.avisos);
  if(PeluAvisos.restarted(v.boot)){toast('El servidor de la Mac se reinició. Ya está conectado otra vez.');state=null;soundDeadline=null;lastEventId=null;}
  if(v.estado==='sin_piloto'){saveChoice(null);setUrl(null);loadRoster().then(()=>renderChooser('Tu piloto ya no está en el registro. Elige otra vez.'));return;}
  if(stale(v))return;
  state=v;show('car');render(v);
}
function schedule(delay=400){if(timer!==null)clearTimeout(timer);timer=setTimeout(()=>{timer=null;poll();},delay);}
async function poll(){
  if(screen!=='car'||!choice){return;}
  if(polling)return;polling=true;started=performance.now();
  const c=new AbortController();ctrl=c;const to=setTimeout(()=>c.abort(),2500);
  try{
    const r=await fetch('/api/micoche?slot='+choice.slot+'&ts='+Date.now(),{cache:'no-store',signal:c.signal});
    if(!r.ok)throw Error('HTTP '+r.status);
    const v=await r.json();if(!v||!('estado' in v))throw Error('Respuesta incompleta');
    fails=0;online();
    try{apply(v);}catch(e){console.error('[mi coche] error de pantalla; sigue el sondeo',e);}
  }catch(e){fails++;offline(fails);}
  finally{
    clearTimeout(to);polling=false;ctrl=null;lastFinish=performance.now();
    if(screen==='car')schedule(document.hidden?1500:state?.sesion?.fase==='countdown'?150:400);
  }
}
// Vigilante: si un sondeo se atora (Mac dormida, Wi-Fi que se cae), se aborta y se vuelve a pedir.
setInterval(()=>{
  const now=performance.now();
  if(screen==='car'){
    if(polling&&now-started>4000){ctrl&&ctrl.abort();polling=false;schedule(0);}
    else if(!polling&&timer===null&&now-lastFinish>1200)schedule(0);
  }
},1000);
function wakeUp(){if(document.hidden)return;keepAwake();if(screen==='car'&&!polling)schedule(0);if(screen!=='car'&&!roster)boot();}
document.addEventListener('visibilitychange',wakeUp);window.addEventListener('pageshow',wakeUp);window.addEventListener('focus',wakeUp);
window.addEventListener('online',wakeUp);

/* ---------- arranque ---------- */
async function loadRoster(){
  const r=await fetch('/api/roster',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);roster=await r.json();rosterFails=0;return roster;
}
let booting=false;
async function boot(){
  if(booting)return;booting=true;
  try{await loadRoster();online();}
  catch(e){rosterFails++;offline(rosterFails+2);booting=false;setTimeout(boot,2000);return;}
  booting=false;
  const r=resolve();
  if(r.ok){setUrl(choice);show('car');renderWaiting('Conectando…','Buscando tu coche en la sesión.');schedule(0);keepAwake();}
  else renderChooser(r.note);
}
// Registro: se refresca de vez en cuando (avatar nuevo, piloto agregado) mientras se elige.
setInterval(async()=>{if(screen==='choose'){try{await loadRoster();online();renderChooser($('chooseNote').hidden?null:$('chooseNote').textContent);}catch(e){rosterFails++;offline(rosterFails+2);}}},3000);
boot();
window.MI_COCHE={get state(){return state;},get choice(){return choice;},get screen(){return screen;}};
})();
