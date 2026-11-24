"""🏎️ Garage: los coches físicos disponibles, cada uno con su ficha y su propio hándicap.

data/garage.json = {'version', 'cars': [ficha], 'pista': {'1'..'6': id del coche que corre con ese mando},
                    'historial': [registro por carrera terminada], 'hechos': [claves ya registradas]}
Fotos: data/garage-fotos/<hex>.jpg (en la DEMO, data/ vive en IndexedDB del navegador).

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
    out['ejemplo'] = bool(c.get('ejemplo', prev.get('ejemplo', False)))
    out['creado'] = prev.get('creado') or round(time.time())
    return out


def efectivo(h, g):
    """Handicap de vueltas.json + los coches del Garage que están en pista: la clase del mando la pone el coche,
    y se agregan h['propio'] {mando: segundos} y h['garage'] {mando: {id, nombre}}. Se congela con la sesión."""
    if h is None or not g: return h
    cars = {c['id']: c for c in g.get('cars') or []}
    out = copy.deepcopy(h); propio = {}; gar = {}
    for k, cid in (g.get('pista') or {}).items():
        c = cars.get(cid)
        if not c: continue
        out.setdefault('clases', {})[str(k)] = c['clase']
        if c.get('h'): propio[str(k)] = c['h']
        gar[str(k)] = {'id': c['id'], 'nombre': c['nombre']}
    if gar: out['propio'] = propio; out['garage'] = gar
    return out


EJEMPLOS = [
    # (nombre, escudería, color, clase, h, chip, techo, motor, peso, dueño, nota)
    ('Rayo Rojo (ejemplo)', 'Escudería Roja', '#e53935', 'con_iman', 0.2, 1, '#ffffff', 'Estándar 18k', 78, 'Club', 'Cambio de llantas'),
    ('Flecha Azul (ejemplo)', 'Equipo Azul', '#1e88e5', 'sin_iman', 0.0, 2, '#ffeb3b', 'Estándar 18k', 74, 'Club', 'Escobillas nuevas'),
    ('Trueno Amarillo (ejemplo)', 'Amarillo Racing', '#fdd835', 'modificado', -0.3, 3, '#000000', 'Motor 21k', 80, 'Club', 'Guía nueva'),
    ('Sombra Negra (ejemplo)', 'Negro Team', '#212121', 'con_iman', 0.0, 4, '#ff9800', 'Estándar 18k', 77, 'Club', ''),
    ('Lima Verde (ejemplo)', 'Verde GP', '#43a047', 'sin_iman', -0.2, 5, '#e91e63', 'Estándar 18k', 72, 'Club', 'Cambio de llantas'),
    ('Nube Blanca (ejemplo)', 'Blanco Motorsport', '#eeeeee', 'sin_iman', 0.1, 6, '#2196f3', 'Estándar 18k', 75, 'Club', ''),
]


class Garage:
    def __init__(self, directory, avisos=None):
        self.directory = Path(directory); self.fotos = self.directory / 'garage-fotos'
        self.fotos.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'garage.json'; self.lock = threading.RLock()
        d, aviso = durable.leer_json(self.path, validate=self.check, nombre='garage.json (coches del Garage)')
        if aviso and avisos is not None: avisos.append(aviso)
        self.data = d or {'version': 0, 'cars': [], 'pista': {}, 'historial': [], 'hechos': []}
    @staticmethod
    def check(d):
        if not isinstance(d, dict) or not isinstance(d.get('cars'), list) or type(d.get('version')) != int: raise ValueError('garage.json inválido')
        d.setdefault('pista', {}); d.setdefault('historial', []); d.setdefault('hechos', [])
        return d
    def read(self):
        with self.lock: return copy.deepcopy(self.data)
    def _save(self):
        self.data['version'] += 1
        durable.escribir_json(self.path, self.data, backup=True, indent=1)
    def _find(self, cid):
        return next((c for c in self.data['cars'] if c['id'] == cid), None)
    def _limpiar_pista(self):
        ids = {c['id']: c for c in self.data['cars']}; p = {}
        for k, cid in (self.data.get('pista') or {}).items():
            c = ids.get(cid)
            if c and (c['chip'] is None or str(c['chip']) == str(k)) and cid not in p.values(): p[str(k)] = cid
        self.data['pista'] = p
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
        """POST /api/garage: save | delete | pista | quitar_foto | ejemplos."""
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
                else:
                    self.data['cars'].append(car)
                    # Coche nuevo con chip y ese mando libre: queda en pista solo (se quita en el Garage).
                    if car['chip'] and str(car['chip']) not in self.data.setdefault('pista', {}): self.data['pista'][str(car['chip'])] = car['id']
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
            if a == 'pista':
                # Poner un coche en pista con un mando (o quitarlo: id vacío). El mando debe ser el de su chip.
                try: m = int(p.get('mando'))
                except (TypeError, ValueError): raise GarageError('Mando del 1 al 6.')
                if not 1 <= m <= 6: raise GarageError('Mando del 1 al 6.')
                cid = p.get('id') or ''
                pista = self.data.setdefault('pista', {})
                if not cid: pista.pop(str(m), None)
                else:
                    c = self._find(cid)
                    if not c: raise GarageError('Ese coche ya no está en el Garage.', 404)
                    if c['chip'] is not None and c['chip'] != m: raise GarageError('%s tiene el chip %d: solo corre con el mando %d.' % (c['nombre'], c['chip'], c['chip']))
                    for k in [k for k, v in pista.items() if v == cid]: pista.pop(k)
                    pista[str(m)] = cid
                self._save(); return self.view()
            if a == 'ejemplos':
                hay = {c['nombre'] for c in self.data['cars']}; n = 0
                for (nom, esc, col, cl, h, chip, techo, motor, peso, dueno, nota) in EJEMPLOS:
                    if nom in hay or len(self.data['cars']) >= MAX_CARS: continue
                    car = limpiar_coche({'nombre': nom, 'escuderia': esc, 'color': col, 'clase': cl, 'h': h, 'chip': chip, 'techo': techo,
                                         'motor': motor, 'peso': peso, 'dueno': dueno, 'ejemplo': True,
                                         'notas': [{'fecha': time.strftime('%Y-%m-%d'), 'texto': nota}] if nota else []})
                    self.data['cars'].append(car); n += 1
                    if str(chip) not in self.data['pista']: self.data['pista'][str(chip)] = car['id']
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
            d = {'version': self.data['version'], 'cars': copy.deepcopy(self.data['cars']), 'pista': dict(self.data.get('pista') or {})}
        st = self.stats()
        for c in d['cars']: c['hist'] = st.get(c['id'], {'mejor': None, 'vueltas': 0, 'carreras': 0, 'ganadas': 0, 'practicas': 0, 'ultima': None})
        return d
