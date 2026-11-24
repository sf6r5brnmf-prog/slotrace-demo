"""👥 Registro de pilotos (data/registro.json): TODOS los pilotos, no solo los 6 de la parrilla.

- Cada piloto: id, nombre, apodo, avatar (opcional), color del traje, nivel y de dónde salió (manual / auto),
  regular o invitado, archivado, coche habitual del Garage (opcional) e historial de sus sesiones.
- La PARRILLA sigue siendo data/pilotos.json (6 lugares con su color de equipo): ahí se «sientan» pilotos del
  registro para correr. Cada lugar guarda una copia (name, avatar, nivel…) y el id del piloto («pid»).
- La clase (imán o no) NO es del piloto: es del coche del Garage que lleve en cada carrera.
- Nada se borra solo: al estrenar el registro se copian los pilotos de la parrilla, del torneo y del ranking.
"""
import copy, re, threading, time, unicodedata, uuid
from pathlib import Path
import durable
import handicap as H

COPIA = ('name', 'avatar', 'nivel', 'sugerido', 'nivel_cambio')   # lo que la parrilla copia del registro
MAX_PILOTOS = 300
MAX_HIST = 60
COLORES = ['#edf2f7', '#ffe23b', '#ff4d50', '#3d96ff', '#50dc92', '#ff963d']
ID_RE = re.compile(r'^[0-9a-f]{10}$')
GAR_RE = re.compile(r'^[0-9a-f]{12}$')


class PilotoError(Exception):
    def __init__(self, message, status=400, **extra): super().__init__(message); self.status = status; self.extra = extra


def clave(nombre):
    """Para encontrar duplicados: sin acentos, sin mayúsculas, sin espacios de más («José  Luis» = «jose luis»)."""
    s = unicodedata.normalize('NFKD', str(nombre or '')).encode('ascii', 'ignore').decode().casefold()
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', s).split())


def limpiar_nombre(v, campo='nombre', minimo=1):
    if v is None: v = ''
    if not isinstance(v, str): raise PilotoError('Escribe el %s del piloto.' % campo)
    v = ' '.join(v.split())
    if not minimo <= len(v) <= 32 or any(ord(c) < 32 for c in v): raise PilotoError('El %s debe tener de %d a 32 caracteres.' % (campo, minimo or 1) if minimo else 'El apodo debe tener máximo 32 caracteres.')
    return v


class Registro:
    def __init__(self, directory, avisos=None):
        self.path = Path(directory) / 'registro.json'; self.lock = threading.RLock()
        d, aviso = durable.leer_json(self.path, validate=self.check, nombre='registro.json (registro de pilotos)')
        if aviso and avisos is not None: avisos.append(aviso)
        self.nuevo = d is None
        self.data = d or {'version': 0, 'pilotos': [], 'hist': {}, 'hechos': [], 'migrado': False}

    @staticmethod
    def check(d):
        if not isinstance(d, dict) or not isinstance(d.get('pilotos'), list) or type(d.get('version')) != int: raise ValueError('registro.json inválido')
        d.setdefault('hist', {}); d.setdefault('hechos', []); d.setdefault('migrado', True)
        for p in d['pilotos']:
            p.setdefault('apodo', ''); p.setdefault('avatar', ''); p.setdefault('tipo', 'regular'); p.setdefault('archivado', False)
            p.setdefault('coche', ''); p.setdefault('nivel', H.NIVEL_DEFAULT); p.setdefault('nivel_fuente', 'manual'); p.setdefault('color', COLORES[0])
            p.setdefault('foto', bool(p.get('avatar')))
        return d

    def save(self):
        self.data['version'] += 1
        durable.escribir_json(self.path, self.data, backup=True, indent=1)

    def read(self):
        with self.lock: return copy.deepcopy(self.data)

    def find(self, pid):
        return next((p for p in self.data['pilotos'] if p['id'] == pid), None)

    def por_nombre(self, nombre):
        k = clave(nombre)
        return next((p for p in self.data['pilotos'] if clave(p['name']) == k), None)

    def nuevo_piloto(self, name, **kw):
        p = {'id': uuid.uuid4().hex[:10], 'name': name, 'apodo': '', 'avatar': '', 'foto': False, 'color': COLORES[len(self.data['pilotos']) % 6],
             'nivel': H.NIVEL_DEFAULT, 'nivel_fuente': 'manual', 'tipo': 'regular', 'archivado': False, 'coche': '', 'creado': time.time()}
        p.update({k: v for k, v in kw.items() if v is not None})
        self.data['pilotos'].append(p); return p

    # ---------- migración: el registro nace con TODO lo que ya había (nada se pierde) ----------
    def migrar(self, slots, inscritos, ranking_nombres):
        """Devuelve True si cambió la parrilla (se le puso «pid» a cada lugar)."""
        with self.lock:
            cambio_slots = False; cambio = False
            for i, s in enumerate(slots):
                if not s: continue
                p = self.find(s.get('pid') or '') or self.por_nombre(s['name'])
                if not p:
                    p = self.nuevo_piloto(s['name'], avatar=s.get('avatar') or '', foto=bool(s.get('avatar')), color=COLORES[i], nivel=H.nivel_ok(s.get('nivel')))
                    for k in ('sugerido', 'nivel_cambio'):
                        if s.get(k): p[k] = copy.deepcopy(s[k])
                    cambio = True
                if s.get('pid') != p['id']: s['pid'] = p['id']; cambio_slots = True
            if not self.data.get('migrado'):
                for q in inscritos or []:
                    if not self.por_nombre(q['name']):
                        self.nuevo_piloto(q['name'], nivel=H.nivel_ok(q.get('nivel')), tipo='invitado', coche=q.get('garage_id') or ''); cambio = True
                for n in ranking_nombres or []:
                    if n and not self.por_nombre(n): self.nuevo_piloto(n, tipo='invitado'); cambio = True
                self.data['migrado'] = True; cambio = True
            if cambio: self.save()
            return cambio_slots

    def invitados(self, nombres, info=None):
        """Nombres escritos a mano (inscritos del torneo): entran al registro como invitados. Nunca duplica."""
        info = info or {}; cambio = False
        with self.lock:
            for n in nombres:
                if n and not self.por_nombre(n):
                    q = info.get(n) or {}
                    self.nuevo_piloto(n, nivel=H.nivel_ok(q.get('nivel')), tipo='invitado', coche=q.get('garage_id') or ''); cambio = True
            if cambio: self.save()
        return cambio

    def desde_slots(self, slots):
        """La parrilla cambió por fuera (alta vieja por lugar, nivel automático): el registro se pone al día."""
        with self.lock:
            cambio = False; cambio_slots = False
            for i, s in enumerate(slots):
                if not s: continue
                p = self.find(s.get('pid') or '') or self.por_nombre(s['name'])
                if not p: p = self.nuevo_piloto(s['name'], color=COLORES[i], foto=bool(s.get('avatar'))); cambio = True
                if s.get('pid') != p['id']: s['pid'] = p['id']; cambio_slots = True
                for k in COPIA:
                    v = s.get(k)
                    if k in ('sugerido', 'nivel_cambio'):
                        if v != p.get(k):
                            if v: p[k] = copy.deepcopy(v)
                            else: p.pop(k, None)
                            cambio = True
                    elif v is not None and p.get(k) != v:
                        if k == 'nivel': p['nivel_fuente'] = 'auto' if s.get('nivel_cambio') else 'manual'
                        if k == 'avatar': p['foto'] = True
                        p[k] = v; cambio = True
            if cambio: self.save()
            return cambio_slots

    def a_slots(self, slots):
        """El registro cambió: copia nombre, avatar y nivel a los lugares de la parrilla de ese piloto."""
        cambio = False
        with self.lock:
            for s in slots:
                if not s or not s.get('pid'): continue
                p = self.find(s['pid'])
                if not p: continue
                este = False
                for k in COPIA:
                    v = p.get(k)
                    if k == 'avatar' and not v: continue
                    if s.get(k) != v:
                        if v is None: s.pop(k, None)
                        else: s[k] = copy.deepcopy(v)
                        este = True
                if este: s['revision'] = uuid.uuid4().hex; cambio = True
        return cambio

    # ---------- historial por piloto ----------
    def ya(self, k):
        with self.lock: return k in self.data['hechos']

    def registrar(self, k, info, filas):
        """filas = [(nombre, mejor vuelta real, vueltas, ganó, coche, posición)]. Cada sesión una vez."""
        with self.lock:
            if k in self.data['hechos']: return False
            self.data['hechos'].append(k); del self.data['hechos'][:-2000]
            for name, best, n, gano, coche, pos in filas:
                p = self.por_nombre(name)
                if not p: continue
                h = self.data['hist'].setdefault(p['id'], [])
                h.insert(0, dict(info, best=round(best, 3) if best is not None else None, vueltas=int(n or 0), gano=bool(gano), coche=coche or '', pos=pos))
                del h[MAX_HIST:]
            self.save(); return True

    def stats(self, pid):
        h = self.data['hist'].get(pid) or []
        return {'carreras': sum(1 for x in h if x.get('tipo') != 'practica'), 'practicas': sum(1 for x in h if x.get('tipo') == 'practica'),
                'ganadas': sum(1 for x in h if x.get('gano')), 'vueltas': sum(x.get('vueltas') or 0 for x in h), 'ultima': h[0].get('fuente') if h else ''}

    # ---------- comandos ----------
    def guardar(self, payload, avatar=None):
        """Alta o edición. Nombre único (sin acentos ni mayúsculas): si ya existe, avisa para unirlos."""
        with self.lock:
            pid = payload.get('id'); p = self.find(pid) if pid else None
            if pid and not p: raise PilotoError('Ese piloto ya no está en el registro.', 404)
            name = limpiar_nombre(payload.get('name'))
            apodo = limpiar_nombre(payload.get('apodo') or '', 'apodo', 0) if payload.get('apodo') else ''
            otro = next((x for x in self.data['pilotos'] if x is not p and clave(x['name']) == clave(name)), None)
            if otro: raise PilotoError('Ya hay un piloto «%s» en el registro.' % otro['name'], 409, duplicado={'id': otro['id'], 'name': otro['name']})
            nv = payload.get('nivel', (p or {}).get('nivel') or H.NIVEL_DEFAULT)
            if nv not in H.NIVEL_TXT: raise PilotoError('Elige Novato, Intermedio o Experto.')
            tipo = payload.get('tipo', (p or {}).get('tipo') or 'regular')
            if tipo not in ('regular', 'invitado'): raise PilotoError('Tipo de piloto inválido.')
            color = payload.get('color', (p or {}).get('color') or COLORES[0])
            if color not in COLORES: color = COLORES[0]
            coche = payload.get('coche', (p or {}).get('coche') or '')
            if coche and not GAR_RE.match(str(coche)): raise PilotoError('Coche habitual inválido.')
            if p is None:
                if len(self.data['pilotos']) >= MAX_PILOTOS: raise PilotoError('El registro está lleno (%d pilotos). Borra o une algunos.' % MAX_PILOTOS)
                p = self.nuevo_piloto(name)
            viejo = p['name']
            if p['nivel'] != nv: p['nivel_fuente'] = 'manual'; p.pop('sugerido', None); p.pop('nivel_cambio', None)
            p.update(name=name, apodo=apodo, nivel=nv, tipo=tipo, color=color, coche=coche)
            if avatar: p['avatar'] = avatar; p['foto'] = bool(payload.get('foto'))
            self.save()
            return p, viejo

    def unir(self, de, a):
        """Une dos registros del mismo piloto: se queda «a» (con su nombre); suma el historial de «de»."""
        with self.lock:
            x, y = self.find(de), self.find(a)
            if not x or not y or x is y: raise PilotoError('Elige dos pilotos distintos para unir.')
            h = (self.data['hist'].pop(x['id'], None) or []) + (self.data['hist'].get(y['id']) or [])
            h.sort(key=lambda r: -(r.get('at') or 0)); self.data['hist'][y['id']] = h[:MAX_HIST]
            if not y.get('avatar') and x.get('avatar'): y['avatar'] = x['avatar']; y['foto'] = x.get('foto', True)
            if not y.get('coche') and x.get('coche'): y['coche'] = x['coche']
            if y.get('tipo') == 'invitado' and x.get('tipo') == 'regular': y['tipo'] = 'regular'
            y['archivado'] = y.get('archivado') and x.get('archivado')
            self.data['pilotos'].remove(x); self.save()
            return x, y

    def simple(self, pid, accion, valor=None):
        with self.lock:
            p = self.find(pid)
            if not p: raise PilotoError('Ese piloto ya no está en el registro.', 404)
            if accion == 'archivar': p['archivado'] = bool(valor)
            elif accion == 'promover': p['tipo'] = 'regular'
            elif accion == 'nivel':
                if valor not in H.NIVEL_TXT: raise PilotoError('Elige Novato, Intermedio o Experto.')
                acepta = (p.get('sugerido') or {}).get('nivel') == valor
                p['nivel'] = valor; p['nivel_fuente'] = 'auto' if acepta else 'manual'; p.pop('sugerido', None); p.pop('nivel_cambio', None)
            elif accion == 'nivel_descartar': p.pop('sugerido', None); p.pop('nivel_cambio', None)
            elif accion == 'borrar':
                self.data['pilotos'].remove(p); self.data['hist'].pop(pid, None)
            else: raise PilotoError('Acción desconocida.')
            self.save(); return p

    def aplicar_nivel(self, h, name, clase, best, n, fuente, ahora):
        """Nivel automático por tiempo (también para pilotos que no están en la parrilla)."""
        with self.lock:
            p = self.por_nombre(name)
            if not p: return False
            antes = (p.get('nivel'), p.get('sugerido'), p.get('nivel_cambio'))
            r = H.aplicar_nivel(p, h, clase, best, n, fuente, ahora)
            if r == 'cambio': p['nivel_fuente'] = 'auto'
            return (p.get('nivel'), p.get('sugerido'), p.get('nivel_cambio')) != antes
