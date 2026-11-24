"""Torneo por mangas (Gran Premio con 7 o más pilotos inscritos).

Así funciona (lo pidió Ernesto):
  · Se inscriben 7 o más pilotos (12 o más es lo normal), cada uno con su nivel: Novato, Intermedio o Experto.
  · Coches por manga: se eligen en Configuración (2 a 6; 3 de fábrica). La app arma las mangas sola.
  · En cada manga se suman vueltas en el tiempo de la manga; el ÚLTIMO de cada manga queda eliminado.
  · La siguiente ronda vuelve a sortear las mangas con los que siguen vivos, hasta que quedan 6.
  · Si en una ronda eliminar a todos los últimos dejaría menos de 6, solo se eliminan los que hagan falta:
    los peores últimos lugares (menos vueltas y, con las mismas vueltas, más tiempo total; con handicap, el ajustado).
  · Final de 6: con 6 coches por manga es UNA carrera (gana el primero en N vueltas; con handicap, el menor tiempo
    total ajustado). Con menos coches, la final se corre en mangas seguidas del mismo tiempo y gana quien sume más
    vueltas (desempata el menor tiempo total).
  · SCX Digital: los coches se cambian de carril solos, así que NO hay rotación de carriles.
  · El handicap por clase de coche (Con imán / Sin imán / Modificado) sigue aplicando: cada coche lleva su clase.

Las mangas se arman AGRUPANDO por nivel (de fábrica): expertos con expertos, novatos con novatos. Como en cada manga
se elimina al último, agrupar por nivel hace que cada quien pelee contra pilotos parecidos y que el novato no sea
siempre el eliminado. La opción «mezclar niveles» (serpentina) también existe en Configuración.
Todo lo que corre una manga (semáforo, salida en falso, vueltas, banderas, pits, PARO) es el motor del Gran Premio.
"""
import copy, math, random, re, shutil, time, uuid
import durable
import handicap as handicap_mod

NIVELES = (('experto', 'Experto'), ('intermedio', 'Intermedio'), ('novato', 'Novato'))
NIVEL_TXT = dict(NIVELES)
NIVEL_RANK = {k: i for i, (k, _) in enumerate(NIVELES)}
MIN_PILOTOS = 7          # con 6 o menos no hay a quién eliminar: es un Gran Premio normal
FINALISTAS = 6
MAX_PILOTOS = 60
MAX_NOMBRE = 24


NIVEL_COLOR = {'experto': '#ffd23b', 'intermedio': '#3d96ff', 'novato': '#50dc92'}


def casco_svg(name, nivel):
    """Avatar de casco (color por nivel + iniciales) para los inscritos que no tienen foto en el registro."""
    from urllib.parse import quote
    ini = ''.join(w[0] for w in name.split()[:2]).upper() or '?'
    ini = ''.join(ch for ch in ini if ch.isalnum())[:2] or '?'
    col = NIVEL_COLOR.get(nivel, '#3d96ff')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" rx="18" fill="#141922"/>'
           '<path d="M18 74c0-30 20-50 46-50 22 0 38 16 38 40v14H58l-6 10H24c-4 0-6-3-6-6z" fill="%s"/>'
           '<path d="M62 46h38c2 6 2 12 2 18H62z" fill="#0b0d11"/><path d="M64 50h32" stroke="#c6ff3d" stroke-width="3"/>'
           '<text x="40" y="72" font-family="Arial,Helvetica,sans-serif" font-size="26" font-weight="900" fill="#0b0d11" text-anchor="middle">%s</text></svg>') % (col, ini)
    return 'data:image/svg+xml;charset=utf-8,' + quote(svg)


class TorneoError(Exception):
    def __init__(self, message, status=400): super().__init__(message); self.status = status


def limpiar_nombre(v):
    if not isinstance(v, str): raise TorneoError('Escribe el nombre de cada piloto.')
    v = ' '.join(v.split())[:MAX_NOMBRE]
    if not v: raise TorneoError('Hay un piloto sin nombre.')
    return v


def limpiar_inscritos(raw):
    """Lista de inscritos [{id, name, nivel}] validada (nombres sin repetir)."""
    if not isinstance(raw, list): raise TorneoError('Lista de pilotos inválida.')
    if len(raw) > MAX_PILOTOS: raise TorneoError('Máximo %d pilotos.' % MAX_PILOTOS)
    out = []; vistos = set()
    for p in raw:
        if not isinstance(p, dict): raise TorneoError('Lista de pilotos inválida.')
        name = limpiar_nombre(p.get('name'))
        if name.casefold() in vistos: raise TorneoError('El nombre «%s» está repetido. Ponle apellido o apodo.' % name)
        vistos.add(name.casefold())
        nivel = p.get('nivel', 'intermedio')
        if nivel not in NIVEL_TXT: raise TorneoError('Nivel inválido para %s: Novato, Intermedio o Experto.' % name)
        pid = p.get('id') if isinstance(p.get('id'), str) and re.fullmatch(r'[a-z0-9]{1,16}', p.get('id') or '') else uuid.uuid4().hex[:10]
        q = {'id': pid, 'name': name, 'nivel': nivel}
        for k in ('sugerido', 'nivel_cambio'):   # nivel automático por tiempo (ver handicap.aplicar_nivel)
            x = handicap_mod.limpiar_sugerido(p.get(k))
            if x: q[k] = x
        out.append(q)
    return out


class Inscritos:
    """Pilotos del torneo con su nivel, guardados en data/inscritos.json (se quedan para el siguiente torneo)."""
    def __init__(self, directory):
        self.path = directory / 'inscritos.json'
        self.avisos = []
        doc, aviso = durable.leer_json(self.path, validate=lambda d: {'pilotos': limpiar_inscritos(d.get('pilotos') if isinstance(d, dict) else None)},
                                       nombre='inscritos.json (pilotos del torneo)')
        if aviso: self.avisos.append(aviso)
        self.pilotos = limpiar_inscritos(doc['pilotos']) if doc else []
        self.version = 1
    def read(self): return {'pilotos': copy.deepcopy(self.pilotos), 'version': self.version, 'niveles': [list(x) for x in NIVELES], 'minimo': MIN_PILOTOS}
    def write(self, payload):
        if not isinstance(payload, dict): raise TorneoError('Datos inválidos.')
        self.pilotos = limpiar_inscritos(payload.get('pilotos'))
        self.version += 1
        durable.escribir_json(self.path, {'pilotos': self.pilotos}, backup=True, indent=2)
        return self.read()


def tamanos(n, c):
    """Cuántos pilotos por manga: lo más parejo posible, nunca más de c. Un grupo de 1 es «pase directo»."""
    k = max(1, math.ceil(n / c)); base, extra = divmod(n, k)
    return [base + 1] * extra + [base] * (k - extra)


class TorneoMixin:
    """Se mezcla en GrandPrix (gp.py). g['mode'] == 'torneo'."""

    # ---------- utilidades ----------
    def es_torneo(self, g=None):
        g = self.gp if g is None else g
        return bool(g and g.get('mode') == 'torneo')
    def car_of(self, run, slot):
        """Coche (mando 1-6) de ese piloto en esa parte. En el torneo cambia en cada manga."""
        if run is not None:
            c = (run.get('cars') or {}).get(str(slot))
            if c: return c
        return self.pilot(slot)['car']
    def _t(self): return self.gp['torneo']
    def _minutes_torneo(self): return float(self.gp['config'].get('torneo_minutes', 3.0))

    # ---------- crear ----------
    def _create_torneo(self, payload, roster):
        g = self.gp
        if g and g['status'] == 'active': raise TorneoError('Ya hay un Gran Premio en curso. Termínalo o cancélalo primero.', 409)
        lista = limpiar_inscritos(payload.get('pilotos'))
        if len(lista) < MIN_PILOTOS:
            raise TorneoError('El torneo por mangas necesita %d pilotos o más (con 6 o menos no hay a quién eliminar: usa el Gran Premio normal).' % MIN_PILOTOS)
        self.set_config({})
        cfg = copy.deepcopy(self.config)
        c = int(cfg.get('torneo_cars', 3))
        if g: self._archive()
        # Foto del registro si el nombre coincide con un piloto registrado (si no, la pantalla dibuja un casco).
        reg = {p['name'].strip().casefold(): p for p in (roster or {}).get('slots', []) if p}
        pilots = []
        for i, p in enumerate(lista):
            avatar = ''
            rp = reg.get(p['name'].casefold())
            if rp and rp.get('avatar'):
                src = self.directory / rp['avatar'].lstrip('/'); avatar = '/avatars/' + uuid.uuid4().hex + '.png'
                try: shutil.copyfile(src, self.directory / avatar.lstrip('/'))
                except OSError: avatar = rp['avatar']
            pilots.append({'slot': i, 'name': p['name'], 'avatar': avatar or casco_svg(p['name'], p['nivel']), 'car': None, 'nivel': p['nivel'], 'ins_id': p['id']})
        gt = getattr(self.scx, 'gatillo', None)
        if gt is not None: gt.reset_session()
        self.gp = g = {'id': uuid.uuid4().hex, 'created_at': time.time(), 'status': 'active', 'config': cfg, 'pilots': pilots,
                       'order': [p['slot'] for p in pilots], 'runs': [], 'current': 0, 'events': [], 'event_id': self.event_id,
                       'version': 1, 'notice': '', 'handicap_v': 1, 'mode': 'torneo',
                       'torneo': {'cars': c, 'agrupar': cfg.get('torneo_agrupar', 'nivel'), 'rondas': [], 'eliminados': [], 'final': None}}
        self._torneo_ronda(sorted(p['slot'] for p in pilots))
        g['current'] = g['torneo']['rondas'][0]['runs'][0]
        self._prepare(g['runs'][g['current']]); self._touch()
        return self.snapshot()

    # ---------- sorteo de mangas ----------
    def _fuerza(self, slot, ronda_prev):
        """Qué tan bien le fue en la ronda anterior (más alto = mejor): vueltas y luego menos tiempo total."""
        if not ronda_prev: return (0, 0, 0)
        for ri in ronda_prev['runs']:
            run = self.gp['runs'][ri]
            if slot in (run['participants'] or []):
                r = next(x for x in self.run_rows(run) if x['slot'] == slot)
                return self._score(r)
        return (0, 0, 0)
    def _score(self, r):
        """Para comparar pilotos de mangas distintas (mismo tiempo de manga): más alto = mejor."""
        T = r.get('total_h') if self.h_on(None) else r.get('total')
        if T is None: T = r.get('total')
        B = (r.get('best_h') if self.h_on(None) else None) or r.get('best')
        # Desempate final: la mejor vuelta (más rápida = mejor).
        return (0 if r.get('dsq') else 1, r.get('laps') or 0, -(T if T is not None else 1e9), -(B if B is not None else 1e9))
    def _ordenar(self, slots, ronda_prev, n_ronda):
        """De más fuerte a menos fuerte: nivel (Experto → Novato) y, desde la ronda 2, cómo le fue en la anterior.
        En la ronda 1, dentro de cada nivel, al azar (sorteo)."""
        rnd = random.Random(self.gp['id'] + ':%d' % n_ronda)
        tmp = list(slots); rnd.shuffle(tmp)
        nivel = lambda s: NIVEL_RANK.get(self.pilot(s).get('nivel'), 1)
        tmp.sort(key=lambda s: (nivel(s), tuple(-x for x in self._fuerza(s, ronda_prev))))
        return tmp
    def _repartir(self, orden, sizes, agrupar):
        k = len(sizes)
        if agrupar == 'mezcla' and k > 1:
            # Serpentina: 1→A, 2→B, 3→C, 4→C, 5→B, 6→A… (cada manga con fuertes y débiles)
            heats = [[] for _ in range(k)]; idx = 0; forward = True
            while idx < len(orden):
                for i in (range(k) if forward else range(k - 1, -1, -1)):
                    if idx < len(orden) and len(heats[i]) < sizes[i]: heats[i].append(orden[idx]); idx += 1
                forward = not forward
            return heats
        # Agrupar por nivel: seguidos (Expertos juntos, luego Intermedios, luego Novatos).
        heats = []; idx = 0
        for s in sizes: heats.append(orden[idx: idx + s]); idx += s
        return heats
    def _torneo_ronda(self, vivos):
        """Arma la siguiente ronda (o la final si quedan 6) con los que siguen vivos."""
        g = self.gp; t = self._t(); c = t['cars']
        prev = t['rondas'][-1] if t['rondas'] else None
        n_ronda = len(t['rondas']) + 1
        es_final = len(vivos) <= FINALISTAS
        orden = self._ordenar(vivos, prev, n_ronda)
        if es_final:
            if c >= FINALISTAS:
                grupos = [orden]
            else:
                grupos = self._repartir(orden, tamanos(len(orden), c), 'mezcla')
        else:
            sizes = tamanos(len(orden), c)
            grupos = self._repartir(orden, sizes, t['agrupar'])
            # La manga débil primero y la fuerte cierra la ronda (se ve mejor al final).
            grupos = list(reversed(grupos)) if t['agrupar'] == 'nivel' else grupos
        byes = [x[0] for x in grupos if len(x) == 1]
        grupos = [x for x in grupos if len(x) > 1]
        idxs = []
        for m, grupo in enumerate(grupos, 1):
            if es_final and len(grupos) == 1:
                key = 'f'; label = 'Final · %d vueltas' % g['config'].get('torneo_final_laps', 10); kind = 'final'
            elif es_final:
                key = 'fm%d' % m; label = 'Final · manga %d de %d' % (m, len(grupos)); kind = 'heat'
            else:
                key = 'r%dm%d' % (n_ronda, m); label = 'Ronda %d · Manga %d de %d' % (n_ronda, m, len(grupos)); kind = 'heat'
            run = {'key': key, 'kind': kind, 'label': label, 'participants': list(grupo), 'ronda': n_ronda, 'manga': m,
                   'etapa': 'final' if es_final else 'ronda', 'cars': {str(s): i + 1 for i, s in enumerate(grupo)}}
            self._reset_run(run); run['grid'] = list(grupo)
            g['runs'].append(run); idxs.append(len(g['runs']) - 1)
        ronda = {'n': n_ronda, 'runs': idxs, 'vivos': list(vivos), 'byes': byes, 'eliminados': [], 'salvados': [], 'nota': '',
                 'final': es_final, 'cerrada': False, 'creada': time.time()}
        if es_final:
            t['final'] = {'modo': 'una' if len(idxs) == 1 else 'mangas', 'runs': idxs, 'ronda': n_ronda}
        t['rondas'].append(ronda)
        return ronda

    # ---------- cerrar ronda: eliminados ----------
    def _cerrar_ronda(self, ronda):
        t = self._t(); vivos = list(ronda['vivos'])
        cands = []
        for ri in ronda['runs']:
            run = self.gp['runs'][ri]
            rows = self.run_rows(run)
            if len(rows) >= 2: cands.append((rows[-1], run))
        need = max(0, len(vivos) - FINALISTAS)
        cands.sort(key=lambda x: self._score(x[0]))   # peor primero
        fuera = cands[:need]; salvados = cands[need:]
        for r, run in fuera:
            t['eliminados'].append({'slot': r['slot'], 'name': r['name'], 'ronda': ronda['n'], 'manga': run['manga'], 'parte': run['label'],
                                    'laps': r['laps'], 'total': r.get('total'), 'total_h': r.get('total_h'), 'dsq': bool(r.get('dsq'))})
            self._event('eliminado', r['slot'], 'Eliminado · último de ' + run['label'])
        ronda['eliminados'] = [r['slot'] for r, _ in fuera]
        ronda['salvados'] = [r['slot'] for r, _ in salvados]
        if salvados:
            ronda['nota'] = ('Para que queden exactamente %d en la final, solo se eliminaron %d de los %d últimos lugares: '
                             'los que hicieron menos vueltas (con las mismas vueltas, más tiempo total). Se salvó: %s.') % (
                FINALISTAS, len(fuera), len(cands), ', '.join(r['name'] for r, _ in salvados))
        ronda['cerrada'] = True
        return [s for s in vivos if s not in ronda['eliminados']]

    def _torneo_advance(self):
        g = self.gp; t = self._t()
        ronda = next(r for r in t['rondas'] if g['current'] in r['runs'])
        pos = ronda['runs'].index(g['current'])
        if pos + 1 < len(ronda['runs']):
            g['current'] = ronda['runs'][pos + 1]; run = g['runs'][g['current']]; self._reset_run(run); self._prepare(run)
            return
        if ronda['final']:
            ronda['cerrada'] = True
            g['status'] = 'done'; g['finished_at'] = time.time()
            rows = self.torneo_final_rows()
            if rows: self._event('podium', rows[0]['slot'], '¡%s gana el torneo!' % rows[0]['name'])
            else: self._event('podium', text='Torneo terminado')
            self._archive(write_only=True)
            return
        vivos = self._cerrar_ronda(ronda)
        nueva = self._torneo_ronda(vivos)
        elim = [self.pilot(s)['name'] for s in ronda['eliminados']]
        g['notice'] = ('Ronda %d terminada. Eliminados: %s. ' % (ronda['n'], ', '.join(elim) or 'nadie')) + \
                      (('Quedan %d: ¡a la FINAL!' % len(vivos)) if nueva['final'] else ('Siguen %d pilotos · Ronda %d sorteada.' % (len(vivos), nueva['n']))) + \
                      ((' ' + ronda['nota']) if ronda['nota'] else '')
        g['current'] = nueva['runs'][0]; run = g['runs'][g['current']]; self._reset_run(run); self._prepare(run)

    # ---------- cambios a mano antes de arrancar ----------
    def _ronda_actual(self):
        g = self.gp
        return next((r for r in self._t()['rondas'] if g['current'] in r['runs']), None)
    def _run_de(self, ronda, slot):
        for ri in ronda['runs']:
            if slot in (self.gp['runs'][ri]['participants'] or []): return ri
        return None
    def torneo_command(self, action, payload):
        g = self.gp; ronda = self._ronda_actual()
        if not ronda: raise TorneoError('No hay ronda en curso.')
        if action == 'swap':
            a, b = payload.get('a'), payload.get('b')
            if type(a) != int or type(b) != int or a == b: raise TorneoError('Elige dos pilotos para cambiarlos.')
            ra, rb = self._run_de(ronda, a), self._run_de(ronda, b)
            if ra is None or rb is None: raise TorneoError('Los dos pilotos tienen que estar en esta ronda.')
            A, B = g['runs'][ra], g['runs'][rb]
            if A['phase'] != 'ready' or B['phase'] != 'ready' or ra < g['current'] or rb < g['current']:
                raise TorneoError('Solo se puede cambiar en mangas que no han arrancado.')
            ca, cb = A['cars'][str(a)], B['cars'][str(b)]
            if ra == rb:
                A['cars'][str(a)], A['cars'][str(b)] = cb, ca
            else:
                ia, ib = A['participants'].index(a), B['participants'].index(b)
                A['participants'][ia] = b; B['participants'][ib] = a
                del A['cars'][str(a)]; del B['cars'][str(b)]; A['cars'][str(b)] = ca; B['cars'][str(a)] = cb
                for run in (A, B): run['grid'] = list(run['participants']); self._reset_run(run)
            if g['runs'][g['current']] in (A, B): self._prepare(g['runs'][g['current']])
            g['notice'] = 'Cambio hecho: %s ↔ %s.' % (self.pilot(a)['name'], self.pilot(b)['name'])
            return
        if action == 'set_car':
            s, car = payload.get('slot'), payload.get('car')
            if type(s) != int or type(car) != int or not 1 <= car <= 6: raise TorneoError('El coche debe ser del 1 al 6.')
            ri = self._run_de(ronda, s)
            if ri is None: raise TorneoError('Ese piloto no corre en esta ronda.')
            run = g['runs'][ri]
            if run['phase'] != 'ready' or ri < g['current']: raise TorneoError('Solo se puede cambiar en mangas que no han arrancado.')
            other = next((x for x, cc in run['cars'].items() if cc == car and x != str(s)), None)
            if other is not None: run['cars'][other] = run['cars'][str(s)]
            run['cars'][str(s)] = car
            if ri == g['current']: self._prepare(run)
            g['notice'] = '%s corre con el coche %d en %s.' % (self.pilot(s)['name'], car, run['label'])
            return
        raise TorneoError('Acción desconocida.')

    # ---------- vistas ----------
    def torneo_final_rows(self):
        t = self._t(); fin = t.get('final')
        if not fin: return []
        runs = [self.gp['runs'][i] for i in fin['runs']]
        if fin['modo'] == 'una':
            return self.run_rows(runs[0]) if runs[0]['phase'] != 'ready' or runs[0].get('data') else []
        rows = []
        for run in runs:
            for r in self.run_rows(run):
                rr = dict(r, manga=run['manga'], parte=run['label'], corrio=run['phase'] != 'ready'); rows.append(rr)
        rows.sort(key=lambda r: tuple(-x for x in self._score(r)))
        k = 0
        for r in rows:
            if r['dsq'] or not r['corrio']: r['pos'] = None
            else: k += 1; r['pos'] = k
            r['finish_pos'] = r['pos']
        return rows
    def torneo_view(self):
        g = self.gp; t = self._t(); cur = g['current']
        elim = {e['slot']: e for e in t['eliminados']}
        hcfg = self.handicap()
        def fila(run, r):
            p = self.pilot(r['slot'])
            return {'slot': r['slot'], 'name': p['name'], 'nivel': p.get('nivel'), 'car': r['car'], 'avatar': p.get('avatar') or '',
                    'clase': r.get('clase'), 'clase_txt': r.get('clase_txt'), 'h_s': r.get('h_s', 0.0), 'h_coche': r.get('h_coche', 0.0),
                    'h_nivel': r.get('h_nivel', 0.0), 'nivel_txt': r.get('nivel_txt'), 'h_txt': r.get('h_txt', ''), 'laps': r['laps'], 'best': r['best'],
                    'coche_nombre': (handicap_mod.garage_de(hcfg, r['car']) or {}).get('nombre') or '',
                    'total': r.get('total'), 'total_h': r.get('total_h'), 'pos': r.get('pos'), 'dsq': r.get('dsq'), 'finished': r.get('finished'),
                    'eliminado': r['slot'] in elim and elim[r['slot']]['parte'] == run['label']}
        rondas = []
        for ro in t['rondas']:
            mangas = []
            for ri in ro['runs']:
                run = g['runs'][ri]
                if run['phase'] == 'ready':
                    pil = []
                    for s in run['participants']:
                        p = self.pilot(s); car = run['cars'][str(s)]
                        pil.append(dict(handicap_mod.info(hcfg, car, p.get('nivel')), slot=s, name=p['name'], nivel=p.get('nivel'), car=car, avatar=p.get('avatar') or '',
                                        laps=None, best=None, total=None, total_h=None, pos=None, dsq=False, finished=False, eliminado=False))
                else:
                    pil = [fila(run, r) for r in self.run_rows(run)]
                niveles = {}
                for x in pil: niveles[x['nivel']] = niveles.get(x['nivel'], 0) + 1
                mangas.append({'index': ri, 'key': run['key'], 'kind': run['kind'], 'label': run['label'], 'manga': run['manga'], 'phase': run['phase'],
                               'actual': ri == cur and g['status'] == 'active', 'pilotos': pil, 'niveles': niveles,
                               'editable': g['status'] == 'active' and run['phase'] == 'ready' and ri >= cur})
            rondas.append({'n': ro['n'], 'final': ro['final'], 'cerrada': ro['cerrada'], 'vivos': len(ro['vivos']),
                           'byes': [{'slot': s, 'name': self.pilot(s)['name']} for s in ro.get('byes') or []],
                           'eliminados': [{'slot': s, 'name': self.pilot(s)['name']} for s in ro['eliminados']],
                           'salvados': [{'slot': s, 'name': self.pilot(s)['name']} for s in ro['salvados']], 'nota': ro['nota'], 'mangas': mangas})
        vivos = [s for s in (t['rondas'][-1]['vivos'] if t['rondas'] else [])]
        # Cola: las mangas que faltan, en orden.
        cola = []
        if g['status'] == 'active':
            ro = self._ronda_actual()
            if ro:
                for ri in ro['runs']:
                    if ri <= cur: continue
                    run = g['runs'][ri]
                    cola.append({'index': ri, 'label': run['label'], 'pilotos': [{'slot': s, 'name': self.pilot(s)['name'], 'car': run['cars'][str(s)]} for s in run['participants']]})
        estado = {}
        for p in g['pilots']:
            s = p['slot']
            if s in elim: estado[s] = {'estado': 'eliminado', 'texto': 'Eliminado en la ronda %d (%s)' % (elim[s]['ronda'], elim[s]['parte'])}
            elif t.get('final') and s in vivos: estado[s] = {'estado': 'finalista', 'texto': 'Finalista'}
            else: estado[s] = {'estado': 'vivo', 'texto': 'Sigue en el torneo'}
        if g['status'] == 'done':
            fr = self.torneo_final_rows()
            for r in fr:
                if r.get('pos'): estado[r['slot']] = {'estado': 'campeon' if r['pos'] == 1 else 'finalista', 'texto': ('🏆 Campeón' if r['pos'] == 1 else 'Final · P%d' % r['pos'])}
        c = t['cars']
        return {'cars': c, 'agrupar': t['agrupar'], 'rondas': rondas, 'cola': cola,
                'eliminados': [dict(e) for e in t['eliminados']], 'vivos': len(vivos), 'inscritos': len(g['pilots']),
                'final_modo': (t.get('final') or {}).get('modo') or ('una' if c >= FINALISTAS else 'mangas'),
                'final_laps': g['config'].get('torneo_final_laps', 10), 'minutos': self._minutes_torneo(),
                'estado': {str(k): v for k, v in estado.items()},
                'niveles': [list(x) for x in NIVELES]}
    def torneo_mi_turno(self, slot):
        """Para Mi coche: cuándo le toca a este piloto."""
        g = self.gp
        if not self.es_torneo() or not any(p['slot'] == slot for p in g['pilots']): return None
        t = self._t(); cur = g['current']; p = self.pilot(slot)
        el = next((e for e in t['eliminados'] if e['slot'] == slot), None)
        out = {'nivel': p.get('nivel'), 'nivel_txt': NIVEL_TXT.get(p.get('nivel'), ''), 'estado': 'vivo', 'texto': '', 'manga': None, 'car': None,
               'faltan': None, 'ahora': False, 'vivos': len(t['rondas'][-1]['vivos']) if t['rondas'] else 0}
        if el:
            out.update(estado='eliminado', texto='Quedaste eliminado en la ronda %d (último de %s). ¡Gracias por correr!' % (el['ronda'], el['parte'])); return out
        if g['status'] == 'done':
            fr = self.torneo_final_rows(); me = next((r for r in fr if r['slot'] == slot), None)
            if me and me.get('pos') == 1: out.update(estado='campeon', texto='🏆 ¡Ganaste el torneo!')
            elif me: out.update(estado='finalista', texto='Terminaste la final en el lugar %s.' % (me.get('pos') or '—'))
            return out
        ro = self._ronda_actual()
        if not ro: return out
        if slot in (ro.get('byes') or []):
            out.update(texto='Pase directo en esta ronda (número impar de pilotos). Espera la siguiente.'); return out
        for k, ri in enumerate(ro['runs']):
            run = g['runs'][ri]
            if slot in run['participants']:
                car = run['cars'][str(slot)]
                out.update(manga=run['label'], car=car)
                if ri == cur and run['phase'] != 'done':
                    out.update(ahora=True, faltan=0, texto='¡Te toca AHORA! %s · coche %d.' % (run['label'], car))
                elif ri < cur or run['phase'] == 'done':
                    out.update(texto='Ya corriste %s. Espera el resultado de la ronda.' % run['label'])
                else:
                    falt = sum(1 for x in ro['runs'] if cur <= x < ri and g['runs'][x]['phase'] != 'done')
                    out.update(faltan=falt, texto='Tu siguiente manga: %s · coche %d · faltan %d manga%s antes.' % (run['label'], car, falt, '' if falt == 1 else 's'))
                if ro['final']: out['estado'] = 'finalista'
                return out
        return out

    # ---------- CSV ----------
    def torneo_csv(self, w, f2):
        g = self.gp; t = self._t(); c = g['config']
        w.writerow(['Modo', 'Torneo por mangas', 'Inscritos', len(g['pilots']), 'Coches por manga', t['cars'], 'Minutos por manga', self._minutes_torneo(),
                    'Mangas', 'agrupadas por nivel' if t['agrupar'] == 'nivel' else 'niveles mezclados (serpentina)',
                    'Final', ('una carrera a %d vueltas' % c.get('torneo_final_laps', 10)) if (t.get('final') or {}).get('modo', 'una' if t['cars'] >= 6 else 'mangas') == 'una' else 'mangas seguidas (suma de vueltas)'])
        H = list(handicap_mod.CSV_HEAD)
        w.writerow([]); w.writerow(['INSCRITOS', 'Piloto', 'Nivel', 'Resultado'])
        est = self.torneo_view()['estado']
        for p in g['pilots']: w.writerow(['', p['name'], NIVEL_TXT.get(p.get('nivel'), ''), est[str(p['slot'])]['texto']])
        fr = self.torneo_final_rows()
        if fr:
            w.writerow([]); w.writerow(['FINAL DEL TORNEO', 'Posición', 'Piloto', 'Nivel', 'Coche', 'Parte', 'Vueltas', 'Mejor vuelta (s)', 'Estado'] + H + ['Tiempo total real (s)', 'Tiempo total con handicap (s)'])
            for r in fr:
                w.writerow(['', 'DSQ' if r['dsq'] else (r.get('pos') or ''), r['name'], NIVEL_TXT.get(self.pilot(r['slot']).get('nivel'), ''), r['car'], r.get('parte', 'Final'),
                            r['laps'], f2(r['best']), 'DESCALIFICADO' if r['dsq'] else ''] + handicap_mod.csv_cols(r) + [f2(r.get('total')), f2(r.get('total_h'))])
        w.writerow([]); w.writerow(['MANGAS', 'Ronda', 'Manga', 'Posición', 'Piloto', 'Nivel', 'Coche', 'Vueltas', 'Mejor vuelta (s)', 'Estado'] + H + ['Tiempo total real (s)', 'Tiempo total con handicap (s)', 'Resultado'])
        elim = {(e['slot'], e['parte']) for e in t['eliminados']}
        for ro in t['rondas']:
            for ri in ro['runs']:
                run = g['runs'][ri]
                if run['phase'] == 'ready': continue
                for r in self.run_rows(run):
                    res = 'ELIMINADO (último)' if (r['slot'], run['label']) in elim else ('se salvó (regla de 6)' if r['slot'] in ro['salvados'] and r['slot'] == self.run_rows(run)[-1]['slot'] else '')
                    w.writerow(['', 'Final' if ro['final'] else ro['n'], run['label'], 'DSQ' if r['dsq'] else (r.get('pos') or ''), r['name'],
                                NIVEL_TXT.get(self.pilot(r['slot']).get('nivel'), ''), r['car'], r['laps'], f2(r['best']), 'DESCALIFICADO' if r['dsq'] else '']
                               + handicap_mod.csv_cols(r) + [f2(r.get('total')), f2(r.get('total_h')), res])
        w.writerow([]); w.writerow(['ELIMINADOS', 'Orden', 'Piloto', 'Ronda', 'Manga', 'Vueltas', 'Tiempo total real (s)', 'Tiempo total con handicap (s)'])
        for i, e in enumerate(t['eliminados'], 1): w.writerow(['', i, e['name'], e['ronda'], e['parte'], e['laps'], f2(e.get('total')), f2(e.get('total_h'))])
        notas = [ro['nota'] for ro in t['rondas'] if ro.get('nota')]
        for n in notas: w.writerow(['NOTA', n])
