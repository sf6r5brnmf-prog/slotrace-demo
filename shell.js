'use strict';
// Contenedor de la DEMO: arranca el servidor real (Python) dentro del navegador y muestra la app real en un iframe.
(function(){
const V='202611241437';
const PY=['durable.py','instancia.py','handicap.py','garage.py','ranking.py','torneo.py','pits.py','gatillo.py','scx.py','live.py','gp.py','micoche.py','esp32usb.py','server.py','demo_glue.py'];
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
async function persist(force){
  if(!FS||syncing||stopped||(!dirty&&!force))return;
  if(!soyDueno())return;
  syncing=true;dirty=false;
  try{await syncfs(false);}catch(e){dirty=true;}finally{syncing=false;}
}
// Fotos del Garage (data/garage-fotos/*.jpg en IndexedDB): igual que los avatares, como blob:.
function fotoUrl(hex){
  let u=avatarUrls.get('g'+hex);if(u)return u;
  try{const bytes=FS.readFile('/data/garage-fotos/'+hex+'.jpg');u=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}))+'#foto';avatarUrls.set('g'+hex,u);return u;}
  catch(e){return 'data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA=';}
}
function avatarUrl(hex){
  let u=avatarUrls.get(hex);if(u)return u;
  try{const bytes=FS.readFile('/data/avatars/'+hex+'.png');u=URL.createObjectURL(new Blob([bytes],{type:'image/png'}))+'#avatar';avatarUrls.set(hex,u);return u;}
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
function request(method,path,headers,body){
  return new Promise((resolve,reject)=>{
    try{
      method=String(method||'GET').toUpperCase();let b=bodyBytes(body);
      const arg=b;
      const out=glue.request(method,path,JSON.stringify(headersObj(headers)),arg);
      const [status,hdrs,text,isB64]=JSON.parse(out);
      if(method==='POST'){dirty=true;setTimeout(()=>persist(),50);}   // guardar en IndexedDB enseguida (no esperar 4 s)
      let payload;
      if(isB64){const bin=atob(text);const a=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);payload=a;}
      else payload=text.replace(/\/avatars\/([0-9a-f]{32})\.png/g,(m,hex)=>avatarUrl(hex)).replace(/\/garage-fotos\/([0-9a-f]{32})\.jpg/g,(m,hex)=>fotoUrl(hex));
      resolve({status,headers:hdrs,body:payload});
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

async function boot(){
  try{
    progress('Cargando el motor de la pista…',8);
    py=await loadPyodide({indexURL:new URL('pyodide/',location.href).href,stdout:t=>console.log('[pista] '+t),stderr:t=>console.warn('[pista] '+t)});window.__demoPy=py;
    FS=py.FS;progress('Abriendo tus datos guardados…',55);
    await pedirPestana();
    FS.mkdirTree('/data');FS.mount(FS.filesystems.IDBFS,{},'/data');
    try{await syncfs(true);}catch(e){console.warn('IDB',e);}
    progress('Cargando la app…',65);
    FS.mkdirTree('/app/py');
    await Promise.all(PY.map(async f=>{const r=await fetch('py/'+f+'?v='+V);if(!r.ok)throw Error('falta '+f);FS.writeFile('/app/py/'+f,await r.text());}));
    let seeded=false;
    try{FS.stat('/data/pilotos.json');}catch(e){
      FS.mkdirTree('/data/avatars');
      await Promise.all(NAMES.map(async(n,i)=>{const r=await fetch('seed/avatar'+(i+1)+'.png');FS.writeFile('/data/avatars/seed'+(i+1)+'.png',new Uint8Array(await r.arrayBuffer()));}));
      seeded=true;
    }
    progress('Prendiendo la Pit Box simulada…',80);
    py.runPython("import sys\nif '/app/py' not in sys.path: sys.path.insert(0,'/app/py')\nimport demo_glue");
    glue=py.pyimport('demo_glue');
    if(seeded){glue.seed('/data',py.toPy(NAMES));}
    glue.start('/data',Number(new URLSearchParams(location.search).get('x'))||1);
    if(seeded){try{glue.demo_defaults();}catch(e){console.warn(e);}}
    if(seeded){dirty=true;await persist(true);}
    ticker=setInterval(()=>{try{glue.tick();}catch(e){console.error(e);}},25);
    saver=setInterval(()=>{dirty=true;persist();},4000);
    document.addEventListener('visibilitychange',()=>{if(document.hidden)persist(true);else soyDueno();});
    window.addEventListener('pagehide',()=>persist(true));
    progress('¡Listo!',100);
    openPage(startPage());
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
  stopped=true;clearInterval(ticker);clearInterval(saver);
  try{(function rm(dir){FS.readdir(dir).forEach(n=>{if(n==='.'||n==='..')return;const p=dir+'/'+n,st=FS.stat(p);if(FS.isDir(st.mode)){rm(p);FS.rmdir(p);}else FS.unlink(p);});})('/data');
    await syncfs(false);}catch(e){console.error(e);}
  try{Object.keys(localStorage).forEach(k=>localStorage.removeItem(k));}catch(e){}
  location.href=location.pathname;
});
boot();
})();
