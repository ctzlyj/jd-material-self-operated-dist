import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from time import monotonic
import uuid

from core_contract import FUNCTIONS, TYPE_NAMES, decode, encode


SETTINGS = json.loads((Path(__file__).resolve().parent / 'protected-settings.json').read_text(encoding='utf-8'))
_terminal_error = None
_core_slots = threading.BoundedSemaphore(2)
_start_lock = threading.Lock()
_next_start = 0.0
_pace_wait = threading.Event().wait


class ProtectedCoreError(RuntimeError):
    pass


def exchange(request):
    executable = shutil.which('node')
    if not executable:
        raise ProtectedCoreError('AUTH_RUNTIME_UNAVAILABLE')
    environment = {key: value for key, value in os.environ.items() if not re.search(r'(?:KEY|TOKEN|SECRET|PASSWORD)', key, re.I)}
    encoded = json.dumps(request, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(encoded) > 8 * 1024 * 1024:
        raise ProtectedCoreError('CORE_REQUEST_TOO_LARGE')
    try:
        result = subprocess.run([executable, str(Path(__file__).with_name('identity-request.mjs'))], input=encoded,
                                capture_output=True, timeout=75, check=False, env=environment,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProtectedCoreError('CORE_RESULT_UNKNOWN') from error
    try:
        reply = json.loads(result.stdout)
    except (ValueError, UnicodeError) as error:
        raise ProtectedCoreError('CORE_RESULT_UNKNOWN') from error
    if result.returncode or not isinstance(reply, dict) or reply.get('ok') is not True:
        code = reply.get('code') if isinstance(reply, dict) else None
        raise ProtectedCoreError(code if isinstance(code, str) and re.fullmatch('[A-Z_]{1,64}', code) else 'CORE_RESULT_UNKNOWN')
    return reply


def call(function, arguments):
    global _terminal_error, _next_start
    with _core_slots:
        with _start_lock:
            if _terminal_error is not None:
                raise ProtectedCoreError(_terminal_error)
            _pace_wait(max(0, _next_start - monotonic()))
            _next_start = monotonic() + 0.55
        if _terminal_error is not None:
            raise ProtectedCoreError(_terminal_error)
        try:
            return _call(function, arguments)
        except ProtectedCoreError as error:
            _terminal_error = str(error)
            raise


def _call(function, arguments):
    product = SETTINGS['product']
    if function not in FUNCTIONS[product]:
        raise ProtectedCoreError('CORE_FUNCTION_NOT_ALLOWED')
    request = {'version': 1, 'product': product, 'operation': 'core-call', 'requestId': str(uuid.uuid4()),
               'payload': {'function': function, 'arguments': encode(arguments)}}
    if SETTINGS.get('requestCoreVersion') is True:
        request['coreVersion'] = SETTINGS['coreVersion']
    reply = exchange(request)
    if not isinstance(reply, dict):
        raise ProtectedCoreError('CORE_RESPONSE_INVALID')
    result = reply.get('result')
    if (reply.get('ok') is not True or reply.get('version') != 1 or reply.get('product') != product
            or reply.get('requestId') != request['requestId'] or not re.fullmatch('[a-f0-9]{64}', str(reply.get('requestHash', '')))
            or not isinstance(result, dict) or result.get('product') != product or result.get('function') != function
            or result.get('coreVersion') != SETTINGS['coreVersion']):
        raise ProtectedCoreError('CORE_RESPONSE_INVALID')
    if 'error' in result:
        error = result['error']
        if not isinstance(error, dict) or error.get('type') != 'ValueError' or not isinstance(error.get('message'), str):
            raise ProtectedCoreError('CORE_RESPONSE_INVALID')
        raise ValueError(error['message'])
    if 'value' not in result:
        raise ProtectedCoreError('CORE_RESPONSE_INVALID')
    core = importlib.import_module('jd_material_agent')
    registry = {name: getattr(core, name) for name in TYPE_NAMES if hasattr(core, name)}
    try:
        return decode(result['value'], registry)
    except (ValueError, TypeError, KeyError) as error:
        raise ProtectedCoreError('CORE_RESPONSE_INVALID') from error
