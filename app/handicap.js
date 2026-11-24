'use strict';
// Handicap · ajuste de tiempo por vuelta por clase de coche (Con imán / Sin imán / Modificado).
// Compartido por Práctica/Carrera (app.js), Gran Premio (gp.js) y Mi coche (micoche.js). Los cálculos y el orden
// los hace la Mac; aquí solo se muestran: tiempo con handicap + «H» chiquita, y el tiempo real abajo.
(function(){
  const CLASES=[['sin_iman','Sin imán'],['con_iman','Con imán'],['modificado','Modificado']];
  const ICON={sin_iman:'○',con_iman:'🧲',modificado:'🔧'};
  const NOMBRE=Object.fromEntries(CLASES);
  function segTxt(v){v=Number(v)||0;if(!v)return '0 s';return (v>0?'+':'−')+String(Math.round(Math.abs(v)*100)/100)+' s';}
  // Con ajuste negativo, la vuelta ajustada nunca baja de MIN_VUELTA_H (igual que en la Mac, handicap.py).
  const MIN_VUELTA_H=1.0;
  function adj(raw,h){if(raw==null||!Number.isFinite(Number(raw)))return null;raw=Number(raw);h=Number(h)||0;let v=raw+h;if(h<0)v=Math.max(v,Math.min(raw,MIN_VUELTA_H));return Math.round(v*1000)/1000;}
  // Campo de segundos con botón de signo: el teclado numérico del iPhone no tiene «−». Botón grande «+ suma» / «− resta»
  // a la izquierda y el número (siempre positivo, 0 a 10) a la derecha. Valor guardado = signo × número.
  // upgrade(input, onChange) envuelve un <input> existente y le pone input.hcField = {setValue, getValue}.
  function upgrade(inp,onChange){
    if(inp.hcField)return inp.hcField;
    const wrap=document.createElement('span');wrap.className='hc-signed';
    const btn=document.createElement('button');btn.type='button';btn.className='hc-sign';
    const txt=document.createElement('small');txt.className='hc-sign-txt';txt.setAttribute('aria-live','polite');
    inp.type='number';inp.min='0';inp.max='10';inp.step='0.1';inp.inputMode='decimal';
    inp.parentNode.insertBefore(wrap,inp);const line=document.createElement('span');line.className='hc-signed-line';line.append(btn,inp);wrap.append(line,txt);
    let neg=false;
    const mag=()=>{const s=String(inp.value).trim().replace(',','.');if(s==='')return 0;const m=Number(s);return Number.isFinite(m)?m:NaN;};
    function getValue(){const m=mag();if(!Number.isFinite(m)||m<0||m>10)return NaN;const v=Math.round(m*100)/100;return v?(neg?-v:v):0;}
    function paint(){btn.textContent=neg?'−':'+';btn.classList.toggle('neg',neg);wrap.classList.toggle('neg',neg);btn.setAttribute('aria-pressed',neg?'true':'false');
      btn.setAttribute('aria-label',neg?'Resta segundos. Toca para que sume.':'Suma segundos. Toca para que reste.');btn.title=neg?'Resta (toca para sumar)':'Suma (toca para restar)';
      const v=getValue();txt.textContent=Number.isFinite(v)?(v?(v<0?'resta ':'suma ')+segTxt(v).replace(/^[+−]/,'')+' por vuelta → '+segTxt(v):'0 s · no cambia'):'número de 0 a 10';}
    function setValue(v){v=Number(v)||0;neg=v<0;inp.value=String(Math.round(Math.abs(v)*100)/100);paint();}
    // En la Mac sí se puede teclear «-0.5»: se acepta y se pasa al botón.
    inp.addEventListener('input',paint);
    inp.addEventListener('change',()=>{const m=mag();if(Number.isFinite(m)&&m<0){neg=true;inp.value=String(Math.abs(m));}paint();if(onChange)onChange(getValue());});
    btn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();neg=!neg;paint();if(onChange)onChange(getValue());});
    const f={setValue,getValue,input:inp,button:btn,wrap};inp.hcField=f;wrap.hcField=f;paint();return f;
  }
  function label(clase,h){return (ICON[clase]||'')+' '+(NOMBRE[clase]||'Sin imán')+' '+segTxt(h);}
  // Nivel del piloto (registro de pilotos): también suma o resta segundos por vuelta. Ajuste total = coche + nivel.
  const NIVELES=[['novato','Novato'],['intermedio','Intermedio'],['experto','Experto']];
  const NIVEL=Object.fromEntries(NIVELES),NIVEL_ICON={novato:'🟢',intermedio:'🔵',experto:'🟡'};
  const AUTO=[['sugerir','Sugerir: aparece «Nivel sugerido» y lo aceptas con un toque'],['auto','Cambiar solo al terminar cada carrera'],['apagado','Apagado (el nivel solo lo cambias tú)']];
  const CORTES_FAB={sin_iman:{experto:12,novato:14},con_iman:{experto:11,novato:13},modificado:{experto:10.5,novato:12.5}};
  function nivelTxt(n){return NIVEL[n]||'Intermedio';}
  function num(x){return String(Math.round(Number(x)*100)/100);}
  // «🧲 +0.5 s · Experto +0.3 s» (las dos partes del ajuste). r = fila con clase, h_coche, nivel, h_nivel, h_s.
  function detalle(r){
    if(!r)return '';if(r.h_txt)return r.h_txt;
    if(r.h_coche==null&&r.h_nivel==null)return r.clase?label(r.clase,r.h_s):'';
    const p=[];if(r.h_coche&&r.h_nivel)p.push((ICON[r.clase]||'')+' '+segTxt(r.h_coche));else if(r.h_coche||!r.h_nivel)p.push(label(r.clase,r.h_coche||0));if(r.h_nivel)p.push(nivelTxt(r.nivel)+' '+segTxt(r.h_nivel));return p.join(' · ');
  }
  function cortesTxt(c){return 'Experto < '+num(c.experto)+' s · Intermedio '+num(c.experto)+'–'+num(c.novato)+' s · Novato > '+num(c.novato)+' s';}
  // «Sugerido: Experto (10.70 s con Con imán · Práctica)»
  function sugTxt(x){if(!x)return '';return nivelTxt(x.nivel)+' · mejor vuelta '+Number(x.s).toFixed(2)+' s ('+(ICON[x.clase]||'○')+' '+(NOMBRE[x.clase]||'Sin imán')+')'+(x.fuente?' · '+x.fuente:'');}
  // Ajustes del handicap por NIVEL y del nivel automático por tiempo (los mismos en el menú y en Gran Premio → Configuración).
  // box: contenedor; h: handicap actual; save(parte) guarda en /api/vueltas-config.
  function nivelSettings(box,h,save,onError){
    const mk=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;};
    box.replaceChildren();const err=m=>{if(onError)onError(m);};
    const en=mk('label','hc-toggle');const cb=mk('input');cb.type='checkbox';cb.id=box.id+'_on';cb.checked=h.nivel_on!==false;
    en.append(cb,document.createTextNode(' Sumar o restar también por NIVEL del piloto'));box.append(en);
    cb.addEventListener('change',()=>{seg.classList.toggle('off',!cb.checked);save({nivel_on:cb.checked});});
    const seg=mk('div','hc-seg hc-niv'+(h.nivel_on===false?' off':''));
    NIVELES.forEach(([k,n])=>{const c=mk('div','hc-cls');const lb=mk('label','',NIVEL_ICON[k]+' '+n);const i=mk('input');i.id=box.id+'_seg_'+k;i.dataset.nivel=k;lb.htmlFor=i.id;c.append(lb,i);seg.append(c);
      const f=upgrade(i,v=>{if(!Number.isFinite(v)||v<-10||v>10){err('El ajuste por nivel debe ser de 0 a 10 segundos (el botón + / − elige si suma o resta).');f.setValue((h.seg_nivel||{})[k]||0);return;}const o={};o[k]=v;save({seg_nivel:o});});
      f.setValue((h.seg_nivel||{})[k]||0);});
    box.append(seg,mk('p','help','Segundos por vuelta según el NIVEL del piloto (se guarda con cada piloto en el registro). Se SUMAN al ajuste de la clase del coche: p. ej. 🧲 Con imán +0.5 s y Experto +0.3 s = +0.8 s por vuelta. De fábrica: Experto +0.3 s, Intermedio 0 s, Novato −0.3 s (ejemplos, cámbialos). Si resta, una vuelta ajustada nunca baja de 1 s.'));
    // Nivel automático por tiempo
    box.append(mk('p','lap-config-title','Nivel automático por tiempo'));
    const md=mk('select','hc-auto');md.id=box.id+'_auto';md.setAttribute('aria-label','Nivel automático por tiempo');AUTO.forEach(([v,t])=>{const o=mk('option','',t);o.value=v;md.append(o);});md.value=h.nivel_auto||'sugerir';
    md.addEventListener('change',()=>save({nivel_auto:md.value}));box.append(md);
    const tb=mk('div','hc-cortes');const cortes=h.cortes||CORTES_FAB;
    CLASES.forEach(([k,n])=>{const c=Object.assign({},CORTES_FAB[k],cortes[k]||{});const row=mk('div','hc-corte');row.dataset.clase=k;
      row.append(mk('strong','',ICON[k]+' '+n));
      const mkIn=(lado,txt)=>{const l=mk('label','hc-corte-in');const i=mk('input');i.type='number';i.inputMode='decimal';i.step='0.1';i.min='1';i.max='120';i.value=num(c[lado]);i.dataset.lado=lado;i.id=box.id+'_c_'+k+'_'+lado;i.setAttribute('aria-label',n+': '+txt);
        i.addEventListener('change',()=>{const v=Number(String(i.value).replace(',','.'));if(!Number.isFinite(v)||v<1||v>120){err('Los tiempos para cambiar de nivel van de 1 a 120 segundos.');i.value=num(c[lado]);return;}
          const o={};o[k]={};o[k][lado]=Math.round(v*100)/100;save({cortes:o});});
        l.append(mk('span','',txt),i,mk('span','','s'));return l;};
      row.append(mkIn('experto','Experto si baja de'),mkIn('novato','Novato si pasa de'),mk('small','hc-corte-txt',cortesTxt(c)));tb.append(row);});
    box.append(tb,mk('p','help','Se usa la MEJOR VUELTA REAL (sin handicap) de cada piloto en la carrera, con la clase de SU coche. Entre los dos tiempos queda Intermedio. Hace falta al menos 3 vueltas. Funciona al terminar una Práctica, una Carrera y cada parte del Gran Premio o del torneo.'));
  }
  // Selector de nivel (3 botones) para el registro de pilotos.
  function nivelPicker(cur,onPick,small){
    const box=document.createElement('span');box.className='nv-pick'+(small?' sm':'');box.setAttribute('role','radiogroup');
    NIVELES.forEach(([k,n])=>{const b=document.createElement('button');b.type='button';b.className='nv-btn nv-'+k+(cur===k?' on':'');b.textContent=small?n[0]:n;b.title=n;b.setAttribute('aria-label',n);b.setAttribute('aria-pressed',cur===k?'true':'false');
      b.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();onPick(k);});box.append(b);});
    return box;
  }
  // Pone un tiempo: con handicap → «10.70 s H» (H = ajustado) y, si hay nodo real, «real 10.20 s».
  function setTime(node,raw,h,on,realNode){
    if(!node)return;const use=!!on&&raw!=null&&Number(h)!==0&&Number.isFinite(Number(h));
    const sig=[raw,h,use].join('|');
    if(node.dataset.hsig!==sig){
      node.dataset.hsig=sig;
      if(raw==null||!Number.isFinite(Number(raw))){node.textContent='—';node.removeAttribute('title');}
      else if(!use){node.textContent=Number(raw).toFixed(2)+' s';node.removeAttribute('title');}
      else{node.textContent=adj(raw,h).toFixed(2)+' s';const m=document.createElement('sup');m.className='hmark';m.textContent='H';m.setAttribute('aria-label','con handicap');node.append(m);
        node.title='Con handicap ('+segTxt(h)+' por vuelta). Tiempo real: '+Number(raw).toFixed(2)+' s';}
    }
    if(realNode){const t=use?'real '+Number(raw).toFixed(2)+' s':'';realNode.hidden=!t;if(realNode.textContent!==t)realNode.textContent=t;}
  }
  // ---------- 🏎️ Garage: coches físicos con su ficha y su propio hándicap (data/garage.json en la Mac) ----------
  // Dos garages: «🏠 Garage de la casa» y «🧳 Garage de invitados» (coches que traen los pilotos invitados).
  // El MANDO no se queda con el coche: el piloto escoge (o le toca por sorteo) un mando y lo vincula a SU coche.
  // uso = {lugar del registro 0-5: id del coche que lleva ese piloto}. Un coche, un piloto a la vez.
  const GAR={data:null,listeners:[],timer:null};
  function garEmit(){GAR.listeners.forEach(f=>{try{f(GAR.data);}catch(e){console.error(e);}});}
  async function garLoad(){
    try{const r=await fetch('/api/garage',{cache:'no-store'});if(!r.ok)return GAR.data;const d=await r.json();
      const ch=!GAR.data||d.version!==GAR.data.version;GAR.data=d;if(ch)garEmit();}catch(e){}
    return GAR.data;
  }
  function garStart(ms){if(GAR.timer)return;garLoad();GAR.timer=setInterval(garLoad,ms||5000);}
  function garCars(){return (GAR.data&&GAR.data.cars)||[];}
  function garCar(id){return id?garCars().find(c=>c.id===id)||null:null;}
  function garUso(slot){const d=GAR.data;return d?garCar((d.uso||{})[String(slot)]):null;}
  function garClaseDe(slot){const c=garUso(slot);return c?c.clase:null;}
  function garUsadoPor(id){const d=GAR.data;if(!d)return null;const e=Object.entries(d.uso||{}).find(([k,v])=>v===id);return e?Number(e[0]):null;}
  async function garPost(body){
    const r=await fetch('/api/garage',{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify(body)});
    let d={};try{d=await r.json();}catch(e){}
    if(!r.ok)throw Error(d.error||'No se pudo guardar en el Garage.');
    GAR.data=d;garEmit();return d;
  }
  function garCarTxt(c){return c.nombre+' · '+ICON[c.clase]+(c.h?' '+segTxt(c.h):'');}
  // Alta rápida de un coche de invitado: nombre + clase + hándicap (lo demás se completa luego en el Garage).
  function garQuick(dueno){
    return new Promise(res=>{
      const mk=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;};
      const bg=mk('div','gq-bg');bg.setAttribute('role','dialog');bg.setAttribute('aria-modal','true');bg.setAttribute('aria-label','Coche de invitado nuevo');
      const f=mk('form','gq');f.noValidate=true;
      f.append(mk('h3','','🧳 Coche de invitado'),mk('p','help','Va al Garage de invitados'+(dueno?' a nombre de '+dueno:'')+'. Lo demás (foto, motor, peso…) se llena después en el Garage.'));
      const ln=mk('label','gq-f');ln.append(mk('span','','Nombre o modelo'));const nm=mk('input');nm.maxLength=40;nm.required=true;nm.placeholder='p. ej. Ford GT azul';nm.autocomplete='off';nm.id='gqNombre';ln.append(nm);
      const lc=mk('label','gq-f');lc.append(mk('span','','Clase'));const cl=mk('select');cl.id='gqClase';CLASES.forEach(([k,n])=>{const o=mk('option','',ICON[k]+' '+n);o.value=k;cl.append(o);});lc.append(cl);
      const lh=mk('div','gq-f');lh.append(mk('span','','Hándicap propio del coche (s por vuelta)'));const hi=mk('input');hi.id='gqH';lh.append(hi);
      const er=mk('p','gq-err');er.setAttribute('role','alert');
      const bt=mk('div','gq-btns');const no=mk('button','gq-no','Cancelar');no.type='button';const ok=mk('button','gq-ok','Agregar y usar');ok.type='submit';bt.append(no,ok);
      f.append(ln,lc,lh,er,bt);bg.append(f);document.body.append(bg);
      const fld=upgrade(hi,()=>{});fld.setValue(0);
      const done=v=>{bg.remove();document.removeEventListener('keydown',esc);res(v);};
      const esc=e=>{if(e.key==='Escape')done(null);};document.addEventListener('keydown',esc);
      no.addEventListener('click',()=>done(null));bg.addEventListener('click',e=>{if(e.target===bg)done(null);});
      f.addEventListener('submit',e=>{e.preventDefault();const n=nm.value.trim();const h=fld.getValue();
        if(!n){er.textContent='Escribe el nombre o modelo del coche.';nm.focus();return;}
        if(!Number.isFinite(h)){er.textContent='El hándicap va de 0 a 10 segundos (el botón + / − elige si suma o resta).';return;}
        done({nombre:n,clase:cl.value,h,dueno:dueno||''});});
      setTimeout(()=>nm.focus(),30);
    });
  }
  // <select> de coche con los dos grupos (casa e invitados) + «➕ Coche de invitado nuevo…».
  // o = {cur, usados:{id:'nombre del piloto que ya lo lleva'}, aria, dueno, onPick(id)→Promise, onNuevo(datos)→Promise, onError(msg)}
  function garPicker(o){
    const s=document.createElement('select');s.className='gar-sel';s.setAttribute('aria-label',o.aria||'Coche del Garage');
    const add=(parent,v,t,dis)=>{const op=document.createElement('option');op.value=v;op.textContent=t;op.disabled=!!dis;parent.append(op);return op;};
    // Cada piloto corre con un coche del Garage (casa o invitados); si no trae, «➕ Coche de invitado nuevo…».
    add(s,'','🏎️ Escoge su coche…');
    [['casa','🏠 Garage de la casa'],['invitado','🧳 Garage de invitados']].forEach(([t,lbl])=>{
      const cs=garCars().filter(c=>(c.tipo||'casa')===t);if(!cs.length)return;
      const g=document.createElement('optgroup');g.label=lbl;
      cs.forEach(c=>{const u=(o.usados||{})[c.id];add(g,c.id,'🏎️ '+garCarTxt(c)+(t==='invitado'&&c.dueno?' · de '+c.dueno:'')+(u?' · en uso con '+u:''),!!u&&c.id!==o.cur);});
      s.append(g);});
    if(o.onNuevo)add(s,'__nuevo','➕ Coche de invitado nuevo…');
    s.value=o.cur&&garCar(o.cur)?o.cur:'';const prev=s.value;s.classList.toggle('falta',!s.value);
    s.addEventListener('click',e=>e.stopPropagation());
    s.addEventListener('change',async()=>{
      try{
        s.blur();   // para que la pantalla se pueda redibujar con el cambio
        if(s.value==='__nuevo'){s.value=prev;const datos=await garQuick(o.dueno);if(datos)await o.onNuevo(datos);return;}
        await o.onPick(s.value||'');
      }catch(e){s.value=prev;if(o.onError)o.onError(e.message||String(e));}
    });
    return s;
  }
  // Coche que lleva el piloto del registro (lugar 0-5) en Práctica, Carrera y Gran Premio. nombres = {lugar: nombre}.
  function garPilot(slot,nombre,nombres,onDone,onError){
    const d=GAR.data||{},usados={};Object.entries(d.uso||{}).forEach(([k,v])=>{if(Number(k)!==Number(slot))usados[v]=(nombres||{})[k]||'otro piloto';});
    return garPicker({cur:(d.uso||{})[String(slot)]||'',usados,aria:'Coche de '+nombre,dueno:nombre,onError,
      onPick:async id=>{await garPost({action:'usar',slot,id});if(onDone)onDone();},
      onNuevo:async c=>{await garPost({action:'rapido',slot,car:c});if(onDone)onDone();}});
  }
  // Sorteo de mandos: n mandos distintos al azar entre los disponibles (1 a 6 por defecto).
  function sortearMandos(n,disp){const a=(disp||[1,2,3,4,5,6]).slice();for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];}return a.slice(0,n);}
  window.PeluGarage={load:garLoad,start:garStart,cars:garCars,car:garCar,uso:garUso,claseDe:garClaseDe,usadoPor:garUsadoPor,post:garPost,picker:garPicker,pilot:garPilot,quick:garQuick,sortear:sortearMandos,txt:garCarTxt,onChange:f=>GAR.listeners.push(f),get data(){return GAR.data;}};
  window.PeluHandicap={CLASES,ICON,NOMBRE,MIN_VUELTA_H,segTxt,adj,label,setTime,upgrade,NIVELES,NIVEL,NIVEL_ICON,AUTO,nivelTxt,detalle,cortesTxt,sugTxt,nivelSettings,nivelPicker};
})();
