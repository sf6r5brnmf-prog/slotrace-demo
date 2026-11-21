"""«Mi coche»: lo que ve UN piloto en su teléfono (solo lectura).

Junta la sesión de Práctica/Carrera (/api/live) y el Gran Premio (/api/gp) y devuelve únicamente los datos de
ese piloto: su coche, vueltas, última, mejor, posición, diferencia, vida de llanta, fase y semáforo.
(La vida de llanta es el nivel D6 de la Pit Box en %; la clave sigue siendo 'fuel' y se agrega 'vida_llanta'.)
Funciones puras sobre las mismas instantáneas que ya arma el servidor, para poder probarlas sin red.
"""
import handicap as handicap_mod

COLORS = [('Blanco', '#edf2f7'), ('Amarillo', '#ffe23b'), ('Rojo', '#ff4d50'), ('Azul', '#3d96ff'), ('Verde', '#50dc92'), ('Naranja', '#ff963d')]
GP_KIND = {'quali': 'Qualy', 'heat': 'Eliminatoria', 'final': 'Final'}
LIVE_PHASE = {'ready': 'Listos · esperando Empezar en la pantalla grande', 'countdown': '¡Semáforo! No aceleres antes del verde',
              'resetting': 'Preparando la salida…', 'waiting_sensor': 'Esperando al sensor para la salida…', 'running': 'En carrera',
              'paused': 'Turno en pausa', 'ended': 'Sesión terminada'}
RED_TEXT = '🚩 BANDERA ROJA · PARO: suelta el gatillo'
YELLOW_TEXT = '🟨 BANDERA AMARILLA · la pidió %s: suelta el gatillo'
FLAG_DEFAULTS = {'enabled': True, 'clicks': 3, 'window_s': 1.5, 'max': 4, 'dsq': True}
RESUME_TEXT = '🚦 Reanudación: semáforo, no aceleres antes del verde'
GP_PHASE = {'ready': 'Listos · esperando Empezar en la pantalla grande', 'countdown': '¡Semáforo! No aceleres antes del verde',
            'running': 'En carrera', 'finishing': 'Bandera: termina tu vuelta', 'done': 'Terminado', 'red': RED_TEXT}
GP_BUSY = ('countdown', 'running', 'finishing', 'red')
LIVE_BUSY = ('countdown', 'resetting', 'waiting_sensor', 'running', 'paused')
DASH_DEFAULTS = {'speed_max_kmh': 300, 'fuel_red_pct': 25, 'fuel_enabled': True, 'track_length_m': 25.0, 'scale': 32,
                 'lights_seconds': 3, 'sound_enabled': True, 'sound_volume': 80, 'tire_name': 'Media', 'tire_red_pct': 20}
MY_EVENTS = ('false_start', 'best', 'winner', 'finish', 'quali_done', 'suspicious', 'yellow_flag', 'dsq', 'pit_entry', 'pit_exit')


def _banderas(used, dsq, cfg, activa=False, tuya=False):
    """Bandera amarilla del piloto: «🟨 2/4», si está DESCALIFICADO y si la bandera activa la pidió él."""
    cfg = dict(FLAG_DEFAULTS, **(cfg or {}))
    return {'on': bool(cfg['enabled']), 'usadas': int(used or 0), 'max': int(cfg['max']), 'clics': int(cfg['clicks']),
            'ventana_s': cfg['window_s'], 'dsq': bool(dsq), 'descalifica': bool(cfg['dsq']), 'activa': bool(activa), 'tuya': bool(tuya),
            'texto': 'DESCALIFICADO' if dsq else '🟨 %d/%d' % (int(used or 0), int(cfg['max']))}


def _gp_flag_cfg(cfg):
    cfg = cfg or {}
    return {'enabled': cfg.get('pilot_flag_enabled', True), 'clicks': cfg.get('pilot_flag_clicks', 3), 'window_s': cfg.get('pilot_flag_window_s', 1.5),
            'max': cfg.get('pilot_flag_max', 4), 'dsq': cfg.get('pilot_flag_dsq', True)}


def _sospechosas(lst, total=None, minimum=None):
    """Vueltas más cortas que la mínima (no contaron): cuántas y las últimas 5 (la más nueva primero)."""
    lst = lst or []
    return {'n': total if isinstance(total, int) and total >= len(lst) else len(lst), 'min': minimum,
            'lista': [{'s': x.get('s'), 'hora': x.get('hora'), 'src': x.get('src')} for x in lst[-5:]][::-1]}


def piloto_de(roster, slot):
    """El piloto registrado en ese lugar (0–5) o None."""
    if type(slot) != int or not 0 <= slot < 6: return None
    p = (roster or {}).get('slots', [None] * 6)[slot]
    if not p: return None
    name, hexa = COLORS[slot]
    return {'slot': slot, 'name': p['name'], 'avatar': p['avatar'], 'revision': p.get('revision'), 'color': hexa, 'color_name': name}


def slot_desde_parametro(roster, valor):
    """?piloto=Ernesto (sin importar mayúsculas/acentos tal cual) o ?piloto=1..6 (lugar del registro)."""
    if valor is None: return None
    v = str(valor).strip()
    if not v: return None
    slots = (roster or {}).get('slots', [])
    for i, p in enumerate(slots):
        if p and p['name'].strip().casefold() == v.casefold(): return i
    if v.isdigit() and 1 <= int(v) <= 6 and int(v) - 1 < len(slots) and slots[int(v) - 1]: return int(v) - 1
    return None


def elegir_fuente(live_snap, gp_snap):
    """¿Qué se está corriendo ahorita? 'gp', 'live' o None. Lo que está en pista manda; luego lo abierto; luego lo último."""
    s = (live_snap or {}).get('session'); g = (gp_snap or {}).get('gp')
    if g and g.get('status') == 'cancelled': g = None
    run = (g or {}).get('run')
    if g and g.get('status') == 'active' and run and run.get('phase') in GP_BUSY: return 'gp'
    if s and s.get('phase') in LIVE_BUSY: return 'live'
    if g and g.get('status') == 'active': return 'gp'
    if s and s.get('phase') != 'ended': return 'live'
    if g and s: return 'gp' if (g.get('created_at') or 0) >= (s.get('created_at') or 0) else 'live'
    if g: return 'gp'
    if s: return 'live'
    return None


def _fmt_gap(seconds):
    return None if seconds is None else '+%.2f s' % seconds


def _pits(src):
    """Resumen de pits (EN PITS, paradas, última, total) si ya viene en la instantánea."""
    if not isinstance(src, dict):
        return {'en_pits': False, 'elapsed_s': None, 'entry_at': None, 'paradas': 0, 'completadas': 0,
                'ultima_s': None, 'total_s': 0.0, 'fuel_before': None, 'fuel_after': None, 'source_exit': None,
                'vida_entrada_pct': None, 'vida_salida_pct': None, 'llanta': None}
    return {k: src.get(k) for k in ('en_pits', 'elapsed_s', 'entry_at', 'paradas', 'completadas', 'ultima_s', 'total_s', 'fuel_before', 'fuel_after', 'source_exit',
                                    'vida_entrada_pct', 'vida_salida_pct', 'llanta')}

def _vista_live(s, live_snap, slot, dash):

    me = next((p for p in s['pilots'] if p['slot'] == slot), None)
    typ = 'practica' if s.get('type') == 'practice' else 'carrera'
    mode_title = 'El último paga las chelas' if s.get('mode') == 'chelas' else 'Puto el último'
    sesion = {'fuente': typ, 'id': s['id'], 'version': s.get('version', 0), 'control': s.get('control', 0), 'created_at': s.get('created_at'),
              'titulo': 'Práctica' if typ == 'practica' else 'Carrera · ' + mode_title, 'etapa': None, 'fase': s['phase'],
              'fase_texto': LIVE_PHASE.get(s['phase'], ''), 'countdown_ms': s.get('countdown_ms', 0),
              'countdown_total': s.get('countdown_total') or dash.get('lights_seconds') or 3,
              'semaforo_label': 'PRÁCTICA' if typ == 'practica' else 'CARRERA · ' + mode_title, 'starts_at': s.get('starts_at'),
              'participantes': len(s['pilots']), 'remaining_ms': None, 'target_laps': None, 'aviso': None,
              'elapsed_ms': s.get('elapsed_ms'), 'paro': None}
    rf = s.get('red_flag')
    if rf:
        resuming = s['phase'] == 'countdown'
        sesion['paro'] = {'n': rf.get('n'), 'at': rf.get('at'), 'reanudando': resuming, 'tipo': rf.get('kind', 'red'), 'pidio': rf.get('by_name'), 'usadas': rf.get('used'), 'max': rf.get('max')}
        sesion['fase_texto'] = RESUME_TEXT if resuming else (YELLOW_TEXT % rf.get('by_name') if rf.get('kind') == 'yellow' else RED_TEXT)
    if me is None: return 'no_estas', sesion, None
    scx_mode = s.get('lap_source') == 'scx'; scx_on = s.get('lap_source') in ('scx', 'both')
    cars = ((live_snap.get('laps_config') or {}).get('cars') or [])
    car = cars[slot] if slot < len(cars) and isinstance(cars[slot], int) else slot + 1
    raw_best = lambda p: min(l['s'] for l in p['laps']) if p['laps'] else None
    hon = bool((s.get('handicap') or {}).get('on'))
    # Handicap: posición, diferencia y «el último» con la mejor vuelta + segundos de la clase de su coche.
    best = lambda p: handicap_mod.mas(raw_best(p), p.get('h_s') or 0.0) if hon else raw_best(p)
    dsq = bool(me.get('dsq')); anydsq = any(p.get('dsq') for p in s['pilots'])
    # Descalificados: sin posición y al final (en Carrera, el descalificado es «el último»).
    timed = [p for p in s['pilots'] if p['laps'] and not p.get('dsq')]
    mine = best(me); last = me['laps'][-1] if me['laps'] else None
    leader = min((best(p) for p in timed), default=None); worst = max((best(p) for p in timed), default=None)
    rank = 1 + sum(1 for p in timed if best(p) < mine) if mine is not None and not dsq else None
    gap = round(mine - leader, 3) if mine is not None and leader is not None and rank and rank > 1 else None
    ended = s['phase'] == 'ended'
    scx = live_snap.get('scx') or {}
    raw_fuel = (scx.get('fuel') or [None] * 6)[car - 1] if scx.get('connected') and 1 <= car <= 6 else None
    fuel = raw_fuel if dash.get('fuel_enabled', True) and isinstance(raw_fuel, (int, float)) else None
    # El aviso general de la sesión solo si no habla de otro piloto.
    otros = [p['name'] for p in s['pilots'] if p['slot'] != slot]
    notice = s.get('notice') or ''
    # Los avisos de «aprieta Empezar» son para la pantalla grande: aquí no hay Empezar.
    sesion['aviso'] = notice if notice and 'Empezar' not in notice and not any(n and n in notice for n in otros) else None
    hs = (me.get('h_s') or 0.0) if hon else 0.0
    datos = {'car': car, 'por_turnos': not scx_on, 'laps': len(me['laps']), 'last': last['s'] if last else None, 'best': raw_best(me),
             'handicap_on': hon, 'h_s': hs, 'clase_txt': me.get('clase_txt'), 'best_h': mine, 'last_h': handicap_mod.mas(last['s'], hs) if last else None,
             'kmh': float(last['escala']) if last and isinstance(last.get('escala'), (int, float)) else None, 'fuel': fuel,
             'pos': rank, 'total': len(timed), 'gap': gap, 'gap_texto': _fmt_gap(gap), 'gap_vueltas': None,
             'en_pista': (not ended) and not rf and (s['phase'] == 'running' if scx_mode else s.get('active') == slot),
             'turno_tuyo': (not scx_mode) and (s.get('active') == slot or (s['phase'] == 'ready' and s.get('pending_active') == slot)),
             'ultimo': typ == 'carrera' and (dsq or (not anydsq and mine is not None and mine == worst)),
             'dsq': dsq,
             'banderas': _banderas(me.get('banderas'), dsq, s.get('bandera_cfg'), bool(rf and rf.get('kind') == 'yellow'), bool(rf and rf.get('by') == slot)),
             'false_start': False, 'penalty': 0, 'finished': ended, 'finish_pos': rank if ended else None, 'grid': None,
             'vueltas_lista': [{'n': l['n'], 's': l['s'], 'sh': handicap_mod.mas(l['s'], hs), 'kmh': l.get('escala')} for l in me['laps'][-8:]][::-1],
             'sospechosas': _sospechosas(me.get('sospechosas'), me.get('sospechosas_n'), s.get('min_lap_s') or (live_snap.get('laps_config') or {}).get('min_lap_s')),
             'pits': _pits(me.get('pits'))}
    if dsq: datos.update(en_pista=False, gap=None, gap_texto=None, finish_pos=None); sesion['aviso'] = None   # el teléfono ya lo dice en rojo (datos.dsq)
    return 'en_sesion', sesion, datos


def _vista_gp(g, gp_snap, slot, dash):
    run = g.get('run') or {}
    cfg = g.get('config') or {}
    me = next((p for p in g['pilots'] if p['slot'] == slot), None)
    phase = run.get('phase') if g.get('status') == 'active' else 'done'
    etapa = GP_KIND.get(run.get('kind'), '') if run else ''
    sesion = {'fuente': 'gp', 'id': g['id'], 'version': g.get('version', 0), 'control': g.get('current', 0), 'created_at': g.get('created_at'),
              'titulo': 'Gran Premio', 'etapa': run.get('label') or etapa, 'etapa_tipo': run.get('kind'), 'fase': phase,
              'fase_texto': GP_PHASE.get(phase, ''), 'countdown_ms': run.get('countdown_ms', 0) if phase == 'countdown' else 0,
              'countdown_total': run.get('countdown_total') or cfg.get('lights_seconds') or 3, 'semaforo_label': run.get('label') or 'GRAN PREMIO',
              'starts_at': None, 'participantes': len(run.get('rows') or []), 'remaining_ms': run.get('remaining_ms'),
              'target_laps': run.get('target_laps'), 'aviso': None, 'gp_terminado': g.get('status') == 'done',
              'elapsed_ms': run.get('elapsed_ms'), 'paro': None}
    red = run.get('red') if g.get('status') == 'active' else None
    if red:
        sesion['paro'] = {'n': red.get('n'), 'at': red.get('at'), 'reanudando': bool(red.get('resuming')), 'tipo': red.get('kind', 'red'), 'pidio': red.get('by_name'), 'usadas': red.get('used'), 'max': red.get('max')}
        if red.get('resuming'): sesion['fase_texto'] = RESUME_TEXT
        elif red.get('kind') == 'yellow': sesion['fase_texto'] = YELLOW_TEXT % red.get('by_name')
    if me is None: return 'no_estas', sesion, None
    scx = gp_snap.get('scx') or {}
    car = me.get('car', slot + 1)
    rows = run.get('rows') or []
    row = next((r for r in rows if r['slot'] == slot), None)
    evs = [{'id': e['id'], 'type': e['type'], 'text': e['text'], 'at': e.get('at')} for e in (g.get('events') or [])
           if e.get('slot') == slot and e.get('type') in MY_EVENTS][-4:]
    raw_fuel = (scx.get('fuel') or [None] * 6)[car - 1] if scx.get('connected') and 1 <= car <= 6 else None
    fuel = raw_fuel if cfg.get('fuel_enabled', True) and isinstance(raw_fuel, (int, float)) else None
    quali = g.get('quali') or []
    qmine = next((q for q in quali if q['slot'] == slot), None)
    hon = bool((g.get('handicap') or {}).get('on')); qb = 'best_h' if hon else 'best'
    hs = (me.get('h_s') or 0.0) if hon else 0.0
    base = {'car': car, 'por_turnos': False, 'laps': 0, 'last': None, 'best': None, 'kmh': None, 'fuel': fuel, 'pos': None, 'total': len(rows),
            'gap': None, 'gap_texto': None, 'gap_vueltas': None, 'en_pista': False, 'turno_tuyo': False, 'ultimo': False,
            'false_start': False, 'penalty': 0, 'finished': False, 'finish_pos': None, 'grid': None, 'vueltas_lista': [], 'eventos': evs,
            'sospechosas': _sospechosas([], 0, cfg.get('min_lap_s')), 'dsq': False,
            'banderas': _banderas(0, False, _gp_flag_cfg(cfg)),
            'pits': _pits(None),
            'handicap_on': hon, 'h_s': hs, 'clase_txt': me.get('clase_txt'), 'best_h': None, 'last_h': None,
            'qualy': {'best': qmine['best'], 'best_h': qmine.get('best_h'), 'laps': qmine['laps'], 'done': qmine['done'],
                      'dsq': bool(qmine.get('dsq')),
                      'pos': (1 + sum(1 for q in quali if q.get(qb) is not None and not q.get('dsq') and q[qb] < qmine[qb])) if qmine and qmine.get(qb) is not None and not qmine.get('dsq') else None,
                      'total': len(quali)} if qmine else None}
    if g.get('status') == 'done':
        fin = next((r for r in (g.get('final') or []) if r['slot'] == slot), None)
        if fin:
            base.update(laps=fin['laps'], best=fin['best'], last=fin.get('last'), pos=fin.get('finish_pos') or fin.get('pos'), best_h=fin.get('best_h') if hon else fin['best'], last_h=fin.get('last_h') if hon else fin.get('last'),
                        finish_pos=fin.get('finish_pos') or fin.get('pos'), finished=True, total=len(g.get('final') or []),
                        false_start=fin.get('false_start', False), penalty=fin.get('penalty', 0), kmh=fin.get('kmh'),
                        dsq=bool(fin.get('dsq')), banderas=_banderas(fin.get('banderas'), fin.get('dsq'), _gp_flag_cfg(cfg)),
                        pits=_pits(fin.get('pits')))
            return 'en_sesion', sesion, base
        sesion['aviso'] = 'Esta vez no entraste a la final.'
        return 'fuera', sesion, base
    if row is None:
        if run.get('kind') == 'quali':
            corre = rows[0]['name'] if rows else ''
            sesion['aviso'] = ('Tu qualy ya quedó. Ahora corre ' + corre + '.') if qmine and qmine['done'] else ('Corre ' + corre + '. Espera tu turno de qualy.')
            return 'espera_turno', sesion, base
        sesion['aviso'] = 'No pasaste a la final. Ve la carrera en la pantalla grande.' if run.get('kind') == 'final' else 'No corres en esta parte.'
        return 'fuera', sesion, base
    lap_list = row.get('lap_list') or []
    base.update(laps=row['laps'], last=row['last'], best=row['best'], kmh=row.get('kmh'), false_start=row.get('false_start', False),
                best_h=row.get('best_h') if hon else row['best'], last_h=row.get('last_h') if hon else row['last'],
                penalty=row.get('penalty', 0), finished=row.get('finished', False), finish_pos=row.get('finish_pos'), grid=row.get('grid'),
                en_pista=phase in ('running', 'finishing') and not row.get('finished'), turno_tuyo=True,
                vueltas_lista=[{'n': l.get('n'), 's': l.get('s'), 'sh': l.get('sh', l.get('s')) if hon else l.get('s'), 'kmh': l.get('kmh'), 'valid': l.get('valid', True)} for l in lap_list[-8:]][::-1],
                sospechosas=_sospechosas(row.get('sospechosas'), row.get('sospechosas_n'), cfg.get('min_lap_s')),
                dsq=bool(row.get('dsq')),
                banderas=_banderas(row.get('banderas'), row.get('dsq'), _gp_flag_cfg(cfg), bool(red and red.get('kind') == 'yellow'), bool(red and red.get('by') == slot)),
                pits=_pits(row.get('pits')))
    if run.get('kind') == 'quali':
        # Qualy: posición contra la tabla de qualy (incluye su mejor vuelta en vivo).
        bests = [q[qb] for q in quali if q['slot'] != slot and q.get(qb) is not None and not q.get('dsq')]
        mb = row.get('best_h') if hon else row['best']
        if mb is not None:
            base['pos'] = 1 + sum(1 for b in bests if b < mb)
            top = min(bests + [mb])
            base['gap'] = round(mb - top, 3) if mb > top else None
            base['gap_texto'] = _fmt_gap(base['gap'])
        base['total'] = len(quali) or 1
    else:
        base['pos'] = row.get('finish_pos') or row.get('pos')
        leader = max((r['laps'] for r in rows), default=0)
        if base['pos'] and base['pos'] > 1:
            d = leader - row['laps']; base['gap_vueltas'] = d
            base['gap_texto'] = 'misma vuelta que el líder' if d == 0 else ('−%d vuelta%s del líder' % (d, '' if d == 1 else 's'))
    if row.get('dsq'):
        # Descalificado en esta parte: sin posición ni diferencia; ya no está en pista para la app.
        base.update(en_pista=False, pos=None, gap=None, gap_texto=None, gap_vueltas=None, finish_pos=None)
        sesion['aviso'] = None   # el teléfono ya lo dice en rojo (datos.dsq)
    return 'en_sesion', sesion, base


def vista(roster, live_snap, gp_snap, slot):
    """Respuesta de /api/micoche para un piloto (lugar 0–5 del registro)."""
    live_snap = live_snap or {}; gp_snap = gp_snap or {}
    dash = dict(DASH_DEFAULTS); dash.update(live_snap.get('dashboard') or {})
    out = {'boot': live_snap.get('boot') or gp_snap.get('boot'), 'avisos': live_snap.get('avisos') or gp_snap.get('avisos') or [],
           'server_time': gp_snap.get('server_time'), 'dashboard': dash,
           'scx': {'connected': bool((live_snap.get('scx') or {}).get('connected'))},
           'piloto': piloto_de(roster, slot), 'estado': None, 'sesion': None, 'datos': None}
    if out['piloto'] is None:
        out['estado'] = 'sin_piloto'; return out
    src = elegir_fuente(live_snap, gp_snap)
    if src is None:
        out['estado'] = 'sin_sesion'; return out
    if src == 'gp':
        g = gp_snap['gp']; cfg = g.get('config') or {}
        for k in ('speed_max_kmh', 'fuel_red_pct', 'fuel_enabled', 'track_length_m', 'scale', 'lights_seconds', 'sound_enabled', 'sound_volume', 'tire_name', 'tire_red_pct'):
            if k in cfg: dash[k] = cfg[k]
        out['estado'], out['sesion'], out['datos'] = _vista_gp(g, gp_snap, slot, dash)
    else:
        out['estado'], out['sesion'], out['datos'] = _vista_live(live_snap['session'], live_snap, slot, dash)
    if isinstance(out['datos'], dict):
        out['datos']['vida_llanta'] = out['datos'].get('fuel')   # mismo valor, en %: vida de llanta
    return out


def vista_torneo(live_snap, gp_snap, tslot, turno):
    """/api/micoche?torneo=N: un piloto del torneo por mangas (no está en el registro de 6). Solo lectura.
    Además de su coche en vivo (cuando corre), dice cuándo le toca: manga, coche y cuántas mangas faltan."""
    live_snap = live_snap or {}; gp_snap = gp_snap or {}
    dash = dict(DASH_DEFAULTS); dash.update(live_snap.get('dashboard') or {})
    out = {'boot': live_snap.get('boot') or gp_snap.get('boot'), 'avisos': live_snap.get('avisos') or gp_snap.get('avisos') or [],
           'server_time': gp_snap.get('server_time'), 'dashboard': dash,
           'scx': {'connected': bool((live_snap.get('scx') or {}).get('connected'))},
           'piloto': None, 'estado': 'sin_piloto', 'sesion': None, 'datos': None, 'torneo': turno}
    g = gp_snap.get('gp')
    if not g or g.get('mode') != 'torneo' or g.get('status') == 'cancelled' or turno is None: return out
    me = next((p for p in g['pilots'] if p['slot'] == tslot), None)
    if me is None: return out
    car = turno.get('car') or me.get('car') or 1
    name, hexa = COLORS[(car - 1) % 6]
    out['piloto'] = {'slot': tslot, 'torneo': True, 'name': me['name'], 'avatar': me.get('avatar') or '', 'revision': None,
                     'color': hexa, 'color_name': (turno.get('nivel_txt') or name), 'nivel': me.get('nivel')}
    cfg = g.get('config') or {}
    for k in ('speed_max_kmh', 'fuel_red_pct', 'fuel_enabled', 'track_length_m', 'scale', 'lights_seconds', 'sound_enabled', 'sound_volume', 'tire_name', 'tire_red_pct'):
        if k in cfg: dash[k] = cfg[k]
    g2 = dict(g, pilots=[dict(p, car=(car if p['slot'] == tslot else p.get('car'))) for p in g['pilots']])
    estado, sesion, datos = _vista_gp(g2, gp_snap, tslot, dash)
    sesion['titulo'] = 'Torneo por mangas'
    if estado in ('fuera', 'espera_turno', 'no_estas') or (g.get('status') == 'done' and estado == 'en_sesion' and turno.get('estado') != 'finalista' and turno.get('estado') != 'campeon'):
        if turno.get('estado') == 'eliminado': estado = 'fuera'
        elif g.get('status') == 'done': estado = 'fuera'
        else: estado = 'espera_turno'
        sesion['aviso'] = turno.get('texto') or sesion.get('aviso')
    if isinstance(datos, dict):
        datos['vida_llanta'] = datos.get('fuel'); datos['car'] = car
    out.update(estado=estado, sesion=sesion, datos=datos)
    return out
