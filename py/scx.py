"""Tarjeta SCX Digital -> PC (amarilla). SOLO LECTURA.

Este módulo NUNCA escribe bytes al puerto serial: abre el puerto con O_RDONLY
y no tiene ninguna llamada de escritura. Sin dependencias (termios de Python).

Trama de la tarjeta (SEB): 55 CMD D0 D1 D2 D3 D4 D5 CRC 05  (10 bytes, 57600 8N1)
Fuente del protocolo del bus: slotbaer.de, páginas 19 y 20 (SCX-Digital Daten-Protokoll).
  FF = mandos (R0..R5: AA = sin mando; bits 3..0 = gatillo 0..15)
  EE = cruce de meta (byte E7 en la posición del coche que cruzó).
       Los demás carriles conectados van en FE si fue por la pista, o en F0 si
       fue por el carril de pits (esa pasada también cuenta como vuelta).
       AA = sin mando. La salida de pits NO llega en una trama: se estima
       (combustible + gatillo) o, más adelante, con un sensor IR en la salida.
  D4 = tiempo de vuelta del Pit Box (FN RU1 RU0 VS Z1 Z0)
  D6 = combustible: S0S1 S2S3 S4S5 $14 $50 $AA (6 nibbles, nibble alto = id menor),
       nivel 8 = lleno ... 0 = vacío. $14 $50 = consumo activo, $00 $50 = inactivo.
El acomodo por byte de D6 en ESTA tarjeta no está confirmado en vivo: ver FUEL_LAYOUTS.

Un SOLO lector (clase SCX) abre el puerto y lo comparten el Gran Premio (add_listener)
y Práctica/Carrera (add_finish_listener -> live.on_scx_finish). Nunca abrir dos.
"""
import collections, copy, json, os, random, select, threading, time
from pathlib import Path
import durable
import handicap as handicap_mod
import gatillo as gatillo_mod
import pits as pits_mod
from pits import PitsTracker, classify_ee_crossing

MIN_LAP_S = 1.5             # anti-rebote: varios EE por cruce (~150 ms); se descartan sin registrar
MIN_VALID_LAP_S = 10.0      # vuelta mínima válida de fábrica: la vuelta real más rápida de la pista es de ~11 s
MIN_LAP_RANGE = (0.5, 60.0) # la vuelta mínima se puede cambiar en la app (data/vueltas.json)
LIVE_WINDOW_S = 3.0         # sin tramas por más de esto = sin datos de la pista
STALE_REOPEN_S = 20.0       # puerto abierto sin un solo byte por más de esto: cerrar y volver a abrir (Mac dormida, USB reenumerado)

class _PuertoMudo(Exception):
    pass

KNOWN_CMDS = {0xFF:'mandos',0xCC:'asignar',0xAA:'bus libre',0xEE:'meta',0xD3:'posiciones',0xD4:'tiempo vuelta',
              0xD5:'contador',0xDB:'qualy pitbox',0xD0:'reset',0xDD:'salida pitbox',0xDC:'fin pitbox',
              0xD6:'combustible',0xDE:'cambio pantalla',0xD7:'freno'}
FUEL_LAYOUTS = {
    # Según slotbaer.de: D0..D2 con 6 nibbles; nibble alto = coche con id menor.
    'nibbles': 'D0..D2, nibble alto primero (slotbaer.de)',
    # Por si la tarjeta lo entrega con el nibble bajo primero.
    'nibbles_bajo': 'D0..D2, nibble bajo primero',
    # Por si la tarjeta lo entrega un byte por coche (D0..D5).
    'bytes': 'D0..D5, un byte por coche',
}

def crc8(data, init=0x00, xor_out=0xBB):
    """CRC-8 polinomio $31 y XOR final $BB (slotbaer). El valor inicial no está documentado."""
    c = init
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x31) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c ^ xor_out

def guess_crc_init(frame):
    """Devuelve los valores iniciales de CRC que hacen válida la trama (para diagnóstico)."""
    body, crc = frame[:8], frame[8]
    return [i for i in range(256) if crc8(body, i) == crc]

def decode_fuel(payload, layout='nibbles'):
    """payload = D0..D5. Devuelve lista de 6 niveles (0..8) o None si no hay dato."""
    out = []
    if layout == 'bytes':
        for b in payload[:6]:
            out.append(b if 0 <= b <= 8 else None)  # AA u otro = sin dato
        return out
    for b in payload[:3]:
        hi, lo = b >> 4, b & 0x0F
        pair = (hi, lo) if layout != 'nibbles_bajo' else (lo, hi)
        out.extend(v if v <= 8 else None for v in pair)  # nibble A (de AA) = sin dato
    return out

def fuel_percent(level):
    if level is None: return None
    return int(100 * level / 8 + 0.5)   # 8→100, 4→50, 1→13, 0→0

def decode_throttle(payload):
    res = []
    for b in payload[:6]:
        if b == 0xAA: res.append(None)
        else: res.append({'speed': b & 0x0F, 'button': not (b & 0x10), 'light': not (b & 0x20)})
    return res

def decode_d4(payload):
    fn, ru1, ru0, vs, z1, z0 = payload[:6]
    base = 256 * z1 + z0 + (256 if vs & 0x08 else 0)
    return {'car': fn & 0x07, 'lap': 256 * ru1 + ru0 + (vs & 1), 'seconds': round(base * 0.01024, 3)}

def mono_ms():
    return time.monotonic() * 1000.0

class FinishDebouncer:
    """Un cruce produce varias tramas EE seguidas: solo la primera cuenta (por coche)."""
    def __init__(self, min_lap_s=MIN_LAP_S):
        self.min_ms = min_lap_s * 1000.0; self.last = {}
    def accept(self, car, t_ms):
        prev = self.last.get(car)
        if prev is not None and t_ms - prev < self.min_ms:
            return False
        self.last[car] = t_ms
        return True

class LapConfig:
    """Práctica/Carrera: con qué se cuentan las vueltas, coche/mando (1-6) de cada lugar de piloto y la
    vuelta mínima válida (segundos; igual para Práctica, Carrera, Gran Premio y Mi coche).
    Se guarda en data/vueltas.json (igual que la versión anterior de la Mac).
    Vuelta mínima: si se cambió en la app queda en vueltas.json; si no, se usa "min_lap_s" de config.json
    (default_min) y, si tampoco está, el valor de fábrica (10 s). Un vueltas.json viejo no necesita cambios."""
    SOURCES = ('auto', 'scx', 'ir', 'both')
    def __init__(self, directory, default_min=None):
        self.path = Path(directory) / 'vueltas.json'; self.lock = threading.Lock()
        self.default_min = self.valid_min(default_min) if default_min is not None else MIN_VALID_LAP_S
        self.data = {'source': 'auto', 'cars': [1, 2, 3, 4, 5, 6]}
        d, self.aviso = durable.leer_json(self.path, validate=self.validate, nombre='vueltas.json (cómo se cuentan las vueltas)')
        if d is not None: self.data = d
    @staticmethod
    def valid_min(m):
        if type(m) == bool or not isinstance(m, (int, float)) or m != m or not MIN_LAP_RANGE[0] <= m <= MIN_LAP_RANGE[1]:
            raise ValueError('La vuelta mínima debe ser un número de segundos entre %g y %g.' % MIN_LAP_RANGE)
        return round(float(m), 2)
    @classmethod
    def validate(cls, d):
        if not isinstance(d, dict) or d.get('source') not in cls.SOURCES:
            raise ValueError('Elige cómo contar las vueltas.')
        cars = d.get('cars')
        if not isinstance(cars, list) or len(cars) != 6 or any(type(c) != int for c in cars) or sorted(cars) != [1, 2, 3, 4, 5, 6]:
            raise ValueError('Cada piloto necesita un coche distinto del 1 al 6.')
        out = {'source': d['source'], 'cars': list(cars)}
        if 'min_lap_s' in d: out['min_lap_s'] = cls.valid_min(d['min_lap_s'])
        if 'handicap' in d: out['handicap'] = handicap_mod.clean(d['handicap'])   # ajuste de tiempo por vuelta (por coche)
        return out
    def read(self):
        with self.lock:
            return {'source': self.data['source'], 'cars': list(self.data['cars']), 'min_lap_s': self.data.get('min_lap_s', self.default_min),
                    'handicap': copy.deepcopy(self.data.get('handicap') or handicap_mod.DEFAULT)}
    def handicap(self):
        """Handicap actual (clases por coche y segundos por clase). Un vueltas.json viejo = valores de fábrica."""
        with self.lock:
            return copy.deepcopy(self.data.get('handicap') or handicap_mod.DEFAULT)
    def write(self, d):
        # Se puede mandar solo una parte (p. ej. {'min_lap_s': 9.5} o {'handicap': {'clases': {'3': 'con_iman'}}}); lo demás se conserva.
        if not isinstance(d, dict): raise ValueError('Datos inválidos.')
        with self.lock: cur = dict(self.data, cars=list(self.data['cars']))
        if 'handicap' in d: d = dict(d, handicap=handicap_mod.clean(d['handicap'], cur.get('handicap') or handicap_mod.DEFAULT))
        d = self.validate(dict(cur, **d))
        with self.lock:
            durable.escribir_json(self.path, d, backup=True)   # archivo de datos, no el puerto
            self.data = d
        return self.read()
    def min_lap(self):
        with self.lock:
            return self.data.get('min_lap_s', self.default_min)
    def car_for_slot(self, slot):
        with self.lock:
            return self.data['cars'][slot] if 0 <= slot < 6 else None
    def slot_for_car(self, car):
        with self.lock:
            return self.data['cars'].index(car) if car in self.data['cars'] else None

class FrameParser:
    """Re-sincroniza solo: busca 55 + CMD conocido + terminador 05."""
    def __init__(self, on_frame, frame_len=10):
        self.buf = bytearray(); self.on_frame = on_frame; self.frame_len = frame_len
        self.dropped = 0; self.crc_bad = 0
    def feed(self, data, t=None):
        t = time.monotonic() if t is None else t
        self.buf += data
        n = self.frame_len
        while len(self.buf) >= n:
            if self.buf[0] == 0x55 and self.buf[1] in KNOWN_CMDS and (n == 9 or self.buf[9] == 0x05):
                frame = bytes(self.buf[:n]); del self.buf[:n]
                if n == 10 and crc8(frame[:8]) != frame[8]: self.crc_bad += 1   # solo diagnóstico
                self.on_frame(frame, t)
            else:
                del self.buf[0]; self.dropped += 1
        if len(self.buf) > 4096: del self.buf[:-n]

class SCX:
    """Estado compartido de la pista leído de la tarjeta SCX."""
    def __init__(self, port=None, baud=57600, fuel_layout='nibbles', frame_len=10, simulate=False, start=True, on_finish=None):
        self.port = port; self.baud = baud; self.fuel_layout = fuel_layout if fuel_layout in FUEL_LAYOUTS else 'nibbles'
        self.lock = threading.RLock(); self.stop_event = threading.Event()
        self.parser = FrameParser(self._frame, frame_len)
        self.listeners = []
        self.connected = False; self.error = 'Buscando tarjeta SCX…'; self.port_in_use = None
        self.last_frame_at = None; self.counts = collections.Counter()
        self.raw = collections.deque(maxlen=40); self.raw_d6 = collections.deque(maxlen=30)
        self.events = collections.deque(maxlen=30); self.d4 = collections.deque(maxlen=20)
        self.fuel_payload = None; self.fuel_at = None; self.fuel_consumo = None
        self.throttle = [None] * 6; self.throttle_at = None
        # Velocímetro en vivo y «pide cambio» de carril (gatillo.py, solo cálculo).
        self.gatillo = gatillo_mod.Gatillo()
        self.last_cross = [0.0] * 6; self.dedupe_s = 0.8
        # Cruces para Práctica/Carrera (formato de la versión anterior de la Mac): 1 por coche cada >= 1.5 s.
        self.debounce = FinishDebouncer(); self.finish_events = collections.deque(maxlen=500); self.seq = 0
        self.finish_listeners = [on_finish] if on_finish else []
        # Bandera amarilla del piloto (triple clic en el botón de cambio de carril): fn(coche_0a5, t).
        self.flag_listeners = []
        # Entrada/salida de pits (pits.py). La entrada sale de la trama EE (F0); la salida se estima.
        self.pits = PitsTracker()
        self.pit_listeners = []
        self.port_open = False; self.reopens = 0; self.stale_reopen_s = STALE_REOPEN_S
        self.simulate = simulate; self.sim = None
        if simulate:
            self.sim = Simulator(self); self.port_in_use = 'SIMULADOR'; self.port_open = True
            self.thread = threading.Thread(target=self.sim.loop, name='scx-sim', daemon=True)
        else:
            self.thread = threading.Thread(target=self._serial_loop, name='scx-reader', daemon=True)
        if start: self.thread.start()
        else: self.thread = None
    # --- recepción ---
    def _frame(self, frame, t, simulated=False):
        cmd = frame[1]; payload = frame[2:8]; accepted = []; flags = []; pit_evs = []
        with self.lock:
            if not simulated: self.last_frame_at = t; self.counts[cmd] += 1
            entry = {'t': round(time.time(), 3), 'hex': frame.hex(' ').upper(), 'cmd': KNOWN_CMDS.get(cmd, '?')}
            if cmd != 0xFF: self.raw.append(entry)  # FF llega cada 100 ms; no llenar el log con eso
            if cmd == 0xD6:
                self.fuel_payload = bytes(payload); self.fuel_at = t
                self.fuel_consumo = None if (payload[3] == 0xFF or self.fuel_layout == 'bytes') else payload[3] != 0x00
                self.raw_d6.append(entry)
                pit_evs = self.pits.on_fuel(decode_fuel(self.fuel_payload, self.fuel_layout), t)
            elif cmd == 0xFF:
                self.throttle = decode_throttle(payload); self.throttle_at = t
                flags = self.gatillo.feed(self.throttle, t) or []
                flag_listeners = list(self.flag_listeners) if flags else []
                pit_evs = self.pits.on_throttle(self.throttle, t)
            elif cmd == 0xD4:
                self.d4.append(dict(decode_d4(payload), t=entry['t']))
            elif cmd == 0xEE:
                lane = classify_ee_crossing(payload)
                cars = [i for i, b in enumerate(payload) if b == 0xE7]
                fresh = [c for c in cars if t - self.last_cross[c] > self.dedupe_s]  # cada EE llega 2 veces
                for c in fresh: self.last_cross[c] = t
                if fresh: self.events.append({'t': entry['t'], 'cars': [c + 1 for c in fresh], 'lane': lane})
                listeners = list(self.listeners)
                levels = decode_fuel(self.fuel_payload, self.fuel_layout) if self.fuel_payload is not None else [None] * 6
                for c in cars:
                    if self.debounce.accept(c + 1, t * 1000.0):
                        self.seq += 1
                        ev = {'seq': self.seq, 'car': c + 1, 't_ms': round(t * 1000.0, 1), 'hora_ms': int(time.time() * 1000), 'simulado': simulated, 'lane': lane}
                        self.finish_events.append(ev); accepted.append(ev)
                        if lane == 'pit':
                            pit_evs += self.pits.on_entry(c, t, fuel=levels[c] if c < len(levels) else None)
                        else:
                            pit_evs += self.pits.on_track_cross(c, t)
                finish_listeners = list(self.finish_listeners)
            else: fresh = []
            pit_listeners = list(self.pit_listeners) if pit_evs else []
        # Fuera del candado del lector para no cruzar bloqueos con el GP o la sesión.
        for car, ft in flags:
            for fn in flag_listeners:
                try: fn(car, ft)
                except Exception as e: print('Error SCX→bandera: ' + type(e).__name__, flush=True)
        if cmd == 0xEE:
            for c in fresh:
                for fn in listeners:
                    try: fn('cross', c, t)
                    except Exception as e: print('Error SCX→GP: ' + type(e).__name__, flush=True)
            for ev in accepted:
                for fn in finish_listeners:
                    try: fn(dict(ev))
                    except Exception as e: print('Error SCX→sesión: ' + type(e).__name__, flush=True)
        for ev in pit_evs:
            for fn in pit_listeners:
                try: fn(dict(ev))
                except Exception as e: print('Error SCX→pits: ' + type(e).__name__, flush=True)
        return accepted
    def add_listener(self, fn):
        """Gran Premio: fn('cross', coche_0a5, t_segundos)."""
        with self.lock: self.listeners.append(fn)
    def add_flag_listener(self, fn):
        """Bandera amarilla del piloto: fn(coche_0a5, t_segundos) al completar el triple clic (solo se escucha la tarjeta)."""
        with self.lock: self.flag_listeners.append(fn)
    def add_finish_listener(self, fn):
        """Práctica/Carrera: fn({'seq','car' 1-6,'t_ms','hora_ms','simulado','lane'})."""
        with self.lock: self.finish_listeners.append(fn)
    def add_pit_listener(self, fn):
        """Entrada/salida de pits: fn(ev) con kind 'entry'|'exit' y coche 1-6. Solo escucha."""
        with self.lock: self.pit_listeners.append(fn)
    def mark_pit_exit(self, car, t=None, source='ir'):
        """Gancho para un sensor IR en la salida de pits (ESP32). Coche 1-6. No toca el puerto."""
        if type(car) != int or not 1 <= car <= 6:
            raise ValueError('Coche inválido (1 a 6).')
        evs = self.pits.mark_exit(car - 1, None if t is None else t, source=source)
        with self.lock: listeners = list(self.pit_listeners)
        for ev in evs:
            for fn in listeners:
                try: fn(dict(ev))
                except Exception as e: print('Error SCX→pits: ' + type(e).__name__, flush=True)
        return evs
    def pits_view(self):
        return self.pits.view()
    def feed(self, data, now_ms=None):
        """Pasa bytes crudos por el mismo parser (pruebas). No toca el puerto."""
        self.parser.feed(data, None if now_ms is None else now_ms / 1000.0)
    def inject_finish(self, car, now_ms=None, lane='track'):
        """Gancho de prueba: simula un cruce SIN tocar el puerto serial ni marcar la tarjeta como conectada.
        lane='pit' arma la trama con F0 (entrada a pits); 'track' deja AA en los demás (pista)."""
        if type(car) != int or not 1 <= car <= 6:
            raise ValueError('Coche inválido (1 a 6).')
        if lane not in ('track', 'pit'):
            raise ValueError('lane debe ser track o pit.')
        t = time.monotonic() if now_ms is None else now_ms / 1000.0
        other = 0xF0 if lane == 'pit' else 0xAA
        frame = build_frame(0xEE, [0xE7 if i == car - 1 else other for i in range(6)])
        return self._frame(frame, t, simulated=True)
    # --- serial solo lectura ---
    def _candidates(self):
        if self.port and os.path.exists(self.port): return [self.port]
        # Puerto fijo que ya no existe (al reconectar el USB macOS a veces le cambia el número): buscar solo.
        try: names = sorted(os.listdir('/dev'))
        except OSError: names = []
        found = ['/dev/' + n for n in names if n.startswith('cu.usbserial') or n.startswith('ttyUSB')]
        if self.port and not found: return [self.port]   # para que el aviso diga cuál falta
        return found
    def _open(self, path):
        import termios
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            excl = getattr(termios, 'TIOCEXCL', None)
            if excl is not None:
                import fcntl
                try: fcntl.ioctl(fd, excl)        # acceso exclusivo: no es escritura de datos
                except OSError: pass
            attrs = termios.tcgetattr(fd)
            speed = getattr(termios, 'B%d' % self.baud)
            attrs[0] = 0                                   # iflag: crudo
            attrs[1] = 0                                   # oflag
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # 8N1, ignora líneas de módem
            attrs[3] = 0                                   # lflag: sin eco ni modo canónico
            attrs[4] = speed; attrs[5] = speed
            attrs[6][termios.VMIN] = 0; attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception:
            os.close(fd); raise
        return fd
    def _release(self, fd):
        # Quitar el modo exclusivo (TIOCNXCL, no es escritura de datos) antes de cerrar, para poder reabrir en seguida.
        try:
            import termios, fcntl
            nx = getattr(termios, 'TIOCNXCL', None)
            if nx is not None: fcntl.ioctl(fd, nx)
        except (OSError, ImportError): pass
        try: os.close(fd)
        except OSError: pass
    def _serial_loop(self):
        while not self.stop_event.is_set():
            ports = self._candidates()
            if not ports:
                with self.lock: self.connected = False; self.port_open = False; self.error = 'No se encontró la tarjeta SCX (USB).'; self.port_in_use = None
                self.stop_event.wait(2); continue
            path = ports[0]
            try: fd = self._open(path)
            except Exception as e:
                if getattr(e, 'errno', None) == 16:   # EBUSY: la tiene otro programa en modo exclusivo
                    msg = 'La tarjeta SCX (%s) está ocupada por otro programa. Ciérralo, o desconecta y vuelve a conectar el USB.' % path
                else:
                    msg = 'No se pudo abrir %s (%s). ¿Otro programa la está usando?' % (path, type(e).__name__)
                with self.lock: self.connected = False; self.port_open = False; self.error = msg; self.port_in_use = path
                self.stop_event.wait(2); continue
            with self.lock: self.port_in_use = path; self.error = None; self.port_open = True
            last_rx = time.monotonic(); quick = False
            try:
                while not self.stop_event.is_set():
                    r, _, _ = select.select([fd], [], [], 0.5)
                    if r:
                        data = os.read(fd, 512)
                        if not data: raise OSError('puerto cerrado')
                        last_rx = time.monotonic()
                        self.parser.feed(data)
                    elif time.monotonic() - last_rx > self.stale_reopen_s:
                        raise _PuertoMudo()
                    with self.lock:
                        self.connected = self.last_frame_at is not None and time.monotonic() - self.last_frame_at < 3
                        if not self.connected: self.error = 'Puerto abierto, pero no llegan tramas SCX. ¿Pit Box encendida?'
                        else: self.error = None
            except _PuertoMudo:
                # Sin un solo byte: reabrir en seguida (solo lectura). Si la Pit Box está apagada no pasa nada.
                with self.lock: self.connected = False; self.reopens += 1; self.error = 'Sin datos de la tarjeta SCX; reabriendo el puerto…'
                quick = True
            except Exception as e:
                with self.lock: self.connected = False; self.port_open = False; self.error = 'Se desconectó la tarjeta SCX (%s).' % type(e).__name__
            finally:
                self._release(fd)
            if not quick: self.stop_event.wait(1)
    # --- consultas ---
    def fuel(self):
        with self.lock:
            if self.fuel_payload is None or time.monotonic() - self.fuel_at > 5: return [None] * 6
            return [fuel_percent(l) for l in decode_fuel(self.fuel_payload, self.fuel_layout)]
    def summary(self):
        with self.lock:
            fresh = self.last_frame_at is not None and time.monotonic() - self.last_frame_at < 3
            thr = self.throttle if self.throttle_at and time.monotonic() - self.throttle_at < 2 else [None] * 6
            return {'connected': fresh, 'error': None if fresh else (self.error or 'Sin tramas SCX'), 'port': self.port_in_use,
                    'simulated': self.simulate, 'fuel': self.fuel(), 'fuel_layout': self.fuel_layout, 'fuel_consumo': self.fuel_consumo,
                    'throttle': [None if x is None else x['speed'] for x in thr]}
    def gatillo_view(self):
        """/api/gatillo: km/h en vivo por gatillo y «pide cambio» por mando (None/False si no hay datos frescos)."""
        with self.lock: present = bool(self.port_open)
        return self.gatillo.view(connected=present)
    def throttle_now(self, car):
        with self.lock:
            if not self.throttle_at or time.monotonic() - self.throttle_at > 1: return None
            x = self.throttle[car]; return None if x is None else x['speed']
    def debug(self):
        with self.lock:
            s = self.summary()
            d6 = list(self.raw_d6)
            for e in d6:
                b = bytes.fromhex(e['hex'].replace(' ', ''))
                e['layouts'] = {k: [fuel_percent(v) for v in decode_fuel(b[2:8], k)] for k in FUEL_LAYOUTS}
                e['niveles'] = {k: decode_fuel(b[2:8], k) for k in FUEL_LAYOUTS}
            inits = collections.Counter()
            for e in list(self.raw)[-15:]:
                b = bytes.fromhex(e['hex'].replace(' ', ''))
                for i in guess_crc_init(b): inits[i] += 1
            s.update(counts={KNOWN_CMDS.get(k, hex(k)): v for k, v in self.counts.items()}, dropped_bytes=self.parser.dropped,
                     raw=list(self.raw)[::-1], raw_d6=d6[::-1], crossings=list(self.events)[::-1], d4=list(self.d4)[::-1],
                     layouts=FUEL_LAYOUTS, baud=self.baud, crc_init_guess=[{'init': '%02X' % k, 'frames': v} for k, v in inits.most_common(3)],
                     throttle_detail=self.throttle, pits=self.pits.view())
            return s
    # --- estado para Práctica/Carrera (mismo formato que la versión anterior de la Mac) ---
    def _state(self):
        now = time.monotonic()
        age = None if self.last_frame_at is None else now - self.last_frame_at
        live = self.port_open and age is not None and age < LIVE_WINDOW_S
        thr_fresh = self.throttle_at is not None and now - self.throttle_at < LIVE_WINDOW_S
        ctrls = [i + 1 for i, x in enumerate(self.throttle) if x is not None] if live and thr_fresh else []
        status = 'conectada' if live else 'sin_datos' if self.port_open else 'desconectada'
        return now, age, live, ctrls, status
    def brief(self):
        """Estado estable (sin edades) para el sondeo de la app."""
        with self.lock:
            _, _, live, ctrls, status = self._state()
            return {'connected': live, 'status': status, 'controllers': ctrls, 'simulated': self.simulate,
                    'fuel': self.fuel() if live else [None] * 6}
    def is_connected(self):
        return self.brief()['connected']
    def card_present(self):
        """Tarjeta enchufada (puerto abierto), aunque la Pit Box todavía no mande tramas."""
        with self.lock: return bool(self.port_open)
    def estado(self):
        with self.lock:
            now, age, live, ctrls, status = self._state()
            return {'connected': live, 'status': status, 'port': self.port_in_use or self.port, 'baud': self.baud,
                    'port_open': self.port_open, 'controllers': ctrls, 'simulated': self.simulate,
                    'last_packet_age_ms': None if age is None else round(age * 1000),
                    'now_t_ms': round(now * 1000, 1), 'packets': {KNOWN_CMDS.get(k, hex(k)): v for k, v in self.counts.items()},
                    'crc_bad': self.parser.crc_bad, 'dropped_bytes': self.parser.dropped, 'last_seq': self.seq, 'reopens': self.reopens,
                    'fuel': self.fuel(), 'fuel_layout': self.fuel_layout,
                    'error': None if live else (self.error or ('Sin datos de la pista. ¿Está prendida la Pit Box?' if self.port_open else 'Tarjeta SCX no conectada'))}
    def eventos(self, desde=0):
        with self.lock:
            return {'last_seq': self.seq, 'now_t_ms': round(mono_ms(), 1),
                    'events': [dict(e) for e in self.finish_events if e['seq'] > desde]}
    def set_layout(self, layout):
        if layout in FUEL_LAYOUTS:
            with self.lock: self.fuel_layout = layout
    def close(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread(): self.thread.join(timeout=3)

class ScxReader(SCX):
    """Compatibilidad con la versión anterior de la Mac: ScxReader(puerto, on_finish=..., start=...)."""
    def __init__(self, port=None, baud=57600, on_finish=None, start=True, **kw):
        super().__init__(port=port, baud=baud, start=start, on_finish=on_finish, **kw)

def build_frame(cmd, payload, init=0x00):
    body = bytes([0x55, cmd]) + bytes(payload)
    return body + bytes([crc8(body, init), 0x05])

class Simulator:
    """Genera BYTES de tarjeta SCX (mandos, combustible, cruces de meta) y los pasa por el mismo parser.
    En modo automático sigue al Gran Premio: los coches corren solo cuando la carrera está en marcha."""
    def __init__(self, scx):
        self.scx = scx; self.lock = threading.RLock(); self.running = set(); self.cars = {}
        self.fuel = [8] * 6; self.lap_counter = [0] * 6; self.base = [10.5, 10.8, 11.2, 11.6, 12.0, 12.5]   # >= 10.2 s: tiempos reales
        # Cruces fantasma (rebote del sensor, un dedo en la meta…) a media vuelta: apagados de fábrica; /api/sim {'ghosts': 0.2} los prende.
        self.ghost_rate = 0.0; self.ghosts = {}
        self.follow = None   # función que devuelve (fase, [coches]) del GP
        self.false_start_next = False; self.rng = random.Random(7)
        self.lap_len = {}; self.button_hold = {}
        # Entre apretones simulados al menos ~2 s: así el simulador nunca hace sin querer el triple clic de la bandera amarilla.
        self.button_cool = {}
        # Entrada a pits: siguiente cruce con F0, combustible subiendo y gatillo a 0 hasta salir.
        self.pit_next = set(); self.in_pit = {}
    def ee_payload(self, car, pit=False):
        """Trama EE como en la pista: E7 el que cruzó, FE (pista) o F0 (pits) en los demás conectados, AA si no hay mando."""
        marker = 0xF0 if pit else 0xFE
        with self.lock:
            connected = set(self.running) | {i for i in range(3)}
        return [0xE7 if i == car else (marker if i in connected else 0xAA) for i in range(6)]
    def request_pit(self, car):
        """Fuerza que el próximo cruce del coche (0..5) sea una entrada a pits (trama F0)."""
        if type(car) != int or not 0 <= car < 6:
            raise ValueError('Coche inválido (0 a 5).')
        now = time.monotonic()
        with self.lock:
            self.pit_next.add(car)
            if car in self.running and car not in self.in_pit:
                self.cars[car] = now + 0.15
    def trigger(self, c, now):
        """Gatillo realista (como el mando de Ernesto en vivo): a fondo 12 en las rectas, 4-6 en curvas, 0 al frenar;
        y de vez en cuando el botón de cambio de carril (~1 apretón cada 5 s, 3 tramas, con gatillo 5-6)."""
        with self.lock: pit = self.in_pit.get(c)
        if pit is not None:
            if pit.get('can_go'): return 8, False
            return 0, False
        lap = self.lap_len.get(c) or self.base[c]; due = self.cars.get(c, now)
        ph = min(1.0, max(0.0, 1.0 - (due - now) / lap))
        if 0.02 <= ph < 0.17 or 0.45 <= ph < 0.58: v = 12
        elif 0.17 <= ph < 0.20 or 0.58 <= ph < 0.61: v = 0
        else: v = self.rng.choice((4, 5, 5, 6))
        hold = self.button_hold.get(c, 0)
        if hold > 0: self.button_hold[c] = hold - 1; return self.rng.choice((5, 6)), True
        cool = self.button_cool.get(c, 0)
        if cool > 0: self.button_cool[c] = cool - 1
        if cool <= 0 and v != 12 and v != 0 and self.rng.random() < 0.02:
            self.button_hold[c] = 2; self.button_cool[c] = 20; return self.rng.choice((5, 6)), True
        return v, False
    def set_running(self, cars):
        now = time.monotonic()
        with self.lock:
            for c in cars:
                if c not in self.running:
                    self.running.add(c); self.cars[c] = now + self.rng.uniform(0.6, 2.0)   # primer cruce = salida
            for c in list(self.running):
                if c not in cars:
                    self.running.discard(c); self.cars.pop(c, None); self.ghosts.pop(c, None)
                    self.pit_next.discard(c); self.in_pit.pop(c, None)
    def loop(self):
        next_ff = next_d6 = 0; feed = self.scx.parser.feed; fs_car = None
        while not self.scx.stop_event.is_set():
            now = time.monotonic()
            if self.follow:
                phase, cars = self.follow()
                if phase == 'countdown' and self.false_start_next and cars: fs_car = cars[0]; self.false_start_next = False
                if phase != 'countdown': fs_car = None
                self.set_running(cars if phase in ('running', 'finishing') else [])
            out = b''
            if now >= next_ff:
                with self.lock: run = set(self.running)
                pay = []
                for c in range(6):
                    if c in run: v, pressed = self.trigger(c, now)
                    elif c >= 3 and c != fs_car: pay.append(0xAA); continue   # como en la pista: mandos 4-6 sin conectar (AA)
                    else: v, pressed = (12 if c == fs_car else 0), False
                    pay.append(0xE0 | (0 if pressed else 0x10) | v)   # bit 0x10 en 0 = botón de cambio de carril apretado
                out += build_frame(0xFF, pay); next_ff = now + 0.1
            with self.lock:
                # En pits: el combustible sube de 1 en 1 (~0.8 s), como en la pista; el gatillo sigue en 0 hasta llenar.
                for c, pit in list(self.in_pit.items()):
                    if self.fuel[c] < 8 and now >= pit.get('fuel_next', 0):
                        self.fuel[c] = min(8, self.fuel[c] + 1); pit['fuel_next'] = now + 0.8
                        if self.fuel[c] == 8: pit['full_at'] = now
                    if self.fuel[c] >= 8 and now - pit.get('full_at', pit.get('since', now)) >= 1.0:
                        pit['can_go'] = True
                        if 'go_at' not in pit: pit['go_at'] = now
                    if pit.get('can_go') and now - pit.get('go_at', now) >= 0.5:
                        lap = self.base[c] * self.rng.uniform(0.97, 1.06)
                        self.cars[c] = now + lap; self.lap_len[c] = lap
                        self.in_pit.pop(c, None)
            if now >= next_d6:
                f = self.fuel
                out += build_frame(0xD6, [(f[0] << 4) | f[1], (f[2] << 4) | f[3], (f[4] << 4) | f[5], 0x14, 0x50, 0xAA]); next_d6 = now + self.rng.uniform(0.4, 0.6)
            with self.lock:
                for c, due in list(self.cars.items()):
                    if now >= due and c not in self.in_pit:
                        pit = c in self.pit_next or self.fuel[c] == 0
                        self.pit_next.discard(c)
                        if pit:
                            # Entrada a pits: cruce con F0 (también cuenta vuelta). Combustible sube después; no hay trama de salida.
                            self.lap_counter[c] += 1
                            self.in_pit[c] = {'since': now, 'fuel_next': now + 1.0}
                            self.cars.pop(c, None)
                            pay = self.ee_payload(c, pit=True)
                            fr = build_frame(0xEE, pay); out += fr + fr
                            continue
                        lap = self.base[c] * self.rng.uniform(0.97, 1.06)
                        self.cars[c] = now + lap; self.lap_len[c] = lap; self.lap_counter[c] += 1
                        if self.ghost_rate and self.rng.random() < self.ghost_rate: self.ghosts[c] = now + self.rng.uniform(2.0, lap - 2.0)
                        if self.lap_counter[c] % 2 == 0: self.fuel[c] = max(0, self.fuel[c] - 1)
                        pay = self.ee_payload(c, pit=False)
                        fr = build_frame(0xEE, pay); out += fr + fr      # el Pit Box lo manda 2 veces
                        z = int(lap / 0.01024)
                        out += build_frame(0xD4, [c, 0, self.lap_counter[c] >> 1, self.lap_counter[c] & 1 | (8 if z > 0xFFFF else 0), (z >> 8) & 0xFF, z & 0xFF])
                for c, due in list(self.ghosts.items()):
                    if now >= due:
                        self.ghosts.pop(c, None); fr = build_frame(0xEE, self.ee_payload(c, pit=False)); out += fr + fr
            if out:
                if self.rng.random() < 0.05: out = b'\x13\x37' + out      # basura para probar re-sincronía
                feed(out)
            self.scx.stop_event.wait(0.02)
