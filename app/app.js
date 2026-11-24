'use strict';
const $=id=>document.getElementById(id);
let rosterFails=0,roster=null,slot=null,expected=null,photo=null,existing=null,photoChanged=false,lastVersion=-1,polling=false,saving=false,photoJob=0,previousFocus=null;
const canvas=$('avatar'),ctx=canvas.getContext('2d');
function notify(text){$('toast').textContent=text;$('toast').style.display='block';clearTimeout(notify.timer);notify.timer=setTimeout(()=>$('toast').style.display='none',4200);}
function element(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function avatarSrc(path){return path+(path.includes('?')?'&':'?')+'v=mica2';}
function render(){
  const board=$('board');board.replaceChildren();
  const count=roster.slots.filter(Boolean).length;$('count').textContent=count+' de 6 pilotos';
  roster.slots.forEach((pilot,i)=>{
    const card=element('article','pilot'+(pilot?'':' empty'));card.style.setProperty('--team',roster.colors[i].hex);
    const top=element('div','card-top');top.append(element('span','team','Equipo '+roster.colors[i].name),element('span','slot-number',String(i+1).padStart(2,'0')));card.append(top);
    if(pilot){const img=element('img','portrait');img.src=avatarSrc(pilot.avatar);img.alt='Avatar de piloto: '+pilot.name;card.append(img);}
    else{const art=element('div','empty-art');art.append(element('strong','','+'),element('span','','Tu lugar en la parrilla'));card.append(art);}
    const bottom=element('div','card-bottom'),btn=element('button','',pilot?'Editar':'Agregar');btn.type='button';btn.addEventListener('click',()=>openEditor(i));
    bottom.append(element('h2','',pilot?pilot.name:'Lugar libre'),btn);card.append(bottom);
    if(pilot)card.append(nivelBox(pilot,i));
    board.append(card);
  });
  syncMenuRoster();
}
// Nivel del piloto (Novato / Intermedio / Experto) y «Nivel sugerido» por sus tiempos (ver handicap.py).
function nivelBox(p,i){
  const nv=p.nivel||'intermedio',box=element('div','nivel-box');
  box.append(element('span','nivel-chip nv-'+nv,PeluHandicap.NIVEL_ICON[nv]+' '+PeluHandicap.nivelTxt(nv)));
  const sg=p.sugerido,ch=p.nivel_cambio;
  if(sg&&sg.nivel!==nv){const s=element('div','nivel-sug');s.append(element('span','','Nivel sugerido: '),element('b','',PeluHandicap.NIVEL_ICON[sg.nivel]+' '+PeluHandicap.nivelTxt(sg.nivel)),element('small','',PeluHandicap.sugTxt(sg).replace(/^[^·]+· /,'')));
    const ok=element('button','primary small','Aceptar');ok.type='button';ok.addEventListener('click',()=>setNivel(i,sg.nivel));
    const no=element('button','small','✕');no.type='button';no.setAttribute('aria-label','Descartar sugerencia');no.addEventListener('click',()=>setNivel(i,null));
    s.append(ok,no);box.append(s);}
  else if(ch){const s=element('div','nivel-sug cambio');s.append(element('span','','Cambió solo: '+PeluHandicap.nivelTxt(ch.de)+' → '),element('b','',PeluHandicap.nivelTxt(ch.nivel)),element('small','',PeluHandicap.sugTxt(ch).replace(/^[^·]+· /,'')));
    const no=element('button','small','OK');no.type='button';no.addEventListener('click',()=>setNivel(i,null));s.append(no);box.append(s);}
  return box;
}
async function setNivel(i,nivel){
  try{const r=await fetch('/api/slot',{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify(nivel?{slot:i,action:'nivel',nivel}:{slot:i,action:'nivel_descartar'})});
    const d=await r.json();if(!r.ok)throw Error(d.error||'No se pudo guardar.');await poll();if(nivel)notify('Nivel guardado: '+PeluHandicap.nivelTxt(nivel)+'.');}
  catch(e){notify(e.message||'No hay conexión con la Mac.');}
}
let editNivel='intermedio';
function renderNivelPick(){const b=$('nivelPick');if(!b)return;b.replaceChildren(PeluHandicap.nivelPicker(editNivel,k=>{editNivel=k;renderNivelPick();if(existing||photo)$('save').disabled=false;}));}
async function poll(){
  if(polling)return;polling=true;
  try{
    const r=await fetch('/api/roster',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const data=await r.json();
    rosterFails=0;$('connection').textContent='● Compartido en vivo';$('connection').className='chip connection live ok';roster=data;
    if(lastVersion!==data.version){try{render();lastVersion=data.version;}catch(e){reportRenderError(e);}}
  }catch(e){rosterFails++;$('connection').textContent=PeluAvisos.offlineText(rosterFails);$('connection').className='chip connection offline bad';}
  finally{polling=false;}
}
function rounded(x,y,w,h,r){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
function drawVisorMica(){
  const prev=ctx.globalCompositeOperation;
  ctx.globalCompositeOperation='multiply';
  const smoke=ctx.createLinearGradient(121,170,121,420);
  smoke.addColorStop(0,'rgba(72,118,168,0.62)');
  smoke.addColorStop(0.38,'rgba(28,62,108,0.76)');
  smoke.addColorStop(1,'rgba(8,22,48,0.88)');
  ctx.fillStyle=smoke;
  ctx.fillRect(121,170,358,250);
  ctx.globalCompositeOperation='screen';
  const glare=ctx.createLinearGradient(130,175,400,410);
  glare.addColorStop(0,'rgba(180,215,255,0.28)');
  glare.addColorStop(0.16,'rgba(140,190,240,0.12)');
  glare.addColorStop(0.45,'rgba(0,0,0,0)');
  ctx.fillStyle=glare;
  ctx.beginPath();
  ctx.moveTo(125,172);
  ctx.lineTo(300,172);
  ctx.quadraticCurveTo(235,260,175,418);
  ctx.lineTo(125,418);
  ctx.closePath();
  ctx.fill();
  ctx.globalCompositeOperation='source-over';
  const sheen=ctx.createLinearGradient(121,170,479,420);
  sheen.addColorStop(0,'rgba(255,255,255,0.10)');
  sheen.addColorStop(0.35,'rgba(90,140,190,0.06)');
  sheen.addColorStop(1,'rgba(0,8,24,0.18)');
  ctx.fillStyle=sheen;
  ctx.fillRect(121,170,358,250);
  ctx.globalCompositeOperation=prev;
}
function drawAvatar(){
  const color=roster?roster.colors[slot??0].hex:'#edf2f7';
  ctx.clearRect(0,0,600,720);const bg=ctx.createLinearGradient(0,0,600,720);bg.addColorStop(0,'#26313f');bg.addColorStop(1,'#080b10');ctx.fillStyle=bg;ctx.fillRect(0,0,600,720);
  ctx.save();ctx.globalAlpha=.1;ctx.strokeStyle=color;ctx.lineWidth=24;for(let x=-720;x<700;x+=100){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x+720,720);ctx.stroke();}ctx.restore();
  // Traje y hombros.
  ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(42,720);ctx.lineTo(66,575);ctx.quadraticCurveTo(80,535,222,509);ctx.lineTo(378,509);ctx.quadraticCurveTo(520,535,534,575);ctx.lineTo(558,720);ctx.closePath();ctx.fill();
  ctx.fillStyle='#19212d';ctx.beginPath();ctx.moveTo(228,510);ctx.lineTo(300,565);ctx.lineTo(372,510);ctx.lineTo(340,720);ctx.lineTo(260,720);ctx.fill();
  ctx.strokeStyle='#ffffff80';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(155,552);ctx.lineTo(135,720);ctx.moveTo(445,552);ctx.lineTo(465,720);ctx.stroke();ctx.strokeStyle='#ffffff55';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(300,571);ctx.lineTo(300,720);ctx.stroke();
  ctx.fillStyle='#10151e';rounded(108,590,103,35,5);ctx.fill();ctx.fillStyle='#f5f7fa';ctx.font='bold 16px system-ui';ctx.textAlign='center';ctx.fillText('SLOTRACE',160,613);
  // Casco con visor que conserva el rostro de la foto.
  ctx.fillStyle='#06090d';ctx.beginPath();ctx.ellipse(300,304,214,246,0,0,Math.PI*2);ctx.fill();
  const shell=ctx.createLinearGradient(100,100,480,480);shell.addColorStop(0,'#ffffff');shell.addColorStop(.12,color);shell.addColorStop(1,color);ctx.fillStyle=shell;ctx.beginPath();ctx.ellipse(300,291,200,231,0,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#141b25';rounded(106,153,388,284,75);ctx.fill();
  ctx.save();rounded(121,170,358,250,62);ctx.clip();
  if(photo){
    const zoom=Number($('zoom').value), scale=Math.max(358/photo.width,250/photo.height)*zoom;
    const w=photo.width*scale,h=photo.height*scale;
    ctx.drawImage(photo,300-w/2+Number($('horizontal').value),295-h/2+Number($('vertical').value),w,h);
  }else{ctx.fillStyle='#26313f';ctx.fillRect(121,170,358,250);ctx.fillStyle='#aab4c2';ctx.font='22px system-ui';ctx.textAlign='center';ctx.fillText('Tu rostro aquí',300,300);}
  drawVisorMica();
  ctx.restore();ctx.strokeStyle='#ffffff75';ctx.lineWidth=4;rounded(121,170,358,250,62);ctx.stroke();
  ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(125,398);ctx.quadraticCurveTo(300,456,475,398);ctx.lineTo(444,478);ctx.quadraticCurveTo(300,565,156,478);ctx.closePath();ctx.fill();
  ctx.fillStyle='#131a24';rounded(238,464,124,23,10);ctx.fill();ctx.fillStyle='#ffffff65';ctx.fillRect(286,81,28,65);ctx.fillStyle='#111822';ctx.font='900 25px system-ui';ctx.textAlign='center';ctx.fillText(String((slot??0)+1).padStart(2,'0'),300,132);
  ctx.fillStyle='#10151ee8';ctx.fillRect(0,657,600,63);ctx.fillStyle='#f5f7fa';ctx.font='900 28px system-ui';ctx.textAlign='center';ctx.fillText('PILOTO / '+String((slot??0)+1).padStart(2,'0'),300,699,550);
}
function preview(){if(existing&&!photoChanged){ctx.clearRect(0,0,600,720);ctx.drawImage(existing,0,0,600,720);}else drawAvatar();}
async function loadImage(url){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(Error('No se pudo abrir la foto. Prueba con una imagen JPEG o PNG.'));im.src=url;});}
async function choosePhoto(event){
  const file=event.target.files[0];if(!file)return;
  const job=++photoJob;$('error').textContent='';$('save').disabled=true;
  let url;
  try{if(file.size>25*1024*1024)throw Error('La foto pesa más de 25 MB. Elige una más pequeña.');
    url=URL.createObjectURL(file);const image=await loadImage(url);if(job!==photoJob||slot===null)return;
    // Limitar memoria y quitar metadatos antes de componer.
    const resized=document.createElement('canvas'),factor=Math.min(1,1600/Math.max(image.width,image.height));resized.width=Math.round(image.width*factor);resized.height=Math.round(image.height*factor);resized.getContext('2d').drawImage(image,0,0,resized.width,resized.height);
    photo=resized;photoChanged=true;existing=null;$('zoom').value='1';$('vertical').value='0';$('horizontal').value='0';$('adjustments').hidden=false;preview();
  }catch(e){$('error').textContent=e.message;}
  finally{if(url)URL.revokeObjectURL(url);if(job===photoJob)$('save').disabled=false;event.target.value='';}
}
async function openEditor(i){
  if(!roster)return;const pilot=roster.slots[i];previousFocus=document.activeElement;slot=i;expected=pilot?pilot.revision:null;photo=null;existing=null;photoChanged=false;const job=++photoJob;
  editNivel=pilot&&pilot.nivel||'intermedio';renderNivelPick();
  $('name').value=pilot?pilot.name:'';$('error').textContent='';$('zoom').value='1';$('vertical').value='0';$('horizontal').value='0';$('adjustments').hidden=true;$('remove').hidden=!pilot;
  $('modalTitle').textContent=pilot?'Editar piloto':'Agregar piloto';$('teamLabel').textContent='Lugar '+(i+1)+' · Equipo '+roster.colors[i].name;$('overlay').style.setProperty('--team',roster.colors[i].hex);$('overlay').hidden=false;document.body.classList.add('modal-open');$('save').disabled=!!pilot;drawAvatar();$('name').focus();
  if(pilot){try{const im=await loadImage(avatarSrc(pilot.avatar));if(job!==photoJob)return;existing=im;preview();}catch(e){$('error').textContent='No se pudo cargar el avatar. Elige otra foto.';}finally{if(job===photoJob)$('save').disabled=false;}}
}
function closeEditor(){if(saving)return;slot=null;photo=null;existing=null;photoJob++;$('overlay').hidden=true;document.body.classList.remove('modal-open');if(previousFocus&&previousFocus.isConnected)previousFocus.focus();else $('add').focus();}
async function mutate(action){
  if(saving)return;if(action==='save'&&!existing&&!photo){$('error').textContent='Toma una selfie o elige una foto del rostro.';return;}
  saving=true;$('save').disabled=true;$('remove').disabled=true;$('error').textContent='';
  try{const body={slot,expectedRevision:expected,action};
    if(action==='save'){body.name=$('name').value.trim();body.nivel=editNivel;if(photoChanged){drawAvatar();body.image=canvas.toDataURL('image/png');}}
    const response=await fetch('/api/slot',{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.error||'No se pudo guardar.');
    saving=false;closeEditor();await poll();notify(action==='remove'?'Piloto eliminado. Lugar disponible.':'Piloto guardado. Ya se ve en la parrilla.');
  }catch(e){$('error').textContent=e.message||'No hay conexión con la Mac. Intenta otra vez.';}
  finally{saving=false;$('save').disabled=false;$('remove').disabled=false;}
}
$('camera').addEventListener('change',choosePhoto);$('library').addEventListener('change',choosePhoto);
['zoom','vertical','horizontal'].forEach(id=>$(id).addEventListener('input',preview));
$('name').addEventListener('input',()=>{if(photoChanged||!existing)preview();});
$('form').addEventListener('submit',e=>{e.preventDefault();mutate('save');});
$('remove').addEventListener('click',()=>{if(confirm('¿Quitar a este piloto y su avatar de la parrilla?'))mutate('remove');});
$('close').addEventListener('click',closeEditor);$('cancel').addEventListener('click',closeEditor);
$('add').addEventListener('click',()=>{if(!roster){notify('Espera la conexión con la Mac.');return;}const i=roster.slots.findIndex(p=>!p);if(i<0){notify('Máximo 6 competidores. Edita o quita uno para liberar un lugar.');return;}openEditor(i);});
document.addEventListener('keydown',e=>{if($('overlay').hidden)return;if(e.key==='Escape')closeEditor();if(e.key==='Tab'){const nodes=[...$('form').querySelectorAll('button,input')].filter(n=>!n.disabled&&n.getClientRects().length&&!n.classList.contains('file'));const first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
poll();setInterval(poll,1000);
// 🏎️ Garage: coches en pista por mando (se refresca solo; al cambiar, se redibujan los selectores).
PeluGarage.onChange(()=>{renderLapConfig(true);if(screen==='choose')renderParticipants();});PeluGarage.start(5000);

// El registro sigue en el servidor; solo las preferencias del menú son locales.
const MODES={ultimo:{title:'Puto el último',rule:'el que quede último es el puto.',icon:'⚑'},chelas:{title:'El último paga las chelas',rule:'el último invita las chelas.',icon:'🍻'}};
function readPreference(key,fallback){try{return localStorage.getItem(key)||fallback;}catch(e){return fallback;}}
function savePreference(key,value){try{localStorage.setItem(key,value);}catch(e){}}
let selectedMode=readPreference('pelu-mode','ultimo');if(!MODES[selectedMode])selectedMode='ultimo';
let sessionType='race',screen='home',selectedPilots=new Set(),activeSession=null,lightTimer=null,lightStep=0,selectionInitialized=false;
const screens=['home','roster','choose','session'];
function showScreen(next){
  if(lightTimer!==null){clearTimeout(lightTimer);lightTimer=null;}
  screen=next;screens.forEach(name=>$(name+'Screen').hidden=name!==next);
  if(next!=='session'&&window.PeluLights)PeluLights.hide();
  if(next!=='session'&&window.PeluParo)PeluParo.hide();
  $('pageEyebrow').textContent=next==='roster'?'SLOTRACE / PILOTOS Y AVATARES':next==='session'&&activeSession?.type==='practice'?'SLOTRACE / SESIÓN LIBRE':(next==='session'||next==='lights')&&activeSession?.type==='race'?'SLOTRACE / CARRERA':'SLOTRACE / ELIGE TU RETO';
  $('pageTitle').textContent=next==='session'&&activeSession?.type==='practice'?'Práctica':'Puto el último';
  $('pageSubtitle').textContent=next==='roster'?'Seis lugares. Cada piloto con su propio estilo.':next==='session'&&activeSession?.type==='practice'?'Encuentra tu ritmo. Sin presión.':'Arma la parrilla. Escoge el modo. A correr.';
  document.body.classList.remove('theme-trash','theme-beer','theme-practice');
  if(next==='session'&&activeSession)document.body.classList.add(activeSession.type==='practice'?'theme-practice':activeSession.mode==='chelas'?'theme-beer':'theme-trash');
  else if(next==='lights')document.body.classList.add((activeSession?.mode||selectedMode)==='chelas'?'theme-beer':'theme-trash');
  window.scrollTo(0,0);
}
function syncMode(){
  document.querySelectorAll('input[name="gameMode"]').forEach(r=>{r.checked=r.value===selectedMode;r.closest('.mode-option').classList.toggle('selected',r.checked);});
}
function syncMenuRoster(){
  $('menuPilotCount').textContent=roster.slots.filter(Boolean).length+'/6';
  if(screen==='choose')renderParticipants();
  if(screen==='home'&&liveState?.session&&liveState.session.phase!=='ended'&&dismissedSessionId!==liveState.session.id)showLiveSession();
  if(screen==='session')renderSession();
  renderLapConfig();
}
function chooseSession(type){
  if(liveState?.session&&liveState.session.phase!=='ended'){dismissedSessionId=null;showLiveSession();notify('Hay una sesión en curso. Termínala antes de comenzar otra.');return;}
  if(!roster){notify('Espera la conexión con la Mac.');return;}
  sessionType=type;savePreference('pelu-session-type',type);
  if(!roster.slots.some(Boolean)){showScreen('roster');notify('Primero agrega al menos un piloto con su foto. Después vuelve al menú.');return;}
  selectedPilots=new Set(roster.slots.flatMap((p,i)=>p?[i]:[]));selectionInitialized=true;$('selectionError').textContent='';renderParticipants();showScreen('choose');
}
function updateSelectionCount(){
  $('selectionCount').textContent=selectedPilots.size+' piloto'+(selectedPilots.size===1?'':'s')+' seleccionado'+(selectedPilots.size===1?'':'s');
  $('beginSession').textContent=sessionType==='practice'?'Entrar a práctica':'Entrar a la carrera';
}
function renderParticipants(){
  if(!selectionInitialized)return;
  selectedPilots.forEach(i=>{if(!roster.slots[i])selectedPilots.delete(i);});
  $('selectionType').textContent=sessionType==='practice'?'PRÁCTICA / SESIÓN LIBRE':'CARRERA / '+MODES[selectedMode].title;
  $('selectionRule').textContent=sessionType==='practice'?'Sin castigos. Tiempos reales y mejor vuelta para encontrar tu ritmo.':MODES[selectedMode].rule;
  const target=$('participantOptions');target.replaceChildren();
  roster.slots.forEach((p,i)=>{
    if(!p)return;const label=element('label','participant-option');label.style.setProperty('--team',roster.colors[i].hex);
    const input=element('input');input.type='checkbox';input.name='pilot';input.value=String(i);input.checked=selectedPilots.has(i);input.addEventListener('change',()=>{input.checked?selectedPilots.add(i):selectedPilots.delete(i);updateSelectionCount();$('selectionError').textContent='';});
    const img=element('img');img.src=avatarSrc(p.avatar);img.alt='Avatar de '+p.name;
    const gc=PeluGarage.on(carFor(i));
    const text=element('span','participant-name');text.append(element('strong','',p.name),element('small','','Equipo '+roster.colors[i].name+' · Coche '+carFor(i)+(gc?' · 🏎️ '+gc.nombre:'')));label.append(input,img,text);
    // 🏎️ Coche del Garage para este piloto: su clase y su hándicap propio se suman solos.
    if(PeluGarage.cars().length){const gs=PeluGarage.select(carFor(i),m=>{if(m!==carFor(i))setCar(i,m);renderParticipants();},m=>{$('selectionError').textContent=m;});gs.classList.add('participant-garage');label.append(gs);}
    target.append(label);
  });
  if(!roster.slots.some(Boolean))target.append(element('p','help','No hay pilotos registrados. Agrega uno desde Administrar pilotos.'));
  updateSelectionCount();
}
function startSession(){
  const ids=[...selectedPilots].filter(i=>roster.slots[i]);
  if(!ids.length){$('selectionError').textContent='Selecciona al menos un piloto para continuar.';return;}
  $('beginSession').disabled=true;
  sendLive({action:'start',type:sessionType,mode:selectedMode,slots:ids}).then(data=>{dismissedSessionId=null;applyLive(data,true);}).catch(e=>{$('selectionError').textContent=e.message;}).finally(()=>$('beginSession').disabled=false);
}
function renderSession(){
  if(!activeSession||!roster)return;
  const s=activeSession,practice=s.type==='practice',mode=MODES[s.mode],ended=s.phase==='ended';
  const scxMode=s.lap_source==='scx',scxOn=scxMode||s.lap_source==='both';
  $('sessionTypeBadge').textContent=(practice?'PRÁCTICA':'CARRERA')+(ended?' · TERMINADA':scxMode?' · TARJETA SCX':s.lap_source==='both'?' · SCX + SENSOR IR':' · POR TURNOS');
  $('sessionEyebrow').textContent=practice?'ENCUENTRA TU RITMO':'TIEMPOS REALES / MEJOR VUELTA';
  $('sessionTitle').textContent=practice?'Práctica':mode.title;
  $('sessionRule').textContent=practice?'Calienta y disfruta la pista. Aquí no hay castigos.':mode.rule;
  $('sessionIcon').textContent=practice?'↗':mode.icon;
  $('sessionCount').textContent=s.pilots.length+' piloto'+(s.pilots.length===1?'':'s');
  const ready=s.phase==='ready',countdown=s.phase==='countdown';
  const active=s.pilots.find(p=>p.slot===s.active),pending=ready?s.pilots.find(p=>p.slot===s.pending_active):null;
  $('activeLabel').textContent=ended?'Sesión terminada':scxMode?(ready||countdown?'Todos a la línea de meta · tarjeta SCX':'Todos en pista · tarjeta SCX'):ready?(pending?'Sale: '+pending.name:'Elige quién sale primero'):active?'En pista: '+active.name:'Sin piloto activo · elige quién corre';
  // Antes del verde: tablero visible y botón Empezar. Nada cuenta hasta que se apague el semáforo.
  $('readyBar').hidden=!ready;
  $('startLights').disabled=liveRequestBusy;
  $('readyHint').textContent=scxMode||s.lap_source==='both'?'Todos los coches en la línea de meta. Al apretar Empezar se prende el semáforo; nada cuenta hasta el verde. Después, la primera pasada de cada coche es la salida.':'Elige quién sale y aprieta Empezar. Al verde, el sensor prepara la salida; el primer paso por la meta inicia el cronómetro.';
  const yellowFlag=s.red&&s.red_flag?.kind==='yellow';
  $('turnHint').textContent=s.red?(countdown?'Semáforo de reanudación: nadie acelera antes del verde. El tiempo sigue desde donde se quedó.':yellowFlag?'🟨 BANDERA AMARILLA (la pidió '+(s.red_flag.by_name||'un piloto')+'): carrera detenida. Las vueltas no cuentan hasta Reanudar en esta pantalla.':'🚩 BANDERA ROJA: carrera detenida. Las vueltas no cuentan hasta Reanudar.'):ended?'Resultados guardados en la Mac.':ready?'Aprieta Empezar para el semáforo de salida. Nada cuenta hasta el verde.':countdown?'¡Semáforo! Nadie arranca antes del verde.':scxMode?'Todos corren a la vez. La primera pasada de cada coche por la meta es la salida; las siguientes cuentan vuelta.':s.phase==='resetting'?'Preparando salida. Espera la confirmación antes de pasar el auto.':s.phase==='waiting_sensor'?'Esperando respuesta del sensor para confirmar la salida.':s.phase==='paused'?'Turno en pausa. Elige al piloto para continuar con una salida nueva.':'Un auto a la vez. Primer paso = salida; los siguientes cuentan vueltas.';
  $('liveNotice').textContent=s.notice||'';
  $('activeForm').hidden=ended||scxMode;$('endSession').hidden=ended;
  const controlKey=s.id+':'+s.control;
  if(activeControlKey!==controlKey){
    activeControlKey=controlKey;const select=$('activePilot');select.replaceChildren();
    const empty=element('option','','Elige un piloto…');empty.value='';select.append(empty);
    s.pilots.forEach(p=>{const o=element('option','',p.name);o.value=String(p.slot);select.append(o);});
    const shown=ready?s.pending_active:s.active;select.value=shown===null||shown===undefined?'':String(shown);
  }
  $('applyActive').textContent=s.phase==='resetting'?'Preparando…':ready?'Elegir para la salida':active?'Iniciar turno / cambiar':'Poner en pista';
  $('applyActive').disabled=liveRequestBusy||s.phase==='resetting'||countdown||!!s.red;
  $('activePilot').disabled=liveRequestBusy||s.phase==='resetting'||countdown||!!s.red;
  // Handicap: posiciones y «el último» con mejor vuelta + segundos de la clase de su coche (h_s lo manda la Mac).
  const hon=!!s.handicap?.on,rawBest=p=>p.laps.length?Math.min(...p.laps.map(l=>l.s)):null;
  const best=p=>{const b=rawBest(p);return b==null?null:hon?PeluHandicap.adj(b,p.h_s):b;};
  // Bandera amarilla del piloto: los DESCALIFICADOS van al final, sin posición; en Carrera el descalificado es «el último».
  const dsqs=s.pilots.filter(p=>p.dsq),flagCfg=Object.assign({enabled:true,max:4},s.bandera_cfg||{});
  const timed=s.pilots.filter(p=>p.laps.length&&!p.dsq),worst=timed.length?Math.max(...timed.map(best)):null;
  const worstCount=dsqs.length||timed.filter(p=>best(p)===worst).length;
  const pilots=s.pilots.slice().sort((a,b)=>(!!a.dsq-!!b.dsq)||(best(a)??Infinity)-(best(b)??Infinity)||a.slot-b.slot);
  const board=$('sessionBoard'),dash=dashConfig(),scx=liveState?.scx;
  if(board.dataset.sessionId!==s.id){board.replaceChildren();sessionGauges.clear();board.dataset.sessionId=s.id;}
  board.classList.toggle('few',pilots.length<=4);
  pilots.forEach((p,index)=>{
    const team=roster.colors[p.slot],last=p.laps[p.laps.length-1],fast=best(p),rank=last&&!p.dsq?1+timed.filter(other=>best(other)<fast).length:null,isLast=!practice&&(dsqs.length?!!p.dsq:last&&fast===worst);
    let card=board.querySelector('[data-slot="'+p.slot+'"]');
    if(card&&card.dataset.hon!==String(hon)){card.remove();card=null;sessionGauges.delete(p.slot);}
    if(card&&(!sessionGauges.has(p.slot)||!['.gpos','.gname small.car-badge','.gname .pide','.gname .gflags','.track-badge','.last-badge','.dsq-badge','.pit-badge','.gcanvas','[data-stat="0"]','[data-stat="1"]','[data-stat="2"]','[data-kmh="1"]','[data-kmh="2"]','.gsus','.gpits','.gtire','details','summary','tbody'].every(selector=>card.querySelector(selector)))){card.remove();card=null;sessionGauges.delete(p.slot);}
    if(!card){
      // Misma tarjeta que el Gran Premio: casco con visor, agujas de velocidad y vida de llanta, y tiempos.
      card=element('article','gcard session-pilot');card.dataset.slot=p.slot;card.dataset.hon=String(hon);card.style.setProperty('--team',team.hex);
      const top=element('div','gtop'),pos=element('div','gpos','—');
      const img=element('img','gav');img.src=avatarSrc(p.avatar);img.alt='Avatar de '+p.name;img.addEventListener('error',()=>{img.removeAttribute('src');img.alt='';},{once:true});
      const nm=element('div','gname'),pide=element('span','pide sin','⇄');pide.setAttribute('role','status');const flags=element('span','gflags');flags.title='Banderas amarillas que pidió en esta sesión (triple clic en su botón de cambio de carril)';const hcl=element('span','hclase');hcl.hidden=true;nm.append(element('strong','',p.name),element('small','car-badge'),hcl,pide,flags);
      const labels=element('div','gbadges'),track=element('span','gbadge on track-badge','EN PISTA'),loser=element('span','gbadge bad last-badge'),dq=element('span','gbadge dsq dsq-badge','DESCALIFICADO'),pit=element('span','gbadge pits pit-badge','EN PITS');labels.append(track,loser,dq,pit);
      top.append(pos,img,nm,labels);
      const cv=element('canvas','gcanvas');
      const stats=element('div','gstats');
      ['Vueltas','Última','Mejor'].forEach((label,i)=>{const box=element('div'),value=element('strong','','—');value.dataset.stat=i;box.append(element('span','',label),value);if(i){const real=element('small','greal');real.hidden=true;real.dataset.real=i;const kmh=element('small','gkmh');kmh.hidden=true;kmh.dataset.kmh=i;box.append(real,kmh);}stats.append(box);});
      const details=element('details','lap-details');details.dataset.lapCount='0';details.append(element('summary'));const table=element('table'),head=element('thead'),hr=element('tr');(hon?['#','Tiempo','Con H','km/h','Escala']:['#','Tiempo','km/h','Escala']).forEach(v=>hr.append(element('th','',v)));head.append(hr);table.append(head,element('tbody'));details.append(table);
      const sus=element('p','gsus');sus.hidden=true;sus.setAttribute('role','note');
      const gpits=element('p','gpits');gpits.hidden=true;gpits.setAttribute('role','status');
      const gtire=element('div','gtire');gtire.setAttribute('role','status');
      card.append(top,cv,stats,gtire,gpits,sus,details);board.append(card);sessionGauges.set(p.slot,new PeluGauges.Gauge(cv));
    }
    const onTrack=!ended&&(scxMode?s.phase==='running':p.slot===s.active);
    card.classList.toggle('last-position',!!isLast);card.classList.toggle('on-track',p.slot===s.active&&!ended);card.classList.toggle('active',onTrack);
    const position=card.querySelector('.gpos'),posText=p.dsq?'DSQ':rank?'P'+rank:'—';if(position.textContent!==posText)position.textContent=posText;position.title=p.dsq?'Descalificado':rank?'Posición '+rank:'Sin posición';
    card.classList.toggle('dsq',!!p.dsq);card.querySelector('.dsq-badge').hidden=!p.dsq;
    const fl=card.querySelector('.gname .gflags'),used=p.banderas||0,flText=flagsText(used,p.dsq,flagCfg);fl.hidden=!flText;if(fl.textContent!==flText)fl.textContent=flText;
    fl.classList.toggle('dsq',!!p.dsq);fl.classList.toggle('full',!p.dsq&&used>=flagCfg.max);
    const car=carFor(p.slot),sub=card.querySelector('.gname small'),subText=(scxOn?'Coche '+car+' · '+team.name:'Equipo '+team.name)+(p.coche_nombre?' · 🏎️ '+p.coche_nombre:'');if(sub.textContent!==subText)sub.textContent=subText;
    card.querySelector('.track-badge').hidden=p.slot!==s.active||ended;
    const loser=card.querySelector('.last-badge');loser.hidden=!isLast;
    const loserText=(s.mode==='chelas'?'Invita las chelas':'El último')+(worstCount>1?' · empate':'');if(loser.textContent!==loserText)loser.textContent=loserText;
    // Agujas: la Pit Box no da velocidad instantánea; la aguja se queda en la velocidad a escala de la última vuelta.
    const kmh=last&&Number.isFinite(Number(last.escala))?Number(last.escala):null;
    const rawFuel=scx?.connected?scx.fuel?.[car-1]:null,fuel=dash.fuel_enabled&&Number.isFinite(rawFuel)?rawFuel:null;
    // Con la tarjeta SCX la aguja sigue el GATILLO en vivo (gatillo.js, calibrado con cada vuelta real); sin datos, la última vuelta.
    const gauge=sessionGauges.get(p.slot);gauge.car=!ended&&(scxMode||p.slot===s.active)?car:null;
    gauge.set(kmh,fuel,dash.speed_max_kmh,PeluGauges.tireRed(dash));
    const pideEl=card.querySelector('.gname .pide'),pc=String(car);if(pideEl.dataset.car!==pc){if(pc)pideEl.dataset.car=pc;else delete pideEl.dataset.car;pideEl.classList.add('sin');}
    const lapsCell=card.querySelector('[data-stat="0"]');if(lapsCell.textContent!==String(p.laps.length))lapsCell.textContent=p.laps.length;
    // Con handicap: tiempo ajustado con «H» y el real abajo. La velocidad promedio siempre es con el tiempo real.
    const rb=rawBest(p);
    PeluHandicap.setTime(card.querySelector('[data-stat="1"]'),last?last.s:null,p.h_s,hon,card.querySelector('[data-real="1"]'));
    PeluHandicap.setTime(card.querySelector('[data-stat="2"]'),rb,p.h_s,hon,card.querySelector('[data-real="2"]'));
    const hcl=card.querySelector('.hclase'),hct=hon&&p.clase?PeluHandicap.detalle(p):'';hcl.hidden=!hct;if(hcl.textContent!==hct)hcl.textContent=hct;
    PeluGauges.fillAvgKmh(card.querySelector('[data-kmh="1"]'),last&&last.s,dash);
    PeluGauges.fillAvgKmh(card.querySelector('[data-kmh="2"]'),rb,dash);
    // Vueltas sospechosas (más cortas que la vuelta mínima): no cuentan; se ven aquí para revisarlas.
    const pits=p.pits||{},pitBadge=card.querySelector('.pit-badge');
    const inPits=!!pits.en_pits&&!ended;card.classList.toggle('en-pits',inPits);
    // Vida de llanta (= nivel de la Pit Box en %) con vueltas y km del juego actual; en rojo: CAMBIA LLANTAS / ENTRA A PITS.
    PeluGauges.fillTire(card.querySelector('.gtire'),fuel,dash,{pits,inPits,finished:ended,off:!dash.fuel_enabled});
    pitBadge.hidden=!inPits;if(inPits){const pt='EN PITS · '+pitElapsed(pits).toFixed(1)+' s';if(pitBadge.textContent!==pt)pitBadge.textContent=pt;}
    const pitBox=card.querySelector('.gpits'),pitText=pitLine(pits);
    pitBox.hidden=!pitText;if(pitBox.textContent!==pitText)pitBox.textContent=pitText;
    const susBox=card.querySelector('.gsus'),susText=suspiciousText(p.sospechosas,p.sospechosas_n,s.min_lap_s??lapConfig?.min_lap_s);
    susBox.hidden=!susText;if(susBox.textContent!==susText)susBox.textContent=susText;
    const susTitle=suspiciousTitle(p.sospechosas);if(susBox.title!==susTitle)susBox.title=susTitle;
    const details=card.querySelector('details');details.hidden=!p.laps.length;
    if(Number(details.dataset.lapCount)!==p.laps.length){
      const tb=details.querySelector('tbody');p.laps.slice(Number(details.dataset.lapCount)).forEach(l=>{const row=element('tr');(hon?[l.n,l.s.toFixed(2)+' s',PeluHandicap.adj(l.s,p.h_s).toFixed(2)+' s H',Number(l.kmh).toFixed(1),Math.round(l.escala)]:[l.n,l.s.toFixed(2)+' s',Number(l.kmh).toFixed(1),Math.round(l.escala)]).forEach(v=>row.append(element('td','',v)));tb.insertBefore(row,tb.firstChild);});details.dataset.lapCount=p.laps.length;details.querySelector('summary').textContent='Ver vueltas ('+p.laps.length+')';
    }
    if(board.children[index]!==card)board.insertBefore(card,board.children[index]||null);
  });
  $('sessionTotal').textContent=s.pilots.reduce((total,p)=>total+p.laps.length,0)+' vueltas registradas'+(scxMode?' · tarjeta SCX':' · 40 por turno');
  const hcText=hon?' · con handicap (H = mejor vuelta + ajuste: '+s.handicap.resumen+')':'';
  $('sessionInfoRule').textContent=(scxMode?'Clasificación por mejor vuelta · todos a la vez con la Pit Box.':'Clasificación por mejor vuelta · carreras por turnos.')+hcText;$('sessionNote').textContent=scxMode?'Solo tienen posición los pilotos con vueltas completadas. La tarjeta SCX reconoce cada coche por su número de mando.':'Solo tienen posición los pilotos con vueltas completadas. Un solo sensor: elige al piloto antes de que corra.';
}
// Bandera amarilla del piloto: «🟨 2/4» en su tarjeta; «DSQ» si ya lo descalificaron. Vacío si la función está apagada y no usó ninguna.
function flagsText(used,dsq,cfg){if(dsq)return '⛔ DSQ';if(!cfg.enabled&&!used)return '';return '🟨 '+(used||0)+'/'+cfg.max;}
function fmtPit(s){if(s==null||!Number.isFinite(Number(s)))return '—';return Number(s).toFixed(1)+' s';}
function pitElapsed(pits){
  if(!pits||!pits.en_pits)return null;
  if(pits.entry_at)return Math.max(0,(Date.now()/1000)-pits.entry_at);
  return Number(pits.elapsed_s)||0;
}
function pitLine(pits){
  if(!pits)return '';
  if(pits.en_pits){
    const t=pitElapsed(pits),n=pits.completadas||0;
    return '🔧 CAMBIO DE LLANTAS · '+t.toFixed(1)+' s'+(n?(' · '+n+' cambio'+(n===1?'':'s')+' antes'):'');
  }
  const n=pits.completadas||0;if(!n)return '';
  return 'Cambios de llantas: '+n+' · último '+fmtPit(pits.ultima_s)+' · total en pits '+fmtPit(pits.total_s);
}
// «⚠ 2 vueltas sospechosas (<10 s): 3.21 s · 4.50 s · no cuentan» (también lo usa la prueba de navegador).
function fmtMin(m){const n=Number(m);return Number.isFinite(n)?String(Math.round(n*100)/100):'10';}
function suspiciousText(list,total,min){
  list=list||[];const n=Number.isInteger(total)&&total>=list.length?total:list.length;if(!n)return '';
  const times=list.slice(-6).reverse().map(x=>Number(x.s).toFixed(2)+' s');
  return '⚠ '+n+' vuelta'+(n===1?'':'s')+' sospechosa'+(n===1?'':'s')+' (<'+fmtMin(min)+' s): '+times.join(' · ')+(n>times.length?' · …':'')+' · no cuenta'+(n===1?'':'n');
}
function suspiciousTitle(list){
  const src={scx:'Pit Box',ir:'sensor IR','scx-sim':'simulada'};
  return (list||[]).slice(-20).reverse().map(x=>Number(x.s).toFixed(2)+' s · '+(x.hora?new Date(x.hora*1000).toLocaleTimeString('es-MX'):'')+' · '+(src[x.src]||x.src||'')+(x.car?' · coche '+x.car:'')).join('\n');
}
document.querySelectorAll('input[name="gameMode"]').forEach(r=>r.addEventListener('change',()=>{if(r.checked){selectedMode=r.value;savePreference('pelu-mode',selectedMode);syncMode();}}));
document.querySelectorAll('.back-menu').forEach(b=>b.addEventListener('click',()=>{dismissedSessionId=liveState?.session?.id||null;showScreen('home');}));
$('showPilots').addEventListener('click',()=>showScreen('roster'));
$('managePilots').addEventListener('click',()=>showScreen('roster'));
$('practiceAction').addEventListener('click',()=>chooseSession('practice'));
$('raceAction').addEventListener('click',()=>chooseSession('race'));
$('participantsForm').addEventListener('submit',e=>{e.preventDefault();startSession();});
syncMode();showScreen('home');

// Sesión única compartida: las lecturas y la asignación se hacen en la Mac.
let liveState=null,livePolling=false,liveSignature='',dismissedSessionId=null,activeControlKey='',liveRequestBusy=false;
let liveTimer=null,liveController=null,liveGeneration=0,liveRequestStarted=0,lastLiveFinish=performance.now(),transportFailures=0,lastMacGoodAt=performance.now(),renderErrorPending=false;
// Agujas compartidas con el Gran Premio (gauges.js). Valores del tablero = configuración del Gran Premio.
const sessionGauges=PeluGauges.watch(new Map());
const DASH_FALLBACK={speed_max_kmh:300,fuel_red_pct:25,fuel_enabled:true,track_length_m:25,scale:32,tire_name:'Media',tire_red_pct:20};
function dashConfig(){return Object.assign({},DASH_FALLBACK,liveState?.dashboard||{});}
const browserHealth={ticks:0,transportFailures:0,renderFailures:0,watchdogRestarts:0,lastError:''};
window.PELU_DIAGNOSTICS=browserHealth;
function reportRenderError(error){
  renderErrorPending=true;browserHealth.renderFailures++;browserHealth.lastError=String(error?.message||error);console.error('[tablero] Error de interfaz; el sondeo continúa',error);
  const box=$('liveError');if(box)box.textContent='No se pudo actualizar el tablero. Reintentando automáticamente…';
}

function sensorStatus(sensor){
  const box=$('sensorStatus');if(!box)return;
  // The server owns the grace window; never add another minute in the browser.
  const healthy=!!sensor&&sensor.connected===true&&!sensor.retrying;
  box.classList.toggle('connected',healthy);
  box.classList.toggle('updating',!!sensor&&sensor.connected===true&&!healthy);
  if(healthy)box.textContent='● sensor IR conectado · '+(sensor.data?.estado||'listo');
  else if(sensor?.connected===true)box.textContent='◌ sensor IR actualizando · comprobando conexión';
  else box.textContent='● sensor IR no conectado · reintentando automáticamente';
}
function noteTransportFailure(error){
  transportFailures++;browserHealth.transportFailures++;browserHealth.lastError=String(error?.message||error);
  // Sin respuesta de la Mac: no dejar "conectada" en verde con datos viejos.
  if(transportFailures>=3)['sensorStatus','scxStatus'].forEach(id=>{const box=$(id);if(!box)return;box.classList.remove('connected','updating');
    const t=id==='scxStatus'?'● tarjeta SCX: sin datos (no hay conexión con la Mac)':'● sensor IR: sin datos (no hay conexión con la Mac)';if(box.textContent!==t)box.textContent=t;});
}
async function sendLive(payload){
  const response=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify(payload)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo actualizar la sesión.');return data;
}
function showLiveSession(){
  const s=liveState?.session;if(!s||!roster)return;activeSession=s;
  if(screen!=='session')showScreen('session');
  renderSession();renderSessionLights(s);
}
// Semáforo de salida: el mismo overlay del Gran Premio (lights.js), encima del tablero de agujas.
let lightsSoundKey='';
function renderSessionLights(s){
  if(!s||screen!=='session'){PeluLights.hide();return;}
  if(s.phase==='countdown'){
    const total=(s.countdown_total||dashConfig().lights_seconds||3)*1000;
    PeluLights.render('countdown',s.countdown_ms,total,s.type==='practice'?'PRÁCTICA':'CARRERA · '+MODES[s.mode].title);
    const key=s.id+':'+s.starts_at;
    if(lightsSoundKey!==key){lightsSoundKey=key;if(s.countdown_ms>300){const lead=PeluLights.soundLead(s.countdown_ms);if(lead>=0)setTimeout(()=>playSfx('semaforo'),lead*1000);else playSfx('semaforo',-lead);}}
  }else PeluLights.render(s.phase);
  renderParo(s);
}
// Bandera roja (PARO): estado en el servidor; cualquier pantalla puede parar o reanudar.
function renderParo(s){
  if(!window.PeluParo)return;
  if(!s||screen!=='session'){PeluParo.hide();return;}
  const label=s.type==='practice'?'PRÁCTICA':'CARRERA · '+MODES[s.mode].title;
  const rf=s.red_flag||{};
  PeluParo.render({canStop:(s.phase==='running'&&!s.simulated)||s.phase==='countdown',red:!!s.red,resuming:!!s.red&&s.phase==='countdown',frozenMs:s.elapsed_ms,label,n:rf.n,
    kind:rf.kind||'red',by:rf.by_name||null,used:rf.used??null,max:rf.max??null});
  noteBanderaEvento(s);
}
// Bandera amarilla / descalificación pedida desde un mando: sonido y aviso en la pantalla grande (una vez por evento).
let banderaSeen=null;
function noteBanderaEvento(s){
  const ev=s.bandera_evento,key=s.id+':'+(ev?ev.n:0);
  if(banderaSeen===null||!banderaSeen.startsWith(s.id+':')){banderaSeen=key;return;}   // al abrir la pantalla: sin sonido por lo viejo
  if(key===banderaSeen||!ev)return;banderaSeen=key;
  if(ev.tipo==='dsq'){playSfx('abucheo');notify('⛔ '+ev.name+' queda DESCALIFICADO: pidió más banderas amarillas de las permitidas.');}
  else{playSfx('frenazo');notify('🟨 BANDERA AMARILLA · la pidió '+ev.name);}
}
if(window.PeluParo){
  PeluParo.onStop=async()=>{const s=liveState?.session;if(!s)return;applyLive(await sendLive({action:'red_flag',id:s.id}),true);};
  PeluParo.onResume=async()=>{const s=liveState?.session;if(!s)return;applyLive(await sendLive({action:'resume',id:s.id}),true);};
}
// Reloj de carrera: el servidor manda el tiempo sin paros; entre sondeos avanza aquí (congelado en PARO).
let raceClockBase=null;
function noteRaceClock(s){
  raceClockBase=s&&s.elapsed_ms!=null?{ms:s.elapsed_ms,at:performance.now(),running:!s.red&&s.phase!=='ended'&&s.phase!=='countdown'}:null;paintRaceClock();
}
function paintRaceClock(){
  const box=$('raceClock');if(!box)return;
  if(!raceClockBase||screen!=='session'){box.hidden=true;return;}
  const ms=raceClockBase.ms+(raceClockBase.running?performance.now()-raceClockBase.at:0),t=Math.floor(ms/1000);
  const text='⏱ '+Math.floor(t/60)+':'+String(t%60).padStart(2,'0')+(raceClockBase.running?'':' · detenido');
  box.hidden=false;box.classList.toggle('stopped',!raceClockBase.running);if(box.textContent!==text)box.textContent=text;
}
setInterval(paintRaceClock,250);
PeluLights.onDeadline=()=>{if(typeof scheduleLive==='function')scheduleLive(0);};
function applyLive(data,force=false){
  // Si el servidor se reinició (otro 'boot'), lo del servidor manda aunque su versión sea menor (apagón a media escritura).
  if(liveState?.session&&data.session&&liveState.boot===data.boot){const old=liveState.session,fresh=data.session;if((old.id===fresh.id&&(fresh.control<old.control||fresh.version<old.version))||(old.id!==fresh.id&&fresh.created_at<old.created_at)){sensorStatus(data.sensor);return;}}
  liveState=data;sensorStatus(data.sensor);scxStatus(data.scx);applyLapConfig(data.laps_config);
  {const d=dashConfig(),f=$('trackFooter'),t='Circuito '+d.track_length_m+' m · Escala 1:'+d.scale+' · Velocímetro a escala hasta '+d.speed_max_kmh+' km/h.';if(f&&f.textContent!==t)f.textContent=t;}
  const s=data.session;$('resumeLive').hidden=!s;$('resumeLive').textContent=s?.phase==='ended'?'Ver resultados →':'Ver sesión en curso →';
  if(!s)return;
  if(force||(s.phase!=='ended'&&dismissedSessionId!==s.id&&$('overlay').hidden&&screen!=='roster'))showLiveSession();
  else if(screen==='session'){activeSession=s;showLiveSession();}
}
function scheduleLive(delay=400){
  if(liveTimer!==null)clearTimeout(liveTimer);
  liveTimer=setTimeout(()=>{liveTimer=null;void pollLive();},delay);
}
async function pollLive(){
  if(livePolling)return;
  livePolling=true;liveRequestStarted=performance.now();browserHealth.ticks++;
  const controller=new AbortController();liveController=controller;
  const timeout=setTimeout(()=>controller.abort(),2500);
  try{
    const response=await fetch('/api/live?ts='+Date.now(),{cache:'no-store',signal:controller.signal});
    if(!response.ok)throw Error('HTTP '+response.status);
    const text=await response.text();const data=JSON.parse(text);
    if(!data||!data.sensor||typeof data.sensor!=='object'||!('session' in data))throw Error('Respuesta de sesión incompleta');
    transportFailures=0;lastMacGoodAt=performance.now();
    PeluAvisos.show(data.boot,data.avisos);if(PeluAvisos.restarted(data.boot))notify('El servidor de la Mac se reinició. Ya está conectado otra vez.');
    try{
      sensorStatus(data.sensor);scxStatus(data.scx);applyLapConfig(data.laps_config);
      // El reloj de carrera cambia en cada sondeo: no cuenta para decidir si se vuelve a pintar el tablero.
      const sig=text.replace(/"elapsed_ms": ?-?\d+/,'');
      noteRaceClock(data.session);
      if(sig!==liveSignature||renderErrorPending){applyLive(data);liveSignature=sig;}
      else if(data.session&&data.session.phase==='countdown'&&dismissedSessionId!==data.session.id)showLiveSession();
      if(renderErrorPending){const errorBox=$('liveError');if(errorBox)errorBox.textContent='';renderErrorPending=false;}
    }catch(error){reportRenderError(error);}
  }catch(error){noteTransportFailure(error);}
  finally{
    clearTimeout(timeout);
    livePolling=false;liveController=null;lastLiveFinish=performance.now();
    scheduleLive(document.hidden?1500:liveState?.session?.phase==='countdown'?150:400);
  }
}
function restartStalledLive(){
  const now=performance.now();
  if(livePolling&&now-liveRequestStarted>4000){
    liveController&&liveController.abort();liveController=null;livePolling=false;browserHealth.watchdogRestarts++;scheduleLive(0);
  }else if(!livePolling&&liveTimer===null&&now-lastLiveFinish>1200)scheduleLive(0);
}
function wakeLive(){
  if(document.hidden)return;
  restartStalledLive();if(!livePolling)scheduleLive(0);
}
$('resumeLive').addEventListener('click',()=>{dismissedSessionId=null;try{showLiveSession();}catch(e){reportRenderError(e);}});
$('activeForm').addEventListener('submit',async e=>{
  e.preventDefault();if(liveRequestBusy||!liveState?.session)return;
  liveRequestBusy=true;$('applyActive').disabled=true;$('liveError').textContent='';
  const s=liveState.session;
  try{const data=await sendLive({action:'active',id:s.id,control:s.control,slot:Number($('activePilot').value)});applyLive(data,true);}
  catch(error){$('liveError').textContent=error.message;}
  finally{liveRequestBusy=false;$('applyActive').disabled=liveState?.session?.phase==='resetting';$('activePilot').disabled=liveState?.session?.phase==='resetting';}
});
// Botón Empezar: prende el semáforo. El servidor ignora repeticiones una vez que arrancó.
$('startLights').addEventListener('click',async()=>{
  if(liveRequestBusy||!liveState?.session||liveState.session.phase!=='ready')return;
  liveRequestBusy=true;$('startLights').disabled=true;$('liveError').textContent='';const s=liveState.session;
  try{applyLive(await sendLive({action:'go',id:s.id,control:s.control}),true);}
  catch(e){$('liveError').textContent=e.message;}
  finally{liveRequestBusy=false;$('startLights').disabled=false;}
});
$('endSession').addEventListener('click',async()=>{
  if(liveRequestBusy||!liveState?.session||!confirm('¿Terminar esta sesión? Se conservarán las vueltas registradas.'))return;
  liveRequestBusy=true;$('endSession').disabled=true;const s=liveState.session;
  try{applyLive(await sendLive({action:'end',id:s.id,control:s.control}),true);}
  catch(e){$('liveError').textContent=e.message;}
  finally{liveRequestBusy=false;$('endSession').disabled=false;}
});
scheduleLive(0);setInterval(restartStalledLive,1000);
document.addEventListener('visibilitychange',wakeLive);window.addEventListener('pageshow',wakeLive);window.addEventListener('focus',wakeLive);

// Tarjeta SCX Digital: estado, fuente de vueltas y coche (mando 1-6) de cada piloto.
let lapConfig=null,lapConfigSignature='',lapConfigBusy=false;
const SOURCE_HELP={auto:'Cuenta con la Pit Box (tarjeta SCX amarilla) si está conectada al iniciar la sesión; solo si la tarjeta no está y el sensor IR sí responde, usa el sensor IR por turnos.',scx:'Todos corren a la vez; cada coche se reconoce por su número de mando.',ir:'Un solo sensor: corren por turnos, eligiendo quién está en pista.',both:'Cuenta con la tarjeta SCX; si se desconecta, sigue el sensor IR con el piloto en pista.'};
function carFor(slot){const c=lapConfig?.cars?.[slot];return Number.isInteger(c)?c:slot+1;}
function scxStatus(scx){
  const box=$('scxStatus');if(!box)return;
  if(!scx){box.textContent='Tarjeta SCX: sin información';return;}
  box.classList.toggle('connected',scx.connected===true);
  box.classList.toggle('updating',scx.status==='sin_datos');
  const c=scx.controllers||[],list=c.length>1?c.slice(0,-1).join(', ')+' y '+c[c.length-1]:String(c[0]||'');
  const text=scx.connected?'● tarjeta SCX conectada · '+(c.length?(c.length===1?'mando '+list:'mandos '+list)+' prendido'+(c.length===1?'':'s'):'sin mandos prendidos'):scx.status==='sin_datos'?'◌ tarjeta SCX sin datos · ¿está prendida la pista?':'● tarjeta SCX no conectada · reintentando automáticamente';
  if(box.textContent!==text)box.textContent=text;
}
function applyLapConfig(config){
  if(!config||lapConfigBusy)return;
  const sig=JSON.stringify(config);if(sig===lapConfigSignature)return;
  lapConfig=config;lapConfigSignature=sig;renderLapConfig(true);
  if(screen==='choose')renderParticipants();
  if(screen==='session')renderSession();
}
function renderLapConfig(force=false){
  if(!lapConfig||!roster)return;
  const target=$('carAssign'),source=$('lapSource');if(!target||!source)return;
  const sig=lapConfigSignature+'|'+roster.version;
  if(!force&&target.dataset.sig===sig)return;
  if(target.contains(document.activeElement)&&!force)return;
  target.dataset.sig=sig;
  if(document.activeElement!==source)source.value=lapConfig.source;
  const minBox=$('lapMin');if(minBox&&document.activeElement!==minBox&&lapConfig.min_lap_s!=null)minBox.value=fmtMin(lapConfig.min_lap_s);
  $('lapSourceHelp').textContent=SOURCE_HELP[lapConfig.source]+' El cambio aplica a la siguiente sesión.';
  target.replaceChildren();
  roster.slots.forEach((p,i)=>{
    if(!p)return;const row=element('label','car-row');row.style.setProperty('--team',roster.colors[i].hex);
    const sel=element('select');sel.setAttribute('aria-label','Coche de '+p.name);
    for(let c=1;c<=6;c++){const o=element('option','','Coche '+c);o.value=String(c);sel.append(o);}
    sel.value=String(carFor(i));sel.addEventListener('change',()=>setCar(i,Number(sel.value)));
    // Handicap: clase del coche (se queda con el coche si los pilotos se cambian de coche).
    const hc=element('select','hc-class');hc.setAttribute('aria-label','Clase del coche de '+p.name);
    PeluHandicap.CLASES.forEach(([k,n])=>{const o=element('option','',PeluHandicap.ICON[k]+' '+n+' · '+PeluHandicap.segTxt(hcCfg().seg[k]));o.value=k;hc.append(o);});
    hc.value=hcCfg().clases[String(carFor(i))]||'sin_iman';hc.addEventListener('change',()=>setClase(carFor(i),hc.value));
    // 🏎️ Garage: si ese mando tiene un coche del Garage en pista, la clase la pone el coche (y suma su hándicap propio).
    const gc=PeluGarage.on(carFor(i));if(gc){hc.value=gc.clase;hc.disabled=true;hc.title='La clase la pone el coche del Garage: '+gc.nombre;}
    const sels=element('span','car-selects');sels.append(sel,hc);
    if(PeluGarage.cars().length)sels.append(PeluGarage.select(carFor(i),m=>{if(m!==carFor(i))setCar(i,m);else renderLapConfig(true);},m=>{$('lapConfigError').textContent=m;}));
    const nv=p.nivel||'intermedio';row.append(element('span','',p.name+' · '+PeluHandicap.NIVEL_ICON[nv]+' '+PeluHandicap.nivelTxt(nv)),sels);target.append(row);
  });
  renderHandicapConfig();
  if(!roster.slots.some(Boolean))target.append(element('p','help','Agrega pilotos para asignarles coche.'));
}
async function saveLapConfig(next){
  lapConfigBusy=true;$('lapConfigError').textContent='';
  try{
    const r=await fetch('/api/vueltas-config',{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify(next)});
    const data=await r.json();if(!r.ok)throw Error(data.error||'No se pudo guardar.');
    lapConfig=data;lapConfigSignature=JSON.stringify(data);
  }catch(e){$('lapConfigError').textContent=e.message||'No hay conexión con la Mac. Intenta otra vez.';}
  finally{lapConfigBusy=false;renderLapConfig(true);if(screen==='choose')renderParticipants();if(screen==='session')renderSession();}
}
// Handicap (ajuste de tiempo por vuelta): data/vueltas.json en la Mac. Clases por COCHE y segundos por clase.
const HC_FALLBACK={enabled:true,seg:{sin_iman:0,con_iman:0.5,modificado:1},clases:{'1':'sin_iman','2':'sin_iman','3':'sin_iman','4':'sin_iman','5':'sin_iman','6':'sin_iman'}};
function hcCfg(){return lapConfig?.handicap||HC_FALLBACK;}
function renderHandicapConfig(){
  const h=hcCfg(),en=$('hcEnabled');if(!en)return;
  if(document.activeElement!==en)en.checked=!!h.enabled;
  PeluHandicap.CLASES.forEach(([k])=>{const i=$('hcSeg_'+k);if(i&&i.hcField&&document.activeElement!==i)i.hcField.setValue(h.seg[k]??0);});
  $('hcSeg').classList.toggle('off',!h.enabled);
  const nb=$('hcNivel');if(nb&&!nb.contains(document.activeElement)){const sig=JSON.stringify([h.nivel_on,h.seg_nivel,h.nivel_auto,h.cortes,h.enabled]);
    if(nb.dataset.sig!==sig){nb.dataset.sig=sig;PeluHandicap.nivelSettings(nb,h,saveHandicap,m=>{$('lapConfigError').textContent=m;});}nb.classList.toggle('off',!h.enabled);}
}
function saveHandicap(part){if(!lapConfig)return;saveLapConfig({source:lapConfig.source,cars:lapConfig.cars.slice(),handicap:part});}
function setClase(car,clase){const c={};c[String(car)]=clase;saveHandicap({clases:c});}
$('hcEnabled').addEventListener('change',()=>saveHandicap({enabled:$('hcEnabled').checked}));
// Cada clase: botón + / − (suma o resta) y el número; el teclado del iPhone no tiene signo menos.
PeluHandicap.CLASES.forEach(([k])=>PeluHandicap.upgrade($('hcSeg_'+k),v=>{
  if(!Number.isFinite(v)||v<-10||v>10){$('lapConfigError').textContent='El ajuste por vuelta debe ser de 0 a 10 segundos (el botón + / − elige si suma o resta).';renderHandicapConfig();return;}
  const seg={};seg[k]=v;saveHandicap({seg});
}));
function setCar(slot,car){
  if(!lapConfig)return;const cars=lapConfig.cars.slice(),other=cars.indexOf(car);
  if(other>=0&&other!==slot){cars[other]=cars[slot];}cars[slot]=car;
  saveLapConfig({source:lapConfig.source,cars});
}
$('lapSource').addEventListener('change',()=>{if(lapConfig)saveLapConfig({source:$('lapSource').value,cars:lapConfig.cars.slice()});});
// Vuelta mínima válida (segundos): se guarda en la Mac (data/vueltas.json) y aplica a Práctica, Carrera, Gran Premio y Mi coche.
$('lapMin').addEventListener('change',()=>{
  if(!lapConfig)return;const v=Number(String($('lapMin').value).replace(',','.'));
  if(!Number.isFinite(v)||v<0.5||v>60){$('lapConfigError').textContent='La vuelta mínima debe ser de 0.5 a 60 segundos.';$('lapMin').value=fmtMin(lapConfig.min_lap_s);return;}
  saveLapConfig({source:lapConfig.source,cars:lapConfig.cars.slice(),min_lap_s:Math.round(v*100)/100});
});

// Sonido del semáforo: mismo archivo y mismo interruptor por equipo que el Gran Premio ("Activar sonido aquí").
const SESSION_SFX={semaforo:new Audio('sfx/semaforo.mp3'),frenazo:new Audio('sfx/frenazo.mp3'),abucheo:new Audio('sfx/abucheo.mp3')};Object.values(SESSION_SFX).forEach(a=>a.preload='auto');
let sfxDevice=false;try{sfxDevice=localStorage.getItem('gp-sound')==='on';}catch(e){}
let sfxUnlocked=false;
function sfxVolume(){const d=dashConfig();return d.sound_enabled===false?0:Math.max(0,Math.min(1,(Number.isFinite(d.sound_volume)?d.sound_volume:80)/100));}
function playSfx(name,offset=0){
  if(!sfxDevice||!sfxUnlocked)return;const v=sfxVolume();if(!v)return;
  const a=SESSION_SFX[name];if(!a)return;try{a.pause();a.currentTime=offset>0?offset:0;}catch(e){}a.volume=v;a.play().catch(()=>{});
}
function unlockSfx(){Object.values(SESSION_SFX).forEach(a=>{a.muted=true;a.play().then(()=>{a.pause();a.currentTime=0;a.muted=false;}).catch(()=>{a.muted=false;});});}
function syncSfxButton(){const b=$('soundToggle');if(!b)return;const on=sfxDevice&&sfxUnlocked;b.textContent=on?'🔊 Sonido en este equipo':'🔇 Activar sonido aquí';b.classList.toggle('on',on);}
$('soundToggle').addEventListener('click',()=>{
  if(sfxDevice&&sfxUnlocked)sfxDevice=false;else{sfxDevice=true;sfxUnlocked=true;unlockSfx();}
  try{localStorage.setItem('gp-sound',sfxDevice?'on':'off');}catch(e){}syncSfxButton();
});
document.addEventListener('pointerdown',()=>{if(sfxDevice&&!sfxUnlocked){sfxUnlocked=true;unlockSfx();syncSfxButton();}});
syncSfxButton();
// 💥 Explosión al sensor: mismo interruptor «Activar sonido aquí» y mismo volumen que el semáforo.
if(window.PeluExplosion)PeluExplosion.config({canPlay:()=>sfxDevice&&sfxUnlocked,volume:sfxVolume});
