import protected_core as _protected_core
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid
import zipfile
PRODUCT = 'jd-material-self-operated'
REPOSITORY = 'ctzlyj/jd-material-self-operated-dist'
API = 'https://api.github.com/repos/' + REPOSITORY
INTERVAL = 6 * 60 * 60
MAX_BYTES = 32 * 1024 * 1024
BOUNDARY = ('requirements.txt', 'scripts/protected_core.py', 'scripts/core_contract.py', 'scripts/protected-settings.json', 'scripts/identity.mjs', 'scripts/identity-request.mjs')
_running_root = None

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)

def safe_path(root, relative):
    parts = PurePosixPath(relative).parts
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{number}' for number in range(1, 10)), *(f'LPT{number}' for number in range(1, 10))}
    if not parts or PurePosixPath(relative).is_absolute() or '\\' in relative or any((part in ('..', '.', '.state', '.cache') or part.endswith((' ', '.')) or any((character in part for character in ':<>"|?*')) or any((ord(character) < 32 for character in part)) or (part.split('.')[0].upper() in reserved) for part in parts)):
        raise ValueError('unsafe update path')
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('update path escaped root')
    if any((path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) for path in (target, *target.parents))):
        raise ValueError('linked update paths are not supported')
    return target

def home(root):
    return safe_path(root.parent, '.self-operated-updates')

def installed(root):
    return root.name == PRODUCT and all(((root / name).is_file() for name in ('PROTECTED_BUILD.json', '.install-baseline.json', 'VERSION')))

@contextmanager
def session_lock(root):
    path = home(root) / 'session.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('self-operated session busy; no update or second worker started') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

class NoRedirect(HTTPRedirectHandler):

    def redirect_request(self, request, file, code, message, headers, newurl):
        raise ValueError('update redirect rejected')

def fetch_bytes(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc not in ('api.github.com', 'codeload.github.com') or parsed.username or (not (url.startswith(API + '/') or url.startswith('https://codeload.github.com/' + REPOSITORY + '/zip/'))):
        raise ValueError('untrusted update source')
    request = Request(url, headers={'User-Agent': PRODUCT + '-updater', 'Accept': 'application/vnd.github+json'})
    with build_opener(NoRedirect()).open(request, timeout=8) as response:
        if response.status != 200:
            raise OSError('update response unavailable')
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('update response too large')
    return data

def version_tuple(version):
    if not re.fullmatch('20\\d{2}\\.\\d{2}\\.\\d{2}\\.[1-9]\\d*', version):
        raise ValueError('invalid stable version')
    return tuple((int(part) for part in version.split('.')))

def release_source(fetch):
    release = json.loads(fetch(API + '/releases/latest'))
    if release.get('draft') is not False or release.get('prerelease') is not False:
        raise ValueError('stable release required')
    tag = release['tag_name']
    if not tag.startswith('v'):
        raise ValueError('version tag required')
    version_tuple(tag[1:])
    reference = json.loads(fetch(API + '/git/ref/tags/' + tag))['object']
    for attempt in range(4):
        if not re.fullmatch('[0-9a-f]{40}', reference.get('sha', '')):
            raise ValueError('invalid release commit')
        if reference['type'] == 'commit':
            break
        if reference['type'] != 'tag':
            raise ValueError('invalid release reference')
        reference = json.loads(fetch(API + '/git/tags/' + reference['sha']))['object']
    else:
        raise ValueError('release tag chain too long')
    commit = reference['sha']
    runs = json.loads(fetch(API + '/actions/workflows/verify.yml/runs?head_sha=' + commit + '&per_page=20'))['workflow_runs']
    matching = sorted((run for run in runs if run.get('head_sha') == commit and run.get('event') == 'push'), key=lambda run: run['id'], reverse=True)
    if not matching or matching[0].get('status') != 'completed' or matching[0].get('conclusion') != 'success':
        raise ValueError('release verification CI has not succeeded')
    return (tag[1:], commit)

def unpack(data, destination):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum((item.file_size for item in entries)) > MAX_BYTES * 2:
            raise ValueError('update archive too large')
        seen = set()
        roots = set()
        planned = []
        for item in entries:
            parts = PurePosixPath(item.filename).parts
            if not parts:
                raise ValueError('empty archive path')
            safe_path(destination, item.filename)
            roots.add(parts[0])
            normalized = '/'.join(parts).casefold()
            if normalized in seen or item.external_attr >> 16 & 61440 == 40960:
                raise ValueError('duplicate or linked archive entry')
            seen.add(normalized)
            if item.is_dir():
                continue
            if len(parts) < 2:
                raise ValueError('archive must contain one repository root')
            planned.append((item, safe_path(destination, '/'.join(parts[1:]))))
        if len(roots) != 1:
            raise ValueError('ambiguous archive root')
        for item, target in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))

def validate(root, candidate, version):
    manifest = read_json(candidate / 'DISTRIBUTION.json')
    protected = read_json(candidate / PRODUCT / 'PROTECTED_BUILD.json')
    policy = read_json(candidate / PRODUCT / 'AUTO_UPDATE.json')
    previous = read_json(root / 'PROTECTED_BUILD.json')
    current = (root / 'VERSION').read_text().strip()
    if manifest.get('product') != PRODUCT or manifest.get('version') != version or protected.get('product') != PRODUCT or (protected.get('version') != version) or (protected.get('containsOriginalCore') is not False) or (protected.get('coreVersion') != previous.get('coreVersion')) or (policy.get('protocol') != 1) or (policy.get('product') != PRODUCT) or (policy.get('repository') != REPOSITORY) or (policy.get('stateMigration') is not False) or (current not in policy.get('compatibleFrom', [])) or (version_tuple(version) <= version_tuple(current)):
        raise ValueError('automatic update compatibility not established')
    incoming = {}
    seen = set()
    for name, expected in manifest['files'].items():
        source = safe_path(candidate, name)
        if name.casefold() in seen or not re.fullmatch('[0-9a-f]{64}', expected) or digest(source) != expected:
            raise ValueError('distribution hash mismatch')
        seen.add(name.casefold())
        if name.startswith(PRODUCT + '/'):
            relative = name[len(PRODUCT) + 1:]
            safe_path(root, relative)
            if relative.startswith('.') or relative.split('/')[0] not in {'scripts', 'references', 'assets', 'SKILL.md', 'VERSION', 'requirements.txt', 'PROTECTED_BUILD.json', 'AUTO_UPDATE.json', 'agents'}:
                raise ValueError('runtime data cannot be updated')
            incoming[relative] = expected
        elif name.startswith('webcli-browser-runtime/'):
            if digest(safe_path(root.parent, name)) != expected:
                raise ValueError('shared browser runtime requires a settled compatibility review')
    required = {'VERSION', 'SKILL.md', 'requirements.txt', 'scripts/self_operated_cli.py', 'PROTECTED_BUILD.json', 'AUTO_UPDATE.json', 'scripts/protected-settings.json'}
    if not required <= set(incoming) or (candidate / PRODUCT / 'VERSION').read_text().strip() != version:
        raise ValueError('incomplete protected update')
    if protected['files'] != {name: value for name, value in incoming.items() if name != 'PROTECTED_BUILD.json'}:
        raise ValueError('protected manifest disagrees with distribution')
    if any(((root / name).exists() != (candidate / PRODUCT / name).exists() or digest(root / name) != digest(candidate / PRODUCT / name) for name in BOUNDARY)):
        raise ValueError('core, identity or dependencies require compatibility review')
    baseline = read_json(root / '.install-baseline.json')
    if not set(baseline) <= set(incoming):
        raise ValueError('automatic removal or migration not supported')
    return (incoming, baseline)

def replace_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.auto-incoming')
    with temporary.open('xb') as stream:
        stream.write(source.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)

def recover(root):
    path = home(root) / 'transaction.json'
    if not path.exists():
        return {'status': 'no-interrupted-update'}
    transaction = read_json(path)
    backup = safe_path(home(root), transaction['backup'])
    if transaction['root'] != str(root.resolve()):
        raise ValueError('interrupted update target changed')
    for name, record in transaction['files'].items():
        target = safe_path(root, name)
        if digest(target) not in (record['before'], record['after']):
            raise ValueError('update recovery found new local changes; preserve and inspect')
        if record['before'] is not None and digest(safe_path(backup, name)) != record['before']:
            raise ValueError('update backup hash mismatch')
        temporary = target.with_name(target.name + '.auto-incoming')
        if temporary.exists() and digest(temporary) != record['after']:
            raise ValueError('partial update staging retained for inspection')
    for name, record in transaction['files'].items():
        target = safe_path(root, name)
        temporary = target.with_name(target.name + '.auto-incoming')
        if temporary.exists():
            temporary.unlink()
        if record['before'] is None:
            if target.exists():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(safe_path(backup, name).read_bytes())
    save_json(backup / 'recovery.json', {'status': 'rolled-back', 'time': time.time()})
    path.unlink()
    return {'status': 'rolled-back'}

def smoke_check(root):
    environment = os.environ.copy()
    environment['JD_SELF_UPDATE_SMOKE'] = str(os.getpid())
    reply = subprocess.run([sys.executable, '-B', str(root / 'scripts/self_operated_cli.py'), 'provider-info'], env=environment, capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if reply.returncode != 0 or json.loads(reply.stdout).get('version') != (root / 'VERSION').read_text().strip():
        raise ValueError('installed update smoke check failed')

def apply(root, candidate, version, *, smoke=None):
    incoming, baseline = validate(root, candidate, version)
    conflicts = [name for name, value in incoming.items() if (root / name).exists() and digest(root / name) not in (value, baseline.get(name))]
    conflicts.extend((path.relative_to(root).as_posix() for path in (root / 'scripts').rglob('*') if path.is_file() and '__pycache__' not in path.parts and (path.suffix in ('.py', '.js', '.mjs', '.json')) and (path.relative_to(root).as_posix() not in incoming)))
    if conflicts:
        destination = home(root) / 'merge-candidates' / version
        for name in incoming:
            target = safe_path(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(safe_path(candidate / PRODUCT, name).read_bytes())
        return {'status': 'merge-required', 'version': version, 'conflicts': conflicts, 'candidate': str(destination), 'localChangesPreserved': True}
    backup = home(root) / 'backups' / uuid.uuid4().hex
    backup.mkdir(parents=True)
    files = {}
    staged_baseline = backup / 'new-baseline.json'
    save_json(staged_baseline, incoming)
    sources = {name: safe_path(candidate / PRODUCT, name) for name in incoming}
    sources['.install-baseline.json'] = staged_baseline
    for name, source in sources.items():
        target = safe_path(root, name)
        before, after = (digest(target), digest(source))
        if before == after:
            continue
        if target.with_name(target.name + '.auto-incoming').exists():
            raise ValueError('unfinished incoming file retained')
        files[name] = {'before': before, 'after': after}
        if before is not None:
            archived = safe_path(backup, name)
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(target.read_bytes())
    transaction = home(root) / 'transaction.json'
    if transaction.exists():
        raise ValueError('recover interrupted update first')
    save_json(transaction, {'root': str(root.resolve()), 'backup': backup.relative_to(home(root)).as_posix(), 'files': files})
    try:
        for name in files:
            if digest(safe_path(root, name)) != files[name]['before']:
                raise ValueError('local file changed after update planning')
            replace_file(sources[name], safe_path(root, name))
        if any((digest(safe_path(root, name)) != value for name, value in incoming.items())):
            raise ValueError('installed files changed during update')
        (smoke or smoke_check)(root)
    except _protected_core.ProtectedCoreError:
        raise
    except Exception:
        return recover(root)
    save_json(backup / 'result.json', {'status': 'updated', 'version': version, 'time': time.time()})
    transaction.unlink()
    return {'status': 'updated', 'version': version, 'backup': str(backup)}

def check(root, *, fetch=fetch_bytes, now=None, force=False):
    if not installed(root):
        return {'status': 'not-protected-install'}
    if (home(root) / 'transaction.json').exists():
        return recover(root)
    configuration = home(root) / 'config.json'
    if configuration.exists() and read_json(configuration).get('enabled') is False:
        return {'status': 'disabled'}
    timestamp = time.time() if now is None else now
    state = home(root) / 'check.json'
    previous = read_json(state) if state.exists() else {}
    if previous.get('status') in ('merge-required', 'review-required', 'rolled-back') and (not force):
        return previous
    if not force and 0 <= timestamp - previous.get('checkedAt', -INTERVAL) < INTERVAL:
        return {'status': 'recently-checked'}
    candidate = None
    try:
        version, commit = release_source(fetch)
        if version_tuple(version) <= version_tuple((root / 'VERSION').read_text().strip()):
            result = {'status': 'up-to-date'}
        else:
            payload = fetch('https://codeload.github.com/' + REPOSITORY + '/zip/' + commit)
            candidate = home(root) / 'downloads' / (version + '-' + commit)
            safe_path(home(root), candidate.relative_to(home(root)).as_posix())
            if not candidate.exists():
                candidate.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='download-', dir=candidate.parent) as temporary:
                    staging = Path(temporary) / 'verified-archive'
                    unpack(payload, staging)
                    if not staging.resolve().is_relative_to(candidate.parent.resolve()):
                        raise ValueError('download staging escaped update workspace')
                    staging.rename(candidate)
            result = apply(root, candidate, version)
    except (OSError, TimeoutError):
        result = {'status': 'update-unavailable', 'usingInstalledVersion': True}
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile):
        result = {'status': 'review-required', 'reason': 'release-integrity-or-compatibility', 'usingInstalledVersion': True}
        if candidate is not None and candidate.is_dir():
            result['candidate'] = str(candidate)
    result['checkedAt'] = timestamp
    save_json(state, result)
    return result

def bootstrap(entry, arguments):
    global _running_root
    root = entry.resolve().parents[1]
    if not installed(root) or _running_root == root or (arguments == ['provider-info'] and os.environ.get('JD_SELF_UPDATE_SMOKE') == str(os.getppid())):
        return
    business_started = False
    try:
        with session_lock(root):
            output_value = next((value.split('=', 1)[1] for value in arguments if value.startswith('--output-dir=')), None)
            if '--output-dir' in arguments and arguments.index('--output-dir') + 1 < len(arguments):
                output_value = arguments[arguments.index('--output-dir') + 1]
            if output_value:
                output = Path(output_value)
                if output.exists() and any(output.rglob('execution.lock')):
                    raise RuntimeError('existing task lock retained; no update started')
            offline = not arguments or arguments[0] == 'provider-info' or any((value in ('-h', '--help') for value in arguments))
            result = {'status': 'check-skipped'} if offline else check(root)
            if (home(root) / 'transaction.json').exists():
                raise RuntimeError('unfinished update requires local recovery')
            if result['status'] not in ('up-to-date', 'recently-checked', 'check-skipped', 'disabled'):
                print(json.dumps({'autoUpdate': result}, ensure_ascii=False), file=sys.stderr)
            if result['status'] in ('merge-required', 'review-required', 'rolled-back'):
                raise SystemExit(75)
            _running_root = root
            original_argv = sys.argv
            try:
                sys.argv = [str(entry), *arguments]
                business_started = True
                runpy.run_path(str(entry), run_name='__main__')
                raise SystemExit(0)
            finally:
                sys.argv = original_argv
                _running_root = None
    except _protected_core.ProtectedCoreError:
        raise
    except (RuntimeError, ValueError, OSError):
        if business_started:
            raise
        print('Self-operated startup held; inspect update status or active task locally. No business command started.', file=sys.stderr)
        raise SystemExit(75) from None

def main():
    parser = argparse.ArgumentParser(description='Protected self-operated startup update controls; no business writes.')
    parser.add_argument('action', choices=('status', 'check', 'enable', 'disable', 'recover'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not installed(root):
        print(json.dumps({'status': 'not-protected-install'}))
        return
    with session_lock(root):
        if args.action in ('enable', 'disable'):
            result = {'enabled': args.action == 'enable'}
            save_json(home(root) / 'config.json', result)
        elif args.action == 'check':
            result = check(root, force=True)
        elif args.action == 'recover':
            result = recover(root)
        else:
            path = home(root) / 'check.json'
            config = home(root) / 'config.json'
            result = {'version': (root / 'VERSION').read_text().strip(), 'enabled': not config.exists() or read_json(config).get('enabled') is not False, 'lastCheck': read_json(path) if path.exists() else None, 'interrupted': (home(root) / 'transaction.json').exists()}
        print(json.dumps(result, ensure_ascii=False))
if __name__ == '__main__':
    main()
