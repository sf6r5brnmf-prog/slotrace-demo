'use strict';
// Torneo por mangas (7 o más pilotos) dentro del Gran Premio: inscripción con nivel, organizador de mangas,
// cola «Siguiente manga», avance de rondas (bracket), eliminados y final. Usa lo de gp.js (state, post, act, el, $…)
// solo dentro de las funciones (este archivo se carga antes que gp.js).
(function(){
const NIV=[['novato','Novato'],['intermedio','Intermedio'],['experto','Experto']];
const NIVTXT=Object.fromEntries(NIV),NIVICON={novato:'🟢',intermedio:'🔵',experto:'🟡'};
const MIN=7,FIN=6;
let ins=null,insBusy=false,insTimer=null,addLevel='intermedio',sel=null,setupSig='';
function nivelTxt(k){return NIVTXT[k]||'';}
function nivelChip(k){const s=el('span','tq-lvl tq-'+(k||'intermedio'),NIVICON[k]+' '+nivelTxt(k));return s;}
function light(hex){const m=/^#?([0-9a-f]{6})$/i.exec(String(hex||'').trim());if(!m)return false;const n=parseInt(m[1],16),r=n>>16,g=n>>8&255,b=n&255;return (r*299+g*587+b*114)/1000>150;}
function carChip(c){const col=COLORS[(c-1)%6],s=el('span','tq-car'+(light(col)?' light':''),String(c));s.style.setProperty('--team',col);s.title='Coche '+c;return s;}
function tamanos(n,c){const k=Math.max(1,Math.ceil(n/c)),b=Math.floor(n/k),x=n%k;return Array.from({length:k},(_,i)=>i<x?b+1:b);}
// Cuántas rondas y mangas salen con n pilotos y c coches (la misma regla que la Mac).
function plan(n,c){const r=[];let v=n;while(v>FIN){const s=tamanos(v,c),m=s.filter(x=>x>1).length,e=Math.min(m,v-FIN);r.push({vivos:v,mangas:m,elim:e,byes:s.filter(x=>x===1).length});v-=e;if(!e)break;}return {rondas:r,final:c>=FIN?1:Math.ceil(FIN/c)};}
function cfgT(){const c=state?.config||{};return {cars:c.torneo_cars||3,min:c.torneo_minutes||3,agrupar:c.torneo_agrupar||'nivel',laps:c.torneo_final_laps||10};}
function formatText(g){const t=g.torneo||{};return 'Torneo por mangas · '+(t.inscritos||g.pilots.length)+' pilotos · '+t.cars+' coches por manga · '+t.minutos+' min por manga · el último de cada manga queda eliminado · final de 6'+(t.final_modo==='una'?' a '+t.final_laps+' vueltas':' en mangas (suma de vueltas)');}

/* ---------------- Inscripción ---------------- */
async function loadIns(){try{const r=await fetch('/api/inscritos',{cache:'no-store'});if(r.ok){ins=await r.json();}}catch(e){}return ins;}
function saveIns(){clearTimeout(insTimer);insTimer=setTimeout(async()=>{insBusy=true;try{ins=await post('/api/inscritos',{pilotos:ins.pilotos});$('tqError').textContent='';}catch(e){$('tqError').textContent=e.message;}finally{insBusy=false;renderSetup(true);}},250);}
function levelPicker(cur,onPick,small){
  const box=el('span','tq-lvls'+(small?' sm':''));box.setAttribute('role','radiogroup');
  NIV.forEach(([k,n])=>{const b=el('button','tq-lvlbtn tq-'+k+(cur===k?' on':''),small?n[0]:n);b.type='button';b.title=n;b.setAttribute('aria-pressed',cur===k?'true':'false');b.setAttribute('aria-label',n);
    b.addEventListener('click',()=>onPick(k));box.append(b);});
  return box;
}
function renderSetup(force){
  const tab=$('torneoTab');if(!tab||tab.hidden&&!force)return;
  if(!ins){loadIns().then(()=>{if(ins)renderSetup(true);});return;}
  const c=cfgT(),n=ins.pilotos.length;
  const sig=JSON.stringify([ins.version,ins.pilotos,c,addLevel]);if(!force&&sig===setupSig)return;setupSig=sig;
  // Formato: coches por manga, minutos, cómo se arman, vueltas de la final (se guarda en la configuración del GP).
  const cf=$('tqConfig');if(!cf.contains(document.activeElement)){cf.replaceChildren();
    const row=(label,input,note)=>{const r=el('label','tq-cfg');r.append(el('span','',label),input);if(note)r.append(el('small','muted',note));cf.append(r);};
    const cars=el('select');cars.id='tqCars';for(let k=2;k<=6;k++){const o=el('option','',k+' coches'+(k===6?' (las dos centralitas)':''));o.value=k;cars.append(o);}cars.value=String(c.cars);
    const mins=el('input');mins.type='number';mins.id='tqMin';mins.inputMode='decimal';mins.step='0.5';mins.min='0.25';mins.max='60';mins.value=c.min;
    const agr=el('select');agr.id='tqAgr';[['nivel','Agrupar por nivel (recomendado)'],['mezcla','Mezclar niveles (serpentina)']].forEach(([v,t])=>{const o=el('option','',t);o.value=v;agr.append(o);});agr.value=c.agrupar;
    const laps=el('input');laps.type='number';laps.id='tqLaps';laps.inputMode='numeric';laps.min='1';laps.max='500';laps.value=c.laps;
    row('Coches por manga',cars,c.cars>=6?'6 coches a la vez: necesitas las dos centralitas.':'Los coches que corren a la vez en cada manga.');
    row('Minutos por manga',mins,'Se suman vueltas en ese tiempo.');
    row('Cómo se arman las mangas',agr,c.agrupar==='nivel'?'Expertos con expertos y novatos con novatos: cada quien pelea contra los de su nivel.':'Cada manga trae fuertes y débiles (serpentina).');
    row('Vueltas de la final',laps,c.cars>=6?'Final de 6 en una sola carrera: gana el primero en esas vueltas.':'Con '+c.cars+' coches la final se corre en '+Math.ceil(FIN/c.cars)+' mangas de '+c.min+' min y gana quien sume más vueltas.');
    const save=async()=>{try{const d=await post('/api/gp/config',{config:{torneo_cars:Number(cars.value),torneo_minutes:Number(String(mins.value).replace(',','.')),torneo_agrupar:agr.value,torneo_final_laps:Math.round(Number(laps.value)),preset:'personal'}});state.config=d.config;$('tqError').textContent='';renderSetup(true);}catch(e){$('tqError').textContent=e.message;}};
    [cars,mins,agr,laps].forEach(i=>i.addEventListener('change',save));}
  $('tqFormat').textContent='Se inscriben '+MIN+' o más pilotos con su nivel. La app arma mangas de '+c.cars+' (en Configuración cambias cuántos coches por manga). En cada manga se suman vueltas '+c.min+' min y el ÚLTIMO queda eliminado. Con los que siguen se sortea otra ronda, hasta que quedan 6 para la final. Es digital: los coches se cambian de carril solos, no hay rotación de carriles. El handicap por clase de coche sigue aplicando.';
  // Lista
  setText($('tqCount'),n?'· '+n+' inscrito'+(n===1?'':'s'):'');
  const lv=$('tqAddLvl');lv.replaceChildren(levelPicker(addLevel,k=>{addLevel=k;renderSetup(true);}));
  const list=$('tqList'),ae=document.activeElement;if(!(list.contains(ae)&&ae.matches('input'))){list.replaceChildren();
    ins.pilotos.forEach((p,i)=>{const li=el('li','tq-item tq-'+p.nivel);
      const nm=el('input','tq-name');nm.value=p.name;nm.maxLength=24;nm.setAttribute('aria-label','Nombre del piloto '+(i+1));
      nm.addEventListener('change',()=>{const q=ins.pilotos[i];const v=nm.value.replace(/\s+/g,' ').trim().slice(0,24);if(!q||!v){nm.value=q?q.name:'';return;}q.name=v;saveIns();});
      const del=el('button','tq-del','✕');del.type='button';del.setAttribute('aria-label','Quitar a '+p.name);del.addEventListener('click',()=>{ins.pilotos.splice(i,1);saveIns();renderSetup(true);});
      li.append(el('b','tq-num',String(i+1)),nm,levelPicker(p.nivel,k=>{const q=ins.pilotos[i];if(q){q.nivel=k;delete q.sugerido;delete q.nivel_cambio;saveIns();}renderSetup(true);},true),del);
      // Nivel sugerido por sus tiempos (o cambiado solo, en modo «Cambiar solo»).
      const sg=p.sugerido,ch=p.nivel_cambio;
      if((sg&&sg.nivel!==p.nivel)||ch){const s=el('div','tq-sug'+(sg?'':' cambio'));
        s.append(el('span','',sg?'Sugerido: '+PeluHandicap.NIVEL_ICON[sg.nivel]+' '+PeluHandicap.nivelTxt(sg.nivel)+' · '+Number(sg.s).toFixed(2)+' s':'Cambió solo: '+PeluHandicap.nivelTxt(ch.de)+' → '+PeluHandicap.nivelTxt(ch.nivel)+' · '+Number(ch.s).toFixed(2)+' s'));
        if(sg){const ok=el('button','primary','Aceptar');ok.type='button';ok.addEventListener('click',()=>{const q=ins.pilotos[i];if(q){q.nivel=sg.nivel;delete q.sugerido;saveIns();}renderSetup(true);});s.append(ok);}
        const no=el('button','','✕');no.type='button';no.setAttribute('aria-label','Quitar aviso');no.addEventListener('click',()=>{const q=ins.pilotos[i];if(q){delete q.sugerido;delete q.nivel_cambio;saveIns();}renderSetup(true);});s.append(no);li.append(s);}
      list.append(li);});
    if(!n)list.append(el('li','muted','Todavía no hay inscritos. Escribe un nombre arriba y aprieta «Inscribir».'));}
  const cnt={novato:0,intermedio:0,experto:0};ins.pilotos.forEach(p=>cnt[p.nivel]++);
  const w=$('tqWarn');w.textContent=n<MIN?('Faltan '+(MIN-n)+' piloto'+(MIN-n===1?'':'s')+' para un torneo (mínimo '+MIN+'). Con 6 o menos no hay a quién eliminar: usa «Nuevo Gran Premio».'):(n<12?'Con '+n+' pilotos sí se puede; con 12 o más el torneo luce mejor.':'');
  w.classList.toggle('bad',n<MIN);
  // Así quedaría
  const pv=$('tqPreview');pv.replaceChildren();
  pv.append(el('p','tq-levels','Niveles: '+NIVICON.experto+' '+cnt.experto+' expertos · '+NIVICON.intermedio+' '+cnt.intermedio+' intermedios · '+NIVICON.novato+' '+cnt.novato+' novatos'));
  if(n>=MIN){const pl=plan(n,c.cars),ol=el('ol','tq-plan');
    pl.rondas.forEach((r,i)=>ol.append(el('li','','Ronda '+(i+1)+': '+r.vivos+' pilotos en '+r.mangas+' manga'+(r.mangas===1?'':'s')+' → se eliminan '+r.elim+(r.elim<r.mangas?' (los peores últimos lugares, para quedar exactamente 6)':' (el último de cada manga)')+(r.byes?' · '+r.byes+' pase directo (número impar)':''))));
    ol.append(el('li','tq-plan-final','Final de 6: '+(pl.final===1?'una carrera con 6 coches a '+c.laps+' vueltas':pl.final+' mangas de '+Math.ceil(FIN/pl.final)+' · gana quien sume más vueltas (desempata el tiempo total)')));
    const mangas=pl.rondas.reduce((a,r)=>a+r.mangas,0)+pl.final;
    pv.append(ol,el('p','muted','≈ '+mangas+' mangas en total · '+Math.round(mangas*(c.min+1.5))+' min aprox. (con salidas y cambios de piloto).'));}
  $('tqCreate').disabled=n<MIN;
}
function addPilot(name,nivel){
  name=String(name||'').replace(/\s+/g,' ').trim().slice(0,24);if(!name)return 'Escribe el nombre del piloto.';
  if(ins.pilotos.some(p=>p.name.toLocaleLowerCase('es-MX')===name.toLocaleLowerCase('es-MX')))return '«'+name+'» ya está inscrito. Ponle apellido o apodo.';
  // Si está en el registro de pilotos, entra con SU nivel (se puede cambiar aquí solo para el torneo).
  const reg=(roster?.slots||[]).find(r=>r&&r.name.toLocaleLowerCase('es-MX')===name.toLocaleLowerCase('es-MX'));
  ins.pilotos.push({name,nivel:reg&&reg.nivel?reg.nivel:nivel});return '';
}
function wire(){
  if(!$('torneoTab'))return;
  if(new URLSearchParams(location.search).get('tab')==='torneo'){const b=document.querySelector('.tab[data-tab="torneoTab"]');if(b)setTimeout(()=>b.click(),0);}
  $('tqAdd').addEventListener('submit',e=>{e.preventDefault();if(!ins)return;const err=addPilot($('tqName').value,addLevel);$('tqError').textContent=err;if(err)return;$('tqName').value='';saveIns();renderSetup(true);$('tqName').focus();});
  $('tqRoster').addEventListener('click',()=>{if(!ins||!roster)return;let k=0;(roster.slots||[]).forEach(p=>{if(p&&!addPilot(p.name,p.nivel||'intermedio'))k++;});$('tqError').textContent=k?'':'Los pilotos registrados ya están inscritos.';if(k){saveIns();toast(k+' piloto'+(k===1?'':'s')+' del registro inscrito'+(k===1?'':'s')+' con su nivel del registro');}renderSetup(true);});
  $('tqClear').addEventListener('click',()=>{if(!ins||!ins.pilotos.length)return;if(!confirm('¿Borrar toda la lista de inscritos?'))return;ins.pilotos=[];saveIns();renderSetup(true);});
  $('tqCreate').addEventListener('click',async()=>{
    if(!ins)return;$('tqError').textContent='';clearTimeout(insTimer);
    $('tqCreate').disabled=true;try{ins=await post('/api/inscritos',{pilotos:ins.pilotos});apply(await post('/api/gp',{action:'create',mode:'torneo',pilotos:ins.pilotos}));}catch(e){$('tqError').textContent=e.message;}finally{$('tqCreate').disabled=false;}
  });
}

/* ---------------- Carrera: stepper, siguiente manga, organizador, bracket ---------------- */
function stepper(g,st){
  const t=g.torneo;st.replaceChildren();
  t.rondas.forEach(r=>{const li=el('li','step');const cur=r.mangas.some(m=>m.actual),done=r.cerrada||g.status==='done';
    li.classList.toggle('current',cur);li.classList.toggle('done',done&&!cur);
    const hechos=r.mangas.filter(m=>m.phase==='done').length;
    li.append(el('b','',r.final?'FINAL':'RONDA '+r.n),el('small','',r.final?(r.mangas.length===1?t.final_laps+' vueltas':hechos+'/'+r.mangas.length+' mangas'):r.vivos+' pilotos · '+hechos+'/'+r.mangas.length));st.append(li);});
  const last=t.rondas[t.rondas.length-1];
  if(last&&!last.final){const p=plan(t.vivos,t.cars);
    p.rondas.slice(last.cerrada?0:1).forEach((r,i)=>{const li=el('li','step');li.append(el('b','','RONDA '+(last.n+1+i)),el('small','',r.vivos+' pilotos'));st.append(li);});
    const li=el('li','step');li.append(el('b','','FINAL'),el('small','','6 pilotos'));st.append(li);}
}
function nextLabel(g){
  const t=g.torneo,ro=t.rondas.find(r=>r.mangas.some(m=>m.actual));if(!ro)return 'Siguiente →';
  const i=ro.mangas.findIndex(m=>m.actual);
  if(i+1<ro.mangas.length)return 'Siguiente: '+ro.mangas[i+1].label+' →';
  return ro.final?'Ver podio 🏆':'Cerrar ronda '+ro.n+' (eliminar últimos) y sortear la siguiente →';
}
function pilotRow(m,p,editable,showRes){
  const row=el(editable?'button':'div','tq-p'+(p.eliminado?' out':'')+(sel===p.slot?' sel':''));if(editable)row.type='button';
  row.dataset.slot=p.slot;
  row.append(carChip(p.car),el('span','tq-pname',p.name),nivelChip(p.nivel));
  if(p.clase&&p.h_s)row.append(el('span','tq-hc',PeluHandicap.detalle(p)+(p.h_coche&&p.h_nivel?' = '+PeluHandicap.segTxt(p.h_s):'')));
  if(showRes&&p.laps!=null){row.append(el('span','tq-res',(p.dsq?'DSQ':p.pos?'P'+p.pos:'—')+' · '+p.laps+' v'+(p.total_h!=null&&state.gp.handicap?.on?' · '+p.total_h.toFixed(1)+' s H':p.total!=null?' · '+p.total.toFixed(1)+' s':'')));}
  if(p.eliminado)row.append(el('span','tq-out','ELIMINADO'));
  if(editable)row.addEventListener('click',()=>pickSwap(p.slot));
  return row;
}
async function pickSwap(slot){
  if(sel===null){sel=slot;toast('Toca otro piloto de una manga que no ha arrancado para cambiarlos de lugar.');renderPanel(state.gp,true);return;}
  if(sel===slot){sel=null;renderPanel(state.gp,true);return;}
  const a=sel;sel=null;await act('swap',{a,b:slot});
}
function heatBox(g,m,ro,opts){
  const box=el('div','tq-heat'+(m.actual?' now':'')+(m.phase==='done'?' done':''));
  const ph={ready:m.actual?'SIGUE':'EN COLA',countdown:'SEMÁFORO',running:'CORRIENDO',finishing:'ÚLTIMA VUELTA',red:'PARO',done:'TERMINADA'}[m.phase]||m.phase;
  const head=el('div','tq-hhead');head.append(el('strong','',m.label.replace(/^Ronda \d+ · /,'')),el('span','tq-ph tq-ph-'+m.phase,ph));box.append(head);
  const showRes=m.phase!=='ready';
  m.pilotos.forEach(p=>{const r=pilotRow(m,p,opts.edit&&m.editable,showRes);
    if(opts.edit&&m.editable){const cs=el('select','tq-carsel');cs.setAttribute('aria-label','Coche de '+p.name);for(let k=1;k<=6;k++){const o=el('option','','Coche '+k);o.value=k;cs.append(o);}cs.value=String(p.car);
      cs.addEventListener('click',e=>e.stopPropagation());cs.addEventListener('change',()=>act('set_car',{slot:p.slot,car:Number(cs.value)}));
      const w=el('div','tq-prow');w.append(r,cs);box.append(w);}else box.append(r);});
  if(m.phase==='done'&&!ro.cerrada&&!ro.final&&m.pilotos.length>1){const u=m.pilotos[m.pilotos.length-1];box.append(el('p','tq-last','Último: '+u.name+' → eliminado al cerrar la ronda'+(ro.vivos-ro.mangas.filter(x=>x.pilotos.length>1).length<FIN?' (salvo la regla de 6)':'')));}
  return box;
}
function renderPanel(g,force){
  let panel=$('torneoPanel');if(!panel){panel=el('section','tq-panel');panel.id='torneoPanel';$('tables').before(panel);}
  let nx=$('tqNext');if(!nx){nx=el('div','tq-next');nx.id='tqNext';$('raceControls').after(nx);}
  const t=g.torneo;panel.hidden=false;
  const sig=JSON.stringify([g.version,sel]);if(!force&&panel.dataset.sig===sig)return;panel.dataset.sig=sig;
  // Siguiente manga (grande, para el proyector): quién corre y con qué coche.
  const ro=t.rondas.find(r=>r.mangas.some(m=>m.actual));const cur=ro&&ro.mangas.find(m=>m.actual);
  nx.replaceChildren();nx.hidden=!cur||g.status!=='active';
  if(cur){const a=el('div','tq-now');a.append(el('span','tq-tag',cur.phase==='ready'?'SIGUE · a la pista':cur.phase==='done'?'TERMINÓ':'EN PISTA'),el('strong','',cur.label));
    const ps=el('div','tq-nowp');cur.pilotos.forEach(p=>{const b=el('span','tq-np');b.append(carChip(p.car),el('b','',p.name),nivelChip(p.nivel));ps.append(b);});a.append(ps);nx.append(a);
    if(t.cola.length){const q=el('div','tq-cola');q.append(el('span','tq-tag','DESPUÉS'));t.cola.slice(0,3).forEach(c=>{const d=el('span','tq-q');d.append(el('b','',c.label.replace(/^Ronda \d+ · /,'')+': '),document.createTextNode(c.pilotos.map(p=>p.name+' ('+p.car+')').join(', ')));q.append(d);});if(t.cola.length>3)q.append(el('span','muted','… y '+(t.cola.length-3)+' más'));nx.append(q);}
    else if(!ro.final){nx.append(el('p','tq-cola muted','Es la última manga de la ronda '+ro.n+'. Al terminar: se eliminan los últimos y se sortea la siguiente.'));}}
  panel.replaceChildren();
  const head=el('div','tq-phead');head.append(el('h3','','🏆 Torneo por mangas'),el('span','muted',t.inscritos+' inscritos · '+t.cars+' coches por manga · siguen '+t.vivos+(t.eliminados.length?' · eliminados '+t.eliminados.length:'')));panel.append(head);
  if(ro&&ro.nota)panel.append(el('p','tq-nota',ro.nota));
  const prev=t.rondas.filter(r=>r.cerrada&&r.nota).slice(-1)[0];if(prev&&prev!==ro)panel.append(el('p','tq-nota',prev.nota));
  // Organizador de la ronda actual (cambios a mano antes de arrancar cada manga).
  if(ro&&g.status==='active'){const org=el('div','tq-org');
    const edit=ro.mangas.some(m=>m.editable);
    org.append(el('h4','',(ro.final?'Final':'Ronda '+ro.n)+' · mangas'+(edit?' · toca dos pilotos para cambiarlos (antes de arrancar su manga)':'')));
    const grid=el('div','tq-heats');ro.mangas.forEach(m=>grid.append(heatBox(g,m,ro,{edit:true})));org.append(grid);
    if(ro.byes.length)org.append(el('p','muted','Pase directo (número impar): '+ro.byes.map(b=>b.name).join(', ')+'.'));
    org.append(el('p','muted tq-why',ro.final?'Final de 6.':(t.agrupar==='nivel'?'Mangas armadas por nivel (Experto, Intermedio, Novato) y, desde la ronda 2, por cómo les fue: cada quien pelea contra pilotos parecidos.':'Mangas con niveles mezclados (serpentina).')+' El último de cada manga se elimina (menos vueltas; con las mismas, el que las hizo más lento'+(g.handicap?.on?', con handicap':'')+').'));
    panel.append(org);}
  panel.append(bracket(g));
  if(t.eliminados.length){const e=el('div','tq-elim');e.append(el('h4','','Eliminados ('+t.eliminados.length+')'));const l=el('div','tq-chips');t.eliminados.forEach(x=>l.append(el('span','tq-chip','❌ '+x.name+' · R'+x.ronda)));e.append(l);panel.append(e);}
}
function bracket(g){
  const t=g.torneo,box=el('div','tq-bracket');box.append(el('h4','','Avance del torneo'));
  const cols=el('div','tq-cols');
  t.rondas.forEach(r=>{const col=el('div','tq-col'+(r.final?' fin':''));
    col.append(el('div','tq-colh',(r.final?'FINAL':'RONDA '+r.n)+' · '+r.vivos+(r.final?'':' → '+(r.cerrada?(r.vivos-r.eliminados.length):'?'))));
    r.mangas.forEach(m=>{const h=el('div','tq-mini'+(m.actual?' now':'')+(m.phase==='done'?' done':''));h.append(el('b','',m.label.replace(/^(Ronda \d+|Final) · /,'')));
      m.pilotos.forEach(p=>{const s=el('span','tq-mp'+(p.eliminado?' out':''));s.append(carChip(p.car),document.createTextNode(' '+p.name+(p.pos&&m.phase!=='ready'?' · P'+p.pos:'')));h.append(s);});col.append(h);});
    if(r.salvados.length)col.append(el('small','muted','Se salvó (regla de 6): '+r.salvados.map(x=>x.name).join(', ')));
    cols.append(col);});
  const last=t.rondas[t.rondas.length-1];
  if(g.status==='active'&&last&&!last.final){const p=plan(t.vivos,t.cars);p.rondas.slice(last.cerrada?0:1).forEach((r,i)=>{const col=el('div','tq-col ghost');col.append(el('div','tq-colh','RONDA '+(last.n+1+i)+' · '+r.vivos+' → '+(r.vivos-r.elim)),el('p','muted',r.mangas+' mangas · se sortea al cerrar la anterior'));cols.append(col);});
    const col=el('div','tq-col ghost fin');col.append(el('div','tq-colh','FINAL · 6'),el('p','muted',t.final_modo==='una'?'Una carrera a '+t.final_laps+' vueltas':'Mangas · suma de vueltas'));cols.append(col);}
  box.append(cols);return box;
}
function renderRace(g){
  if(g.mode!=='torneo'){const p=$('torneoPanel');if(p)p.hidden=true;const n=$('tqNext');if(n)n.hidden=true;return;}
  const run=g.run,t=g.torneo;
  if(run&&run.kind==='heat'){
    const hon=!!g.handicap?.on;const fin=/^Final/.test(run.label);
    const hints={ready:'A la pista con el coche que dice cada quien. Aprieta Empezar.',running:fin?'Final en mangas: se suman vueltas; la tabla final junta las mangas (desempata el menor tiempo total'+(hon?' con handicap':'')+').':'Se suman vueltas '+t.minutos+' min. El último de la manga queda eliminado'+(hon?' (con las mismas vueltas: el de más tiempo total con handicap)':'')+'.'};
    if(hints[run.phase])setText($('runHint'),hints[run.phase]);
    if(run.phase==='ready'||run.phase==='countdown')setText($('clock'),clock(t.minutos*60000));
  }
  const eb=$('runEyebrow');if(run&&eb.textContent.startsWith('ELIMINATORIAS'))setText(eb,eb.textContent.replace('ELIMINATORIAS','TORNEO'));
  renderPanel(g,false);
}
function tables(g,box){
  box.replaceChildren();const t=g.torneo,hon=!!g.handicap?.on;
  const fr=(g.final||[]).filter(r=>r.corrio!==false&&(r.laps>0||r.finished||r.pos));
  if(fr.length){box.append(table('Final del torneo'+(t.final_modo==='mangas'?' · suma de vueltas de las mangas':'')+(hon?' · con handicap':''),['Pos','Piloto','Nivel','Coche','Vueltas','Mejor'].concat(hon?['Total (H)']:['Total']),fr.map(r=>[r.dsq?'DSQ':r.pos??'—',r.name+(r.parte&&t.final_modo==='mangas'?' · '+r.parte.replace('Final · ',''):''),nivelTxt(r.nivel),r.car,r.laps,fmt(r.best),fmt(hon?r.total_h:r.total)])));}
  if(t.eliminados.length)box.append(table('Eliminados',['#','Piloto','Ronda','Manga','Vueltas','Total'],t.eliminados.map((e,i)=>[i+1,e.name,e.ronda,e.parte.replace(/^Ronda \d+ · /,''),e.laps,fmt(hon?e.total_h:e.total)])));
  if((g.sospechosas||[]).length){const tb=table('⚠ Vueltas sospechosas · no cuentan',['Parte','Piloto','Tiempo'],g.sospechosas.slice(-30).reverse().map(x=>[x.parte,x.name+(x.car?' · coche '+x.car:''),fmt(x.s)]));tb.classList.add('sus-box');box.append(tb);}
}
function renderDone(g){
  if(g.mode!=='torneo')return;
  const box=$('doneTables');
  setTimeout(()=>{if(!state?.gp||state.gp.mode!=='torneo')return;const b=bracket(state.gp);b.classList.add('done');box.prepend(b);
    const pod=$('podium');pod.querySelectorAll('.pod span').forEach((s,i)=>{});},0);
}
window.PeluTorneo={renderSetup,stepper,nextLabel,renderRace,tables,renderDone,formatText,nivelTxt,plan,tamanos};
document.addEventListener('DOMContentLoaded',wire);
})();
