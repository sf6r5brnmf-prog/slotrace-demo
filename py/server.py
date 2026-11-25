#!/usr/bin/env python3
"""Padrón local de pilotos. Python 3.9+, sin dependencias externas."""
import argparse, base64, binascii, copy, errno, json, os, re, signal, struct, sys, threading, time, traceback, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from live import Live, LiveError
from scx import SCX, LapConfig
from esp32usb import Esp32Usb, OFF_VALUES as USB_OFF
import juego as juego_mod
from gp import GrandPrix, GPError, DEFAULTS as GP_DEFAULTS, flag_config as gp_flag_config
import durable
from instancia import InstanceLock
import micoche
import torneo as torneo_mod
import handicap as handicap_mod
import garage as garage_mod
import ranking as ranking_mod
import pilotos as pilotos_mod

ROOT = Path(__file__).resolve().parent
COLORS = [('Blanco','#edf2f7'),('Amarillo','#ffe23b'),('Rojo','#ff4d50'),('Azul','#3d96ff'),('Verde','#50dc92'),('Naranja','#ff963d')]
LOCK = threading.RLock()

class Store:
    """Pilotos registrados (data/pilotos.json). Guardado atómico con copia .bak del último archivo bueno."""
    def __init__(self, directory, avisos=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory/'avatars').mkdir(exist_ok=True)
        self.path = self.directory/'pilotos.json'; self.cache = None
        d, aviso = durable.leer_json(self.path, validate=self.check, nombre='pilotos.json (pilotos registrados)')
        if aviso and avisos is not None: avisos.append(aviso)
        if d is None: d = {'version':0,'slots':[None]*6}
        if d is None or aviso or not self.path.exists(): self.write(d)
        self.cache = copy.deepcopy(d)
    @staticmethod
    def check(d):
        if not isinstance(d, dict) or not isinstance(d.get('slots'), list) or len(d['slots']) != 6 or type(d.get('version')) != int:
            raise RuntimeError('El archivo de pilotos no tiene seis espacios; no se modificó.')
    def read(self):
        try:
            d = json.loads(self.path.read_text(encoding='utf-8')); self.check(d)
            self.cache = copy.deepcopy(d); return d
        except (OSError, ValueError, RuntimeError):
            # Archivo borrado o a medias: se sigue con la última versión buena en memoria y se vuelve a guardar.
            if self.cache is None: raise RuntimeError('El archivo de pilotos no tiene seis espacios; no se modificó.')
            if self.path.exists(): durable.apartar(self.path)   # el archivo raro se guarda aparte, no se pierde
            try: self.write(self.cache)
            except OSError: pass
            return copy.deepcopy(self.cache)
    def write(self,d):
        durable.escribir_json(self.path, d, backup=True, indent=2)
        self.cache = copy.deepcopy(d)

class Handler(BaseHTTPRequestHandler):
    server_version='PutoElUltimo/1.0'
    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        if isinstance(data,(dict,list)): data=json.dumps(data,ensure_ascii=False).encode()
        if isinstance(data,str): data=data.encode()
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','private, max-age=31536000, immutable' if content_type=='image/png' else 'no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(data)
    def handle_safely(self, fn):
        try: fn()
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception:
            # Nunca mandar un traceback en inglés al navegador; queda en server.log para diagnóstico.
            print('Error interno en %s %s:\n%s' % (self.command, urlsplit(self.path).path, traceback.format_exc()), flush=True)
            try: self.reply(500, {'error':'Algo falló en el servidor de la Mac. Vuelve a intentar en unos segundos.'})
            except Exception: pass
    def do_GET(self): self.handle_safely(self._get)
    def do_POST(self): self.handle_safely(self._post)
    def _get(self):
        path=urlsplit(self.path).path
        if path=='/api/salud':
            return self.reply(200,{'ok':True,'app':'Puto el último','boot':self.server.boot,'pid':os.getpid(),'inicio':self.server.started_at,
                                   'esp32_url':self.server.live.base_url,'avisos':list(self.server.avisos)})
        if path=='/scx/estado':return self.reply(200,self.server.scx.estado())
        if path=='/scx/eventos':
            try:desde=int(parse_qs(urlsplit(self.path).query).get('desde',['0'])[0])
            except ValueError:return self.reply(400,{'error':'desde debe ser un número'})
            return self.reply(200,self.server.scx.eventos(desde))
        if path=='/api/vueltas-config':return self.reply(200,self.server.lap_config.read())
        if path=='/api/juego':return self.reply(200,self.server.juego.vista())
        if path=='/api/diagnostics':return self.reply(200,self.server.live.diagnostics())
        if path in ['/api/live','/api/session']:
            revisar_garage(self.server)
            return self.reply(200,self.server.live.snapshot(include_sensor_data=False))
        if path=='/api/cruces':
            # Explosión al sensor: solo un contador de cruces del sensor IR. ?explosion=1 = una pantalla grande está escuchando.
            q=parse_qs(urlsplit(self.path).query)
            return self.reply(200,self.server.live.crossings(listener=q.get('explosion',['0'])[0]=='1'))
        if path in ['/api/sensor','/datos']:
            sensor=self.server.live.sensor_snapshot()
            if path=='/api/sensor':return self.reply(200,sensor)
            return self.reply(200 if sensor['connected'] else 503,sensor['data'] if sensor['connected'] else {'error':'sensor no conectado'})
        if path=='/api/micoche':
            # «Mi coche» (teléfono de cada piloto): solo los datos de ese piloto, sin controles. Solo lectura.
            q=parse_qs(urlsplit(self.path).query)
            with LOCK: roster=self.server.store.read()
            raw=q.get('slot',[None])[0];slot=None
            if raw is not None:
                try:slot=int(raw)
                except ValueError:slot=None
            elif 'piloto' in q:slot=micoche.slot_desde_parametro(roster,q['piloto'][0])
            # Torneo por mangas: ?torneo=N (lugar del piloto en el torneo, no en el registro de 6).
            tq=q.get('torneo',[None])[0];tslot=None
            if tq is not None:
                try:tslot=int(tq)
                except ValueError:tslot=None
            if tslot is not None:
                gpo=self.server.gp
                with gpo.lock:turno=gpo.torneo_mi_turno(tslot) if gpo.es_torneo() else None
                return self.reply(200,micoche.vista_torneo(self.server.live.snapshot(include_sensor_data=False),gpo.snapshot(),tslot,turno))
            return self.reply(200,micoche.vista(roster,self.server.live.snapshot(include_sensor_data=False),self.server.gp.snapshot(),slot))
        if path=='/api/micoche/torneo':
            # Mi coche: solo la lista de pilotos del torneo activo (nombre, nivel, avatar) para elegir; nada más.
            gpo=self.server.gp
            with gpo.lock:
                g=gpo.gp
                t=None if not g or g.get('mode')!='torneo' or g.get('status')=='cancelled' else {'id':g['id'],'pilots':[{'slot':p['slot'],'name':p['name'],'nivel':p.get('nivel'),'avatar':p.get('avatar') or ''} for p in g['pilots']]}
            return self.reply(200,{'torneo':t})
        if path=='/api/gp':
            revisar_garage(self.server)   # barato: solo trabaja cuando algo acaba de terminar
            return self.reply(200,self.server.gp.snapshot())
        if path=='/api/inscritos':
            revisar_niveles(self.server);return self.reply(200,self.server.inscritos.read())
        if path=='/api/gp/config':return self.reply(200,self.server.gp.get_config())
        if path=='/api/scx':return self.reply(200,self.server.scx.debug())
        if path=='/api/gatillo':return self.reply(200,self.server.scx.gatillo_view())   # velocímetro en vivo + «pide cambio» (~10 por segundo)
        if path=='/api/pits':return self.reply(200,self.server.scx.pits_view())   # entrada/salida de pits y tiempos (estimados)
        if path=='/api/gp/resultados.csv':
            try:body=self.server.gp.export_csv()
            except GPError as e:return self.reply(e.status,{'error':str(e)})
            data=('\ufeff'+body).encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8')
            self.send_header('Content-Disposition','attachment; filename="gran_premio_resultados.csv"');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
        if path=='/api/session/resultados.csv':
            try:body=self.server.live.export_csv()
            except LiveError as e:return self.reply(e.status,{'error':str(e)})
            data=('\ufeff'+body).encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8')
            self.send_header('Content-Disposition','attachment; filename="sesion_vueltas.csv"');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
        if re.fullmatch(r'/sfx/[a-z_]+\.mp3',path):
            file=ROOT/path[1:]
            if file.exists():return self.reply(200,file.read_bytes(),'audio/mpeg')
        if path=='/api/garage':
            revisar_garage(self.server)
            return self.reply(200,self.server.garage.view())
        if path=='/api/pilotos':
            asegurar_registro(self.server);revisar_niveles(self.server);revisar_garage(self.server)
            return self.reply(200,vista_pilotos(self.server))
        if path=='/api/ranking':
            revisar_niveles(self.server)
            return self.reply(200,vista_ranking(self.server))
        if path=='/api/roster':
            revisar_niveles(self.server)
            revisar_garage(self.server)
            with LOCK: d=self.server.store.read()
            # 🏆 mejor vuelta REAL (sin hándicap) de cada piloto por clase, para su tarjeta.
            rk=self.server.ranking
            return self.reply(200,dict(d,colors=[{'name':n,'hex':h} for n,h in COLORS],mejores=[rk.mejores(p['name']) if p else {} for p in d['slots']],ranking_v=rk.data['version']))
        assets={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),
                '/gp':('gp.html','text/html; charset=utf-8'),'/avisos.js':('avisos.js','text/javascript; charset=utf-8'),'/gp.js':('gp.js','text/javascript; charset=utf-8'),'/gauges.js':('gauges.js','text/javascript; charset=utf-8'),'/lights.js':('lights.js','text/javascript; charset=utf-8'),'/paro.js':('paro.js','text/javascript; charset=utf-8'),'/explosion.js':('explosion.js','text/javascript; charset=utf-8'),'/gatillo.js':('gatillo.js','text/javascript; charset=utf-8'),'/gp.css':('gp.css','text/css; charset=utf-8'),
                '/micoche':('micoche.html','text/html; charset=utf-8'),'/micoche.js':('micoche.js','text/javascript; charset=utf-8'),'/micoche.css':('micoche.css','text/css; charset=utf-8'),'/micoche-icon.png':('micoche-icon.png','image/png'),
                '/scx':('scx.html','text/html; charset=utf-8'),'/scx.js':('scx.js','text/javascript; charset=utf-8'),'/handicap.js':('handicap.js','text/javascript; charset=utf-8'),
                '/garage':('garage.html','text/html; charset=utf-8'),'/ranking':('ranking.html','text/html; charset=utf-8'),'/ranking.js':('ranking.js','text/javascript; charset=utf-8'),'/garage.js':('garage.js','text/javascript; charset=utf-8'),'/garage.css':('garage.css','text/css; charset=utf-8')}
        if path=='/micoche/':path='/micoche'
        if path=='/garage/':path='/garage'
        if path in assets:
            filename,mime=assets[path]
            return self.reply(200,(ROOT/filename).read_bytes(),mime)
        if re.fullmatch(r'/garage-fotos/[0-9a-f]{32}\.jpg',path):
            file=self.server.garage.directory/path[1:]
            if file.exists(): return self.reply(200,file.read_bytes(),'image/jpeg')
        if re.fullmatch(r'/avatars/[0-9a-f]{32}\.png',path):
            file=self.server.store.directory/path[1:]
            if file.exists(): return self.reply(200,file.read_bytes(),'image/png')
        self.reply(404,{'error':'No se encontró esa página.'})
    def _post(self):
        route=urlsplit(self.path).path
        if route not in ['/api/slot','/api/session','/api/gp','/api/gp/config','/api/sim','/api/vueltas-config','/api/scx/simular','/api/inscritos','/api/garage','/api/pilotos','/api/juego']: return self.reply(404,{'error':'Ruta desconocida.'})
        # Un sitio externo no puede escribir con un formulario o fetch sin CORS.
        origin=self.headers.get('Origin')
        if self.headers.get('X-Roster')!='1' or (origin and urlsplit(origin).netloc!=self.headers.get('Host')):
            return self.reply(403,{'error':'Abre esta app directamente para cambiar pilotos.'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=2500000: return self.reply(413,{'error':'La imagen es demasiado grande. Toma otra foto.'})
            payload=json.loads(self.rfile.read(size))
            if not isinstance(payload,dict):raise ValueError('Datos inválidos.')
            if route in ['/api/gp','/api/gp/config']:
                try:
                    if route=='/api/gp/config':return self.reply(200,self.server.gp.set_config(payload))
                    with LOCK:roster=self.server.store.read()
                    return self.reply(200,self.server.gp.command(payload,roster))
                except GPError as e:return self.reply(e.status,{'error':str(e)})
            if route=='/api/pilotos':
                try:return self.reply(200,api_pilotos(self.server,payload))
                except pilotos_mod.PilotoError as e:return self.reply(e.status,dict({'error':str(e)},**e.extra))
            if route=='/api/inscritos':
                try:
                    r=self.server.inscritos.write(payload)
                    try:self.server.registro.invitados([x['name'] for x in r['pilotos']],{x['name']:x for x in r['pilotos']})
                    except Exception:traceback.print_exc()
                    return self.reply(200,r)
                except torneo_mod.TorneoError as e:return self.reply(e.status,{'error':str(e)})
            if route=='/api/garage':
                if isinstance(payload,dict) and payload.get('action') in ('usar','rapido'):
                    with LOCK:sl=self.server.store.read()['slots']
                    payload['nombres']={str(i):(x or {}).get('name') or 'Piloto %d'%(i+1) for i,x in enumerate(sl)}
                try:return self.reply(200,self.server.garage.command(payload))
                except garage_mod.GarageError as e:return self.reply(e.status,{'error':str(e)})
            if route=='/api/juego':
                # ⚑/🍻 Modos de juego: configuración, «la siguiente ronda vale doble» y «Cerrar la noche».
                try:
                    a=payload.get('action');st=self.server.juego
                    if a=='config':return self.reply(200,st.set_config(payload))
                    if a=='doble':return self.reply(200,st.doble_siguiente(bool(payload.get('on'))))
                    if a=='cerrar_noche':
                        if _ocupado_juego(self.server):return self.reply(409,{'error':'Hay una ronda en curso. Termínala antes de cerrar la noche.'})
                        n=st.cerrar_noche();v=st.vista();v['cerrada']=n;return self.reply(200,v)
                    return self.reply(400,{'error':'Acción desconocida.'})
                except juego_mod.JuegoError as e:return self.reply(e.status,{'error':str(e)})
            if route=='/api/vueltas-config':
                return self.reply(200,self.server.lap_config.write(payload))
            if route=='/api/scx/simular':
                # Gancho de prueba solo desde la propia Mac; nunca escribe al puerto serial.
                if self.client_address[0] not in ['127.0.0.1','::1']:return self.reply(403,{'error':'Solo desde la Mac.'})
                car=payload.get('car')
                t=payload.get('t_ms');t=t if type(t) in (int,float) else None
                lane=payload.get('lane') or 'track'
                return self.reply(200,{'accepted':self.server.scx.inject_finish(car,t,lane=lane)})
            if route=='/api/sim':
                sim=self.server.scx.sim
                if not sim:return self.reply(404,{'error':'El simulador no está activo.'})
                if payload.get('false_start'):sim.false_start_next=True
                g=payload.get('ghosts')
                if type(g) in (int,float) and 0<=g<=1:sim.ghost_rate=float(g)   # cruces fantasma a media vuelta (pruebas de vueltas sospechosas)
                pit=payload.get('pit')
                if type(pit)==int and 1<=pit<=6:sim.request_pit(pit-1)   # próxima pasada de ese coche (1-6) = entrada a pits (F0)
                return self.reply(200,{'ok':True})
            if route=='/api/session':
                with LOCK:roster=self.server.store.read()
                try:return self.reply(200,self.server.live.command(payload,roster))
                except LiveError as e:return self.reply(e.status,{'error':str(e)})
            slot=payload.get('slot')
            if not isinstance(slot,int) or isinstance(slot,bool) or not 0<=slot<6:
                return self.reply(400,{'error':'Máximo 6 competidores. No hay un séptimo espacio.'})
            if payload.get('action') in ('nivel','nivel_descartar'):
                # Nivel del piloto (Novato / Intermedio / Experto): se cambia solo, sin tocar nombre ni foto.
                # «nivel_descartar»: quita el aviso de nivel sugerido / nivel cambiado sin cambiar nada.
                nv=payload.get('nivel')
                if payload['action']=='nivel' and nv not in handicap_mod.NIVEL_TXT: raise ValueError('Elige Novato, Intermedio o Experto.')
                with LOCK:
                    d=self.server.store.read()
                    if not d['slots'][slot]: return self.reply(404,{'error':'Ese lugar ya no tiene piloto.'})
                    if payload['action']=='nivel':d['slots'][slot]['nivel']=nv
                    d['slots'][slot].pop('sugerido',None);d['slots'][slot].pop('nivel_cambio',None)
                    self.server.registro.desde_slots(d['slots'])
                    d['version']+=1; self.server.store.write(d)
                return self.reply(200,{'ok':True,'version':d['version']})
            with LOCK:
                d=self.server.store.read(); previous=d['slots'][slot]
                revision=previous['revision'] if previous else None
                if payload.get('expectedRevision')!=revision:
                    return self.reply(409,{'error':'Este espacio cambió desde otro dispositivo. Cierra y vuelve a abrir la edición.'})
                action=payload.get('action')
                old=previous.get('avatar') if previous else None
                if action=='remove':
                    d['slots'][slot]=None
                elif action=='save':
                    name=payload.get('name','')
                    if not isinstance(name,str): raise ValueError('Escribe el nombre del piloto.')
                    name=' '.join(name.split())
                    if not 1<=len(name)<=32 or any(ord(c)<32 for c in name): raise ValueError('El nombre debe tener de 1 a 32 caracteres.')
                    avatar=old
                    image=payload.get('image')
                    if image is not None:
                        if not isinstance(image,str) or not image.startswith('data:image/png;base64,'): raise ValueError('Usa una foto para crear el avatar.')
                        try: raw=base64.b64decode(image.split(',',1)[1],validate=True)
                        except (ValueError,binascii.Error): raise ValueError('La imagen no es válida.')
                        if not (100<len(raw)<=1800000 and raw[:8]==b'\x89PNG\r\n\x1a\n' and raw[12:16]==b'IHDR' and struct.unpack('>II',raw[16:24])==(600,720)):
                            raise ValueError('El avatar no es válido. Vuelve a elegir la foto.')
                        avatar='/avatars/'+uuid.uuid4().hex+'.png'
                        durable.escribir_bytes(self.server.store.directory/avatar[1:],raw)
                    if not avatar: raise ValueError('Falta la foto del rostro.')
                    nv=payload.get('nivel',(previous or {}).get('nivel') or handicap_mod.NIVEL_DEFAULT)
                    if nv not in handicap_mod.NIVEL_TXT: raise ValueError('Elige Novato, Intermedio o Experto.')
                    d['slots'][slot]={'name':name,'avatar':avatar,'revision':uuid.uuid4().hex,'nivel':nv}
                    if previous and previous.get('pid'):d['slots'][slot]['pid']=previous['pid']
                else: raise ValueError('Acción desconocida.')
                # 👥 Registro: el piloto queda (o se actualiza) en el registro aunque se quite de la parrilla.
                self.server.registro.desde_slots(d['slots'])
                d['version']+=1; self.server.store.write(d)
                if old and (d['slots'][slot] is None or old!=d['slots'][slot]['avatar']):
                    borrar_avatar(self.server,old)
            self.reply(200,{'ok':True,'version':d['version']})
        except (ValueError,TypeError,KeyError) as e:
            self.reply(400,{'error':str(e) if isinstance(e,ValueError) else 'Datos incompletos.'})
        except OSError:
            self.reply(500,{'error':'No se pudo guardar en la Mac. Revisa el espacio disponible.'})
    def log_message(self, fmt, *args):
        # No imprimir nombres, fotos ni datos enviados. Los sondeos frecuentes del tablero no llenan server.log.
        if len(args)>=2 and str(args[1])=='200' and any(x in str(args[0]) for x in ['GET /api/gp ','GET /api/scx ','GET /api/salud ','GET /api/live','GET /api/micoche','GET /api/roster ','GET /api/sensor ','GET /api/cruces','GET /api/gatillo','GET /scx/estado','GET /scx/eventos']):return
        print('%s %s' % (self.log_date_time_string(), fmt % args),flush=True)

# ---------- Nivel automático por tiempo (registro de pilotos e inscritos del torneo) ----------
NIVEL_LOCK=threading.Lock()
def _sesiones_terminadas(server):
    """[(clave, fuente, [(nombre, clase, mejor vuelta real, vueltas válidas)])] de lo que ya terminó."""
    out=[];live=server.live;gpo=server.gp
    with live.lock:
        s=live.session
        if s and s.get('phase')=='ended' and s.get('id'):
            h=live.session_handicap(s);rows=[]
            for p in s['pilots']:
                laps=[l['s'] for l in p.get('laps') or [] if isinstance(l.get('s'),(int,float))]
                rows.append((p['name'],handicap_mod.clase_de(h,live.hkey(h,p['slot'])),min(laps) if laps else None,len(laps)))
            out.append(('live:'+s['id'],('Carrera' if s.get('type')=='race' else 'Práctica')+time.strftime(' %d/%m %H:%M',time.localtime(s.get('created_at') or time.time())),rows))
    with gpo.lock:
        g=gpo.gp
        if g and g.get('status')!='cancelled':
            tq=gpo.es_torneo()
            for run in g['runs']:
                if run['phase']!='done' or run.get('skipped'):continue
                rows=[];h=gpo.handicap_run(run)
                for sl in run.get('participants') or []:
                    d=run['data'].get(str(sl))
                    if not isinstance(d,dict):continue
                    laps=[l['s'] for l in d.get('laps') or [] if l.get('valid')]
                    p=gpo.pilot(sl);rows.append((p['name'],handicap_mod.clase_de(h,gpo.hk(h,run,sl)),min(laps) if laps else None,len(laps)))
                out.append(('gp:%s:%s'%(g['id'],run['key']),('Torneo · ' if tq else 'Gran Premio · ')+run['label'],rows))
    return out
GARAGE_LOCK=threading.Lock()
def revisar_garage(server):
    """Historial del Garage: al terminar una Práctica/Carrera o un Gran Premio/torneo, guarda por coche del Garage
    su mejor vuelta REAL, vueltas y si ganó. Cada sesión una vez (data/garage.json «hechos»)."""
    if not GARAGE_LOCK.acquire(blocking=False):return
    try:
        gar=server.garage;live=server.live;gpo=server.gp
        with live.lock:
            s=live.session
            s=copy.deepcopy(s) if s and s.get('phase')=='ended' and s.get('id') and not gar.ya('live:'+s['id']) else None
        if s and s.get('phase')=='ended' and s.get('id') and not gar.ya('live:'+s['id']):
            h=s.get('handicap');coches={};hs={};gid={}
            for p in s['pilots']:
                car=live.hkey(h,p['slot']);g=handicap_mod.garage_de(h,car)
                hs[p['slot']]=handicap_mod.seg_de(h,car,p.get('nivel'))
                if not g:continue
                laps=[l['s'] for l in p.get('laps') or [] if isinstance(l.get('s'),(int,float))]
                gid[p['slot']]=g['id'];x=coches.setdefault(g['id'],{'best':None,'vueltas':0,'gano':False,'piloto':p['name']})
                if laps:x['best']=min(laps) if x['best'] is None else min(x['best'],min(laps));x['vueltas']+=len(laps)
            if s.get('type')=='race':
                for pos,p in live.standings(s,hs):
                    if pos==1 and p['slot'] in gid:coches[gid[p['slot']]]['gano']=True
            gar.registrar('live:'+s['id'],{'tipo':'carrera' if s.get('type')=='race' else 'practica','at':s.get('created_at'),
                          'fuente':('Carrera' if s.get('type')=='race' else 'Práctica')+time.strftime(' %d/%m %H:%M',time.localtime(s.get('created_at') or time.time())),'coches':coches})
        with gpo.lock:
            g=gpo.gp
            g=copy.deepcopy(g) if g and g.get('status')=='done' and not gar.ya('gp:'+g['id']) else None
        if g and g.get('status')=='done' and not gar.ya('gp:'+g['id']):
            snap=(gpo.snapshot() or {}).get('gp') or {}
            with gpo.lock:
                coches={};tq=gpo.es_torneo()
                for run in g['runs']:
                    if run['phase']!='done' or run.get('skipped'):continue
                    h=gpo.handicap_run(run)
                    for sl in run.get('participants') or []:
                        d=run['data'].get(str(sl))
                        if not isinstance(d,dict):continue
                        gg=handicap_mod.garage_de(h,gpo.hk(h,run,sl))
                        if not gg:continue
                        laps=[l['s'] for l in d.get('laps') or [] if l.get('valid')]
                        x=coches.setdefault(gg['id'],{'best':None,'vueltas':0,'gano':False,'piloto':gpo.pilot(sl)['name']})
                        if laps:x['best']=min(laps) if x['best'] is None else min(x['best'],min(laps));x['vueltas']+=len(laps)
                for r in snap.get('final') or []:
                    if r.get('pos')==1:
                        gg={'id':r.get('garage_id')} if r.get('garage_id') else None
                        if gg and gg['id'] in coches:coches[gg['id']]['gano']=True
            gar.registrar('gp:'+g['id'],{'tipo':'torneo' if tq else 'gp','at':g.get('created_at'),'fuente':('Torneo' if tq else 'Gran Premio')+time.strftime(' %d/%m %H:%M',time.localtime(g.get('created_at') or time.time())),'coches':coches})
    except Exception as e:
        print('Garage: no se pudo revisar el historial:',e,flush=True)
    finally:
        try:revisar_pilotos(server)
        except Exception:traceback.print_exc()
        GARAGE_LOCK.release()
def asegurar_registro(server):
    """Todo piloto de la parrilla está en el registro (por si alguien llegó por la ruta vieja /api/slot o por archivo)."""
    reg=getattr(server,'registro',None)
    if reg is None:return
    with LOCK:
        d=server.store.read()
        if any(x and not reg.find(x.get('pid') or '') for x in d['slots']) and reg.desde_slots(d['slots']):d['version']+=1;server.store.write(d)
def revisar_pilotos(server):
    asegurar_registro(server)
    """👥 Historial de cada piloto del registro: al terminar una Práctica/Carrera o un Gran Premio/torneo guarda su
    mejor vuelta REAL, vueltas, posición, si ganó y con qué coche. Cada sesión una vez (registro.json «hechos»)."""
    reg=getattr(server,'registro',None)
    if reg is None:return
    live=server.live;gpo=server.gp
    with live.lock:
        s=live.session
        s=copy.deepcopy(s) if s and s.get('phase')=='ended' and s.get('id') and not reg.ya('live:'+s['id']) else None
    if s:
        h=s.get('handicap');hs={};coche={}
        for p in s['pilots']:
            car=live.hkey(h,p['slot']);hs[p['slot']]=handicap_mod.seg_de(h,car,p.get('nivel'));g=handicap_mod.garage_de(h,car);coche[p['slot']]=(g or {}).get('nombre') or ''
        pos={p['slot']:x for x,p in live.standings(s,hs)};race=s.get('type')=='race';filas=[]
        for p in s['pilots']:
            laps=[l['s'] for l in p.get('laps') or [] if isinstance(l.get('s'),(int,float))]
            filas.append((p['name'],min(laps) if laps else None,len(laps),race and pos.get(p['slot'])==1,coche[p['slot']],pos.get(p['slot'])))
        reg.registrar('live:'+s['id'],{'tipo':'carrera' if race else 'practica','at':s.get('created_at'),
                      'fuente':('Carrera' if race else 'Práctica')+time.strftime(' %d/%m %H:%M',time.localtime(s.get('created_at') or time.time()))},filas)
    with gpo.lock:
        g=gpo.gp
        g=copy.deepcopy(g) if g and g.get('status')=='done' and not reg.ya('gp:'+g['id']) else None
    if g:
        snap=(gpo.snapshot() or {}).get('gp') or {}
        with gpo.lock:
            tq=gpo.es_torneo();por={}
            for run in g['runs']:
                if run['phase']!='done' or run.get('skipped'):continue
                h=gpo.handicap_run(run)
                for sl in run.get('participants') or []:
                    d=run['data'].get(str(sl))
                    if not isinstance(d,dict):continue
                    gg=handicap_mod.garage_de(h,gpo.hk(h,run,sl));laps=[l['s'] for l in d.get('laps') or [] if l.get('valid')]
                    x=por.setdefault(gpo.pilot(sl)['name'],{'best':None,'n':0,'coche':''})
                    if laps:x['best']=min(laps) if x['best'] is None else min(x['best'],min(laps));x['n']+=len(laps)
                    if gg:x['coche']=gg.get('nombre') or x['coche']
        fin={r.get('name'):r.get('pos') for r in snap.get('final') or []}
        reg.registrar('gp:'+g['id'],{'tipo':'torneo' if tq else 'gp','at':g.get('created_at'),
                      'fuente':('Torneo' if tq else 'Gran Premio')+time.strftime(' %d/%m %H:%M',time.localtime(g.get('created_at') or time.time()))},
                      [(n,x['best'],x['n'],fin.get(n)==1,x['coche'],fin.get(n)) for n,x in por.items()])
def borrar_avatar(server,av):
    """Borra un avatar solo si ya nadie lo usa (ni la parrilla ni el registro)."""
    if not av:return
    try:
        sl=server.store.read()['slots'];reg=server.registro.read()['pilotos']
        if any(x and x.get('avatar')==av for x in sl) or any(p.get('avatar')==av for p in reg):return
        (server.store.directory/av[1:]).unlink(missing_ok=True)
    except Exception:traceback.print_exc()
def avatar_png(server,image):
    """Avatar del piloto: PNG de 600×720 hecho en el teléfono (con foto o con sus iniciales)."""
    if not isinstance(image,str) or not image.startswith('data:image/png;base64,'): raise pilotos_mod.PilotoError('El avatar no es válido.')
    try: raw=base64.b64decode(image.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error): raise pilotos_mod.PilotoError('La imagen no es válida.')
    if not (100<len(raw)<=1800000 and raw[:8]==b'\x89PNG\r\n\x1a\n' and raw[12:16]==b'IHDR' and struct.unpack('>II',raw[16:24])==(600,720)):
        raise pilotos_mod.PilotoError('El avatar no es válido. Vuelve a elegir la foto.')
    av='/avatars/'+uuid.uuid4().hex+'.png';durable.escribir_bytes(server.store.directory/av[1:],raw);return av
def vista_pilotos(server):
    """Registro completo: cada piloto con su lugar en la parrilla, mejores vueltas reales por clase e historial."""
    with LOCK:d=server.store.read()
    reg=server.registro;r=reg.read();lugar={}
    for i,x in enumerate(d['slots']):
        if x and x.get('pid'):lugar[x['pid']]=i
    out=[]
    for p in r['pilotos']:
        q=dict(p,slot=lugar.get(p['id']),mejores=server.ranking.mejores(p['name']),hist=(r['hist'].get(p['id']) or [])[:20])
        with reg.lock:q.update(reg.stats(p['id']))
        out.append(q)
    return {'version':r['version'],'parrilla_v':d['version'],'pilotos':out,'colors':[{'name':n,'hex':h} for n,h in COLORS],'colores':pilotos_mod.COLORES}
def _renombrar(server,viejo,nuevo):
    """Nombre nuevo (o pilotos unidos): ranking e inscritos del torneo siguen al piloto."""
    if not viejo or viejo==nuevo:return
    try:server.ranking.renombrar(viejo,nuevo)
    except Exception:traceback.print_exc()
    try:
        ins=server.inscritos.read()['pilotos'];ch=False;ya={x['name'].casefold() for x in ins}
        for x in ins:
            if x['name'].casefold()==viejo.casefold():
                if nuevo.casefold() in ya and nuevo.casefold()!=viejo.casefold():ins.remove(x)
                else:x['name']=nuevo
                ch=True;break
        if ch:server.inscritos.write({'pilotos':ins})
    except Exception:traceback.print_exc()
def _levantar(server,d,i):
    """Quita a un piloto de la parrilla (sigue en el registro). Su coche del Garage se libera."""
    if not d['slots'][i]:return
    d['slots'][i]=None
    try:server.garage.command({'action':'usar','slot':i,'id':''})
    except Exception:pass
def _ocupado(server):
    live=server.live
    with live.lock:s=live.session;return bool(s and s.get('phase') not in ('ended',None))
def api_pilotos(server,payload):
    asegurar_registro(server)
    reg=server.registro;a=payload.get('action');pid=payload.get('id')
    E=pilotos_mod.PilotoError
    with LOCK:
        d=server.store.read();cambio_parrilla=False;tirar=[]
        if a=='guardar':
            img=payload.get('image');av=avatar_png(server,img) if img else None
            previo=reg.find(pid) if pid else None;old_av=(previo or {}).get('avatar')
            try:p,viejo=reg.guardar(payload,av)
            except pilotos_mod.PilotoError:
                if av:(server.store.directory/av[1:]).unlink(missing_ok=True)
                raise
            if previo and viejo!=p['name']:_renombrar(server,viejo,p['name'])
            cambio_parrilla=reg.a_slots(d['slots'])
            if av and old_av and old_av!=av:
                if cambio_parrilla:d['version']+=1;server.store.write(d);cambio_parrilla=False
                borrar_avatar(server,old_av)
            res={'saved':p['id']}
        elif a=='unir':
            x,y=reg.unir(payload.get('de'),payload.get('a'))
            for s in d['slots']:
                if s and s.get('pid')==x['id']:
                    if any(t and t.get('pid')==y['id'] for t in d['slots']):_levantar(server,d,d['slots'].index(s))
                    else:s['pid']=y['id']
                    cambio_parrilla=True
            _renombrar(server,x['name'],y['name'])
            cambio_parrilla=reg.a_slots(d['slots']) or cambio_parrilla
            res={'saved':y['id']}
        elif a in ('archivar','promover','nivel','nivel_descartar','borrar'):
            p=reg.find(pid)
            if not p:raise E('Ese piloto ya no está en el registro.',404)
            if a in ('archivar','borrar') and (a=='borrar' or payload.get('valor')):
                for i,s in enumerate(d['slots']):
                    if s and s.get('pid')==pid:
                        if _ocupado(server):raise E('Hay una sesión en curso con %s. Termínala antes.'%p['name'],409)
                        _levantar(server,d,i);cambio_parrilla=True
            p=reg.simple(pid,a,payload.get('valor') if a!='nivel' else payload.get('nivel'))
            if a=='borrar':
                try:server.ranking.borrar(p['name'])
                except Exception:traceback.print_exc()
                tirar.append(p.get('avatar'))
            cambio_parrilla=reg.a_slots(d['slots']) or cambio_parrilla
            res={'saved':pid}
        elif a=='sentar':
            p=reg.find(pid)
            if not p:raise E('Ese piloto ya no está en el registro.',404)
            if any(s and s.get('pid')==pid for s in d['slots']):return dict(vista_pilotos(server),saved=pid)
            if p.get('archivado'):raise E('%s está archivado. Reactívalo primero.'%p['name'])
            if any(s and pilotos_mod.clave(s['name'])==pilotos_mod.clave(p['name']) for s in d['slots']):raise E('Ya hay un «%s» en la parrilla.'%p['name'],409)
            i=payload.get('slot')
            if not (type(i)==int and 0<=i<6 and not d['slots'][i]):
                i=next((k for k,s in enumerate(d['slots']) if not s),None)
            if i is None:raise E('La parrilla ya tiene 6 pilotos. Quita a alguien para que entre %s.'%p['name'],409)
            if not p.get('avatar'):
                img=payload.get('image')
                if not img:raise E('Falta el avatar de %s.'%p['name'])
                with reg.lock:p['avatar']=avatar_png(server,img);p['foto']=False;reg.save()
            d['slots'][i]={'name':p['name'],'avatar':p['avatar'],'revision':uuid.uuid4().hex,'nivel':p['nivel'],'pid':pid}
            for k in ('sugerido','nivel_cambio'):
                if p.get(k):d['slots'][i][k]=copy.deepcopy(p[k])
            # Su coche habitual, si nadie lo trae ahorita.
            if p.get('coche'):
                try:
                    g=server.garage.read()
                    if any(c['id']==p['coche'] for c in g['cars']) and p['coche'] not in (g.get('uso') or {}).values():
                        server.garage.command({'action':'usar','slot':i,'id':p['coche']})
                except Exception:pass
            cambio_parrilla=True;res={'saved':pid,'slot':i}
        elif a=='levantar':
            i=payload.get('slot')
            if not (type(i)==int and 0<=i<6):raise E('Lugar inválido.')
            if d['slots'][i] and _ocupado(server) and any(x['slot']==i for x in (server.live.session or {}).get('pilots') or []):
                raise E('%s está en la sesión en curso. Termínala antes.'%d['slots'][i]['name'],409)
            _levantar(server,d,i);cambio_parrilla=True;res={'ok':True}
        else:raise E('Acción desconocida.')
        if cambio_parrilla:d['version']+=1;server.store.write(d)
        for av in tirar:borrar_avatar(server,av)
    return dict(vista_pilotos(server),**res)
def revisar_niveles(server):
    """Al terminar una Práctica/Carrera o cada parte del Gran Premio/torneo: con la mejor vuelta REAL (sin handicap)
    de cada piloto y la clase de su coche, sugiere (o cambia, en modo «Cambiar solo») su nivel. Cada sesión una vez."""
    if not NIVEL_LOCK.acquire(blocking=False):return
    try:
        # 🏆 Ranking: siempre (aunque el nivel automático esté apagado). Mejor vuelta REAL, sin ningún hándicap.
        try:
            rk=getattr(server,'ranking',None)
            if rk is not None:
                for clave,fuente,rows in _sesiones_terminadas(server):
                    if not rk.ya(clave):rk.registrar(clave,fuente,rows)
        except Exception:traceback.print_exc()
        h=server.lap_config.handicap()
        if not h or h.get('nivel_auto','sugerir')=='apagado':return
        hechos=server.niveles_hechos
        nuevas=[x for x in _sesiones_terminadas(server) if x[0] not in hechos]
        if not nuevas:return
        ahora=time.time()
        with LOCK:
            d=server.store.read();ins=server.inscritos.read()['pilotos']
            antes_d=json.dumps(d['slots'],sort_keys=True);antes_i=json.dumps(ins,sort_keys=True)
            for clave,fuente,rows in nuevas:
                for name,clase,best,n in rows:
                    nm=name.casefold()
                    for p in [x for x in d['slots'] if x]+ins:
                        if p['name'].casefold()==nm:handicap_mod.aplicar_nivel(p,h,clase,best,n,fuente,ahora)
                    try:server.registro.aplicar_nivel(h,name,clase,best,n,fuente,ahora)
                    except Exception:traceback.print_exc()
                hechos.append(clave)
            try:server.registro.save()
            except OSError:pass
            if json.dumps(d['slots'],sort_keys=True)!=antes_d:d['version']+=1;server.store.write(d)
            if json.dumps(ins,sort_keys=True)!=antes_i:server.inscritos.write({'pilotos':ins})
        del hechos[:-200]
        try:durable.escribir_json(server.niveles_path,{'hechos':hechos},backup=False)
        except OSError:pass
    except Exception:
        traceback.print_exc()
    finally:
        NIVEL_LOCK.release()

def vista_ranking(server):
    """Ranking por clase con tiempos REALES (sin hándicap) + nivel actual de cada piloto (registro o torneo)."""
    with LOCK:d=server.store.read();ins=server.inscritos.read()['pilotos']
    niveles={}
    for p in ins:niveles[p['name'].casefold()]=(p.get('nivel'),'torneo')
    for p in d['slots']:
        if p:niveles[p['name'].casefold()]=(p.get('nivel'),'registro')
    v=server.ranking.view(server.lap_config.handicap(),niveles)
    v['por_piloto']={k:server.ranking.mejores(k) for k in niveles}
    return v
def gp_busy(gp):
    run=gp.current()
    return bool(run and run['phase'] in ('countdown','running','finishing','red'))

def _ocupado_juego(server):
    live=server.live
    with live.lock:s=live.session;return bool(s and s.get('juego') and s.get('phase')!='ended')
def live_sim_phase(live,lap_config):
    """Simulador: (fase, coches) de la Práctica/Carrera. En el semáforo de una ronda de juego también (salida en falso de prueba)."""
    with live.lock:
        s=live.session
        if s and s.get('juego') and s['phase']=='countdown' and not s.get('red_flag') and s.get('lap_source') in ('scx','both'):
            slots=[p['slot'] for p in s['pilots']];cars=lap_config.read()['cars'];return 'countdown',[cars[i]-1 for i in slots]
    cars=live_sim_cars(live,lap_config)
    return ('running',cars) if cars else (None,[])
def live_sim_cars(live,lap_config):
    """Simulador: coches de la Práctica/Carrera en curso que cuenta la tarjeta SCX (0 a 5)."""
    with live.lock:
        s=live.session
        if not s or s['phase']!='running' or s.get('red_flag') or s.get('lap_source') not in ('scx','both') or s.get('simulated'):return []
        slots=[p['slot'] for p in s['pilots']]
    cars=lap_config.read()['cars']
    return [cars[i]-1 for i in slots]

# Lo que Práctica/Carrera toman de la configuración del Gran Premio: agujas, semáforo y sonido.
DASH_KEYS=('speed_max_kmh','fuel_red_pct','fuel_enabled','track_length_m','scale','lights_seconds','sound_enabled','sound_volume','tire_name','tire_red_pct')

def wire(server):
    """Conecta el lector SCX compartido con Práctica/Carrera y el Gran Premio."""
    live,gp,scx=server.live,server.gp,server.scx
    scx.add_finish_listener(live.on_scx_finish);live.scx=scx
    live.gp_busy=lambda:gp_busy(gp)
    live.track=lambda:(float(gp.config.get('track_length_m',25.0)),int(gp.config.get('scale',32)))
    scx.gatillo.track=live.track   # factor de fábrica del velocímetro en vivo con el largo y la escala de la pista
    live.dashboard=lambda:{k:gp.config.get(k,GP_DEFAULTS[k]) for k in DASH_KEYS}
    # Vuelta mínima válida: una sola (data/vueltas.json) para Práctica, Carrera, Gran Premio y Mi coche.
    gp.min_lap=server.lap_config.min_lap
    gp.set_min_lap=lambda v:server.lap_config.write({'min_lap_s':v})
    # Handicap (ajuste de tiempo por vuelta por clase de coche): también en data/vueltas.json, uno para todo.
    # + Garage: el coche va con el PILOTO (no con el mando): su clase y su hándicap propio (data/garage.json «uso»).
    def hc_live():
        g=server.garage.read();return handicap_mod.con_pilotos(server.lap_config.handicap(),garage_mod.entradas(g,g.get('uso'),range(6)))
    live.current_handicap=hc_live;gp.handicap_actual=server.lap_config.handicap
    gp.garage_read=server.garage.read
    server.exigir_coche=True   # cada piloto que corre lleva coche del Garage (las pruebas viejas de vueltas lo apagan)
    def falta_coche(ids,roster):
        if not getattr(server,'exigir_coche',True):return None
        g=server.garage.read();q=garage_mod.faltan(g,g.get('uso'),ids,{str(i):(roster['slots'][i] or {}).get('name') for i in ids})
        return garage_mod.aviso_faltan(q) if q else None
    live.falta_coche=falta_coche
    # ⚑/🍻 Modos de juego: configuración y cuentas (data/juego.json); salida en falso con el mismo umbral del GP.
    live.juego_store=server.juego
    live.falso_throttle=lambda:gp.config.get('false_start_throttle',GP_DEFAULTS.get('false_start_throttle',2))
    # Bandera amarilla del piloto: triple clic del botón de cambio de carril (la tarjeta SCX solo se escucha).
    # Una sola configuración (Gran Premio → Configuración) para GP, Práctica y Carrera.
    flag_cfg=lambda:gp_flag_config(gp.gp['config'] if gp.gp and gp.gp.get('status')=='active' else gp.config)
    scx.gatillo.flag_cfg=flag_cfg;live.flag_config=flag_cfg
    def on_pilot_flag(car,t):
        # Mientras corre una parte del GP la bandera es del GP; si no, de la Práctica/Carrera en curso.
        if gp_busy(gp):gp.on_pilot_flag(car,t)
        else:live.on_pilot_flag(car+1,t)
    scx.add_flag_listener(on_pilot_flag)
    # Tiempo en pits: la entrada sale de la trama EE (F0); la salida se estima. Mientras corre el GP, es del GP.
    def on_pit(ev):
        if gp_busy(gp):gp.on_pit(ev)
        else:live.on_pit(ev)
    scx.add_pit_listener(on_pit)
    live.rehydrate_pits();gp.rehydrate_pits()
    if scx.sim:
        def follow():
            phase,cars=gp.sim_follow()
            if phase in ('countdown','running','finishing'):return phase,cars
            ph,cars=live_sim_phase(live,server.lap_config)
            return (ph,cars) if cars else (phase,[])
        scx.sim.follow=follow

def build_server(host,port,data,esp32_url,scx_port=None,scx_baud=57600,simulate=False,avisos=None,esp32_usb='auto',min_lap_s=None):
    server=ThreadingHTTPServer((host,port),Handler)
    try:
        server.daemon_threads=True
        # Avisos de arranque (archivos recuperados, configuración rara…): se muestran en la app en español.
        server.avisos=list(avisos or []);server.boot=uuid.uuid4().hex;server.started_at=time.time()
        durable.limpiar_temporales(data)
        server.store=Store(data,server.avisos)
        # Vuelta mínima de config.json ("min_lap_s"): la de fábrica si la app no tiene otra guardada.
        try:server.lap_config=LapConfig(data,min_lap_s)
        except ValueError:
            server.avisos.append('"min_lap_s" de config.json no es válido (debe ser de 0.5 a 60 segundos); se usó 10 s.');server.lap_config=LapConfig(data)
        if server.lap_config.aviso:server.avisos.append(server.lap_config.aviso)
        server.live=Live(data,esp32_url,server.lap_config)
        server.avisos.extend(server.live.avisos)
        # UN SOLO lector SCX (solo lectura) para todo: Gran Premio y Práctica/Carrera.
        server.scx=SCX(port=scx_port,baud=scx_baud,simulate=simulate)
        server.gp=GrandPrix(data,server.scx,server.live)
        # 🏎️ Garage: coches físicos con su ficha y su propio hándicap (data/garage.json + data/garage-fotos/).
        server.garage=garage_mod.Garage(Path(data),server.avisos)
        # 🏆 Ranking de pilotos por clase (tiempos reales, sin hándicap): data/ranking.json.
        server.ranking=ranking_mod.Ranking(Path(data),server.avisos)
        # Torneo por mangas: pilotos inscritos con su nivel (data/inscritos.json).
        server.inscritos=torneo_mod.Inscritos(Path(data));server.avisos.extend(server.inscritos.avisos)
        # Nivel automático por tiempo: sesiones ya revisadas (para no sugerir dos veces lo mismo).
        server.niveles_path=Path(data)/'niveles_revisados.json'
        nh,_=durable.leer_json(server.niveles_path,validate=lambda x:x if isinstance(x,dict) and isinstance(x.get('hechos'),list) else (_ for _ in ()).throw(ValueError('x')),nombre='niveles_revisados.json')
        server.niveles_hechos=[str(k) for k in (nh or {}).get('hechos',[])][-200:]
        # 👥 Registro de pilotos: nace con todos los pilotos que ya había (parrilla, torneo y ranking). Nada se borra.
        server.registro=pilotos_mod.Registro(Path(data),server.avisos)
        # ⚑ Puto el último / 🍻 Las chelas: configuración, veces Puto y cuenta de la noche (data/juego.json).
        server.juego=juego_mod.JuegoStore(Path(data),server.avisos)
        d=server.store.read()
        if server.registro.migrar(d['slots'],server.inscritos.read()['pilotos'],server.ranking.nombres()):d['version']+=1;server.store.write(d)
        # ESP32 del sensor por cable USB (solo lectura, solo para la 💥 explosión al instante). Nunca la tarjeta SCX.
        usb_off=simulate or (isinstance(esp32_usb,str) and esp32_usb.strip().lower() in USB_OFF) or esp32_usb is False
        usb_port=None if usb_off or esp32_usb in (None,True) or str(esp32_usb).strip().lower()=='auto' else str(esp32_usb)
        server.esp32_usb=Esp32Usb(on_cross=server.live.on_usb_cross,port=usb_port,exclude=[scx_port],enabled=not usb_off)
        server.live.usb=server.esp32_usb
        server.avisos.extend(server.gp.avisos)
        for part in (server.live,server.gp):part.boot=server.boot;part.avisos_servidor=server.avisos
    except BaseException:
        server.server_close();raise
    wire(server)
    for a in server.avisos:print('AVISO: '+a,flush=True)
    return server

def close_server(server):
    usb=getattr(server,'esp32_usb',None)
    if usb is not None:usb.close()
    server.gp.close();server.scx.close();server.live.close();server.server_close()

# ---------- arranque desde la terminal o el LaunchAgent de macOS ----------
DEFAULT_ESP32='http://172.16.2.55'

def valid_esp32_url(u):
    if not isinstance(u,str):return False
    url=urlsplit(u)
    try:url.port
    except ValueError:return False
    return url.scheme=='http' and bool(url.hostname) and not url.username and not url.password

def load_config(path,avisos):
    """config.json dañado o vacío: no tumbar el servidor; se usan valores de fábrica y se avisa."""
    if not path.exists():return {}
    try:
        d=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(d,dict):raise ValueError('no es un objeto')
        return d
    except (OSError,ValueError):
        avisos.append('config.json está dañado; se usaron valores de fábrica. Revisa la dirección del sensor (ESP32).')
        return None

def save_esp32_url(path,config,url,avisos):
    """Recordar la última dirección buena de la ESP32 en config.json (el siguiente arranque automático la usa)."""
    if config is not None and config.get('esp32_url')==url:return
    try:
        if config is None and path.exists():durable.apartar(path)
        d=dict(config or {});d['esp32_url']=url
        durable.escribir_json(path,d,indent=2)
    except OSError as e:
        avisos.append('No se pudo guardar la dirección del sensor en config.json (%s).'%type(e).__name__)

def say(msg):print(msg,flush=True)

def main(argv=None):
    ap=argparse.ArgumentParser(description='Puto el último: servidor de la pista');ap.add_argument('--port',type=int,default=8080);ap.add_argument('--host',default='0.0.0.0');ap.add_argument('--data',default=str(ROOT/'data'))
    ap.add_argument('--config',default=str(ROOT/'config.json'),help=argparse.SUPPRESS)
    ap.add_argument('--esp32-url',default=None,help='Dirección del sensor IR. Se recuerda en config.json para el próximo arranque.')
    ap.add_argument('--scx-port',default=None);ap.add_argument('--scx-baud',type=int,default=None)
    ap.add_argument('--simular-scx',action='store_true',help='Pista simulada para probar sin tarjeta SCX')
    ap.add_argument('--esp32-usb',default=None,help='Cable USB de la ESP32 para la explosión: auto (de fábrica), off, o /dev/cu.usbmodemXXXX. Solo lectura.')
    ap.add_argument('--esperar',action='store_true',help='Si ya hay otro servidor, esperar a que se cierre en vez de salir (arranque automático).')
    args=ap.parse_args(argv)
    avisos=[];config_path=Path(args.config)
    config=load_config(config_path,avisos);cfg=config or {}
    # Prioridad: --esp32-url > SLOTRACE_ESP32_URL > config.json > fábrica.
    chosen=args.esp32_url or os.environ.get('SLOTRACE_ESP32_URL')
    if chosen is not None and not valid_esp32_url(chosen):ap.error('La URL de la ESP32 debe ser http://IP sin credenciales')
    if chosen is None:
        chosen=cfg.get('esp32_url',DEFAULT_ESP32)
        if not valid_esp32_url(chosen):
            avisos.append('La dirección del sensor en config.json no es válida; se usó %s. Arranca con --esp32-url http://IP para corregirla.'%DEFAULT_ESP32);chosen=DEFAULT_ESP32
    # Tarjeta SCX (solo lectura). Si no se indica, se busca /dev/cu.usbserial-* automáticamente.
    scx_port=args.scx_port or os.environ.get('SLOTRACE_SCX_PORT') or next((cfg[k] for k in ['scx_port','scx_serial','serial_port','scx_device'] if isinstance(cfg.get(k),str) and cfg.get(k)),None)
    try:scx_baud=args.scx_baud or int(cfg.get('scx_baud',57600))
    except (TypeError,ValueError):scx_baud=57600
    esp32_usb=args.esp32_usb or os.environ.get('SLOTRACE_ESP32_USB') or cfg.get('esp32_usb_port')
    if esp32_usb is None and cfg.get('esp32_usb') is False:esp32_usb='off'
    if not isinstance(esp32_usb,str) or not esp32_usb.strip():esp32_usb='auto'
    try:lock=InstanceLock(args.data)
    except PermissionError:
        say('ERROR: macOS no deja abrir la carpeta de datos (%s). Da permiso a python3 / Terminal para la carpeta Documentos (ver INSTALAR.txt).'%args.data)
        if args.esperar:time.sleep(30)
        return 5
    if not lock.acquire():
        if not args.esperar:
            say('Ya hay un servidor de Puto el último corriendo con estos datos. No se abrió otro. (Usa Detener antes de arrancarlo a mano.)');return 3
        say('Ya hay otro servidor de Puto el último corriendo. Espero a que se cierre para tomar su lugar…')
        lock.acquire(wait=True)
    if args.esp32_url and not args.simular_scx:save_esp32_url(config_path,config,chosen,avisos)
    waited=False
    while True:
        try:
            server=build_server(args.host,args.port,args.data,chosen,scx_port,scx_baud,args.simular_scx,avisos,esp32_usb,cfg.get('min_lap_s'));break
        except OSError as e:
            if e.errno!=errno.EADDRINUSE:raise
            if not args.esperar:
                say('ERROR: el puerto %d ya está ocupado (¿quedó abierta una versión anterior con nohup?). Usa «Detener Puto el último» y vuelve a intentar.'%args.port);return 4
            if not waited:say('El puerto %d está ocupado por otro programa. Reintento cada 5 segundos…'%args.port);waited=True
            time.sleep(5)
    def stop(signum,frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop)
    try:signal.signal(signal.SIGHUP,stop)
    except (AttributeError,ValueError):pass
    say('Tarjeta SCX: '+('SIMULADOR' if args.simular_scx else (scx_port or 'búsqueda automática /dev/cu.usbserial-*'))+' · solo lectura')
    say('Sensor ESP32: '+chosen)
    say('ESP32 por USB (explosión): '+('apagado' if not server.esp32_usb.enabled else (server.esp32_usb.port or 'búsqueda automática /dev/cu.usbmodem*'))+' · solo lectura')
    say('Puto el último: http://localhost:%s/ | archivos: %s | pid %d' % (args.port,server.store.directory,os.getpid()))
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        say('Cerrando Puto el último: guardando sesión…');close_server(server);say('Servidor detenido.')
    return 0

if __name__=='__main__':
    sys.exit(main())
