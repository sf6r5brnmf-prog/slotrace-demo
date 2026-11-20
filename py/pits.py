"""Detección de entrada/salida de pits y tiempo en pits por piloto.

La Pit Box (tarjeta SCX, solo lectura) marca la ENTRADA al cruzar la meta por el
carril de pits: en la trama EE, los demás carriles conectados van en F0 (en la
pista van en FE). Esa pasada SÍ cuenta como vuelta (como en la vida real).

En la app la parada se muestra como CAMBIO DE LLANTAS: el nivel D6 (el que la
Pit Box llama «combustible») se ve como vida de llanta en %. Las claves internas
(fuel_before/fuel_after = nivel 0..8) no cambian; se agregan vida_entrada_pct y
vida_salida_pct (en %).

La Pit Box NO manda trama de SALIDA. Se estima así, con un margen de 1 a 2 s:
  1) el combustible dejó de subir (o no subió) y el gatillo pasa de bajo/parado
     a más del umbral; o
  2) el combustible lleva X segundos sin subir y el gatillo se mantiene por
     encima del umbral unos 0.3 s; o
  3) un tope de seguridad (timeout); o
  4) el coche cruza la meta por la pista (FE) todavía «en pits».

Gancho para un sensor IR KY-032 en la salida de pits (ESP32, como el de la
explosión): mark_exit(coche, source='ir') cierra la parada con tiempo exacto
y sustituye la estimación. Hoy pit_exit_source='estimado'.
"""
import collections, threading, time

# Valores de fábrica (también en gp.DEFAULTS). Se pueden cambiar en
# Gran Premio → Configuración, y valen para Práctica, Carrera y GP.
DEFAULTS = {
    'pit_exit_source': 'estimado',   # 'estimado' | 'ir' | 'auto'
    'pit_exit_throttle': 3,          # gatillo 0..15: por encima = saliendo
    'pit_exit_low_throttle': 1,      # a este valor o menos = detenido/lento en pits
    'pit_exit_fuel_idle_s': 1.0,     # segundos sin que suba el combustible
    'pit_exit_throttle_hold_s': 0.3, # gatillo sostenido por encima del umbral
    'pit_exit_timeout_s': 60.0,      # tope de seguridad
}
SOURCES = ('estimado', 'ir', 'auto')
EXIT_SOURCES = ('estimado', 'ir', 'timeout', 'pista', 'cierre', 'reinicio')

def classify_ee_crossing(payload):
    """'pit' si el cruce fue por el carril de pits; si no, 'track' (pista).

    Regla robusta: es pits si en los bytes que no son E7 (el que cruzó) ni AA
    (sin mando) aparece F0 y no aparece FE. Cualquier otra mezcla (incluido
    un FE junto a un F0, o un cruce sin otros carriles) se toma como pista.
    """
    others = [b for b in bytes(payload or b'')[:6] if b not in (0xE7, 0xAA)]
    if 0xF0 in others and 0xFE not in others:
        return 'pit'
    return 'track'

def pit_config(cfg):
    """Config de pits con valores de fábrica para lo que falte."""
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(DEFAULTS)
    for k, factory in DEFAULTS.items():
        if k not in cfg or cfg[k] is None: continue
        v = cfg[k]
        if k == 'pit_exit_source':
            if v in SOURCES: out[k] = v
        elif k in ('pit_exit_throttle', 'pit_exit_low_throttle'):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= int(v) <= 15:
                out[k] = int(v)
        else:
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
                out[k] = float(v)
    return out

def _level(v):
    """Nivel de combustible 0..8, o None."""
    if v is None or isinstance(v, bool): return None
    if isinstance(v, (int, float)) and 0 <= v <= 8 and v == v: return int(v)
    return None

def _speed(v):
    if v is None: return None
    if isinstance(v, dict): v = v.get('speed')
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v: return None
    return int(v)

# ---------- Vida de llanta ----------
# La Pit Box manda en D6 un nivel por coche (0..8) que baja con el gatillo y sube en pits.
# En la app ese mismo nivel se muestra como VIDA DE LLANTA en % (no se inventa desgaste extra).
TIRE_DEFAULTS = {'tire_name': 'Media', 'tire_red_pct': 20, 'tire_yellow_pct': 50}

def vida_pct(level):
    """Nivel D6 (0..8) -> vida de llanta en % (8 -> 100, 4 -> 50). None si no hay dato."""
    lv = _level(level)
    if lv is None: return None
    return int(100 * lv / 8 + 0.5)

def color_llanta(pct, red=None, yellow=None):
    """'verde' (>50 %), 'amarilla' (20-50 %), 'roja' (<20 %) o None si no hay dato."""
    if pct is None or isinstance(pct, bool) or not isinstance(pct, (int, float)): return None
    red = TIRE_DEFAULTS['tire_red_pct'] if red is None else red
    yellow = TIRE_DEFAULTS['tire_yellow_pct'] if yellow is None else yellow
    if pct < red: return 'roja'
    if pct <= yellow: return 'amarilla'
    return 'verde'

def km_por_vuelta(track_length_m, scale):
    """Km a escala por vuelta = largo de pista (m) x escala / 1000 (25 m x 32 = 0.8 km)."""
    try:
        length, sc = float(track_length_m), float(scale)
    except (TypeError, ValueError):
        return None
    if not (length > 0 and sc > 0): return None
    return length * sc / 1000.0

def _laps_at(rec):
    """Vueltas que llevaba el piloto al entrar a pits (cuenta la pasada por el carril de pits)."""
    v = rec.get('vueltas_al_entrar', rec.get('lap'))
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None

def _km(laps, km_lap):
    return None if km_lap is None or laps is None else round(laps * km_lap, 2)

def juego_actual(paradas, laps_now, km_lap=None):
    """Vueltas y km con el juego de llantas actual: se reinicia en cada entrada a pits."""
    stops = list(paradas or [])
    base = 0
    for x in stops:
        lp = _laps_at(x)
        if lp is not None: base = lp
    laps_now = laps_now if isinstance(laps_now, int) and not isinstance(laps_now, bool) else 0
    n = max(0, laps_now - base)
    return {'juego': len(stops) + 1, 'vueltas': n, 'km': _km(n, km_lap) if km_lap is not None else None,
            'km_vuelta': None if km_lap is None else round(km_lap, 4)}

def paradas_llantas(paradas, km_lap=None):
    """Copia de las paradas con lo del cambio de llantas: vida al entrar/salir (%) y vueltas/km de ese juego."""
    out, prev = [], 0
    for x in list(paradas or []):
        r = dict(x)
        lp = _laps_at(x)
        n = None if lp is None else max(0, lp - prev)
        if lp is not None: prev = lp
        # El nivel D6 guardado manda (fuel_before/fuel_after); el % guardado solo si no hay nivel.
        for key, lvk in (('vida_entrada_pct', 'fuel_before'), ('vida_salida_pct', 'fuel_after')):
            v = vida_pct(x.get(lvk))
            r[key] = v if v is not None else x.get(key)
        r['vueltas_juego'] = n
        r['km_juego'] = _km(n, km_lap)
        out.append(r)
    return out

def resumen(paradas, live=None, now=None, laps_now=None, km_lap=None):
    """Resumen para una tarjeta: EN PITS, cronómetro, paradas, última y total.

    paradas: lista guardada en la sesión (puede ir vacía).
    live: vista en vivo del tracker para ese coche (opcional).
    """
    now = time.time() if now is None else now
    stops = list(paradas or [])
    closed = [x for x in stops if not x.get('abierta')]
    abierta = next((x for x in stops if x.get('abierta')), None)
    en = bool(live and live.get('en_pits')) or bool(abierta)
    elapsed = None
    entry_at = None
    fuel_before = None
    if live and live.get('en_pits'):
        elapsed = live.get('elapsed_s')
        entry_at = live.get('entry_at')
        fuel_before = live.get('fuel_before')
        if elapsed is None and live.get('entry_at') is not None:
            elapsed = max(0.0, now - live['entry_at'])
    elif abierta:
        entry_at = abierta.get('entry_at')
        fuel_before = abierta.get('fuel_before')
        if entry_at is not None:
            elapsed = max(0.0, now - entry_at)
    last = closed[-1]['duration_s'] if closed else None
    total = sum((x.get('duration_s') or 0) for x in closed)
    if en and elapsed is not None: total += elapsed
    n = len(closed) + (1 if en else 0)
    out = {
        'en_pits': en,
        'elapsed_s': None if (not en or elapsed is None) else round(elapsed, 1),
        'entry_at': entry_at if en else None,
        'paradas': n,
        'completadas': len(closed),
        'ultima_s': None if last is None else round(float(last), 1),
        'total_s': round(total, 1),
        'fuel_before': fuel_before,
        'fuel_after': (live or {}).get('fuel_after') if en else (closed[-1].get('fuel_after') if closed else None),
        'source_exit': None if en else (closed[-1].get('source_exit') if closed else None),
        'stops': stops,
    }
    # Vida de llanta (mismo nivel D6 en %) al entrar y al salir del último cambio de llantas.
    out['vida_entrada_pct'] = vida_pct(out['fuel_before'] if en else (closed[-1].get('fuel_before') if closed else None))
    out['vida_salida_pct'] = vida_pct(out['fuel_after'])
    if laps_now is not None:
        out['llanta'] = juego_actual(stops, laps_now, km_lap)
    return out

def stop_record(car, ev, abierta=False):
    """Dict persistible de una parada (entrada o ya cerrada). car es 1..6."""
    rec = {
        'car': car,
        'lap': ev.get('lap'),
        'entry_at': ev.get('entry_at'),
        'exit_at': ev.get('exit_at'),
        'duration_s': ev.get('duration_s'),
        'fuel_before': ev.get('fuel_before'),
        'fuel_after': ev.get('fuel_after'),
        'vida_entrada_pct': vida_pct(ev.get('fuel_before')),
        'vida_salida_pct': vida_pct(ev.get('fuel_after')),
        'source_entry': ev.get('source_entry') or 'scx',
        'source_exit': ev.get('source_exit'),
        'abierta': bool(abierta),
    }
    return rec

class PitsTracker:
    """Estado «en pits» por coche (índice 0..5). Solo cálculo; no toca puertos."""
    def __init__(self, config=None, config_fn=None):
        self.lock = threading.RLock()
        self._config = pit_config(config)
        self.config_fn = config_fn   # fn() -> dict, p.ej. la config del Gran Premio
        self.state = [None] * 6      # parada abierta o None
        self.history = [[] for _ in range(6)]
        self.events = collections.deque(maxlen=80)
        self.seq = 0

    def cfg(self):
        fn = self.config_fn
        if fn is not None:
            try: return pit_config(fn())
            except Exception: pass
        with self.lock: return dict(self._config)

    def set_config(self, cfg):
        with self.lock: self._config = pit_config(cfg)

    def _fuel(self, levels, car):
        if not levels or car < 0 or car >= len(levels): return None
        return _level(levels[car])

    def on_entry(self, car, t=None, fuel=None, lap=None):
        """El coche (0..5) cruzó la meta por el carril de pits. Devuelve [evento] o []."""
        t = time.monotonic() if t is None else t
        with self.lock:
            if not 0 <= car < 6: return []
            if self.state[car] is not None: return []   # ya está en pits (rebote)
            fuel_lv = _level(fuel) if not isinstance(fuel, (list, tuple)) else self._fuel(fuel, car)
            st = {
                'entry_t': t, 'entry_at': time.time(), 'lap': lap,
                'fuel_before': fuel_lv, 'fuel_after': fuel_lv,
                'fuel_last_rise_t': None, 'saw_low': False,
                'high_since': None, 'source_entry': 'scx',
            }
            self.state[car] = st
            ev = self._event('entry', car, t, st, abierta=True)
            return [ev]

    def on_fuel(self, levels, t=None):
        t = time.monotonic() if t is None else t
        out = []
        with self.lock:
            for car in range(6):
                if self.state[car] is None: continue
                lv = self._fuel(levels, car)
                if lv is None: continue
                st = self.state[car]
                prev = st['fuel_after']
                if prev is None or lv > prev:
                    if prev is not None and lv > prev:
                        st['fuel_last_rise_t'] = t
                    st['fuel_after'] = lv
                ev = self._maybe_exit(car, t)
                if ev: out.append(ev)
        return out

    def on_throttle(self, throttle, t=None):
        t = time.monotonic() if t is None else t
        out = []
        with self.lock:
            for car in range(6):
                if self.state[car] is None: continue
                spd = _speed(throttle[car] if throttle and car < len(throttle) else None)
                ev = self._maybe_exit(car, t, speed=spd)
                if ev: out.append(ev)
        return out

    def on_track_cross(self, car, t=None):
        """Cruzó la meta por la pista estando todavía en pits: se cierra la parada."""
        t = time.monotonic() if t is None else t
        with self.lock:
            if not 0 <= car < 6 or self.state[car] is None: return []
            ev = self._close(car, t, 'pista')
            return [ev] if ev else []

    def mark_exit(self, car, t=None, source='ir'):
        """Gancho del sensor IR en la salida de pits (o cierre manual). Coche 0..5.

        Si source='ir', cierra siempre que el coche esté en pits (sustituye la
        estimación). Otros source (timeout, cierre, reinicio) también cierran.
        """
        t = time.monotonic() if t is None else t
        if source not in EXIT_SOURCES: source = 'ir'
        with self.lock:
            if not 0 <= car < 6 or self.state[car] is None: return []
            ev = self._close(car, t, source)
            return [ev] if ev else []

    def tick(self, t=None):
        """Revisa timeouts y salidas por combustible/gatillo sin una trama nueva."""
        t = time.monotonic() if t is None else t
        out = []
        with self.lock:
            for car in range(6):
                if self.state[car] is None: continue
                ev = self._maybe_exit(car, t)
                if ev: out.append(ev)
        return out

    def rehydrate(self, car, rec, t=None):
        """Reabre una parada guardada (p. ej. tras reiniciar el servidor). car 0..5."""
        t = time.monotonic() if t is None else t
        with self.lock:
            if not 0 <= car < 6 or self.state[car] is not None: return False
            if not rec or not rec.get('abierta'): return False
            entry_at = rec.get('entry_at')
            elapsed = 0.0 if entry_at is None else max(0.0, time.time() - entry_at)
            st = {
                'entry_t': t - elapsed, 'entry_at': entry_at or time.time(),
                'lap': rec.get('lap'), 'fuel_before': rec.get('fuel_before'),
                'fuel_after': rec.get('fuel_after', rec.get('fuel_before')),
                'fuel_last_rise_t': None, 'saw_low': False, 'high_since': None,
                'source_entry': rec.get('source_entry') or 'scx',
            }
            self.state[car] = st
            return True

    def reset(self, car=None, reason='cierre', t=None):
        """Cierra paradas abiertas (un coche o todos). Devuelve eventos de salida."""
        t = time.monotonic() if t is None else t
        out = []
        with self.lock:
            cars = range(6) if car is None else [car]
            for c in cars:
                if not 0 <= c < 6 or self.state[c] is None: continue
                ev = self._close(c, t, reason)
                if ev: out.append(ev)
        return out

    def clear_history(self, car=None):
        with self.lock:
            if car is None:
                self.history = [[] for _ in range(6)]
            elif 0 <= car < 6:
                self.history[car] = []

    def car_view(self, car, t=None):
        """Vista de un coche (0..5)."""
        t = time.monotonic() if t is None else t
        with self.lock:
            if not 0 <= car < 6: return None
            return self._view_one(car, t)

    def view(self, t=None):
        t = time.monotonic() if t is None else t
        cfg = self.cfg()
        with self.lock:
            cars = [self._view_one(c, t) for c in range(6)]
            return {'config': cfg, 'cars': cars, 'events': list(self.events)[::-1], 'seq': self.seq}

    def _view_one(self, car, t):
        st = self.state[car]
        hist = list(self.history[car])
        if st is None:
            last = hist[-1] if hist else None
            return {
                'car': car + 1, 'en_pits': False, 'elapsed_s': None, 'entry_at': None,
                'lap': None, 'fuel_before': None if not last else last.get('fuel_before'),
                'fuel_after': None if not last else last.get('fuel_after'),
                'paradas': len(hist), 'ultima_s': None if not last else last.get('duration_s'),
                'total_s': round(sum((x.get('duration_s') or 0) for x in hist), 1),
                'source_exit': None if not last else last.get('source_exit'),
                'vida_entrada_pct': None if not last else vida_pct(last.get('fuel_before')),
                'vida_salida_pct': None if not last else vida_pct(last.get('fuel_after')),
                'stops': hist,
            }
        elapsed = max(0.0, t - st['entry_t'])
        return {
            'car': car + 1, 'en_pits': True, 'elapsed_s': round(elapsed, 1),
            'entry_at': st['entry_at'], 'lap': st.get('lap'),
            'fuel_before': st.get('fuel_before'), 'fuel_after': st.get('fuel_after'),
            'paradas': len(hist) + 1, 'ultima_s': hist[-1]['duration_s'] if hist else None,
            'total_s': round(sum((x.get('duration_s') or 0) for x in hist) + elapsed, 1),
            'source_exit': None, 'stops': hist,
            'vida_entrada_pct': vida_pct(st.get('fuel_before')), 'vida_salida_pct': vida_pct(st.get('fuel_after')),
        }

    def _fuel_idle(self, st, t, cfg):
        idle = cfg['pit_exit_fuel_idle_s']
        if st['fuel_last_rise_t'] is None:
            return (t - st['entry_t']) >= idle
        return (t - st['fuel_last_rise_t']) >= idle

    def _maybe_exit(self, car, t, speed=None):
        st = self.state[car]
        if st is None: return None
        cfg = self.cfg()
        if t - st['entry_t'] >= cfg['pit_exit_timeout_s']:
            return self._close(car, t, 'timeout')
        # Con source='ir' no se estima: solo el sensor, un cruce por pista o el tope.
        if cfg['pit_exit_source'] == 'ir':
            return None
        if speed is not None:
            if speed <= cfg['pit_exit_low_throttle']:
                st['saw_low'] = True
                st['high_since'] = None
            elif speed > cfg['pit_exit_throttle']:
                # El gatillo sostenido solo cuenta cuando el combustible ya no sube (la salida, no la carga).
                if self._fuel_idle(st, t, cfg):
                    if st['high_since'] is None: st['high_since'] = t
                else:
                    st['high_since'] = None
            else:
                st['high_since'] = None
        if not self._fuel_idle(st, t, cfg):
            return None
        hold = cfg['pit_exit_throttle_hold_s']
        # A) combustible en reposo y el gatillo sube después de haber estado bajo.
        if st['saw_low'] and speed is not None and speed > cfg['pit_exit_throttle']:
            return self._close(car, t, 'estimado')
        # B) combustible en reposo y gatillo sostenido por encima del umbral.
        if st['high_since'] is not None and (t - st['high_since']) >= hold:
            return self._close(car, t, 'estimado')
        return None

    def _close(self, car, t, source):
        st = self.state[car]
        if st is None: return None
        duration = max(0.0, t - st['entry_t'])
        rec = {
            'car': car + 1, 'lap': st.get('lap'),
            'entry_t': st['entry_t'], 'entry_at': st['entry_at'],
            'exit_t': t, 'exit_at': time.time(),
            'duration_s': round(duration, 3),
            'fuel_before': st.get('fuel_before'), 'fuel_after': st.get('fuel_after'),
            'vida_entrada_pct': vida_pct(st.get('fuel_before')), 'vida_salida_pct': vida_pct(st.get('fuel_after')),
            'source_entry': st.get('source_entry') or 'scx', 'source_exit': source,
            'abierta': False,
        }
        self.state[car] = None
        self.history[car].append(rec)
        return self._event('exit', car, t, rec, abierta=False)

    def _event(self, kind, car, t, data, abierta):
        self.seq += 1
        ev = {
            'seq': self.seq, 'kind': kind, 'car': car + 1, 't': t,
            'lap': data.get('lap'),
            'entry_at': data.get('entry_at'), 'exit_at': data.get('exit_at'),
            'duration_s': data.get('duration_s'),
            'fuel_before': data.get('fuel_before'), 'fuel_after': data.get('fuel_after'),
            'vida_entrada_pct': vida_pct(data.get('fuel_before')), 'vida_salida_pct': vida_pct(data.get('fuel_after')),
            'source_entry': data.get('source_entry') or 'scx',
            'source_exit': data.get('source_exit'),
            'abierta': abierta,
        }
        self.events.append(ev)
        return ev
