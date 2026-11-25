"""Un solo trabajador accede a la ESP32; los GET sirven memoria, sin E/S remota."""
import collections,copy,csv,io,json,math,os,threading,time,uuid,shutil
import durable
import pits as pits_mod
import handicap as handicap_mod
import juego as juego_mod
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler

class LiveError(Exception):
    def __init__(self,message,status=400):super().__init__(message);self.status=status

READY_NOTICE='Todos a la línea de meta. Aprieta Empezar para el semáforo de salida.'
RESTART_READY_NOTICE='Se reinició el servidor durante el semáforo (¿se cerró la Mac o se fue la luz?). Todos a la línea de meta y aprieta Empezar otra vez.'
PHASES={'ready','countdown','resetting','waiting_sensor','running','paused','ended'}
# Al recuperar después de un reinicio, versión y control brincan para que ninguna pantalla abierta se quede con datos viejos.
RECOVERY_JUMP=1000
# Bandera roja (PARO): el cronómetro se congela y no cuenta ninguna vuelta hasta Reanudar (semáforo otra vez).
RED_NOTICE='🚩 BANDERA ROJA · PARO. Suelten el gatillo. El cronómetro está detenido y las vueltas no cuentan hasta Reanudar.'
RED_RESTART_NOTICE='Se reinició el servidor durante la BANDERA ROJA. La carrera sigue en PARO con sus vueltas guardadas; aprieta Reanudar para el semáforo.'
IR_MIN_LAP_S=0.5
# Bandera amarilla del piloto (triple clic en el botón de cambio de carril): es el MISMO PARO con otra etiqueta.
# Límite por piloto y por sesión (cada Práctica o Carrera); una más = DESCALIFICADO (sus vueltas ya no cuentan).
YELLOW_NOTICE='🟨 BANDERA AMARILLA · la pidió %s (%d de %d). Suelten el gatillo. El cronómetro está detenido y las vueltas no cuentan hasta Reanudar (pantalla grande).'
DSQ_NOTICE='⛔ %s DESCALIFICADO: pidió una bandera amarilla más de las %d permitidas. Sus vueltas ya no cuentan en esta sesión.'
FLAG_FALLBACK={'enabled':True,'clicks':3,'window_s':1.5,'max':4,'dsq':True}
# Vuelta mínima válida (data/vueltas.json, 10 s de fábrica). Una vuelta más corta NO cuenta (ni vueltas, ni mejor, ni
# agujas, ni posiciones) y queda guardada como «sospechosa» en p['sospechosas'] con tiempo, coche, hora y fuente.
# La siguiente vuelta válida se mide desde la última pasada VÁLIDA: el cruce falso no reinicia la vuelta.
# Por debajo de BOUNCE_S (anti-rebote de la tarjeta SCX) es el mismo cruce leído dos veces: se ignora sin registrar.
DEFAULT_MIN_LAP_S=10.0
BOUNCE_S=1.5
MAX_SOSPECHOSAS=300

def check_session(s):
    if not isinstance(s,dict) or not isinstance(s.get('id'),str) or s.get('phase') not in PHASES:raise ValueError('sesión inválida')
    if type(s.get('control'))!=int or type(s.get('version'))!=int or not isinstance(s.get('pilots'),list):raise ValueError('sesión inválida')
    for p in s['pilots']:
        if not isinstance(p,dict) or type(p.get('slot'))!=int or not isinstance(p.get('laps'),list):raise ValueError('piloto inválido')

class Live:
    SCX_MAX_LAPS=200
    REQUEST_TIMEOUT_S=1.5
    def __init__(self,directory,base_url,lap_config=None):
        # scx: el MISMO lector SCX del Gran Premio (solo lectura). gp_busy(): True si una parte del GP está corriendo.
        # track(): (metros de la pista, escala) del Gran Premio para calcular km/h igual en todos lados.
        self.scx=None;self.lap_config=lap_config;self.scx_marks={};self.gp_busy=None;self.track=None
        self.juego_store=None;self.falso_throttle=None   # ⚑/🍻 modos de juego (juego.py): server.wire los conecta
        self.flag_config=None   # server.wire: configuración de la bandera amarilla del piloto (la del Gran Premio)
        self.directory=Path(directory);self.path=self.directory/'session.json';self.base_url=base_url.rstrip('/')
        self.lock=threading.RLock();self.stop_event=threading.Event();self.wake=threading.Event();self.opener=build_opener(ProxyHandler({}))
        self.sensor={'connected':False,'data':None,'error':'Esperando respuesta del sensor','base_url':self.base_url}
        self.stats={'data_requests':0,'reset_requests':0,'inflight':0,'max_inflight':0,'last_request_ms':0,'last_data_at':None,'reset_reasons':[],'consecutive_failures':0,'failed_data_requests':0}
        self.dirty=False;self.avisos=[];self.boot=None;self.avisos_servidor=[]
        # Explosión al sensor: contador de cruces del sensor IR (salida + cada vuelta), solo para el sonido.
        self.cruces={'n':0,'at':None};self.cruce_prev=None;self.explosion_seen=None
        # Explosión por el cable USB de la ESP32 (esp32usb.py, solo lectura): al instante aunque se caiga su WiFi.
        # usb_pending = cruces que ya tronaron por USB y que /datos (WiFi) todavía no ha reportado: así 1 paso = 1 explosión.
        self.usb=None;self.usb_pending=collections.deque(maxlen=50);self.cruces_fuente={'usb':0,'wifi':0}
        self.session,aviso=durable.leer_json(self.path,validate=check_session,nombre='session.json (Práctica/Carrera)')
        if aviso:self.avisos.append(aviso)
        if self.session and self.session['phase']!='ended':
            try:
                self.recover()
            except Exception:
                moved=durable.apartar(self.path);self.session=None
                self.avisos.append('La sesión guardada no se pudo recuperar; se empezó limpio.'+(' Quedó guardada como '+moved.name+'.' if moved else ''))
        self.worker=threading.Thread(target=self.loop,name='esp32-poller',daemon=True);self.worker.start()
    def recover(self):
        """Sesión que estaba abierta cuando murió el servidor (Mac cerrada, apagón, kill -9). Las vueltas guardadas no se tocan."""
        s=self.session
        if isinstance(s.get('red_flag'),dict) and s['phase'] in ['running','countdown']:
            # Reinicio durante el PARO (o durante el semáforo de reanudación): sigue en PARO; Reanudar vuelve a prender el semáforo.
            s['red_flag']['stage']='stop'
            s.update(phase='running',starts_at=0,control=s['control']+1,version=s['version']+1,notice=RED_RESTART_NOTICE)
            s.pop('pending_active',None);s.pop('reset_sent',None);s.pop('flush_previous',None)
        elif s['phase'] in ['ready','countdown'] and not s.get('simulated'):
            # Semáforo a medias (o sesión vieja con salida automática): volver a "listos" para apretar Empezar.
            s.update(phase='ready',starts_at=0,control=s['control']+1,version=s['version']+1,notice=RESTART_READY_NOTICE if s['phase']=='countdown' else READY_NOTICE)
            s.pop('reset_sent',None);s.pop('flush_previous',None)
        elif s.get('lap_source')=='scx' and not s.get('simulated') and s['phase'] in ['resetting','waiting_sensor','running']:
            # Tarjeta SCX: no hay turnos ni reinicio de ESP32. La siguiente pasada de cada coche es salida.
            s.update(phase='running',active=None,control=s['control']+1,version=s['version']+1,notice='Sesión recuperada tras reiniciar el servidor; las vueltas ya contadas se conservaron. La siguiente pasada de cada coche por la meta cuenta como salida.')
            s.pop('pending_active',None);s.pop('reset_sent',None)
        elif s['phase']=='running' and s.get('active') is not None and any(p['slot']==s['active'] for p in s['pilots']):
            # Recuperar el cursor persistido sin reiniciar la ESP32 ni perder el turno.
            s.update(notice='Turno recuperado. Continúa con el mismo piloto.',version=s['version']+1)
        elif s['phase'] in ['resetting','waiting_sensor']:
            s.update(phase='waiting_sensor',notice='Comprobando conexión del sensor para recuperar la salida.',version=s['version']+1)
        else:
            s.update(phase='paused',active=None,control=s['control']+1,notice='Sesión recuperada en pausa. Elige quién está en pista para preparar una salida nueva.')
            s.pop('pending_active',None)
        s['version']+=RECOVERY_JUMP;s['control']+=RECOVERY_JUMP;s['recovered_at']=time.time()
        self.save()
    def save(self):
        # Solo marcar; el trabajador escribe fuera del bloqueo de lecturas HTTP.
        self.dirty=True
    def flush(self):
        with self.lock:
            if not self.dirty:return
            document=copy.deepcopy(self.session);self.dirty=False
        try:
            if document is None:return
            durable.escribir_json(self.path,document,backup=True,allow_nan=False)
        except Exception:
            with self.lock:self.dirty=True
            raise
    def fetch(self,path):
        if threading.current_thread() is not self.worker:raise RuntimeError('ESP32 access must run only in esp32-poller')
        start=time.monotonic()
        with self.lock:
            self.stats['reset_requests' if path=='/reiniciar' else 'data_requests']+=1
            self.stats['inflight']+=1;self.stats['max_inflight']=max(self.stats['max_inflight'],self.stats['inflight'])
        try:
            req=Request(self.base_url+path,headers={'Connection':'close','Cache-Control':'no-store'})
            with self.opener.open(req,timeout=self.REQUEST_TIMEOUT_S) as r:return r.read(16384)
        finally:
            with self.lock:self.stats['inflight']-=1;self.stats['last_request_ms']=round((time.monotonic()-start)*1000,2)
    def read_sensor(self):
        try:
            d=json.loads(self.fetch('/datos'))
            needed=['estado','vueltas','ultimo_s','mejor_s','promedio_s','kmh','kmh_escala','laps']
            if not isinstance(d,dict) or not all(k in d for k in needed):raise ValueError('JSON incompleto')
            if type(d['vueltas'])!=int or d['vueltas']<0 or not isinstance(d['laps'],list):raise ValueError('JSON inválido')
            seen=set()
            for lap in d['laps']:
                if not isinstance(lap,dict) or type(lap.get('n'))!=int or lap['n']<=0 or lap['n'] in seen:raise ValueError('Vuelta inválida')
                seen.add(lap['n'])
                if not all(isinstance(lap.get(k),(int,float)) and math.isfinite(lap[k]) and lap[k]>=0 for k in ['s','kmh','escala']) or lap['s']<=0:raise ValueError('Tiempo inválido')
            with self.lock:
                self.count_crossings(d)
                self.sensor={'connected':True,'data':d,'error':None,'base_url':self.base_url};self.stats['last_data_at']=time.monotonic();self.stats['last_data_wall']=time.time();self.stats['consecutive_failures']=0
            return d
        except Exception:
            with self.lock:
                self.stats['consecutive_failures']+=1;self.stats['failed_data_requests']+=1
            return None
    CRUCE_STALE_S=5.0
    @staticmethod
    def crossing_total(d):
        # El primer paso por la meta es la salida (estado deja «esperando salida», vueltas sigue en 0); cada vuelta es otro paso.
        return d['vueltas']+(0 if d.get('estado')=='esperando salida' else 1)
    USB_PENDING_S=120.0
    def count_crossings(self,d):
        """Solo para el sonido de explosión. No toca la sesión, el PARO ni las vueltas. Llamar con self.lock."""
        total=self.crossing_total(d);prev=self.cruce_prev;last=self.stats['last_data_at']
        self.cruce_prev=total
        # Primera lectura, o volvió la conexión tras un rato: solo tomar referencia (no tronar por cruces viejos).
        if prev is None or last is None:self.usb_pending.clear();return
        # Si la ESP32 se reinició (vueltas para atrás), lo que lleve desde el reinicio son cruces nuevos.
        new=total-prev if total>=prev else total
        # Tras un corte de WiFi de la ESP32 sí cuentan los cruces que hizo mientras tanto (hasta 5); más que eso = referencia nueva.
        if time.monotonic()-last>self.CRUCE_STALE_S and new>5:self.usb_pending.clear();return
        # Los que ya tronaron por el cable USB no vuelven a tronar.
        now=time.monotonic()
        while self.usb_pending and now-self.usb_pending[0]>self.USB_PENDING_S:self.usb_pending.popleft()
        while new>0 and self.usb_pending:self.usb_pending.popleft();new-=1
        # Con el cable USB activo, la explosión sale SOLO del cable (el WiFi llegaría tarde); sin cable, del WiFi como antes.
        if new>0 and not self.usb_active():self.cruces['n']+=new;self.cruces['at']=time.time();self.cruces_fuente['wifi']+=new
    def on_usb_cross(self,kind=None):
        """Llamado por esp32usb al leer «salida» o «vuelta N» del cable: truena al instante."""
        with self.lock:
            self.usb_pending.append(time.monotonic())
            self.cruces['n']+=1;self.cruces['at']=time.time();self.cruces_fuente['usb']+=1
    def usb_active(self):
        usb=getattr(self,'usb',None)
        if usb is None:return False
        try:return bool(usb.active())
        except Exception:return False
    def crossings(self,listener=False):
        """/api/cruces: lo mínimo para la explosión en la pantalla grande (Práctica/Carrera y Gran Premio)."""
        usb=self.usb_active()
        with self.lock:
            if listener:self.explosion_seen=time.monotonic()
            last=self.stats['last_data_at']
            wifi=last is not None and time.monotonic()-last<60.0
            return {'n':self.cruces['n'],'at':self.cruces['at'],'boot':getattr(self,'boot',None),'connected':usb or wifi,'fuente':'usb' if usb else 'wifi' if wifi else None,'now':time.time()}
    def explosion_listening(self):
        seen=self.explosion_seen
        return seen is not None and time.monotonic()-seen<5.0
    def sensor_snapshot(self):
        with self.lock:
            sensor=copy.deepcopy(self.sensor);last=self.stats['last_data_at']
            age=None if last is None else time.monotonic()-last
            wall=self.stats.get('last_data_wall')
            # Después de dormir la Mac el reloj monotónico no avanzó: usar también el reloj de pared.
            if age is not None and wall is not None and 0<=time.time()-wall<86400:age=max(age,time.time()-wall)
            connected=last is not None and age<60.0
            retrying=self.stats['consecutive_failures']>0
            status='updating' if connected and retrying else 'connected' if connected else 'disconnected'
            sensor.update(connected=connected,status=status,error=None if connected else 'sensor no conectado',retrying=retrying,age_ms=None if age is None else round(age*1000))
            return sensor
    def snapshot(self,include_sensor_data=True):
        with self.lock:
            s=copy.deepcopy(self.session)
            if s:
                s['countdown_ms']=max(0,int((s.get('starts_at',0)-time.time())*1000)) if s['phase']=='countdown' else 0
                s['elapsed_ms']=self.elapsed_ms(s)
                s['red']=bool(s.get('red_flag'))
                s['min_lap_s']=self.min_lap_s()
                s['bandera_cfg']=self.flag_cfg_de(self.session)
                if s.get('juego'):s['juego']=juego_mod.vista(self,self.session)
                for p in s['pilots']:
                    p['pits']=self.pits_view(p)
                # Handicap (ajuste de tiempo por vuelta): clase y segundos de cada piloto según su coche.
                h=self.session_handicap(s);cars=[]
                for p in s['pilots']:
                    car=self.hkey(h,p['slot']);cars.append(car)
                    p.update(handicap_mod.info(h,car,p.get('nivel')))   # clase del coche + nivel del piloto
                s['handicap']={'on':handicap_mod.activo(h,cars,[p.get('nivel') for p in s['pilots']]),'enabled':bool(h and h.get('enabled')),'resumen':handicap_mod.resumen(h),
                               'seg':(h or handicap_mod.OFF)['seg'],'nivel_on':bool(h and h.get('nivel_on')),'seg_nivel':(h or handicap_mod.OFF).get('seg_nivel') or {},'fijo':s['phase']!='ready'}
                if not include_sensor_data:
                    # URLs de avatares, nunca PNG/base64; omitir metadatos internos por vuelta.
                    for p in s['pilots']:
                        p['laps']=[{k:l[k] for k in ['n','s','kmh','escala']} for l in p['laps']]
            sensor=self.sensor_snapshot()
            if not include_sensor_data and sensor['data'] is not None:sensor['data']={'estado':sensor['data']['estado']}
            out={'session':s,'sensor':sensor,'boot':getattr(self,'boot',None),'avisos':list(getattr(self,'avisos_servidor',None) or getattr(self,'avisos',[]))}
        scx=getattr(self,'scx',None);config=getattr(self,'lap_config',None)
        if scx is not None:out['scx']=scx.brief()
        if config is not None:out['laps_config']=config.read()
        # Tablero de agujas: mismos valores que el Gran Premio (velocímetro, zona roja, pista y escala).
        dash=getattr(self,'dashboard',None)
        if dash is not None:
            try:out['dashboard']=dash()
            except Exception:pass
        return out
    @staticmethod
    def elapsed_ms(s):
        """Tiempo de carrera sin contar los paros (bandera roja). None antes del primer verde."""
        start=s.get('clock_started')
        if not start or (s['phase']=='ended' and not s.get('ended_at')):return None
        rf=s.get('red_flag')
        end=rf['at'] if rf else s.get('ended_at') if s['phase']=='ended' and s.get('ended_at') else time.time()
        return max(0,int((end-start-s.get('paused_s',0))*1000))
    def start_clock(self,s):
        if not s.get('clock_started'):s['clock_started']=time.time();s.setdefault('paused_s',0.0)
    def gatillo_pause(self,on):
        g=getattr(getattr(self,'scx',None),'gatillo',None)
        if g is not None:
            try:g.pause(on)
            except Exception as e:print('Error gatillo: '+type(e).__name__,flush=True)
    def red_stop(self,s,yellow=None):
        """PARO: congelar. Se guarda cuánto llevaba cada coche de su vuelta en curso (sobrevive a un reinicio).
        yellow={'by','by_name','car','used','max'} si lo pidió un piloto (bandera amarilla)."""
        self.gatillo_pause(True)   # velocímetro en vivo: las vueltas que cruzan el paro no calibran
        now_ms=time.monotonic()*1000.0;elapsed={}
        for key in [k for k in self.scx_marks if k[0]==s['id']]:
            elapsed[str(key[1])]=round(max(0.0,(now_ms-self.scx_marks.pop(key))/1000.0),3)
        n=len(s.get('pausas') or [])+1
        s['red_flag']={'n':n,'at':time.time(),'stage':'stop','lap_elapsed':elapsed,'ignored':0,'kind':'yellow' if yellow else 'red'}
        if yellow:s['red_flag'].update(yellow)
        s.update(control=s['control']+1,version=s['version']+1,notice=YELLOW_NOTICE%(yellow['by_name'],yellow['used'],yellow['max']) if yellow else RED_NOTICE)
    def red_close(self,s,resumed):
        rf=s.pop('red_flag',None)
        if not rf:return None
        self.gatillo_pause(False)
        now=time.time();dur=max(0.0,now-rf['at'])
        s.setdefault('pausas',[]).append({'n':rf['n'],'at':rf['at'],'resumed_at':now if resumed else None,'duration_s':round(dur,3),'ignored_laps':rf.get('ignored',0),'kind':rf.get('kind','red'),'by_name':rf.get('by_name')})
        s['paused_s']=s.get('paused_s',0.0)+dur
        return rf
    def red_resume_go(self,s):
        """Verde del semáforo de reanudación: el reloj sigue donde se quedó y cada vuelta en curso sin el tiempo del paro."""
        rf=self.red_close(s,True);now=time.time();now_ms=time.monotonic()*1000.0
        for car,el in (rf.get('lap_elapsed') or {}).items():
            try:self.scx_marks[(s['id'],int(car))]=now_ms-float(el)*1000.0
            except (TypeError,ValueError):pass
        if s.get('lap_source')!='scx' and s.get('active') is not None:
            # Sensor IR: su vuelta en curso incluye el paro; se descuenta en la primera vuelta tras el verde.
            s['ir_credit']=round(max(0.0,now-max(rf['at'],rf.get('ir_cross_at') or 0)),3)
        s.update(phase='running',starts_at=0,control=s['control']+1,version=s['version']+1,notice='🟢 ¡Verde! Carrera reanudada. El tiempo del paro no cuenta.')
    def diagnostics(self):
        with self.lock:
            d=copy.deepcopy(self.stats);last=d.pop('last_data_at');d.pop('last_data_wall',None)
            d['sensor_age_ms']=None if last is None else round((time.monotonic()-last)*1000)
            d['poll_interval_ms']=round(self.poll_interval()*1000)
            d['worker_count']=1;d['connection_grace_ms']=60000;d['request_timeout_ms']=round(self.REQUEST_TIMEOUT_S*1000)
            d['explosion']={'n':self.cruces['n'],'por_usb':self.cruces_fuente['usb'],'por_wifi':self.cruces_fuente['wifi'],'usb_pendientes':len(self.usb_pending)}
        usb=getattr(self,'usb',None)
        d['esp32_usb']=usb.estado() if usb is not None else {'habilitado':False,'activo':False}
        d['explosion']['fuente']='usb' if d['esp32_usb'].get('activo') else 'wifi'
        return d
    def consume(self,d,flush_previous=False):
        s=self.session
        if s and s.get('red_flag') and not flush_previous:
            if s['active'] is not None and d['vueltas']>s['cursor']:
                # Vueltas del sensor durante el PARO: se saltan (no cuentan ni se cronometran).
                rf=s['red_flag'];rf['ignored']=rf.get('ignored',0)+d['vueltas']-s['cursor'];rf['ir_cross_at']=time.time()
                s.pop('ir_carry',None)   # la vuelta del sensor vuelve a empezar en ese cruce
                s['cursor']=d['vueltas'];s['version']+=1;self.save()
            return
        if not s or (s['phase']!='running' and not flush_previous) or s['active'] is None:return
        if d['vueltas']<s['cursor']:
            if not flush_previous:s.update(phase='paused',notice='El sensor se reinició fuera de esta app. Inicia un turno nuevo.',control=s['control']+1);self.save()
            return
        pilot=next(p for p in s['pilots'] if p['slot']==s['active'])
        prior=next((l for l in reversed(pilot['laps']) if l.get('turn')==s['turn'] and l.get('source_n')==s['cursor']),None)
        reported=next((l for l in d['laps'] if l['n']==s['cursor']),None)
        # source_s = tiempo crudo de la ESP32 (el guardado puede llevar descontado el paro o sumado un cruce sospechoso).
        if prior and reported and prior.get('source_s',prior['s'])!=reported['s']:
            if not flush_previous:s.update(phase='paused',notice='El sensor tiene otra salida. Inicia un turno nuevo para no mezclar tiempos.',control=s['control']+1);self.save()
            return
        if d['vueltas']<=s['cursor']:return
        if s.get('lap_source')=='both' and self.scx_connected():
            # Ambos: la tarjeta SCX manda mientras esté conectada; el IR solo avanza su cursor (sin duplicar vueltas).
            s['cursor']=min(d['vueltas'],40);s['version']+=1;self.save();return
        # Copiar TODAS las vueltas nuevas, incluso saltos 3→5, sin duplicados.
        rows=sorted([l for l in d['laps'] if s['cursor']<l['n']<=min(d['vueltas'],40)],key=lambda l:l['n'])
        minimum=self.min_lap_s();cal=None
        for lap in rows:
            if pilot.get('dsq'):
                # Descalificado: el cursor avanza pero sus vueltas ya no cuentan.
                pilot['dsq']['ignored']=pilot['dsq'].get('ignored',0)+1;s.pop('ir_credit',None);s.pop('ir_carry',None);continue
            raw_s=lap['s'];credit=s.pop('ir_credit',None)
            if credit:
                # Primera vuelta tras Reanudar: sin el tiempo del paro.
                secs=round(lap['s']-credit,3)
                if secs<IR_MIN_LAP_S:s['notice']='La primera pasada tras la bandera roja no se pudo cronometrar; no cuenta.';s.pop('ir_carry',None);continue
                f=lap['s']/secs;lap=dict(lap,s=secs,kmh=lap['kmh']*f,escala=lap['escala']*f)
            # La ESP32 empieza vuelta nueva en cada cruce; si el anterior fue sospechoso, su tiempo se suma
            # (ir_carry) para medir desde la última pasada válida.
            total=round(lap['s']+s.get('ir_carry',0.0),3)
            if total<minimum:
                self.record_suspicious(s,pilot,total,'ir',None,minimum);s['ir_carry']=total;continue
            if s.pop('ir_carry',None):
                f=lap['s']/total;lap=dict(lap,s=total,kmh=lap['kmh']*f,escala=lap['escala']*f)
            row={'n':len(pilot['laps'])+1,'s':lap['s'],'kmh':lap['kmh'],'escala':lap['escala'],'source_n':lap['n'],'turn':s['turn']}
            if raw_s!=lap['s']:row['source_s']=raw_s
            pilot['laps'].append(row);cal=row
        if not flush_previous and cal is not None:
            # Sensor IR: el mando del piloto en pista (vueltas.json) calibra su velocímetro con la última vuelta válida.
            config=getattr(self,'lap_config',None)
            car=config.car_for_slot(s['active']) if config is not None else s['active']+1
            self.calibrate_trigger(car,cal['s'],self.speed(cal['s'])[1])
        missing=max(0,min(d['vueltas'],40)-s['cursor']-len(rows))
        if missing:s['notice']='Hay vueltas que el sensor ya no conserva; no se inventaron tiempos.'
        s['cursor']=d['vueltas'];s['version']+=1
        if d['vueltas']>=40 and not flush_previous:s.update(phase='turn_limit',notice='Se completaron las 40 vueltas de este turno. Inicia otro turno para seguir guardando tiempos.',control=s['control']+1)
        self.save()
    def poll_interval(self):
        # Wait AFTER each request. Failed connections never use the racing cadence.
        failures=self.stats['consecutive_failures']
        if failures:return min(10.0, 2.0**min(failures-1,4))
        if self.session and self.session['phase'] in ['running','countdown'] and self.session.get('lap_source')!='scx':return .2
        # Pantalla grande con «Explosión al sensor» abierta: preguntar más seguido para que truene a tiempo (menos que en carrera IR).
        # Con el cable USB activo la explosión ya no depende del WiFi: no apurar a la ESP32.
        return .3 if self.explosion_listening() and not self.usb_active() else 1.0
    def lights_seconds(self):
        # Misma duración que el semáforo del Gran Premio (configuración "Segundos de semáforo"), 3 s si no hay.
        dash=getattr(self,'dashboard',None);secs=3
        if dash is not None:
            try:secs=dash().get('lights_seconds',3)
            except Exception:secs=3
        return secs if type(secs) in (int,float) and 1<=secs<=10 else 3
    def scx_connected(self):
        scx=getattr(self,'scx',None)
        return bool(scx is not None and scx.is_connected())
    def scx_present(self):
        scx=getattr(self,'scx',None)
        if scx is None:return False
        present=getattr(scx,'card_present',None)
        return bool(scx.is_connected() or (present is not None and present()))
    def resolve_source(self):
        config=getattr(self,'lap_config',None)
        source=config.read()['source'] if config is not None else 'ir'
        if source=='auto':
            # Las vueltas las cuenta la Pit Box: tarjeta SCX si está enchufada (aunque la Pit Box aún no mande datos).
            # Solo si la tarjeta NO está y el sensor IR sí responde, se usa el IR por turnos.
            if self.scx_present():source='scx'
            elif getattr(self,'scx',None) is not None and not self.sensor_snapshot()['connected']:source='scx'
            else:source='ir'
        return source
    def min_lap_s(self):
        config=getattr(self,'lap_config',None)
        try:return float(config.min_lap()) if config is not None else DEFAULT_MIN_LAP_S
        except Exception:return DEFAULT_MIN_LAP_S
    def record_suspicious(self,s,pilot,seconds,source,car,minimum):
        """Vuelta más corta que la mínima: no cuenta, se guarda para revisarla. Llamar con self.lock."""
        lst=pilot.setdefault('sospechosas',[])
        lst.append({'s':round(seconds,3),'car':car,'src':source,'hora':round(time.time(),3),'min':minimum,'tras_vuelta':len(pilot['laps'])})
        if len(lst)>MAX_SOSPECHOSAS:del lst[:-MAX_SOSPECHOSAS]
        pilot['sospechosas_n']=pilot.get('sospechosas_n',0)+1
        s['notice']='⚠ Vuelta sospechosa de %s%s: %.2f s, menos del mínimo de %g s. No cuenta; se sigue midiendo desde la última pasada válida.'%(pilot['name'],' (coche %s)'%car if car else '',seconds,minimum)
    def current_handicap(self):
        config=getattr(self,'lap_config',None)
        try:return config.handicap() if config is not None else None
        except Exception:return None
    def session_handicap(self,s):
        """Antes de Empezar se usa el handicap actual (se puede cambiar); al Empezar queda fijo en la sesión.
        Una sesión guardada antes de esta versión no tiene handicap."""
        if s.get('phase')=='ready':return self.current_handicap()
        return s.get('handicap')
    def hkey(self,h,slot):
        """Llave del ajuste: el coche del Garage que lleva el piloto ('p<slot>'), si no, su mando."""
        return handicap_mod.clave(h,slot,self.car_of_slot(slot))
    def car_of_slot(self,slot):
        config=getattr(self,'lap_config',None)
        try:c=config.car_for_slot(slot) if config is not None else None
        except Exception:c=None
        return c if isinstance(c,int) else slot+1
    def export_csv(self):
        """Práctica/Carrera actual (o la última terminada): vueltas válidas y vueltas sospechosas (columna «Cuenta»)."""
        with self.lock:s=copy.deepcopy(self.session);minimum=self.min_lap_s()
        if not s:raise LiveError('Todavía no hay una sesión de Práctica o Carrera.',404)
        hcfg=self.session_handicap(s);hs={p['slot']:handicap_mod.seg_de(hcfg,self.hkey(hcfg,p['slot']),p.get('nivel')) for p in s['pilots']}
        hcols={p['slot']:handicap_mod.csv_cols(handicap_mod.info(hcfg,self.hkey(hcfg,p['slot']),p.get('nivel'))) for p in s['pilots']}
        config=getattr(self,'lap_config',None)
        def car_of(slot):
            try:return config.car_for_slot(slot) if config is not None else ''
            except Exception:return ''
        hora=lambda t:time.strftime('%H:%M:%S',time.localtime(t)) if t else ''
        f3=lambda x:'' if x is None else '%.3f'%x
        src={'scx':'Pit Box (tarjeta SCX)','ir':'Sensor IR','scx-sim':'Simulada'}
        buf=io.StringIO();w=csv.writer(buf)
        w.writerow(['Puto el último · '+('Carrera' if s.get('type')=='race' else 'Práctica'),time.strftime('%Y-%m-%d %H:%M',time.localtime(s.get('created_at') or time.time()))])
        w.writerow(['Vuelta mínima (s)',minimum,'Fuente',src.get(s.get('lap_source'),s.get('lap_source') or ''),'Handicap (s por vuelta)',handicap_mod.resumen(hcfg)])
        w.writerow([])
        w.writerow(['Piloto','Coche','Vuelta #','Tiempo (s)','km/h escala','Cuenta','Hora','Fuente','Después de la vuelta']+handicap_mod.CSV_HEAD+['Tiempo con handicap (s)'])
        for p in s['pilots']:
            car=car_of(p['slot']);h=hs[p['slot']]
            for l in p['laps']:
                w.writerow([p['name'],car,l['n'],f3(l['s']),'' if l.get('escala') is None else round(l['escala'],1),'sí','','','']+hcols[p['slot']]+[f3(handicap_mod.mas(l['s'],h))])
            for x in p.get('sospechosas') or []:
                w.writerow([p['name'],x.get('car') or car,'',f3(x.get('s')),'','NO · sospechosa (menos de %g s)'%(x.get('min') or minimum),
                            hora(x.get('hora')),src.get(x.get('src'),x.get('src') or ''),x.get('tras_vuelta','')])
        total=sum(len(p.get('sospechosas') or []) for p in s['pilots'])
        # Resultado con la bandera amarilla del piloto: descalificados al final y sin posición.
        fl=self.flag_cfg();w.writerow([])
        w.writerow(['RESULTADO','Posición','Piloto','Coche','Vueltas','Mejor vuelta (s)','Banderas amarillas (máx. %d)'%fl['max'],'Estado','Hora DSQ','Vueltas al DSQ','Pasadas que ya no contaron','Paradas en pits','Última parada (s)','Tiempo en pits (s)','Vel. última (km/h)','Vel. mejor (km/h)','Llanta','Vueltas con las llantas actuales','Km con las llantas actuales',
                    ]+handicap_mod.CSV_HEAD+['Mejor vuelta con handicap (s)','Tiempo total real (s)','Tiempo total con handicap (s)'])
        tire_now=self.tire_name();km_now=self.km_lap()
        for pos,p in self.standings(s,hs):
            q=p.get('dsq') or {};best=min((l['s'] for l in p['laps']),default=None);last=p['laps'][-1]['s'] if p['laps'] else None
            pv=pits_mod.resumen(p.get('paradas'),laps_now=len(p['laps']),km_lap=km_now);ll=pv['llanta']
            w.writerow(['','DSQ' if q else (pos or ''),p['name'],car_of(p['slot']),len(p['laps']),f3(best),p.get('banderas',0),'DESCALIFICADO' if q else '',
                        hora(q.get('at')),q.get('laps','') if q else '',q.get('ignored','') if q else '',
                        pv['completadas'],'' if pv['ultima_s'] is None else '%.1f'%pv['ultima_s'],'' if not pv['completadas'] and not pv['en_pits'] else '%.1f'%pv['total_s'],
                        self.vel_txt(last),self.vel_txt(best),tire_now,ll['vueltas'],'' if ll['km'] is None else '%.1f'%ll['km'],
                        ]+hcols[p['slot']]+[f3(handicap_mod.mas(best,hs[p['slot']])),
                        f3(sum(l['s'] for l in p['laps'])) if p['laps'] else '',f3(handicap_mod.suma((l['s'] for l in p['laps']),hs[p['slot']])) if p['laps'] else ''])
        # Cada parada en pits = CAMBIO DE LLANTAS: vida de llanta al entrar/salir (%) y vueltas/km de ese juego.
        km_lap=self.km_lap()
        w.writerow([]);w.writerow(['CAMBIOS DE LLANTAS (PITS)','Piloto','Coche','Parada #','Vuelta al entrar','Entrada','Salida','Duración (s)','Vida de llanta al entrar (%)','Vida de llanta al salir (%)','Cómo salió','En curso','Llanta','Vueltas con ese juego','Km con ese juego'])
        src_p={'estimado':'estimada (deja de cargar la Pit Box + gatillo)','ir':'sensor IR de salida','timeout':'tope de tiempo','pista':'cruzó la meta por la pista','cierre':'se terminó la sesión','reinicio':'reinicio del servidor'}
        anyp=False;tire=self.tire_name()
        for p in s['pilots']:
            for i,x in enumerate(pits_mod.paradas_llantas(p.get('paradas'),km_lap),1):
                anyp=True
                w.writerow(['',p['name'],x.get('car') or car_of(p['slot']),i,x.get('lap',''),hora(x.get('entry_at')),hora(x.get('exit_at')),
                            '' if x.get('duration_s') is None else '%.1f'%x['duration_s'],
                            '' if x.get('vida_entrada_pct') is None else x['vida_entrada_pct'],
                            '' if x.get('vida_salida_pct') is None else x['vida_salida_pct'],
                            src_p.get(x.get('source_exit'),x.get('source_exit') or ''),
                            'sí' if x.get('abierta') else 'no',tire,
                            '' if x.get('vueltas_juego') is None else x['vueltas_juego'],
                            '' if x.get('km_juego') is None else '%.1f'%x['km_juego']])
        if not anyp:w.writerow(['','ninguna'])
        if s.get('pausas') or s.get('red_flag'):
            w.writerow([]);w.writerow(['PAROS','Paro #','Inicio','Duración (s)','Reanudado','Bandera','La pidió'])
            tipo=lambda x:'amarilla (piloto)' if x.get('kind')=='yellow' else 'roja'
            for x in s.get('pausas') or []:
                w.writerow(['',x.get('n'),hora(x.get('at')),'%.1f'%(x.get('duration_s') or 0),'sí' if x.get('resumed_at') else 'no',tipo(x),x.get('by_name') or ''])
            rf=s.get('red_flag')
            if rf:w.writerow(['',rf.get('n'),hora(rf.get('at')),'%.1f'%(time.time()-rf['at']),'en curso',tipo(rf),rf.get('by_name') or ''])
        w.writerow([]);w.writerow(['Vueltas sospechosas (no cuentan)',total])   # última fila (como antes)
        return buf.getvalue()
    @staticmethod
    def standings(s,hs=None):
        """[(posición o None, piloto)] por mejor vuelta (con handicap si hs={lugar: segundos}); los descalificados al final y sin posición."""
        hs=hs or {}
        if s.get('juego'):return juego_mod.posiciones(s,hs)   # ⚑/🍻: el orden del juego (vueltas netas y tiempo)
        best=lambda p:handicap_mod.mas(min((l['s'] for l in p['laps']),default=None),hs.get(p['slot'],0.0))
        ps=sorted(s['pilots'],key=lambda p:(bool(p.get('dsq')),best(p) is None,best(p) or 0,p['slot']))
        return [(i+1 if not p.get('dsq') and best(p) is not None else None,p) for i,p in enumerate(ps)]
    # ---------- bandera amarilla del piloto ----------
    def flag_cfg(self):
        fn=getattr(self,'flag_config',None);cfg=dict(FLAG_FALLBACK)
        if fn is not None:
            try:cfg.update(fn() or {})
            except Exception:pass
        return cfg
    def flag_cfg_de(self,s):
        cfg=self.flag_cfg()
        j=(s or {}).get('juego') if isinstance(s,dict) else None
        if j:
            n=int(j['cfg'].get('banderas',2));cfg=dict(cfg,max=n,enabled=bool(cfg.get('enabled')) and n>0)
        return cfg
    def on_pilot_flag(self,car,t=None):
        """Triple clic del mando car (1..6) en Práctica/Carrera. Devuelve 'yellow', 'dsq' o None (ignorado)."""
        busy=getattr(self,'gp_busy',None)
        if busy is not None and busy():return None   # mientras corre el Gran Premio, la bandera es del GP
        cfg=self.flag_cfg()
        with self.lock:
            s=self.session
            cfg=self.flag_cfg_de(s)
            # Solo con la sesión en verde. Antes del semáforo, sin sesión, durante un PARO (o su semáforo) o en una prueba simulada: nada.
            if not cfg['enabled'] or not s or s['phase']!='running' or s.get('red_flag') or s.get('simulated'):return None
            config=getattr(self,'lap_config',None)
            slot=config.slot_for_car(car) if config is not None else car-1
            pilot=next((p for p in s['pilots'] if p['slot']==slot),None)
            if pilot is None or pilot.get('dsq'):return None
            # Sensor IR por turnos: solo el piloto que está en pista.
            if s.get('lap_source')=='ir' and s.get('active')!=slot:return None
            used=pilot.get('banderas',0);ev=s.get('bandera_evento') or {}
            if used<cfg['max']:
                pilot['banderas']=used+1
                self.red_stop(s,{'by':slot,'by_name':pilot['name'],'car':car,'used':used+1,'max':cfg['max']})
                s['bandera_evento']={'n':ev.get('n',0)+1,'tipo':'amarilla','slot':slot,'name':pilot['name'],'at':time.time()}
                self.save();self.wake.set();return 'yellow'
            if not cfg['dsq']:
                s.update(version=s['version']+1,notice='🟨 %s ya usó sus %d banderas amarillas; no se sacó otra.'%(pilot['name'],cfg['max']));self.save();return None
            pilot['dsq']={'at':time.time(),'laps':len(pilot['laps']),'ignored':0,'banderas':used,'elapsed_ms':self.elapsed_ms(s)}
            for key in [k for k in self.scx_marks if k[0]==s['id'] and k[1]==car]:self.scx_marks.pop(key,None)
            s['bandera_evento']={'n':ev.get('n',0)+1,'tipo':'dsq','slot':slot,'name':pilot['name'],'at':time.time()}
            s.update(version=s['version']+1,notice=DSQ_NOTICE%(pilot['name'],cfg['max']));self.save()
        self.wake.set();return 'dsq'
    def calibrate_trigger(self,car,seconds,escala,end=None):
        """Velocímetro en vivo: cada vuelta VÁLIDA ajusta el factor del gatillo de ese mando (gatillo.py). Nunca falla la vuelta."""
        g=getattr(getattr(self,'scx',None),'gatillo',None)
        if g is None or type(car)!=int or not 1<=car<=6:return False
        try:return g.on_lap(car-1,seconds,escala,end)
        except Exception as e:print('Error gatillo: '+type(e).__name__,flush=True);return False
    def track_params(self):
        length,scale=25.0,32
        track=getattr(self,'track',None)
        if track is not None:
            try:length,scale=track()
            except Exception:pass
        return length,scale
    def vel_txt(self,seconds):
        length,scale=self.track_params()
        if not seconds or seconds<=0:return ''
        try:s=float(seconds)
        except (TypeError,ValueError):return ''
        if s<=0:return ''
        return str(int(round(length/s*3.6*scale)))
    def speed(self,seconds):
        length,scale=self.track_params()
        kmh=(length/seconds)*3.6
        return kmh,kmh*scale
    def pits_view(self,pilot):
        """Resumen de pits para la tarjeta de un piloto (EN PITS, cronómetro, paradas, total)."""
        car=None
        config=getattr(self,'lap_config',None)
        if config is not None:
            try:car=config.car_for_slot(pilot['slot'])
            except Exception:car=None
        if car is None:car=pilot.get('car')
        live=None
        scx=getattr(self,'scx',None)
        if scx is not None and type(car)==int:
            try:live=scx.pits.car_view(car-1)
            except Exception:live=None
        r=pits_mod.resumen(pilot.get('paradas'),live,laps_now=len(pilot.get('laps') or []),km_lap=self.km_lap())
        r.pop('stops',None)
        return r
    def km_lap(self):
        """Km a escala por vuelta con el largo y la escala de la configuración (25 m × 32 = 0.8 km)."""
        length,scale=self.track_params()
        return pits_mod.km_por_vuelta(length,scale)
    def tire_name(self):
        """Nombre de la llanta (Gran Premio → Configuración); «Media» de fábrica."""
        dash=getattr(self,'dashboard',None)
        try:name=(dash() or {}).get('tire_name') if dash is not None else None
        except Exception:name=None
        return name if isinstance(name,str) and name.strip() else pits_mod.TIRE_DEFAULTS['tire_name']
    def close_open_pits(self,s,reason='cierre'):
        """Cierra paradas abiertas al terminar la sesión (o al recuperarla)."""
        now=time.time();config=getattr(self,'lap_config',None)
        for p in s.get('pilots') or []:
            for rec in p.get('paradas') or []:
                if rec.get('abierta'):
                    rec['exit_at']=now
                    rec['duration_s']=round(max(0.0,now-(rec.get('entry_at') or now)),3)
                    rec['source_exit']=reason
                    rec['abierta']=False
            car=None
            if config is not None:
                try:car=config.car_for_slot(p['slot'])
                except Exception:car=None
            scx=getattr(self,'scx',None)
            if scx is not None and type(car)==int:
                try:scx.pits.reset(car-1,reason=reason)
                except Exception as e:print('Error al cerrar pits: '+type(e).__name__,flush=True)
    def rehydrate_pits(self):
        """Tras arrancar: si una sesión en curso tenía una parada abierta, el tracker la retoma."""
        with self.lock:
            s=self.session
            if not s:return
            if s['phase'] in ('ended','ready'):
                self.close_open_pits(s,'reinicio');return
            scx=getattr(self,'scx',None);config=getattr(self,'lap_config',None)
            if scx is None:return
            for p in s.get('pilots') or []:
                rec=next((x for x in (p.get('paradas') or []) if x.get('abierta')),None)
                if not rec:continue
                car=None
                if config is not None:
                    try:car=config.car_for_slot(p['slot'])
                    except Exception:car=None
                if type(car)==int:
                    try:scx.pits.rehydrate(car-1,rec)
                    except Exception as e:print('Error al retomar pits: '+type(e).__name__,flush=True)
    def on_pit(self,ev):
        """Entrada o salida de pits en Práctica/Carrera (la tarjeta SCX solo se escucha)."""
        busy=getattr(self,'gp_busy',None)
        if busy is not None and busy():return None
        with self.lock:
            s=self.session
            if not ev or not s or s.get('simulated'):return None
            config=getattr(self,'lap_config',None)
            slot=config.slot_for_car(ev['car']) if config is not None else ev['car']-1
            pilot=next((p for p in s['pilots'] if p['slot']==slot),None)
            if pilot is None:return None
            pilot.setdefault('paradas',[])
            if ev.get('kind')=='entry':
                if s['phase'] in ('ready','countdown','ended'):return None
                if any(x.get('abierta') for x in pilot['paradas']):return None
                rec=pits_mod.stop_record(ev['car'],ev,abierta=True)
                rec['lap']=ev.get('lap') if ev.get('lap') is not None else len(pilot['laps'])
                rec['vueltas_al_entrar']=len(pilot['laps'])   # para las vueltas/km de cada juego de llantas
                pilot['paradas'].append(rec)
                s.update(version=s['version']+1,notice=pilot['name']+' (coche '+str(ev['car'])+') entró a pits · cambio de llantas.')
                self.save();self.wake.set();return 'entry'
            if ev.get('kind')=='exit':
                rec=next((x for x in reversed(pilot['paradas']) if x.get('abierta')),None)
                if rec is None:
                    if s['phase']=='ended':return None
                    rec=pits_mod.stop_record(ev['car'],ev,abierta=False);pilot['paradas'].append(rec)
                else:
                    rec.update(exit_at=ev.get('exit_at'),duration_s=ev.get('duration_s'),
                               fuel_after=ev.get('fuel_after'),vida_salida_pct=pits_mod.vida_pct(ev.get('fuel_after')),source_exit=ev.get('source_exit'),abierta=False)
                dur=rec.get('duration_s')
                if s['phase']!='ended':
                    s.update(version=s['version']+1,notice=pilot['name']+' salió de pits con llantas nuevas'+(' · %.1f s'%dur if dur is not None else '')+'.')
                self.save();self.wake.set();return 'exit'
            return None
    def on_scx_finish(self,ev):
        """Un cruce de meta ya filtrado (1 por coche cada >=1.5 s). Tiempo = diferencia del reloj monotónico del servidor."""
        # Fuera del candado de la sesión (el GP toma su propio candado): mientras corre una parte del
        # Gran Premio, los cruces son del GP y no se cuentan en Práctica/Carrera.
        busy=getattr(self,'gp_busy',None)
        if busy is not None and busy():
            with self.lock:self.scx_marks.clear()   # al terminar el GP, la siguiente pasada vuelve a ser salida
            return
        with self.lock:
            s=self.session
            if s and s.get('red_flag') and s.get('lap_source') in ['scx','both']:
                # PARO: no cuenta ni cronometra. Si el coche ya había salido, su vuelta vuelve a empezar en la meta.
                rf=s['red_flag'];lap=rf.setdefault('lap_elapsed',{})
                if str(ev['car']) in lap and lap[str(ev['car'])]!=0:lap[str(ev['car'])]=0;rf['ignored']=rf.get('ignored',0)+1;self.save()
                return
            if s and s.get('juego') and s['phase']=='countdown' and not s.get('red_flag') and s.get('lap_source') in ['scx','both']:
                # ⚑/🍻: cruzar la meta durante el semáforo = salida en falso (castigo en la tabla).
                config=getattr(self,'lap_config',None);sl=config.slot_for_car(ev['car']) if config is not None else ev['car']-1
                if juego_mod.falso(self,s,sl,'cruzó la meta antes del verde'):self.save()
                return
            if not s or s.get('lap_source') not in ['scx','both'] or s['phase'] in ['ready','countdown','ended'] or s.get('simulated'):return
            config=getattr(self,'lap_config',None)
            slot=config.slot_for_car(ev['car']) if config is not None else ev['car']-1
            pilot=next((p for p in s['pilots'] if p['slot']==slot),None)
            if pilot is None:return
            if pilot.get('dsq'):
                # Descalificado: sus pasadas ya no cuentan (ni vuelta, ni mejor, ni velocímetro).
                pilot['dsq']['ignored']=pilot['dsq'].get('ignored',0)+1;s['version']+=1;self.save();return
            key=(s['id'],ev['car']);prev=self.scx_marks.get(key);minimum=self.min_lap_s()
            if prev is not None and (ev['t_ms']-prev)/1000.0<min(BOUNCE_S,minimum):return   # rebote del mismo cruce: no mover la marca
            if prev is not None and (ev['t_ms']-prev)/1000.0<minimum:
                # Vuelta sospechosa: no cuenta y NO mueve la marca (la vuelta sigue desde la última pasada válida).
                self.record_suspicious(s,pilot,(ev['t_ms']-prev)/1000.0,'scx-sim' if ev.get('simulado') else 'scx',ev['car'],minimum)
                s['version']+=1;self.save();return
            self.scx_marks[key]=ev['t_ms']
            if prev is None:
                s.update(version=s['version']+1,notice=pilot['name']+' (coche '+str(ev['car'])+'): salida registrada. La siguiente pasada cuenta vuelta.')
            else:
                seconds=round((ev['t_ms']-prev)/1000.0,3)
                if len(pilot['laps'])>=self.SCX_MAX_LAPS:
                    s.update(version=s['version']+1,notice='Máximo '+str(self.SCX_MAX_LAPS)+' vueltas por piloto en esta sesión.');self.save();return
                kmh,escala=self.speed(seconds)
                if s.get('juego') and not juego_mod.antes_vuelta(self,s,pilot):
                    self.save();return   # 🍻 ya terminó su última vuelta de la ronda: esta pasada no cuenta
                pilot['laps'].append(dict(n=len(pilot['laps'])+1,s=seconds,kmh=kmh,escala=escala,source_n=None,turn='scx',car=ev['car'],src='scx-sim' if ev.get('simulado') else 'scx'))
                s.update(version=s['version']+1,notice='')
                self.calibrate_trigger(ev['car'],seconds,escala,ev['t_ms']/1000.0)
                if s.get('juego'):juego_mod.despues_vuelta(self,s,pilot)
            self.save()
        self.wake.set()
    def complete_reset(self,token):
        with self.lock:
            s=self.session
            if not s or (s['id'],s['control'])!=token:return
            target=s.pop('pending_active',s['active'])
            s.pop('reset_sent',None);s.pop('flush_previous',None)
            s.update(phase='running',active=target,cursor=0,turn=uuid.uuid4().hex,control=s['control']+1,version=s['version']+1,notice='' if target is not None else 'Elige quién está en pista. Un solo auto por turno.')
            s.pop('ir_credit',None);s.pop('ir_carry',None);self.start_clock(s)
            self.save()
    def reset_turn(self,token,d):
        # A fresh /datos must succeed before issuing ONE reset for this command.
        with self.lock:
            s=self.session
            if not s or (s['id'],s['control'])!=token:return
            if s.get('reset_sent'):
                # A timed-out response is ambiguous: never blindly repeat a reset.
                if d['vueltas']==0 and d['estado']=='esperando salida':
                    self.complete_reset(token)
                else:
                    s.update(phase='paused',control=s['control']+1,version=s['version']+1,notice='El sensor respondió, pero no se confirmó la salida. Inicia un turno nuevo para no mezclar tiempos.')
                    s.pop('reset_sent',None);s.pop('pending_active',None);self.save()
                return
            if s.pop('flush_previous',False):self.consume(d,True)
            s['reset_sent']=True
            reason=s.get('reset_reason','start')
            self.stats['reset_reasons']=(self.stats['reset_reasons']+[reason])[-12:]
            self.save()
        # Persist the attempt before network I/O, even across a server restart.
        self.flush()
        try:
            if self.fetch('/reiniciar').strip()!=b'ok':raise ValueError('Reset no confirmado')
        except Exception:
            with self.lock:
                self.stats['consecutive_failures']+=1
                if self.session and (self.session['id'],self.session['control'])==token:
                    self.session.update(phase='waiting_sensor',notice='Comprobando conexión y confirmación de salida…');self.save()
            return
        self.complete_reset(token)
    def command(self,payload,roster):
        with self.lock:
            action=payload.get('action')
            if action=='start':
                if self.session and self.session['phase']!='ended':raise LiveError('Ya hay una sesión en curso. Ábrela o termínala antes de crear otra.',409)
                typ=payload.get('type');mode=payload.get('mode');ids=payload.get('slots')
                if typ not in ['race','practice'] or mode not in ['ultimo','chelas','carrera']:raise LiveError('Elige Carrera o Práctica y un modo válido.')
                es_juego=bool(payload.get('juego'))
                if es_juego and (typ!='race' or mode not in juego_mod.MODOS):raise LiveError('Modo de juego inválido.')
                if not isinstance(ids,list) or not 1<=len(ids)<=6 or any(type(i)!=int or i<0 or i>5 for i in ids) or len(set(ids))!=len(ids):raise LiveError('Selecciona de uno a seis pilotos.')
                if any(not roster['slots'][i] for i in ids):raise LiveError('Un piloto ya no está registrado. Vuelve a elegir participantes.',409)
                # 🏎️ Cada piloto que corre lleva un coche del Garage (casa o invitados): de ahí salen su clase y su hándicap.
                fc=getattr(self,'falta_coche',None);falta=fc(ids,roster) if fc else None
                if falta:raise LiveError(falta,409)
                if self.session:
                    durable.escribir_json(self.directory/'sessions'/(self.session['id']+'.json'),self.session)
                pilots=[]
                for i in ids:
                    source=self.directory/roster['slots'][i]['avatar'].lstrip('/');avatar='/avatars/'+uuid.uuid4().hex+'.png';shutil.copyfile(source,self.directory/avatar.lstrip('/'))
                    pilots.append(dict(slot=i,name=roster['slots'][i]['name'],avatar=avatar,laps=[],nivel=handicap_mod.nivel_ok(roster['slots'][i].get('nivel')),pid=roster['slots'][i].get('pid')))
                source=self.resolve_source()
                if es_juego and source not in ('scx','both'):
                    raise LiveError('Puto el último y El último paga las chelas necesitan la Pit Box (tarjeta SCX) para que todos corran a la vez. Conéctala o cambia «Contar vueltas con» en Configuración.',409)
                # Práctica y Carrera empiezan en "listos": se ve el tablero y el botón Empezar. Nada cuenta (ni se
                # reinicia la ESP32) hasta que alguien aprieta Empezar y el semáforo llega a verde.
                g=getattr(getattr(self,'scx',None),'gatillo',None)
                if g is not None:g.reset_session()   # «pide cambio»: los apretones se cuentan por sesión
                self.session={'id':uuid.uuid4().hex,'created_at':time.time(),'type':typ,'mode':mode,'lap_source':source,'phase':'ready','starts_at':0,'active':None,'pending_active':ids[0] if len(ids)==1 else None,'control':1,'version':1,'cursor':0,'turn':uuid.uuid4().hex,'notice':READY_NOTICE,'reset_reason':'start','pilots':pilots,'handicap':self.current_handicap()}
                if source=='scx':self.session.update(pending_active=None)
                if es_juego:
                    st=self.juego_store;cfg=(st.config() if st is not None else juego_mod.DEFAULTS)[mode]
                    noche=st.noche() if (st is not None and mode=='chelas') else None
                    self.session['juego']=juego_mod.nuevo(mode,cfg,pilots,doble=bool(noche and noche.get('doble_siguiente')),ronda=(len(noche['rondas'])+1) if noche else (1 if mode=='chelas' else None))
                    if source=='both':self.session.update(pending_active=None)
                self.save()
            elif action=='go':
                # Botón Empezar: semáforo de salida. Repetirlo (otro dispositivo, doble clic, carrera ya en verde) no hace nada.
                s=self.session
                if not s or s['id']!=payload.get('id') or s['phase']=='ended':raise LiveError('La sesión cambió. Actualiza la pantalla.',409)
                if s['phase']=='ready':
                    secs=self.lights_seconds()
                    s['handicap']=self.current_handicap()   # el handicap queda fijo al apretar Empezar (con los coches del Garage)
                    for p in s['pilots']:   # y el nivel de cada piloto (registro de pilotos), también, y su mando
                        p['car']=self.car_of_slot(p['slot'])
                        r=roster['slots'][p['slot']] if 0<=p['slot']<len(roster['slots']) else None
                        if r and r.get('name')==p['name']:p['nivel']=handicap_mod.nivel_ok(r.get('nivel'))
                    s.update(phase='countdown',starts_at=time.time()+secs,countdown_total=secs,control=s['control']+1,version=s['version']+1,notice='¡Semáforo! Nadie arranca antes del verde.')
                    s.pop('reset_sent',None);s.pop('flush_previous',None)
                    for key in [k for k in self.scx_marks if k[0]==s['id']]:self.scx_marks.pop(key,None)   # la primera pasada tras el verde es la salida
                    self.save()
            elif action in ['red_flag','resume']:
                # PARO (bandera roja) y Reanudar: desde cualquier pantalla; repetirlos no hace nada.
                s=self.session
                if not s or s['id']!=payload.get('id') or s['phase']=='ended':raise LiveError('La sesión cambió. Actualiza la pantalla.',409)
                rf=s.get('red_flag')
                if action=='red_flag':
                    if rf and rf.get('stage')=='stop':return self.snapshot(False)
                    if rf:
                        # Paro durante el semáforo de reanudación: de vuelta a PARO.
                        rf['stage']='stop';s.update(phase='running',starts_at=0,control=s['control']+1,version=s['version']+1,notice=RED_NOTICE)
                    elif s['phase']=='countdown':
                        # Paro durante el semáforo de salida: nadie ha corrido; vuelve a "listos".
                        s.update(phase='ready',starts_at=0,control=s['control']+1,version=s['version']+1,notice='PARO durante el semáforo. Todos a la línea de meta y aprieta Empezar otra vez.')
                        for key in [k for k in self.scx_marks if k[0]==s['id']]:self.scx_marks.pop(key,None)
                    elif s['phase']=='running' and not s.get('simulated'):self.red_stop(s)
                    elif s['phase']=='ready':raise LiveError('La carrera todavía no arranca. No hay nada que parar.')
                    else:raise LiveError('Solo se puede parar una sesión que está corriendo.')
                else:
                    if not rf:return self.snapshot(False)
                    if rf.get('stage')=='resume':return self.snapshot(False)
                    secs=self.lights_seconds();rf['stage']='resume'
                    s.update(phase='countdown',starts_at=time.time()+secs,countdown_total=secs,control=s['control']+1,version=s['version']+1,notice='¡Semáforo de reanudación! Nadie acelera antes del verde.')
                self.save()
            elif action in ['sim_lap','sim_finish']:
                # Demo data stays entirely local: never advance the sensor cursor/reset.
                s=self.session
                if not s or s['id']!=payload.get('id') or s['phase'] not in ['ready','running','paused']:
                    raise LiveError('La sesión cambió o no está lista para una prueba.',409)
                if payload.get('control')!=s['control']:
                    raise LiveError('Otro dispositivo cambió el turno. Vuelve a intentarlo.',409)
                if s.get('red_flag'):raise LiveError('Hay bandera roja. Reanuda primero.',409)
                if s.get('simulated') and (s['phase']!='paused' or s['active'] is not None):
                    raise LiveError('La prueba se reanudó físicamente. Inicia otra sesión para simular.',409)
                if s['type']!='race' or s['mode']!='chelas':
                    raise LiveError('La prueba requiere una carrera de chelas.')
                if action=='sim_finish':
                    if not s.get('simulated'):raise LiveError('No hay una prueba simulada en curso.')
                    s.update(phase='paused',active=None,version=s['version']+1,notice='Carrera de prueba simulada. En pausa; termina esta sesión e inicia una nueva para correr de verdad.')
                else:
                    slot=payload.get('slot');seconds=payload.get('s')
                    pilot=next((p for p in s['pilots'] if type(slot)==int and p['slot']==slot),None)
                    if pilot is None:raise LiveError('Elige un piloto de esta sesión.')
                    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not .1<=seconds<=3600:
                        raise LiveError('Tiempo simulado inválido.')
                    if len(pilot['laps'])>=40:raise LiveError('Máximo 40 vueltas simuladas por piloto.')
                    if not s.get('simulated') and any(p['laps'] for p in s['pilots']):
                        raise LiveError('No se mezclan vueltas reales con una prueba simulada.',409)
                    # Pause before adding the first lap; physical passes cannot enter this demo.
                    if not s.get('simulated'):
                        s.update(simulated=True,phase='paused',active=None,control=s['control']+1)
                    kmh,escala=self.speed(seconds)
                    pilot['laps'].append(dict(n=len(pilot['laps'])+1,s=seconds,kmh=kmh,escala=escala,source_n=None,turn='sim:'+s['id']))
                    s.update(version=s['version']+1,notice='Carrera de prueba simulada. Agregando vueltas de demostración…')
                self.save()
            elif action in ['active','end']:
                s=self.session
                if not s or s['id']!=payload.get('id') or s['phase']=='ended':raise LiveError('La sesión cambió. Actualiza la pantalla.',409)
                if payload.get('control')!=s['control']:raise LiveError('Otro dispositivo cambió el turno. Vuelve a intentarlo.',409)
                if action=='end':
                    j=s.get('juego')
                    if j and j['fase']!='fin':j['fase']='fin';j['resultado']=None;j['bomba']=None;j['cancelada']=True
                    self.terminar_sesion(s,'Sesión terminada. Resultados guardados.' if not j else 'Ronda terminada a mano: sin Puto ni chelas esta vez.')
                else:
                    if s.get('red_flag'):raise LiveError('Hay bandera roja. Aprieta Reanudar antes de cambiar de piloto.',409)
                    if s.get('lap_source')=='scx':raise LiveError('Con la tarjeta SCX todos corren a la vez; no hace falta elegir quién está en pista.')
                    if s['phase'] in ['countdown','resetting']:raise LiveError('Espera a que termine la preparación de salida.')
                    slot=payload.get('slot')
                    if type(slot)!=int or not any(p['slot']==slot for p in s['pilots']):raise LiveError('Elige un piloto de esta sesión.')
                    if s['phase']=='ready':
                        name=next(p['name'] for p in s['pilots'] if p['slot']==slot)
                        s.update(pending_active=slot,control=s['control']+1,version=s['version']+1,notice='Sale '+name+'. Aprieta Empezar para el semáforo de salida.');self.save()
                        self.wake.set();return self.snapshot(False)
                    s.pop('reset_sent',None)
                    s.update(flush_previous=s['phase']=='running',phase='resetting',pending_active=slot,control=s['control']+1,version=s['version']+1,notice='Preparando turno nuevo. Espera la confirmación.',reset_reason='active-change');self.save()
            else:raise LiveError('Acción de sesión desconocida.')
            self.wake.set()
            return self.snapshot(False)
    def terminar_sesion(self,s,notice):
        self.red_close(s,False)
        self.close_open_pits(s,'cierre')
        s.update(phase='ended',ended_at=time.time(),starts_at=0,control=s['control']+1,version=s['version']+1,notice=notice);self.save()
    def juego_tick(self):
        """⚑/🍻: salida en falso durante el semáforo, bombas, cortes y fin de ronda (también entre cruces)."""
        with self.lock:
            s=self.session
            if s and s.get('juego') and s['phase'] in ('countdown','running'):juego_mod.tick(self,s)
    def loop(self):
        next_poll=0
        while not self.stop_event.is_set():
            try:
                self.wake.clear();now=time.monotonic()
                with self.lock:
                    s=self.session
                    if s and s.get('red_flag') and s['phase']=='countdown' and time.time()>=s.get('starts_at',0):
                        self.red_resume_go(s);self.save()
                    phase=s['phase'] if s else None
                    prepare=bool(s and not s.get('red_flag') and (phase in ['resetting','waiting_sensor'] or (phase=='countdown' and time.time()>=s['starts_at'])))
                    token=(s['id'],s['control']) if s else None
                    if prepare and s.get('lap_source')=='scx':
                        s.update(phase='running',active=None,control=s['control']+1,version=s['version']+1,notice='¡A correr! La primera pasada de cada coche por la meta es la salida.')
                        self.start_clock(s)
                        s.pop('pending_active',None);self.save();prepare=False;token=(s['id'],s['control'])
                if now>=next_poll:
                    d=self.read_sensor()
                    with self.lock:
                        current=self.session and (self.session['id'],self.session['control'])==token
                        if current and d and not prepare:self.consume(d)
                        if current and prepare and not d:
                            if self.session['phase']!='waiting_sensor':
                                self.session.update(phase='waiting_sensor',version=self.session['version']+1,notice='Comprobando conexión del sensor. La salida se preparará al recuperar respuesta.');self.save()
                    if current and prepare and d:self.reset_turn(token,d)
                    with self.lock:next_poll=time.monotonic()+self.poll_interval()
                self.juego_tick()
                self.flush()
                wait_s=min(.2,next_poll-time.monotonic())
                with self.lock:
                    s=self.session
                    if s and s['phase']=='countdown':wait_s=min(wait_s,s.get('starts_at',0)-time.time())
                self.wake.wait(max(.01,wait_s))
            except Exception as e:
                print('Error de sesión: '+type(e).__name__,flush=True);self.stop_event.wait(.5)
        self.flush()
    def close(self):self.stop_event.set();self.wake.set();self.worker.join(timeout=4)
