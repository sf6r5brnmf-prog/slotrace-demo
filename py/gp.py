"""Modo Gran Premio: Qualy (uno por uno) -> Eliminatorias (todos juntos) -> Final (primero a N vueltas).
Sin features Arcade. Las vueltas por coche vienen de la tarjeta SCX (solo lectura).
Todo es configurable (data/gp_config.json); presets: GP corto, GP estándar, GP largo."""
import copy, csv, io, json, os, shutil, threading, time, uuid
from pathlib import Path
import durable
import pits as pits_mod

DEFAULTS = {
    'preset': 'estandar',
    'quali_enabled': True, 'quali_minutes': 2.0, 'quali_order': 'registro', 'quali_finish_lap': True,
    'quali_any_car': True, 'quali_source': 'scx',
    'heats_rounds': 2, 'heats_minutes': 4.0,
    'finalists': 4, 'final_laps': 20, 'final_wait_s': 30,
    'fuel_enabled': True, 'lights_enabled': True, 'lights_seconds': 3,
    'false_start_penalty_laps': 1, 'false_start_throttle': 2,
    'first_pass_is_start': True, 'min_lap_s': 10.0,
    'track_length_m': 25.0, 'scale': 32, 'speed_max_kmh': 300, 'fuel_red_pct': 25,
    'sound_enabled': True, 'sound_volume': 80,
    'fuel_layout': 'nibbles',
    # Bandera amarilla del piloto (triple clic en el botón de cambio de carril). Aplica también a Práctica y Carrera.
    'pilot_flag_enabled': True, 'pilot_flag_clicks': 3, 'pilot_flag_window_s': 1.5, 'pilot_flag_max': 4, 'pilot_flag_dsq': True,
    # Tiempo en pits (= cambio de llantas): la entrada llega en la trama EE (F0); la salida se estima (nivel D6 + gatillo).
    'pit_exit_source': 'estimado', 'pit_exit_throttle': 3, 'pit_exit_low_throttle': 1,
    'pit_exit_fuel_idle_s': 1.0, 'pit_exit_throttle_hold_s': 0.3, 'pit_exit_timeout_s': 60.0,
    # Vida de llanta: el nivel D6 de la Pit Box (lo que ella llama «combustible») se muestra como llanta en %.
    # Solo nombre y zona roja; no hay desgaste inventado. Verde >50 %, amarilla 20–50 %, roja <20 %.
    'tire_name': 'Media', 'tire_red_pct': 20,
    'cars': {},
}

def scale_kmh(seconds, track_m=None, scale=None):
    """Velocidad promedio de una vuelta, en km/h a escala (1 decimal). None si no hay tiempo."""
    try:
        s = float(seconds)
        length = float(DEFAULTS['track_length_m'] if track_m is None else track_m)
        sc = float(DEFAULTS['scale'] if scale is None else scale)
    except (TypeError, ValueError):
        return None
    if s <= 0 or length <= 0 or sc <= 0:
        return None
    return round(length / s * 3.6 * sc, 1)

def scale_kmh_txt(seconds, track_m=None, scale=None):
    """Entero redondeado para etiquetas y CSV; cadena vacía si no hay tiempo."""
    v = scale_kmh(seconds, track_m, scale)
    return '' if v is None else str(int(round(v)))

# (tipo, mínimo, máximo)
FIELDS = {
    'quali_enabled': (bool,), 'quali_minutes': (float, 0.25, 30), 'quali_order': (str, ['registro', 'azar']),
    'quali_finish_lap': (bool,), 'quali_any_car': (bool,), 'quali_source': (str, ['scx', 'ir']),
    'heats_rounds': (int, 0, 6), 'heats_minutes': (float, 0.25, 60),
    'finalists': (int, 2, 6), 'final_laps': (int, 1, 500), 'final_wait_s': (int, 0, 300),
    'fuel_enabled': (bool,), 'lights_enabled': (bool,), 'lights_seconds': (int, 1, 10),
    'false_start_penalty_laps': (int, 0, 5), 'false_start_throttle': (int, 0, 15),
    'first_pass_is_start': (bool,), 'min_lap_s': (float, 0.5, 60),
    'track_length_m': (float, 1, 200), 'scale': (int, 1, 100), 'speed_max_kmh': (int, 50, 1000), 'fuel_red_pct': (int, 0, 100),
    'sound_enabled': (bool,), 'sound_volume': (int, 0, 100),
    'fuel_layout': (str, ['nibbles', 'nibbles_bajo', 'bytes']), 'preset': (str, ['corto', 'estandar', 'largo', 'personal']),
    'pilot_flag_enabled': (bool,), 'pilot_flag_clicks': (int, 2, 6), 'pilot_flag_window_s': (float, 0.5, 5),
    'pilot_flag_max': (int, 1, 20), 'pilot_flag_dsq': (bool,),
    'pit_exit_source': (str, ['estimado', 'ir', 'auto']), 'pit_exit_throttle': (int, 0, 15),
    'pit_exit_low_throttle': (int, 0, 15), 'pit_exit_fuel_idle_s': (float, 0.2, 10),
    'pit_exit_throttle_hold_s': (float, 0.05, 5), 'pit_exit_timeout_s': (float, 5, 300),
    'tire_name': (str, None, 24), 'tire_red_pct': (int, 0, 50),
}
FLAG_KEYS = ('pilot_flag_enabled', 'pilot_flag_clicks', 'pilot_flag_window_s', 'pilot_flag_max', 'pilot_flag_dsq')
TIRE_KEYS = ('tire_name', 'tire_red_pct')
PIT_KEYS = ('pit_exit_source', 'pit_exit_throttle', 'pit_exit_low_throttle', 'pit_exit_fuel_idle_s', 'pit_exit_throttle_hold_s', 'pit_exit_timeout_s')

def flag_config(cfg):
    """Bandera amarilla del piloto con valores de fábrica para lo que falte (configs y GP guardados antes de esta versión)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    v = {k: cfg.get(k, DEFAULTS[k]) for k in FLAG_KEYS}
    return {'enabled': bool(v['pilot_flag_enabled']), 'clicks': int(v['pilot_flag_clicks']), 'window_s': float(v['pilot_flag_window_s']),
            'max': int(v['pilot_flag_max']), 'dsq': bool(v['pilot_flag_dsq'])}
PRESETS = {
    'corto':    {'label': 'GP corto',    'quali_minutes': 1.0, 'heats_rounds': 1, 'heats_minutes': 3.0, 'finalists': 4, 'final_laps': 10},
    'estandar': {'label': 'GP estándar', 'quali_minutes': 2.0, 'heats_rounds': 2, 'heats_minutes': 4.0, 'finalists': 4, 'final_laps': 20},
    'largo':    {'label': 'GP largo',    'quali_minutes': 3.0, 'heats_rounds': 3, 'heats_minutes': 5.0, 'finalists': 4, 'final_laps': 30},
}

class GPError(Exception):
    def __init__(self, message, status=400): super().__init__(message); self.status = status

def clean_config(raw, base):
    cfg = copy.deepcopy(base)
    if not isinstance(raw, dict): raise GPError('Configuración inválida.')
    for k, v in raw.items():
        spec = FIELDS.get(k)
        if k == 'cars':
            if not isinstance(v, dict): raise GPError('Asignación de coches inválida.')
            cars = {}
            for slot, car in v.items():
                if str(slot) not in [str(i) for i in range(6)] or type(car) != int or not 1 <= car <= 6: raise GPError('Cada coche debe ser del 1 al 6.')
                cars[str(slot)] = car
            cfg['cars'] = cars; continue
        if not spec: continue
        t = spec[0]
        if t is bool:
            if type(v) != bool: raise GPError('Valor inválido en ' + k)
        elif t is str and spec[1] is None:
            # Texto libre corto (nombre de la llanta). Vacío = valor de fábrica.
            if not isinstance(v, str): raise GPError('Escribe un texto en ' + k)
            v = ' '.join(v.split())[:spec[2]] or DEFAULTS[k]
        elif t is str:
            if v not in spec[1]: raise GPError('Opción inválida en ' + k)
        else:
            if type(v) == bool or not isinstance(v, (int, float)): raise GPError('Escribe un número en ' + k)
            if t is int and int(v) != v: raise GPError('Usa un número entero en ' + k)
            if not spec[1] <= v <= spec[2]: raise GPError('%s debe estar entre %s y %s.' % (k, spec[1], spec[2]))
            v = t(v)
        cfg[k] = v
    return cfg

def check_gp(g):
    if not isinstance(g, dict) or g.get('status') not in ('active', 'done', 'cancelled') or not isinstance(g.get('runs'), list) or not g['runs']:
        raise ValueError('Gran Premio inválido')
    if type(g.get('current')) != int or not isinstance(g.get('pilots'), list) or not isinstance(g.get('config'), dict):
        raise ValueError('Gran Premio inválido')
    for r in g['runs']:
        if not isinstance(r, dict) or 'phase' not in r or not isinstance(r.get('data'), dict): raise ValueError('parte inválida')

RECOVERY_JUMP = 1000
# Vuelta mínima válida: la MISMA de Práctica/Carrera (data/vueltas.json, 10 s de fábrica); el servidor la conecta con
# gp.min_lap / gp.set_min_lap. Una vuelta más corta no cuenta y queda en d['sospechosas'] (tiempo, coche, hora, fuente).
# La siguiente vuelta se mide desde la última pasada válida. Debajo de BOUNCE_S es rebote: se ignora sin registrar.
BOUNCE_S = 1.5
MAX_SOSPECHOSAS = 300
# Bandera roja (PARO): los relojes (monotónicos) de la parte se guardan RELATIVOS al momento del paro, así
# sobreviven a un reinicio del servidor y al reanudar se recalculan: el tiempo del paro no cuenta para nadie.
RUN_STAMPS = ('green_at', 'ends_at', 'deadline', 'winner_at')
DATA_STAMPS = ('last_cross', 'finished_at')
RED_NOTICE = '🚩 BANDERA ROJA · PARO. Suelten el gatillo. El reloj está detenido y las vueltas no cuentan hasta Reanudar.'
YELLOW_NOTICE = '🟨 BANDERA AMARILLA · la pidió %s (%d de %d). Suelten el gatillo. El reloj está detenido y las vueltas no cuentan hasta Reanudar (pantalla grande).'
DSQ_NOTICE = '⛔ %s DESCALIFICADO: pidió una bandera amarilla más de las %d permitidas. Sus vueltas ya no cuentan en esta parte.'

class GrandPrix:
    def __init__(self, directory, scx, live=None):
        self.directory = Path(directory); self.scx = scx; self.live = live
        self.lock = threading.RLock(); self.stop_event = threading.Event(); self.dirty = False
        self.cfg_path = self.directory / 'gp_config.json'; self.path = self.directory / 'gp_session.json'
        self.config = copy.deepcopy(DEFAULTS); self.avisos = []; self.boot = None; self.avisos_servidor = []
        cfg, aviso = durable.leer_json(self.cfg_path, validate=lambda d: clean_config(d, DEFAULTS), nombre='gp_config.json (configuración del Gran Premio)')
        if cfg is not None: self.config = cfg
        if aviso: self.avisos.append(aviso); print(aviso, flush=True)
        self.scx.set_layout(self.config['fuel_layout'])
        if getattr(self.scx, 'pits', None) is not None:
            self.scx.pits.config_fn = lambda: (self.gp['config'] if self.gp and self.gp.get('status') == 'active' else self.config)
        self.gp, aviso = durable.leer_json(self.path, validate=check_gp, nombre='gp_session.json (Gran Premio en curso)')
        if aviso: self.avisos.append(aviso)
        if self.gp:
            try: self._recover()
            except Exception:
                moved = durable.apartar(self.path); self.gp = None
                self.avisos.append('El Gran Premio guardado no se pudo recuperar; se empezó limpio.' + (' Quedó guardado como ' + moved.name + '.' if moved else ''))
        self.event_id = (self.gp or {}).get('event_id', 0)
        scx.add_listener(self._on_scx)
        self.worker = threading.Thread(target=self._loop, name='gp-tick', daemon=True); self.worker.start()

    def _recover(self):
        """Servidor reiniciado (Mac cerrada, apagón, kill): la parte que corría se repite con Empezar.
        Las partes terminadas se conservan; las vueltas de la parte cortada quedan guardadas en el CSV (no se pierden)."""
        g = self.gp; run = self.current()
        if run and (run['phase'] == 'red' or (run['phase'] == 'countdown' and run.get('red'))):
            # Reinicio durante el PARO: la parte sigue en PARO con todo lo que llevaba; Reanudar prende el semáforo.
            run.update(phase='red', countdown_until=None)
            g['notice'] = 'Se reinició el servidor durante la BANDERA ROJA. La parte sigue en PARO con sus vueltas; aprieta Reanudar para el semáforo.'
        elif run and run['phase'] in ('countdown', 'running', 'finishing'):
            laps = sum(len(d.get('laps', [])) + len(d.get('sospechosas') or []) for d in run['data'].values() if isinstance(d, dict))
            if laps:
                g.setdefault('interrumpidas', []).append({'key': run['key'], 'label': run['label'], 'phase': run['phase'], 'at': time.time(),
                                                          'data': copy.deepcopy(run['data'])})
            self._reset_run(run)
            g['notice'] = ('Se reinició el servidor a media carrera (¿se cerró la Mac o se fue la luz?). Repite esta parte con "Empezar". '
                           'Las partes ya terminadas se conservaron' + ('; las vueltas de la parte cortada quedaron en el CSV.' if laps else '.'))
        g['version'] = g.get('version', 0) + RECOVERY_JUMP; self.dirty = True

    # ---------- utilidades ----------
    def current(self):
        g = self.gp
        if not g or g['status'] != 'active': return None
        return g['runs'][g['current']] if 0 <= g['current'] < len(g['runs']) else None
    def _event(self, typ, slot=None, text=''):
        g = self.gp; self.event_id += 1; g['event_id'] = self.event_id
        name = next((p['name'] for p in g['pilots'] if p['slot'] == slot), None)
        g['events'] = (g['events'] + [{'id': self.event_id, 'type': typ, 'slot': slot, 'name': name, 'text': text, 'at': time.time()}])[-25:]
    def _touch(self): self.gp['version'] += 1; self.dirty = True
    def pilot(self, slot): return next(p for p in self.gp['pilots'] if p['slot'] == slot)
    def kmh(self, s):
        c = self.gp['config'] if self.gp else self.config
        return scale_kmh(s, c.get('track_length_m'), c.get('scale'))
    def _new_data(self): return {'laps': [], 'sospechosas': [], 'paradas': [], 'started': False, 'last_cross': None, 'false_start': False, 'penalty': 0, 'finished_at': None, 'finish_pos': None, 'done': False}
    def _reset_run(self, run):
        self._close_run_pits(run, 'cierre')
        run.pop('red', None)
        run.update(phase='ready', countdown_until=None, green_at=None, ends_at=None, deadline=None, winner_at=None, ir_base=None, finishers=0)
        run['data'] = {str(s): self._new_data() for s in (run['participants'] or [])}

    # ---------- configuración ----------
    def min_lap_s(self):
        """Vuelta mínima válida en segundos (la global de vueltas.json si el servidor la conectó)."""
        fn = getattr(self, 'min_lap', None)
        if fn is not None:
            try: return float(fn())
            except Exception: pass
        cfg = self.gp['config'] if self.gp else self.config
        return float(cfg.get('min_lap_s', DEFAULTS['min_lap_s']))
    def _shown_config(self):
        c = copy.deepcopy(self.config); c['min_lap_s'] = self.min_lap_s(); return c
    def get_config(self):
        with self.lock: return {'config': self._shown_config(), 'presets': PRESETS, 'defaults': DEFAULTS}
    def set_config(self, payload):
        with self.lock:
            base = copy.deepcopy(self.config)
            preset = payload.get('apply_preset')
            if preset:
                if preset not in PRESETS: raise GPError('Ese preset no existe.')
                base.update({k: v for k, v in PRESETS[preset].items() if k != 'label'}); base['preset'] = preset
            if payload.get('reset_defaults'): base = copy.deepcopy(DEFAULTS); base['cars'] = self.config.get('cars', {})
            if isinstance(payload.get('config'), dict): base = clean_config(payload['config'], base)
            setter = getattr(self, 'set_min_lap', None)
            touched = payload.get('reset_defaults') or (isinstance(payload.get('config'), dict) and 'min_lap_s' in payload['config'])
            if setter is not None and touched and float(base['min_lap_s']) != self.min_lap_s():
                setter(base['min_lap_s'])   # misma vuelta mínima para todo (Práctica, Carrera y GP)
            self.config = base
            self.scx.set_layout(self.config['fuel_layout'])
            if self.gp and self.gp['status'] == 'active':
                # Lo que se puede cambiar en vivo sin alterar la carrera: visual, sonido y combustible.
                for k in ['fuel_enabled', 'track_length_m', 'scale', 'speed_max_kmh', 'fuel_red_pct', 'sound_enabled', 'sound_volume', 'fuel_layout'] + list(FLAG_KEYS) + list(PIT_KEYS) + list(TIRE_KEYS):
                    self.gp['config'][k] = self.config[k]
                self._touch()
            durable.escribir_json(self.cfg_path, self.config, backup=True, indent=2)
            return self.get_config()

    # ---------- comandos ----------
    def command(self, payload, roster):
        with self.lock:
            action = payload.get('action'); g = self.gp
            if action == 'create':
                if g and g['status'] == 'active': raise GPError('Ya hay un Gran Premio en curso. Termínalo o cancélalo primero.', 409)
                ids = payload.get('slots')
                if not isinstance(ids, list) or not 2 <= len(ids) <= 6 or any(type(i) != int or not 0 <= i <= 5 for i in ids) or len(set(ids)) != len(ids):
                    raise GPError('Elige de 2 a 6 pilotos para el Gran Premio.')
                if any(not roster['slots'][i] for i in ids): raise GPError('Un piloto ya no está registrado. Vuelve a elegir.', 409)
                cars = dict(self.config.get('cars', {}))
                if isinstance(payload.get('cars'), dict): cars.update(clean_config({'cars': payload['cars']}, self.config)['cars'])
                chosen = [cars.get(str(i), i + 1) for i in ids]
                if len(set(chosen)) != len(chosen): raise GPError('Dos pilotos tienen el mismo coche. Cada piloto necesita su propio número de coche (mando).')
                self.config['cars'] = cars
                self.set_config({})
                cfg = copy.deepcopy(self.config)
                if g: self._archive()
                pilots = []
                for i in ids:
                    src = self.directory / roster['slots'][i]['avatar'].lstrip('/'); avatar = '/avatars/' + uuid.uuid4().hex + '.png'
                    try: shutil.copyfile(src, self.directory / avatar.lstrip('/'))
                    except OSError: avatar = roster['slots'][i]['avatar']
                    pilots.append({'slot': i, 'name': roster['slots'][i]['name'], 'avatar': avatar, 'car': cars.get(str(i), i + 1)})
                order = list(ids)
                if cfg['quali_order'] == 'azar':
                    import random; random.shuffle(order)
                runs = []
                if cfg['quali_enabled']:
                    for k, s in enumerate(order):
                        runs.append({'key': 'q%d' % s, 'kind': 'quali', 'label': 'Qualy · %d de %d' % (k + 1, len(order)), 'participants': [s]})
                for r in range(cfg['heats_rounds']):
                    runs.append({'key': 'h%d' % (r + 1), 'kind': 'heat', 'label': 'Eliminatoria · ronda %d de %d' % (r + 1, cfg['heats_rounds']), 'participants': None})
                runs.append({'key': 'f', 'kind': 'final', 'label': 'Final · %d vueltas' % cfg['final_laps'], 'participants': None})
                for run in runs: self._reset_run(run)
                gt = getattr(self.scx, 'gatillo', None)
                if gt is not None: gt.reset_session()   # «pide cambio»: los apretones se cuentan por Gran Premio
                self.gp = g = {'id': uuid.uuid4().hex, 'created_at': time.time(), 'status': 'active', 'config': cfg, 'pilots': pilots, 'order': order,
                               'runs': runs, 'current': 0, 'events': [], 'event_id': self.event_id, 'version': 1, 'notice': ''}
                self._prepare(runs[0]); self._touch()
                return self.snapshot()
            if not g or g['id'] != payload.get('id'): raise GPError('El Gran Premio cambió. Actualiza la pantalla.', 409)
            run = self.current()
            if action == 'start':
                if not run or run['phase'] != 'ready': raise GPError('Esta parte ya arrancó o terminó.')
                if run['kind'] != 'quali' or g['config']['quali_source'] == 'scx':
                    sc = self.scx.summary()
                    if not sc['connected'] and not payload.get('force'): raise GPError('La tarjeta SCX no está mandando datos. Revisa el USB y que la Pit Box esté encendida.', 409)
                g['notice'] = ''
                if g['config']['lights_enabled']:
                    run.update(phase='countdown', countdown_until=time.monotonic() + g['config']['lights_seconds'], countdown_total=g['config']['lights_seconds'])
                    self._event('countdown', text=run['label'])
                else: self._go(run)
            elif action == 'repeat':
                if not run: raise GPError('No hay nada que repetir.')
                self._reset_run(run); self._prepare(run); g['notice'] = 'Se repite: ' + run['label']
            elif action == 'red_flag':
                # PARO desde cualquier pantalla; repetirlo no hace nada.
                if not run: raise GPError('No hay ninguna parte corriendo.')
                if run['phase'] == 'red': return self.snapshot()
                if run['phase'] == 'countdown' and run.get('red'):
                    run.update(phase='red', countdown_until=None); g['notice'] = RED_NOTICE; self._event('red_flag', text='Bandera roja · ' + run['label'])
                elif run['phase'] == 'countdown':
                    # Paro durante el semáforo de salida: nadie ha corrido; se vuelve a "listos".
                    self._reset_run(run); g['notice'] = 'PARO durante el semáforo. Todos a la línea de meta y aprieta Empezar otra vez.'
                elif run['phase'] in ('running', 'finishing'): self._red_stop(run)
                else: raise GPError('Esta parte no está corriendo; no hay nada que parar.')
            elif action == 'resume':
                if not run or run['phase'] != 'red':
                    if run and run.get('red'): return self.snapshot()      # ya está en el semáforo de reanudación
                    raise GPError('No hay bandera roja que reanudar.')
                g['notice'] = ''
                if g['config']['lights_enabled']:
                    run.update(phase='countdown', countdown_until=time.monotonic() + g['config']['lights_seconds'], countdown_total=g['config']['lights_seconds'])
                    self._event('countdown', text='Reanudación · ' + run['label'])
                else: self._resume_go(run)
            elif action == 'end_run':
                if not run or run['phase'] not in ('running', 'finishing', 'countdown', 'red'): raise GPError('Esta parte no está corriendo.')
                if run.get('red'):
                    self._red_record(run, resumed=False); run.pop('red', None)
                    if run['phase'] in ('red', 'countdown'): run['phase'] = 'running'
                self._finish(run, forced=True)
            elif action == 'skip':
                if not run or run['kind'] != 'quali' or run['phase'] != 'ready': raise GPError('Solo se puede saltar un piloto de la qualy antes de que arranque.')
                run['phase'] = 'done'; run['skipped'] = True; self._advance()
            elif action == 'next':
                if not run or run['phase'] != 'done': raise GPError('Termina esta parte antes de pasar a la siguiente.')
                self._advance()
            elif action == 'cancel':
                g['status'] = 'cancelled'; self._archive(); self.gp = None; self.dirty = True
                self._forget()
                return self.snapshot()
            elif action == 'close':
                if g['status'] == 'active': raise GPError('El Gran Premio sigue en curso.')
                self._archive(); self.gp = None
                self._forget()
                return self.snapshot()
            else: raise GPError('Acción desconocida.')
            self._touch(); return self.snapshot()

    def _prepare(self, run):
        """Define quién corre y en qué orden de salida."""
        g = self.gp
        if run['kind'] == 'heat': run['participants'] = self.quali_order()
        elif run['kind'] == 'final':
            heats = any(r['kind'] == 'heat' for r in g['runs'])
            base = self.heat_standings_slots() if heats else self.quali_order()
            # Descalificado en la etapa que da el pase (eliminatorias, o la qualy si no hay) = no pasa a la final.
            out = self.stage_dsq('heat' if heats else 'quali')
            base = [s for s in base if s not in out] or base
            run['participants'] = base[:g['config']['finalists']]
        run['grid'] = list(run['participants'])
        run['data'] = {str(s): run['data'].get(str(s)) or self._new_data() for s in run['participants']}
    def _advance(self):
        g = self.gp
        if g['current'] + 1 >= len(g['runs']):
            g['status'] = 'done'; g['finished_at'] = time.time(); self._event('podium', text='Gran Premio terminado'); self._archive(write_only=True)
            return
        g['current'] += 1; run = g['runs'][g['current']]; self._reset_run(run); self._prepare(run)
    def _go(self, run):
        g = self.gp; now = time.monotonic()
        run.update(phase='running', green_at=now, green_wall=time.time())
        if run['kind'] in ('quali', 'heat'):
            mins = g['config']['quali_minutes'] if run['kind'] == 'quali' else g['config']['heats_minutes']
            run['ends_at'] = now + mins * 60; run['duration_s'] = mins * 60
        for s in run['participants']:
            d = run['data'][str(s)]
            if d['false_start']: d['penalty'] = g['config']['false_start_penalty_laps']
        if run['kind'] == 'quali' and g['config']['quali_source'] == 'ir': self._ir_baseline(run)
        self._event('go', text=run['label'])
    def _red_stop(self, run, yellow=None):
        """PARO. yellow = {'by','by_name','used','max'} si lo pidió un piloto (bandera amarilla); None = bandera roja."""
        g = self.gp; now = time.monotonic()
        rel = {k: run[k] - now for k in RUN_STAMPS if isinstance(run.get(k), (int, float))}
        drel = {s: {k: d[k] - now for k in DATA_STAMPS if isinstance(d.get(k), (int, float))} for s, d in run['data'].items()}
        n = len(g.get('pausas') or []) + 1
        run['red'] = {'n': n, 'from': run['phase'], 'at': time.time(), 'rel': rel, 'data_rel': drel, 'ignored': 0, 'kind': 'yellow' if yellow else 'red'}
        if yellow: run['red'].update(yellow)
        self._gatillo_pause(True)   # velocímetro en vivo: las vueltas que cruzan el paro no calibran
        run['phase'] = 'red'
        if yellow:
            g['notice'] = YELLOW_NOTICE % (yellow['by_name'], yellow['used'], yellow['max'])
            self._event('yellow_flag', yellow['by'], 'Bandera amarilla %d/%d · %s' % (yellow['used'], yellow['max'], run['label']))
        else:
            g['notice'] = RED_NOTICE
            self._event('red_flag', text='Bandera roja · ' + run['label'])
    def _gatillo_pause(self, on):
        g = getattr(self.scx, 'gatillo', None)
        if g is not None:
            try: g.pause(on)
            except Exception as e: print('Error gatillo: ' + type(e).__name__, flush=True)
    def _red_record(self, run, resumed):
        red = run.get('red')
        if not red: return
        self._gatillo_pause(False)
        now = time.time()
        self.gp.setdefault('pausas', []).append({'n': red['n'], 'key': run['key'], 'label': run['label'], 'at': red['at'], 'resumed_at': now if resumed else None,
                                                 'duration_s': round(max(0.0, now - red['at']), 3), 'ignored_laps': red.get('ignored', 0),
                                                 'kind': red.get('kind', 'red'), 'by_name': red.get('by_name')})
    def _resume_go(self, run):
        """Verde de la reanudación: relojes recalculados desde lo guardado; el tiempo del paro no cuenta."""
        g = self.gp; now = time.monotonic(); red = run['red']
        self._red_record(run, resumed=True); run.pop('red')
        for k, v in red['rel'].items(): run[k] = now + v
        for s, dd in red['data_rel'].items():
            if s in run['data']:
                for k, v in dd.items(): run['data'][s][k] = now + v
        run.update(phase=red['from'], countdown_until=None); g['notice'] = ''
        if run['kind'] == 'quali' and g['config']['quali_source'] == 'ir': self._ir_baseline(run)
        self._event('go', text='Reanuda · ' + run['label'])
    def _finish(self, run, forced=False):
        run['phase'] = 'done'; run['ended_wall'] = time.time()
        if run['kind'] == 'final':
            rows = self.run_rows(run)
            if run.get('winner_at'): self._event('final_done', rows[0]['slot'] if rows else None, 'Final terminada')
            elif rows and rows[0]['laps'] > 0: self._event('finish', rows[0]['slot'], '¡%s gana el Gran Premio!' % rows[0]['name'])
            else: self._event('finish', text='Final terminada')
        elif run['kind'] == 'heat': self._event('finish', text=run['label'] + ' terminada')
        else: self._event('quali_done', run['participants'][0], 'Qualy terminada')
        if forced: run['forced'] = True
        self._close_run_pits(run, 'cierre')
        self._touch()

    # ---------- entradas de la pista ----------
    def _on_scx(self, kind, car, t):
        if kind != 'cross': return
        with self.lock:
            run = self.current()
            if not run or run['phase'] not in ('countdown', 'running', 'finishing', 'red'): return
            if run['kind'] == 'quali' and self.gp['config']['quali_source'] != 'scx': return
            slot = self._slot_for_car(run, car + 1)
            if run.get('red'):
                # PARO (o semáforo de reanudación): no cuenta ni cronometra. Si ya había salido, su vuelta empieza de nuevo en la meta.
                if slot is None: return
                d = run['data'][str(slot)]; dr = run['red']['data_rel'].setdefault(str(slot), {})
                if d['started'] and d['finished_at'] is None and dr.get('last_cross') != 0:
                    dr['last_cross'] = 0; run['red']['ignored'] = run['red'].get('ignored', 0) + 1; self._touch()
                return
            if slot is None: self.gp['notice'] = 'Cruzó el coche %d, que no está en esta parte (revisa la asignación de coches).' % (car + 1); self._touch(); return
            self._cross(run, slot, t, car=car + 1)
    def _slot_for_car(self, run, car):
        if run['kind'] == 'quali' and self.gp['config']['quali_any_car']: return run['participants'][0]
        for s in run['participants']:
            if self.pilot(s)['car'] == car: return s
        return None
    def _false_start(self, run, slot, why):
        d = run['data'][str(slot)]
        if d['false_start']: return
        d['false_start'] = True
        pen = self.gp['config']['false_start_penalty_laps']
        self._event('false_start', slot, 'Salida en falso (%s)%s' % (why, ' · −%d vuelta%s' % (pen, '' if pen == 1 else 's') if pen else ''))
        self._touch()
    def _suspicious(self, run, slot, d, lap_s, t, source, car, minimum):
        lst = d.setdefault('sospechosas', [])
        lst.append({'s': round(lap_s, 3), 'at': round(t - run['green_at'], 2) if run.get('green_at') else None, 'hora': round(time.time(), 3),
                    'src': source, 'car': car, 'min': minimum, 'tras_vuelta': len(d['laps'])})
        if len(lst) > MAX_SOSPECHOSAS: del lst[:-MAX_SOSPECHOSAS]
        self._event('suspicious', slot, 'Vuelta sospechosa %.2f s (menos de %g s): no cuenta' % (lap_s, minimum))
        self._touch()
    def _cross(self, run, slot, t, lap_s=None, car=None):
        cfg = self.gp['config']; d = run['data'][str(slot)]
        if run['phase'] == 'countdown': self._false_start(run, slot, 'cruzó la meta'); return
        if d.get('dsq'):
            d['dsq']['ignored'] = d['dsq'].get('ignored', 0) + 1; self._touch(); return   # descalificado: ya no cuenta
        if d['done'] or d['finished_at'] is not None: return
        minimum = self.min_lap_s(); source = 'ir' if lap_s is not None else 'scx'
        if car is None: car = self.pilot(slot)['car'] if source == 'scx' else None
        if lap_s is not None:
            # Sensor IR: la ESP32 reinicia su vuelta en cada cruce; lo de cruces sospechosos se suma (ir_carry).
            lap_s = round(lap_s + d.get('ir_carry', 0.0), 3)
            if lap_s < minimum:
                d['ir_carry'] = lap_s; self._suspicious(run, slot, d, lap_s, t, source, car, minimum); return
            d.pop('ir_carry', None)
        if not d['started']:
            d['started'] = True; d['last_cross'] = t
            if cfg['first_pass_is_start'] and lap_s is None: self._touch(); return
            if lap_s is None:
                lap_s = t - run['green_at']
                if lap_s < minimum:
                    # Primer cruce demasiado pronto tras el verde: no cuenta; la vuelta sigue midiéndose desde el verde.
                    d['last_cross'] = run['green_at']; self._suspicious(run, slot, d, lap_s, t, source, car, minimum); return
        else:
            if lap_s is None:
                lap_s = t - d['last_cross']
                if lap_s < min(BOUNCE_S, minimum): return      # rebote o doble lectura del mismo cruce
                if lap_s < minimum:
                    # Sospechosa: no cuenta y no mueve last_cross (se mide desde la última pasada válida).
                    self._suspicious(run, slot, d, lap_s, t, source, car, minimum); return
            d['last_cross'] = t
        n = len(d['laps']) + 1
        valid = not (run['kind'] == 'quali' and n <= d['penalty'])
        prev_best = self.stage_best(run)
        d['laps'].append({'n': n, 's': round(lap_s, 3), 'kmh': self.kmh(lap_s), 'valid': valid, 'at': round(t - run['green_at'], 2)})
        g = getattr(self.scx, 'gatillo', None)
        cal_car = car or self.pilot(slot).get('car')
        if g is not None and cal_car:
            # Velocímetro en vivo: la vuelta válida calibra el gatillo de ese mando (solo cálculo, nunca falla la vuelta).
            try: g.on_lap(int(cal_car) - 1, lap_s, self.kmh(lap_s), t)
            except Exception as e: print('Error gatillo: ' + type(e).__name__, flush=True)
        self._event('lap', slot, '%.2f s' % lap_s)
        if valid and prev_best is not None and lap_s < prev_best: self._event('best', slot, 'Mejor vuelta: %.2f s' % lap_s)
        if run['kind'] == 'quali' and run['phase'] == 'finishing': d['done'] = True; self._finish(run)
        elif run['kind'] == 'final':
            if self.net_laps(run, slot) >= cfg['final_laps'] and run['phase'] == 'running': self._final_finish(run, slot, t, winner=True)
            elif run['phase'] == 'finishing': self._final_finish(run, slot, t)
        self._touch()
    def _final_finish(self, run, slot, t, winner=False):
        d = run['data'][str(slot)]; run['finishers'] = run.get('finishers', 0) + 1
        d['finished_at'] = t; d['finish_pos'] = run['finishers']
        if winner:
            run['phase'] = 'finishing'; run['winner_at'] = t; run['deadline'] = t + self.gp['config']['final_wait_s']
            self._event('winner', slot, '¡Bandera a cuadros! Gana ' + self.pilot(slot)['name'])
        self._final_check(run)
    def _final_check(self, run):
        """La final termina cuando todos cruzaron la meta final o están descalificados."""
        if run['phase'] in ('running', 'finishing') and all(run['data'][str(s)]['finished_at'] is not None or run['data'][str(s)].get('dsq') for s in run['participants']):
            self._finish(run)

    # ---------- bandera amarilla del piloto ----------
    def flag_cfg(self):
        return flag_config(self.gp['config'] if self.gp else self.config)
    def on_pilot_flag(self, car, t=None):
        """Triple clic del mando car (0..5) en una parte del GP. Devuelve 'yellow', 'dsq' o None (ignorado)."""
        with self.lock:
            run = self.current()
            # Solo con la parte en verde; nada antes del semáforo, durante un PARO ni en su semáforo de reanudación.
            if not run or run['phase'] not in ('running', 'finishing') or run.get('red'): return None
            cfg = self.flag_cfg()
            if not cfg['enabled']: return None
            slot = self._slot_for_car(run, car + 1)
            if slot is None: return None
            d = run['data'].get(str(slot))
            if d is None or d.get('dsq') or d.get('done') or d.get('finished_at') is not None: return None
            name = self.pilot(slot)['name']; used = d.get('banderas', 0)
            if used < cfg['max']:
                d['banderas'] = used + 1
                self._red_stop(run, {'by': slot, 'by_name': name, 'used': used + 1, 'max': cfg['max']})
                self._touch(); return 'yellow'
            if not cfg['dsq']:
                self.gp['notice'] = '🟨 %s ya usó sus %d banderas amarillas de esta parte; no se sacó otra.' % (name, cfg['max'])
                self._touch(); return None
            d['dsq'] = {'at': time.time(), 'laps': len(d['laps']), 'ignored': 0, 'banderas': used}
            d['banderas_extra'] = d.get('banderas_extra', 0) + 1
            self.gp['notice'] = DSQ_NOTICE % (name, cfg['max'])
            self._event('dsq', slot, 'DESCALIFICADO · pidió la bandera amarilla %d (máximo %d) · %s' % (used + 1, cfg['max'], run['label']))
            if run['kind'] == 'quali': d['done'] = True; self._finish(run)      # su qualy se acaba ahí
            elif run['kind'] == 'final': self._final_check(run)
            self._touch(); return 'dsq'
    def stage_dsq(self, kind):
        """Pilotos descalificados en alguna parte de ese tipo ('quali', 'heat', 'final')."""
        return {int(s) for r in self.gp['runs'] if r['kind'] == kind and r['participants'] for s, d in r['data'].items() if isinstance(d, dict) and d.get('dsq')}
    def km_lap(self, cfg=None):
        """Km a escala por vuelta con el largo y la escala de la configuración (25 m × 32 = 0.8 km)."""
        cfg = cfg or (self.gp['config'] if self.gp else self.config)
        return pits_mod.km_por_vuelta(cfg.get('track_length_m', DEFAULTS['track_length_m']), cfg.get('scale', DEFAULTS['scale']))
    def _pits_view(self, d, car):
        live = None
        try:
            tr = getattr(self.scx, 'pits', None)
            live = tr.car_view(car - 1) if tr is not None and type(car) == int else None
        except Exception: live = None
        r = pits_mod.resumen(d.get('paradas'), live, laps_now=len(d.get('laps') or []), km_lap=self.km_lap())
        r.pop('stops', None)
        return r
    def _close_run_pits(self, run, reason='cierre'):
        """Cierra paradas abiertas al terminar (o repetir) una parte. También limpia el tracker de esos coches."""
        if not run or not self.gp: return
        now = time.time()
        tr = getattr(self.scx, 'pits', None)
        for s in run.get('participants') or []:
            d = (run.get('data') or {}).get(str(s)) or {}
            for rec in d.get('paradas') or []:
                if rec.get('abierta'):
                    rec['exit_at'] = now
                    rec['duration_s'] = round(max(0.0, now - (rec.get('entry_at') or now)), 3)
                    rec['source_exit'] = reason
                    rec['abierta'] = False
            if tr is None: continue
            p = next((x for x in (self.gp.get('pilots') or []) if x.get('slot') == s), None)
            car = None if p is None else p.get('car')
            if type(car) == int:
                try: tr.reset(car - 1, reason=reason)
                except Exception as e:
                    print('Error al cerrar pits: ' + type(e).__name__, flush=True)
    def rehydrate_pits(self):
        """Tras arrancar: si la parte sigue en curso (p. ej. en PARO) y había una parada abierta, el tracker la retoma."""
        with self.lock:
            run = self.current()
            if not run or run['phase'] not in ('running', 'finishing', 'red', 'countdown'): return
            for s in run.get('participants') or []:
                d = (run.get('data') or {}).get(str(s)) or {}
                rec = next((x for x in (d.get('paradas') or []) if x.get('abierta')), None)
                if not rec: continue
                tr = getattr(self.scx, 'pits', None)
                if tr is None: continue
                try:
                    car = self.pilot(s)['car']
                    if type(car) == int: tr.rehydrate(car - 1, rec)
                except Exception as e:
                    print('Error al retomar pits: ' + type(e).__name__ + ': ' + str(e), flush=True)
    def on_pit(self, ev):
        """Entrada o salida de pits durante una parte en curso del Gran Premio."""
        with self.lock:
            run = self.current()
            if not run or run['phase'] not in ('running', 'finishing', 'red'):
                # Si la parte ya no corre, igual cerramos una parada que haya quedado abierta.
                if not ev or ev.get('kind') != 'exit' or not run or run['phase'] not in ('done', 'ready', 'countdown'): return None
            slot = self._slot_for_car(run, ev['car'])
            if slot is None: return None
            d = run['data'][str(slot)]
            d.setdefault('paradas', [])
            if ev.get('kind') == 'entry':
                if any(x.get('abierta') for x in d['paradas']): return None
                rec = pits_mod.stop_record(ev['car'], ev, abierta=True)
                rec['lap'] = ev.get('lap') if ev.get('lap') is not None else self.net_laps(run, slot)
                rec['vueltas_al_entrar'] = len(d.get('laps') or [])   # para las vueltas/km de cada juego de llantas
                d['paradas'].append(rec)
                self._event('pit_entry', slot, 'entró a pits · cambio de llantas')
                self._touch(); return 'entry'
            if ev.get('kind') == 'exit':
                rec = next((x for x in reversed(d['paradas']) if x.get('abierta')), None)
                if rec is None:
                    d['paradas'].append(pits_mod.stop_record(ev['car'], ev, abierta=False)); rec = d['paradas'][-1]
                else:
                    rec.update(exit_at=ev.get('exit_at'), duration_s=ev.get('duration_s'),
                               fuel_after=ev.get('fuel_after'), vida_salida_pct=pits_mod.vida_pct(ev.get('fuel_after')), source_exit=ev.get('source_exit'), abierta=False)
                dur = rec.get('duration_s')
                self._event('pit_exit', slot, 'salió de pits con llantas nuevas' + (' · %.1f s' % dur if dur is not None else ''))
                self._touch(); return 'exit'
            return None

    def _ir_baseline(self, run):
        snap = self.live.sensor_snapshot() if self.live else None
        data = snap['data'] if snap and snap['connected'] else None
        if not data: run['ir_base'] = None; self.gp['notice'] = 'Sensor IR sin conexión: no se contarán vueltas de la qualy.'; return
        run['ir_base'] = data['vueltas']; run['ir_skip'] = 'esperando' not in str(data.get('estado', ''))
        for d in run['data'].values(): d.pop('ir_carry', None)   # la vuelta del sensor vuelve a empezar
        if data['vueltas'] >= 36: self.gp['notice'] = 'El sensor IR ya casi llega a 40 vueltas; reinícialo (botón de reset de la ESP32) antes de la qualy.'
    def _ir_poll(self, run):
        if run.get('ir_base') is None or not self.live: return
        snap = self.live.sensor_snapshot(); data = snap['data'] if snap['connected'] else None
        if not data: return
        slot = run['participants'][0]; d = run['data'][str(slot)]
        for lap in sorted(data['laps'], key=lambda l: l['n']):
            if lap['n'] <= run['ir_base']: continue
            run['ir_base'] = lap['n']
            if run.get('ir_skip'): run['ir_skip'] = False; d['started'] = True; d['last_cross'] = time.monotonic(); continue
            d['started'] = True; d['last_cross'] = time.monotonic()
            self._cross(run, slot, time.monotonic(), lap_s=lap['s'])

    # ---------- bucle ----------
    def _loop(self):
        while not self.stop_event.is_set():
            try:
                with self.lock: self._tick()
                self._flush()
            except Exception as e: print('Error GP: ' + type(e).__name__ + ' ' + str(e), flush=True)
            self.stop_event.wait(0.05)
    def _tick(self):
        run = self.current()
        if not run: return
        now = time.monotonic(); cfg = self.gp['config']
        if run['phase'] == 'countdown' and run.get('red'):
            # Semáforo de reanudación: sin castigos (los coches pueden estar en cualquier parte de la pista).
            if now >= run['countdown_until']: self._resume_go(run); self._touch()
        elif run['phase'] == 'countdown':
            thr = cfg['false_start_throttle']
            if thr > 0 and not (run['kind'] == 'quali' and cfg['quali_source'] == 'ir'):
                for s in run['participants']:
                    v = self.scx.throttle_now(self.pilot(s)['car'] - 1)
                    if v is not None and v >= thr: self._false_start(run, s, 'aceleró antes del verde')
            if now >= run['countdown_until']: self._go(run); self._touch()
        elif run['phase'] in ('running', 'finishing'):
            if run['kind'] == 'quali' and cfg['quali_source'] == 'ir': self._ir_poll(run)
            if run['phase'] == 'running' and run['kind'] in ('quali', 'heat') and now >= run['ends_at']:
                d = run['data'][str(run['participants'][0])]
                if run['kind'] == 'quali' and cfg['quali_finish_lap'] and d['started']:
                    run['phase'] = 'finishing'; run['deadline'] = now + max(30, cfg['final_wait_s']); self._event('last_lap', run['participants'][0], 'Se acabó el tiempo: termina tu vuelta'); self._touch()
                else: self._finish(run)
            elif run['phase'] == 'finishing' and run.get('deadline') and now >= run['deadline']: self._finish(run)
    def _flush(self):
        with self.lock:
            if not self.dirty: return
            self.dirty = False; doc = copy.deepcopy(self.gp)
        if doc is None: return
        try: durable.escribir_json(self.path, doc, backup=True)
        except Exception:
            with self.lock: self.dirty = True   # se reintenta en el siguiente ciclo
            raise
        with self.lock:
            if self.gp is None: self._forget()   # se canceló mientras se guardaba
    def _forget(self):
        # Gran Premio cerrado o cancelado: borrar el archivo Y su respaldo, para que no "reviva" al reiniciar.
        for f in (self.path, durable.backup_path(self.path)):
            try: f.unlink()
            except OSError: pass
    def _archive(self, write_only=False):
        g = self.gp
        if not g: return
        folder = self.directory / 'gp'; folder.mkdir(exist_ok=True)
        stamp = time.strftime('%Y-%m-%d_%H%M', time.localtime(g['created_at']))
        durable.escribir_json(folder / ('%s_%s.json' % (stamp, g['id'][:6])), g)
        durable.escribir_texto(folder / ('%s_%s.csv' % (stamp, g['id'][:6])), self.csv(), encoding='utf-8-sig')
    def close(self): self.stop_event.set(); self.worker.join(timeout=2); self._flush()

    # ---------- clasificaciones ----------
    def net_laps(self, run, slot):
        d = run['data'][str(slot)]
        if run['kind'] == 'quali': return sum(1 for l in d['laps'] if l['valid'])
        return len(d['laps']) - d['penalty']
    def best(self, run, slot):
        laps = [l['s'] for l in run['data'][str(slot)]['laps'] if l['valid']]
        return min(laps) if laps else None
    def stage_best(self, run):
        runs = [r for r in self.gp['runs'] if r['kind'] == run['kind'] and r['participants']] if run['kind'] == 'quali' else [run]
        vals = [self.best(r, s) for r in runs for s in r['participants']]
        vals = [v for v in vals if v is not None]
        return min(vals) if vals else None
    def quali_results(self):
        g = self.gp; res = []
        for p in g['pilots']:
            run = next((r for r in g['runs'] if r['kind'] == 'quali' and r['participants'] == [p['slot']]), None)
            dd = run['data'].get(str(p['slot'])) if run else None
            res.append({'slot': p['slot'], 'best': self.best(run, p['slot']) if run else None, 'laps': self.net_laps(run, p['slot']) if run else 0,
                        'dsq': bool(isinstance(dd, dict) and dd.get('dsq')), 'banderas': dd.get('banderas', 0) if isinstance(dd, dict) else 0,
                        'sospechosas_n': len(run['data'][str(p['slot'])].get('sospechosas') or []) if run and str(p['slot']) in run['data'] else 0,
                        'done': bool(run and run['phase'] == 'done'), 'skipped': bool(run and run.get('skipped'))})
        order = g['order']
        res.sort(key=lambda r: (r['dsq'], r['best'] is None, r['best'] or 0, order.index(r['slot'])))   # DSQ = al final
        return res
    def quali_order(self):
        if not self.gp['config']['quali_enabled']: return list(self.gp['order'])
        return [r['slot'] for r in self.quali_results()]
    def heat_standings(self):
        g = self.gp; heats = [r for r in g['runs'] if r['kind'] == 'heat' and r['participants'] and r['phase'] != 'ready']
        q = self.quali_order(); res = []
        for p in g['pilots']:
            s = p['slot']; laps = 0; best = None; per = []
            for r in heats:
                n = self.net_laps(r, s) if str(s) in r['data'] else 0; laps += n; per.append(n)
                b = self.best(r, s) if str(s) in r['data'] else None
                if b is not None and (best is None or b < best): best = b
            dsq = any(isinstance(r['data'].get(str(s)), dict) and r['data'][str(s)].get('dsq') for r in heats)
            res.append({'slot': s, 'laps': laps, 'best': best, 'rounds': per, 'dsq': dsq})
        res.sort(key=lambda r: (r['dsq'], -r['laps'], r['best'] is None, r['best'] or 0, q.index(r['slot'])))   # DSQ = al final
        return res
    def heat_standings_slots(self): return [r['slot'] for r in self.heat_standings()]
    def run_rows(self, run):
        g = self.gp; cfg = g['config']; fuel = self.scx.fuel(); rows = []
        for s in run['participants'] or []:
            p = self.pilot(s); d = run['data'][str(s)]; last = d['laps'][-1] if d['laps'] else None
            rows.append({'slot': s, 'name': p['name'], 'avatar': p['avatar'], 'car': p['car'], 'laps': self.net_laps(run, s), 'raw_laps': len(d['laps']),
                         'last': last['s'] if last else None, 'best': self.best(run, s), 'kmh': last['kmh'] if last else None,
                         'fuel': fuel[p['car'] - 1] if cfg['fuel_enabled'] else None,
                         'vida_llanta': fuel[p['car'] - 1] if cfg['fuel_enabled'] else None,   # mismo valor que 'fuel', en %
                         'false_start': d['false_start'], 'penalty': d['penalty'],
                         'started': d['started'], 'finished': d['finished_at'] is not None, 'finish_pos': d['finish_pos'],
                         '_last_cross': d['last_cross'] or 0, 'grid': run['grid'].index(s) + 1 if s in run.get('grid', []) else None,
                         'lap_list': d['laps'][-60:], 'sospechosas': (d.get('sospechosas') or [])[-20:],
                         'sospechosas_n': len(d.get('sospechosas') or []),
                         'dsq': bool(d.get('dsq')), 'banderas': d.get('banderas', 0),
                         'pits': self._pits_view(d, p['car'])})
        if run['kind'] == 'quali':
            key = lambda r: (r['dsq'], r['best'] is None, r['best'] or 0)
        elif run['kind'] == 'final':
            key = lambda r: (r['dsq'], r['finish_pos'] is None, r['finish_pos'] or 0, -r['laps'], r['_last_cross'] if r['laps'] else 0, r['grid'] or 0)
        else:
            key = lambda r: (r['dsq'], -r['laps'], r['_last_cross'] if r['laps'] else 0, r['grid'] or 0)
        rows.sort(key=key)
        # Descalificado: al final y sin posición (en pantalla dice DSQ).
        for i, r in enumerate(rows): r['pos'] = i + 1 if (not r['dsq'] and (r['laps'] > 0 or r['best'] is not None)) else None; r.pop('_last_cross')
        return rows

    # ---------- vistas ----------
    def snapshot(self):
        with self.lock:
            out = {'server_time': time.time(), 'config': self._shown_config(), 'min_lap_s': self.min_lap_s(), 'presets': PRESETS, 'scx': self.scx.summary(), 'gp': None,
                   'boot': getattr(self, 'boot', None), 'avisos': list(getattr(self, 'avisos_servidor', None) or getattr(self, 'avisos', []))}
            g = self.gp
            if not g: return out
            now = time.monotonic(); run = self.current()
            v = {k: copy.deepcopy(g[k]) for k in ['id', 'created_at', 'status', 'config', 'pilots', 'order', 'current', 'events', 'version', 'notice']}
            v['config']['min_lap_s'] = self.min_lap_s()
            for k in FLAG_KEYS: v['config'].setdefault(k, DEFAULTS[k])   # GP guardado antes de la bandera del piloto
            for k in PIT_KEYS: v['config'].setdefault(k, DEFAULTS[k])   # GP guardado antes del tiempo en pits
            for k in TIRE_KEYS: v['config'].setdefault(k, DEFAULTS[k])   # GP guardado antes de la vida de llanta
            v['sospechosas'] = self.suspicious_rows()
            v['runs'] = [{'key': r['key'], 'kind': r['kind'], 'label': r['label'], 'phase': r['phase'], 'skipped': r.get('skipped', False)} for r in g['runs']]
            v['quali'] = self.quali_results() if g['config']['quali_enabled'] else []
            v['heats'] = self.heat_standings() if any(r['kind'] == 'heat' for r in g['runs']) else []
            final = g['runs'][-1]
            v['final'] = self.run_rows(final) if final['participants'] else []
            view_run = run or (final if g['status'] == 'done' else None)
            if view_run:
                rr = {k: view_run.get(k) for k in ['key', 'kind', 'label', 'phase', 'participants', 'grid', 'skipped']}
                rr['rows'] = self.run_rows(view_run)
                rr['countdown_ms'] = max(0, int((view_run['countdown_until'] - now) * 1000)) if view_run['phase'] == 'countdown' else 0
                rr['countdown_total'] = view_run.get('countdown_total', g['config']['lights_seconds'])
                rr['remaining_ms'] = max(0, int((view_run['ends_at'] - now) * 1000)) if view_run.get('ends_at') and view_run['phase'] == 'running' else (0 if view_run.get('ends_at') else None)
                rr['elapsed_ms'] = int((now - view_run['green_at']) * 1000) if view_run.get('green_at') and view_run['phase'] in ('running', 'finishing') else None
                rr['deadline_ms'] = max(0, int((view_run['deadline'] - now) * 1000)) if view_run.get('deadline') and view_run['phase'] == 'finishing' else None
                rr['target_laps'] = g['config']['final_laps'] if view_run['kind'] == 'final' else None
                rr['stage_best'] = self.stage_best(view_run)
                red = view_run.get('red')
                rr['red'] = None
                if red:
                    rel = red['rel']
                    rr['red'] = {'n': red['n'], 'at': red['at'], 'from': red['from'], 'resuming': view_run['phase'] == 'countdown', 'ignored': red.get('ignored', 0),
                                 'kind': red.get('kind', 'red'), 'by': red.get('by'), 'by_name': red.get('by_name'), 'used': red.get('used'), 'max': red.get('max')}
                    rr['remaining_ms'] = max(0, int(rel['ends_at'] * 1000)) if 'ends_at' in rel else None
                    rr['elapsed_ms'] = max(0, int(-rel['green_at'] * 1000)) if 'green_at' in rel else None
                    rr['deadline_ms'] = max(0, int(rel['deadline'] * 1000)) if 'deadline' in rel and red['from'] == 'finishing' else None
                v['run'] = rr
            out['gp'] = v
            return out
    def suspicious_rows(self, include_interrupted=False):
        """Todas las vueltas sospechosas del Gran Premio (para la tabla y el CSV)."""
        g = self.gp; out = []
        name = {p['slot']: p['name'] for p in g['pilots']}
        sources = [(run['label'], run['data'], False) for run in g['runs'] if run['participants']]
        if include_interrupted: sources += [(it['label'] + ' (interrumpida)', it['data'], True) for it in g.get('interrumpidas') or []]
        for label, data, cut in sources:
            for s, d in sorted(data.items(), key=lambda kv: int(kv[0])):
                for x in (d.get('sospechosas') or []) if isinstance(d, dict) else []:
                    out.append(dict(x, parte=label, slot=int(s), name=name.get(int(s), s), interrumpida=cut))
        return out
    def csv(self):
        g = self.gp; buf = io.StringIO(); w = csv.writer(buf)
        name = {p['slot']: p['name'] for p in g['pilots']}; car = {p['slot']: p['car'] for p in g['pilots']}
        f2 = lambda x: '' if x is None else ('%.3f' % x)
        w.writerow(['Puto el último · Gran Premio', time.strftime('%Y-%m-%d %H:%M', time.localtime(g['created_at']))])
        c = g['config']
        w.writerow(['Qualy min', c['quali_minutes'], 'Rondas', c['heats_rounds'], 'Min por ronda', c['heats_minutes'], 'Finalistas', c['finalists'], 'Vueltas final', c['final_laps'], 'Vuelta mínima (s)', self.min_lap_s()])
        if c['quali_enabled']:
            w.writerow([]); w.writerow(['QUALY', 'Posición', 'Piloto', 'Coche', 'Mejor vuelta (s)', 'Vueltas válidas', 'Banderas amarillas', 'Estado', 'Vel. mejor (km/h)'])
            for i, r in enumerate(self.quali_results()):
                w.writerow(['', i + 1 if r['best'] is not None and not r['dsq'] else 'DSQ' if r['dsq'] else '', name[r['slot']], car[r['slot']], f2(r['best']), r['laps'],
                            r.get('banderas', 0), 'DESCALIFICADO' if r['dsq'] else '', scale_kmh_txt(r['best'], c['track_length_m'], c['scale'])])
        if c['heats_rounds']:
            w.writerow([]); w.writerow(['ELIMINATORIAS', 'Posición', 'Piloto', 'Coche', 'Vueltas totales', 'Mejor vuelta (s)'] + ['Ronda %d' % (i + 1) for i in range(c['heats_rounds'])] + ['Estado', 'Vel. mejor (km/h)'])
            for i, r in enumerate(self.heat_standings()): w.writerow(['', 'DSQ' if r['dsq'] else i + 1, name[r['slot']], car[r['slot']], r['laps'], f2(r['best'])] + r['rounds'] + ['DESCALIFICADO' if r['dsq'] else '', scale_kmh_txt(r['best'], c['track_length_m'], c['scale'])])
        final = g['runs'][-1]
        if final['participants']:
            w.writerow([]); w.writerow(['FINAL', 'Posición', 'Piloto', 'Coche', 'Vueltas', 'Mejor vuelta (s)', 'Salida en falso', 'Terminó', 'Banderas amarillas', 'Estado', 'Vel. última (km/h)', 'Vel. mejor (km/h)'])
            for r in self.run_rows(final): w.writerow(['', 'DSQ' if r['dsq'] else r['pos'] or '', r['name'], r['car'], r['laps'], f2(r['best']), 'sí' if r['false_start'] else '', 'sí' if r['finished'] else '',
                                                       r['banderas'], 'DESCALIFICADO' if r['dsq'] else '', scale_kmh_txt(r.get('last'), c['track_length_m'], c['scale']), scale_kmh_txt(r['best'], c['track_length_m'], c['scale'])])
        # Bandera amarilla del piloto: cuántas pidió cada quien por parte, y quién quedó descalificado.
        fl = self.flag_cfg()
        w.writerow([]); w.writerow(['BANDERAS AMARILLAS DEL PILOTO (máximo %d por parte)' % fl['max'], 'Parte', 'Piloto', 'Coche', 'Banderas', 'Estado', 'Hora DSQ', 'Vueltas al DSQ', 'Cruces que ya no contaron'])
        hora_f = lambda t: time.strftime('%H:%M:%S', time.localtime(t)) if t else ''
        anyf = False
        for run in g['runs']:
            for s in run['participants'] or []:
                d = run['data'].get(str(s)) or {}
                if not d.get('banderas') and not d.get('dsq'): continue
                anyf = True; q = d.get('dsq') or {}
                w.writerow(['', run['label'], name[s], car[s], d.get('banderas', 0), 'DESCALIFICADO' if q else '', hora_f(q.get('at')), q.get('laps', '') if q else '', q.get('ignored', '') if q else ''])
        if not anyf: w.writerow(['', 'ninguna'])
        w.writerow([]); w.writerow(['VUELTAS', 'Parte', 'Piloto', 'Vuelta', 'Tiempo (s)', 'km/h escala', 'Válida'])
        for run in g['runs']:
            for s in run['participants'] or []:
                for l in run['data'][str(s)]['laps']: w.writerow(['', run['label'], name[s], l['n'], f2(l['s']), l['kmh'], 'sí' if l['valid'] else 'anulada'])
        if g.get('interrumpidas'):
            # Vueltas de partes cortadas por un reinicio del servidor (no cuentan para el resultado; se repitieron).
            w.writerow([]); w.writerow(['VUELTAS DE PARTES INTERRUMPIDAS (no cuentan)', 'Parte', 'Piloto', 'Vuelta', 'Tiempo (s)', 'km/h escala', 'Válida'])
            for it in g['interrumpidas']:
                for s, d in sorted(it['data'].items()):
                    for l in d.get('laps', []): w.writerow(['', it['label'], name.get(int(s), s), l.get('n'), f2(l.get('s')), l.get('kmh'), 'sí' if l.get('valid') else 'anulada'])
        sus = self.suspicious_rows(include_interrupted=True)
        w.writerow([]); w.writerow(['VUELTAS SOSPECHOSAS (NO CUENTAN · más cortas que la vuelta mínima)', 'Parte', 'Piloto', 'Coche', 'Tiempo (s)', 'Mínimo (s)', 'Hora', 'Seg. desde el verde', 'Fuente', 'Después de la vuelta'])
        hora_s = lambda t: time.strftime('%H:%M:%S', time.localtime(t)) if t else ''
        if not sus: w.writerow(['', 'ninguna'])
        for x in sus:
            w.writerow(['', x['parte'], x['name'], x.get('car') or '', f2(x.get('s')), x.get('min', ''), hora_s(x.get('hora')), '' if x.get('at') is None else x['at'],
                        {'scx': 'Pit Box (tarjeta SCX)', 'ir': 'Sensor IR'}.get(x.get('src'), x.get('src') or ''), x.get('tras_vuelta', '')])
        # Cada parada en pits = CAMBIO DE LLANTAS: vida de llanta al entrar/salir (%) y vueltas/km de ese juego (por parte).
        w.writerow([]); w.writerow(['CAMBIOS DE LLANTAS (PITS)', 'Parte', 'Piloto', 'Coche', 'Parada #', 'Vuelta al entrar', 'Entrada', 'Salida', 'Duración (s)', 'Vida de llanta al entrar (%)', 'Vida de llanta al salir (%)', 'Cómo salió', 'En curso', 'Llanta', 'Vueltas con ese juego', 'Km con ese juego'])
        anyp = False; km_lap = self.km_lap(g['config']); tire = g['config'].get('tire_name') or DEFAULTS['tire_name']
        hora_p = lambda t: time.strftime('%H:%M:%S', time.localtime(t)) if t else ''
        src_p = {'estimado': 'estimada (deja de cargar la Pit Box + gatillo)', 'ir': 'sensor IR de salida', 'timeout': 'tope de tiempo', 'pista': 'cruzó la meta por la pista', 'cierre': 'se terminó la parte', 'reinicio': 'reinicio del servidor'}
        for run in [r for r in g['runs'] if not r.get('skipped')]:
            for s in run['participants'] or []:
                d = run['data'].get(str(s)) or {}
                for i, x in enumerate(pits_mod.paradas_llantas(d.get('paradas'), km_lap), 1):
                    anyp = True
                    w.writerow(['', run['label'], name[s], car[s], i, x.get('lap', ''), hora_p(x.get('entry_at')), hora_p(x.get('exit_at')),
                                '' if x.get('duration_s') is None else '%.1f' % x['duration_s'],
                                '' if x.get('vida_entrada_pct') is None else x['vida_entrada_pct'],
                                '' if x.get('vida_salida_pct') is None else x['vida_salida_pct'],
                                src_p.get(x.get('source_exit'), x.get('source_exit') or ''),
                                'sí' if x.get('abierta') else 'no', tire,
                                '' if x.get('vueltas_juego') is None else x['vueltas_juego'],
                                '' if x.get('km_juego') is None else '%.1f' % x['km_juego']])
        if not anyp: w.writerow(['', 'ninguna'])
        if g.get('pausas') or (self.current() or {}).get('red'):
            w.writerow([]); w.writerow(['PAROS (BANDERA ROJA)', 'Parte', 'Paro #', 'Inicio', 'Duración (s)', 'Reanudado', 'Cruces ignorados', 'Bandera', 'La pidió'])
            hora = lambda t: time.strftime('%H:%M:%S', time.localtime(t)) if t else ''
            tipo = lambda x: 'amarilla (piloto)' if x.get('kind') == 'yellow' else 'roja'
            for p in g.get('pausas') or []:
                w.writerow(['', p['label'], p['n'], hora(p['at']), '%.1f' % p['duration_s'], 'sí' if p.get('resumed_at') else 'no (se terminó la parte)', p.get('ignored_laps', 0), tipo(p), p.get('by_name') or ''])
            run = self.current()
            if run and run.get('red'):
                w.writerow(['', run['label'], run['red']['n'], hora(run['red']['at']), '%.1f' % (time.time() - run['red']['at']), 'en curso', run['red'].get('ignored', 0), tipo(run['red']), run['red'].get('by_name') or ''])
        return buf.getvalue()
    def export_csv(self):
        with self.lock:
            if not self.gp: raise GPError('No hay Gran Premio para exportar.', 404)
            return self.csv()
    def sim_follow(self):
        with self.lock:
            run = self.current()
            if not run: return (None, [])
            if run['kind'] == 'quali': return (run['phase'], [self.pilot(run['participants'][0])['car'] - 1])
            return (run['phase'], [self.pilot(s)['car'] - 1 for s in run['participants'] if run['data'][str(s)]['finished_at'] is None])
