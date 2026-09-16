import protected_core as _protected_core
from collections import deque
from email.utils import parsedate_to_datetime
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import urlparse
import jd_material_agent as core
from image_benchmark_metrics import new_attempt_id
INITIAL_COOLDOWN_SECONDS = 60
SUBSEQUENT_COOLDOWN_SECONDS = 120
COOLDOWN_POLICY = 'server-or-60-120-v1'
TRANSPORT_RETRY_SECONDS = 5

def retry_after_seconds(value, now):
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            return None
    return delay if math.isfinite(delay) and delay >= 0 else None

class DispatchGate:

    def __init__(self, scheduler, start_gate):
        self.scheduler = scheduler
        self.start_gate = start_gate
        self.lock = threading.Lock()
        self.clock = time.monotonic
        self.wait_seconds = time.sleep
        self.last_start = float('-inf')
        self.last_key_starts = {}

    def wait(self):
        with self.lock:
            self.scheduler.ready()
            self.start_gate.wait()
            while True:
                self.scheduler.ready()
                now = self.clock()
                slot = self.scheduler.client.local.slot
                delay = max(self.last_start + 1.0 - now, self.last_key_starts.get(slot, float('-inf')) + 2.0 - now)
                if delay <= 0:
                    self.last_start = now
                    self.last_key_starts[slot] = now
                    self.scheduler.started()
                    return
                self.wait_seconds(min(delay, 1.0))

class ImageSchedule:

    def __init__(self, client, output, clock, wait, paused):
        self.client, self.clock, self.wait, self.paused = (client, clock, wait, paused)
        self.root = Path(output) / '.state/dual-key-generation'
        self.path = self.root / 'cooldown.json'
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.condition = threading.Condition()
        self.available = deque((0, 1, 0, 1))
        self.recovery_owner = None
        self.attribute_legacy_state()

    def attribute_legacy_state(self):
        if not self.state or 'blockedKeySlots' in self.state:
            return
        events = [json.loads(path.read_text(encoding='utf-8')) for path in (self.root / 'attempts').glob('*.json')]
        matches = [event for event in events if event.get('httpStatus') == 429 and event.get('providerEvidence') == self.state.get('lastEvidence')]
        if not matches:
            raise ValueError('legacy cooldown requires original attributed response evidence')
        last_failure = max((event['endedAt'] for event in matches))
        blocked = {event['keySlot'] for event in events if event.get('httpStatus') == 429 and self.state['firstBlockedAt'] <= event.get('endedAt', 0) <= last_failure}
        if not blocked:
            raise ValueError('legacy cooldown credential attribution unavailable')
        proofs = {}
        for slot in blocked:
            successful = [event for event in events if event['keySlot'] == slot and event['status'] == 'valid-image' and (self.state['nextStartAt'] <= event['startedAt'] < self.state['deadline'])]
            if successful:
                proofs[str(slot)] = min(successful, key=lambda event: event['startedAt'])['attemptId']
        original = self.path.read_bytes()
        archive = self.root / 'migrations' / (new_attempt_id() + '-before.json')
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(original)
        remaining = sorted(blocked - {int(slot) for slot in proofs})
        status = self.state['status'] if self.state['status'] == 'exhausted' else 'waiting' if remaining else 'resolved'
        self.state.update(blockedKeySlots=remaining, recoveryProofs=proofs, status=status, legacyMigration={'path': str(archive), 'sha256': hashlib.sha256(original).hexdigest()}, resolutionProof='each_blocked_credential_requires_its_own_valid_image')
        for name in ('resolvedAt', 'attemptId', 'proof'):
            self.state.pop(name, None)
        if status == 'resolved':
            final = max((event for event in events if event['attemptId'] in proofs.values()), key=lambda event: event['endedAt'])
            self.state.update(resolvedAt=final['endedAt'], attemptId=final['attemptId'])
        self.save()

    def check(self):
        if self.paused() and self.client.cancel_event is not None:
            self.client.cancel_event.set()
        if self.client.cancel_event is not None and self.client.cancel_event.is_set():
            raise RuntimeError('generation cancelled before dispatch; partial cache preserved')
        if self.client.quota_exhausted:
            raise core.ModelQuotaExceeded()
        if self.client.authentication_failed:
            raise RuntimeError('model authentication failed; further dispatch stopped')
        if self.client.image_resource_blocked or self.state.get('status') == 'exhausted':
            self.client.image_resource_blocked = True
            raise core.ImageModelResourceBlocked(self.client.image_resource_failure)

    def acquire(self):
        with self.condition:
            while not self.available:
                self.check()
                self.condition.wait(0.2)
            self.check()
            return self.available.popleft()

    def release(self, slot, event):
        with self.condition:
            self.available.append(slot)
            if self.recovery_owner == threading.get_ident():
                if self.state.get('status') == 'waiting' and event['status'] == 'failed' and (event.get('httpStatus') != 429):
                    now = self.clock()
                    self.state.update(nextStartAt=max(self.state['nextStartAt'], now + SUBSEQUENT_COOLDOWN_SECONDS), cooldownPolicy=COOLDOWN_POLICY, cooldownDelaySource='recovery-failure', cooldownDelaySeconds=SUBSEQUENT_COOLDOWN_SECONDS, cooldownUpdatedAt=now, recoveryFailureAttemptId=event['attemptId'])
                    self.save()
                self.recovery_owner = None
            self.condition.notify_all()

    def save(self):
        core._save_state(self.path, self.state)

    def ready(self):
        while True:
            with self.condition:
                self.check()
                if self.state.get('status') != 'waiting':
                    return
                now = self.clock()
                if now >= self.state['deadline']:
                    self.state.update(status='exhausted', stoppedAt=now)
                    self.save()
                    self.check()
                delay = min(self.state['nextStartAt'], self.state['deadline']) - now
                if delay <= 0:
                    if self.recovery_owner in (None, threading.get_ident()):
                        self.recovery_owner = threading.get_ident()
                        return
                    self.condition.wait(0.2)
                    continue
            self.wait(min(1.0, delay))

    def started(self):
        event = self.client.local.event
        event.update(startedAt=self.clock(), status='dispatched')
        core._save_state(self.root / 'attempts' / (event['attemptId'] + '.json'), event)

    def throttle(self, response, evidence):
        with self.condition:
            now = self.clock()
            first = self.state.get('status') != 'waiting'
            if first:
                self.state = {'firstBlockedAt': now, 'deadline': now + 1800, 'throttles': 0, 'blockedKeySlots': [], 'recoveryProofs': {}}
            slot = self.client.local.slot + 1
            self.state['blockedKeySlots'] = sorted(set(self.state['blockedKeySlots']) | {slot})
            self.state['recoveryProofs'].pop(str(slot), None)
            server_delay = retry_after_seconds(response.headers.get('Retry-After', ''), now)
            delay = server_delay if server_delay is not None else INITIAL_COOLDOWN_SECONDS if first else SUBSEQUENT_COOLDOWN_SECONDS
            source = 'retry-after' if server_delay is not None else 'default-initial' if first else 'default-subsequent'
            self.state.update(status='waiting', lastBlockedAt=now, nextStartAt=max(self.state.get('nextStartAt', 0), now + delay), cooldownPolicy=COOLDOWN_POLICY, cooldownDelaySource=source, cooldownDelaySeconds=delay, cooldownUpdatedAt=now, throttles=self.state['throttles'] + 1, lastEvidence=evidence)
            self.save()

    def valid(self, event):
        with self.condition:
            if self.state.get('status') == 'waiting' and event['keySlot'] in self.state['blockedKeySlots'] and (event['startedAt'] >= self.state['nextStartAt']):
                self.state['blockedKeySlots'].remove(event['keySlot'])
                self.state['recoveryProofs'][str(event['keySlot'])] = event['attemptId']
                if not self.state['blockedKeySlots']:
                    self.state.update(status='resolved', resolvedAt=self.clock(), proof='all_blocked_keys_produced_valid_images_after_global_cooldown', attemptId=event['attemptId'])
                self.save()
                if self.state['status'] == 'resolved':
                    core._save_state(self.root / 'episodes' / (event['attemptId'] + '.json'), self.state)

class DualKeyModelClient(core.ModelClient):

    @property
    def _api_key(self):
        if hasattr(self, 'local'):
            return self.keys[getattr(self.local, 'slot', 0)]
        return self._primary_key

    @_api_key.setter
    def _api_key(self, value):
        self._primary_key = value

    def __init__(self, primary, secondary, output, *, timeout=600, image_concurrency=4, clock=time.time, wait=time.sleep, paused=None):
        if image_concurrency != 4:
            raise ValueError('dual-key mode requires total image concurrency four')
        if not secondary or secondary == primary or (not secondary.isascii()) or any((character.isspace() for character in secondary)):
            raise ValueError('two distinct authorized runtime credentials required')
        super().__init__(primary, timeout=timeout, image_concurrency=4)
        self.keys = (primary, secondary)
        self.local = threading.local()
        self.no_generation_retries = True
        self.scheduler = ImageSchedule(self, output, clock, wait, paused or (lambda: False))
        self.image_gate = DispatchGate(self.scheduler, self.image_gate)

    def clean(self, value):
        for credential in self.keys:
            value = value.replace(credential, '[REDACTED]')
        return value

    def observe_image_response(self, response):
        event = self.local.event
        event['httpStatus'] = response.status_code
        if response.status_code < 400:
            return
        evidence = core._model_resource_failure_evidence(response, self.keys[self.local.slot])
        evidence = json.loads(self.clean(json.dumps(evidence, ensure_ascii=False)))
        event['providerEvidence'] = evidence
        try:
            details = response.json().get('error', {})
        except (ValueError, AttributeError):
            details = {}
        quota = isinstance(details, dict) and str(details.get('code')) == '2007'
        if response.status_code == 429 and (not quota):
            self.scheduler.throttle(response, evidence)
            raise RuntimeError('image throttled; failed task skipped, both keys cooling: ' + json.dumps(evidence, ensure_ascii=False))

    def _request(self, method, url, *, max_attempts=4, **kwargs):
        image_request = urlparse(url).path.endswith('/images/edits')
        slot = getattr(self.local, 'slot', 0) if image_request else 0
        headers = dict(kwargs.pop('headers', {}) or {})
        headers['Authorization'] = 'Bearer ' + self.keys[slot]
        try:
            for attempt in range(2 if image_request else 1):
                try:
                    return super()._request(method, url, max_attempts=1, headers=headers, **kwargs)
                except core.ModelTransientError as error:
                    cause = error.__cause__
                    if not image_request or not isinstance(cause, (core.httpx.RemoteProtocolError, core.httpx.ReadError)):
                        raise
                    self.local.event['transportErrorType'] = type(cause).__name__
                    if attempt:
                        raise
                    self.reserve_transport_retry(cause)
        except _protected_core.ProtectedCoreError:
            raise
        except (core.ModelQuotaExceeded, core.ImageModelResourceBlocked):
            raise
        except Exception as error:
            raise RuntimeError(self.clean(str(error))) from None

    def reserve_transport_retry(self, error):
        event = self.local.event
        now = self.scheduler.clock()
        retry = {'attemptId': new_attempt_id(), 'requestHash': event['requestHash'], 'keySlot': event['keySlot'], 'sourcePath': event['sourcePath'], 'status': 'queued', 'queuedAt': now, 'retryOf': event['attemptId'], 'retryNumber': 1, 'recoveryStartedAt': now, 'retryDelaySeconds': TRANSPORT_RETRY_SECONDS}
        marker = self.scheduler.root / 'transport-retries' / (event['requestHash'] + '.json')
        core._save_state(marker, {'status': 'reserved', 'requestHash': event['requestHash'], 'originalAttemptId': event['attemptId'], 'retryAttemptId': retry['attemptId'], 'keySlot': event['keySlot'], 'reservedAt': now})
        event.update(status='failed', errorType=type(error).__name__, error=self.clean(str(error)), endedAt=now, elapsedSeconds=round(now - event['queuedAt'], 6), retryAttemptId=retry['attemptId'])
        core._save_state(self.scheduler.root / 'attempts' / (event['attemptId'] + '.json'), event)
        self.local.event = retry
        core._save_state(self.scheduler.root / 'attempts' / (retry['attemptId'] + '.json'), retry)
        for remaining in range(TRANSPORT_RETRY_SECONDS):
            self.scheduler.check()
            self.scheduler.wait(1.0)
        self.scheduler.check()

    def edit_image(self, prompt, source_path):
        source_path = Path(source_path)
        signature = core._auto_maintain_plan_hash({'prompt': prompt, 'model': core.PROVIDER.image_model, 'sourceSha256': hashlib.sha256(source_path.read_bytes()).hexdigest(), 'size': '1024x1024'})
        failure = self.scheduler.root / 'failures' / (signature + '.json')
        if failure.exists():
            raise RuntimeError('image request previously failed; no retry or alternate key')
        retry_marker = self.scheduler.root / 'transport-retries' / (signature + '.json')
        if retry_marker.exists():
            raise RuntimeError('image transport retry already reserved; reuse cache or reconcile evidence, no replay')
        slot = self.scheduler.acquire()
        self.local.slot = slot
        event = {'attemptId': new_attempt_id(), 'requestHash': signature, 'keySlot': slot + 1, 'status': 'queued', 'sourcePath': str(source_path), 'queuedAt': self.scheduler.clock()}
        self.local.event = event
        started = time.monotonic()
        try:
            image = super().edit_image(prompt, source_path)
            with core.Image.open(BytesIO(image)) as decoded:
                decoded.verify()
            event = self.local.event
            event.update(status='valid-image', imageSha256=hashlib.sha256(image).hexdigest())
            self.scheduler.valid(event)
            return image
        except _protected_core.ProtectedCoreError:
            raise
        except Exception as error:
            event = self.local.event
            event.update(status='failed' if 'startedAt' in event else 'not-dispatched', errorType=event.get('transportErrorType', type(error).__name__), error=self.clean(str(error)))
            if 'startedAt' in event:
                core._save_state(failure, event)
            raise
        finally:
            event = self.local.event
            event.update(endedAt=self.scheduler.clock(), elapsedSeconds=round(time.monotonic() - started, 6))
            if event.get('retryOf'):
                event['recoveryElapsedSeconds'] = round(event['endedAt'] - event['recoveryStartedAt'], 6)
                event['elapsedSeconds'] = round(event['endedAt'] - event['queuedAt'], 6)
                core._save_state(retry_marker, {'status': event['status'], 'requestHash': signature, 'originalAttemptId': event['retryOf'], 'retryAttemptId': event['attemptId'], 'keySlot': event['keySlot'], 'recoveryElapsedSeconds': event['recoveryElapsedSeconds']})
            core._save_state(self.scheduler.root / 'attempts' / (event['attemptId'] + '.json'), event)
            del self.local.slot
            del self.local.event
            self.scheduler.release(slot, event)
