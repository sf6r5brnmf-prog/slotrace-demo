// ⚑ Puto el último / 🍻 El último paga las chelas: tablero del juego, pantalla de castigo, cuenta de la noche,
// sonidos generados aquí mismo (Web Audio, sin archivos) y bus interno de eventos (sin red).
(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const el=(t,c,txt)=>{const e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e;};
  const fmtT=ms=>{ms=Math.max(0,ms);const s=Math.ceil(ms/1000);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0');};

  // ---------- bus interno (para Home Assistant más adelante; hoy no sale nada a la red) ----------
  const oyentes=new Set();
  const Bus={on(fn){oyentes.add(fn);return()=>oyentes.delete(fn);},emit(ev){oyentes.forEach(fn=>{try{fn(ev);}catch(e){}});try{window.dispatchEvent(new CustomEvent('slotrace:evento',{detail:ev}));}catch(e){}},ultimos:[]};
  window.SlotraceEventos=Bus;

  // ---------- sonidos generados ----------
  let ctx=null;
  function puede(){try{return !!(sfxDevice&&sfxUnlocked&&sfxVolume()>0);}catch(e){return false;}}
  function vol(){try{return sfxVolume();}catch(e){return .8;}}
  function ac(){if(!ctx){const C=window.AudioContext||window.webkitAudioContext;if(!C)return null;ctx=new C();}if(ctx.state!=='running')ctx.resume().catch(()=>{});return ctx;}
  document.addEventListener('pointerdown',()=>{if(puede())ac();},{passive:true});
  function tono(f,dur,o={}){const c=ac();if(!c)return;const t=c.currentTime+(o.t0||0),os=c.createOscillator(),gn=c.createGain();os.type=o.tipo||'sine';os.frequency.setValueAtTime(f,t);if(o.f2)os.frequency.exponentialRampToValueAtTime(o.f2,t+dur);
    gn.gain.setValueAtTime(0.0001,t);gn.gain.exponentialRampToValueAtTime(Math.max(0.0002,(o.v||.3)*vol()),t+(o.ataque||.01));gn.gain.exponentialRampToValueAtTime(0.0001,t+dur);os.connect(gn).connect(c.destination);os.start(t);os.stop(t+dur+.05);}
  function ruido(dur,o={}){const c=ac();if(!c)return;const n=Math.floor(c.sampleRate*dur),b=c.createBuffer(1,n,c.sampleRate),d=b.getChannelData(0);for(let i=0;i<n;i++)d[i]=Math.random()*2-1;
    const s=c.createBufferSource();s.buffer=b;const t=c.currentTime+(o.t0||0),fl=c.createBiquadFilter();fl.type=o.tipo||'lowpass';fl.frequency.setValueAtTime(o.f||1000,t);if(o.f2)fl.frequency.exponentialRampToValueAtTime(o.f2,t+dur);fl.Q.value=o.q||1;
    const gn=c.createGain();gn.gain.setValueAtTime(0.0001,t);gn.gain.exponentialRampToValueAtTime(Math.max(0.0002,(o.v||.3)*vol()),t+(o.ataque||.005));gn.gain.exponentialRampToValueAtTime(0.0001,t+dur);s.connect(fl).connect(gn).connect(c.destination);s.start(t);s.stop(t+dur+.05);}
  const SON={
    bip(){tono(1046,.09,{tipo:'square',v:.16});},
    bipFinal(){tono(1568,.4,{tipo:'square',v:.2});},
    corte(){[0,.3].forEach(t=>{tono(98,.26,{tipo:'sawtooth',v:.35,t0:t});tono(104,.26,{tipo:'sawtooth',v:.25,t0:t});});tono(98,.7,{tipo:'sawtooth',v:.35,t0:.6});tono(104,.7,{tipo:'sawtooth',v:.25,t0:.6});},
    boom(){ruido(1.5,{v:.9,tipo:'lowpass',f:2200,f2:50,ataque:.003});tono(72,.9,{v:.7,f2:28});},
    bomba(){ruido(1.0,{v:.10,tipo:'highpass',f:3500,q:.7,ataque:.06});for(let i=0;i<8;i++)ruido(.03,{v:.25,tipo:'highpass',f:4000,t0:i*.12});setTimeout(()=>{if(puede())SON.boom();},1000);},
    abucheo(){[196,207,220,233,185,175].forEach((f,i)=>tono(f,1.9,{tipo:'sawtooth',v:.07,t0:i*.06,f2:f*.6,ataque:.15}));ruido(1.9,{v:.12,tipo:'bandpass',f:450,q:.8,ataque:.25});},
    lata(){ruido(.04,{v:.7,tipo:'highpass',f:2500});ruido(.8,{v:.35,tipo:'bandpass',f:6000,f2:2200,q:1.4,ataque:.008,t0:.04});tono(1900,.05,{tipo:'triangle',v:.15,t0:.02});},
    peligro(){tono(440,.12,{tipo:'triangle',v:.25});tono(330,.2,{tipo:'triangle',v:.25,t0:.15});},
    ganador(){[523,659,784,1046].forEach((f,i)=>tono(f,.2,{tipo:'triangle',v:.2,t0:i*.12}));},
    falso(){tono(220,.15,{tipo:'square',v:.2});tono(220,.15,{tipo:'square',v:.2,t0:.2});},
    salva(){tono(660,.12,{tipo:'sine',v:.25});tono(990,.25,{tipo:'sine',v:.25,t0:.12});}
  };
  function sonar(n){if(!puede()||!SON[n])return;try{SON[n]();}catch(e){}}
  const SON_DE={salida_falso:'falso',bomba:'bomba',peligro:'peligro',aviso_corte:'bipFinal',salvavidas:'salva',corte:'corte',puto:'abucheo',ganador:null,ultima_vuelta:'corte',chela:'lata',perdon:null};
  const ICON={salida_falso:'🟥',bomba:'💣',peligro:'⚠',aviso_corte:'⏳',salvavidas:'🛟',corte:'✂️',puto:'🚩',ganador:'🏆',ultima_vuelta:'🏁',chela:'🍺',perdon:'🙌'};

  // ---------- eventos nuevos de la sesión ----------
  let visto={id:null,n:0};
  function eventos(s,j){
    if(visto.id!==s.id){visto={id:s.id,n:j.n_ev};return;}   // al abrir no se repiten los viejos
    if(j.n_ev<=visto.n)return;
    const nuevos=j.eventos.filter(e=>e.n>visto.n);visto.n=j.n_ev;
    let delay=0;
    nuevos.forEach(ev=>{Bus.ultimos.push(ev);if(Bus.ultimos.length>40)Bus.ultimos.shift();Bus.emit(ev);
      const snd=SON_DE[ev.tipo];if(snd){setTimeout(()=>sonar(snd),delay);delay+=ev.tipo==='corte'?1300:ev.tipo==='bomba'?0:150;}});
  }

  // ---------- reloj del corte (se mueve solo entre lecturas; congelado en PARO) ----------
  let reloj={ms:null,at:0,corre:false,cb:null},ultimoSeg=null;
  setInterval(()=>{if(reloj.ms==null||!reloj.cb)return;const rem=reloj.ms-(reloj.corre?performance.now()-reloj.at:0);reloj.cb(rem);
    const sec=Math.ceil(rem/1000);if(reloj.corre&&sec<=10&&sec>=1&&sec!==ultimoSeg){ultimoSeg=sec;sonar('bip');}},200);

  function cfgChips(j){
    const c=j.cfg,out=[];
    if(c.bomba)out.push('💣 Bomba al líder +'+c.bomba_s+' s');
    if(c.falso)out.push('🟥 Salida en falso −'+c.falso_vueltas+' v');
    out.push(c.banderas>0?'🟨 '+c.banderas+' banderas c/u':'🟨 sin banderas');
    if(c.rebufo)out.push('⚡ Rebufo −'+c.rebufo_s+' s/vuelta al último');
    if(j.modo==='ultimo'&&c.salvavidas)out.push('🛟 Salvavidas');
    if(j.modo==='chelas'&&c.perdon)out.push('🙌 Al ganador se le perdona 1');
    return out;
  }
  function banner(s,j){
    const b=$('corteBanner');b.hidden=false;b.className='corte-banner '+j.modo;b.replaceChildren();
    const c=j.corte||{},ended=s.phase==='ended',pre=s.phase==='ready'||s.phase==='countdown';
    const left=el('div','cb-left'),big=el('div','cb-big'),lab=el('div','cb-lab');
    let eyebrow='',sub='';reloj.cb=null;reloj.ms=null;
    if(ended){
      const r=j.resultado;b.classList.add('fin');
      eyebrow=j.modo==='ultimo'?'✂️ CORTE':'🏁 RONDA TERMINADA';
      big.textContent=r?(j.modo==='ultimo'?'🚩 '+r.name:'🍺 '+r.name):'—';lab.textContent=r?(j.modo==='ultimo'?'es PUTO EL ÚLTIMO':'paga +'+r.suma+' chela'+(r.suma===1?'':'s')):s.notice||'Ronda cancelada';
    }else if(c.tipo==='vueltas'){
      eyebrow=pre?'PRÓXIMO CORTE':'⚑ PRÓXIMO CORTE';
      big.textContent=String(c.faltan);lab.textContent=c.faltan===1?'¡ÚLTIMA VUELTA DEL LÍDER ANTES DEL CORTE!':'vueltas del líder para el corte';
      sub='Líder: '+j.lider_vueltas+' / '+c.meta+' · al corte, el último es el Puto';
      if(c.faltan<=1&&!pre)b.classList.add('urge');
    }else if(c.tipo==='tiempo'||c.tipo==='terminando'){
      const term=c.tipo==='terminando';
      eyebrow=term?'🏁 ¡TIEMPO! TERMINEN SU VUELTA':j.modo==='chelas'?'🍻 RONDA '+(j.ronda||'')+' · TERMINA EN':'⚑ CORTE EN';
      lab.textContent=term?'para cerrar la ronda':j.modo==='chelas'?'el último al final suma una chela':'al corte, el último es el Puto';
      if(term){const faltan=s.pilots.filter(p=>!p.dsq&&!(c.cruzaron||[]).includes(p.slot)).map(p=>p.name);sub=faltan.length?'Faltan de cruzar: '+faltan.join(', '):'';b.classList.add('urge');}
      reloj={ms:c.faltan_ms,at:performance.now(),corre:s.phase==='running'&&!s.red,cb:rem=>{const t=fmtT(rem);if(big.textContent!==t)big.textContent=t;b.classList.toggle('urge',term||rem<=10000);}};
      big.textContent=fmtT(c.faltan_ms);
    }
    if(s.red&&!ended)sub='PARO: el reloj del juego está congelado';
    if(j.doble&&!ended)eyebrow+=' · 🍺×2 VALE DOBLE';
    left.append(el('p','cb-eyebrow',eyebrow),big,lab);if(sub)left.append(el('p','cb-sub',sub));
    b.append(left);
  }
  function filas(s,j){
    const box=$('juegoBoard');box.hidden=false;box.replaceChildren();
    const rows=j.tabla,n=rows.length,pre=s.phase==='ready'||s.phase==='countdown',ended=s.phase==='ended';
    const chips=el('div','j-chips');cfgChips(j).forEach(t=>chips.append(el('span','j-chip',t)));box.append(chips);
    const by=new Map(s.pilots.map(p=>[p.slot,p]));const R=typeof roster!=='undefined'?roster:null;
    rows.forEach((r,i)=>{
      const p=by.get(r.slot)||{},peligro=!pre&&n>1&&i===n-1&&(r.reales>0||r.dsq),row=el('div','jrow'+(peligro?' peligro':'')+(i===0&&!pre&&r.reales?' lider':'')+(r.dsq?' dsq':''));
      row.dataset.slot=r.slot;const hex=R&&R.colors&&R.colors[r.slot]?R.colors[r.slot].hex:'#888';row.style.setProperty('--team',hex);
      const pos=el('span','jpos',r.dsq?'DSQ':String(r.pos));
      const img=el('img','jav');try{img.src=avatarSrc(p.avatar);}catch(e){}img.alt='';img.addEventListener('error',()=>img.removeAttribute('src'),{once:true});
      const nm=el('div','jname');nm.append(el('b','',r.name));
      const tags=[];if(r.bombas)tags.push('💣 +'+r.pen_seg+' s');if(r.pen_vueltas)tags.push('🟥 −'+r.pen_vueltas+' v');if(p.banderas)tags.push('🟨 '+p.banderas+'/'+(j.cfg.banderas||0));if(r.rebufo)tags.push('⚡ −'+r.rebufo+' s');if(r.salvado)tags.push('🛟 usado');
      if(tags.length)nm.append(el('small','jtags',tags.join(' · ')));
      const v=el('div','jv');v.append(el('b','',String(r.vueltas)),el('small','','vuelta'+(r.vueltas===1?'':'s')));
      let gap='';if(i===0)gap=pre?'':r.reales?'LÍDER':'';else if(r.gap==='DSQ')gap='DSQ';else if(typeof r.gap==='number')gap='+'+r.gap.toFixed(2)+' s';else if(r.gap)gap=r.gap;
      row.append(pos,img,nm,v,el('div','jgap',gap));
      if(peligro){
        const prev=rows[i-1];let falta=typeof r.gap==='number'?'a '+r.gap.toFixed(2)+' s de salvarse':r.gap&&r.gap!=='DSQ'?'a '+r.gap.replace('−','')+' de salvarse':'';
        let t=(j.modo==='ultimo'?(ended?'🚩 PUTO EL ÚLTIMO':'⚠ ZONA DE PELIGRO'):(ended?'🍺 PAGA LA CHELA':'🍺 SI ASÍ ACABA, PAGA'))+(falta&&!ended?' · '+falta+(prev?' ('+prev.name+')':''):'');
        if(j.cfg.rebufo&&!ended)t+=' · ⚡ rebufo −'+j.cfg.rebufo_s+' s por vuelta mientras vaya último';
        row.append(el('div','jdanger',t));
      }
      box.append(row);
    });
    const tk=el('div','j-ticker');const evs=j.eventos.slice(-4).reverse();
    evs.forEach((e,k)=>tk.append(el('p',k?'':'nuevo',e.texto||((ICON[e.tipo]||'')+' '+(e.name||'')))));
    if(evs.length)box.append(tk);
    box.append(el('p','j-honesto help','💣 🟥 ⚡ son castigos de la app: se suman o restan en la tabla. La Pit Box no frena ni apaga ningún coche.'));
  }

  // ---------- pantalla de fin: castigo (Puto) o cuenta de chelas ----------
  let finVisto=new Set();try{finVisto=new Set(JSON.parse(sessionStorage.getItem('juego-fin-visto')||'[]'));}catch(e){}
  function cerrarFin(){const f=$('juegoFin');if(f&&!f.hidden){f.hidden=true;f.replaceChildren();}}
  function marcarVisto(id){finVisto.add(id);try{sessionStorage.setItem('juego-fin-visto',JSON.stringify([...finVisto].slice(-30)));}catch(e){}}
  function otraRonda(s,btn){
    btn.disabled=true;const box=$('juegoFin');
    sendLive({action:'start',type:'race',mode:s.mode,juego:true,slots:s.pilots.map(p=>p.slot)}).then(d=>{marcarVisto(s.id);cerrarFin();dismissedSessionId=null;applyLive(d,true);})
      .catch(e=>{btn.disabled=false;const er=box.querySelector('.jf-err');if(er)er.textContent=e.message;});
  }
  function cuentaTabla(tabla,paga){
    const t=el('div','jf-cuenta');
    (tabla||[]).forEach(x=>{const r=el('div','jf-crow'+(paga&&paga.names.includes(x.name)?' paga':''));r.append(el('span','',x.name),el('b','',(x.chelas>0?'🍺'.repeat(Math.min(x.chelas,8))+(x.chelas>8?'…':''):'—')+' '+x.chelas));t.append(r);});
    return t;
  }
  function fin(s,j){
    const r=j.resultado,box=$('juegoFin');
    if(!(s.phase==='ended'&&r&&(r.tipo==='puto'||r.tipo==='chelas'))||finVisto.has(s.id)){if(!(s.phase==='ended'&&r))cerrarFin();return;}
    if(!box.hidden&&box.dataset.sid===s.id)return;
    box.dataset.sid=s.id;box.replaceChildren();const card=el('div','jf-card '+r.tipo);
    const p=s.pilots.find(x=>x.slot===r.slot)||{};const img=el('img','jf-av');try{img.src=avatarSrc(p.avatar);}catch(e){}img.alt='';
    if(r.tipo==='puto'){
      card.append(el('p','jf-eyebrow','✂️ CORTE · '+(j.cfg.corte==='vueltas'?'VUELTA '+(j.corte?.meta||j.cfg.cada_vueltas)+' DEL LÍDER':'TIEMPO')),img);
      const h=el('h2','',r.name);h.id='jfTitulo';card.append(h,el('p','jf-big','PUTO EL ÚLTIMO'));
      const st=el('div','jf-stats');[[r.vueltas,'vueltas'],[r.falto||'—','le faltó'],[r.veces!=null?r.veces:'—','veces Puto']].forEach(([a,b])=>{const d=el('div');d.append(el('b','',String(a)),el('span','',b));st.append(d);});card.append(st);
      if(r.castigo){const c=el('div','jf-castigo');c.append(el('span','','CASTIGO'),el('b','',r.castigo));card.append(c);}
      if(r.ganador)card.append(el('p','jf-gana','🏆 Se salvó primero: '+r.ganador.name));
    }else{
      card.append(el('p','jf-eyebrow','🍻 RONDA '+(r.ronda||j.ronda||'')+' TERMINADA'),img);
      const h=el('h2','',r.name+' paga');h.id='jfTitulo';card.append(h,el('p','jf-big','+'+r.suma+' 🍺'+(r.suma>1?' (ronda doble)':'')));
      if(r.perdon&&r.ganador)card.append(el('p','jf-gana','🙌 '+r.ganador.name+' ganó la ronda: se le perdona 1 chela.'));else if(r.ganador)card.append(el('p','jf-gana','🏆 Ganó la ronda: '+r.ganador.name));
      card.append(el('p','jf-sub','CUENTA DE LA NOCHE'),cuentaTabla(r.cuenta,null));
      card.append(el('div','jf-doble-slot'));
    }
    const acts=el('div','jf-actions'),otra=el('button','primary big',r.tipo==='puto'?'▶ Otra ronda':'▶ Siguiente ronda');otra.type='button';otra.id='jfOtra';otra.addEventListener('click',()=>otraRonda(s,otra));
    const ver=el('button','ghost','Ver tabla');ver.type='button';ver.id='jfCerrar';ver.addEventListener('click',()=>{marcarVisto(s.id);cerrarFin();});
    acts.append(otra,ver);
    if(r.tipo==='chelas'){const cn=el('button','ghost','Cerrar la noche');cn.type='button';cn.id='jfCerrarNoche';cn.addEventListener('click',()=>cerrarNoche(cn,()=>{marcarVisto(s.id);cerrarFin();}));acts.append(cn);}
    card.append(acts,el('p','jf-err error'));box.append(card);box.hidden=false;
    loadEstado().then(pintarDoble);
  }
  function pintarDoble(){
    const slot=document.querySelector('#juegoFin .jf-doble-slot');if(!slot)return;
    const on=!!estado?.config?.chelas?.doble;let lb=slot.querySelector('.jf-doble');
    if(!on){slot.replaceChildren();return;}
    if(!lb){lb=el('label','jf-doble');const cb=el('input');cb.type='checkbox';cb.addEventListener('change',()=>post({action:'doble',on:cb.checked}).catch(e=>{cb.checked=!cb.checked;try{notify(e.message);}catch(x){}}));lb.append(cb,document.createTextNode(' 🍺×2 La siguiente ronda vale doble'));slot.append(lb);}
    const cb=lb.querySelector('input');if(document.activeElement!==cb)cb.checked=!!estado?.noche?.doble_siguiente;
  }

  // ---------- estado guardado (config, veces Puto, noche de chelas) ----------
  let estado=null,cargando=false;
  async function loadEstado(){if(cargando)return;cargando=true;try{const r=await fetch('/api/juego?ts='+Date.now(),{cache:'no-store'});if(r.ok){estado=await r.json();pintarNoche();pintarConfig();pintarDoble();}}catch(e){}finally{cargando=false;}}
  async function post(body){const r=await fetch('/api/juego',{method:'POST',headers:{'Content-Type':'application/json','X-Roster':'1'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'No se pudo guardar.');estado=d;pintarNoche();return d;}
  function cerrarNoche(btn,despues){
    const n=estado?.noche;const paga=n?.paga;
    if(!confirm('¿Cerrar la noche?'+(paga?'\n\nPaga: '+paga.names.join(' y ')+' ('+paga.chelas+' 🍺).':'')+'\n\nLa cuenta se guarda y la próxima ronda empieza una noche nueva.'))return;
    btn.disabled=true;post({action:'cerrar_noche'}).then(d=>{const c=d.cerrada;try{notify(c?'🍻 Noche cerrada. '+(paga?'Paga: '+paga.names.join(' y ')+' ('+paga.chelas+' 🍺)':''):'No había rondas en la noche.');}catch(e){}if(despues)despues();})
      .catch(e=>{try{notify(e.message);}catch(x){alert(e.message);}}).finally(()=>btn.disabled=false);
  }
  function pintarNoche(){
    const card=$('nocheCard');if(!card)return;const n=estado?.noche;
    if(!n||!n.rondas||!n.rondas.length){card.hidden=true;card.replaceChildren();return;}
    card.hidden=false;card.replaceChildren();
    const h=el('div','nc-head');h.append(el('b','','🍻 La noche va así · '+n.rondas.length+' ronda'+(n.rondas.length===1?'':'s')),el('span','nc-paga',n.paga?'Va pagando: '+n.paga.names.join(' y ')+' ('+n.paga.chelas+')':''));
    card.append(h,cuentaTabla(n.tabla,n.paga));
    const a=el('div','nc-actions'),sig=el('button','primary','▶ Siguiente ronda');sig.type='button';sig.addEventListener('click',()=>$('chelasAction').click());
    const cn=el('button','ghost','Cerrar la noche');cn.type='button';cn.id='cerrarNoche';cn.addEventListener('click',()=>cerrarNoche(cn));a.append(sig,cn);card.append(a);
  }
  // Reglas cortas en «¿Quiénes corren?»
  function reglas(modo){
    const box=$('juegoReglas');if(!box)return;
    if(modo!=='ultimo'&&modo!=='chelas'){box.hidden=true;box.replaceChildren();return;}
    const c=(estado?.config||{})[modo];box.hidden=false;box.replaceChildren();
    if(!c){loadEstado().then(()=>reglas(modo));return;}
    const head=modo==='ultimo'?(c.corte==='vueltas'?'✂️ Corte cuando el líder complete '+c.cada_vueltas+' vueltas':'✂️ Corte a los '+fmtT(c.cada_s*1000)+' min')+' · el último es el Puto':'⏱ Ronda de '+fmtT(c.ronda_s*1000)+' min · todos terminan su vuelta · el último +1 🍺';
    box.append(el('p','jr-head',head));const ch=el('div','j-chips');cfgChips({modo,cfg:c}).forEach(t=>ch.append(el('span','j-chip',t)));box.append(ch);
    if(modo==='ultimo'&&c.castigo)box.append(el('p','jr-castigo','Castigo: '+c.castigo));
    box.append(el('p','help','Necesita la Pit Box (tarjeta SCX). Se cambia en ⚙️ Configuración → Modos de juego.'));
  }

  // ---------- Configuración → Modos de juego ----------
  let cfgSig='';
  function pintarConfig(){
    const box=$('juegoConfig');if(!box||!estado)return;
    const sig=JSON.stringify([estado.config,estado.putos,estado.ultima_noche&&estado.ultima_noche.id]);if(sig===cfgSig)return;
    if(box.contains(document.activeElement))return;cfgSig=sig;box.replaceChildren();
    const C=estado.config;
    const campo=(modo,k,label,tipo,extra={})=>{
      const w=el('label','jc-f'+(tipo==='checkbox'?' chk':''));const i=el(tipo==='select'?'select':'input');i.dataset.modo=modo;i.dataset.k=k;i.id='jc_'+modo+'_'+k;
      if(tipo==='select'){extra.opts.forEach(([v,t])=>{const o=el('option','',t);o.value=v;i.append(o);});i.value=C[modo][k];}
      else if(tipo==='checkbox'){i.type='checkbox';i.checked=!!C[modo][k];}
      else{i.type=tipo;if(tipo==='number'){i.inputMode='decimal';i.step=extra.step||'1';if(extra.min!=null)i.min=extra.min;if(extra.max!=null)i.max=extra.max;}i.value=extra.div?String(C[modo][k]/extra.div):String(C[modo][k]);if(extra.div)i.dataset.div=extra.div;if(tipo==='text')i.maxLength=120;}
      if(tipo==='checkbox')w.append(i,el('span','',label));else w.append(el('span','',label),i);
      i.addEventListener('change',guardar);return w;
    };
    const u=el('fieldset','jc-box');u.append(el('legend','','⚑ Puto el último'),
      campo('ultimo','corte','Cortes por','select',{opts:[['vueltas','Vueltas del líder'],['tiempo','Tiempo']]}),
      campo('ultimo','cada_vueltas','Corte cada (vueltas del líder)','number',{min:2,max:50}),
      campo('ultimo','cada_s','Corte cada (minutos, si es por tiempo)','number',{step:'0.5',min:0.5,max:30,div:60}),
      campo('ultimo','castigo','Castigo del Puto','text'),
      campo('ultimo','bomba','💣 Bomba al líder','checkbox'),campo('ultimo','bomba_s','Segundos de la bomba','number',{step:'0.5',min:0.5,max:20}),
      campo('ultimo','falso','🟥 Salida en falso','checkbox'),campo('ultimo','falso_vueltas','Vueltas que cuesta','number',{min:0,max:5}),
      campo('ultimo','banderas','🟨 Banderas amarillas por piloto','number',{min:0,max:9}),
      campo('ultimo','rebufo','⚡ Rebufo para el último','checkbox'),campo('ultimo','rebufo_s','Segundos por vuelta','number',{step:'0.1',min:0,max:2}),
      campo('ultimo','salvavidas','🛟 Salvavidas (una vez por piloto, mueve el corte)','checkbox'));
    const c=el('fieldset','jc-box');c.append(el('legend','','🍻 El último paga las chelas'),
      campo('chelas','ronda_s','Duración de la ronda (minutos)','number',{step:'0.5',min:0.5,max:30,div:60}),
      campo('chelas','espera_s','Para terminar su vuelta (segundos)','number',{min:5,max:120}),
      campo('chelas','perdon','🙌 Al ganador de la ronda se le perdona 1 chela','checkbox'),
      campo('chelas','doble','🍺×2 Permitir «la siguiente ronda vale doble»','checkbox'),
      campo('chelas','bomba','💣 Bomba al líder','checkbox'),campo('chelas','bomba_s','Segundos de la bomba','number',{step:'0.5',min:0.5,max:20}),
      campo('chelas','falso','🟥 Salida en falso','checkbox'),campo('chelas','banderas','🟨 Banderas por piloto','number',{min:0,max:9}),
      campo('chelas','rebufo','⚡ Rebufo para el último','checkbox'));
    const msg=el('p','jc-msg');msg.id='juegoCfgMsg';msg.setAttribute('role','status');
    box.append(el('p','help','Todo esto son castigos de la app: se suman o restan en la tabla. La Pit Box no frena ningún coche. Los modos de juego necesitan la Pit Box (tarjeta SCX).'),u,c,msg);
    const sal=el('div','jc-box salon');sal.append(el('p','jc-t','🚩 Salón de los Putos'));
    if(estado.putos&&estado.putos.length)estado.putos.forEach(x=>{const r=el('div','jf-crow');r.append(el('span','',x.name),el('b','',x.n+' vez'+(x.n===1?'':'es')));sal.append(r);});else sal.append(el('p','help','Nadie todavía.'));
    if(estado.ultima_noche){const n=estado.ultima_noche,t=Object.values(n.cuenta||{}).sort((a,b)=>b.chelas-a.chelas)[0];if(t)sal.append(el('p','help','Última noche de chelas: pagó '+t.name+' ('+t.chelas+' 🍺).'));}
    box.append(sal);
  }
  function guardar(){
    const box=$('juegoConfig'),out={ultimo:{},chelas:{}};
    box.querySelectorAll('[data-modo]').forEach(i=>{let v=i.type==='checkbox'?i.checked:i.type==='number'?Number(i.value):i.value;if(i.dataset.div)v=Math.round(v*Number(i.dataset.div));out[i.dataset.modo][i.dataset.k]=v;});
    const m=$('juegoCfgMsg');m.textContent='Guardando…';m.classList.remove('error');
    post(Object.assign({action:'config'},out)).then(()=>{m.textContent='✓ Guardado. Aplica a la siguiente ronda.';cfgSig='';}).catch(e=>{m.textContent=e.message;m.classList.add('error');cfgSig='';pintarConfig();});
  }

  // ---------- render del tablero ----------
  function agujas(){try{return localStorage.getItem('juego-agujas')==='on';}catch(e){return false;}}
  function render(s){
    const j=s&&s.juego,scr=$('sessionScreen'),gt=$('gaugesToggle');
    scr.classList.toggle('juego-mode',!!j);document.body.classList.toggle('juego-on',!!j);
    if(!j){$('juegoBoard').hidden=true;$('corteBanner').hidden=true;gt.hidden=true;scr.classList.remove('agujas-off');reloj.cb=null;cerrarFin();return;}
    const ag=agujas();gt.hidden=false;gt.textContent=ag?'◉ Agujas':'○ Agujas';gt.setAttribute('aria-pressed',ag?'true':'false');scr.classList.toggle('agujas-off',!ag);
    eventos(s,j);banner(s,j);filas(s,j);fin(s,j);
  }
  function init(){
    const gt=$('gaugesToggle');if(gt)gt.addEventListener('click',()=>{try{localStorage.setItem('juego-agujas',agujas()?'off':'on');}catch(e){}const s=typeof activeSession!=='undefined'?activeSession:null;if(s)render(s);});
    loadEstado();setInterval(()=>{const sc=typeof screen==='string'?screen:'';if(sc==='home'||sc==='config'||sc==='choose')loadEstado();},5000);
    const pr=$('sfxPrueba');if(pr){pr.append(el('span','help','Probar: '));[['bip','⏱ Pitido'],['corte','✂️ Corte'],['bomba','💣 Bomba'],['abucheo','👎 Abucheo'],['lata','🍺 Lata']].forEach(([k,t])=>{const b=el('button','chip-button',t);b.type='button';b.addEventListener('click',()=>{if(!puede()){try{notify('Primero activa el sonido en este equipo.');}catch(e){}return;}ac();SON[k]();});pr.append(b);});}
  }
  window.PeluJuego={render,reglas,sonar,SON,estado:()=>estado,recargar:loadEstado};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
