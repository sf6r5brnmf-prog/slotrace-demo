"""🏆 Ranking de pilotos por clase de coche, con TIEMPOS REALES (sin ningún hándicap: ni de clase, ni del coche, ni de nivel).

El hándicap solo cambia los resultados de cada carrera; el ranking y el nivel automático usan la vuelta real.
Por clase porque con imán, sin imán y modificado no se comparan.
data/ranking.json = {'version', 'pilotos': {nombre en minúsculas: {'name', 'clases': {clase: {'mejor', 'vueltas',
                     'sesiones', 'fuente', 'at'}}}}, 'hechos': [claves de sesiones ya contadas]}
"""
import copy, threading, time
from pathlib import Path
import durable
import handicap as H

MIN_VUELTAS = H.MIN_VUELTAS_NIVEL   # igual que el nivel automático
MAX_HECHOS = 2000


class Ranking:
    def __init__(self, directory, avisos=None):
        self.path = Path(directory) / 'ranking.json'; self.lock = threading.RLock()
        d, aviso = durable.leer_json(self.path, validate=self.check, nombre='ranking.json (ranking de pilotos)')
        if aviso and avisos is not None: avisos.append(aviso)
        self.data = d or {'version': 0, 'pilotos': {}, 'hechos': []}
    @staticmethod
    def check(d):
        if not isinstance(d, dict) or not isinstance(d.get('pilotos'), dict) or type(d.get('version')) != int: raise ValueError('ranking.json inválido')
        d.setdefault('hechos', [])
        return d
    def ya(self, clave):
        with self.lock: return clave in self.data['hechos']
    def registrar(self, clave, fuente, rows, ahora=None):
        """rows = [(nombre, clase, mejor vuelta REAL, vueltas válidas)]. Cada sesión una sola vez."""
        ahora = ahora or time.time()
        with self.lock:
            if clave in self.data['hechos']: return False
            self.data['hechos'].append(clave); del self.data['hechos'][:-MAX_HECHOS]
            for name, clase, best, n in rows:
                if best is None or n < MIN_VUELTAS or clase not in H.NOMBRE: continue
                p = self.data['pilotos'].setdefault(name.casefold(), {'name': name, 'clases': {}})
                p['name'] = name
                c = p['clases'].setdefault(clase, {'mejor': None, 'vueltas': 0, 'sesiones': 0, 'fuente': '', 'at': None})
                c['vueltas'] += int(n); c['sesiones'] += 1
                if c['mejor'] is None or best < c['mejor']:
                    c['mejor'] = round(float(best), 3); c['fuente'] = fuente; c['at'] = ahora
            self.data['version'] += 1
            durable.escribir_json(self.path, self.data, backup=True, indent=1)
            return True
    def renombrar(self, viejo, nuevo):
        """Cambio de nombre o dos registros unidos: junta sus tiempos (se queda la mejor vuelta de cada clase)."""
        with self.lock:
            a = self.data['pilotos'].pop((viejo or '').casefold(), None)
            if not a: return False
            b = self.data['pilotos'].setdefault(nuevo.casefold(), {'name': nuevo, 'clases': {}}); b['name'] = nuevo
            for k, c in a['clases'].items():
                d = b['clases'].get(k)
                if not d: b['clases'][k] = c; continue
                d['vueltas'] += c.get('vueltas', 0); d['sesiones'] += c.get('sesiones', 0)
                if c.get('mejor') is not None and (d.get('mejor') is None or c['mejor'] < d['mejor']): d.update(mejor=c['mejor'], fuente=c.get('fuente'), at=c.get('at'))
            self.data['version'] += 1; durable.escribir_json(self.path, self.data, backup=True, indent=1); return True
    def borrar(self, name):
        with self.lock:
            if self.data['pilotos'].pop((name or '').casefold(), None) is None: return False
            self.data['version'] += 1; durable.escribir_json(self.path, self.data, backup=True, indent=1); return True
    def nombres(self):
        with self.lock: return [p['name'] for p in self.data['pilotos'].values()]
    def mejores(self, name):
        """{clase: mejor vuelta real} de un piloto (para su tarjeta)."""
        with self.lock:
            p = self.data['pilotos'].get((name or '').casefold())
            return {k: v['mejor'] for k, v in (p or {}).get('clases', {}).items() if v.get('mejor') is not None}
    def view(self, h, niveles):
        """niveles = {nombre en minúsculas: (nivel actual, 'registro'|'torneo')}. Lista por clase, de la mejor vuelta real a la peor."""
        with self.lock: pil = copy.deepcopy(self.data['pilotos']); ver = self.data['version']
        out = {}
        for k, _ in H.CLASES:
            rows = []
            for key, p in pil.items():
                c = p['clases'].get(k)
                if not c or c.get('mejor') is None: continue
                nv = niveles.get(key)
                rows.append({'name': p['name'], 'mejor': c['mejor'], 'vueltas': c['vueltas'], 'sesiones': c['sesiones'], 'fuente': c.get('fuente') or '',
                             'nivel': H.nivel_ok(nv[0]) if nv else None, 'donde': nv[1] if nv else '',
                             'nivel_tiempo': H.nivel_por_tiempo(h, k, c['mejor'])})
            rows.sort(key=lambda r: (r['mejor'], r['name'].casefold()))
            for i, r in enumerate(rows): r['pos'] = i + 1
            out[k] = {'nombre': H.NOMBRE[k], 'icon': H.ICON[k], 'cortes': H.texto_cortes(h, k), 'pilotos': rows}
        return {'version': ver, 'clases': out, 'orden': [k for k, _ in H.CLASES], 'min_vueltas': MIN_VUELTAS,
                'nivel_auto': (h or {}).get('nivel_auto', H.DEFAULT['nivel_auto']), 'nota': 'Tiempos reales, sin hándicap'}
