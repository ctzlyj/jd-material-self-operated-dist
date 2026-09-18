from collections import deque
from io import BytesIO
import json
from pathlib import Path
import threading
import jd_material_agent as core
from dual_key_generation import DualKeyModelClient
from gemini_image_protocol import ENDPOINT, MODELS, request_payload, response_image, response_summary

def routing_config(profile, selling_model, concurrency):
    if profile not in ('gemini-flash', 'gemini-pro') or selling_model not in MODELS:
        raise ValueError('unsupported image routing; Product-Pro is not enabled')
    if concurrency not in (1, 2, 4):
        raise ValueError('Gemini evaluation concurrency must be 1, 2 or 4; not a provider limit claim')
    return {'formatVersion': 1, 'routes': {'white': profile, 'scene1': profile, 'scene2': profile, 'selling': selling_model, 'transparent': 'local'}, 'models': MODELS, 'imageConcurrency': concurrency, 'globalStartIntervalSeconds': 1, 'sameKeyStartIntervalSeconds': 2, 'geminiRetries': 0, 'gptTransportRetryPolicy': 'same-request-once-after-five-seconds'}

def freeze_routing(output, args):
    output = Path(output)
    profile = getattr(args, 'image_routing', 'legacy')
    selling = getattr(args, 'selling_image_model', 'gpt-image-2')
    path = output / '.state/image-routing.json'
    if profile == 'legacy':
        if path.exists() or selling != 'gpt-image-2':
            raise ValueError('frozen image routing cannot be changed or silently reset to legacy')
        return None
    if not getattr(args, 'dual_key_images', False) or not getattr(args, 'no_generation_retries', False) or getattr(args, 'resource_cooldown', False):
        raise ValueError('Gemini routing requires dual-key-images and no-generation-retries, without resource probes')
    config = routing_config(profile, selling, args.image_concurrency)
    fingerprint = core._auto_maintain_plan_hash(config)
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved != {'configuration': config, 'sha256': fingerprint}:
            raise ValueError('frozen image routing changed; preserve original run and receipts')
        return config
    progress_path = output / '.state/direct-progress.json'
    progress = json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.exists() else {}
    if any((progress.get(field) for field in ('segments', 'activeSpuIds', 'completedSpuIds', 'deferredSpuIds', 'prefetchedSegment'))) or any(((output / '.state' / name).exists() for name in ('dual-key-generation', 'model-metrics.json', 'run-events'))):
        raise ValueError('cannot switch an existing execution to Gemini; reconcile original writes first')
    core._save_state(path, {'configuration': config, 'sha256': fingerprint})
    return config

class GeminiRoutedModelClient(DualKeyModelClient):

    def __init__(self, primary, secondary, output, *, profile, selling_model='gpt-image-2', image_concurrency=4, **kwargs):
        self.routing = routing_config(profile, selling_model, image_concurrency)
        super().__init__(primary, secondary, output, image_concurrency=4, **kwargs)
        self.image_semaphore = threading.Semaphore(image_concurrency)
        self.scheduler.available = deque((0, 1, 0, 1)[:image_concurrency])
        self.http.event_hooks['response'].append(self.capture_headers)

    def capture_headers(self, response):
        if not core.is_image_request_url(str(response.request.url)) or not hasattr(self.local, 'event'):
            return
        self.local.event['httpStatus'] = response.status_code
        allowed = {'request-id', 'x-request-id', 'x-trace-id', 'date', 'retry-after'}
        self.local.event['responseHeaders'] = {name: self.clean(value) for name, value in response.headers.items() if name.lower() in allowed}
        core._save_state(self.scheduler.root / 'attempts' / (self.local.event['attemptId'] + '.json'), self.local.event)

    def edit_material(self, kind, prompt, source_path):
        if kind not in ('white', 'scene1', 'scene2', 'selling'):
            raise ValueError('unsupported image kind; transparent images are local only')
        if hasattr(self.local, 'image_request'):
            raise RuntimeError('nested image dispatch is not supported')
        model = MODELS[self.routing['routes'][kind]]
        source_bytes = Path(source_path).read_bytes()
        with core.Image.open(BytesIO(source_bytes)) as image:
            mime = image.get_format_mimetype() or 'image/png'
        payload = request_payload(model, prompt, source_bytes, mime) if model != core.PROVIDER.image_model else None
        self.local.image_request = {'model': model, 'kind': kind, 'payload': payload}
        try:
            return self.edit_image(prompt, source_path)
        finally:
            del self.local.image_request

    def image_signature(self, prompt, source_path):
        request = getattr(self.local, 'image_request', None)
        if request is None:
            raise ValueError('routed generation requires an explicit material kind')
        if request['payload'] is None:
            return super().image_signature(prompt, source_path)
        return core._auto_maintain_plan_hash({'method': 'POST', 'url': f'{core.PROVIDER.base_url}/{ENDPOINT}', 'payload': request['payload']})

    def image_metadata(self):
        request = self.local.image_request
        metadata = {'model': request['model'], 'materialKind': request['kind']}
        if request['payload'] is not None:
            metadata.update(endpoint=ENDPOINT, requestPayloadSha256=core._auto_maintain_plan_hash(request['payload']))
        return metadata

    def before_image_dispatch(self, method, url, kwargs):
        if self.local.image_request['payload'] is None:
            return
        event = self.local.event
        path = self.scheduler.root / 'gemini-requests' / (event['requestHash'] + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        reservation = {'status': 'reserved', 'attemptId': event['attemptId'], 'requestHash': event['requestHash'], 'model': event['model'], 'keySlot': event['keySlot'], 'reservedAt': self.scheduler.clock()}
        try:
            with path.open('x', encoding='utf-8') as stream:
                json.dump(reservation, stream, ensure_ascii=False, indent=2)
        except FileExistsError:
            raise RuntimeError('Gemini request already reserved; reuse valid cache or reconcile, no replay') from None

    def request_image(self, prompt, source_path):
        request = self.local.image_request
        if request['payload'] is None:
            return super().request_image(prompt, source_path)
        with self.image_semaphore:
            response = self._request('POST', f'{core.PROVIDER.base_url}/{ENDPOINT}', json=request['payload'], request_gate=self.image_gate, max_attempts=1)
            self.local.event.update(json.loads(self.clean(json.dumps(response_summary(response)))))
            return response_image(response.json())
