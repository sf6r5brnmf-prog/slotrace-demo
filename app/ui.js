// Orden en pantalla: pestañas de Configuración, píldora de estado (Pit Box / sensor / Mac) y «ⓘ ver más» en textos de ayuda largos.
(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  // ---- ⓘ ver más: la ayuda larga queda en una línea hasta que la tocas ----
  const LARGO=90;
  if(!document.getElementById('uiHelpCss')){const st=document.createElement('style');st.id='uiHelpCss';
    st.textContent='.help.ui-clamp{display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}.help.ui-clamp::before{content:"ⓘ ver más · ";font-weight:700;opacity:.85}.help.ui-open{display:block;cursor:pointer}.help.ui-open::before{content:"ⓘ ver menos · ";font-weight:700;opacity:.85}';
    document.head.append(st);}
  function marcar(n){if(!n.classList||!n.classList.contains('help')||n.classList.contains('ui-open'))return;
    const largo=(n.textContent||'').trim().length>LARGO;n.classList.toggle('ui-clamp',largo);
    if(largo){n.setAttribute('role','button');n.tabIndex=0;n.title='Toca para ver la explicación completa';}else if(n.getAttribute('role')==='button'){n.removeAttribute('role');n.removeAttribute('tabindex');}}
  function barrer(root){if(root.nodeType!==1)return;if(root.classList.contains('help'))marcar(root);root.querySelectorAll&&root.querySelectorAll('.help').forEach(marcar);}
  let pend=new Set(),prog=false;
  new MutationObserver(ms=>{ms.forEach(m=>{const t=m.type==='characterData'?m.target.parentElement:m.target;if(t)pend.add(t);m.addedNodes&&m.addedNodes.forEach(n=>n.nodeType===1&&pend.add(n));});
    if(!prog){prog=true;requestAnimationFrame(()=>{prog=false;const p=pend;pend=new Set();p.forEach(n=>{if(n.closest&&n.closest('.help'))marcar(n.closest('.help'));barrer(n);});});}})
    .observe(document.documentElement,{subtree:true,childList:true,characterData:true});
  function toggle(h){if(h.classList.contains('ui-open')){h.classList.remove('ui-open');marcar(h);}else{h.classList.remove('ui-clamp');h.classList.add('ui-open');}}
  document.addEventListener('click',e=>{const h=e.target.closest&&e.target.closest('.help.ui-clamp,.help.ui-open');if(!h||e.target.closest('a,button,input,select,label'))return;toggle(h);});
  document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.classList&&(e.target.classList.contains('ui-clamp')||e.target.classList.contains('ui-open'))){e.preventDefault();toggle(e.target);}});
  // ---- pestañas de Configuración ----
  function tabs(){
    const bar=document.querySelector('.cfg-tabs');if(!bar)return;
    const go=name=>{bar.querySelectorAll('[data-tab]').forEach(b=>{const on=b.dataset.tab===name;b.classList.toggle('on',on);b.setAttribute('aria-selected',on?'true':'false');});
      document.querySelectorAll('.cfg-panel').forEach(p=>p.hidden=p.dataset.panel!==name);try{sessionStorage.setItem('cfg-tab',name);}catch(e){}};
    bar.addEventListener('click',e=>{const b=e.target.closest('[data-tab]');if(b)go(b.dataset.tab);});
    let first='pista';try{first=sessionStorage.getItem('cfg-tab')||'pista';}catch(e){}if(!bar.querySelector('[data-tab="'+first+'"]'))first='pista';go(first);
    window.PeluConfigTab=go;
  }
  // ---- píldora de estado: un renglón; el detalle (Pit Box, sensor, Mac) al tocarla ----
  function pill(){
    const p=$('statusPill'),d=$('statusDetails');if(!p||!d)return;
    p.addEventListener('click',()=>{d.hidden=!d.hidden;p.setAttribute('aria-expanded',d.hidden?'false':'true');});
    const upd=()=>{
      const scx=$('scxStatus'),sen=$('sensorStatus'),con=$('connection');
      const macOk=!!con&&con.classList.contains('ok');
      const scxOk=scx&&scx.classList.contains('connected'),irOk=sen&&sen.classList.contains('connected');
      const parts=[scxOk?'Pit Box ✓':'Pit Box ✗',irOk?'sensor ✓':'sensor ✗',macOk?'en vivo':'sin Mac'];
      const t=parts.join(' · ');const tx=$('statusPillText');if(tx&&tx.textContent!==t)tx.textContent=t;
      p.classList.toggle('ok',macOk&&(scxOk||irOk));p.classList.toggle('bad',!macOk);
    };
    upd();setInterval(upd,1000);
  }
  function init(){tabs();pill();barrer(document.body);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
