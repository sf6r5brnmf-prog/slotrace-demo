// 👥 Registro de pilotos: todos los que han venido (regulares e invitados), con su nivel, mejores vueltas REALES,
// carreras, ganadas e historial. La parrilla de hoy (6 lugares) se arma desde aquí. La clase NO es del piloto: es del coche.
(()=>{
const $=id=>document.getElementById(id);
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e;};
const H=window.PeluHandicap;
let REG=null,loading=false,again=false,filtro='activos',orden='nombre',q='',detalle=null,quickOpen=false;
try{orden=localStorage.getItem('pelu-reg-orden')||'nombre';}catch(e){}
const NV_ORD={experto:0,intermedio:1,novato:2};
const clave=s=>String(s||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('es-MX').replace(/[^a-z0-9 ]/g,' ').replace(/\s+/g,' ').trim();
function mejor(p){const v=Object.values(p.mejores||{}).filter(x=>x!=null);return v.length?Math.min(...v):null;}
function ini(n){const w=String(n||'').trim().split(/\s+/).filter(Boolean);return ((w[0]||'?')[0]+(w.length>1?w[w.length-1][0]:(w[0]||'').slice(1,2))).toLocaleUpperCase('es-MX');}
function foto(p,cls){
  if(p.avatar){const i=el('img',cls||'reg-av');i.src=p.avatar+'?v=mica2';i.alt='Avatar de '+p.name;i.loading='lazy';return i;}
  const d=el('span',(cls||'reg-av')+' reg-ini',ini(p.name));d.style.setProperty('--team',p.color);d.setAttribute('aria-hidden','true');return d;
}
function nivelChip(p){
  const nv=p.nivel||'intermedio',s=el('span','nivel-chip nv-'+nv,H.NIVEL_ICON[nv]+' '+H.nivelTxt(nv));
  s.append(el('small','nv-src',p.nivel_fuente==='auto'?' · por tiempos':' · a mano'));return s;
}
function mejoresChips(p,box){
  const ks=H.CLASES.map(([k])=>k).filter(k=>(p.mejores||{})[k]!=null);
  if(!ks.length){box.append(el('span','mj-v none','Sin tiempos todavía'));return;}
  ks.forEach(k=>box.append(el('span','mj-v',H.ICON[k]+' '+H.NOMBRE[k]+' '+Number(p.mejores[k]).toFixed(2)+' s')));
}
async function post(body){return await window.regPost(body);}
function toast(m){if(window.notify)notify(m);}
function err(e){toast(e.message||'No hay conexión con la Mac.');}
async function load(){
  if(loading){again=true;return;}loading=true;
  try{const r=await fetch('/api/pilotos',{cache:'no-store'});if(r.ok)set(await r.json());}catch(e){}
  finally{loading=false;if(again){again=false;load();}}
}
let firma='';
function set(d){if(!d||!d.pilotos)return;const f=JSON.stringify(d.pilotos);if(f===firma&&REG)return;firma=f;REG=d;paint();}
function get(id){return REG&&REG.pilotos.find(p=>p.id===id)||null;}
function colores(){return (REG?.colors||roster?.colors||[]).map(c=>({name:c.name,hex:c.hex}));}
function colorLibre(){const cs=colores().map(c=>c.hex),us=(REG?.pilotos||[]).filter(p=>!p.archivado).map(p=>p.color);return cs.find(c=>!us.includes(c))||cs[(REG?.pilotos.length||0)%cs.length]||'#d5ff42';}
function sentados(){return (REG?.pilotos||[]).filter(p=>p.slot!=null);}
function avisoDup(name,pid){
  const b=$('dupAviso');if(!b)return;const k=clave(name),o=k&&(REG?.pilotos||[]).find(p=>p.id!==pid&&clave(p.name)===k);
  b.hidden=!o;if(o)b.textContent='⚠️ Ya hay un «'+o.name+'» en el registro'+(o.archivado?' (archivado)':'')+'. Si es la misma persona, al guardar te ofrezco unirlos.';
}
async function sentar(p){
  if(p.slot!=null)return;
  if(sentados().length>=6){toast('La parrilla ya tiene 6. Saca a alguien (✕) para meter a '+p.name+'.');return;}
  try{const r=await post({action:'sentar',id:p.id,image:p.avatar?undefined:window.avatarIniciales(p.name,p.color)});
    if(typeof r.slot==='number'&&typeof selectionInitialized!=='undefined'&&selectionInitialized)selectedPilots.add(r.slot);await poll();toast(p.name+' entra a la parrilla.');}catch(e){err(e);}
}
async function levantar(p){if(p.slot==null)return;try{await post({action:'levantar',slot:p.slot});await poll();toast(p.name+' sale de la parrilla (sigue en el registro).');}catch(e){err(e);}}

// ---------- pantalla del registro ----------
function lista(){
  let ps=(REG?.pilotos||[]).slice();
  if(filtro==='activos')ps=ps.filter(p=>!p.archivado);
  else if(filtro==='regulares')ps=ps.filter(p=>!p.archivado&&p.tipo==='regular');
  else if(filtro==='invitados')ps=ps.filter(p=>!p.archivado&&p.tipo==='invitado');
  else if(filtro==='archivados')ps=ps.filter(p=>p.archivado);
  const k=clave(q);if(k)ps=ps.filter(p=>clave(p.name+' '+(p.apodo||'')).includes(k));
  const nm=(a,b)=>a.name.localeCompare(b.name,'es-MX');
  const by={nombre:nm,nivel:(a,b)=>NV_ORD[a.nivel]-NV_ORD[b.nivel]||nm(a,b),
    vuelta:(a,b)=>{const x=mejor(a),y=mejor(b);return (x==null)-(y==null)||(x??0)-(y??0)||nm(a,b);},carreras:(a,b)=>b.carreras-a.carreras||nm(a,b)};
  return ps.sort(by[orden]||nm);
}
function card(p){
  const c=el('article','reg-card'+(p.archivado?' archivado':'')+(p.slot!=null?' sentado':''));c.style.setProperty('--team',p.color);c.dataset.id=p.id;c.tabIndex=0;c.setAttribute('role','button');c.setAttribute('aria-label','Ver a '+p.name);
  const info=el('div','reg-info'),top=el('div','reg-nombre');top.append(el('strong','',p.name));if(p.apodo)top.append(el('span','reg-apodo','«'+p.apodo+'»'));
  const tags=el('div','reg-tags');tags.append(nivelChip(p));
  if(p.tipo==='invitado')tags.append(el('span','reg-tag inv','👥 Invitado'));
  if(p.archivado)tags.append(el('span','reg-tag arch','🗄️ Archivado'));
  const mj=el('div','mejores-box');mejoresChips(p,mj);
  const car=window.PeluGarage&&PeluGarage.car(p.coche);
  const st=el('p','reg-stats',[p.carreras+' carrera'+(p.carreras===1?'':'s'),p.ganadas+' ganada'+(p.ganadas===1?'':'s'),p.practicas+' práctica'+(p.practicas===1?'':'s')].join(' · ')+(car?' · 🏎️ '+car.nombre:''));
  info.append(top,tags);
  // Nivel sugerido por sus tiempos: se acepta con un toque desde la tarjeta.
  const sg=p.sugerido,ch=p.nivel_cambio,stop=f=>e=>{e.stopPropagation();f();};
  if(sg&&sg.nivel!==p.nivel){const x=el('div','nivel-sug');x.append(el('span','','💡 Sugerido: '),el('b','',H.NIVEL_ICON[sg.nivel]+' '+H.nivelTxt(sg.nivel)),el('small','',H.sugTxt(sg).replace(/^[^·]+· /,'')));
    const a=el('button','primary small','Aceptar');a.type='button';a.addEventListener('click',stop(()=>accion(p,'nivel',{nivel:sg.nivel},'Nivel: '+H.nivelTxt(sg.nivel))));
    const n=el('button','small','✕');n.type='button';n.setAttribute('aria-label','Descartar sugerencia');n.addEventListener('click',stop(()=>accion(p,'nivel_descartar')));x.append(a,n);info.append(x);}
  else if(ch){const x=el('div','nivel-sug cambio');x.append(el('span','','Cambió solo: '+H.nivelTxt(ch.de)+' → '),el('b','',H.nivelTxt(ch.nivel)));const n=el('button','small','OK');n.type='button';n.addEventListener('click',stop(()=>accion(p,'nivel_descartar')));x.append(n);info.append(x);}
  info.append(mj,st);
  const act=el('div','reg-act');
  if(!p.archivado){const b=el('button',p.slot!=null?'reg-seat on':'reg-seat',p.slot!=null?'✓ Lugar '+(p.slot+1):'＋ Parrilla');b.type='button';
    b.setAttribute('aria-label',p.slot!=null?'Sacar a '+p.name+' de la parrilla':'Meter a '+p.name+' a la parrilla');
    b.addEventListener('click',e=>{e.stopPropagation();p.slot!=null?levantar(p):sentar(p);});act.append(b);}
  c.append(foto(p),info,act);
  c.addEventListener('click',()=>abrir(p.id));c.addEventListener('keydown',e=>{if(e.key==='Enter')abrir(p.id);});
  return c;
}
function parrilla(){
  const box=$('parrilla');if(!box)return;box.replaceChildren();const cols=REG?.colors||[];
  for(let i=0;i<6;i++){
    const p=(REG?.pilotos||[]).find(x=>x.slot===i),t=el('div','reg-slot'+(p?'':' libre'));t.style.setProperty('--team',p?p.color:(cols[i]?.hex||'#555'));
    if(p){t.append(foto(p,'reg-slot-av'),el('span','reg-slot-n',p.apodo||p.name));const x=el('button','reg-slot-x','✕');x.type='button';x.setAttribute('aria-label','Sacar a '+p.name+' de la parrilla');x.addEventListener('click',e=>{e.stopPropagation();levantar(p);});t.append(x);t.addEventListener('click',()=>abrir(p.id));}
    else{t.append(el('span','reg-slot-plus','＋'),el('span','reg-slot-n','Libre'));t.addEventListener('click',()=>{$('regBuscar').focus();toast('Toca «＋ Parrilla» en el piloto que va a correr.');});}
    box.append(t);
  }
  $('parrillaN').textContent=sentados().length+'/6';
}
function filtros(){
  const box=$('regFiltro');if(!box)return;box.replaceChildren();const ps=REG?.pilotos||[];
  [['activos','Activos',ps.filter(p=>!p.archivado).length],['regulares','Regulares',ps.filter(p=>!p.archivado&&p.tipo==='regular').length],['invitados','Invitados',ps.filter(p=>!p.archivado&&p.tipo==='invitado').length],['archivados','Archivados',ps.filter(p=>p.archivado).length]].forEach(([k,t,n])=>{
    const b=el('button','reg-f'+(filtro===k?' on':''),t+' '+n);b.type='button';b.setAttribute('aria-pressed',String(filtro===k));b.addEventListener('click',()=>{filtro=k;paint();});box.append(b);});
}
function paint(){
  if(!REG)return;
  const n=REG.pilotos.filter(p=>!p.archivado).length;
  if($('count')){$('count').textContent=n+' piloto'+(n===1?'':'s')+' en el registro';$('countSub').textContent=sentados().length+' de 6 en la parrilla de hoy';}
  parrilla();filtros();
  const board=$('board');if(board){board.replaceChildren();const ps=lista();ps.forEach(p=>board.append(card(p)));
    if(!ps.length)board.append(el('p','help reg-vacio',REG.pilotos.length?(q?'Nadie se llama así. Revisa o toca «+ Nuevo piloto».':'No hay pilotos en esta lista.'):'Todavía no hay pilotos. Toca «+ Nuevo piloto».'));}
  if($('regOrden'))$('regOrden').value=orden;
  if(detalle&&!$('regDetalle').hidden){const p=get(detalle);p?pintarDetalle(p):cerrar();}
  if(typeof screen!=='undefined'&&screen==='choose'&&typeof renderParticipants==='function')renderParticipants();
}

// ---------- detalle del piloto ----------
function abrir(id){detalle=id;const p=get(id);if(!p)return;pintarDetalle(p);$('regDetalle').hidden=false;document.body.classList.add('modal-open');$('rdCerrar').focus();}
function cerrar(){detalle=null;$('regDetalle').hidden=true;$('rdCuerpo').replaceChildren();if($('overlay').hidden)document.body.classList.remove('modal-open');}
function btn(t,cls,f){const b=el('button',cls||'',t);b.type='button';b.addEventListener('click',f);return b;}
function pintarDetalle(p){
  $('regDetalle').querySelector('.modal').style.setProperty('--team',p.color);
  $('rdTipo').textContent=(p.tipo==='invitado'?'👥 INVITADO':'⭐ REGULAR')+(p.archivado?' · ARCHIVADO':'')+(p.slot!=null?' · EN LA PARRILLA (LUGAR '+(p.slot+1)+')':'');
  $('rdNombre').textContent=p.name+(p.apodo?' «'+p.apodo+'»':'');
  const b=$('rdCuerpo');b.replaceChildren();
  const head=el('div','rd-head');head.append(foto(p,'rd-av'));
  const nb=el('div','rd-nivel');nb.append(el('span','rd-lbl','Nivel'),nivelChip(p));
  const sg=p.sugerido,ch=p.nivel_cambio;
  if(sg&&sg.nivel!==p.nivel){const s=el('div','nivel-sug');s.append(el('span','','Sugerido por sus tiempos: '),el('b','',H.NIVEL_ICON[sg.nivel]+' '+H.nivelTxt(sg.nivel)),el('small','',H.sugTxt(sg).replace(/^[^·]+· /,'')));
    s.append(btn('Aceptar','primary small',()=>accion(p,'nivel',{nivel:sg.nivel},'Nivel: '+H.nivelTxt(sg.nivel))),btn('✕','small',()=>accion(p,'nivel_descartar')));nb.append(s);}
  else if(ch){const s=el('div','nivel-sug cambio');s.append(el('span','','Cambió solo: '+H.nivelTxt(ch.de)+' → '),el('b','',H.nivelTxt(ch.nivel)),el('small','',H.sugTxt(ch).replace(/^[^·]+· /,'')),btn('OK','small',()=>accion(p,'nivel_descartar')));nb.append(s);}
  nb.append(el('p','help',p.nivel_fuente==='auto'?'Lo puso la app con su mejor vuelta real de una sesión.':'Lo pusiste a mano. La app te sugiere cambios con sus tiempos.'));
  head.append(nb);b.append(head);
  const kp=el('div','rd-kpis');[['Carreras',p.carreras],['Ganadas',p.ganadas],['Prácticas',p.practicas],['Vueltas',p.vueltas]].forEach(([t,v])=>{const k=el('div','rd-kpi');k.append(el('b','',String(v)),el('span','',t));kp.append(k);});b.append(kp);
  {const box=el('a','mejores-box');box.href='ranking.html';box.append(el('span','mj-t','🏆 Mejor vuelta real (sin hándicap)'));mejoresChips(p,box);b.append(box);}
  const car=window.PeluGarage&&PeluGarage.car(p.coche);b.append(el('p','rd-coche','🏎️ Coche habitual: '+(car?PeluGarage.txt(car):'ninguno')));
  const ac=el('div','rd-acciones');
  ac.append(btn('✏️ Editar','primary',()=>{cerrar();openPilot(p.id);}));
  if(!p.archivado)ac.append(p.slot!=null?btn('Sacar de la parrilla','',()=>levantar(p)):btn('＋ Meter a la parrilla','',()=>sentar(p)));
  if(p.tipo==='invitado')ac.append(btn('⭐ Pasar a regular','',()=>accion(p,'promover',{},p.name+' ya es piloto regular.')));
  ac.append(btn(p.archivado?'♻️ Reactivar':'🗄️ Archivar','',()=>{if(!p.archivado&&!confirm('¿Archivar a «'+p.name+'»?\n\nYa no sale en la lista ni en la parrilla, pero guarda su historial y tiempos. Lo puedes reactivar cuando vuelva.'))return;accion(p,'archivar',{valor:!p.archivado},p.archivado?p.name+' está activo otra vez.':p.name+' archivado.');}));
  b.append(ac);
  // Unir duplicados
  const otros=REG.pilotos.filter(x=>x.id!==p.id);
  if(otros.length){const u=el('details','rd-unir');u.append(el('summary','','🔗 Es la misma persona que otro registro (unir)'));
    const s=el('select');s.setAttribute('aria-label','Piloto a unir');const o0=el('option','','Elige el otro registro…');o0.value='';s.append(o0);
    const k=clave(p.name);otros.slice().sort((a,b)=>(clave(b.name).includes(k.split(' ')[0])-clave(a.name).includes(k.split(' ')[0]))||a.name.localeCompare(b.name,'es-MX')).forEach(x=>{const o=el('option','',x.name+(x.apodo?' «'+x.apodo+'»':'')+(x.tipo==='invitado'?' (invitado)':''));o.value=x.id;s.append(o);});
    u.append(el('p','help','Se queda «'+p.name+'» con el historial, tiempos y carreras de los dos. El otro registro desaparece.'),s,btn('Unir','',async()=>{const x=get(s.value);if(!x){toast('Elige el otro registro.');return;}
      if(!confirm('¿Unir «'+x.name+'» dentro de «'+p.name+'»?\n\nSe juntan historial y tiempos; «'+x.name+'» deja de existir como registro aparte.'))return;
      try{await post({action:'unir',de:x.id,a:p.id});await poll();toast('Listo: '+x.name+' quedó unido a '+p.name+'.');}catch(e){err(e);}}));b.append(u);}
  // Historial
  b.append(el('h3','rd-h','Historial'));
  const h=el('ol','rd-hist');(p.hist||[]).forEach(r=>{const li=el('li','');
    li.append(el('span','rd-h-f',(r.tipo==='practica'?'↗ ':r.tipo==='carrera'?'▦ ':r.tipo==='torneo'?'🏆 ':'🏁 ')+r.fuente),
      el('span','rd-h-d',[r.pos?('P'+r.pos+(r.gano?' 🥇':'')):'',r.best!=null?Number(r.best).toFixed(2)+' s':'',r.vueltas+' vta'+(r.vueltas===1?'':'s'),r.coche?'🏎️ '+r.coche:''].filter(Boolean).join(' · ')));h.append(li);});
  if(!(p.hist||[]).length)h.append(el('li','muted','Todavía no corre. Aquí salen sus prácticas, carreras y Grandes Premios.'));
  b.append(h);
  b.append(btn('🗑️ Borrar del registro','danger rd-borrar',()=>{if(!confirm('¿Borrar a «'+p.name+'» del registro?\n\nSe borran su historial y sus tiempos del ranking. No se puede deshacer.\nSi solo ya no viene, mejor usa «Archivar».'))return;accion(p,'borrar',{},p.name+' borrado.').then(cerrar);}));
}
async function accion(p,a,extra,msg){try{await post(Object.assign({action:a,id:p.id},extra||{}));await poll();if(msg)toast(msg);}catch(e){err(e);}}

// ---------- chips del registro al elegir quién corre (Práctica / Carrera) ----------
function chips(){
  const box=el('div','reg-chips');box.id='regChips';
  const head=el('div','reg-chips-h');head.append(el('strong','','👥 ¿Quiénes corren hoy?'),el('small','muted',sentados().length+'/6 · toca un piloto para meterlo o sacarlo'));box.append(head);
  const row=el('div','reg-chip-row');
  const ps=(REG?.pilotos||[]).filter(p=>!p.archivado).sort((a,b)=>(a.slot==null)-(b.slot==null)||(a.tipo==='invitado')-(b.tipo==='invitado')||a.name.localeCompare(b.name,'es-MX'));
  ps.forEach(p=>{const c=el('button','reg-chip'+(p.slot!=null?' on':''));c.type='button';c.style.setProperty('--team',p.color);c.setAttribute('aria-pressed',String(p.slot!=null));
    c.append(foto(p,'reg-chip-av'),el('span','',(p.slot!=null?'✓ ':'')+(p.apodo||p.name)));if(p.tipo==='invitado')c.title='Invitado';
    c.addEventListener('click',()=>p.slot!=null?levantar(p):sentar(p));row.append(c);});
  const add=el('button','reg-chip nuevo','＋ Nuevo');add.type='button';add.id='regQuick';add.addEventListener('click',()=>{quickOpen=!quickOpen;renderParticipants();});row.append(add);
  box.append(row);
  if(quickOpen){const f=el('form','reg-quick');f.autocomplete='off';const i=el('input');i.id='regQuickName';i.placeholder='Nombre del piloto';i.maxLength=32;i.setAttribute('aria-label','Nombre del piloto nuevo');
    const cb=el('label','reg-check');const x=el('input');x.type='checkbox';x.id='regQuickInv';x.checked=true;cb.append(x,document.createTextNode(' Invitado'));
    const ok=el('button','primary','Agregar y meter');ok.type='submit';const full=btn('Con foto…','',()=>{quickOpen=false;openPilot(null,{sentar:true,name:i.value.trim(),invitado:x.checked});});
    const m=el('p','error');f.append(i,cb,ok,full,m);
    f.addEventListener('submit',async e=>{e.preventDefault();const name=i.value.replace(/\s+/g,' ').trim();if(!name){m.textContent='Escribe el nombre.';return;}
      const k=clave(name),dup=(REG?.pilotos||[]).find(p=>clave(p.name)===k);
      if(dup){if(!confirm('Ya hay un «'+dup.name+'» en el registro'+(dup.archivado?' (archivado)':'')+'. ¿Es la misma persona?\n\nAceptar = meter a «'+dup.name+'» a la parrilla (no se duplica).\nCancelar = escribe otro nombre o apellido.'))return;
        if(dup.archivado)await accion(dup,'archivar',{valor:false});quickOpen=false;await sentar(get(dup.id)||dup);return;}
      if(sentados().length>=6){m.textContent='La parrilla ya tiene 6. Saca a alguien primero.';return;}
      try{const col=colorLibre();const d=await post({action:'guardar',name,tipo:x.checked?'invitado':'regular',color:col,image:window.avatarIniciales(name,col),foto:false});
        quickOpen=false;const p=get(d.saved);await sentar(p);}catch(er){m.textContent=er.message;}});
    box.append(f);setTimeout(()=>i.focus(),0);}
  return box;
}

function wire(){
  if($('regBuscar'))$('regBuscar').addEventListener('input',e=>{q=e.target.value;paint();});
  if($('regOrden'))$('regOrden').addEventListener('change',e=>{orden=e.target.value;try{localStorage.setItem('pelu-reg-orden',orden);}catch(_){}paint();});
  if($('rdCerrar'))$('rdCerrar').addEventListener('click',cerrar);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('regDetalle').hidden&&$('overlay').hidden)cerrar();});
  setInterval(()=>{if(typeof screen!=='undefined'&&(screen==='roster'||screen==='choose')&&!document.hidden)load();},4000);
  if(window.PeluGarage)PeluGarage.onChange(()=>paint());
  load();
}
window.PeluPilotos={load,set,get,colores,colorLibre,chips,avisoDup,sentar,levantar,abrir,get data(){return REG;}};
wire();
})();
