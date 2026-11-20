'use strict';
const $=id=>document.getElementById(id);
function el(t,c,x){const e=document.createElement(t);if(c)e.className=c;if(x!==undefined&&x!==null)e.textContent=x;return e;}
function table(head,rows){const t=el('table'),h=el('tr');head.forEach(x=>h.append(el('th','',x)));const th=el('thead');th.append(h);const tb=el('tbody');rows.forEach(r=>{const tr=el('tr');r.forEach(v=>tr.append(el('td','',v)));tb.append(tr);});t.append(th,tb);return t;}
const pct=v=>v==null?'—':v+'%';let layoutsFilled=false;
async function poll(){
  try{const d=await (await fetch('/api/scx',{cache:'no-store'})).json();
    $('st').textContent=d.connected?'● '+(d.simulated?'SIMULADOR':'Conectada')+' · '+d.port:'● '+(d.error||'Sin datos');$('st').className='chip '+(d.connected?'ok':'bad');
    if(!layoutsFilled){Object.entries(d.layouts).forEach(([k,v])=>{const o=el('option','',k+' — '+v);o.value=k;$('layout').append(o);});layoutsFilled=true;}
    if(document.activeElement!==$('layout'))$('layout').value=d.fuel_layout;
    const last=d.raw_d6[0];
    $('fuelTable').replaceChildren(last?table(['Acomodo','C1','C2','C3','C4','C5','C6'],Object.entries(last.layouts).map(([k,v])=>[(k===d.fuel_layout?'▶ ':'')+k].concat(v.map(pct)))):el('p','muted','Todavía no llega ningún D6. ¿Está encendida la Pit Box?'));
    $('info').replaceChildren(table(['Dato','Valor'],[['Puerto',d.port||'—'],['Velocidad',d.baud+' 8N1'],['Desgaste de llanta en Pit Box (consumo)',d.fuel_consumo==null?'—':d.fuel_consumo?'activo (14 50)':'apagado (00 50)'],['Bytes descartados (re-sincronía)',d.dropped_bytes],['CRC: valor inicial que cuadra',d.crc_init_guess.map(x=>x.init+' ('+x.frames+')').join(', ')||'—']].concat(Object.entries(d.counts).map(([k,v])=>['Tramas '+k,v]))));
    $('thr').replaceChildren(table(['Mando','1','2','3','4','5','6'],[['Gatillo'].concat(d.throttle.map(v=>v==null?'—':v))]));
    $('d6').replaceChildren(table(['Hora','Bytes','Niveles (acomodo actual)'],d.raw_d6.slice(0,15).map(e=>[new Date(e.t*1000).toLocaleTimeString('es-MX'),e.hex,e.niveles[d.fuel_layout].map(v=>v==null?'—':v).join(' ')])));
    $('ee').replaceChildren(table(['Hora','Coche(s) en meta'],d.crossings.slice(0,10).map(e=>[new Date(e.t*1000).toLocaleTimeString('es-MX'),e.cars.join(', ')])));
    $('d4').replaceChildren(table(['Hora','Coche','Vuelta','Tiempo Pit Box'],d.d4.slice(0,10).map(e=>[new Date(e.t*1000).toLocaleTimeString('es-MX'),e.car+1,e.lap,e.seconds.toFixed(2)+' s'])));
    $('raw').replaceChildren(table(['Hora','Tipo','Bytes'],d.raw.slice(0,25).map(e=>[new Date(e.t*1000).toLocaleTimeString('es-MX'),e.cmd,e.hex])));
  }catch(e){$('st').textContent='Sin respuesta de la Mac';$('st').className='chip bad';}
}
$('layout').addEventListener('change',async()=>{try{const r=await fetch('/api/gp/config',{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify({config:{fuel_layout:$('layout').value}})});const d=await r.json();if(!r.ok)throw Error(d.error);$('layoutMsg').textContent='Guardado ✓';}catch(e){$('layoutMsg').textContent=e.message;}});
poll();setInterval(poll,500);
