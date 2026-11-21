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
  window.PeluHandicap={CLASES,ICON,NOMBRE,MIN_VUELTA_H,segTxt,adj,label,setTime,upgrade};
})();
