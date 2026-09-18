import protected_core as _protected_core
import ctypes
from ctypes import wintypes
from contextlib import contextmanager, nullcontext
import os
from pathlib import Path
import sys
import time
import uuid
NAMES = ('JD_LLM_API_KEY', 'JD_LLM_API_KEY_2')
SERVICE = 'jd-material-self-operated'

@contextmanager
def configuration_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'configuration.lock'
    deadline = time.monotonic() + 180
    token = (str(os.getpid()) + ':' + uuid.uuid4().hex).encode('ascii')
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 384)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError('another credential configuration is active or interrupted; inspect it before removing its lock') from None
            time.sleep(0.2)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(token)
        yield
    finally:
        if path.exists() and path.read_bytes() == token:
            path.unlink()

def checked_name(name):
    if name not in NAMES:
        raise ValueError('unsupported credential slot')
    return name

def user_environment(name):
    checked_name(name)
    if os.name != 'nt':
        return ''
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
            value, kind = winreg.QueryValueEx(registry, name)
            return value.strip() if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str) else ''
    except FileNotFoundError:
        return ''

class WindowsStore:

    def __init__(self, root=None):
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
        self.root = Path(root) if root is not None else base / 'JDMaterialSelfOperated/credentials'

    def path(self, name):
        checked_name(name)
        return self.root / ('primary.dpapi' if name == NAMES[0] else 'secondary.dpapi')

    @staticmethod
    def crypt(data, protect):
        if os.name != 'nt':
            raise RuntimeError('Windows secure credential storage required')

        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        destination = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        operation = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        operation.restype = wintypes.BOOL
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
            raise RuntimeError('secure credential storage cannot be decrypted by this OS user')
        try:
            return ctypes.string_at(destination.data, destination.size)
        finally:
            kernel.LocalFree(destination.data)

    def get(self, name):
        path = self.path(name)
        if not path.exists():
            return None
        return self.crypt(path.read_bytes(), False).decode('utf-8')

    def put(self, name, value):
        path = self.path(name)
        encrypted = self.crypt(value.encode('utf-8'), True)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(encrypted)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, name):
        self.path(name).unlink(missing_ok=True)

    def lock(self):
        return configuration_lock(self.root)

class KeyringStore:

    def __init__(self):
        try:
            import keyring
            backend = keyring.get_keyring()
        except _protected_core.ProtectedCoreError:
            raise
        except Exception:
            raise RuntimeError('secure credential storage unavailable; install an OS keyring or use session-only entry') from None
        if type(backend).__module__ not in ('keyring.backends.macOS', 'keyring.backends.SecretService', 'keyring.backends.libsecret'):
            raise RuntimeError('secure credential storage requires an OS keyring; plaintext backends are not allowed')
        self.backend = backend

    def get(self, name):
        return self.backend.get_password(SERVICE, checked_name(name))

    def put(self, name, value):
        self.backend.set_password(SERVICE, checked_name(name), value)

    def delete(self, name):
        if self.get(name) is not None:
            self.backend.delete_password(SERVICE, checked_name(name))

    def lock(self):
        return configuration_lock(Path.home() / '.cache' / SERVICE / 'credential-setup')

def default_store():
    return WindowsStore() if os.name == 'nt' else KeyringStore()

def existing(name, environment, store=None, *, skip_store=False):
    value = environment.get(checked_name(name), '').strip()
    if value:
        return (value, 'process-environment')
    value = user_environment(name)
    if value:
        return (value, 'user-environment')
    if skip_store:
        return ('', 'missing')
    try:
        value = (store or default_store()).get(name)
    except _protected_core.ProtectedCoreError:
        raise
    except Exception:
        raise RuntimeError('secure credential storage could not be read; inspect or explicitly reconfigure it, do not repeatedly prompt') from None
    return (value.strip(), 'secure-store') if value and value.strip() else ('', 'missing')

def prompt_key(name, remember=True):
    checked_name(name)
    description = '保存到本机当前系统用户的加密凭据库，后续自动复用。' if remember else '仅供本次运行，不保存。'
    label = '第二把Key' if name == NAMES[1] else '主Key'
    root = None
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        value = simpledialog.askstring('自营素材维护：配置' + label, '请输入' + label + '。' + description + '\n不会写入项目、聊天、日志或命令行。取消即停止。', show='*', parent=root)
    except _protected_core.ProtectedCoreError:
        raise
    except Exception:
        if not sys.stdin.isatty():
            raise RuntimeError('local credential input unavailable; run the secure launcher in an interactive local session') from None
        import getpass
        value = getpass.getpass(label + '（隐藏输入；' + description + '）：')
    finally:
        if root is not None:
            try:
                root.destroy()
            except _protected_core.ProtectedCoreError:
                raise
            except Exception:
                pass
    value = (value or '').strip()
    if not value:
        raise ValueError('credential entry cancelled; task stopped without another prompt')
    return value

def ensure_environment(*, dual=False, environ=None, store=None, prompt=None, remember=True):
    environment = os.environ if environ is None else environ
    prompt = prompt or prompt_key
    for name in NAMES if dual else NAMES[:1]:
        value, _ = existing(name, environment, store, skip_store=not remember)
        if not value:
            target = store or default_store() if remember else None
            lock = target.lock() if callable(getattr(target, 'lock', None)) else nullcontext()
            with lock:
                value, _ = existing(name, environment, target, skip_store=not remember)
                if not value:
                    value = (prompt(name, remember) or '').strip()
                    if not value or not value.isascii() or any((character.isspace() for character in value)):
                        raise ValueError('credential entry cancelled or invalid; task stopped')
                    if name == NAMES[1] and value == environment.get(NAMES[0]):
                        raise ValueError('dual-key execution requires two distinct credentials')
                    if target is not None:
                        try:
                            target.put(name, value)
                        except _protected_core.ProtectedCoreError:
                            raise
                        except Exception:
                            raise RuntimeError('secure credential storage could not be saved; task stopped without repeated prompting') from None
        environment[name] = value
    if dual and environment[NAMES[0]] == environment[NAMES[1]]:
        raise ValueError('dual-key execution requires two distinct credentials')

def credential_status(*, environ=None, store=None):
    environment = os.environ if environ is None else environ
    status = {}
    for name in NAMES:
        value, source = existing(name, environment, store)
        status[name] = {'configured': bool(value), 'source': source}
    return status

def needs_credentials(arguments):
    if not arguments or any((flag in arguments for flag in ('--help', '-h', '--plan-only', '--cached-only'))):
        return False
    return arguments[0] in ('maintain-self-operated', 'run-direct', 'run-resume')

def prepare_command(arguments, *, environ=None, store=None, prompt=None, remember=True):
    if needs_credentials(arguments):
        ensure_environment(dual='--dual-key-images' in arguments, environ=environ, store=store, prompt=prompt, remember=remember)
