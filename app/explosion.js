'use strict';
// 💥 Explosión al sensor: cada vez que un coche cruza el sensor IR de la ESP32 suena una explosión en la pantalla
// grande (Práctica/Carrera y Gran Premio). No va en «Mi coche». Sonido sintetizado aquí mismo con Web Audio
// (ruido + golpe grave + retumbo): sin archivos, sin licencias, funciona sin internet.
// Respeta «Activar sonido aquí» y el volumen/«Sonidos encendidos» de la configuración (cada pantalla lo conecta con
//   PeluExplosion.config({canPlay:()=>bool, volume:()=>0..1})).
// Interruptor propio «💥 Explosión al sensor» (encendido de fábrica), guardado en este equipo (localStorage).
// No toca la carrera: es solo sonido. Truena también durante el PARO (es el sensor, no una vuelta contada).
(function(){
  const KEY='peu-explosion',POLL_MS=250,GAP_MS=450,MAX_QUEUE=3,LATE_S=4;
  let on=true;try{on=localStorage.getItem(KEY)!=='off';}catch(e){}
  let canPlay=()=>false,volume=()=>0.8,ctx=null,noise=null,base=null,queue=0,lastPlay=0,timer=null,busy=false;
  const stats={cruces:0,explosiones:0,silenciadas:0,tarde:0,reanudadas:0,bloqueadas:0,fuente:null};
  const log=(...a)=>{try{console.log('[💥 explosión]',...a);}catch(e){}};
  function audio(){
    if(ctx&&ctx.state==='closed'){log('AudioContext cerrado; se crea otro');ctx=null;}
    if(ctx)return ctx;const AC=window.AudioContext||window.webkitAudioContext;if(!AC){log('Este navegador no tiene Web Audio');return null;}
    try{ctx=new AC();}catch(e){log('No se pudo crear AudioContext',e);return null;}
    const len=Math.floor(ctx.sampleRate*6);noise=ctx.createBuffer(1,len,ctx.sampleRate);const w=noise.getChannelData(0);
    let b=0;for(let i=0;i<len;i++){const r=Math.random()*2-1;b=(b+0.02*r)/1.02;w[i]=r*0.6+b*3.2;}   // blanco + café (grave)
    return ctx;
  }
  // Safari puede dejarlo en «suspended» o «interrupted» (otra app tomó el audio, Mac dormida): reanudar en cada intento.
  function resume(c){
    if(!c||c.state==='running')return Promise.resolve(true);
    const before=c.state;
    return c.resume().then(()=>{if(c.state!=='running')log('resume() no lo prendió; estado:',c.state,'(haz clic en la página)');return c.state==='running';})
      .catch(e=>{log('resume() falló desde',before,e&&e.name);return false;});
  }
  function unlock(){const c=audio();if(c&&c.state!=='running')resume(c);}
  ['pointerdown','keydown','touchstart'].forEach(t=>document.addEventListener(t,unlock,{passive:true}));
  function src(c,t){const s=c.createBufferSource();s.buffer=noise;s.start(t,Math.random()*1.5);return s;}
  function env(c,g,t,peak,attack,decay){g.gain.setValueAtTime(0.0001,t);g.gain.exponentialRampToValueAtTime(peak,t+attack);g.gain.exponentialRampToValueAtTime(0.0001,t+attack+decay);}
  function boom(v){
    const c=audio();if(!c)return false;
    if(c.state!=='running'){stats.reanudadas++;resume(c).then(ok=>{if(ok)boomNow(c,v);else stats.bloqueadas++;});return true;}
    return boomNow(c,v);
  }
  function boomNow(c,v){
    const t=c.currentTime+0.01,out=c.createGain();out.gain.value=Math.min(1,v)*1.6;
    const comp=c.createDynamicsCompressor();comp.threshold.value=-14;comp.knee.value=8;comp.ratio.value=6;comp.attack.value=0.002;comp.release.value=0.25;
    const shaper=c.createWaveShaper();const k=new Float32Array(1024);for(let i=0;i<1024;i++){const x=i/511.5-1;k[i]=Math.tanh(2.2*x);}shaper.curve=k;
    out.connect(shaper);shaper.connect(comp);comp.connect(c.destination);
    // 1) Chasquido inicial (agudo, muy corto)
    const n1=src(c,t),h=c.createBiquadFilter();h.type='highpass';h.frequency.value=1800;const g1=c.createGain();env(c,g1,t,0.9,0.002,0.18);
    n1.connect(h);h.connect(g1);g1.connect(out);n1.stop(t+0.3);
    // 2) Cuerpo: ruido que se va apagando de brillante a sordo
    const n2=src(c,t),l=c.createBiquadFilter();l.type='lowpass';l.Q.value=0.7;l.frequency.setValueAtTime(5000,t);l.frequency.exponentialRampToValueAtTime(160,t+1.8);
    const g2=c.createGain();env(c,g2,t,1.0,0.006,2.4);n2.connect(l);l.connect(g2);g2.connect(out);n2.stop(t+2.6);
    // 3) Golpe grave (la «patada» del bombazo): seno que cae de 110 a 32 Hz
    const o=c.createOscillator();o.type='sine';o.frequency.setValueAtTime(110,t);o.frequency.exponentialRampToValueAtTime(32,t+0.7);
    const g3=c.createGain();env(c,g3,t,1.0,0.004,1.3);o.connect(g3);g3.connect(out);o.start(t);o.stop(t+1.5);
    // 4) Retumbo largo (eco grave que se aleja)
    const n4=src(c,t+0.05),l4=c.createBiquadFilter();l4.type='lowpass';l4.frequency.value=140;const g4=c.createGain();env(c,g4,t+0.05,0.8,0.12,3.2);
    n4.connect(l4);l4.connect(g4);g4.connect(out);n4.stop(t+3.6);
    return true;
  }
  function fire(){
    stats.explosiones++;lastPlay=Date.now();
    window.dispatchEvent(new CustomEvent('peu-explosion',{detail:{n:stats.explosiones}}));
    let v=0;try{v=canPlay()?Number(volume())||0:0;}catch(e){v=0;}
    if(v>0){boom(v);log('BUM #'+stats.explosiones,'(audio: '+(ctx?ctx.state:'sin audio')+', fuente: '+(stats.fuente||'?')+')');}
    else{stats.silenciadas++;log('cruce sin sonido: falta «Activar sonido aquí» o el volumen está en 0');}
  }
  function drain(){
    if(queue<=0)return;const wait=lastPlay+GAP_MS-Date.now();
    if(wait>0){setTimeout(drain,wait+5);return;}
    queue--;fire();if(queue>0)setTimeout(drain,GAP_MS+5);
  }
  function onCrossings(k){stats.cruces+=k;if(!on)return;const was=queue;queue=Math.min(MAX_QUEUE,queue+k);if(was===0)drain();}
  let seen=null;   // {boot,n}
  async function poll(){
    if(busy)return;busy=true;const ctrl=new AbortController(),to=setTimeout(()=>ctrl.abort(),2000);
    try{
      const r=await fetch('/api/cruces?explosion='+(on?1:0)+'&ts='+Date.now(),{cache:'no-store',signal:ctrl.signal});
      if(r.ok){const d=await r.json();
        if(d&&typeof d.n==='number'){
          if(!seen||seen.boot!==d.boot||d.n<seen.n){seen={boot:d.boot,n:d.n};}   // primera vez o servidor reiniciado: solo referencia
          else if(d.n>seen.n){const k=d.n-seen.n;seen.n=d.n;
            // Si esta pantalla se enteró muy tarde (pestaña en segundo plano, Mac dormida), no tronar a destiempo.
            const age=(typeof d.now==='number'&&typeof d.at==='number')?d.now-d.at:0;
            if(age>LATE_S){stats.tarde+=k;log(k+' cruce(s) llegaron '+age.toFixed(1)+' s tarde; no se tocan');}
            else{log(k+' cruce(s) nuevo(s) por',d.fuente||'?');onCrossings(k);}}
          if(d.fuente!==stats.fuente){log('fuente de cruces:',d.fuente||'ninguna (sensor sin conexión)');stats.fuente=d.fuente||null;}
        }}
    }catch(e){}finally{clearTimeout(to);busy=false;}
  }
  function syncButton(){const b=document.getElementById('explosionToggle');if(!b)return;b.textContent=on?'💥 Explosión al sensor: Sí':'💥 Explosión al sensor: No';b.classList.toggle('on',on);b.setAttribute('aria-pressed',on?'true':'false');}
  function setOn(v){on=!!v;try{localStorage.setItem(KEY,on?'on':'off');}catch(e){}if(!on)queue=0;syncButton();}
  function build(){
    const bar=document.querySelector('.gp-status');if(!bar||document.getElementById('explosionToggle'))return;
    const b=document.createElement('button');b.type='button';b.id='explosionToggle';b.className='chip-button';
    b.title='Suena una explosión cada vez que un coche cruza el sensor IR. Necesita «Activar sonido aquí».';
    b.addEventListener('click',()=>{setOn(!on);if(on){unlock();let v=0;try{v=canPlay()?Number(volume())||0:0;}catch(e){}if(v>0)boom(v);}});
    const snd=document.getElementById('soundToggle');if(snd&&snd.nextSibling)bar.insertBefore(b,snd.nextSibling);else bar.append(b);
    syncButton();
  }
  function start(){build();if(!timer){poll();timer=setInterval(poll,POLL_MS);}
    // Al volver a la pestaña: preguntar ya y reanudar el audio si el navegador lo pausó.
    document.addEventListener('visibilitychange',()=>{if(!document.hidden){poll();if(ctx&&ctx.state!=='running')resume(ctx);}});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
  window.PeluExplosion={
    config(o){if(o&&typeof o.canPlay==='function')canPlay=o.canPlay;if(o&&typeof o.volume==='function')volume=o.volume;},
    get on(){return on;},set on(v){setOn(v);},
    test(){unlock();fire();},          // botón «Probar sonidos» del Gran Premio
    get stats(){return Object.assign({},stats);}
  };
})();
