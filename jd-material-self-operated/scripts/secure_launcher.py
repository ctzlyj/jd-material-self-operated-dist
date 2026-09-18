import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import secure_credentials
SKILL_ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = Path(__file__).with_name('self_operated_cli.py')
REQUIREMENTS_PATH = SKILL_ROOT / 'requirements.txt'
REQUIRED_MODULES = ('httpx', 'openpyxl', 'PIL', 'PyInstaller')

def ensure_dependencies():
    required = REQUIRED_MODULES + (('keyring',) if os.name != 'nt' else ())
    if any((importlib.util.find_spec(name) is None for name in required)):
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(REQUIREMENTS_PATH)], check=True)
    if any((importlib.util.find_spec(name) is None for name in required)):
        raise RuntimeError('required dependencies unavailable after installation')

def prompt_api_key():
    return secure_credentials.prompt_key('JD_LLM_API_KEY')

def run_agent(agent_args, *, prompt=None, dependency_installer=ensure_dependencies, runner=subprocess.run, remember=True):
    if not agent_args:
        raise ValueError('provide a self_operated_cli.py subcommand')
    dependency_installer()
    environment = os.environ.copy()
    callback = (lambda name, saved: prompt()) if prompt is not None else None
    secure_credentials.prepare_command(agent_args, environ=environment, prompt=callback, remember=remember)
    result = runner([sys.executable, str(AGENT_PATH), *agent_args], env=environment, check=False)
    return int(result.returncode)

def main(argv=None):
    parser = argparse.ArgumentParser(description='Use existing credentials or configure an OS-protected credential once.')
    controls = parser.add_mutually_exclusive_group()
    controls.add_argument('--credential-status', action='store_true')
    controls.add_argument('--configure-credentials', action='store_true')
    controls.add_argument('--forget-credentials', action='store_true')
    parser.add_argument('--key-slot', type=int, choices=(1, 2), default=1)
    parser.add_argument('--dual-key-images', action='store_true')
    parser.add_argument('--session-only', action='store_true')
    parser.add_argument('agent_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.credential_status:
        print(json.dumps(secure_credentials.credential_status(), ensure_ascii=False))
        return 0
    if args.forget_credentials:
        secure_credentials.default_store().delete(secure_credentials.NAMES[args.key_slot - 1])
        print('Encrypted stored slot removed. Existing process/user environment is unchanged.')
        return 0
    if args.configure_credentials:
        secure_credentials.ensure_environment(dual=args.dual_key_images, remember=not args.session_only)
        print('Credentials available. No model or product request performed.')
        return 0
    arguments = args.agent_args[1:] if args.agent_args[:1] == ['--'] else args.agent_args
    return run_agent(arguments, remember=not args.session_only)
if __name__ == '__main__':
    raise SystemExit(main())
