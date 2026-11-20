"""Velocímetro en vivo con el GATILLO de cada mando + aviso de «pide cambio» de carril. Solo cálculo, sin E/S.

La tarjeta SCX (solo lectura) manda ~10 veces por segundo la trama FF «mandos»: por mando el gatillo
(0..15) y si el botón de cambio de carril está apretado. Aquí:
  * fondo de escala por mando = el gatillo más alto visto (empieza en 12: el mando de Ernesto llega a 12).
  * km/h en vivo = factor × (gatillo suavizado / fondo de escala).
  * calibración: al terminar cada vuelta VÁLIDA, el factor se ajusta para que el promedio del gatillo
    durante esa vuelta (ponderado por tiempo) dé exactamente la velocidad promedio real de la vuelta
    (largo de la pista / segundos × 3.6 × escala).
  * antes de la primera vuelta: factor de fábrica = a fondo marca la velocidad de una vuelta de 6 s.
  * sin datos (sin tarjeta, trama de mandos vieja > 1 s, o mando AA) -> None: la pantalla usa la vuelta.
  * botón: «pide cambio» (la tarjeta NO dice si el coche cambió de carril). Se cuenta cada apretón por sesión.
  * BANDERA AMARILLA DEL PILOTO: N apretones (flancos de subida, con anti-rebote) del MISMO mando dentro de una
    ventana de segundos (3 en 1.5 s de fábrica) = ese piloto pide bandera. feed() devuelve [(coche 0..5, t)] y el
    lector SCX avisa FUERA de su candado; qué hacer (PARO amarillo, límite, descalificación) lo decide live.py / gp.py.
"""
import collections, math, threading, time

FULL_START = 12          # fondo de escala inicial (máximo medido del mando de Ernesto)
FULL_MAX = 15            # máximo del protocolo
STALE_S = 1.0            # trama de mandos más vieja que esto = sin datos
DEFAULT_FULL_LAP_S = 6.0 # antes de calibrar: a fondo = velocidad de una vuelta de 6 s (22 m 1:32 -> 422 km/h)
SMOOTH_TAU_S = 0.15      # suavizado exponencial del gatillo (la aguja además se anima en el navegador)
PIDE_HOLD_S = 1.0        # el ⇄ se queda prendido 1 s después de apretar
HIST_S = 120.0           # historia del gatillo para calibrar (vueltas de hasta 2 min)
MAX_HOLD_S = 0.5         # un dato "vale" a lo más 0.5 s (huecos sin tramas no cuentan)
MIN_COVER = 0.6          # para calibrar, la vuelta debe tener datos del gatillo en >= 60 % de su tiempo
MIN_MEAN = 0.05          # gatillo promedio mínimo (5 %) para calibrar; si no, la vuelta no dice nada
SAME_LAP_S = 3.0         # la misma vuelta avisada dos veces (Pit Box + sensor IR en «ambos»): calibrar una vez
FLAG_DEBOUNCE_S = 0.15   # bandera del piloto: un flanco a menos de 0.15 s del anterior es rebote (no cuenta)
FLAG_MIN_RELEASE_S = 0.08  # ... y también si el botón estuvo suelto menos de 0.08 s (la tarjeta manda cada 0.1 s)
FLAG_DEFAULT = {'enabled': True, 'clicks': 3, 'window_s': 1.5}

def default_factor(track_m=22.0, scale=32):
    return track_m / DEFAULT_FULL_LAP_S * 3.6 * scale

class _Car:
    __slots__ = ('full', 'factor', 'calibrated', 'cal_laps', 'last_cal_end', 'hist', 'raw', 'smooth', 'smooth_t',
                 'button', 'press_at', 'presses', 'present', 'clicks', 'last_edge', 'release_at')
    def __init__(self, factor):
        self.full = FULL_START; self.factor = factor; self.calibrated = False; self.cal_laps = 0; self.last_cal_end = None
        self.hist = collections.deque(); self.raw = None; self.smooth = None; self.smooth_t = None
        self.button = False; self.press_at = None; self.presses = 0; self.present = False
        self.clicks = collections.deque(); self.last_edge = None; self.release_at = None

class Gatillo:
    def __init__(self, track=None):
        # track(): (metros, escala) de la configuración del Gran Premio; se usa para el factor de fábrica.
        self.track = track; self.lock = threading.Lock(); self.at = None
        self.cars = [_Car(self._default()) for _ in range(6)]
        self.session_since = time.time()
        self.pause_since = None; self.pause_ended = None   # PARO (bandera roja), en hora monotónica
        # flag_cfg(): {'enabled','clicks','window_s'} de la configuración (gp.flag_config); None = valores de fábrica.
        self.flag_cfg = None
    def _flag(self):
        cfg = dict(FLAG_DEFAULT)
        try:
            if self.flag_cfg: cfg.update(self.flag_cfg() or {})
        except Exception: pass
        return cfg
    def _default(self):
        try:
            if self.track: m, s = self.track(); return default_factor(float(m), int(s))
        except Exception: pass
        return default_factor()
    # --- entrada: cada trama FF decodificada (scx.decode_throttle) con su hora monotónica ---
    def feed(self, mandos, t):
        """Devuelve [(coche 0..5, t)] de los mandos que completaron el triple clic de bandera en esta trama."""
        flag = self._flag(); fired = []
        with self.lock:
            self.at = t
            for i, c in enumerate(self.cars):
                x = mandos[i] if i < len(mandos) else None
                if x is None:
                    c.present = False; c.raw = None; c.smooth = None
                    if c.button: c.release_at = t
                    c.button = False
                    c.hist.append((t, None)); self._trim(c, t); continue
                v = int(x['speed']) & 0x0F; pressed = bool(x['button'])
                if v > c.full: c.full = min(FULL_MAX, v)
                if c.smooth is None or c.smooth_t is None or t - c.smooth_t > STALE_S: c.smooth = float(v)
                else:
                    k = 1 - math.exp(-max(0.0, t - c.smooth_t) / SMOOTH_TAU_S); c.smooth += (v - c.smooth) * k
                c.smooth_t = t; c.raw = v; c.present = True
                if pressed and not c.button:
                    c.presses += 1; c.press_at = t   # flanco: un apretón = 1
                    if self._flag_edge(c, t, flag): fired.append((i, t))
                if pressed: c.press_at = t
                elif c.button: c.release_at = t   # se soltó
                c.button = pressed
                c.hist.append((t, v)); self._trim(c, t)
        return fired
    @staticmethod
    def _flag_edge(c, t, flag):
        """Un apretón nuevo (flanco de subida). True si con él se juntan N apretones dentro de la ventana."""
        if c.last_edge is not None and 0 <= t - c.last_edge < FLAG_DEBOUNCE_S: return False   # rebote
        if c.release_at is not None and 0 <= t - c.release_at < FLAG_MIN_RELEASE_S: return False   # soltó un instante: rebote
        c.last_edge = t
        try: n = int(flag.get('clicks', 3)); win = float(flag.get('window_s', 1.5))
        except (TypeError, ValueError): n, win = 3, 1.5
        c.clicks.append(t)
        while c.clicks and (t - c.clicks[0] > win or t < c.clicks[0]): c.clicks.popleft()
        if not flag.get('enabled', True) or n < 1: return False
        if len(c.clicks) >= n:
            c.clicks.clear(); return True   # se empieza a contar de nuevo
        return False
    @staticmethod
    def _trim(c, t):
        while c.hist and t - c.hist[0][0] > HIST_S: c.hist.popleft()
    # --- calibración con cada vuelta válida ---
    def mean_fraction(self, car, start, end):
        """Promedio del gatillo (0..1, ponderado por tiempo) en [start, end] y la fracción del tiempo con datos."""
        with self.lock:
            c = self.cars[car]; pts = list(c.hist); full = c.full
        if end <= start or not pts: return None, 0.0
        acc = cov = 0.0
        for j, (ti, v) in enumerate(pts):
            nxt = pts[j + 1][0] if j + 1 < len(pts) else ti + 0.1
            a = max(ti, start); b = min(nxt, ti + MAX_HOLD_S, end)
            if b <= a or v is None: continue
            acc += (v / float(full)) * (b - a); cov += b - a
        cover = cov / (end - start)
        return (acc / cov if cov > 0 else None), cover
    def on_lap(self, car, seconds, kmh_scale, end=None):
        """car 0..5; seconds = vuelta válida; kmh_scale = su km/h a escala; end = hora monotónica del cruce."""
        if not (isinstance(car, int) and 0 <= car < 6) or not seconds or seconds <= 0 or not kmh_scale or kmh_scale <= 0: return False
        end = time.monotonic() if end is None else end
        with self.lock:
            c = self.cars[car]
            if c.last_cal_end is not None and abs(end - c.last_cal_end) < SAME_LAP_S: return False
            # PARO: una vuelta que empezó antes del verde de la reanudación no calibra (su ventana incluye el paro).
            if self.pause_since is not None or (self.pause_ended is not None and self.pause_ended > end - seconds): return False
        mean, cover = self.mean_fraction(car, end - seconds, end)
        if mean is None or cover < MIN_COVER or mean < MIN_MEAN: return False
        with self.lock:
            c.factor = kmh_scale / mean; c.calibrated = True; c.cal_laps += 1; c.last_cal_end = end
        return True
    def pause(self, on, t=None):
        """PARO (on=True) y verde de la reanudación (on=False). Mientras dure, y para la vuelta que lo cruza, no se calibra."""
        t = time.monotonic() if t is None else t
        with self.lock:
            if on:
                if self.pause_since is None: self.pause_since = t
            else:
                self.pause_since = None; self.pause_ended = t if self.pause_ended is None else max(self.pause_ended, t)
    def reset_session(self):
        """Nueva Práctica/Carrera o Gran Premio: los apretones del botón se cuentan desde cero (la calibración se queda)."""
        with self.lock:
            for c in self.cars: c.presses = 0; c.press_at = None; c.clicks.clear(); c.last_edge = None; c.release_at = None
            self.pause_since = None
            self.session_since = time.time()
    # --- consultas ---
    def _factor(self, c):
        return c.factor if c.calibrated else self._default()
    def kmh(self, car, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            c = self.cars[car]
            if self.at is None or now - self.at > STALE_S or not c.present or c.smooth is None: return None
            return self._factor(c) * min(1.0, c.smooth / float(c.full))
    def view(self, now=None, connected=True):
        now = time.monotonic() if now is None else now
        with self.lock:
            fresh = connected and self.at is not None and now - self.at <= STALE_S
            out = []; dflt = self._default()
            for i, c in enumerate(self.cars):
                f = c.factor if c.calibrated else dflt
                live = fresh and c.present and c.smooth is not None
                pide = live and (c.button or (c.press_at is not None and now - c.press_at < PIDE_HOLD_S))
                out.append({'car': i + 1, 'live': live, 'raw': c.raw if live else None,
                            'pct': round(100 * min(1.0, c.smooth / float(c.full))) if live else None,
                            'kmh': round(f * min(1.0, c.smooth / float(c.full)), 1) if live else None,
                            'full': c.full, 'factor': round(f, 1), 'calibrated': c.calibrated, 'cal_laps': c.cal_laps,
                            'pide': bool(pide), 'presses': c.presses})
            return {'ok': fresh, 'age_ms': None if self.at is None else round((now - self.at) * 1000),
                    'session_since': self.session_since, 'cars': out}
