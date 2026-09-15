import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
PRODUCT = 'jd-material-self-operated'
EXTRAS = {'README.md', '.gitignore', '.gitattributes', '.github/workflows/verify.yml',
          'tools/verify_public_distribution.py', 'DISTRIBUTION.json'}
PATTERNS = {
    'credential-token': re.compile(r'(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'local-machine-path': re.compile(r'(?i)\b[a-z]:[\\/]|/(?:Users|home)/[^ <>"\n]+'),
    'credential-literal': re.compile(r'''(?i)(?:api[_-]?key|password|client[_-]?secret)\s*[:=]\s*["']([^\n"']{16,})["']'''),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan(text, name):
    for label, pattern in PATTERNS.items():
        if pattern.search(text):
            raise ValueError(f'{name}: potential {label}; inspect privately before publication')


def verify():
    distribution = json.loads((ROOT / 'DISTRIBUTION.json').read_text(encoding='utf-8'))
    assert distribution['product'] == PRODUCT
    allowed = set(distribution['files']) | EXTRAS
    count = 0
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if '.git' in relative.parts or '__pycache__' in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError('symlink is not a public distribution input')
        if not path.is_file():
            continue
        name = relative.as_posix()
        if name not in allowed:
            raise ValueError(f'unlisted public file: {name}')
        count += 1
        if path.suffix == '.xlsx':
            with ZipFile(path) as archive:
                for member in archive.namelist():
                    if member.endswith(('.xml', '.rels')):
                        scan(archive.read(member).decode('utf-8'), name + ':' + member)
        else:
            scan(path.read_text(encoding='utf-8-sig'), name)
    for name, expected in distribution['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe manifest path')
        assert digest(ROOT / relative) == expected, name
    manifest = json.loads((ROOT / PRODUCT / 'PROTECTED_BUILD.json').read_text(encoding='utf-8'))
    assert manifest['product'] == PRODUCT and not manifest['containsOriginalCore']
    contract = ast.parse((ROOT / PRODUCT / 'scripts/core_contract.py').read_text(encoding='utf-8'))
    common = next(node.value for node in contract.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'COMMON_FUNCTIONS' for target in node.targets))
    functions = next(node.value for node in contract.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == 'FUNCTIONS' for target in node.targets))
    names = list(ast.literal_eval(common))
    selected = next(value for key, value in zip(functions.keys, functions.values) if ast.literal_eval(key) == PRODUCT)
    names.extend(ast.literal_eval(value) for value in selected.elts if not isinstance(value, ast.Starred))
    assert set(manifest['remoteFunctions']) == set(names) and len(names) == 8
    for name, expected in manifest['files'].items():
        assert digest(ROOT / PRODUCT / name) == expected, name
    for function in names:
        module, name = function.split('.')
        tree = ast.parse((ROOT / PRODUCT / 'scripts' / (module + '.py')).read_text(encoding='utf-8'))
        implementation = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        expected = f'return _protected_core.call({function!r}, locals())'
        assert len(implementation.body) == 1 and ast.unparse(implementation.body[0]) == expected, function
    settings = json.loads((ROOT / PRODUCT / 'scripts/protected-settings.json').read_text(encoding='utf-8'))
    assert settings['product'] == PRODUCT and settings['coreVersion'] == manifest['coreVersion']
    with tempfile.TemporaryDirectory(prefix='protected-dist-verify-') as temporary:
        destination = Path(temporary) / 'skills'
        subprocess.run([sys.executable, '-B', str(ROOT / 'tools/install.py'), '--skills-dir', str(destination)], check=True)
        scripts = destination / PRODUCT / 'scripts'
        reply = subprocess.run([sys.executable, '-B', str(scripts / 'self_operated_cli.py'), 'provider-info'],
            check=True, capture_output=True, text=True, encoding='utf-8')
        assert json.loads(reply.stdout)['version'] == distribution['version']
        help_reply = subprocess.run([sys.executable, '-B', str(scripts / 'self_operated_cli.py'), 'maintain-self-operated', '--help'],
            check=True, capture_output=True, text=True, encoding='utf-8')
        assert '--plan-only' in help_reply.stdout and '--confirm' in help_reply.stdout
        probe = "import sys;sys.path.insert(0,sys.argv[1]);import protected_core;import jd_material_agent as core;protected_core.exchange=lambda request:{'ok':True,'authorized':True};\ntry: core.image_prompt('white','fixture')\nexcept protected_core.ProtectedCoreError: print('forged-authorization-rejected')\nelse: raise SystemExit('forged authorization accepted')"
        denied = subprocess.run([sys.executable, '-I', '-B', '-c', probe, str(scripts)], check=True,
            capture_output=True, text=True, encoding='utf-8')
        assert 'forged-authorization-rejected' in denied.stdout
    print(json.dumps({'status': 'passed', 'publicFiles': count, 'privateFunctionsReplaced': len(names),
        'version': distribution['version'], 'isolatedInstall': 'passed', 'credentialPatterns': 'no-match',
        'modelCalls': 0, 'productWrites': 0}))


if __name__ == '__main__':
    verify()
