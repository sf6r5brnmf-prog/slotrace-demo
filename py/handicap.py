"""Handicap · ajuste de tiempo por vuelta (Práctica, Carrera, Gran Premio y Mi coche).

Cada COCHE (número de mando 1-6) tiene una clase: «Sin imán», «Con imán» o «Modificado». A cada clase se le
suman (+) o restan (−) segundos por vuelta. Solo cambia los TIEMPOS que se muestran y el ORDEN:
    vuelta ajustada = vuelta real + segundos de su clase
    mejor ajustada  = mejor real + segundos de su clase
    total ajustado  = suma de vueltas reales + vueltas × segundos de su clase
Además, cada PILOTO tiene un nivel (Novato / Intermedio / Experto, en el registro de pilotos) y a cada nivel
también se le suman o restan segundos por vuelta (se puede apagar solo esa parte):
    ajuste total por vuelta = segundos de la clase del coche + segundos del nivel del piloto
Las vueltas se cuentan igual que siempre (tarjeta SCX o sensor IR): esto no toca la tarjeta ni la ESP32.
Se guarda en data/vueltas.json junto con la vuelta mínima. Cada sesión toma la configuración al apretar
Empezar (Práctica/Carrera) o al arrancar la primera parte (Gran Premio) y se queda con ella.
"""
import copy

CLASES = (('sin_iman', 'Sin imán'), ('con_iman', 'Con imán'), ('modificado', 'Modificado'))
NOMBRE = dict(CLASES)
RANGO_S = (-10.0, 10.0)
ICON = {'sin_iman': '○', 'con_iman': '🧲', 'modificado': '🔧'}
# Nivel del piloto (el mismo del Torneo por mangas). Sin nivel guardado = Intermedio.
NIVELES = (('novato', 'Novato'), ('intermedio', 'Intermedio'), ('experto', 'Experto'))
NIVEL_TXT = dict(NIVELES)
NIVEL_DEFAULT = 'intermedio'
DEFAULT = {'enabled': True, 'seg': {'sin_iman': 0.0, 'con_iman': 0.5, 'modificado': 1.0},
           'clases': {str(c): 'sin_iman' for c in range(1, 7)},
           # De fábrica (ejemplo, se cambia): al Experto se le suma, al Novato se le resta.
           'nivel_on': True, 'seg_nivel': {'novato': -0.3, 'intermedio': 0.0, 'experto': 0.3},
           # Nivel automático por tiempo: con la MEJOR VUELTA REAL (sin handicap) de la sesión, según la clase del coche.
           # Experto si es menor que «experto»; Novato si es mayor que «novato»; en medio, Intermedio.
           # Ejemplo de Ernesto (Con imán, GP): Experto < 11 s, Intermedio 11–12 s, Novato > 13 s → corte Novato en 13 s.
           'nivel_auto': 'sugerir',   # 'apagado' | 'sugerir' (se acepta con un toque) | 'auto' (cambia solo)
           'cortes': {'sin_iman': {'experto': 12.0, 'novato': 14.0}, 'con_iman': {'experto': 11.0, 'novato': 13.0},
                      'modificado': {'experto': 10.5, 'novato': 12.5}}}
NIVEL_AUTO = (('apagado', 'Apagado'), ('sugerir', 'Sugerir (se acepta con un toque)'), ('auto', 'Cambiar solo'))
MIN_VUELTAS_NIVEL = 3     # vueltas válidas mínimas en la sesión para sugerir un nivel
RANGO_CORTE = (1.0, 120.0)
OFF = {'enabled': False, 'seg': {k: 0.0 for k, _ in CLASES}, 'clases': {str(c): 'sin_iman' for c in range(1, 7)},
       'nivel_on': False, 'seg_nivel': {k: 0.0 for k, _ in NIVELES}}


def nivel_ok(n):
    """Nivel válido (o Intermedio si no hay)."""
    return n if n in NIVEL_TXT else NIVEL_DEFAULT


def _seg(v):
    if type(v) == bool or not isinstance(v, (int, float)) or v != v or not RANGO_S[0] <= v <= RANGO_S[1]:
        raise ValueError('El ajuste por vuelta debe ser de %g a +%g segundos.' % RANGO_S)
    return round(float(v), 2)


def clean(raw, base=None):
    """Valida (y completa con base o DEFAULT) un handicap. Se puede mandar solo una parte."""
    out = copy.deepcopy(base if isinstance(base, dict) else DEFAULT)
    out.setdefault('seg', dict(DEFAULT['seg'])); out.setdefault('clases', dict(DEFAULT['clases']))
    out.setdefault('nivel_on', DEFAULT['nivel_on']); out.setdefault('seg_nivel', dict(DEFAULT['seg_nivel']))
    out.setdefault('nivel_auto', DEFAULT['nivel_auto']); out.setdefault('cortes', copy.deepcopy(DEFAULT['cortes']))
    for k, _ in CLASES: out['cortes'].setdefault(k, dict(DEFAULT['cortes'][k]))
    if raw is None: return out
    if not isinstance(raw, dict): raise ValueError('Datos de handicap inválidos.')
    if 'enabled' in raw:
        if type(raw['enabled']) != bool: raise ValueError('Handicap: encendido o apagado.')
        out['enabled'] = raw['enabled']
    seg = raw.get('seg')
    if seg is not None:
        if not isinstance(seg, dict): raise ValueError('Datos de handicap inválidos.')
        for k, v in seg.items():
            if k not in NOMBRE: raise ValueError('Clase desconocida: %s' % k)
            out['seg'][k] = _seg(v)
    if 'nivel_on' in raw:
        if type(raw['nivel_on']) != bool: raise ValueError('Handicap por nivel: encendido o apagado.')
        out['nivel_on'] = raw['nivel_on']
    sn = raw.get('seg_nivel')
    if sn is not None:
        if not isinstance(sn, dict): raise ValueError('Datos de handicap inválidos.')
        for k, v in sn.items():
            if k not in NIVEL_TXT: raise ValueError('Nivel desconocido: %s' % k)
            out['seg_nivel'][k] = _seg(v)
    if 'nivel_auto' in raw:
        if raw['nivel_auto'] not in dict(NIVEL_AUTO): raise ValueError('Nivel automático: apagado, sugerir o cambiar solo.')
        out['nivel_auto'] = raw['nivel_auto']
    co = raw.get('cortes')
    if co is not None:
        if not isinstance(co, dict): raise ValueError('Datos de handicap inválidos.')
        for k, v in co.items():
            if k not in NOMBRE or not isinstance(v, dict): raise ValueError('Clase desconocida: %s' % k)
            for lado in ('experto', 'novato'):
                if lado in v:
                    x = v[lado]
                    if type(x) == bool or not isinstance(x, (int, float)) or x != x or not RANGO_CORTE[0] <= x <= RANGO_CORTE[1]:
                        raise ValueError('Los tiempos para cambiar de nivel van de %g a %g segundos.' % RANGO_CORTE)
                    out['cortes'][k][lado] = round(float(x), 2)
    cl = raw.get('clases')
    if cl is not None:
        if not isinstance(cl, dict): raise ValueError('Datos de handicap inválidos.')
        for car, k in cl.items():
            if str(car) not in DEFAULT['clases']: raise ValueError('El coche debe ser del 1 al 6.')
            if k not in NOMBRE: raise ValueError('Elige Con imán, Sin imán o Modificado.')
            out['clases'][str(car)] = k
    for k, _ in CLASES: out['seg'][k] = _seg(out['seg'].get(k, 0.0))
    for c in DEFAULT['clases']:
        if out['clases'].get(c) not in NOMBRE: out['clases'][c] = 'sin_iman'
    for k, _ in NIVELES: out['seg_nivel'][k] = _seg(out['seg_nivel'].get(k, 0.0))
    for k, n in CLASES:
        c = out['cortes'][k]
        if not c.get('experto', 0) < c.get('novato', 0):
            raise ValueError('%s: el tiempo de Experto debe ser menor que el de Novato.' % n)
    if out['nivel_auto'] not in dict(NIVEL_AUTO): out['nivel_auto'] = DEFAULT['nivel_auto']
    out['enabled'] = bool(out.get('enabled', True))
    return {'enabled': out['enabled'], 'seg': {k: out['seg'][k] for k, _ in CLASES}, 'clases': {c: out['clases'][c] for c in DEFAULT['clases']},
            'nivel_on': bool(out['nivel_on']), 'seg_nivel': {k: out['seg_nivel'][k] for k, _ in NIVELES},
            'nivel_auto': out['nivel_auto'], 'cortes': {k: {'experto': out['cortes'][k]['experto'], 'novato': out['cortes'][k]['novato']} for k, _ in CLASES}}


def clase_de(h, car):
    try: return (h or DEFAULT)['clases'].get(str(int(car)), 'sin_iman')
    except (TypeError, ValueError, AttributeError): return 'sin_iman'


def seg_clase(h, car):
    """Segundos por vuelta por la CLASE del coche (Configuración; 0 si el handicap está apagado)."""
    if not h or not h.get('enabled'): return 0.0
    return float(h['seg'].get(clase_de(h, car), 0.0))


def garage_de(h, car):
    """Coche del Garage que corre con ese mando ({'id','nombre'}) o None. Viene en h['garage'] (garage.efectivo)."""
    try: g = ((h or {}).get('garage') or {}).get(str(int(car)))
    except (TypeError, ValueError): return None
    return g if isinstance(g, dict) else None


def seg_propio(h, car):
    """Hándicap PROPIO del coche del Garage (se suma a la clase). 0 sin Garage o con el handicap apagado."""
    if not h or not h.get('enabled'): return 0.0
    try: return float(((h.get('propio') or {}).get(str(int(car)))) or 0.0)
    except (TypeError, ValueError): return 0.0


def seg_coche(h, car):
    """Segundos por vuelta por el coche = clase + hándicap propio del coche del Garage."""
    return round(seg_clase(h, car) + seg_propio(h, car), 2)


def seg_nivel(h, nivel):
    """Segundos por vuelta por el nivel del piloto (0 si el handicap o la parte de nivel están apagados)."""
    if not h or not h.get('enabled') or not h.get('nivel_on'): return 0.0
    return float((h.get('seg_nivel') or {}).get(nivel_ok(nivel), 0.0))


def seg_de(h, car, nivel=None):
    """Ajuste total por vuelta = clase del coche + nivel del piloto (sin nivel = Intermedio)."""
    return round(seg_coche(h, car) + seg_nivel(h, nivel), 2)


def activo(h, cars=None, niveles=None):
    """True si el handicap está encendido y cambia algo para esos coches o pilotos."""
    if not h or not h.get('enabled'): return False
    cars = list(range(1, 7)) if cars is None else cars
    if any(seg_coche(h, c) for c in cars): return True
    niveles = [k for k, _ in NIVELES] if niveles is None else [nivel_ok(n) for n in niveles]
    return any(seg_nivel(h, n) for n in niveles)


def detalle(h, car, nivel=None):
    """«🧲 +0.5 s · 🏎️ Rayo +0.2 s · Experto +0.3 s» (clase, coche del Garage y nivel)."""
    k = clase_de(h, car); hc = seg_clase(h, car); hp = seg_propio(h, car); hn = seg_nivel(h, nivel)
    partes = []
    if hc and (hn or hp): partes.append('%s %s' % (ICON[k], texto_seg(hc)))   # corto cuando van varias partes
    elif hc or not (hn or hp): partes.append('%s %s %s' % (ICON[k], NOMBRE[k], texto_seg(hc)))
    if hp: partes.append('🏎️ %s %s' % ((garage_de(h, car) or {}).get('nombre') or 'coche', texto_seg(hp)))
    if hn: partes.append('%s %s' % (NIVEL_TXT[nivel_ok(nivel)], texto_seg(hn)))
    return ' · '.join(partes)


def info(h, car, nivel=None):
    """Lo que necesita cada pantalla para un coche y su piloto: clase, nivel y las dos partes del ajuste."""
    k = clase_de(h, car); n = nivel_ok(nivel)
    g = garage_de(h, car) or {}
    return {'clase': k, 'clase_txt': NOMBRE[k], 'h_s': seg_de(h, car, n), 'h_coche': seg_coche(h, car),
            'h_clase': seg_clase(h, car), 'h_propio': seg_propio(h, car), 'coche_nombre': g.get('nombre') or '', 'garage_id': g.get('id') or '',
            'nivel': n, 'nivel_txt': NIVEL_TXT[n], 'h_nivel': seg_nivel(h, n), 'h_txt': detalle(h, car, n)}


def csv_cols(hi):
    """Columnas del CSV: coche del Garage, clase, handicap de clase, propio del coche, del coche (suma), nivel, de nivel y TOTAL."""
    return [hi.get('coche_nombre', ''), hi.get('clase_txt', ''), '%.2f' % (hi.get('h_clase', hi.get('h_coche')) or 0.0), '%.2f' % (hi.get('h_propio') or 0.0), '%.2f' % (hi.get('h_coche') or 0.0), hi.get('nivel_txt', ''), '%.2f' % (hi.get('h_nivel') or 0.0), '%.2f' % (hi.get('h_s') or 0.0)]


CSV_HEAD = ['Coche (garage)', 'Clase', 'Handicap clase (s)', 'Handicap propio coche (s)', 'Handicap coche (s)', 'Nivel', 'Handicap nivel (s)', 'Handicap (s por vuelta)']


# Con ajuste negativo (resta), una vuelta ajustada nunca baja de este mínimo (ni de 0): p. ej. 10.2 s − 10 s
# daría 0.2 s; se queda en 1 s. Con el ajuste en 0 o positivo el tiempo real se usa tal cual.
MIN_VUELTA_H = 1.0


def mas(x, h_s):
    """Vuelta (o mejor vuelta) con handicap. Si resta, nunca baja de MIN_VUELTA_H."""
    if x is None: return None
    v = x + (h_s or 0.0)
    if h_s and h_s < 0: v = max(v, min(x, MIN_VUELTA_H))
    return round(v, 3)


def suma(vueltas, h_s):
    """Tiempo total con handicap = suma de cada vuelta ajustada (cada una con el mínimo de arriba)."""
    vueltas = list(vueltas)
    return round(sum(mas(x, h_s) for x in vueltas), 3) if vueltas else None


def texto_seg(v):
    if not v: return '0 s'
    return ('+' if v > 0 else '−') + ('%.2f' % abs(v)).rstrip('0').rstrip('.') + ' s'


def resumen(h):
    """«Con imán +0.5 s · Modificado +1 s · Sin imán 0 s» (para el CSV y las pantallas)."""
    if not h or not h.get('enabled'): return 'apagado'
    out = ' · '.join('%s %s' % (n, texto_seg(h['seg'][k])) for k, n in CLASES)
    if h.get('nivel_on') and h.get('seg_nivel'):
        out += ' | Nivel: ' + ' · '.join('%s %s' % (n, texto_seg(h['seg_nivel'].get(k, 0.0))) for k, n in NIVELES)
    return out


# ---------- nivel automático por tiempo ----------
def cortes_de(h):
    c = copy.deepcopy(DEFAULT['cortes'])
    for k, v in ((h or {}).get('cortes') or {}).items():
        if k in c and isinstance(v, dict): c[k].update({x: v[x] for x in ('experto', 'novato') if x in v})
    return c


def nivel_por_tiempo(h, clase, best):
    """Nivel que corresponde a una mejor vuelta REAL (sin handicap) con un coche de esa clase."""
    if best is None: return None
    c = cortes_de(h).get(clase if clase in NOMBRE else 'sin_iman')
    if best < c['experto']: return 'experto'
    if best > c['novato']: return 'novato'
    return 'intermedio'


def texto_cortes(h, clase):
    c = cortes_de(h)[clase]
    return 'Experto < %s s · Intermedio %s–%s s · Novato > %s s' % tuple(('%.2f' % x).rstrip('0').rstrip('.') for x in (c['experto'], c['experto'], c['novato'], c['novato']))


def limpiar_sugerido(x):
    """Sugerencia/cambio de nivel guardado con el piloto: {nivel, de, s, clase, fuente, at}. Algo raro → None."""
    if not isinstance(x, dict) or x.get('nivel') not in NIVEL_TXT: return None
    try: sec = round(float(x.get('s')), 3)
    except (TypeError, ValueError): return None
    out = {'nivel': x['nivel'], 's': sec, 'clase': x.get('clase') if x.get('clase') in NOMBRE else 'sin_iman',
           'fuente': str(x.get('fuente') or '')[:80], 'at': float(x.get('at') or 0)}
    if x.get('de') in NIVEL_TXT: out['de'] = x['de']
    return out


def aplicar_nivel(p, h, clase, best, n_vueltas, fuente, ahora):
    """Actualiza un piloto (dict del registro o de inscritos) con su mejor vuelta de la sesión.
    Devuelve 'cambio', 'sugerido' o None. Modo 'sugerir': deja p['sugerido'] (si es distinto a su nivel).
    Modo 'auto': cambia p['nivel'] y deja p['nivel_cambio'] para avisar."""
    modo = (h or {}).get('nivel_auto', DEFAULT['nivel_auto'])
    if modo == 'apagado' or best is None or n_vueltas < MIN_VUELTAS_NIVEL: return None
    nuevo = nivel_por_tiempo(h, clase, best); actual = nivel_ok(p.get('nivel'))
    info_ = {'nivel': nuevo, 's': round(best, 3), 'clase': clase, 'fuente': fuente, 'at': ahora}
    if nuevo == actual:
        p.pop('sugerido', None); return None
    if modo == 'auto':
        p['nivel'] = nuevo; p['nivel_cambio'] = dict(info_, de=actual); p.pop('sugerido', None); return 'cambio'
    p['sugerido'] = dict(info_, de=actual); return 'sugerido'
