'use strict';
// Contenedor de la DEMO: arranca el servidor real (Python) dentro del navegador y muestra la app real en un iframe.
(function(){
const V='202611251205';
// Tus datos viven en IndexedDB «/slotrace». Hasta la versión 202611241610 vivían en «/data»: las pestañas VIEJAS que sigan
// abiertas en el teléfono todavía escriben ahí (y podían borrar coches). Ahora ya no pueden: esta versión solo LEE «/data»
// una vez para traerse tus datos, y nunca escribe en ella.
const D='/slotrace',OLD='/data';
const PY=['durable.py','instancia.py','handicap.py','garage.py','ranking.py','pilotos.py','torneo.py','pits.py','gatillo.py','scx.py','juego.py','live.py','gp.py','micoche.py','esp32usb.py','server.py','demo_glue.py'];
const NAMES=['Ernesto','Pepe','Lalo','Mica'];
const PAGES=['index.html','gp.html','micoche.html','scx.html','garage.html','ranking.html'];
const COLORS=[['Blanco','#edf2f7'],['Amarillo','#ffe23b'],['Rojo','#ff4d50'],['Azul','#3d96ff'],['Verde','#50dc92'],['Naranja','#ff963d']];
const $=id=>document.getElementById(id);
let py=null,glue=null,FS=null,ticker=null,saver=null,syncing=false,dirty=false,stopped=false;
const avatarUrls=new Map();
function progress(msg,pct){$('bootMsg').textContent=msg;$('bootBar').style.width=pct+'%';}
function fail(e){console.error(e);const b=$('bootErr');b.hidden=false;b.textContent='No se pudo arrancar la demo ('+(e&&e.message||e)+'). Revisa el internet y vuelve a cargar la página.';}
function syncfs(populate){return new Promise((res,rej)=>FS.syncfs(populate,err=>err?rej(err):res()));}
// ---------- Una sola pestaña guarda ----------
// Los datos viven en el teléfono (IndexedDB). Si la demo está abierta en dos pestañas, cada una tiene su copia y al
// guardar la vieja BORRABA lo que la otra había agregado (así se perdían coches del Garage). Ahora la pestaña más
// nueva es la dueña: antes de abrir pide a las otras que guarden y se detengan; las otras ya no guardan nada.
const TAB=Math.random().toString(36).slice(2)+Date.now().toString(36),OWNER_KEY='slotrace-demo-dueno';
const chan=('BroadcastChannel' in window)?new BroadcastChannel('slotrace-demo-datos'):null;
let owner=false;
function ownerNow(){try{return localStorage.getItem(OWNER_KEY);}catch(e){return null;}}
function soyDueno(){if(!owner)return false;const o=ownerNow();if(o&&o!==TAB){ceder();return false;}return true;}
function ceder(){
  if(stopped&&!owner)return;owner=false;stopped=true;clearInterval(ticker);clearInterval(saver);
  try{respaldar('otra pestaña tomó el control').catch(()=>{});}catch(e){}
  const b=$('staleTab');if(b)b.hidden=false;
}
async function pedirPestana(){
  // Las pestañas viejas guardan lo último que tienen y se detienen; luego ésta lee los datos ya completos.
  if(chan){
    let n=0;const listo=new Promise(res=>{const t=setTimeout(res,1500);chan.onmessage=e=>{const d=e.data||{};
      if(d.t==='listo'&&d.para===TAB){n++;clearTimeout(t);setTimeout(res,300);}};});
    chan.postMessage({t:'hola',de:TAB});await listo;
  }
  try{localStorage.setItem(OWNER_KEY,TAB);}catch(e){}
  owner=true;
  if(chan)chan.onmessage=async e=>{const d=e.data||{};
    if(d.t==='hola'&&d.de!==TAB){if(owner){try{dirty=true;await persist(true);}catch(x){}}ceder();chan.postMessage({t:'listo',para:d.de});}};
}
// Guardar: en cola (nunca se salta un cambio) y con GUARDIA. IDBFS «sincroniza»: lo que no está en memoria se BORRA del
// teléfono. Por eso, antes de guardar, se compara con lo que ya está guardado: si esta pantalla tiene MENOS coches o pilotos
// que el teléfono y no fue porque tú los borraste aquí, NO se guarda (así ninguna pestaña vieja o arranque fallido borra nada).
let chain=Promise.resolve(),permitido={cars:0,pilotos:0},bloqueado=false;
function persist(force){chain=chain.then(()=>guardar(force)).catch(e=>console.error('guardar',e));return chain;}
async function guardar(force){
  if(!FS||stopped||(!dirty&&!force))return;
  if(!soyDueno())return;
  dirty=false;
  const mem=conteoMem();let idb;
  try{idb=await conteoIDB();}catch(e){dirty=true;console.warn('No pude revisar lo guardado',e);return;}
  if(mem.cars<idb.cars-permitido.cars||mem.pilotos<idb.pilotos-permitido.pilotos||(idb.roster&&!mem.roster)){
    if(!bloqueado){bloqueado=true;console.warn('Guardado BLOQUEADO para no borrar datos',JSON.stringify({mem,idb,permitido}));
      try{await respaldar('pantalla con menos datos que el teléfono (no se guardó)');}catch(e){}
      avisoBloqueo(mem,idb);}
    return;
  }
  syncing=true;
  try{await syncfs(false);
    // IDBFS avisa «listo» antes de que el teléfono confirme; leerlo de vuelta espera a que quede escrito de verdad.
    const ya=await conteoIDB(),m2=conteoMem();
    if(ya.cars!==m2.cars||ya.pilotos!==m2.pilotos||ya.roster!==m2.roster)dirty=true;
    else{permitido={cars:0,pilotos:0};marcarConDatos(m2);}
  }catch(e){dirty=true;}finally{syncing=false;}
  if(!dirty)respaldarLuego();
}
// ---------- conteos (memoria y lo guardado en IndexedDB) ----------
const STORE='FILE_DATA';
function leerJSONmem(f){try{return JSON.parse(new TextDecoder().decode(FS.readFile(D+'/'+f)));}catch(e){return null;}}
function contar(g,r,ro){return {cars:(g&&Array.isArray(g.cars))?g.cars.length:0,pilotos:(r&&Array.isArray(r.pilotos))?r.pilotos.length:0,roster:!!ro};}
function conteoMem(){return contar(leerJSONmem('garage.json'),leerJSONmem('registro.json'),leerJSONmem('pilotos.json'));}
function abrirDB(name,ver,up){return new Promise((res,rej)=>{let q;try{q=indexedDB.open(name,ver);}catch(e){rej(e);return;}q.onupgradeneeded=()=>up(q.result);q.onsuccess=()=>res(q.result);q.onerror=()=>rej(q.error);q.onblocked=()=>rej(Error('IndexedDB ocupado'));});}
function idbDatos(name){return abrirDB(name||D,21,db=>{if(!db.objectStoreNames.contains(STORE))db.createObjectStore(STORE).createIndex('timestamp','timestamp',{unique:false});});}
async function conteoIDB(){
  const db=await idbDatos();
  try{const leer=k=>new Promise((res,rej)=>{const t=db.transaction(STORE,'readonly').objectStore(STORE).get(k);t.onsuccess=()=>{const v=t.result;try{res(v&&v.contents?JSON.parse(new TextDecoder().decode(v.contents)):null);}catch(e){res(null);}};t.onerror=()=>rej(t.error);});
    const total=await new Promise((res,rej)=>{const t=db.transaction(STORE,'readonly').objectStore(STORE).count();t.onsuccess=()=>res(t.result);t.onerror=()=>rej(t.error);});
    return Object.assign(contar(await leer(D+'/garage.json'),await leer(D+'/registro.json'),await leer(D+'/pilotos.json')),{total});}
  finally{db.close();}
}
function marcarConDatos(m){try{if(m.cars||m.pilotos||m.roster)localStorage.setItem('slotrace-respaldo-hay-datos',JSON.stringify({cars:m.cars,pilotos:m.pilotos,at:Date.now()}));}catch(e){}}
// ---------- respaldos automáticos (otra base de datos: IDBFS nunca la toca) ----------
const RDB='slotrace-respaldos',MAXR=10;
function idbResp(){return abrirDB(RDB,1,db=>{if(!db.objectStoreNames.contains('snaps'))db.createObjectStore('snaps',{keyPath:'id',autoIncrement:true});});}
function archivosMem(){const out={};(function rec(dir){let ls=[];try{ls=FS.readdir(dir);}catch(e){return;}ls.forEach(n=>{if(n==='.'||n==='..')return;const p=dir+'/'+n;const st=FS.stat(p);if(FS.isDir(st.mode))rec(p);else out[p.slice(D.length+1)]=FS.readFile(p);});})(D);return out;}
const TXT=['garage.json','registro.json','pilotos.json','inscritos.json','ranking.json','lap-config.json','gp-config.json'];
function firmaMem(){return TXT.map(f=>{try{return new TextDecoder().decode(FS.readFile(D+'/'+f));}catch(e){return '';}}).join('\u0001');}
let ultimaFirma=null,respTimer=null;
function respaldarLuego(){clearTimeout(respTimer);respTimer=setTimeout(()=>respaldar('automático').catch(e=>console.warn('respaldo',e)),1500);}
async function listaRespaldos(){const db=await idbResp();try{return await new Promise((res,rej)=>{const t=db.transaction('snaps','readonly').objectStore('snaps').getAll();t.onsuccess=()=>res(t.result||[]);t.onerror=()=>rej(t.error);});}finally{db.close();}}
async function respaldar(motivo,forzar){
  if(!FS)return;const m=conteoMem();if(!m.cars&&!m.pilotos)return;
  const firma=firmaMem();if(!forzar&&firma===ultimaFirma)return;
  const g=leerJSONmem('garage.json'),r=leerJSONmem('registro.json');
  const snap={at:Date.now(),v:V,motivo,cars:m.cars,pilotos:m.pilotos,coches:((g&&g.cars)||[]).map(c=>c.nombre).slice(0,40),nombres:((r&&r.pilotos)||[]).map(p=>p.name).slice(0,60),firma:firma.length+':'+hash(firma),files:archivosMem()};
  const db=await idbResp();
  try{const todos=await new Promise((res,rej)=>{const t=db.transaction('snaps','readonly').objectStore('snaps').getAll();t.onsuccess=()=>res(t.result||[]);t.onerror=()=>rej(t.error);});
    if(!forzar&&todos.length&&todos[todos.length-1].firma===snap.firma){ultimaFirma=firma;return;}
    await new Promise((res,rej)=>{const tx=db.transaction('snaps','readwrite');const st=tx.objectStore('snaps');st.add(snap);
      // Se quedan los 10 más nuevos y, siempre, el que tiene MÁS coches.
      const lista=todos.concat([snap]);const max=lista.reduce((a,b)=>(b.cars>a.cars||(b.cars===a.cars&&b.at>a.at))?b:a,lista[0]);
      todos.slice(0,Math.max(0,todos.length+1-MAXR)).forEach(x=>{if(x!==max&&x.id!=null)st.delete(x.id);});
      tx.oncomplete=res;tx.onerror=()=>rej(tx.error);});
    ultimaFirma=firma;
  }finally{db.close();}
  // Copia corta (solo los datos, sin fotos) también en localStorage.
  try{const files={};TXT.forEach(f=>{try{files[f]=new TextDecoder().decode(FS.readFile(D+'/'+f));}catch(e){}});
    const prev=JSON.parse(localStorage.getItem('slotrace-respaldo-max')||'null');const lite={at:snap.at,v:V,cars:m.cars,pilotos:m.pilotos,coches:snap.coches,nombres:snap.nombres,files};
    localStorage.setItem('slotrace-respaldo-ultimo',JSON.stringify(lite));
    if(!prev||m.cars>=prev.cars)localStorage.setItem('slotrace-respaldo-max',JSON.stringify(lite));}catch(e){console.warn('respaldo corto',e);}
}
function hash(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return (h>>>0).toString(36);}
// Fotos del Garage (data/garage-fotos/*.jpg en IndexedDB): igual que los avatares, como blob:.
function fotoUrl(hex){
  let u=avatarUrls.get('g'+hex);if(u)return u;
  try{const bytes=FS.readFile(D+'/garage-fotos/'+hex+'.jpg');u=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}))+'#foto';avatarUrls.set('g'+hex,u);return u;}
  catch(e){return 'data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA=';}
}
function avatarUrl(hex){
  let u=avatarUrls.get(hex);if(u)return u;
  try{const bytes=FS.readFile(D+'/avatars/'+hex+'.png');u=URL.createObjectURL(new Blob([bytes],{type:'image/png'}))+'#avatar';avatarUrls.set(hex,u);return u;}
  catch(e){return 'data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA=';}
}
function bodyBytes(b){
  if(b==null)return null;if(typeof b==='string')return b;
  if(b instanceof ArrayBuffer)return new Uint8Array(b);if(ArrayBuffer.isView(b))return new Uint8Array(b.buffer,b.byteOffset,b.byteLength);
  return String(b);
}
function headersObj(h){const o={};if(!h)return o;if(typeof h.forEach==='function'&&!Array.isArray(h)){h.forEach((v,k)=>o[k]=v);return o;}
  if(Array.isArray(h)){h.forEach(([k,v])=>o[k]=v);return o;}return Object.assign(o,h);}
// Una petición al servidor de la pista (Python). Devuelve {status, headers, body} con los avatares como blob:.
let entrega=Promise.resolve();
function request(method,path,headers,body){
  return new Promise((resolve,reject)=>{
    try{
      method=String(method||'GET').toUpperCase();let b=bodyBytes(body);
      const arg=b;
      const antes=method==='POST'?conteoMem():null;
      const out=glue.request(method,path,JSON.stringify(headersObj(headers)),arg);
      const [status,hdrs,text,isB64]=JSON.parse(out);
      let guardado=null;
      if(method==='POST'){const d=conteoMem();   // lo que TÚ borras aquí sí se puede guardar
        permitido.cars+=Math.max(0,antes.cars-d.cars);permitido.pilotos+=Math.max(0,antes.pilotos-d.pilotos);
        dirty=true;guardado=persist();}        // guardar en IndexedDB YA y esperar a que quede guardado
      let payload;
      if(isB64){const bin=atob(text);const a=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);payload=a;}
      else payload=text.replace(/\/avatars\/([0-9a-f]{32})\.png/g,(m,hex)=>avatarUrl(hex)).replace(/\/garage-fotos\/([0-9a-f]{32})\.jpg/g,(m,hex)=>fotoUrl(hex));
      // respuestas EN ORDEN: una lectura no se adelanta a un guardado pendiente (si no, la app ve datos a medias)
      const listo=guardado?Promise.race([guardado,new Promise(r=>setTimeout(r,4000))]):null;
      entrega=entrega.then(()=>listo).then(()=>resolve({status,headers:hdrs,body:payload}),()=>resolve({status,headers:hdrs,body:payload}));
    }catch(e){console.error('DEMO request',path,e);resolve({status:500,headers:{'Content-Type':'application/json; charset=utf-8'},body:JSON.stringify({error:'Algo falló en el servidor de la demo.'})});}
  });
}
async function download(path){
  const r=await request('GET',path,{},null);
  if(r.status!==200){alert('No hay datos para exportar todavía.');return;}
  const cd=r.headers['Content-Disposition']||'',m=cd.match(/filename="([^"]+)"/),name=m?m[1]:'resultados.csv';
  const blob=new Blob([r.body],{type:(r.headers['Content-Type']||'text/csv')}),a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download=name;document.body.append(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},4000);
}
window.DEMO_API={request,download,get ready(){return !!glue;}};

// Datos de la versión anterior (IndexedDB «/data»): solo se LEEN.
async function leerViejo(){
  const db=await idbDatos(OLD);
  try{return await new Promise((res,rej)=>{const files={};let at=0;const t=db.transaction(STORE,'readonly').objectStore(STORE).openCursor();
    t.onsuccess=()=>{const c=t.result;if(!c){res({files,at});return;}const v=c.value,k=String(c.key);
      if(v&&v.contents&&k.startsWith(OLD+'/')){files[k.slice(OLD.length+1)]=v.contents;at=Math.max(at,v.timestamp?new Date(v.timestamp).getTime():0);}c.continue();};
    t.onerror=()=>rej(t.error);});}finally{db.close();}
}
function txt(u8){try{return JSON.parse(new TextDecoder().decode(u8));}catch(e){return null;}}
async function viejoComoRespaldo(){
  const o=await leerViejo();if(!o.files['pilotos.json'])return null;
  const g=txt(o.files['garage.json']),r=txt(o.files['registro.json']),c=contar(g,r,true);
  return {at:o.at||Date.now(),v:'anterior',motivo:'datos de la versión anterior de la demo',cars:c.cars,pilotos:c.pilotos,coches:((g&&g.cars)||[]).map(x=>x.nombre),nombres:((r&&r.pilotos)||[]).map(x=>x.name),files:o.files};
}
async function traerDeVersionAnterior(){
  try{FS.stat(D+'/pilotos.json');return false;}catch(e){}
  let idb=null;try{idb=await conteoIDB();}catch(e){return false;}
  if(idb.total>0)return false;
  const o=await leerViejo();if(!o.files['pilotos.json'])return false;
  Object.entries(o.files).forEach(([rel,data])=>{const p=D+'/'+rel;FS.mkdirTree(p.slice(0,p.lastIndexOf('/')));FS.writeFile(p,data);});
  console.log('Datos traídos de la versión anterior:',Object.keys(o.files).length,'archivos');return true;
}
// Leer lo guardado; en iPhone a veces IndexedDB falla al volver del fondo («Connection … lost»): se reintenta.
async function leerGuardado(){
  let err=null;
  for(let k=0;k<4;k++){
    try{await syncfs(true);
      let idb=null;try{idb=await conteoIDB();}catch(e){}
      const m=conteoMem();
      if(!idb||idb.total===0||m.roster||!idb.roster)return;   // leído bien (o de verdad no hay nada)
      err=Error('lectura incompleta');
    }catch(e){err=e;console.warn('IDB',e);}
    await new Promise(r=>setTimeout(r,600*(k+1)));
  }
  throw Error('No pude leer tus datos guardados en este teléfono ('+(err&&err.message||err)+'). NO borré nada. Cierra esta pestaña y vuelve a abrir la liga.');
}
async function boot(){
  try{
    progress('Cargando el motor de la pista…',8);
    py=await loadPyodide({indexURL:new URL('pyodide/',location.href).href,stdout:t=>console.log('[pista] '+t),stderr:t=>console.warn('[pista] '+t)});window.__demoPy=py;
    FS=py.FS;progress('Abriendo tus datos guardados…',55);
    await pedirPestana();
    FS.mkdirTree(D);FS.mount(FS.filesystems.IDBFS,{},D);
    await leerGuardado();
    try{if(await traerDeVersionAnterior())dirty=true;}catch(e){console.warn('versión anterior',e);}
    progress('Cargando la app…',65);
    FS.mkdirTree('/app/py');
    await Promise.all(PY.map(async f=>{const r=await fetch('py/'+f+'?v='+V);if(!r.ok)throw Error('falta '+f);FS.writeFile('/app/py/'+f,await r.text());}));
    let seeded=false;
    try{FS.stat(D+'/pilotos.json');}catch(e){
      // ¿De verdad es la primera vez? Si este teléfono ya tenía datos, NO se siembra nada encima.
      let hay=false;try{hay=!!localStorage.getItem('slotrace-respaldo-hay-datos');}catch(_){}
      let idb=null;try{idb=await conteoIDB();}catch(_){}
      if(hay||!idb||idb.total>0)throw Error('No pude leer tus datos guardados en este teléfono. NO borré nada. Cierra esta pestaña, vuelve a abrir la liga y, si sigue, abre el menú DEMO → ♻️ Recuperar.');
      FS.mkdirTree(D+'/avatars');
      await Promise.all(NAMES.map(async(n,i)=>{const r=await fetch('seed/avatar'+(i+1)+'.png');FS.writeFile(D+'/avatars/seed'+(i+1)+'.png',new Uint8Array(await r.arrayBuffer()));}));
      seeded=true;
    }
    progress('Prendiendo la Pit Box simulada…',80);
    py.runPython("import sys\nif '/app/py' not in sys.path: sys.path.insert(0,'/app/py')\nimport demo_glue");
    glue=py.pyimport('demo_glue');
    if(seeded){glue.seed(D,py.toPy(NAMES));}
    glue.start(D,Number(new URLSearchParams(location.search).get('x'))||1);
    if(seeded){try{glue.demo_defaults();}catch(e){console.warn(e);}}
    if(seeded){dirty=true;await persist(true);}else if(dirty)await persist(true);
    ticker=setInterval(()=>{try{glue.tick();}catch(e){console.error(e);}},25);
    saver=setInterval(()=>{dirty=true;persist();},4000);
    // Al volver a esta pestaña: si otra pestaña vieja dejó tus coches en la versión anterior, se ofrece recuperarlos.
    document.addEventListener('visibilitychange',()=>{if(document.hidden)persist(true);else if(soyDueno())setTimeout(()=>ofrecerRespaldo().catch(()=>{}),1200);});
    window.addEventListener('pagehide',()=>persist(true));
    progress('¡Listo!',100);
    openPage(startPage());
    if(!seeded)marcarConDatos(conteoMem());
    setTimeout(()=>{respaldar('al abrir').catch(()=>{});ofrecerRespaldo().catch(e=>console.warn(e));},2500);
  }catch(e){fail(e);}
}
function startPage(){const p=new URLSearchParams(location.search).get('p')||'index.html';const name=p.split('?')[0];return PAGES.includes(name)?p:'index.html';}
function openPage(p){
  const f=$('app');f.src='app/'+p;
  f.addEventListener('load',()=>{$('boot').hidden=true;f.hidden=false;$('demoChip').hidden=false;
    try{const loc=f.contentWindow.location,page=loc.pathname.split('/').pop()+loc.search;const q=new URLSearchParams(location.search);q.set('p',page);const u='?'+q.toString();if(location.search!==u)history.replaceState(null,'',u);document.title=f.contentDocument.title+' · DEMO';}catch(e){}
  });
}
// ---------- menú DEMO ----------
function msg(t){$('dmMsg').textContent=t;clearTimeout(msg.t);msg.t=setTimeout(()=>$('dmMsg').textContent='',4000);}
async function post(path,body){const r=await request('POST',path,{'Content-Type':'application/json','X-Roster':'1'},JSON.stringify(body));let d={};try{d=JSON.parse(r.body);}catch(e){}if(r.status!==200)throw Error(d.error||'No se pudo');return d;}
function buildCars(){
  const box=$('dmCars');box.replaceChildren();
  COLORS.forEach(([n,c],i)=>{const d=document.createElement('div');d.className='dm-car';d.style.setProperty('--team',c);d.style.border='1px solid #303743';d.style.borderRadius='10px';
    const b=document.createElement('b');b.textContent='Coche '+(i+1)+' · '+n;const s=document.createElement('span');
    const lap=document.createElement('button');lap.type='button';lap.textContent='⏱ Pasa meta';lap.onclick=async()=>{try{const r=await post('/api/scx/simular',{car:i+1});msg(r.accepted&&r.accepted.length!==0?'Coche '+(i+1)+' pasó por la meta.':'Coche '+(i+1)+' pasó por la meta (no cuenta si no está corriendo o es muy pronto).');}catch(e){msg(e.message);}};
    const pit=document.createElement('button');pit.type='button';pit.textContent='🔧 A pits';pit.onclick=async()=>{try{await post('/api/sim',{pit:i+1});msg('Coche '+(i+1)+' entra a pits en su próxima pasada.');}catch(e){msg(e.message);}};
    s.append(lap,pit);d.append(b,s);box.append(d);});
}
$('demoChip').addEventListener('click',()=>{buildCars();$('demoMenu').hidden=false;});
$('dmClose').addEventListener('click',()=>$('demoMenu').hidden=true);
$('demoMenu').addEventListener('click',e=>{if(e.target===$('demoMenu'))$('demoMenu').hidden=true;});
$('dmFalse').addEventListener('click',async()=>{try{await post('/api/sim',{false_start:true});msg('En el próximo semáforo un coche sale antes del verde.');}catch(e){msg(e.message);}});
// Torneo: 12 pilotos de ejemplo (3 expertos, 5 intermedios, 4 novatos) y mangas de 1 minuto para enseñarlo rápido.
const TORNEO_DEMO=[['Ernesto','experto'],['Pepe','experto'],['Lalo','intermedio'],['Mica','novato'],['Javi','experto'],['Kike','intermedio'],['Memo','intermedio'],['Paco','novato'],['Toño','intermedio'],['Beto','novato'],['Chuy','intermedio'],['Rafa','novato']];
$('dmTorneo').addEventListener('click',async()=>{
  try{// Cada piloto corre con un coche del Garage: 8 de ejemplo + 4 de invitados nuevos, uno distinto por piloto.
    let g=await post('/api/garage',{action:'ejemplos'});const ids=g.cars.filter(c=>!/^Coche de .* \(ejemplo\)$/.test(c.nombre)).map(c=>c.id).slice(0,8);
    const CL=['sin_iman','con_iman','modificado'];
    for(let k=ids.length;k<TORNEO_DEMO.length;k++){const nm=TORNEO_DEMO[k][0];const ya=g.cars.find(c=>c.nombre==='Coche de '+nm+' (ejemplo)');if(ya){ids.push(ya.id);continue;}const d=await post('/api/garage',{action:'rapido',car:{nombre:'Coche de '+nm+' (ejemplo)',clase:CL[k%3],h:0,dueno:nm}});ids.push(d.saved);}
    await post('/api/inscritos',{pilotos:TORNEO_DEMO.map(([name,nivel],k)=>({name,nivel,garage_id:ids[k]}))});
    await post('/api/gp/config',{config:{torneo_cars:3,torneo_minutes:1,torneo_final_laps:5,preset:'personal'}});
    msg('Listo: 12 pilotos inscritos, cada uno con su coche del Garage, mangas de 1 min. Abriendo Gran Premio → Torneo por mangas…');
    const f=$('app');setTimeout(()=>{$('demoMenu').hidden=true;try{f.contentWindow.location.href=new URL('gp.html?tab=torneo',f.contentWindow.location.href).href;}catch(e){}},900);
  }catch(e){msg(e.message);}
});
// 🏎️ Garage de ejemplo: 6 coches de la casa + 2 de invitados, marcados «(ejemplo)». Nadie los lleva hasta que el piloto lo escoge.
$('dmGarage').addEventListener('click',async()=>{
  try{const d=await post('/api/garage',{action:'ejemplos'});
    msg(d.agregados?'Listo: '+d.agregados+' coches de ejemplo (6 de la casa y 2 de invitados). Cada piloto escoge su coche y su mando al armar la carrera. Abriendo el Garage…':'El garage de ejemplo ya estaba cargado. Abriendo el Garage…');
    const f=$('app');setTimeout(()=>{$('demoMenu').hidden=true;try{f.contentWindow.location.href=new URL('garage.html',f.contentWindow.location.href).href;}catch(e){}},900);
  }catch(e){msg(e.message);}
});
$('staleReload').addEventListener('click',()=>location.reload());
$('dmReset').addEventListener('click',async()=>{
  if(!confirm('¿Restablecer la demo? Se borran los pilotos, los coches del Garage, la configuración y las carreras de este teléfono, y vuelven los pilotos de ejemplo.'))return;
  try{await respaldar('antes de restablecer',true);}catch(e){}
  stopped=true;clearInterval(ticker);clearInterval(saver);
  try{(function rm(dir){FS.readdir(dir).forEach(n=>{if(n==='.'||n==='..')return;const p=dir+'/'+n,st=FS.stat(p);if(FS.isDir(st.mode)){rm(p);FS.rmdir(p);}else FS.unlink(p);});})(D);
    await syncfs(false);await conteoIDB();}catch(e){console.error(e);}
  try{Object.keys(localStorage).forEach(k=>{if(!k.startsWith('slotrace-respaldo'))localStorage.removeItem(k);});localStorage.removeItem('slotrace-respaldo-hay-datos');}catch(e){}
  location.href=location.pathname;
});
// ---------- ♻️ Recuperar / Exportar / Importar ----------
function fecha(t){const d=new Date(t);return d.toLocaleDateString('es-MX',{day:'2-digit',month:'2-digit'})+' '+d.toLocaleTimeString('es-MX',{hour:'2-digit',minute:'2-digit'});}
function avisoBloqueo(mem,idb){$('bloqueoMsg').textContent='En este teléfono hay '+idb.cars+' coche'+(idb.cars===1?'':'s')+' y '+idb.pilotos+' piloto'+(idb.pilotos===1?'':'s')+' guardados, y esta pantalla tiene '+mem.cars+' y '+mem.pilotos+'. Toca «Recargar» para ver lo guardado.';$('bloqueo').hidden=false;}
$('bloqueoRecargar').addEventListener('click',()=>location.reload());
function liteDeLS(){const out=[];['slotrace-respaldo-max','slotrace-respaldo-ultimo'].forEach(k=>{try{const x=JSON.parse(localStorage.getItem(k)||'null');if(x&&x.files&&!out.some(o=>o.at===x.at))out.push(Object.assign(x,{lite:true,motivo:'copia corta (sin fotos)'}));}catch(e){}});return out;}
async function todosRespaldos(){let l=[];try{l=await listaRespaldos();}catch(e){console.warn(e);}
  try{const v=await viejoComoRespaldo();if(v&&v.cars>0)l.push(v);}catch(e){}return l.concat(liteDeLS().filter(x=>!l.some(y=>Math.abs(y.at-x.at)<5000))).sort((a,b)=>b.at-a.at);}
async function abrirRescate(msg){
  const l=await todosRespaldos(),box=$('rescLista');box.replaceChildren();const m=conteoMem();
  $('rescMsg').textContent=msg||('Ahora hay '+m.cars+' coche'+(m.cars===1?'':'s')+' y '+m.pilotos+' piloto'+(m.pilotos===1?'':'s')+'. Elige un respaldo para dejar todo como estaba en ese momento (lo de ahora también se respalda antes).');
  const max=l.reduce((a,b)=>!a||b.cars>a.cars?b:a,null);
  if(!l.length){const li=document.createElement('li');li.textContent='Todavía no hay respaldos en este teléfono.';box.append(li);}
  l.forEach(x=>{const li=document.createElement('li');if(x===max&&x.cars>m.cars)li.className='mejor';const b=document.createElement('b');b.textContent=fecha(x.at)+' · '+x.cars+' coche'+(x.cars===1?'':'s')+' · '+x.pilotos+' piloto'+(x.pilotos===1?'':'s');
    const bt=document.createElement('button');bt.type='button';bt.textContent='Recuperar';bt.addEventListener('click',()=>restaurar(x));
    const sm=document.createElement('small');sm.textContent=(x.coches&&x.coches.length?'🏎️ '+x.coches.join(', '):'Sin coches')+(x.nombres&&x.nombres.length?' · 👥 '+x.nombres.slice(0,12).join(', '):'')+' · '+(x.motivo||'')+(x.lite?'':'')+' · v'+(x.v||'?');
    li.append(b,bt,sm);box.append(li);});
  $('demoMenu').hidden=true;$('rescate').hidden=false;
}
$('rescCerrar').addEventListener('click',()=>$('rescate').hidden=true);
$('dmRecuperar').addEventListener('click',()=>abrirRescate().catch(e=>msg(e.message)));
let ofrecido='';
async function ofrecerRespaldo(){
  if(stopped||!$('rescate').hidden)return;
  const m=conteoMem(),l=await todosRespaldos();const best=l.reduce((a,b)=>!a||b.cars>a.cars?b:a,null);
  const k=best?best.at+':'+best.cars+':'+m.cars:'';if(k===ofrecido)return;   // no insistir con el mismo
  if(best&&best.cars>m.cars){ofrecido=k;abrirRescate('Encontré un respaldo del '+fecha(best.at)+' con '+best.cars+' coche'+(best.cars===1?'':'s')+' ('+(best.coches||[]).slice(0,6).join(', ')+'). Ahora solo hay '+m.cars+'. Toca «Recuperar» en el que quieras.');}
}
function b64(u8){let s='';for(let i=0;i<u8.length;i+=0x8000)s+=String.fromCharCode.apply(null,u8.subarray(i,i+0x8000));return btoa(s);}
function unb64(t){const b=atob(t),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a;}
async function restaurar(x){
  const n=x.cars+' coche'+(x.cars===1?'':'s')+' y '+x.pilotos+' piloto'+(x.pilotos===1?'':'s');
  if(!confirm('¿Dejar todo como estaba el '+fecha(x.at)+' ('+n+')?\n\nLo que hay ahora también se guarda como respaldo, por si acaso.'+(x.lite?'\n\nEsta copia no trae fotos: los coches y pilotos vuelven, las fotos no.':'')))return;
  try{await respaldar('antes de recuperar',true);}catch(e){}
  stopped=true;clearInterval(ticker);clearInterval(saver);
  try{await chain;}catch(e){}
  // Se ESCRIBE encima (borrar y volver a crear el mismo archivo confunde al sistema de archivos de la demo);
  // luego se quitan los archivos que el respaldo no tiene.
  const keep=new Set();
  Object.entries(x.files).forEach(([rel,data])=>{const p=D+'/'+rel;FS.mkdirTree(p.slice(0,p.lastIndexOf('/')));FS.writeFile(p,typeof data==='string'?(x.b64?unb64(data):data):data);keep.add(p);});
  (function rm(dir){FS.readdir(dir).forEach(k=>{if(k==='.'||k==='..')return;const p=dir+'/'+k,st=FS.stat(p);if(FS.isDir(st.mode))rm(p);else if(!keep.has(p))FS.unlink(p);});})(D);
  const m=conteoMem();
  for(let k=0;k<3;k++){await syncfs(false);const ya=await conteoIDB();if(ya.cars===m.cars&&ya.pilotos===m.pilotos&&ya.roster===m.roster)break;}
  marcarConDatos(m);
  location.reload();
}
$('dmExportar').addEventListener('click',()=>{
  try{const files={};Object.entries(archivosMem()).forEach(([k,v])=>files[k]=b64(v));const m=conteoMem(),g=leerJSONmem('garage.json')||{};
    const doc={app:'slotrace-demo',tipo:'respaldo',v:V,at:Date.now(),cars:m.cars,pilotos:m.pilotos,coches:(g.cars||[]).map(c=>c.nombre),b64:true,files};
    const d=new Date(),nm='slotrace-respaldo-'+d.getFullYear()+String(d.getMonth()+1).padStart(2,'0')+String(d.getDate()).padStart(2,'0')+'-'+String(d.getHours()).padStart(2,'0')+String(d.getMinutes()).padStart(2,'0')+'.json';
    const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(doc)],{type:'application/json'}));a.download=nm;document.body.append(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},4000);
    msg('Respaldo listo: '+nm+' ('+m.cars+' coches, '+m.pilotos+' pilotos). Guárdalo en Archivos o iCloud.');}catch(e){msg('No se pudo exportar: '+e.message);}
});
$('dmImportar').addEventListener('change',async e=>{
  const f=e.target.files[0];e.target.value='';if(!f)return;
  try{const doc=JSON.parse(await f.text());if(!doc||doc.app!=='slotrace-demo'||!doc.files)throw Error('Ese archivo no es un respaldo de la demo.');
    if(!doc.files['pilotos.json'])throw Error('El respaldo está incompleto.');
    await restaurar(Object.assign({motivo:'archivo '+f.name},doc));}catch(er){msg(er.message);}
});
window.__demoRespaldos={todosRespaldos,restaurar,conteoIDB,conteoMem};
boot();
})();
