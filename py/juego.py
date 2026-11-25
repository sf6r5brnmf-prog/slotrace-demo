"""⚑ Puto el último y 🍻 El último paga las chelas: formatos de juego encima de una Carrera con la Pit Box (SCX).

Lo único que importa: NO ser el último.
  * Puto el último: todos salen juntos; la ronda termina en el PRIMER CORTE (de fábrica: cuando el líder completa
    5 vueltas; o por tiempo). El que va último en ese momento es El Puto (pantalla de castigo, contador de «veces Puto»).
  * El último paga las chelas: rondas de 3 min; al acabar el tiempo cada quien termina su vuelta; el último suma 🍺
    a la cuenta de la noche (hasta «Cerrar la noche»). El que gana la ronda se perdona 1 chela.

HONESTO: en SCX Digital la app NO puede frenar ni cortar un coche (la tarjeta solo se escucha). Todos los «features»
son castigos de SOFTWARE en la tabla: vueltas que se restan o segundos que se suman/restan al tiempo.
Orden de la tabla: más vueltas netas (vueltas − castigos) y, con las mismas, menos tiempo total (con hándicap,
bombas y rebufo). Los descalificados (banderas amarillas de más) van al final.

Eventos (bus interno, sin red): cada cosa que pasa se anota en s['juego']['eventos'] y se avisa a BUS.
Mañana Home Assistant (luces, sirena) se puede colgar de BUS; hoy no hay nada conectado."""
import copy, random, threading, time
from pathlib import Path
import durable, handicap as handicap_mod

MODOS = ('ultimo', 'chelas')
DEFAULTS = {
    'ultimo': {'corte': 'vueltas', 'cada_vueltas': 5, 'cada_s': 90,
               'bomba': True, 'bomba_s': 3.0, 'falso': True, 'falso_vueltas': 1, 'banderas': 2,
               'rebufo': True, 'rebufo_s': 0.3, 'salvavidas': False,
               'castigo': 'Le toca recoger los coches 🧹'},
    'chelas': {'ronda_s': 180, 'espera_s': 30,
               'bomba': True, 'bomba_s': 3.0, 'falso': True, 'falso_vueltas': 1, 'banderas': 2,
               'rebufo': False, 'rebufo_s': 0.3, 'perdon': True, 'doble': False},
}
# (tipo, mínimo, máximo) de cada parámetro
LIMITES = {'cada_vueltas': (int, 2, 50), 'cada_s': (float, 20, 1800), 'bomba_s': (float, 0.5, 20), 'falso_vueltas': (int, 0, 5),
           'banderas': (int, 0, 9), 'rebufo_s': (float, 0, 2), 'ronda_s': (float, 30, 1800), 'espera_s': (float, 5, 120)}
BOOLS = ('bomba', 'falso', 'rebufo', 'salvavidas', 'perdon', 'doble')
MAX_EVENTOS = 40
SALVAVIDAS_VUELTAS = 2
SALVAVIDAS_S = 45

class JuegoError(Exception):
    def __init__(self, message, status=400): super().__init__(message); self.status = status

# ---------- bus interno de eventos (para Home Assistant en el futuro; hoy nadie escucha) ----------
BUS = []          # funciones f(evento) ; nunca hay red aquí
def avisar(ev):
    for f in list(BUS):
        try: f(copy.deepcopy(ev))
        except Exception: pass

def limpiar_cfg(modo, raw, base=None):
    """Configuración de un modo con valores de fábrica para lo que falte o venga mal."""
    out = copy.deepcopy(base if base is not None else DEFAULTS[modo])
    for k, v in (raw or {}).items():
        if k not in DEFAULTS[modo]: continue
        if k in BOOLS: out[k] = bool(v)
        elif k == 'corte':
            if v in ('vueltas', 'tiempo'): out[k] = v
        elif k == 'castigo':
            if isinstance(v, str): out[k] = v.strip()[:80]
        elif k in LIMITES:
            t, lo, hi = LIMITES[k]
            try: x = t(v)
            except (TypeError, ValueError): raise JuegoError('Valor inválido en «%s».' % k)
            if not lo <= x <= hi: raise JuegoError('«%s» debe ir de %g a %g.' % (k, lo, hi))
            out[k] = x
    return out

class JuegoStore:
    """data/juego.json: configuración de los dos modos, contador de «veces Puto» y la cuenta de chelas de la noche."""
    def __init__(self, directory, avisos=None):
        self.path = Path(directory) / 'juego.json'; self.lock = threading.RLock()
        d, aviso = durable.leer_json(self.path, validate=lambda x: x if isinstance(x, dict) else (_ for _ in ()).throw(ValueError('x')), nombre='juego.json (modos de juego)')
        if aviso and avisos is not None: avisos.append(aviso)
        self.d = self._sano(d or {})
    def _sano(self, d):
        cfg = d.get('config') if isinstance(d.get('config'), dict) else {}
        out = {'config': {}, 'puto': {}, 'noche': None, 'noches': []}
        for m in MODOS:
            try: out['config'][m] = limpiar_cfg(m, cfg.get(m) if isinstance(cfg.get(m), dict) else {})
            except JuegoError: out['config'][m] = copy.deepcopy(DEFAULTS[m])
        if isinstance(d.get('puto'), dict): out['puto'] = {str(k): v for k, v in d['puto'].items() if isinstance(v, dict)}
        if isinstance(d.get('noche'), dict): out['noche'] = d['noche']
        if isinstance(d.get('noches'), list): out['noches'] = d['noches'][-30:]
        return out
    def _guardar(self): durable.escribir_json(self.path, self.d, backup=True, indent=1)
    def config(self):
        with self.lock: return copy.deepcopy(self.d['config'])
    def set_config(self, payload):
        with self.lock:
            nuevo = {m: limpiar_cfg(m, payload.get(m) if isinstance(payload.get(m), dict) else {}, self.d['config'][m]) for m in MODOS}
            self.d['config'] = nuevo; self._guardar(); return self.vista()
    # ----- veces Puto -----
    def sumar_puto(self, name, pid=None):
        with self.lock:
            k = (pid or name or '?').casefold() if not pid else 'pid:' + pid
            x = self.d['puto'].setdefault(k, {'name': name, 'n': 0, 'fechas': []})
            x['name'] = name; x['n'] = int(x.get('n', 0)) + 1; x['fechas'] = (x.get('fechas') or [])[-19:] + [round(time.time())]
            self._guardar(); return x['n']
    def veces_puto(self, name, pid=None):
        with self.lock:
            x = self.d['puto'].get('pid:' + pid if pid else (name or '').casefold())
            return int(x['n']) if x else 0
    # ----- noche de chelas -----
    def noche(self, crear=False):
        with self.lock:
            if self.d['noche'] is None and crear:
                self.d['noche'] = {'id': '%x' % int(time.time() * 1000), 'inicio': round(time.time()), 'rondas': [], 'cuenta': {}, 'doble_siguiente': False}
            return self.d['noche']
    def doble_siguiente(self, on):
        with self.lock:
            n = self.noche(crear=True); n['doble_siguiente'] = bool(on); self._guardar(); return self.vista()
    def anotar_ronda(self, ronda):
        """ronda = {'ultimo':{slot,name,pid}, 'ganador':{...}|None, 'vale':1|2, 'session': id} → actualiza la cuenta."""
        with self.lock:
            n = self.noche(crear=True)
            if any(r.get('session') == ronda.get('session') for r in n['rondas']): return copy.deepcopy(n)
            def fila(x):
                k = 'pid:' + x['pid'] if x.get('pid') else x['name'].casefold()
                return n['cuenta'].setdefault(k, {'name': x['name'], 'chelas': 0, 'ultimos': 0, 'ganadas': 0, 'perdones': 0})
            u = fila(ronda['ultimo']); u['name'] = ronda['ultimo']['name']; u['chelas'] += ronda.get('vale', 1); u['ultimos'] += 1
            perdon = None
            if ronda.get('ganador'):
                g = fila(ronda['ganador']); g['ganadas'] += 1
                if ronda.get('perdon') and g['chelas'] > 0 and g is not u:
                    g['chelas'] -= 1; g['perdones'] += 1; perdon = ronda['ganador']['name']
            ronda = dict(ronda, n=len(n['rondas']) + 1, at=round(time.time()), perdonado=perdon)
            n['rondas'].append(ronda); n['doble_siguiente'] = False
            self._guardar(); return copy.deepcopy(n)
    def cerrar_noche(self):
        with self.lock:
            n = self.d['noche']
            if not n or not n['rondas']: self.d['noche'] = None; self._guardar(); return None
            n['cierre'] = round(time.time()); n['paga'] = paga(n)
            self.d['noches'] = (self.d['noches'] + [n])[-30:]; self.d['noche'] = None; self._guardar(); return copy.deepcopy(n)
    def vista(self):
        with self.lock:
            n = copy.deepcopy(self.d['noche'])
            if n: n['tabla'] = tabla_noche(n); n['paga'] = paga(n)
            putos = sorted(self.d['puto'].values(), key=lambda x: -int(x.get('n', 0)))[:10]
            ult = copy.deepcopy(self.d['noches'][-1]) if self.d['noches'] else None
            return {'config': copy.deepcopy(self.d['config']), 'defaults': copy.deepcopy(DEFAULTS), 'noche': n, 'ultima_noche': ult,
                    'putos': [{'name': x['name'], 'n': x['n']} for x in putos]}

def tabla_noche(n):
    return sorted(({'name': v['name'], 'chelas': v['chelas'], 'ultimos': v['ultimos'], 'ganadas': v['ganadas'], 'perdones': v['perdones']} for v in n['cuenta'].values()),
                  key=lambda x: (-x['chelas'], -x['ultimos'], x['name'].casefold()))
def paga(n):
    t = tabla_noche(n)
    if not t or t[0]['chelas'] <= 0: return None
    top = [x for x in t if x['chelas'] == t[0]['chelas']]
    return {'names': [x['name'] for x in top], 'chelas': t[0]['chelas']}

# ---------- la ronda (vive dentro de la sesión: s['juego']) ----------
def nuevo(modo, cfg, pilots, doble=False, ronda=None, rng=None):
    rng = rng or random
    j = {'modo': modo, 'cfg': copy.deepcopy(cfg), 'fase': 'juego', 'pen': {}, 'eventos': [], 'n_ev': 0, 'resultado': None,
         'ultimo_slot': None, 'aviso_corte': False, 'doble': bool(doble and modo == 'chelas'), 'ronda': ronda}
    for p in pilots: j['pen'][str(p['slot'])] = {'vueltas': 0, 'seg': 0.0, 'rebufo': 0.0, 'rebufo_n': 0, 'bombas': 0, 'falso': False, 'salvado': False}
    if modo == 'ultimo':
        j['meta_vueltas'] = cfg['cada_vueltas']; j['meta_s'] = float(cfg['cada_s'])
    else:
        j['meta_s'] = float(cfg['ronda_s'])
    j['bomba'] = programar_bomba(j, 0.0, 0, rng) if cfg.get('bomba') else None
    return j

def programar_bomba(j, ahora_s, lider_vueltas, rng=random):
    cfg = j['cfg']
    if j['modo'] == 'ultimo' and cfg['corte'] == 'vueltas':
        n = j['meta_vueltas']
        if n < 3: return None
        if lider_vueltas == 0: return {'tipo': 'vueltas', 'at': rng.randint(2, n - 1)}
        return {'tipo': 'vueltas', 'at': lider_vueltas + rng.randint(8, 12)} if n >= 12 else None
    dur = j['meta_s']
    if ahora_s == 0:
        lo, hi = (0.35 * dur, 0.8 * dur) if dur <= 240 else (120, 180)
        return {'tipo': 'tiempo', 'at': round(rng.uniform(lo, hi), 1)}
    return {'tipo': 'tiempo', 'at': round(ahora_s + rng.uniform(120, 180), 1)} if dur > 240 else None

def evento(s, tipo, slot=None, name=None, texto=''):
    j = s['juego']; j['n_ev'] += 1
    ev = {'n': j['n_ev'], 'tipo': tipo, 'slot': slot, 'name': name, 'texto': texto, 'at': round(time.time(), 3), 'modo': j['modo'], 'session': s.get('id')}
    j['eventos'].append(ev); del j['eventos'][:-MAX_EVENTOS]
    s['version'] = s.get('version', 0) + 1
    avisar(ev); return ev

def pilot_of(s, slot): return next((p for p in s['pilots'] if p['slot'] == slot), None)

def tabla(s, hs=None):
    """Filas ordenadas (el primero va ganando, el último es el que pierde)."""
    j = s.get('juego') or {}; hs = hs or {}; rows = []
    for p in s['pilots']:
        pen = (j.get('pen') or {}).get(str(p['slot'])) or {}
        laps = [l['s'] for l in p.get('laps') or [] if isinstance(l.get('s'), (int, float))]
        net = len(laps) - int(pen.get('vueltas', 0))
        t = handicap_mod.suma(laps, hs.get(p['slot'], 0.0)) if laps else None
        if t is not None: t = round(t + float(pen.get('seg', 0.0)) - float(pen.get('rebufo', 0.0)), 3)
        rows.append({'slot': p['slot'], 'name': p['name'], 'pid': p.get('pid'), 'vueltas': net, 'reales': len(laps), 'tiempo': t, 'dsq': bool(p.get('dsq')),
                     'pen_vueltas': int(pen.get('vueltas', 0)), 'pen_seg': round(float(pen.get('seg', 0.0)), 2), 'rebufo': round(float(pen.get('rebufo', 0.0)), 2),
                     'bombas': int(pen.get('bombas', 0)), 'falso': bool(pen.get('falso')), 'salvado': bool(pen.get('salvado'))})
    rows.sort(key=lambda r: (r['dsq'], -r['vueltas'], r['tiempo'] if r['tiempo'] is not None else float('inf'), r['slot']))
    for i, r in enumerate(rows):
        r['pos'] = i + 1
        if i == 0: r['gap'] = None; continue
        a = rows[i - 1]
        if r['dsq']: r['gap'] = 'DSQ'
        elif a['vueltas'] != r['vueltas']: d = a['vueltas'] - r['vueltas']; r['gap'] = '−%d vuelta%s' % (d, '' if d == 1 else 's')
        elif a['tiempo'] is not None and r['tiempo'] is not None: r['gap'] = round(r['tiempo'] - a['tiempo'], 2)
        else: r['gap'] = None
    return rows

def posiciones(s, hs=None):
    """Para el registro de pilotos y el Garage: [(posición, piloto)] con el orden del juego."""
    by = {p['slot']: p for p in s['pilots']}
    return [(r['pos'], by[r['slot']]) for r in tabla(s, hs)]

def lider_vueltas(rows):
    return max([r['vueltas'] for r in rows if not r['dsq']] or [0])

def hs_de(live, s):
    h = live.session_handicap(s) if hasattr(live, 'session_handicap') else s.get('handicap')
    if not h or not h.get('enabled'): return {}
    return {p['slot']: handicap_mod.seg_de(h, live.hkey(h, p['slot']), p.get('nivel')) for p in s['pilots']}

def segundos(live, s):
    ms = live.elapsed_ms(s); return (ms or 0) / 1000.0

def falso(live, s, slot, por):
    j = s.get('juego')
    if not j or not j['cfg'].get('falso') or j['fase'] != 'juego': return False
    pen = j['pen'].get(str(slot))
    if pen is None or pen['falso']: return False
    pen['falso'] = True; v = int(j['cfg'].get('falso_vueltas', 1)); pen['vueltas'] += v
    p = pilot_of(s, slot)
    evento(s, 'salida_falso', slot, p and p['name'], '🟥 Salida en falso de %s (%s): −%d vuelta%s en la tabla.' % (p and p['name'], por, v, '' if v == 1 else 's'))
    return True

def antes_vuelta(live, s, pilot):
    """Antes de contar la vuelta de pilot. Devuelve False si NO debe contar (ronda ya cerrada para él)."""
    j = s.get('juego')
    if not j: return True
    if j['fase'] == 'fin': return False
    if j['fase'] == 'terminando':
        if pilot['slot'] in j.get('cruzaron', []): return False
        return True
    # ⚡ Rebufo: el que va último (zona de peligro) se descuenta segundos en cada vuelta que completa ahí.
    if j['cfg'].get('rebufo') and len(s['pilots']) > 1 and not pilot.get('dsq'):
        rows = tabla(s, hs_de(live, s))
        if rows and rows[-1]['slot'] == pilot['slot'] and pilot.get('laps'):
            pen = j['pen'][str(pilot['slot'])]; pen['rebufo'] = round(pen['rebufo'] + float(j['cfg']['rebufo_s']), 3); pen['rebufo_n'] += 1
    return True

def despues_vuelta(live, s, pilot):
    j = s.get('juego')
    if not j: return
    if j['fase'] == 'terminando':
        j.setdefault('cruzaron', []).append(pilot['slot']); revisar(live, s); return
    revisar(live, s)

def tick(live, s):
    """Llamado seguido por el bucle de la sesión (Mac) o por tick() del demo."""
    j = s.get('juego')
    if not j or j['fase'] == 'fin': return
    if s['phase'] == 'countdown' and not s.get('red_flag'):
        thr = 2
        fn = getattr(live, 'falso_throttle', None)
        if fn is not None:
            try: thr = int(fn())
            except Exception: pass
        scx = getattr(live, 'scx', None)
        if thr > 0 and scx is not None and j['cfg'].get('falso'):
            for p in s['pilots']:
                try: v = scx.throttle_now(live.car_of_slot(p['slot']) - 1)
                except Exception: v = None
                if v is not None and v >= thr and falso(live, s, p['slot'], 'aceleró antes del verde'): live.save()
        return
    if s['phase'] == 'running' and not s.get('red_flag'):
        revisar(live, s)

def revisar(live, s):
    """Bombas, aviso de corte, corte (Puto) o fin de ronda (chelas)."""
    j = s['juego']; cfg = j['cfg']; t = segundos(live, s); hs = hs_de(live, s); rows = tabla(s, hs); cambio = False
    if s['phase'] != 'running' or s.get('red_flag') or j['fase'] == 'fin': return
    lv = lider_vueltas(rows)
    # 💣 bomba al líder (+N s a su tiempo en la tabla)
    b = j.get('bomba')
    if b and j['fase'] == 'juego':
        hit = (b['tipo'] == 'vueltas' and lv >= b['at']) or (b['tipo'] == 'tiempo' and t >= b['at'])
        if hit:
            lider = next((r for r in rows if not r['dsq'] and r['reales'] > 0), None)
            if lider:
                pen = j['pen'][str(lider['slot'])]; pen['seg'] = round(pen['seg'] + float(cfg['bomba_s']), 3); pen['bombas'] += 1
                evento(s, 'bomba', lider['slot'], lider['name'], '💣 ¡Bomba! Le explotó a %s (iba primero): +%g s a su tiempo.' % (lider['name'], cfg['bomba_s']))
                rows = tabla(s, hs)
            j['bomba'] = programar_bomba(j, t, lv); cambio = True
    # ⚠ zona de peligro: el último de la tabla
    if len(rows) > 1:
        last = rows[-1]
        if (last['reales'] > 0 or last['dsq']) and j['ultimo_slot'] != last['slot']:
            j['ultimo_slot'] = last['slot']; cambio = True
            # Aviso (y sonido) a lo mucho cada 8 s: en una pelea cerrada el último cambia a cada rato.
            if t - float(j.get('peligro_t', -99)) >= 8:
                j['peligro_t'] = t; evento(s, 'peligro', last['slot'], last['name'], '⚠ %s entra a la zona de peligro.' % last['name'])
    if j['modo'] == 'ultimo':
        porv = cfg['corte'] == 'vueltas'
        falta = (j['meta_vueltas'] - lv) if porv else (j['meta_s'] - t)
        if not j['aviso_corte'] and ((porv and falta == 1) or (not porv and falta <= 10)):
            j['aviso_corte'] = True; evento(s, 'aviso_corte', None, None, '⏳ ¡Último aviso! ' + ('Al líder le falta 1 vuelta para el corte.' if porv else 'Corte en 10 segundos.')); cambio = True
        if falta <= 0: cortar(live, s, rows); return
    else:
        if j['fase'] == 'juego' and t >= j['meta_s']:
            j['fase'] = 'terminando'; j['cruzaron'] = []; j['deadline_s'] = t + float(cfg['espera_s'])
            evento(s, 'ultima_vuelta', None, None, '🏁 ¡Tiempo! Cada quien termina su vuelta.'); cambio = True
        if j['fase'] == 'terminando':
            vivos = [p['slot'] for p in s['pilots'] if not p.get('dsq')]
            if all(x in j['cruzaron'] for x in vivos) or t >= j['deadline_s']: cerrar_chelas(live, s); return
    if cambio: live.save()

def cortar(live, s, rows):
    j = s['juego']; cfg = j['cfg']
    if len(rows) < 2:
        terminar(live, s, None, '¡Corte! Con un solo piloto no hay Puto: nadie pierde.'); return
    last = rows[-1]; pen = j['pen'][str(last['slot'])]
    if cfg.get('salvavidas') and not pen['salvado'] and not last['dsq']:
        pen['salvado'] = True
        if cfg['corte'] == 'vueltas': j['meta_vueltas'] += SALVAVIDAS_VUELTAS; extra = '+%d vueltas' % SALVAVIDAS_VUELTAS
        else: j['meta_s'] += SALVAVIDAS_S; extra = '+%d s' % SALVAVIDAS_S
        j['aviso_corte'] = False
        evento(s, 'salvavidas', last['slot'], last['name'], '🛟 %s usó su salvavidas: el corte se mueve (%s).' % (last['name'], extra)); live.save(); return
    prev = rows[-2]
    if last['dsq']: falto = 'descalificado'
    elif prev['vueltas'] != last['vueltas']: d = prev['vueltas'] - last['vueltas']; falto = '%d vuelta%s' % (d, '' if d == 1 else 's')
    elif prev['tiempo'] is not None and last['tiempo'] is not None: falto = '%.1f s' % max(0.0, last['tiempo'] - prev['tiempo'])
    else: falto = None
    store = getattr(live, 'juego_store', None); veces = None
    p = pilot_of(s, last['slot']) or {}
    if store is not None:
        try: veces = store.sumar_puto(last['name'], p.get('pid'))
        except Exception: veces = None
    res = {'tipo': 'puto', 'slot': last['slot'], 'name': last['name'], 'vueltas': last['vueltas'], 'falto': falto, 'veces': veces,
           'castigo': cfg.get('castigo') or '', 'ganador': {'slot': rows[0]['slot'], 'name': rows[0]['name']}, 'tabla': rows}
    evento(s, 'corte', last['slot'], last['name'], '✂️ ¡CORTE! Fuera: %s.' % last['name'])
    evento(s, 'puto', last['slot'], last['name'], '🚩 %s es PUTO EL ÚLTIMO.' % last['name'])
    evento(s, 'ganador', rows[0]['slot'], rows[0]['name'], '🏆 Se salvó primero: %s.' % rows[0]['name'])
    terminar(live, s, res, '🚩 %s es PUTO EL ÚLTIMO. Ronda terminada.' % last['name'])

def cerrar_chelas(live, s):
    j = s['juego']; cfg = j['cfg']; rows = tabla(s, hs_de(live, s))
    if len(rows) < 2:
        terminar(live, s, None, 'Ronda terminada. Con un solo piloto nadie paga.'); return
    last, win = rows[-1], rows[0]; vale = 2 if j.get('doble') else 1
    pl = pilot_of(s, last['slot']) or {}; pw = pilot_of(s, win['slot']) or {}
    store = getattr(live, 'juego_store', None); cuenta = None; perdon = None
    if store is not None:
        try:
            n = store.anotar_ronda({'session': s['id'], 'vale': vale, 'perdon': bool(cfg.get('perdon')),
                                    'ultimo': {'slot': last['slot'], 'name': last['name'], 'pid': pl.get('pid')},
                                    'ganador': {'slot': win['slot'], 'name': win['name'], 'pid': pw.get('pid')}})
            perdon = n['rondas'][-1].get('perdonado'); cuenta = tabla_noche(n); ronda_n = n['rondas'][-1]['n']
        except Exception: ronda_n = None
    else: ronda_n = None
    res = {'tipo': 'chelas', 'slot': last['slot'], 'name': last['name'], 'suma': vale, 'perdon': perdon, 'ganador': {'slot': win['slot'], 'name': win['name']},
           'cuenta': cuenta, 'ronda': ronda_n, 'tabla': rows}
    evento(s, 'chela', last['slot'], last['name'], '🍺 %s quedó último: +%d chela%s.' % (last['name'], vale, '' if vale == 1 else 's'))
    if perdon: evento(s, 'perdon', win['slot'], win['name'], '🙌 %s ganó la ronda: se le perdona 1 chela.' % win['name'])
    evento(s, 'ganador', win['slot'], win['name'], '🏆 Ganó la ronda: %s.' % win['name'])
    terminar(live, s, res, '🍺 %s paga: +%d chela%s.' % (last['name'], vale, '' if vale == 1 else 's'))

def terminar(live, s, res, notice):
    j = s['juego']; j['fase'] = 'fin'; j['resultado'] = res; j['bomba'] = None
    live.terminar_sesion(s, notice)

def vista(live, s):
    """Lo que la pantalla necesita (sin revelar cuándo cae la bomba)."""
    j = s.get('juego')
    if not j: return None
    t = segundos(live, s); rows = j['resultado']['tabla'] if j.get('resultado') else tabla(s, hs_de(live, s))
    lv = lider_vueltas(rows); cfg = j['cfg']; out = {'modo': j['modo'], 'fase': j['fase'], 'cfg': copy.deepcopy(cfg), 'tabla': rows,
                                                     'eventos': copy.deepcopy(j['eventos'][-12:]), 'n_ev': j['n_ev'], 'resultado': copy.deepcopy(j['resultado']),
                                                     'doble': j.get('doble', False), 'ronda': j.get('ronda'), 'lider_vueltas': lv}
    if j['modo'] == 'ultimo':
        if cfg['corte'] == 'vueltas': out['corte'] = {'tipo': 'vueltas', 'meta': j['meta_vueltas'], 'faltan': max(0, j['meta_vueltas'] - lv)}
        else: out['corte'] = {'tipo': 'tiempo', 'meta_s': j['meta_s'], 'faltan_ms': max(0, int((j['meta_s'] - t) * 1000))}
    else:
        if j['fase'] == 'terminando': out['corte'] = {'tipo': 'terminando', 'cruzaron': list(j.get('cruzaron', [])), 'faltan_ms': max(0, int((j.get('deadline_s', t) - t) * 1000))}
        else: out['corte'] = {'tipo': 'tiempo', 'meta_s': j['meta_s'], 'faltan_ms': max(0, int((j['meta_s'] - t) * 1000))}
    return out
