'use strict';
// Bandera roja (PARO) compartida por Práctica, Carrera, Gran Premio y «Mi coche».
// El estado vive en el servidor (Mac): esta pieza solo lo pinta. En «Mi coche» es solo lectura (sin botones).
//   PeluParo.render({canStop, red, resuming, frozenMs, label, readOnly, kind, by, used, max})
//   kind:'yellow' = BANDERA AMARILLA que pidió un piloto (triple clic en su botón de cambio de carril): es el mismo
//   PARO (reloj detenido, vueltas no cuentan, Reanudar con semáforo), con letrero amarillo y «la pidió <piloto>».
//   PeluParo.onStop / PeluParo.onResume = async ()=>{...}   (la pantalla manda la orden al servidor)
// Atajo de teclado (pantalla grande): P o barra espaciadora = PARO. Reanudar solo con el botón (para no reanudar sin querer).
(function(){
  let state={canStop:false,red:false,resuming:false,readOnly:false},busy=false,mini=false,lastN=null,built=false;
  const api={onStop:null,onResume:null};
  function fmt(ms){if(ms==null)return null;const t=Math.floor(ms/1000),m=Math.floor(t/60),s=t%60;return m+':'+String(s).padStart(2,'0');}
  function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
  function build(){
    if(built)return;built=true;
    const fab=el('button','paro-fab','■ PARO');fab.type='button';fab.id='paroBtn';fab.hidden=true;fab.title='Bandera roja: detiene el cronómetro (tecla P o espacio)';
    fab.setAttribute('aria-label','PARO: bandera roja, detener la carrera');
    fab.addEventListener('click',()=>run(api.onStop));
    const ov=el('div','paro-overlay');ov.id='paroOverlay';ov.hidden=true;ov.setAttribute('role','alertdialog');ov.setAttribute('aria-labelledby','paroTitle');
    const box=el('div','paro-box');
    const flag=el('div','paro-flag','🚩');flag.id='paroFlag';const eb=el('p','paro-eyebrow','BANDERA ROJA');eb.id='paroEyebrow';const h=el('strong','paro-title','PARO');h.id='paroTitle';
    const sub=el('p','paro-sub','Suelten el gatillo. El cronómetro está detenido y las vueltas no cuentan.');sub.id='paroSub';
    const clock=el('p','paro-clock');clock.id='paroClock';
    const label=el('p','paro-label');label.id='paroLabel';
    const by=el('p','paro-by');by.id='paroBy';by.hidden=true;
    const actions=el('div','paro-actions');actions.id='paroActions';
    const resume=el('button','paro-resume','▶ REANUDAR · semáforo');resume.type='button';resume.id='paroResume';resume.addEventListener('click',()=>run(api.onResume));
    const look=el('button','paro-look','Ver tablero');look.type='button';look.id='paroLook';look.addEventListener('click',()=>{mini=true;paint();});
    actions.append(resume,look);
    const err=el('p','paro-error');err.id='paroError';err.setAttribute('role','alert');
    box.append(flag,eb,h,by,label,sub,clock,actions,err);ov.append(box);
    const bar=el('div','paro-bar');bar.id='paroBar';bar.hidden=true;
    const bt=el('strong','','🚩 BANDERA ROJA · PARO');bt.id='paroBarTitle';const bclock=el('span','paro-bar-clock');bclock.id='paroBarClock';
    const bres=el('button','paro-resume small','▶ Reanudar');bres.type='button';bres.id='paroBarResume';bres.addEventListener('click',()=>run(api.onResume));
    const bbig=el('button','paro-look small','Ampliar');bbig.type='button';bbig.addEventListener('click',()=>{mini=false;paint();});
    bar.append(bt,bclock,bres,bbig);
    document.body.append(bar,ov,fab);
    document.addEventListener('keydown',e=>{
      if(e.repeat||e.ctrlKey||e.metaKey||e.altKey)return;
      const k=e.key;if(!(k==='p'||k==='P'||k===' '||k==='Spacebar'))return;
      const t=document.activeElement,tag=t&&t.tagName;
      if(tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT'||(t&&t.isContentEditable))return;
      if(k!=='p'&&k!=='P'&&(tag==='BUTTON'||tag==='A'||tag==='SUMMARY'))return;   // espacio sobre un botón = ese botón
      if(document.querySelector('.overlay:not([hidden])'))return;                       // ventana de pilotos abierta
      if(state.readOnly||!state.canStop||state.red&&!state.resuming)return;
      e.preventDefault();run(api.onStop);
    });
  }
  async function run(fn){
    if(busy||typeof fn!=='function')return;busy=true;paint();const err=document.getElementById('paroError');if(err)err.textContent='';
    try{await fn();}catch(e){if(err)err.textContent=e&&e.message||'No se pudo. Intenta otra vez.';}
    finally{busy=false;paint();}
  }
  function paint(){
    build();
    const s=state,fab=document.getElementById('paroBtn'),ov=document.getElementById('paroOverlay'),bar=document.getElementById('paroBar');
    const stopped=s.red&&!s.resuming;
    fab.hidden=s.readOnly||!s.canStop||stopped;fab.disabled=busy;
    ov.hidden=!stopped||mini;bar.hidden=!stopped||!mini||s.readOnly;
    ov.classList.toggle('readonly',!!s.readOnly);
    document.getElementById('paroActions').hidden=!!s.readOnly;
    document.getElementById('paroResume').disabled=busy;document.getElementById('paroBarResume').disabled=busy;
    const c=fmt(s.frozenMs),ct=c?'Reloj detenido en '+c:'';
    const set=(id,t)=>{const n=document.getElementById(id);if(n&&n.textContent!==t)n.textContent=t;};
    set('paroClock',ct);set('paroBarClock',c?'⏱ '+c:'');set('paroLabel',s.label||'');
    const yellow=s.kind==='yellow',who=s.by||'un piloto',cnt=Number.isInteger(s.used)&&Number.isInteger(s.max)?' ('+s.used+' de '+s.max+')':'';
    set('paroFlag',yellow?'🟨':'🚩');set('paroEyebrow',yellow?'BANDERA AMARILLA':'BANDERA ROJA');
    set('paroBy',yellow?'La pidió '+who+cnt:'');document.getElementById('paroBy').hidden=!yellow;
    set('paroBarTitle',yellow?'🟨 BANDERA AMARILLA · la pidió '+who:'🚩 BANDERA ROJA · PARO');
    ov.classList.toggle('yellow',yellow);bar.classList.toggle('yellow',yellow);document.body.classList.toggle('paro-yellow',!!s.red&&yellow);
    set('paroSub',s.readOnly?'Suelta el gatillo y espera. Cuando reanuden habrá semáforo otra vez; el tiempo del paro no cuenta.':'Suelten el gatillo. El cronómetro está detenido y las vueltas no cuentan. Reanudar prende el semáforo de salida.');
    document.body.classList.toggle('paro-on',!!s.red);
  }
  function render(next){
    next=Object.assign({canStop:false,red:false,resuming:false,frozenMs:null,label:'',readOnly:false,n:null,kind:'red',by:null,used:null,max:null},next||{});
    if(next.red&&next.n!==lastN){mini=false;lastN=next.n;}   // cada bandera roja nueva se ve en grande
    if(!next.red)lastN=null;
    state=next;paint();
  }
  function hide(){render({});}
  window.PeluParo={render,hide,set onStop(fn){api.onStop=fn;},set onResume(fn){api.onResume=fn;},get state(){return Object.assign({},state);},get busy(){return busy;}};
})();
