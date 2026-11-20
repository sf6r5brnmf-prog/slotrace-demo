'use strict';
// Agujas analógicas compartidas: Gran Premio, Práctica y Carrera usan exactamente el mismo dibujo.
// Velocímetro (km/h a escala) + VIDA DE LLANTA (0–100 %, el nivel D6 de la Pit Box que antes decía «combustible»).
// Verde >50 %, amarilla 20–50 %, roja <20 % (la zona roja sale de tire_red_pct). Animación suave con k=1-exp(-dt*4.5).
(function(){
class Gauge{
  constructor(canvas){this.c=canvas;this.speed=0;this.fuel=0;this.ts=0;this.tf=0;this.fuelNull=true;this.max=300;this.red=20;this.kmh=null;this.dirty=true;
    // car = mando (1-6) de esta tarjeta: si hay gatillo en vivo (gatillo.js), la aguja lo sigue; si no, se queda en la última vuelta.
    this.car=null;this.lapTs=0;this.live=null;}
  set(kmh,fuel,max,red){this.max=max;this.red=red;this.kmh=kmh;this.lapTs=Math.min(kmh||0,max);this.ts=this.live!=null?Math.min(this.live,max):this.lapTs;this.fuelNull=fuel==null;this.tf=fuel==null?0:fuel;this.fuelText=fuel==null?'—':fuel+'%';this.dirty=true;
    // Lectura accesible (y para las pruebas): lo mismo que marcan las agujas.
    const ks=kmh==null?'':String(Math.round(kmh)),fs=fuel==null?'':String(fuel);if(this.c.dataset.kmh!==ks)this.c.dataset.kmh=ks;if(this.c.dataset.fuel!==fs)this.c.dataset.fuel=fs;
    if(this.c.dataset.llanta!==fs)this.c.dataset.llanta=fs;
    const lab='Velocidad '+(ks||'—')+' km/h · vida de llanta '+this.fuelText;if(this.c.getAttribute('aria-label')!==lab){this.c.setAttribute('aria-label',lab);this.c.setAttribute('role','img');}
    // Primer dibujo en cuanto la tarjeta ya tiene tamaño (no esperar al siguiente cuadro: tarjeta nueva nunca en blanco).
    if(!this.drawn&&this.draw()!==false)this.drawn=true;}
  liveTick(){
    const G=window.PeluGatillo,v=this.car&&G?G.kmh(this.car):null,was=this.live;this.live=v;
    if(v!=null)this.ts=Math.min(Math.max(0,v),this.max);else if(was!=null)this.ts=this.lapTs;
    const mode=v!=null?'gatillo':'vuelta';if(this.c.dataset.velo!==mode){this.c.dataset.velo=mode;this.dirty=true;}
    const lk=v==null?'':String(Math.round(v));if(this.c.dataset.liveKmh!==lk){this.c.dataset.liveKmh=lk;this.dirty=true;}
  }
  step(dt){this.liveTick();const k=1-Math.exp(-dt*4.5);const ds=(this.ts-this.speed)*k,df=(this.tf-this.fuel)*k;
    if(Math.abs(ds)>.02||Math.abs(df)>.02||this.dirty){this.speed+=ds;this.fuel+=df;this.dirty=false;if(this.draw()===false)this.dirty=true;}}   // canvas sin tamaño todavía: dibujar en el siguiente cuadro
  draw(){
    const c=this.c,dpr=window.devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;if(!w||!h)return false;
    if(c.width!==Math.round(w*dpr)||c.height!==Math.round(h*dpr)){c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);}
    const x=c.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);x.clearRect(0,0,w,h);
    const r1=Math.min(h*.47,w*.33),cx1=r1+6,cy=h/2+2;
    dial(x,cx1,cy,r1,0,this.max,this.speed,{major:this.max<=300?50:100,minor:this.max<=300?10:20,redFrom:this.max*.84,label:this.live!=null?'km/h · gatillo':'km/h',value:this.live!=null?String(Math.round(this.live)):this.kmh==null?'—':String(Math.round(this.kmh))});
    const r2=Math.min(h*.42,w*.2),cx2=w-r2-8;
    // Vida de llanta: mismo valor de la Pit Box en %, con el dibujo de una llanta junto a la etiqueta.
    dial(x,cx2,cy+r2*.3,r2,0,100,this.fuel,{major:25,minor:12.5,redTo:this.red,yellowTo:TIRE_YELLOW,label:'LLANTA',tire:true,value:this.fuelText,small:true,dim:this.fuelNull,ticksText:['0','','50','','100'],a0:Math.PI*1.05,a1:Math.PI*1.95,half:true});
  }
}
function dial(x,cx,cy,r,min,max,val,o){
  const a0=o.a0??Math.PI*.75,a1=o.a1??Math.PI*2.25,ang=v=>a0+(a1-a0)*(Math.max(min,Math.min(max,v))-min)/(max-min);
  // cara
  const g=x.createRadialGradient(cx,cy-r*.3,r*.1,cx,cy,r);g.addColorStop(0,'#232a35');g.addColorStop(1,'#0b0e13');
  x.beginPath();if(o.half){x.arc(cx,cy,r,Math.PI,0);x.lineTo(cx+r,cy+r*.5);x.arcTo(cx+r,cy+r*.62,cx+r*.85,cy+r*.62,r*.12);x.lineTo(cx-r*.85,cy+r*.62);x.arcTo(cx-r,cy+r*.62,cx-r,cy+r*.5,r*.12);x.closePath();}else x.arc(cx,cy,r,0,Math.PI*2);
  x.fillStyle=g;x.fill();x.lineWidth=Math.max(2,r*.04);x.strokeStyle='#3a4352';x.stroke();
  // zonas rojas
  x.lineWidth=r*.09;x.lineCap='butt';
  if(o.redFrom!=null){x.beginPath();x.arc(cx,cy,r*.84,ang(o.redFrom),a1);x.strokeStyle='#ff3b3bcc';x.stroke();}
  if(o.yellowTo!=null&&o.redTo!=null&&o.yellowTo>o.redTo){x.beginPath();x.arc(cx,cy,r*.84,ang(o.redTo),ang(o.yellowTo));x.strokeStyle='#ffc93ccc';x.stroke();}
  if(o.redTo!=null){x.beginPath();x.arc(cx,cy,r*.84,a0,ang(o.redTo));x.strokeStyle='#ff3b3bcc';x.stroke();}
  // marcas
  for(let v=min,i=0;v<=max+1e-6;v+=o.minor,i++){
    const isMajor=Math.abs((v-min)/o.major-Math.round((v-min)/o.major))<1e-6,a=ang(v),ri=r*(isMajor?.7:.76);
    x.beginPath();x.moveTo(cx+Math.cos(a)*ri,cy+Math.sin(a)*ri);x.lineTo(cx+Math.cos(a)*r*.9,cy+Math.sin(a)*r*.9);
    x.strokeStyle=isMajor?'#f5f7fa':'#7d8796';x.lineWidth=isMajor?Math.max(1.5,r*.025):1;x.stroke();
    if(isMajor){const idx=Math.round((v-min)/o.major),txt=o.ticksText?o.ticksText[idx]:String(Math.round(v));
      if(txt){x.fillStyle='#cfd6df';x.font='700 '+Math.max(8,r*(o.small?.17:.12))+'px system-ui';x.textAlign='center';x.textBaseline='middle';const rr=o.half?.6:.55;x.fillText(txt,cx+Math.cos(a)*r*rr,cy+Math.sin(a)*r*rr);}}
  }
  // lectura
  const low=o.redTo!=null&&!o.dim&&val<o.redTo,mid=!low&&o.yellowTo!=null&&!o.dim&&val<=o.yellowTo;
  x.fillStyle=o.dim?'#6b7480':low?'#ff5a4d':mid?'#ffc93c':'#d5ff42';x.font='900 '+Math.max(11,r*(o.half?.24:.26))+'px system-ui';x.textAlign='center';x.textBaseline='middle';x.fillText(o.value,cx,o.half?cy+r*.3:cy+r*.42);
  x.fillStyle='#8f9aa8';x.font='700 '+Math.max(8,r*(o.half?.11:.1))+'px system-ui';const ly=o.half?cy+r*.52:cy+r*.66;x.fillText(o.label,cx,ly);
  if(o.tire){const lw=x.measureText(o.label).width,tr=Math.max(4,r*.085);tireIcon(x,cx-lw/2-tr-3,ly,tr,o.dim?'#6b7480':low?'#ff5a4d':mid?'#ffc93c':'#d5ff42');}
  // aguja
  const a=ang(val);x.save();x.translate(cx,cy);x.rotate(a);x.beginPath();x.moveTo(-r*.12,-r*.025);x.lineTo(r*.86,-r*.006);x.lineTo(r*.86,r*.006);x.lineTo(-r*.12,r*.025);x.closePath();
  x.fillStyle=o.dim?'#59616c':'#ff4d3d';x.shadowColor='#ff4d3d88';x.shadowBlur=o.dim?0:r*.06;x.fill();x.restore();
  x.beginPath();x.arc(cx,cy,r*.08,0,Math.PI*2);x.fillStyle='#e9edf2';x.fill();x.beginPath();x.arc(cx,cy,r*.04,0,Math.PI*2);x.fillStyle='#11151b';x.fill();
}
// Llanta vista de lado: hule negro con dibujo, rin de color (según la vida) y maza.
function tireIcon(x,cx,cy,r,color){
  x.save();x.beginPath();x.arc(cx,cy,r,0,Math.PI*2);x.fillStyle='#1b1f26';x.fill();x.lineWidth=Math.max(1,r*.22);x.strokeStyle='#cfd6df';x.stroke();
  for(let i=0;i<8;i++){const a=i*Math.PI/4;x.beginPath();x.moveTo(cx+Math.cos(a)*r*.78,cy+Math.sin(a)*r*.78);x.lineTo(cx+Math.cos(a)*r*1.0,cy+Math.sin(a)*r*1.0);x.lineWidth=Math.max(1,r*.12);x.strokeStyle='#11151b';x.stroke();}
  x.beginPath();x.arc(cx,cy,r*.5,0,Math.PI*2);x.fillStyle=color;x.fill();x.beginPath();x.arc(cx,cy,r*.18,0,Math.PI*2);x.fillStyle='#11151b';x.fill();x.restore();
}
const sets=new Set();
function watch(map){sets.add(map);return map;}
let lastFrame=performance.now();
function animate(t){const dt=Math.min(.1,(t-lastFrame)/1000);lastFrame=t;sets.forEach(m=>m.forEach(g=>g.step(dt)));requestAnimationFrame(animate);}
requestAnimationFrame(animate);
window.addEventListener('resize',()=>sets.forEach(m=>m.forEach(g=>{g.dirty=true;})));
// km/h a escala igual que el Gran Premio: largo de pista / segundos * 3.6 * escala.
// Se calcula en vivo con la config actual (si cambia el largo o la escala, las tarjetas se actualizan).
function scaleKmh(seconds,cfg){const s=Number(seconds),len=Number(cfg&&cfg.track_length_m),sc=Number(cfg&&cfg.scale);return s>0&&Number.isFinite(s)&&Number.isFinite(len)&&len>0&&Number.isFinite(sc)?len/s*3.6*sc:null;}
function scaleKmhLabel(seconds,cfg){const v=scaleKmh(seconds,cfg);return v==null?'':Math.round(v)+' km/h';}
function fillAvgKmh(el,seconds,cfg){if(!el)return;const t=scaleKmhLabel(seconds,cfg);el.hidden=!t;if(el.textContent!==t)el.textContent=t;}
// ---------- Vida de llanta en las tarjetas (Práctica, Carrera, Gran Premio y Mi coche) ----------
// Es el MISMO valor que la Pit Box manda como «combustible» (D6), en %. No se inventa desgaste.
const TIRE_YELLOW=50,TIRE_RED=20;
function tireRed(cfg){const v=Number(cfg&&cfg.tire_red_pct);return Number.isFinite(v)&&v>=0&&v<=50?v:TIRE_RED;}
function tireLevel(pct,cfg){const v=Number(pct);if(pct==null||pct===''||!Number.isFinite(v))return null;return v<tireRed(cfg)?'roja':v<=TIRE_YELLOW?'amarilla':'verde';}
function tireName(cfg){const n=cfg&&typeof cfg.tire_name==='string'?cfg.tire_name.trim():'';return n||'Media';}
// Km a escala por vuelta = largo (m) × escala / 1000 (25 m × 32 = 0.8 km). Con la config actual, no fijo.
function kmPerLap(cfg){const len=Number(cfg&&cfg.track_length_m),sc=Number(cfg&&cfg.scale);return Number.isFinite(len)&&len>0&&Number.isFinite(sc)&&sc>0?len*sc/1000:null;}
function fmtKm(km){if(km==null||!Number.isFinite(Number(km)))return '—';const v=Number(km);return (v<100?v.toFixed(1):String(Math.round(v)))+' km';}
// Vueltas y km con el juego de llantas actual: el servidor lo manda en pits.llanta (se reinicia en cada parada).
function tireSet(pits,cfg){const l=pits&&pits.llanta;if(!l)return null;const n=Number.isInteger(l.vueltas)?l.vueltas:0,k=kmPerLap(cfg);return {vueltas:n,km:k==null?null:n*k,juego:l.juego||1};}
function tireSetText(set){if(!set)return '';return set.vueltas+' vuelta'+(set.vueltas===1?'':'s')+' · '+fmtKm(set.km)+' con este juego';}
const SVGNS='http://www.w3.org/2000/svg';
function tireSvg(){const s=document.createElementNS(SVGNS,'svg');s.setAttribute('viewBox','0 0 24 24');s.setAttribute('class','tire-icon');s.setAttribute('aria-hidden','true');
  const add=(tag,at)=>{const e=document.createElementNS(SVGNS,tag);Object.entries(at).forEach(([k,v])=>e.setAttribute(k,v));s.append(e);return e;};
  add('circle',{cx:12,cy:12,r:10.5,fill:'#1b1f26',stroke:'#cfd6df','stroke-width':2});
  for(let i=0;i<8;i++){const a=i*Math.PI/4;add('line',{x1:12+Math.cos(a)*8.6,y1:12+Math.sin(a)*8.6,x2:12+Math.cos(a)*11.4,y2:12+Math.sin(a)*11.4,stroke:'#11151b','stroke-width':1.6});}
  add('circle',{cx:12,cy:12,r:5.2,class:'tire-rim'});add('circle',{cx:12,cy:12,r:1.8,fill:'#11151b'});return s;}
// Arma (una vez) el bloque de llanta dentro de box: ícono, «Vida de llanta», %, barra, nombre y vueltas/km del juego.
function buildTire(box){if(box.querySelector('.tire-pct'))return;box.replaceChildren();
  const head=document.createElement('div');head.className='tire-head';const lab=document.createElement('span');lab.className='tire-label';lab.textContent='Vida de llanta';
  const name=document.createElement('em');name.className='tire-name';const pct=document.createElement('strong');pct.className='tire-pct';pct.textContent='—';
  head.append(tireSvg(),lab,name,pct);
  const bar=document.createElement('div');bar.className='tire-bar';const fill=document.createElement('i');bar.append(fill);
  const set=document.createElement('small');set.className='tire-set';
  const warn=document.createElement('div');warn.className='tire-warn';warn.setAttribute('role','alert');warn.textContent='CAMBIA LLANTAS / ENTRA A PITS';warn.hidden=true;
  box.append(head,bar,set,warn);}
// opts: {pits, inPits, finished, off}. off = vida de llanta apagada en Configuración.
function fillTire(box,pct,cfg,opts){if(!box)return;opts=opts||{};buildTire(box);
  const off=!!opts.off,lvl=off?null:tireLevel(pct,cfg),v=lvl?Math.max(0,Math.min(100,Number(pct))):null;
  box.hidden=off;box.dataset.nivel=lvl||'';box.dataset.vida=v==null?'':String(Math.round(v));
  const set=(sel,t)=>{const e=box.querySelector(sel);if(e.textContent!==t)e.textContent=t;};
  set('.tire-pct',v==null?'—':Math.round(v)+'%');set('.tire-name',tireName(cfg));
  const fill=box.querySelector('.tire-bar i'),w=(v==null?0:v)+'%';if(fill.style.width!==w)fill.style.width=w;
  const ts=tireSet(opts.pits,cfg);set('.tire-set',opts.inPits?'Cambiando llantas…':tireSetText(ts));
  const warn=box.querySelector('.tire-warn');warn.hidden=!(lvl==='roja'&&!opts.inPits&&!opts.finished);
  box.closest('.gcard,.mc-dash')?.classList.toggle('tire-low',!warn.hidden);}
window.PeluGauges={Gauge,dial,watch,scaleKmh,scaleKmhLabel,fillAvgKmh,tireLevel,tireName,tireRed,kmPerLap,fmtKm,tireSet,tireSetText,tireSvg,fillTire,TIRE_YELLOW,TIRE_RED};
})();
