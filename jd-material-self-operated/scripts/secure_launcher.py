import protected_core as _protected_core
import argparse
import getpass
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence
SKILL_ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = Path(__file__).with_name('jd_material_agent.py')
REQUIREMENTS_PATH = SKILL_ROOT / 'requirements.txt'
REQUIRED_MODULES = ('httpx', 'openpyxl', 'PIL', 'PyInstaller')

def ensure_dependencies() -> None:
    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if not missing:
        return
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(REQUIREMENTS_PATH)], check=True)
    remaining = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if remaining:
        raise RuntimeError(f"依赖安装后仍不可用：{', '.join(remaining)}")

def prompt_api_key() -> str:
    value = None
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        value = simpledialog.askstring('京东内部素材 Skill', '请粘贴本次运行使用的 API Key。Key 不会写入磁盘或命令行。', show='*', parent=root)
        root.destroy()
    except _protected_core.ProtectedCoreError:
        raise
    except Exception:
        value = getpass.getpass('请粘贴本次运行使用的 API Key（输入不可见）：')
    key = (value or '').strip()
    if not key:
        raise ValueError('未输入 API Key，已停止任务。')
    return key

def run_agent(agent_args: Sequence[str], *, prompt: Callable[[], str]=prompt_api_key, dependency_installer: Callable[[], None]=ensure_dependencies, runner: Callable[..., object]=subprocess.run) -> int:
    if not agent_args:
        raise ValueError('请提供 jd_material_agent.py 子命令。')
    dependency_installer()
    saved_write = False
    if agent_args[0] == 'auto-maintain' and '--business-mode' in agent_args and ('--output-dir' in agent_args):
        mode_index = agent_args.index('--business-mode') + 1
        output_index = agent_args.index('--output-dir') + 1
        if mode_index < len(agent_args) and output_index < len(agent_args) and (agent_args[mode_index] == 'self-operated'):
            saved_write = (Path(agent_args[output_index]) / '.state' / 'self-operated-writes.json').is_file()
    if agent_args[0] in {'plan-self-operated', 'discover-self-operated'} or '--write-confirm-token' in agent_args or saved_write:
        result = runner([sys.executable, str(AGENT_PATH), *agent_args], check=False)
        return int(result.returncode)
    key = os.environ.get('JD_LLM_API_KEY', '').strip() or prompt().strip()
    if not key:
        raise ValueError('未输入 API Key，已停止任务。')
    child_environment = os.environ.copy()
    child_environment['JD_LLM_API_KEY'] = key
    result = runner([sys.executable, str(AGENT_PATH), *agent_args], env=child_environment, check=False)
    return int(result.returncode)

def main(argv: Sequence[str] | None=None) -> int:
    parser = argparse.ArgumentParser(description='自动补齐依赖，并通过本地隐藏输入为单次素材任务提供 API Key。')
    parser.add_argument('agent_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    agent_args = list(args.agent_args)
    if agent_args[:1] == ['--']:
        agent_args = agent_args[1:]
    return run_agent(agent_args)
if __name__ == '__main__':
    raise SystemExit(main())
