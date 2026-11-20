"""Guardado a prueba de apagones (cerrar la Mac, se va la luz, proceso matado).

- escribir_*: archivo temporal en la MISMA carpeta + flush + fsync (F_FULLFSYNC en macOS) + rename
  atómico + fsync de la carpeta. Si se corta la luz a la mitad, queda el archivo anterior completo.
- Copia de respaldo opcional (nombre.json.bak) del último archivo bueno, para recuperar si el
  disco devuelve un archivo vacío o a medias después de un apagón.
- leer_json: si el archivo está dañado, lo aparta como nombre.danado-FECHA (no se borra nada)
  y usa el respaldo .bak. Devuelve un aviso en español para mostrar en la app.
Sin dependencias. Nunca toca el puerto serial.
"""
import json, os, shutil, tempfile, time
from pathlib import Path

try:
    import fcntl
    _FULLFSYNC = getattr(fcntl, 'F_FULLFSYNC', None)
except ImportError:  # pragma: no cover
    fcntl = None; _FULLFSYNC = None

def _sync(fd):
    # En macOS fsync() no obliga al disco a vaciar su caché; F_FULLFSYNC sí.
    if _FULLFSYNC is not None:
        try:
            fcntl.fcntl(fd, _FULLFSYNC); return
        except OSError:
            pass
    os.fsync(fd)

def _sync_dir(folder):
    try:
        fd = os.open(str(folder), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)

_UMASK = os.umask(0o022); os.umask(_UMASK)   # se lee una vez al importar (os.umask no es seguro entre hilos)
def _umask():
    return _UMASK

def backup_path(path):
    path = Path(path); return path.with_name(path.name + '.bak')

def escribir_bytes(path, data, backup=False):
    path = Path(path); folder = path.parent
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=str(folder))
    try:
        # mkstemp crea con 0600: dejar los mismos permisos que tenía el archivo (o los normales 0644).
        try: mode = os.stat(path).st_mode & 0o777
        except OSError: mode = 0o666 & ~_umask()
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); _sync(f.fileno())
        if backup and path.exists():
            # El respaldo es el archivo bueno ANTERIOR (enlace duro: no copia datos; si no se puede, copia).
            bak = backup_path(path); btmp = bak.with_name(bak.name + '.tmp')
            try:
                try: os.unlink(btmp)
                except FileNotFoundError: pass
                try: os.link(path, btmp)
                except OSError: shutil.copyfile(path, btmp)
                os.replace(btmp, bak)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    _sync_dir(folder)

def escribir_texto(path, text, encoding='utf-8', backup=False):
    escribir_bytes(path, text.encode(encoding), backup)

def escribir_json(path, obj, backup=False, **kw):
    kw.setdefault('ensure_ascii', False)
    escribir_bytes(path, json.dumps(obj, **kw).encode('utf-8'), backup)

def apartar(path):
    """Mueve un archivo dañado a nombre.danado-AAAAMMDD-HHMMSS (nunca se borra)."""
    path = Path(path)
    dest = path.with_name('%s.danado-%s' % (path.name, time.strftime('%Y%m%d-%H%M%S')))
    n = 1
    while dest.exists():
        dest = path.with_name('%s.danado-%s-%d' % (path.name, time.strftime('%Y%m%d-%H%M%S'), n)); n += 1
    try:
        os.replace(path, dest); return dest
    except OSError:
        return None

def _load(path, validate):
    raw = Path(path).read_bytes()
    if not raw.strip(): raise ValueError('archivo vacío')
    data = json.loads(raw.decode('utf-8'))
    if validate is not None:
        r = validate(data)
        if r is not None: data = r
    return data

def leer_json(path, validate=None, nombre=None):
    """Devuelve (datos, aviso). datos=None si no existe o no se pudo recuperar.
    validate(d) debe lanzar una excepción si d no sirve (o devolver d corregido)."""
    path = Path(path); nombre = nombre or path.name; bak = backup_path(path)
    if not path.exists():
        if bak.exists():
            try:
                data = _load(bak, validate)
                return data, 'No se encontró %s; se recuperó la última copia buena.' % nombre
            except Exception:
                return None, None
        return None, None
    try:
        return _load(path, validate), None
    except Exception:
        pass
    moved = apartar(path)
    guardado = (' El archivo dañado quedó guardado como %s.' % moved.name) if moved else ''
    if bak.exists():
        try:
            data = _load(bak, validate)
            return data, 'El archivo %s se dañó (¿apagón o se cerró la Mac a media escritura?). Se recuperó la última copia buena.%s' % (nombre, guardado)
        except Exception:
            pass
    return None, 'El archivo %s estaba dañado y no había copia buena; se empezó limpio.%s' % (nombre, guardado)

def limpiar_temporales(folder):
    """Borra temporales .tmp que dejó un proceso matado a media escritura (no toca datos)."""
    folder = Path(folder)
    if not folder.is_dir(): return 0
    n = 0
    for p in folder.iterdir():
        if p.is_file() and p.name.endswith('.tmp') and (p.name.startswith('.') or p.name in ('session.tmp', 'gp_session.tmp', 'gp_config.tmp', 'pilotos.tmp', 'vueltas.tmp')):
            try: p.unlink(); n += 1
            except OSError: pass
    return n
