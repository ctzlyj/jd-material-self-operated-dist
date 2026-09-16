import protected_core as _protected_core
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import threading
import time
import jd_material_agent as core

class ImageResourceRecovery:

    def __init__(self, client, output, *, clock=time.time, wait=None, paused=None, window_seconds=300):
        if window_seconds not in (300, 1800):
            raise ValueError('resource cooldown window must be 300 or explicitly authorized 1800 seconds')
        self.client = client
        self.root = Path(output) / '.state/image-resource-recovery'
        self.path = self.root / 'current.json'
        self.clock = clock
        self.wait = wait or time.sleep
        self.paused = paused or (lambda: False)
        self.lock = threading.Lock()
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.window_seconds = window_seconds
        if self.state and self.state.get('status') != 'resolved' and (window_seconds == 1800):
            deadline = self.state['firstBlockedAt'] + window_seconds
            if deadline > self.state['deadline'] and self.clock() < deadline:
                original = self.path.read_bytes()
                archive = self.root / 'window-authorizations' / f'{time.time_ns()}-previous.json'
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_bytes(original)
                self.state.update(deadline=deadline, status='waiting', windowSeconds=window_seconds, nextProbeAt=max(self.clock() + 300, self.state.get('lastProbeAt', self.state['firstBlockedAt']) + 600), windowExtension={'authorizedAt': self.clock(), 'windowSeconds': window_seconds, 'previous': {'path': str(archive), 'sha256': hashlib.sha256(original).hexdigest()}})
                self.save()
        self.pending = None
        self.probing = False
        self.probe_thread = None
        self.last_response_evidence = None
        self.resume_required = self.state.get('status') in ('waiting', 'probing', 'recovered')

    def signature(self, method, url, kwargs):
        return core._auto_maintain_plan_hash({'method': method, 'url': url, 'json': kwargs.get('json')})

    def save(self):
        core._save_state(self.path, self.state)

    def retry_delay(self):
        return 600 if self.state.get('windowSeconds', self.window_seconds) == 1800 else 120

    def resolve(self, proof):
        self.state.update(status='resolved', resolvedAt=self.clock(), resolutionProof=proof)
        self.save()
        core._save_state(self.root / 'episodes' / f'{time.time_ns()}.json', self.state)

    def cancelled(self):
        event = self.client.cancel_event
        if self.paused():
            if event is not None:
                event.set()
            return True
        return event is not None and event.is_set()

    def before_request(self, method, url, kwargs):
        if self.cancelled():
            raise RuntimeError('resource cooldown cancelled; cached progress preserved')
        signature = self.signature(method, url, kwargs)
        cached = self.root / 'images' / f'{signature}.json'
        if cached.exists():
            item = json.loads(cached.read_text(encoding='utf-8'))
            if 'rejectedEvidence' in item:
                raise RuntimeError('image request rejected: ' + json.dumps(item['rejectedEvidence'], ensure_ascii=False))
            image = cached.with_suffix('.png').read_bytes()
            if hashlib.sha256(image).hexdigest() != item['imageSha256']:
                raise ValueError('recovered image cache SHA mismatch')
            return core.httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(image).decode('ascii')}]})
        if self.state.get('status') == 'exhausted':
            raise core.ImageModelResourceBlocked(self.state.get('lastEvidence'))
        if self.probing and threading.get_ident() != self.probe_thread:
            raise core.ImageModelResourceBlocked(self.state.get('lastEvidence'))
        if self.resume_required and (not self.probing):
            with self.lock:
                if signature == self.state.get('requestHash'):
                    self.pending = (method, url, deepcopy(kwargs))
            raise core.ImageModelResourceBlocked(self.state.get('lastEvidence'))
        return None

    def record_failure(self, method, url, kwargs, evidence):
        with self.lock:
            observed = self.clock()
            signature = self.signature(method, url, kwargs)
            if not self.state or self.state.get('status') == 'resolved':
                self.state = {'firstBlockedAt': observed, 'deadline': observed + self.window_seconds, 'windowSeconds': self.window_seconds, 'probeAttempts': 0, 'nextProbeAt': observed + (300 if self.window_seconds == 1800 else 60)}
            if self.pending is None:
                self.pending = (method, url, deepcopy(kwargs))
                self.state['requestHash'] = signature
            self.state.update(status='waiting', lastEvidence=evidence)
            core._save_state(self.root / 'events' / f'{time.time_ns()}.json', {'observedAt': observed, 'requestHash': signature, 'evidence': evidence})
            self.save()

    def cooldown(self):
        target = min(self.state['deadline'], self.state['nextProbeAt'])
        while self.clock() < target:
            if self.cancelled():
                raise RuntimeError('resource cooldown cancelled; cached progress preserved')
            self.wait(min(1, target - self.clock()))
        if self.cancelled():
            raise RuntimeError('resource cooldown cancelled; cached progress preserved')
        if self.clock() >= self.state['deadline']:
            self.state.update(status='exhausted', stoppedAt=self.clock())
            self.save()
            raise core.ImageModelResourceBlocked(self.state.get('lastEvidence'))

    def probe(self):
        self.cooldown()
        if self.pending is None:
            raise RuntimeError('original blocked image request unavailable; do not substitute another probe')
        method, url, kwargs = self.pending
        self.state.update(status='probing', probeAttempts=self.state['probeAttempts'] + 1, lastProbeAt=self.clock())
        self.save()
        self.probing = True
        self.probe_thread = threading.get_ident()
        self.client.image_resource_blocked = False
        self.client.last_request_retry_delay = 0
        remaining = self.state['deadline'] - self.clock()
        try:
            response = self.client._request(method, url, request_gate=self.client.image_gate, max_attempts=1, **{**kwargs, 'timeout': min(remaining, 120)})
            item = (response.json().get('data') or [{}])[0]
            encoded = item.get('b64_json') or item.get('b64Json')
            if not encoded and str(item.get('url', '')).startswith('data:image/'):
                encoded = item['url'].split(',', 1)[1]
            image = base64.b64decode(encoded, validate=True)
            with core.Image.open(BytesIO(image)) as decoded:
                decoded.verify()
            signature = self.signature(method, url, kwargs)
            path = self.root / 'images' / f'{signature}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.incoming')
            temporary.write_bytes(image)
            temporary.replace(path)
            core._save_state(path.with_suffix('.json'), {'requestHash': signature, 'imageSha256': hashlib.sha256(image).hexdigest(), 'recoveredAt': self.clock()})
            self.pending = None
            self.resume_required = False
            self.client.image_resource_failure = None
            self.state.update(status='recovered', recoveredAt=self.clock(), nextProbeAt=self.clock() + 120)
            self.resolve('same-request-valid-image-cached')
        except _protected_core.ProtectedCoreError:
            raise
        except core.ImageModelResourceBlocked:
            self.state.update(status='waiting', nextProbeAt=self.clock() + self.retry_delay())
            self.save()
        except RuntimeError as error:
            if not self.client.quota_exhausted and (not self.client.authentication_failed) and core.is_moderation_error(error):
                signature = self.signature(method, url, kwargs)
                core._save_state(self.root / 'images' / f'{signature}.json', {'requestHash': signature, 'rejectedEvidence': self.last_response_evidence})
                self.pending = None
                self.resume_required = False
                self.client.image_resource_failure = None
                self.state.update(status='recovered', recoveredAt=self.clock(), nextProbeAt=self.clock() + 120)
                self.resolve('resource-accessible-request-specific-rejection-cached')
                return
            self.client.image_resource_blocked = True
            self.state.update(status='waiting', nextProbeAt=self.clock() + max(self.retry_delay(), self.client.last_request_retry_delay))
            self.save()
            raise
        except Exception:
            self.client.image_resource_blocked = True
            self.state.update(status='waiting', nextProbeAt=self.clock() + max(self.retry_delay(), self.client.last_request_retry_delay))
            self.save()
            raise
        finally:
            self.probing = False
            self.probe_thread = None

    def run(self, generate):
        if self.state.get('status') == 'exhausted':
            raise core.ImageModelResourceBlocked(self.state.get('lastEvidence'))
        while True:
            try:
                result = generate()
                if self.resume_required or self.client.image_resource_blocked:
                    raise core.ImageModelResourceBlocked(self.state.get('lastEvidence'))
                if self.state and self.state.get('status') != 'resolved':
                    self.resolve('generation-segment-completed')
                return result
            except core.ImageModelResourceBlocked:
                while self.client.image_resource_blocked or self.resume_required:
                    try:
                        self.probe()
                    except _protected_core.ProtectedCoreError:
                        raise
                    except core.ImageModelResourceBlocked:
                        raise
                    except core.ModelQuotaExceeded:
                        raise
                    except core.ModelTransientError:
                        continue
                    except RuntimeError as error:
                        if self.client.authentication_failed or not str(error).startswith('HTTP 429:'):
                            raise
