"""Un solo servidor de Puto el último por carpeta de datos (archivo de candado, no el puerto serial)."""
import errno, os
from pathlib import Path

class InstanceLock:
    """Un solo servidor por carpeta de datos. El sistema suelta el candado solo si el proceso muere (kill -9, apagón)."""
    def __init__(self,data):
        import fcntl;self.fcntl=fcntl
        Path(data).mkdir(parents=True,exist_ok=True)
        self.path=Path(data)/'.servidor.lock';self.fd=os.open(str(self.path),os.O_RDWR|os.O_CREAT,0o644)
    def acquire(self,wait=False):
        flags=self.fcntl.LOCK_EX|(0 if wait else self.fcntl.LOCK_NB)
        try:self.fcntl.flock(self.fd,flags)
        except OSError as e:
            if e.errno in (errno.EAGAIN,errno.EACCES,errno.EWOULDBLOCK):return False
            raise
        os.ftruncate(self.fd,0);os.write(self.fd,str(os.getpid()).encode());return True
