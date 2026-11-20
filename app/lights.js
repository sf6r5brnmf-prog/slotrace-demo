'use strict';
// Semáforo de salida compartido por el Gran Premio, la Práctica y la Carrera (mismo overlay #lights de gp.css):
// tres focos que se prenden en rojo uno por uno, luego los tres en verde con "¡VERDE!" 700 ms, y se esconde.
(function(){
  const GREEN_MS=700;
  let deadline=null,totalMs=3000,greenTimer=null,tickTimer=null,onDeadline=null,deadlineFired=false;
  function box(){return document.getElementById('lights');}
  // Focos encendidos para los ms que faltan: igual que el GP con 3 s (1 rojo, 2 rojos, 3 rojos "Listos…").
  function lampsFor(ms,total){const T=total>0?total:3000;if(ms>T)return 0;return Math.max(1,Math.min(3,3-Math.floor(ms*3/T)));}
  function paint(on,text){
    const o=box();if(!o)return;
    o.querySelectorAll('.gp-lights i').forEach((l,i)=>{const c=on==='green'?'green':i<on?'red':'';if(l.className!==c)l.className=c;});
    const t=document.getElementById('lightsText');if(t&&t.textContent!==text)t.textContent=text;
  }
  function tick(){
    if(deadline===null)return;
    const ms=Math.max(0,deadline-performance.now()),on=lampsFor(ms,totalMs);
    paint(on,on===3?'Listos…':'Pilotos, a sus lugares');
    if(ms<=0&&!deadlineFired){deadlineFired=true;if(onDeadline)try{onDeadline();}catch(e){}}
  }
  function stopTick(){if(tickTimer!==null){clearInterval(tickTimer);tickTimer=null;}deadline=null;}
  // phase: 'countdown' (rojos), 'running' (verde si el semáforo estaba a la vista) o cualquier otra (esconder).
  function render(phase,ms,total,label){
    const o=box();if(!o)return;
    if(phase==='countdown'){
      if(greenTimer!==null){clearTimeout(greenTimer);greenTimer=null;}
      o.dataset.go='';o.hidden=false;
      const l=document.getElementById('lightsLabel');if(l&&label!==undefined&&l.textContent!==label)l.textContent=label;
      totalMs=total>0?total:3000;
      const target=performance.now()+Math.max(0,ms||0);
      // Reloj local entre sondeos; solo se corrige si el servidor difiere más de 150 ms.
      if(deadline===null||Math.abs(deadline-target)>150){deadline=target;deadlineFired=ms<=0;}
      if(tickTimer===null)tickTimer=setInterval(tick,50);
      tick();
    }else if(phase==='running'&&!o.hidden&&o.dataset.go!=='1'){
      stopTick();o.dataset.go='1';paint('green','¡VERDE!');
      greenTimer=setTimeout(()=>{greenTimer=null;o.hidden=true;o.dataset.go='';},GREEN_MS);
    }else if(phase!=='running'||o.dataset.go!=='1'){
      stopTick();if(o.dataset.go!=='1')o.hidden=true;
    }
  }
  function hide(){stopTick();if(greenTimer!==null){clearTimeout(greenTimer);greenTimer=null;}const o=box();if(o){o.hidden=true;o.dataset.go='';}}
  // Segundos a esperar antes de tocar el sonido "semaforo" (dura 3 s y termina en el verde); negativo = empezar a la mitad.
  function soundLead(ms){return (ms??3000)/1000-3;}
  window.PeluLights={render,hide,lampsFor,soundLead,set onDeadline(fn){onDeadline=fn;},get visible(){const o=box();return !!o&&!o.hidden;}};
})();
