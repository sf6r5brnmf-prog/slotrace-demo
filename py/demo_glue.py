"""DEMO sin Mac: corre el servidor REAL de «Puto el último» dentro del navegador (Pyodide).
- No hay hilos en el navegador: los bucles (simulador SCX, sondeo del sensor, reloj del GP) se llaman con tick().
- La tarjeta SCX es el Simulador de scx.py (bytes SCX reales por el mismo parser). Nunca hay puerto serial.
- El sensor IR (ESP32) es un sensor simulado en memoria con el mismo JSON que /datos del firmware."""
import io, json, random, sys, threading, time, traceback

import os as _os, shutil as _shutil
_os.umask(0o022)  # en Pyodide la umask viene en 0o777 y los archivos quedan sin permisos
if not hasattr(_os, 'link'):
    def _link(a, b): _shutil.copy2(a, b)
    _os.link = _link
for _n in ('fchmod', 'fsync', 'ftruncate'):
    if not hasattr(_os, _n): setattr(_os, _n, lambda *a, **k: None)
from email.message import Message

threading.Thread.start = lambda self: setattr(self, '_demo_started', True)   # no hay hilos: se usa tick()
threading.Thread.join = lambda self, timeout=None: None

import server as S, live as L, scx as X, gp as G

class _NoSocket:
    def __init__(self, addr, handler): self.server_address = addr
    def server_close(self): pass
S.ThreadingHTTPServer = _NoSocket

# ---------- sensor IR simulado (ESP32 /datos y /reiniciar) ----------
class FakeSensor:
    def __init__(self): self.rng = random.Random(); self.reset()
    def reset(self):
        self.data = {'estado': 'esperando salida', 'vueltas': 0, 'ultimo_s': 0, 'mejor_s': 0, 'promedio_s': 0, 'kmh': 0, 'kmh_escala': 0, 'laps': []}
        self.next_at = None; self.started = False
    def lap(self, s):
        d = self.data; n = d['vueltas'] + 1; k = round(25 / s * 3.6, 1)
        d.update(vueltas=n, estado='en pista', ultimo_s=round(s, 3), kmh=k, kmh_escala=round(k * 32))
        d['laps'].append({'n': n, 's': round(s, 3), 'kmh': k, 'escala': d['kmh_escala']}); d['laps'] = d['laps'][-40:]
        d['mejor_s'] = min(l['s'] for l in d['laps']); d['promedio_s'] = round(sum(l['s'] for l in d['laps']) / len(d['laps']), 3)
    def step(self, running):
        now = time.monotonic()
        if not running: self.next_at = None; return
        if self.next_at is None: self.next_at = now + (1.5 if not self.started else self.rng.uniform(10.6, 12.2)); return
        if now >= self.next_at:
            if not self.started: self.started = True; self.data['estado'] = 'en pista'
            else: self.lap(self.rng.uniform(10.6, 12.2))
            self.next_at = now + self.rng.uniform(10.6, 12.2)
SENSOR = FakeSensor()
def _fetch(self, path):
    if path == '/reiniciar': SENSOR.reset(); return b'ok'
    return json.dumps(SENSOR.data).encode()
L.Live.fetch = _fetch

srv = None
def set_speed(x):
    """Solo para pruebas (?x=N en el link): el reloj del servidor corre N veces más rápido."""
    x = float(x or 1)
    if x == 1: return
    rm, rw = time.monotonic, time.time; m0, w0 = rm(), rw()
    time.monotonic = lambda: m0 + (rm() - m0) * x
    time.time = lambda: w0 + (rw() - w0) * x
def demo_defaults():
    """Primera vez: un Gran Premio cortito para enseñarlo (se cambia en Configuración)."""
    srv.gp.set_config({'config': {'preset': 'personal', 'quali_minutes': 1, 'heats_rounds': 1, 'heats_minutes': 1.5, 'final_laps': 5, 'final_wait_s': 20,
                                  'torneo_minutes': 1, 'torneo_final_laps': 5}})
    # Handicap de ejemplo para enseñarlo: coche 2 con imán (+0.5 s por vuelta) y coche 4 modificado (+1 s). Se cambia en el menú.
    srv.lap_config.write({'handicap': {'enabled': True, 'clases': {'2': 'con_iman', '4': 'modificado'}}})
def _fix_modes(d):
    for root, dirs, files in _os.walk(d):
        for f in files:
            try: _os.chmod(_os.path.join(root, f), 0o644)
            except OSError: pass

def start(data_dir, speed=1):
    global srv
    _fix_modes(data_dir); set_speed(speed)
    srv = S.build_server('127.0.0.1', 0, data_dir, 'http://sensor-ir.demo', simulate=True, esp32_usb='off')
    sim = srv.scx.sim; sim.rng = random.Random()
    sim._next_ff = sim._next_d6 = 0; sim._fs_car = None
    srv.live._next_poll = 0
    return True

# ---------- una vuelta de cada bucle (copiados de scx.Simulator.loop, live.Live.loop y gp._loop) ----------
def _sim_step(self):
    now = time.monotonic(); feed = self.scx.parser.feed
    if self.follow:
        phase, cars = self.follow()
        if phase == 'countdown' and self.false_start_next and cars: self._fs_car = cars[0]; self.false_start_next = False
        # Torneo (solo DEMO): en cada manga los coches cambian de ritmo, para que no pierda siempre el mismo número de coche.
        if phase == 'countdown' and getattr(self, '_tq_phase', None) != 'countdown':
            try:
                if srv.gp.es_torneo(): self.base = [round(self.rng.uniform(10.4, 12.0), 2) for _ in range(6)]
            except Exception: pass
        self._tq_phase = phase
        if phase != 'countdown': self._fs_car = None
        self.set_running(cars if phase in ('running', 'finishing') else [])
    fs_car = self._fs_car; out = b''
    if now >= self._next_ff:
        with self.lock: run = set(self.running)
        pay = []
        for c in range(6):
            if c in run: v, pressed = self.trigger(c, now)
            elif c >= 3 and c != fs_car: pay.append(0xAA); continue
            else: v, pressed = (12 if c == fs_car else 0), False
            pay.append(0xE0 | (0 if pressed else 0x10) | v)
        out += X.build_frame(0xFF, pay); self._next_ff = now + 0.1
    with self.lock:
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
    if now >= self._next_d6:
        f = self.fuel
        out += X.build_frame(0xD6, [(f[0] << 4) | f[1], (f[2] << 4) | f[3], (f[4] << 4) | f[5], 0x14, 0x50, 0xAA]); self._next_d6 = now + self.rng.uniform(0.4, 0.6)
    with self.lock:
        for c, due in list(self.cars.items()):
            if now >= due and c not in self.in_pit:
                pit = c in self.pit_next or self.fuel[c] == 0
                self.pit_next.discard(c)
                if pit:
                    self.lap_counter[c] += 1
                    self.in_pit[c] = {'since': now, 'fuel_next': now + 1.0}
                    self.cars.pop(c, None)
                    fr = X.build_frame(0xEE, self.ee_payload(c, pit=True)); out += fr + fr
                    continue
                lap = self.base[c] * self.rng.uniform(0.97, 1.06)
                self.cars[c] = now + lap; self.lap_len[c] = lap; self.lap_counter[c] += 1
                if self.ghost_rate and self.rng.random() < self.ghost_rate: self.ghosts[c] = now + self.rng.uniform(2.0, lap - 2.0)
                if self.lap_counter[c] % 2 == 0: self.fuel[c] = max(0, self.fuel[c] - 1)
                fr = X.build_frame(0xEE, self.ee_payload(c, pit=False)); out += fr + fr
                z = int(lap / 0.01024)
                out += X.build_frame(0xD4, [c, 0, self.lap_counter[c] >> 1, self.lap_counter[c] & 1 | (8 if z > 0xFFFF else 0), (z >> 8) & 0xFF, z & 0xFF])
        for c, due in list(self.ghosts.items()):
            if now >= due:
                self.ghosts.pop(c, None); fr = X.build_frame(0xEE, self.ee_payload(c, pit=False)); out += fr + fr
    if out: feed(out)

def _live_step(self):
    now = time.monotonic()
    with self.lock:
        s = self.session
        if s and s.get('red_flag') and s['phase'] == 'countdown' and time.time() >= s.get('starts_at', 0):
            self.red_resume_go(s); self.save()
        phase = s['phase'] if s else None
        prepare = bool(s and not s.get('red_flag') and (phase in ['resetting', 'waiting_sensor'] or (phase == 'countdown' and time.time() >= s['starts_at'])))
        token = (s['id'], s['control']) if s else None
        if prepare and s.get('lap_source') == 'scx':
            s.update(phase='running', active=None, control=s['control'] + 1, version=s['version'] + 1, notice='¡A correr! La primera pasada de cada coche por la meta es la salida.')
            self.start_clock(s)
            s.pop('pending_active', None); self.save(); prepare = False; token = (s['id'], s['control'])
    if now >= self._next_poll:
        d = self.read_sensor()
        with self.lock:
            current = self.session and (self.session['id'], self.session['control']) == token
            if current and d and not prepare: self.consume(d)
            if current and prepare and not d:
                if self.session['phase'] != 'waiting_sensor':
                    self.session.update(phase='waiting_sensor', version=self.session['version'] + 1, notice='Comprobando conexión del sensor. La salida se preparará al recuperar respuesta.'); self.save()
        if current and prepare and d: self.reset_turn(token, d)
        with self.lock: self._next_poll = time.monotonic() + self.poll_interval()
    self.flush()

def _sensor_running():
    s = srv.live.session
    if s and s['phase'] == 'running' and not s.get('red_flag') and s.get('lap_source') in ('ir', 'both') and (s.get('lap_source') == 'both' or s.get('active') is not None): return True
    try:
        run = srv.gp.current()
        if run and run['kind'] == 'quali' and srv.gp.gp['config'].get('quali_source') == 'ir' and run['phase'] in ('running', 'finishing') and not run.get('red'): return True
    except Exception: pass
    return False

_errs = {}
def _safe(name, fn):
    try: fn()
    except Exception:
        n = _errs.get(name, 0) + 1; _errs[name] = n
        if n <= 3: print('DEMO tick %s:\n%s' % (name, traceback.format_exc()), flush=True)

def _gp_step():
    with srv.gp.lock: srv.gp._tick()
    srv.gp._flush()

def tick():
    if srv is None: return
    _safe('scx', lambda: _sim_step(srv.scx.sim))
    _safe('sensor', lambda: SENSOR.step(_sensor_running()))
    _safe('live', lambda: _live_step(srv.live))
    _safe('gp', _gp_step)

# ---------- peticiones HTTP sin red ----------
class DemoHandler(S.Handler):
    def __init__(self): self._status = 500; self._hdrs = {}
    def send_response(self, code, message=None): self._status = code
    def send_header(self, k, v): self._hdrs[k] = v
    def end_headers(self): pass
    def log_message(self, *a): pass

def request(method, url, headers_json, body):
    h = DemoHandler(); h.server = srv; h.path = url; h.command = method; h.request_version = 'HTTP/1.1'
    msg = Message()
    for k, v in json.loads(headers_json or '{}').items(): msg[k] = v
    if body is None: body = b''
    elif isinstance(body, str): body = body.encode('utf-8')
    elif hasattr(body, 'to_bytes'): body = body.to_bytes()
    else: body = bytes(body)
    del msg['Content-Length']; msg['Content-Length'] = str(len(body))
    h.headers = msg; h.rfile = io.BytesIO(body); h.wfile = io.BytesIO(); h.client_address = ('127.0.0.1', 0)
    (h.do_POST if method == 'POST' else h.do_GET)()
    raw = h.wfile.getvalue(); ct = h._hdrs.get('Content-Type', '')
    if ct.startswith('application/json') or ct.startswith('text/'): return json.dumps([h._status, h._hdrs, raw.decode('utf-8', 'replace'), False])
    import base64
    return json.dumps([h._status, h._hdrs, base64.b64encode(raw).decode(), True])

def seed(data_dir, names):
    """Primera vez: pilotos de ejemplo con avatar (los PNG ya están en data_dir/avatars/seedN.png)."""
    import os, uuid
    from pathlib import Path
    d = Path(data_dir)
    if (d / 'pilotos.json').exists(): return False
    slots = [None] * 6
    for i, n in enumerate(names):
        src = d / 'avatars' / ('seed%d.png' % (i + 1))
        a = '/avatars/' + uuid.uuid4().hex + '.png'; os.rename(src, d / a[1:])
        slots[i] = {'name': n, 'avatar': a, 'revision': uuid.uuid4().hex}
    for f in (d / 'avatars').glob('seed*.png'): f.unlink()
    (d / 'pilotos.json').write_text(json.dumps({'version': 1, 'slots': slots}, ensure_ascii=False, indent=2), encoding='utf-8')
    return True
