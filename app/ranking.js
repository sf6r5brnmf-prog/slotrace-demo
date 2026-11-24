'use strict';
// 🏆 Ranking de pilotos por clase de coche: mejor vuelta REAL (sin ningún hándicap) de todo su historial.
// El nivel (Novato / Intermedio / Experto) sale de los tiempos de corte de cada clase, también con tiempos reales.
(function(){
const $=id=>document.getElementById(id);
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;};
const H=window.PeluHandicap;
let data=null,hcfg=null,clase=null,sig='';
function conn(ok){const c=$('connection');c.textContent=ok?'● En vivo':'Sin conexión con la Mac';c.classList.toggle('live',ok);}
async function load(){
  try{const r=await fetch('/api/ranking',{cache:'no-store'});if(!r.ok)throw Error();data=await r.json();conn(true);}catch(e){conn(false);return;}
  try{const r=await fetch('/api/vueltas-config',{cache:'no-store'});if(r.ok)hcfg=(await r.json()).handicap;}catch(e){}
  render();
}
async function save(part){
  try{const r=await fetch('/api/vueltas-config',{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify({handicap:part})});
    const d=await r.json();if(!r.ok)throw Error(d.error||'No se pudo guardar.');hcfg=d.handicap;$('rkMsg').textContent='';sig='';await load();}
  catch(e){$('rkMsg').textContent=e.message||'No hay conexión con la Mac.';}
}
function render(){
  if(!data)return;const s=JSON.stringify([data,hcfg,clase]);if(s===sig)return;sig=s;
  if(!clase){clase=data.orden.find(k=>data.clases[k].pilotos.length)||data.orden[0];}
  $('rkMin').textContent=data.min_vueltas;
  const tabs=$('rkTabs');tabs.replaceChildren();
  data.orden.forEach(k=>{const c=data.clases[k],b=el('button','gar-tab'+(k===clase?' on':''));b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-selected',String(k===clase));b.dataset.clase=k;
    b.append(document.createTextNode(c.icon+' '+c.nombre+' '),el('b','',String(c.pilotos.length)));b.addEventListener('click',()=>{clase=k;render();});tabs.append(b);});
  const c=data.clases[clase];$('rkCortes').textContent='Cortes de nivel ('+c.icon+' '+c.nombre+'): '+c.cortes;
  const list=$('rkList');list.replaceChildren();
  if(!c.pilotos.length){const li=el('li','rk-empty');li.append(el('strong','','Todavía no hay tiempos con coches '+c.nombre.toLowerCase()),el('p','muted','Corre una Práctica, Carrera o Gran Premio con un coche de esta clase del Garage.'));list.append(li);}
  c.pilotos.forEach(p=>{const li=el('li','rk-row'+(p.pos<=3?' top'+p.pos:''));
    li.append(el('b','rk-pos',p.pos<=3?['🥇','🥈','🥉'][p.pos-1]:String(p.pos)));
    const who=el('div','rk-who');who.append(el('strong','',p.name));
    const sub=el('small','muted',p.vueltas+' vueltas · '+p.sesiones+(p.sesiones===1?' sesión':' sesiones')+(p.fuente?' · récord en '+p.fuente:''));who.append(sub);
    const nv=el('div','rk-nv');
    if(p.nivel){nv.append(el('span','nivel-chip nv-'+p.nivel,H.NIVEL_ICON[p.nivel]+' '+H.nivelTxt(p.nivel)));}
    else nv.append(el('span','muted','No está en el registro'));
    if(p.nivel_tiempo&&p.nivel&&p.nivel_tiempo!==p.nivel)nv.append(el('small','rk-sug','Por su tiempo: '+H.NIVEL_ICON[p.nivel_tiempo]+' '+H.nivelTxt(p.nivel_tiempo)));
    who.append(nv);
    li.append(who,el('span','rk-time',p.mejor.toFixed(2)+' s'));list.append(li);});
  const modo=(data.nivel_auto||'sugerir');$('rkModo').textContent='Ahora: '+((H.AUTO.find(x=>x[0]===modo)||[,''])[1])+'. Los cambios de nivel usan la mejor vuelta real de cada sesión.';
  if(hcfg&&!$('rkAjustes').contains(document.activeElement))H.nivelSettings($('rkNivel'),hcfg,save,m=>{$('rkMsg').textContent=m;});
}
load();setInterval(()=>{if(!document.hidden)load();},4000);
})();
