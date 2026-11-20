"""Handicap · ajuste de tiempo por vuelta (Práctica, Carrera, Gran Premio y Mi coche).

Cada COCHE (número de mando 1-6) tiene una clase: «Sin imán», «Con imán» o «Modificado». A cada clase se le
suman (+) o restan (−) segundos por vuelta. Solo cambia los TIEMPOS que se muestran y el ORDEN:
    vuelta ajustada = vuelta real + segundos de su clase
    mejor ajustada  = mejor real + segundos de su clase
    total ajustado  = suma de vueltas reales + vueltas × segundos de su clase
Las vueltas se cuentan igual que siempre (tarjeta SCX o sensor IR): esto no toca la tarjeta ni la ESP32.
Se guarda en data/vueltas.json junto con la vuelta mínima. Cada sesión toma la configuración al apretar
Empezar (Práctica/Carrera) o al arrancar la primera parte (Gran Premio) y se queda con ella.
"""
import copy

CLASES = (('sin_iman', 'Sin imán'), ('con_iman', 'Con imán'), ('modificado', 'Modificado'))
NOMBRE = dict(CLASES)
RANGO_S = (-10.0, 10.0)
DEFAULT = {'enabled': True, 'seg': {'sin_iman': 0.0, 'con_iman': 0.5, 'modificado': 1.0},
           'clases': {str(c): 'sin_iman' for c in range(1, 7)}}
OFF = {'enabled': False, 'seg': {k: 0.0 for k, _ in CLASES}, 'clases': {str(c): 'sin_iman' for c in range(1, 7)}}


def _seg(v):
    if type(v) == bool or not isinstance(v, (int, float)) or v != v or not RANGO_S[0] <= v <= RANGO_S[1]:
        raise ValueError('El ajuste por vuelta debe ser de %g a +%g segundos.' % RANGO_S)
    return round(float(v), 2)


def clean(raw, base=None):
    """Valida (y completa con base o DEFAULT) un handicap. Se puede mandar solo una parte."""
    out = copy.deepcopy(base if isinstance(base, dict) else DEFAULT)
    out.setdefault('seg', dict(DEFAULT['seg'])); out.setdefault('clases', dict(DEFAULT['clases']))
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
    out['enabled'] = bool(out.get('enabled', True))
    return {'enabled': out['enabled'], 'seg': {k: out['seg'][k] for k, _ in CLASES}, 'clases': {c: out['clases'][c] for c in DEFAULT['clases']}}


def clase_de(h, car):
    try: return (h or DEFAULT)['clases'].get(str(int(car)), 'sin_iman')
    except (TypeError, ValueError, AttributeError): return 'sin_iman'


def seg_de(h, car):
    """Segundos por vuelta para ese coche (0 si el handicap está apagado o no hay)."""
    if not h or not h.get('enabled'): return 0.0
    return float(h['seg'].get(clase_de(h, car), 0.0))


def activo(h, cars=None):
    """True si el handicap está encendido y cambia algo para esos coches."""
    if not h or not h.get('enabled'): return False
    cars = list(range(1, 7)) if cars is None else cars
    return any(seg_de(h, c) for c in cars)


def info(h, car):
    """Lo que necesita cada pantalla para un coche."""
    k = clase_de(h, car)
    return {'clase': k, 'clase_txt': NOMBRE[k], 'h_s': seg_de(h, car)}


def mas(x, h_s):
    return None if x is None else round(x + h_s, 3)


def texto_seg(v):
    if not v: return '0 s'
    return ('+' if v > 0 else '−') + ('%.2f' % abs(v)).rstrip('0').rstrip('.') + ' s'


def resumen(h):
    """«Con imán +0.5 s · Modificado +1 s · Sin imán 0 s» (para el CSV y las pantallas)."""
    if not h or not h.get('enabled'): return 'apagado'
    return ' · '.join('%s %s' % (n, texto_seg(h['seg'][k])) for k, n in CLASES)
