'use strict';
// 🏎️ Garage: coches físicos con su ficha (foto, clase, chip, hándicap propio, mantenimiento) e historial.
// Todo se guarda en la Mac (data/garage.json + data/garage-fotos/). Aquí solo se muestra y se edita.
(function(){
const $=id=>document.getElementById(id);
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;};
const H=window.PeluHandicap,G=window.PeluGarage;
const COLORS=['#f5f7fa','#ffd84d','#ff4b4b','#3d96ff','#48d66d','#b46cff'];
let hcfg=null,editing=null,photoData=null,photoRemove=false,notas=[],hField=null;
function fmtFecha(f){if(!f)return '';const [y,m,d]=f.split('-');return d+'/'+m+'/'+y;}
function hoy(){const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function segClase(k){return hcfg&&hcfg.enabled?Number((hcfg.seg||{})[k]||0):0;}
function msg(t){$('msg').textContent=t||'';}
async function loadCfg(){try{const r=await fetch('/api/vueltas-config',{cache:'no-store'});if(r.ok){const d=await r.json();const s=JSON.stringify(d.handicap);if(s!==JSON.stringify(hcfg)){hcfg=d.handicap;render();}}}catch(e){}}
function conn(ok){const c=$('connection');c.textContent=ok?'● En vivo':'Sin conexión con la Mac';c.classList.toggle('live',ok);}
// ---------- ¿Quién lleva qué? (pilotos del registro) ----------
let roster=null,tab='casa';
async function loadRoster(){try{const r=await fetch('/api/roster',{cache:'no-store'});if(r.ok){const d=await r.json();const ch=!roster||d.version!==roster.version;roster=d;if(ch)render();}}catch(e){}}
function nombres(){const n={};((roster||{}).slots||[]).forEach((p,i)=>{if(p)n[String(i)]=p.name;});return n;}
function renderPista(){
  const box=$('pista');if(box.contains(document.activeElement))return;box.replaceChildren();
  const sl=(roster||{}).slots||[];
  if(!sl.some(Boolean)){box.append(el('p','muted','No hay pilotos registrados. Regístralos en el menú → Pilotos.'));return;}
  sl.forEach((p,i)=>{if(!p)return;const r=el('div','gar-mando');r.style.setProperty('--team',COLORS[i]);
    const c=G.uso(i);r.append(el('b','gar-mando-n',(p.name||'?').slice(0,1).toUpperCase()));
    const t=el('div','gar-mando-t');t.append(el('small','',p.name));
    t.append(el('span','gar-mando-sub',c?H.ICON[c.clase]+' '+H.NOMBRE[c.clase]+' '+H.segTxt(segClase(c.clase))+' · coche '+H.segTxt(c.h)+' = '+H.segTxt(Math.round((segClase(c.clase)+c.h)*100)/100)+((c.tipo==='invitado')?' · 🧳 invitado':''):(k=>'Sin ficha · '+H.ICON[k]+' '+H.NOMBRE[k]+' '+H.segTxt(segClase(k)))(G.claseDe(i))));
    t.append(G.pilot(i,p.name,nombres(),null,msg));r.append(t);box.append(r);});
}
// ---------- Tarjetas ----------
function stat(n,v){const d=el('div');d.append(el('dt','',n),el('dd','',v));return d;}
function card(c){
  const a=el('article','gar-card');a.style.setProperty('--car',c.color||'#555');a.dataset.id=c.id;
  const img=el('div','gar-img');
  if(c.foto){const i=el('img');i.src=c.foto;i.alt='Foto de '+c.nombre;img.append(i);}else{const n=el('span','gar-noimg','🏎️');img.append(n);}
  const badges=el('div','gar-badges');
  if(c.chip)badges.append(el('span','gar-badge chip','Mando habitual '+c.chip));
  const inv=c.tipo==='invitado';if(inv)badges.append(el('span','gar-badge inv','🧳 INVITADO'+(c.dueno?' · '+c.dueno:'')));
  const us=G.usadoPor(c.id);if(us!=null)badges.append(el('span','gar-badge pista','LO LLEVA · '+(nombres()[String(us)]||'piloto '+(us+1))));
  if(c.ejemplo)badges.append(el('span','gar-badge ej','EJEMPLO'));
  img.append(badges);
  const b=el('div','gar-body');
  const h3=el('h3','',c.nombre);b.append(h3);
  const sub=el('p','gar-sub');const dot=el('span','gar-dot');dot.style.background=c.color||'#555';sub.append(dot,document.createTextNode(c.escuderia||'Sin escudería'));b.append(sub);
  const hc=el('div','gar-hc'),sc=segClase(c.clase),tot=Math.round((sc+c.h)*100)/100;
  hc.append(el('span','gar-pill',H.ICON[c.clase]+' '+H.NOMBRE[c.clase]+' '+H.segTxt(sc)),el('span','gar-pill own'+(c.h<0?' neg':c.h>0?' pos':''),'Propio '+H.segTxt(c.h)),el('b','gar-tot','= '+H.segTxt(tot)+' por vuelta + nivel del piloto'));
  b.append(hc);
  const st=c.hist||{},dl=el('dl','gar-stats');
  dl.append(stat('Mejor vuelta',st.mejor!=null?st.mejor.toFixed(2)+' s':'—'),stat('Vueltas',String(st.vueltas||0)),stat('Carreras',String(st.carreras||0)),stat('Ganadas',String(st.ganadas||0)));
  b.append(dl);
  if(st.ultima)b.append(el('p','gar-last','Última: '+st.ultima+(st.practicas?' · prácticas: '+st.practicas:'')));
  const ex=[c.motor,c.peso?c.peso+' g':'',c.dueno?'Dueño: '+c.dueno:''].filter(Boolean);
  const exl=el('p','gar-extra');if(ex.length)exl.append(document.createTextNode(ex.join(' · ')));
  if(c.techo){const t=el('span','gar-techo');t.title='Marca del techo';const s=el('i');s.style.background=c.techo;t.append(s,document.createTextNode('techo'));exl.append(t);}
  if(exl.childNodes.length)b.append(exl);
  if(c.notas&&c.notas.length){const n=c.notas[0];b.append(el('p','gar-nota','🔧 '+(n.fecha?fmtFecha(n.fecha)+' · ':'')+n.texto+(c.notas.length>1?' (+'+(c.notas.length-1)+')':'')));}
  const bt=el('div','gar-btns');const ed=el('button','','Editar');ed.type='button';ed.addEventListener('click',()=>openEditor(c));bt.append(ed);
  // Coche de invitado: al terminar el evento se pasa a la casa o se borra.
  if(inv){const m=el('button','','🏠 Pasar a la casa');m.type='button';m.addEventListener('click',async()=>{try{await G.post({action:'a_casa',id:c.id});msg('«'+c.nombre+'» ya está en el Garage de la casa.');}catch(e){msg(e.message);}});
    const d=el('button','gar-danger','🗑 Borrar');d.type='button';d.addEventListener('click',async()=>{if(!confirm('¿Borrar «'+c.nombre+'» del Garage de invitados? Las carreras ya guardadas no cambian.'))return;try{await G.post({action:'delete',id:c.id});msg('');}catch(e){msg(e.message);}});
    bt.append(m,d);}
  b.append(bt);a.append(img,b);return a;
}
function render(){
  const all=G.cars(),casa=all.filter(c=>(c.tipo||'casa')==='casa'),invs=all.filter(c=>c.tipo==='invitado');
  $('nCasa').textContent=casa.length;$('nInv').textContent=invs.length;
  $('tabCasa').classList.toggle('on',tab==='casa');$('tabInv').classList.toggle('on',tab==='invitado');
  $('tabCasa').setAttribute('aria-selected',String(tab==='casa'));$('tabInv').setAttribute('aria-selected',String(tab==='invitado'));
  const cars=tab==='casa'?casa:invs;
  $('count').textContent=cars.length+(cars.length===1?' coche':' coches')+(tab==='casa'?' de la casa':' de invitados');
  $('countHelp').textContent=tab==='casa'?' · Hándicap total por vuelta = clase + coche + nivel del piloto':' · Coches que traen los pilotos invitados. Después del evento: pásalos a la casa o bórralos.';
  $('add').textContent=tab==='casa'?'+ Agregar coche':'+ Coche de invitado';$('delGuests').hidden=tab!=='invitado'||!invs.length;
  renderPista();
  const box=$('cars');box.replaceChildren();
  if(!cars.length){const e=el('div','gar-empty');
    if(tab==='casa')e.append(el('strong','','El Garage de la casa está vacío'),el('p','muted','Agrega tus coches con «+ Agregar coche». En la DEMO también puedes cargar el garage de ejemplo desde el botón DEMO.'));
    else e.append(el('strong','','No hay coches de invitados'),el('p','muted','Cuando un piloto invitado trae su coche, agrégalo aquí o directo al armar la carrera con «➕ Coche de invitado nuevo…» (nombre, clase y hándicap).'));
    box.append(e);return;}
  cars.forEach(c=>box.append(card(c)));
}
// ---------- Editor ----------
function renderNotas(){
  const ul=$('notas');ul.replaceChildren();
  if(!notas.length)ul.append(el('li','muted','Sin notas. Anota cambios de llantas, escobillas, guía…'));
  notas.forEach((n,i)=>{const li=el('li');li.append(el('span','gar-nf',n.fecha?fmtFecha(n.fecha):'—'),el('span','gar-nt',n.texto));
    const x=el('button','gar-nx','✕');x.type='button';x.setAttribute('aria-label','Quitar nota');x.addEventListener('click',()=>{notas.splice(i,1);renderNotas();});li.append(x);ul.append(li);});
}
function setPhoto(src){const i=$('photo');if(src){i.src=src;i.hidden=false;$('photoEmpty').hidden=true;}else{i.removeAttribute('src');i.hidden=true;$('photoEmpty').hidden=false;}$('noPhoto').hidden=!src;}
function updHelp(){const k=$('clase').value,sc=segClase(k),v=hField?hField.getValue():0;
  $('hHelp').textContent='Clase '+H.NOMBRE[k]+' '+H.segTxt(sc)+' + propio '+(Number.isFinite(v)?H.segTxt(v):'?')+' = '+(Number.isFinite(v)?H.segTxt(Math.round((sc+v)*100)/100):'?')+' por vuelta, más el nivel del piloto. Verde = suma, azul = resta.';}
function openEditor(c){
  editing=c||null;photoData=null;photoRemove=false;$('edError').textContent='';
  $('edTitle').textContent=c?'Editar coche':'Agregar coche';$('delete').hidden=!c;
  $('nombre').value=c?c.nombre:'';$('escuderia').value=c?c.escuderia:'';$('color').value=c&&c.color?c.color:'#e53935';
  $('clase').value=c?c.clase:'sin_iman';$('tipo').value=c?(c.tipo||'casa'):tab;$('chip').value=c&&c.chip?String(c.chip):'';
  hField.setValue(c?c.h:0);
  $('techo').value=c&&c.techo?c.techo:'#ffffff';$('sinTecho').checked=!!c&&!c.techo;$('techo').disabled=$('sinTecho').checked;
  $('motor').value=c?c.motor:'';$('peso').value=c&&c.peso!=null?c.peso:'';$('dueno').value=c?c.dueno:'';
  $('mas').open=!!(c&&(c.motor||c.peso||c.dueno))||$('tipo').value==='invitado';
  notas=c?c.notas.map(n=>Object.assign({},n)):[];renderNotas();$('notaFecha').value=hoy();$('notaTexto').value='';
  setPhoto(c&&c.foto?c.foto:'');updHelp();
  $('editor').hidden=false;document.body.classList.add('modal-open');setTimeout(()=>{if(!c)$('nombre').focus();},50);
}
function closeEditor(){$('editor').hidden=true;document.body.classList.remove('modal-open');editing=null;}
// Foto: se achica en el teléfono (máx. 800 px, JPG) antes de mandarla a la Mac.
function resize(file){return new Promise((res,rej)=>{const u=URL.createObjectURL(file),im=new Image();
  im.onload=()=>{const k=Math.min(1,800/Math.max(im.naturalWidth,im.naturalHeight)),w=Math.max(1,Math.round(im.naturalWidth*k)),h=Math.max(1,Math.round(im.naturalHeight*k));
    const cv=document.createElement('canvas');cv.width=w;cv.height=h;const x=cv.getContext('2d');x.fillStyle='#111';x.fillRect(0,0,w,h);x.drawImage(im,0,0,w,h);URL.revokeObjectURL(u);
    let q=0.82,d=cv.toDataURL('image/jpeg',q);while(d.length>1100000&&q>0.4){q-=0.12;d=cv.toDataURL('image/jpeg',q);}res(d);};
  im.onerror=()=>{URL.revokeObjectURL(u);rej(Error('No se pudo leer esa foto. Prueba con otra (JPG o PNG).'));};im.src=u;});}
async function save(e){
  e.preventDefault();$('edError').textContent='';
  const h=hField.getValue();if(!Number.isFinite(h)||h<-10||h>10){$('edError').textContent='El hándicap del coche debe ser de 0 a 10 segundos (el botón elige si suma o resta).';return;}
  if(!$('nombre').value.trim()){$('edError').textContent='Escribe el nombre o modelo del coche.';$('nombre').focus();return;}
  const pend=$('notaTexto').value.trim();if(pend)notas.unshift({fecha:$('notaFecha').value||'',texto:pend});
  const car={id:editing?editing.id:undefined,nombre:$('nombre').value,escuderia:$('escuderia').value,color:$('color').value,clase:$('clase').value,h,
    chip:$('chip').value?Number($('chip').value):null,techo:$('sinTecho').checked?'':$('techo').value,motor:$('motor').value,peso:$('peso').value===''?null:$('peso').value,
    dueno:$('dueno').value,tipo:$('tipo').value,notas,ejemplo:editing?editing.ejemplo:false};
  $('save').disabled=true;
  try{if(photoRemove&&editing&&editing.foto&&!photoData)await G.post({action:'quitar_foto',id:editing.id});
    const body={action:'save',car};if(photoData)body.image=photoData;await G.post(body);closeEditor();msg('');}
  catch(err){$('edError').textContent=err.message;}finally{$('save').disabled=false;}
}
function wire(){
  H.CLASES.forEach(([k,n])=>{const o=el('option','',H.ICON[k]+' '+n);o.value=k;$('clase').append(o);});
  hField=H.upgrade($('h'),()=>updHelp());
  $('clase').addEventListener('change',updHelp);
  $('add').addEventListener('click',()=>openEditor(null));
  $('tabCasa').addEventListener('click',()=>{tab='casa';render();});$('tabInv').addEventListener('click',()=>{tab='invitado';render();});
  $('tipo').addEventListener('change',()=>{if($('tipo').value==='invitado')$('mas').open=true;});
  $('delGuests').addEventListener('click',async()=>{const n=G.cars().filter(c=>c.tipo==='invitado').length;
    if(!confirm('¿Borrar los '+n+' coches del Garage de invitados? Pasa a la casa antes los que se quedan. Las carreras ya guardadas no cambian.'))return;
    try{await G.post({action:'borrar_invitados'});msg('');}catch(e){msg(e.message);}});
  $('close').addEventListener('click',closeEditor);$('cancel').addEventListener('click',closeEditor);
  $('editor').addEventListener('click',e=>{if(e.target===$('editor'))closeEditor();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('editor').hidden)closeEditor();});
  $('form').addEventListener('submit',save);
  $('sinTecho').addEventListener('change',()=>{$('techo').disabled=$('sinTecho').checked;});
  $('file').addEventListener('change',async()=>{const f=$('file').files[0];$('file').value='';if(!f)return;
    try{photoData=await resize(f);photoRemove=false;setPhoto(photoData);$('edError').textContent='';}catch(e){$('edError').textContent=e.message;}});
  $('noPhoto').addEventListener('click',()=>{photoData=null;photoRemove=true;setPhoto('');});
  $('notaAdd').addEventListener('click',()=>{const t=$('notaTexto').value.trim();if(!t){$('notaTexto').focus();return;}notas.unshift({fecha:$('notaFecha').value||'',texto:t});notas.sort((a,b)=>(b.fecha||'').localeCompare(a.fecha||''));$('notaTexto').value='';renderNotas();});
  $('delete').addEventListener('click',async()=>{if(!editing)return;
    if(!confirm('¿Borrar «'+editing.nombre+'» del Garage? Se borran su ficha, su foto y sus notas. Las carreras ya guardadas no cambian.'))return;
    try{await G.post({action:'delete',id:editing.id});closeEditor();}catch(e){$('edError').textContent=e.message;}});
  G.onChange(()=>{conn(true);render();});
  G.start(4000);loadCfg();setInterval(loadCfg,10000);loadRoster();setInterval(loadRoster,8000);
  if(/[?&]tab=invitados/.test(location.search))tab='invitado';
  setInterval(async()=>{const d=await G.load();conn(!!d);},15000);
}
document.addEventListener('DOMContentLoaded',wire);
window.PeluGaragePage={openEditor,render,setTab:t=>{tab=t;render();}};
})();
