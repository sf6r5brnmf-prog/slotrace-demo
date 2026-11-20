'use strict';
// Compartido por el menú (/) y el Gran Premio (/gp):
// - errores de red en español (nunca "Failed to fetch"),
// - avisos de arranque del servidor (archivos recuperados tras un apagón, configuración dañada…),
// - detectar que el servidor se reinició para no quedarse con datos viejos en pantalla.
(function(){
  const RED='No hay conexión con la Mac. Si se cerró o se fue la luz: ábrela, inicia sesión y espera un minuto; luego vuelve a intentar.';
  const rawFetch=window.fetch.bind(window);
  window.fetch=async function(...args){
    try{return await rawFetch(...args);}
    catch(e){if(e&&e.name==='AbortError')throw e;throw new TypeError(RED);}
  };
  const rawJson=Response.prototype.json;
  Response.prototype.json=async function(){
    try{return await rawJson.call(this);}
    catch(e){throw new SyntaxError('La Mac respondió algo inesperado. Vuelve a intentar en unos segundos.');}
  };
  let lastBoot=null;
  function show(boot,list){
    const box=document.getElementById('avisos');if(!box)return;
    list=Array.isArray(list)?list.filter(x=>typeof x==='string'&&x):[];
    let seen=false;try{seen=localStorage.getItem('avisos-vistos')===boot;}catch(e){}
    if(!list.length||seen){if(!box.hidden)box.hidden=true;return;}
    const sig=boot+'|'+list.join('|');if(box.dataset.sig===sig&&!box.hidden)return;box.dataset.sig=sig;
    box.replaceChildren();
    const t=document.createElement('strong');t.textContent='Aviso al arrancar el servidor';box.append(t);
    list.forEach(x=>{const p=document.createElement('p');p.textContent=x;box.append(p);});
    const b=document.createElement('button');b.type='button';b.textContent='Entendido';
    b.addEventListener('click',()=>{try{localStorage.setItem('avisos-vistos',boot);}catch(e){}box.hidden=true;});
    box.append(b);box.hidden=false;
  }
  // true solo la primera vez que llega un arranque distinto al que ya conocía esta pantalla.
  function restarted(boot){if(!boot)return false;const r=lastBoot!==null&&boot!==lastBoot;lastBoot=boot;return r;}
  function offlineText(failures){return failures>=5?'Sin conexión con la Mac · reintentando solo. Si se cerró o se fue la luz, ábrela e inicia sesión.':'Conexión con la Mac intermitente · reintentando';}
  window.PeluAvisos={show,restarted,offlineText,RED};
})();
