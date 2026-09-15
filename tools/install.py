import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(root, relative):
    value = Path(relative)
    if value.is_absolute() or '..' in value.parts:
        raise ValueError('unsafe installation path')
    target = root / value
    if root.resolve() not in target.resolve().parents or any(item.is_symlink() for item in (target, *target.parents)):
        raise ValueError('unsafe installation path')
    return target


def install(source, destination):
    manifest = json.loads((source / 'DISTRIBUTION.json').read_text(encoding='utf-8'))
    product = manifest['product']
    if product not in {'jd-material-self-operated', 'jd-material-pop'}:
        raise ValueError('unknown product')
    folders = [product] + (['webcli-browser-runtime'] if product == 'jd-material-self-operated' else [])
    for relative, expected in manifest['files'].items():
        if digest(checked(source, relative)) != expected:
            raise ValueError('distribution hash mismatch')
    plans = []
    for folder in folders:
        target = checked(destination, folder)
        if folder == product and target.exists() and any(target.iterdir()) and not (target / 'PROTECTED_BUILD.json').is_file():
            raise ValueError('unprotected installation retained; use a separate clean profile instead of overwriting the private Skill')
        incoming = {name[len(folder) + 1:]: value for name, value in manifest['files'].items() if name.startswith(folder + '/')}
        baseline_path = checked(target, '.install-baseline.json')
        baseline = json.loads(baseline_path.read_text(encoding='utf-8')) if baseline_path.exists() else {}
        conflicts = []
        for name, value in incoming.items():
            existing = checked(target, name)
            if existing.exists() and digest(existing) not in {value, baseline.get(name)}:
                conflicts.append(name)
        if conflicts:
            for name in conflicts:
                candidate = checked(destination, str(Path('.merge-candidates') / folder / incoming[name] / name))
                candidate.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(checked(source, str(Path(folder) / name)), candidate)
            raise ValueError('local changes preserved; candidates staged for three-way merge')
        plans.append((folder, target, incoming, baseline_path))
    for folder, target, incoming, baseline_path in plans:
        for name in incoming:
            output = checked(target, name)
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = checked(target, name + '.incoming')
            if temporary.exists():
                raise ValueError('unfinished installation retained; inspect incoming file before retry')
            shutil.copyfile(checked(source, str(Path(folder) / name)), temporary)
            temporary.replace(output)
        baseline_path.write_text(json.dumps(incoming, indent=2) + '\n', encoding='utf-8')
    return {'product': product, 'installed': folders, 'localOnlyFilesPreserved': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--skills-dir', type=Path, default=Path.home() / '.codex' / 'skills')
    arguments = parser.parse_args()
    print(json.dumps(install(Path(__file__).resolve().parents[1], arguments.skills_dir.resolve())))
