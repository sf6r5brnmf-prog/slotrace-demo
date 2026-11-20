'use strict';
// DEMO: esta página de la app real habla con el servidor de la pista que corre en la ventana de arriba (shell.js), sin red.
(function(){
  var P=null;try{if(window.parent!==window&&window.parent.DEMO_API)P=window.parent;}catch(e){}
  if(!P){var page=location.pathname.split('/').pop()||'index.html';location.replace('../?p='+encodeURIComponent(page+location.search));return;}
  var api=P.DEMO_API,orig=window.fetch;
  function apiPath(u){try{var x=new URL(u,location.href);return x.origin===location.origin&&x.pathname.indexOf('/api/')===0?x.pathname+x.search:null;}catch(e){return null;}}
  window.fetch=function(input,init){
    var url=typeof input==='string'?input:(input&&input.url)||String(input),p=apiPath(url);
    if(!p)return orig.apply(window,arguments);
    init=init||{};var sig=init.signal;
    return new Promise(function(resolve,reject){
      if(sig&&sig.aborted)return reject(new DOMException('Aborted','AbortError'));
      api.request(init.method||'GET',p,init.headers||{},init.body).then(function(r){resolve(new Response(r.body,{status:r.status,headers:r.headers}));},reject);
    });
  };
  document.addEventListener('click',function(e){
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;if(!a)return;
    var h=a.getAttribute('href')||'';if(h.indexOf('/api/')===0){e.preventDefault();api.download(h);}
  },true);
})();
