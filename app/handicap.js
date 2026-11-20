'use strict';
// Handicap · ajuste de tiempo por vuelta por clase de coche (Con imán / Sin imán / Modificado).
// Compartido por Práctica/Carrera (app.js), Gran Premio (gp.js) y Mi coche (micoche.js). Los cálculos y el orden
// los hace la Mac; aquí solo se muestran: tiempo con handicap + «H» chiquita, y el tiempo real abajo.
(function(){
  const CLASES=[['sin_iman','Sin imán'],['con_iman','Con imán'],['modificado','Modificado']];
  const ICON={sin_iman:'○',con_iman:'🧲',modificado:'🔧'};
  const NOMBRE=Object.fromEntries(CLASES);
  function segTxt(v){v=Number(v)||0;if(!v)return '0 s';return (v>0?'+':'−')+String(Math.round(Math.abs(v)*100)/100)+' s';}
  function adj(raw,h){return raw==null||!Number.isFinite(Number(raw))?null:Math.round((Number(raw)+(Number(h)||0))*1000)/1000;}
  function label(clase,h){return (ICON[clase]||'')+' '+(NOMBRE[clase]||'Sin imán')+' '+segTxt(h);}
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
  window.PeluHandicap={CLASES,ICON,NOMBRE,segTxt,adj,label,setTime};
})();
