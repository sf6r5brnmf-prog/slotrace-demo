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
// DEMO · SONIDO PARA iPhone/iPad. En la demo el sonido viene encendido de fábrica en cada equipo nuevo
// (en la pista real hay que tocar «Activar sonido aquí»). Todos los sonidos (mp3 y explosión) pasan por UN solo
// AudioContext que se desbloquea con cualquier toque; en iOS 17+ se pide sesión de audio «playback» para que
// el switch de silencio no lo calle.
(function(){
  if(window.parent===window)return;
  var NativeAC=window.AudioContext||window.webkitAudioContext;if(!NativeAC)return;
  try{if(localStorage.getItem('gp-sound')===null)localStorage.setItem('gp-sound','on');}catch(e){}
  function session(){try{if(navigator.audioSession&&navigator.audioSession.type!=='playback')navigator.audioSession.type='playback';}catch(e){}}
  session();
  var ctx=null,bufs={},stats={plays:0,started:0,skipped:0,errors:0,loaded:0,unlocks:0};window.DEMO_SFX=stats;
  function getCtx(){if(!ctx||ctx.state==='closed'){ctx=new NativeAC();}return ctx;}
  stats.state=function(){return ctx?ctx.state:'none';};
  function unlock(){
    session();var c=getCtx();stats.unlocks++;
    if(c.state!=='running'){try{c.resume();}catch(e){}}
    try{var b=c.createBuffer(1,1,22050),s=c.createBufferSource();s.buffer=b;s.connect(c.destination);s.start(0);}catch(e){}
  }
  ['touchstart','touchend','pointerdown','pointerup','click','keydown'].forEach(function(t){document.addEventListener(t,unlock,{capture:true,passive:true});});
  // La explosión (explosion.js) usa este mismo contexto.
  var Shared=function(){return getCtx();};Shared.prototype=NativeAC.prototype;
  window.AudioContext=Shared;window.webkitAudioContext=Shared;
  function load(url){
    if(!bufs[url])bufs[url]=fetch(url).then(function(r){if(!r.ok)throw Error('HTTP '+r.status);return r.arrayBuffer();})
      .then(function(ab){return new Promise(function(res,rej){getCtx().decodeAudioData(ab,res,rej);});})
      .then(function(b){stats.loaded++;return b;},function(e){stats.errors++;delete bufs[url];console.warn('[demo sonido] no cargó',url,e);throw e;});
    return bufs[url];
  }
  function ready(c){
    if(c.state==='running')return Promise.resolve(true);
    var p;try{p=c.resume();}catch(e){p=null;}
    return Promise.race([Promise.resolve(p).then(function(){return c.state==='running';},function(){return false;}),new Promise(function(r){setTimeout(function(){r(c.state==='running');},400);})]);
  }
  function DemoAudio(src){this._src='';this.volume=1;this.muted=false;this.paused=true;this.preload='auto';this.loop=false;this._off=0;this._t0=0;this._node=null;this._tok=0;this._dur=NaN;if(src)this.src=src;}
  Object.defineProperty(DemoAudio.prototype,'src',{get:function(){return this._src;},set:function(v){var self=this;this._src=new URL(v,location.href).href;load(this._src).then(function(b){self._dur=b.duration;}).catch(function(){});}});
  Object.defineProperty(DemoAudio.prototype,'duration',{get:function(){return this._dur;}});
  Object.defineProperty(DemoAudio.prototype,'currentTime',{
    get:function(){return this.paused||!ctx?this._off:this._off+(ctx.currentTime-this._t0);},
    set:function(v){this._off=Math.max(0,+v||0);if(!this.paused){this._stopNode();this.paused=true;this.play();}}});
  DemoAudio.prototype._stopNode=function(){if(this._node){try{this._node.onended=null;this._node.stop();}catch(e){}this._node=null;}};
  DemoAudio.prototype.play=function(){
    var self=this,tok=++this._tok,c=getCtx();stats.plays++;this.paused=false;
    return Promise.all([load(this._src),ready(c)]).then(function(r){
      if(tok!==self._tok||self.paused)return;
      var buf=r[0];self._dur=buf.duration;
      if(self.muted)return;                           // «toque de calentamiento» de la app: no suena
      if(!r[1]){stats.skipped++;self.paused=true;return;}  // audio aún bloqueado: falta un toque en la pantalla
      self._stopNode();
      var off=Math.min(self._off,Math.max(0,buf.duration-0.01)),s=c.createBufferSource(),g=c.createGain();
      s.buffer=buf;g.gain.value=Math.max(0,Math.min(1,+self.volume));s.connect(g);g.connect(c.destination);
      s.onended=function(){if(self._node===s){self._node=null;self.paused=true;self._off=0;}};
      s.start(0,off);self._t0=c.currentTime-0;self._off=off;self._node=s;stats.started++;
    });
  };
  DemoAudio.prototype.pause=function(){if(this.paused)return;this._off=this.currentTime;this._tok++;this._stopNode();this.paused=true;};
  DemoAudio.prototype.load=function(){};
  DemoAudio.prototype.cloneNode=function(){var a=new DemoAudio(this._src);a.volume=this.volume;a.preload=this.preload;return a;};
  DemoAudio.prototype.addEventListener=function(){};DemoAudio.prototype.removeEventListener=function(){};
  DemoAudio.prototype.setAttribute=function(k,v){if(k==='src')this.src=v;};
  window.Audio=DemoAudio;
  document.addEventListener('visibilitychange',function(){if(!document.hidden&&ctx&&ctx.state!=='running'){try{ctx.resume();}catch(e){}}});
})();
