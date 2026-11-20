"""ESP32 del sensor IR por USB (cable a la Mac). SOLO LECTURA, solo para la 💥 explosión.

La ESP32 imprime por su USB cada paso por el sensor AL INSTANTE, aunque su WiFi esté caído:
  'salida: cronometro andando'      -> primer paso (salida)
  'vuelta N: X s | ...'             -> cada vuelta
  'nueva sesion'                    -> reinicio de la sesión (no es un paso)
  'wifi evt: ...'                   -> eventos del WiFi (solo se cuentan las desconexiones)

Este módulo NUNCA escribe al puerto: lo abre con O_RDONLY (sin modo exclusivo, sin bytes, sin flush) y no tiene
ninguna llamada de escritura. Busca solo /dev/cu.usbmodem* (Mac) o /dev/ttyACM* (Linux); JAMÁS
/dev/cu.usbserial-* / ttyUSB* (esa es la tarjeta SCX, FTDI). Si se desconecta el cable, se reconecta solo.
No guarda ni muestra el texto de las líneas (solo su tipo), así que nada del WiFi queda en registros.
Las vueltas cronometradas de Práctica/Carrera siguen saliendo de /datos por WiFi (live.py); esto es solo sonido.
"""
import os, re, select, threading, time

BAUD = 115200
WARMUP_S = 0.5          # al abrir, la ESP32 puede soltar líneas viejas que tenía guardadas: se ignoran
RESCAN_S = 2.0
LINE_MAX = 512
OFF_VALUES = ('off', 'no', '0', 'false', 'apagado')

RE_SALIDA = re.compile(r'^salida\b')
RE_VUELTA = re.compile(r'^vuelta (\d+):')
RE_DISC = re.compile(r'^wifi evt: DISCONNECTED reason=(\d+)')

def is_scx_name(name):
    return name.startswith('cu.usbserial') or name.startswith('tty.usbserial') or name.startswith('ttyUSB')

def classify(line):
    """Tipo de línea: 'salida', 'vuelta', 'nueva', 'wifi_caida', 'wifi', 'esp32' u None (desconocida)."""
    # Gancho futuro: una línea «salida_pits N» (sensor IR KY-032 a la salida de pits) se
    # engancharía aquí y llamaría SCX.mark_pit_exit(N, source='ir') para marcar la salida exacta.
    if RE_SALIDA.match(line): return 'salida'
    if RE_VUELTA.match(line): return 'vuelta'
    if line.startswith('nueva sesion'): return 'nueva'
    if RE_DISC.match(line): return 'wifi_caida'
    if line.startswith('wifi evt:'): return 'wifi'
    if line.startswith('redes 2.4') or line.startswith('mejor CASA') or line.startswith(' - '): return 'esp32'
    return None

class Esp32Usb:
    def __init__(self, on_cross=None, port=None, exclude=(), baud=BAUD, enabled=True, start=True, warmup_s=WARMUP_S):
        self.on_cross = on_cross; self.port = port or None; self.exclude = {os.path.realpath(p) for p in exclude if p}
        self.baud = baud; self.enabled = enabled; self.warmup_s = warmup_s
        self.lock = threading.Lock(); self.stop_event = threading.Event()
        self.path = None; self.open_at = None; self.port_open = False; self.verified = set()
        self.error = None if enabled else 'Apagado en la configuración'
        self.lines = 0; self.crossings = 0; self.discarded = 0; self.reconnects = 0
        self.last_line_at = None; self.last_kind = None; self.last_cross_at = None
        self.wifi_drops = 0; self.wifi_last_reason = None; self.wifi_last_drop_at = None
        self.thread = None
        if enabled and start:
            self.thread = threading.Thread(target=self._loop, name='esp32-usb', daemon=True); self.thread.start()
    # --- puerto (solo lectura) ---
    def candidates(self):
        if self.port:
            name = os.path.basename(self.port)
            if is_scx_name(name) or os.path.realpath(self.port) in self.exclude: return []
            return [self.port] if os.path.exists(self.port) else []
        try: names = sorted(os.listdir('/dev'))
        except OSError: names = []
        out = []
        for n in names:
            if is_scx_name(n): continue
            if n.startswith('cu.usbmodem') or n.startswith('ttyACM'):
                p = '/dev/' + n
                if os.path.realpath(p) not in self.exclude: out.append(p)
        return out
    def _open(self, path):
        import termios
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            attrs = termios.tcgetattr(fd)
            speed = getattr(termios, 'B%d' % self.baud)
            attrs[0] = 0; attrs[1] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL   # sin HUPCL: al cerrar no se bajan DTR/RTS (no reinicia la ESP32)
            attrs[3] = 0; attrs[4] = speed; attrs[5] = speed
            attrs[6][termios.VMIN] = 0; attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception:
            os.close(fd); raise
        return fd
    def _loop(self):
        while not self.stop_event.is_set():
            ports = self.candidates()
            if not ports:
                with self.lock:
                    self.port_open = False; self.path = None
                    self.error = 'No está conectada por USB (%s)' % (self.port or '/dev/cu.usbmodem*')
                self.stop_event.wait(RESCAN_S); continue
            path = ports[0]
            try: fd = self._open(path)
            except Exception as e:
                with self.lock: self.port_open = False; self.path = path; self.error = 'No se pudo abrir %s (%s)' % (path, type(e).__name__)
                self.stop_event.wait(RESCAN_S); continue
            with self.lock:
                self.path = path; self.port_open = True; self.open_at = time.monotonic(); self.error = None
            buf = bytearray(); empties = 0; last_check = time.monotonic()
            try:
                while not self.stop_event.is_set():
                    r, _, _ = select.select([fd], [], [], 0.5)
                    now = time.monotonic()
                    if r:
                        data = os.read(fd, 1024)
                        if not data:
                            empties += 1
                            if empties >= 10 or not os.path.exists(path): raise OSError('cable desconectado')
                            self.stop_event.wait(0.05); continue
                        empties = 0
                        if now - self.open_at < self.warmup_s:
                            with self.lock: self.discarded += data.count(b'\n')
                            continue
                        buf += data
                        while b'\n' in buf:
                            raw, _, rest = bytes(buf).partition(b'\n'); buf = bytearray(rest)
                            self._line(path, raw.decode('ascii', 'replace').strip('\r\x00 '))
                        if len(buf) > LINE_MAX: del buf[:]
                    elif now - last_check > 1.0:
                        last_check = now
                        if not os.path.exists(path): raise OSError('cable desconectado')
            except Exception as e:
                with self.lock: self.error = 'Se desconectó el USB (%s); reconectando…' % type(e).__name__; self.reconnects += 1
            finally:
                with self.lock: self.port_open = False
                try: os.close(fd)
                except OSError: pass
            self.stop_event.wait(1.0)
    def _line(self, path, line):
        kind = classify(line)
        if kind is None: return
        now = time.monotonic(); cross = kind in ('salida', 'vuelta')
        with self.lock:
            self.verified.add(path); self.lines += 1; self.last_line_at = now; self.last_kind = kind
            if kind == 'wifi_caida':
                self.wifi_drops += 1; self.wifi_last_drop_at = time.time()
                m = RE_DISC.match(line); self.wifi_last_reason = int(m.group(1)) if m else None
            if cross: self.crossings += 1; self.last_cross_at = time.time()
            cb = self.on_cross
        if cross and cb is not None:
            try: cb(kind)
            except Exception as e: print('Error ESP32 USB→explosión: ' + type(e).__name__, flush=True)
    # --- consultas ---
    def feed_line(self, line, path='prueba'):
        """Gancho de prueba: procesa una línea como si llegara por el cable (no toca ningún puerto)."""
        self._line(path, line)
    def active(self):
        """True = el cable está conectado, abierto y ya se vio que es la ESP32 del sensor: la explosión sale de aquí."""
        with self.lock:
            return bool(self.port_open and self.path in self.verified and self.open_at is not None
                        and time.monotonic() - self.open_at >= self.warmup_s)
    def estado(self):
        act = self.active()
        with self.lock:
            now = time.monotonic()
            return {'habilitado': self.enabled, 'activo': act, 'puerto': self.path, 'abierto': self.port_open,
                    'verificado': bool(self.path and self.path in self.verified), 'baud': self.baud, 'solo_lectura': True,
                    'lineas': self.lines, 'cruces': self.crossings, 'descartadas_al_abrir': self.discarded,
                    'ultima_linea': self.last_kind, 'ultima_linea_hace_ms': None if self.last_line_at is None else round((now - self.last_line_at) * 1000),
                    'reconexiones': self.reconnects, 'wifi_caidas': self.wifi_drops, 'wifi_ultima_razon': self.wifi_last_reason,
                    'wifi_ultima_caida': self.wifi_last_drop_at,
                    'error': None if act else ('Cable abierto; falta la primera línea de la ESP32 (pasa un coche por el sensor).' if self.port_open else self.error)}
    def close(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread(): self.thread.join(timeout=3)
