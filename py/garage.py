"""🏎️ Garage: los coches físicos disponibles, cada uno con su ficha y su propio hándicap.

Dos garages: «Garage de la casa» (tipo 'casa') y «Garage de invitados» (tipo 'invitado': el coche que trae un
piloto invitado, ligado a su dueño). Un coche de invitado se puede pasar a la casa o borrar después del evento.

El MANDO no se queda con el coche: en cada carrera o manga el piloto escoge (o le toca por sorteo) un mando y lo
vincula a su coche o a uno del Garage. Por eso el coche va con el PILOTO:
data/garage.json = {'version', 'cars': [ficha], 'uso': {'0'..'5': id del coche que lleva el piloto de ese lugar del registro},
                    'historial': [registro por carrera terminada], 'hechos': [claves ya registradas]}
Fotos: data/garage-fotos/<hex>.jpg (en la DEMO, data/ vive en IndexedDB del navegador).

El chip (mando habitual) es solo informativo: en SCX Digital el coche se empareja con cualquier mando.
Hándicap total por vuelta = clase del coche (Configuración) + hándicap PROPIO del coche + nivel del piloto.
Sin coche del Garage en un mando, todo funciona como antes (la clase del mando en Configuración).
"""
import base64, binascii, copy, re, threading, time, uuid
from pathlib import Path
import durable
import handicap as H

MAX_CARS = 40
MAX_NOTAS = 60
MAX_HIST = 600
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
FOTO = re.compile(r'^/garage-fotos/[0-9a-f]{32}\.jpg$')
FECHA = re.compile(r'^\d{4}-\d{2}-\d{2}$')
ID = re.compile(r'^[0-9a-f]{12}$')


class GarageError(Exception):
    def __init__(self, message, status=400): super().__init__(message); self.status = status


def _txt(v, n, campo, req=False):
    if v is None: v = ''
    if not isinstance(v, str): raise GarageError('%s no es válido.' % campo)
    v = ' '.join(v.split())
    if req and not v: raise GarageError('Escribe el %s.' % campo.lower())
    if len(v) > n or any(ord(c) < 32 for c in v): raise GarageError('%s: máximo %d letras.' % (campo, n))
    return v


def _num(v, lo, hi, campo, allow_none=True):
    if v in (None, ''):
        if allow_none: return None
        raise GarageError('Falta %s.' % campo)
    if isinstance(v, bool): raise GarageError('%s no es válido.' % campo)
    try: x = float(str(v).replace(',', '.'))
    except ValueError: raise GarageError('%s no es un número.' % campo)
    if not lo <= x <= hi: raise GarageError('%s debe ser de %g a %g.' % (campo, lo, hi))
    return x


def limpiar_coche(c, prev=None):
    """Valida una ficha. Lanza GarageError con un mensaje claro."""
    if not isinstance(c, dict): raise GarageError('Datos del coche inválidos.')
    prev = prev or {}
    out = {'id': prev.get('id') or uuid.uuid4().hex[:12]}
    out['nombre'] = _txt(c.get('nombre'), 40, 'Nombre o modelo', req=True)
    out['escuderia'] = _txt(c.get('escuderia'), 40, 'Escudería')
    col = c.get('color') or ''
    if col and not HEX.match(col): raise GarageError('Color no válido.')
    out['color'] = col.lower()
    if c.get('clase', 'sin_iman') not in H.NOMBRE: raise GarageError('Elige la clase: Sin imán, Con imán o Modificado.')
    out['clase'] = c.get('clase', 'sin_iman')
    h = _num(c.get('h', 0), -10, 10, 'El hándicap del coche (segundos)')
    out['h'] = round(h or 0.0, 2)
    chip = c.get('chip')
    if chip in (None, '', 0, '0'): out['chip'] = None
    else:
        try: chip = int(chip)
        except (TypeError, ValueError): raise GarageError('El chip debe ser del 1 al 6.')
        if not 1 <= chip <= 6: raise GarageError('El chip debe ser del 1 al 6.')
        out['chip'] = chip
    t = c.get('techo') or ''
    if t and not HEX.match(t): raise GarageError('Color de la marca del techo no válido.')
    out['techo'] = t.lower()
    out['motor'] = _txt(c.get('motor'), 40, 'Motor')
    p = _num(c.get('peso'), 1, 2000, 'El peso (g)')
    out['peso'] = None if p is None else round(p, 1)
    out['dueno'] = _txt(c.get('dueno'), 40, 'Dueño')
    notas = c.get('notas') or []
    if not isinstance(notas, list) or len(notas) > MAX_NOTAS: raise GarageError('Demasiadas notas de mantenimiento.')
    out['notas'] = []
    for n in notas:
        if not isinstance(n, dict): raise GarageError('Nota inválida.')
        f = n.get('fecha') or ''
        if f and not FECHA.match(f): raise GarageError('Fecha de la nota inválida (usa el calendario).')
        tx = _txt(n.get('texto'), 120, 'Nota')
        if tx: out['notas'].append({'fecha': f, 'texto': tx})
    out['notas'].sort(key=lambda n: n['fecha'], reverse=True)
    out['foto'] = prev.get('foto') or ''
    out['tipo'] = c.get('tipo', prev.get('tipo', 'casa'))
    if out['tipo'] not in ('casa', 'invitado'): raise GarageError('Garage inválido: casa o invitados.')
    out['ejemplo'] = bool(c.get('ejemplo', prev.get('ejemplo', False)))
    out['creado'] = prev.get('creado') or round(time.time())
    return out


CLASE_SIN = re.compile(r'^clase:(sin_iman|con_iman|modificado)$')


def valor_ok(v):
    """Lo que un piloto puede llevar: '' (nada), id de un coche del Garage o 'clase:<clase>' (coche sin ficha)."""
    return v == '' or (isinstance(v, str) and (bool(ID.match(v)) or bool(CLASE_SIN.match(v))))


def entradas(g, mapa, slots=None):
    """{'p<slot>': ficha} para handicap.con_pilotos: mapa = {slot: id del coche o 'clase:<clase>'}.
    La clase (imán o no) es del COCHE: sin coche del Garage, la clase se escoge al vincular ('clase:…');
    si no escogió nada, Sin imán. Nunca sale del piloto ni del mando (la clase vieja por mando se ignora).
    slots: lugares que corren (cada uno lleva entrada aunque no haya escogido nada)."""
    cars = {c['id']: c for c in (g or {}).get('cars') or []}; out = {}
    mapa = {str(k): v for k, v in (mapa or {}).items()}
    for slot in (list(mapa) if slots is None else [str(s) for s in slots]):
        v = mapa.get(slot) or ''; c = cars.get(v)
        if c: out['p%s' % slot] = {'id': c['id'], 'nombre': c['nombre'], 'clase': c['clase'], 'h': c.get('h') or 0.0, 'tipo': c.get('tipo') or 'casa'}
        else:
            m = CLASE_SIN.match(v) if isinstance(v, str) else None
            out['p%s' % slot] = {'id': '', 'nombre': '', 'clase': m.group(1) if m else 'sin_iman', 'h': 0.0, 'tipo': 'sin'}
    return out


EJEMPLOS = [
    # (nombre, escudería, color, clase, h, chip, techo, motor, peso, dueño, nota)
    ('Rayo Rojo (ejemplo)', 'Escudería Roja', '#e53935', 'con_iman', 0.2, 1, '#ffffff', 'Estándar 18k', 78, 'Club', 'Cambio de llantas'),
    ('Flecha Azul (ejemplo)', 'Equipo Azul', '#1e88e5', 'sin_iman', 0.0, 2, '#ffeb3b', 'Estándar 18k', 74, 'Club', 'Escobillas nuevas'),
    ('Trueno Amarillo (ejemplo)', 'Amarillo Racing', '#fdd835', 'modificado', -0.3, 3, '#000000', 'Motor 21k', 80, 'Club', 'Guía nueva'),
    ('Sombra Negra (ejemplo)', 'Negro Team', '#212121', 'con_iman', 0.0, 4, '#ff9800', 'Estándar 18k', 77, 'Club', ''),
    ('Lima Verde (ejemplo)', 'Verde GP', '#43a047', 'sin_iman', -0.2, 5, '#e91e63', 'Estándar 18k', 72, 'Club', 'Cambio de llantas'),
    ('Nube Blanca (ejemplo)', 'Blanco Motorsport', '#eeeeee', 'sin_iman', 0.1, 6, '#2196f3', 'Estándar 18k', 75, 'Club', ''),
    # Garage de invitados: coches que traen los pilotos invitados (ligados a su dueño)
    ('Bala Naranja (ejemplo invitado)', 'Invitados', '#fb8c00', 'con_iman', 0.0, None, '', 'Estándar 18k', 76, 'Invitado Luis', ''),
    ('Cometa Morado (ejemplo invitado)', 'Invitados', '#8e24aa', 'sin_iman', 0.3, None, '', '', None, 'Invitada Sofía', ''),
]


class Garage:
    def __init__(self, directory, avisos=None):
        self.directory = Path(directory); self.fotos = self.directory / 'garage-fotos'
        self.fotos.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'garage.json'; self.lock = threading.RLock()
        d, aviso = durable.leer_json(self.path, validate=self.check, nombre='garage.json (coches del Garage)')
        if aviso and avisos is not None: avisos.append(aviso)
        self.data = d or {'version': 0, 'cars': [], 'uso': {}, 'historial': [], 'hechos': []}
    @staticmethod
    def check(d):
        if not isinstance(d, dict) or not isinstance(d.get('cars'), list) or type(d.get('version')) != int: raise ValueError('garage.json inválido')
        d.pop('pista', None)   # versión vieja (coche amarrado al mando): ya no se usa
        d.setdefault('uso', {}); d.setdefault('historial', []); d.setdefault('hechos', [])
        for c in d['cars']: c.setdefault('tipo', 'casa')
        return d
    def read(self):
        with self.lock: return copy.deepcopy(self.data)
    def _save(self):
        self.data['version'] += 1
        durable.escribir_json(self.path, self.data, backup=True, indent=1)
    def _find(self, cid):
        return next((c for c in self.data['cars'] if c['id'] == cid), None)
    def _limpiar_pista(self):
        ids = {c['id'] for c in self.data['cars']}; u = {}
        for k, cid in (self.data.get('uso') or {}).items():
            if isinstance(cid, str) and CLASE_SIN.match(cid): u[str(k)] = cid   # coche sin ficha: solo su clase
            elif cid in ids and cid not in u.values(): u[str(k)] = cid   # un coche lo lleva un solo piloto a la vez
        self.data['uso'] = u
    def _usar(self, slot, cid, nombres=None):
        try: slot = int(slot)
        except (TypeError, ValueError): raise GarageError('Piloto inválido.')
        if not 0 <= slot <= 5: raise GarageError('Piloto inválido.')
        u = self.data.setdefault('uso', {})
        if not cid: u.pop(str(slot), None); return
        if isinstance(cid, str) and CLASE_SIN.match(cid): u[str(slot)] = cid; return
        c = self._find(cid)
        if not c: raise GarageError('Ese coche ya no está en el Garage.', 404)
        otro = next((k for k, v in u.items() if v == cid and k != str(slot)), None)
        if otro is not None:
            quien = (nombres or {}).get(otro) or 'otro piloto'
            raise GarageError('%s ya está en uso con %s. Escoge otro coche.' % (c['nombre'], quien), 409)
        u[str(slot)] = cid
    def _foto(self, car, image):
        if not isinstance(image, str) or not image.startswith('data:image/jpeg;base64,'): raise GarageError('Usa una foto (JPG).')
        try: raw = base64.b64decode(image.split(',', 1)[1], validate=True)
        except (ValueError, binascii.Error): raise GarageError('La foto no es válida.')
        if not (200 < len(raw) <= 900000 and raw[:3] == b'\xff\xd8\xff'): raise GarageError('La foto no es válida o es muy grande.')
        name = '/garage-fotos/' + uuid.uuid4().hex + '.jpg'
        durable.escribir_bytes(self.directory / name[1:], raw)
        old = car.get('foto')
        car['foto'] = name
        if old and FOTO.match(old): (self.directory / old[1:]).unlink(missing_ok=True)
    def command(self, p):
        """POST /api/garage: save | delete | usar | rapido | a_casa | borrar_invitados | quitar_foto | ejemplos."""
        if not isinstance(p, dict): raise GarageError('Datos inválidos.')
        a = p.get('action')
        with self.lock:
            if a == 'save':
                c = p.get('car') or {}
                cid = c.get('id')
                prev = self._find(cid) if cid else None
                if cid and not prev: raise GarageError('Ese coche ya no está en el Garage.', 404)
                if not prev and len(self.data['cars']) >= MAX_CARS: raise GarageError('El Garage ya tiene %d coches.' % MAX_CARS)
                car = limpiar_coche(c, prev)
                if p.get('image') is not None: self._foto(car, p['image'])
                if prev: self.data['cars'][self.data['cars'].index(prev)] = car
                else: self.data['cars'].append(car)   # no se asigna solo a nadie: el piloto lo escoge a propósito
                self._limpiar_pista(); self._save()
                return dict(self.view(), saved=car['id'])
            if a == 'delete':
                c = self._find(p.get('id'))
                if not c: raise GarageError('Ese coche ya no está en el Garage.', 404)
                self.data['cars'].remove(c)
                if c.get('foto') and FOTO.match(c['foto']): (self.directory / c['foto'][1:]).unlink(missing_ok=True)
                self._limpiar_pista(); self._save(); return self.view()
            if a == 'quitar_foto':
                c = self._find(p.get('id'))
                if not c: raise GarageError('Ese coche ya no está en el Garage.', 404)
                if c.get('foto') and FOTO.match(c['foto']): (self.directory / c['foto'][1:]).unlink(missing_ok=True)
                c['foto'] = ''; self._save(); return self.view()
            if a == 'usar':
                # El piloto (lugar del registro 0-5) lleva este coche (id vacío = ninguno). Un coche, un piloto a la vez.
                self._usar(p.get('slot'), p.get('id') or '', p.get('nombres')); self._save(); return self.view()
            if a == 'rapido':
                # Alta rápida desde la carrera: coche de invitado (nombre + clase + hándicap) y se lo lleva ese piloto.
                if len(self.data['cars']) >= MAX_CARS: raise GarageError('El Garage ya tiene %d coches.' % MAX_CARS)
                c = p.get('car') or {}
                car = limpiar_coche({'nombre': c.get('nombre'), 'clase': c.get('clase', 'sin_iman'), 'h': c.get('h', 0),
                                     'dueno': c.get('dueno'), 'tipo': 'invitado'})
                self.data['cars'].append(car)
                if p.get('slot') not in (None, ''): self._usar(p.get('slot'), car['id'], p.get('nombres'))
                self._save(); return dict(self.view(), saved=car['id'])
            if a == 'a_casa':
                c = self._find(p.get('id'))
                if not c: raise GarageError('Ese coche ya no está en el Garage.', 404)
                c['tipo'] = 'casa'; self._save(); return self.view()
            if a == 'borrar_invitados':
                for c in [c for c in self.data['cars'] if c.get('tipo') == 'invitado']:
                    self.data['cars'].remove(c)
                    if c.get('foto') and FOTO.match(c['foto']): (self.directory / c['foto'][1:]).unlink(missing_ok=True)
                self._limpiar_pista(); self._save(); return self.view()
            if a == 'ejemplos':
                hay = {c['nombre'] for c in self.data['cars']}; n = 0
                for (nom, esc, col, cl, h, chip, techo, motor, peso, dueno, nota) in EJEMPLOS:
                    if nom in hay or len(self.data['cars']) >= MAX_CARS: continue
                    car = limpiar_coche({'nombre': nom, 'escuderia': esc, 'color': col, 'clase': cl, 'h': h, 'chip': chip, 'techo': techo,
                                         'motor': motor, 'peso': peso, 'dueno': dueno, 'ejemplo': True, 'tipo': 'invitado' if 'invitad' in nom else 'casa',
                                         'notas': [{'fecha': time.strftime('%Y-%m-%d'), 'texto': nota}] if nota else []})
                    self.data['cars'].append(car); n += 1
                self._limpiar_pista(); self._save(); return dict(self.view(), agregados=n)
        raise GarageError('Acción desconocida.')
    # ---------- historial ----------
    def registrar(self, clave, registro):
        """registro = {'tipo': 'practica'|'carrera'|'gp'|'torneo', 'fuente', 'at', 'coches': {id: {best, vueltas, gano}}}"""
        with self.lock:
            if clave in self.data['hechos']: return False
            self.data['hechos'].append(clave); self.data['hechos'] = self.data['hechos'][-MAX_HIST:]
            if registro.get('coches'):
                self.data['historial'].append(dict(registro, clave=clave)); self.data['historial'] = self.data['historial'][-MAX_HIST:]
            self._save(); return True
    def ya(self, clave):
        with self.lock: return clave in self.data['hechos']
    def stats(self):
        out = {}
        with self.lock: hist = copy.deepcopy(self.data['historial'])
        for r in hist:
            carrera = r.get('tipo') in ('carrera', 'gp', 'torneo')
            for cid, x in (r.get('coches') or {}).items():
                s = out.setdefault(cid, {'mejor': None, 'vueltas': 0, 'carreras': 0, 'ganadas': 0, 'practicas': 0, 'ultima': None})
                b = x.get('best')
                if b is not None and (s['mejor'] is None or b < s['mejor']): s['mejor'] = round(b, 3)
                s['vueltas'] += int(x.get('vueltas') or 0)
                if carrera: s['carreras'] += 1
                else: s['practicas'] += 1
                if carrera and x.get('gano'): s['ganadas'] += 1
                s['ultima'] = r.get('fuente')
        return out
    def view(self):
        with self.lock:
            d = {'version': self.data['version'], 'cars': copy.deepcopy(self.data['cars']), 'uso': dict(self.data.get('uso') or {})}
        st = self.stats()
        for c in d['cars']: c['hist'] = st.get(c['id'], {'mejor': None, 'vueltas': 0, 'carreras': 0, 'ganadas': 0, 'practicas': 0, 'ultima': None})
        return d
