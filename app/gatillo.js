'use strict';
// Velocímetro en vivo con el gatillo de cada mando + «⇄ pide cambio» de carril. Lee /api/gatillo ~10 veces por segundo.
// Solo lectura: la tarjeta SCX solo se escucha. Si no hay datos frescos (sin tarjeta, mando apagado, Mac sin
// responder) kmh() da null y las agujas vuelven a la velocidad de la última vuelta, como antes.
(function(){
const POLL_MS=100,FRESH_MS=1500;
let data=null,gotAt=0,busy=false,fails=0;
function fresh(){return data&&data.ok&&performance.now()-gotAt<FRESH_MS;}
function info(car){car=Number(car);if(!fresh()||!(car>=1&&car<=6))return null;const c=data.cars[car-1];return c&&c.live?c:null;}
function kmh(car){const c=info(car);return c&&Number.isFinite(c.kmh)?c.kmh:null;}
function pide(car){const c=info(car);return !!(c&&c.pide);}
function presses(car){car=Number(car);if(!data||!(car>=1&&car<=6))return 0;return (data.cars[car-1]||{}).presses||0;}
// Indicadores: cualquier <span class="pide" data-car="N"> se prende ~1 s cuando ese mando aprieta el botón de cambio.
function paint(){
  document.querySelectorAll('.pide[data-car]').forEach(e=>{
    const car=e.dataset.car,on=pide(car),n=presses(car),live=!!info(car);
    e.classList.toggle('on',on);e.classList.toggle('sin',!live);
    const t='⇄'+(n?' '+n:'');if(e.textContent!==t)e.textContent=t;
    const tt=(on?'Pide cambio de carril ahora · ':'')+'Botón de cambio de carril apretado '+n+' '+(n===1?'vez':'veces')+' en esta sesión. Solo dice que el piloto lo pidió, no que el coche cambió de carril.';
    if(e.title!==tt){e.title=tt;e.setAttribute('aria-label',(on?'Pide cambio. ':'')+'Cambios pedidos: '+n);}
    const s=on?'1':'0';if(e.dataset.on!==s)e.dataset.on=s;
  });
}
async function poll(){
  if(busy||document.hidden)return;busy=true;const ctrl=new AbortController(),to=setTimeout(()=>ctrl.abort(),900);
  try{const r=await fetch('/api/gatillo?ts='+Date.now(),{cache:'no-store',signal:ctrl.signal});if(!r.ok)throw Error('HTTP '+r.status);data=await r.json();gotAt=performance.now();fails=0;}
  catch(e){fails++;}
  finally{clearTimeout(to);busy=false;try{paint();}catch(e){}}
}
setInterval(poll,POLL_MS);
window.PeluGatillo={kmh,pide,info,presses,paint,get data(){return data;}};
})();
