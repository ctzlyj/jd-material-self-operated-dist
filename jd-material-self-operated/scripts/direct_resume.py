import protected_core as _protected_core
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import threading
import time
import jd_material_agent as core
import manual_resume as manual
import direct_binding as binding
import direct_failures
import direct_pipeline

def plan_direct(handoff, erp, output, cache_dirs):
    snapshot = manual.load_handoff(handoff, erp)
    output = Path(output).resolve()
    roots = [Path(path).resolve() for path in cache_dirs]
    if any((output == root or output.is_relative_to(root) for root in roots)):
        raise ValueError('direct state must be independent from source caches')
    records, sources = manual.exporter.collect_cached_records(roots, erp, owner_erp=snapshot.queue.get('ownerErp', ''))
    records = manual.project_records(snapshot.jobs, records)
    evidence = {}
    for record in records:
        for filename in record['sourceFiles']:
            source = Path(filename).resolve()
            if not any((source.is_relative_to(root) for root in roots)):
                raise ValueError('receipt outside authorized cache roots')
            for path in (source, source.with_name('short-title-write.json'), source.with_name('upload-ledger.json')):
                if path.exists():
                    evidence[str(path)] = manual.sha(path)
    payload = {'formatVersion': 1, 'variant': core.VARIANT_ID, 'version': core.SKILL_VERSION, 'erp': erp, 'ownerErp': snapshot.queue.get('ownerErp', ''), 'output': str(output), 'handoff': str(snapshot.path), 'handoffSha256': manual.sha(snapshot.path), 'pendingQueueSha256': snapshot.receipt['pendingQueueSha256'], 'exclusionLedgerSha256': snapshot.receipt['exclusionLedgerSha256'], 'cacheDirectories': [str(path) for path in roots], 'cachePlans': sources, 'sourceReceipts': evidence, 'cachedRecords': records, 'jobs': [asdict(job) for job in snapshot.jobs], 'delivery': 'api-binding', 'allowedWrites': ['image-space-files', 'material-fields-in-pending-scope', 'short-titles-in-pending-scope']}
    payload['confirmToken'] = 'DIRECT-' + core._auto_maintain_plan_hash(payload)
    path = output / '.state/direct-plan.json'
    if path.exists() and manual.read_json(path) != json.loads(json.dumps(payload)):
        raise ValueError('direct plan changed; preserve the original and use a new directory')
    core._save_state(path, payload)
    return {'status': 'dry-run-ready', 'confirmToken': payload['confirmToken'], 'summary': snapshot.queue['summary']}

def load_direct(output, erp, token):
    output = Path(output).resolve()
    plan = manual.read_json(output / '.state/direct-plan.json')
    frozen = dict(plan)
    actual = frozen.pop('confirmToken')
    if token != actual or actual != 'DIRECT-' + core._auto_maintain_plan_hash(frozen):
        raise ValueError('direct confirmation hash mismatch')
    if plan['erp'] != erp or plan['output'] != str(output) or plan['variant'] != core.VARIANT_ID or (plan['delivery'] != 'api-binding'):
        raise ValueError('direct ERP or state identity mismatch')
    if plan.get('formatVersion') == 2:
        import first_use
        snapshot = first_use.fresh_snapshot(plan)
    else:
        manual.checked_json(plan['handoff'], plan['handoffSha256'])
        snapshot = manual.load_handoff(plan['handoff'], erp)
        if plan['pendingQueueSha256'] != snapshot.receipt['pendingQueueSha256'] or plan['exclusionLedgerSha256'] != snapshot.receipt['exclusionLedgerSha256']:
            raise ValueError('direct scope changed')
    if plan['jobs'] != json.loads(json.dumps([asdict(job) for job in snapshot.jobs])):
        raise ValueError('direct scope changed')
    for source in plan['cachePlans']:
        manual.checked_json(source['path'], source['sha256'])
    for path, digest in plan['sourceReceipts'].items():
        manual.checked_json(path, digest)
    return (plan, snapshot)

def migrate_writes(jobs, records, folder):
    folder = Path(folder)
    marker = folder / '.state/write-migration.json'
    if marker.exists():
        return manual.read_json(marker)
    state_path = folder / '.state/task.json'
    state = manual.read_json(state_path)
    by_spu = {record['spuId']: record for record in records}
    evidence = {}
    titles = {'submittedTitles': {}, 'unconfirmedTitles': {}, 'rejectedTitles': {}, 'requests': [], 'errors': []}
    for job in jobs:
        target = state['jobs'].setdefault(job.spu_id, {})
        for filename in by_spu.get(job.spu_id, {}).get('sourceFiles', []):
            source = Path(filename)
            if not source.exists():
                continue
            old = manual.read_json(source).get('jobs', {}).get(job.spu_id, {})
            evidence[str(source)] = manual.sha(source)
            for field in ('material_submission_intents', 'material_submission_receipts'):
                for kind, receipt in old.get(field, {}).items():
                    previous = target.setdefault(field, {}).get(kind)
                    if previous and previous['fingerprint'] != receipt['fingerprint']:
                        raise ValueError('conflicting legacy binding fingerprints; reconcile without replay')
                    target[field][kind] = dict(receipt)
            title_path = source.with_name('short-title-write.json')
            if not title_path.exists():
                continue
            audit = manual.read_json(title_path)
            evidence[str(title_path)] = manual.sha(title_path)
            unknown = dict(audit.get('unconfirmedTitles', {}))
            if 'unconfirmedTitles' not in audit and (audit.get('errors') or 'after' not in audit):
                unknown.update({row['skuId']: row['shortTitle'] for body in audit.get('requests', []) for row in body['reqList'] if row['skuId'] not in audit.get('submittedTitles', {})})
            for field, values in (('submittedTitles', audit.get('submittedTitles', {})), ('unconfirmedTitles', unknown), ('rejectedTitles', audit.get('rejectedTitles', {}))):
                for sku, value in values.items():
                    if sku not in job.short_title_sku_ids:
                        continue
                    previous = titles[field].get(sku)
                    if previous and previous != value:
                        raise ValueError('conflicting legacy title payload; reconcile without replay')
                    titles[field][sku] = value
    core._save_state(state_path, state)
    if any((titles[field] for field in ('submittedTitles', 'unconfirmedTitles', 'rejectedTitles'))):
        core._save_state(folder / '.state/short-title-write.json', titles)
    report = {'sources': evidence, 'legacyWritesReplayed': False}
    core._save_state(marker, report)
    return report

def freeze_requests(folder, payload):
    path = Path(folder) / '.state/direct-desired.json'
    if path.exists() and set(payload) == {'materials', 'shortTitles'}:
        previous = manual.read_json(path)['payload']
        materials = {(item['spuId'], item['materialType']): item for item in previous['materials']}
        titles = dict(previous['shortTitles'])
        for item in payload['materials']:
            key = (item['spuId'], item['materialType'])
            if key in materials and materials[key] != item:
                raise ValueError('direct desired material changed; reconcile before replacing')
            materials[key] = item
        for sku, title in payload['shortTitles'].items():
            if sku in titles and titles[sku] != title:
                raise ValueError('direct desired title changed; reconcile before replacing')
            titles[sku] = title
        payload = {'materials': list(materials.values()), 'shortTitles': titles}
    frozen = {'payload': payload, 'sha256': core._auto_maintain_plan_hash(payload)}
    if path.exists() and set(payload) != {'materials', 'shortTitles'} and (manual.read_json(path) != json.loads(json.dumps(frozen))):
        raise ValueError('direct desired payload changed; reconcile before replacing')
    core._save_state(Path(folder) / '.state/desired-history' / (frozen['sha256'] + '.json'), frozen)
    core._save_state(path, frozen)
    return frozen['sha256']

def validate_progress(output, progress, allowed):
    import upload_quarantine
    quarantined = upload_quarantine.load(output)
    if set(quarantined).intersection(progress['completedSpuIds']):
        raise ValueError('quarantined SPU cannot be marked complete')
    completed, deferred = (set(), set())
    for key, segment in progress['segments'].items():
        folder = Path(segment['directory']).resolve()
        if folder != (Path(output) / 'segments' / key).resolve():
            raise ValueError('direct progress segment path changed')
        receipt = Path(segment.get('reportPath', folder / 'direct-result.json')).resolve()
        if not receipt.is_relative_to(folder):
            raise ValueError('direct progress report path changed')
        report = manual.checked_json(receipt, segment['reportSha256'])
        if report.get('scopeRevision'):
            import scope_revision
            scope_revision.load(folder, expected=report['scopeRevision'])
        known = set(report['jobs'])
        successes = {spu for spu, item in report['jobs'].items() if item['complete']}
        if not known <= allowed or successes != set(segment['completed']) or known - successes != set(segment['deferred']):
            raise ValueError('direct progress contradicts persisted results')
        completed.update(successes)
        deferred.update(known - successes)
    if completed != set(progress['completedSpuIds']) or deferred - completed != set(progress['deferredSpuIds']) or (not set(progress.get('activeSpuIds', [])) <= allowed):
        raise ValueError('direct progress contains unrecorded completion or changed scope')

def save_report(folder, report):
    folder = Path(folder)
    path = folder / 'direct-result.json'
    if path.exists():
        path = folder / 'direct-results' / f'{time.time_ns()}.json'
    report = {**report, 'receiptPath': str(path)}
    core._save_state(path, report)
    return report

def refresh_progress(progress):
    completed = {spu for segment in progress['segments'].values() for spu in segment['completed']}
    deferred = {spu for segment in progress['segments'].values() for spu in segment['deferred']} - completed
    progress['completedSpuIds'] = sorted(completed)
    progress['deferredSpuIds'] = sorted(deferred)

def audit_request(request, materials, item):
    status, reason = binding._evaluate_binding_request(request, materials)
    receipt = item.get('material_submission_receipts', {}).get(str(request['materialType']), {})
    return {'spuId': request['spuId'], 'materialType': request['materialType'], 'fingerprint': request['fingerprint'], 'persisted': status in ('approved', 'pending'), 'auditStatus': status, 'reason': reason, 'auditApproved': status == 'approved', 'auditPending': status == 'pending', 'auditRejected': bool(binding.rejected_material_matches(request, materials)), 'accepted': receipt.get('fingerprint') == request['fingerprint']}

def failure_fraction(jobs):
    return sum((not item['complete'] and (not item.get('awaitingReadback', False)) and (not item.get('awaitingFinalReadback', False)) for item in jobs.values())) / max(1, len(jobs))

def title_spu_ids(jobs, desired):
    allowed = {sku for job in jobs for sku in job.short_title_sku_ids}
    if not set(desired) <= allowed:
        raise ValueError('desired title scope exceeds pending fields')
    return [job.spu_id for job in jobs if set(job.short_title_sku_ids).intersection(desired)]

def expected_titles(snapshot):
    source = snapshot.queue['sourcePlan']
    payload = manual.checked_json(source['path'], source['sha256'])
    owners = {sku: job.spu_id for job in snapshot.jobs for sku in job.short_title_sku_ids}
    values = {}
    for row in payload['result']['report_rows']:
        sku = str(row.get('skuId', ''))
        if sku not in owners:
            continue
        if sku in values or str(row.get('spuId')) != owners[sku] or row.get('shortTitleStatus') not in ('missing', 'complete') or (not isinstance(row.get('shortTitle'), str)):
            raise ValueError('original title identity or value is unavailable')
        values[sku] = core.cell_text(row['shortTitle'])
    if set(values) != set(owners):
        raise ValueError('original title scope is incomplete')
    return values

def submit_direct_titles(client, jobs, desired, folder, original_values):
    if not set(desired) <= set(original_values):
        raise ValueError('original title value is missing; no write is allowed')
    return binding.submit_self_operated_short_titles(client, title_spu_ids(jobs, desired), desired, folder, expected_before={sku: original_values[sku] for sku in desired}, defer_conflicts=True)

def source_blocks(plan):
    blocked = {}
    if plan.get('formatVersion') == 2:
        origin = plan['origin']
        source = manual.checked_json(origin['path'], origin['sha256'])
        allowed = set(plan.get('regenerateRejectedSpuIds', []))
        reasons = {}
        for row in source['result']['report_rows']:
            if row['spuId'] not in allowed and row.get('rejectedMaterials'):
                reasons.setdefault(row['spuId'], []).extend((material.get('reason') or 'native audit rejected' for material in row['rejectedMaterials']))
        for spu, messages in reasons.items():
            blocked[spu] = {'path': origin['path'], 'sha256': origin['sha256'], 'reason': '; '.join(dict.fromkeys(messages)), 'category': 'skipped-native-rejection'}
    cache = {}
    for record in plan['cachedRecords']:
        if all((record.get('urls', {}).get(kind) for kind in record['requiredKinds'])):
            continue
        for filename in reversed(record.get('sourceFiles', [])):
            if filename not in cache:
                cache[filename] = manual.read_json(filename)
            item = cache[filename].get('jobs', {}).get(record['spuId'])
            if item is None:
                continue
            reason = str(item.get('failure', ''))
            if any((marker in reason.lower() for marker in ('moderation_blocked', 'safety system', 'content policy', '内容策略'))):
                blocked[record['spuId']] = {'path': filename, 'sha256': manual.sha(filename), 'reason': reason}
            break
    return blocked

def pause_requested(output):
    path = Path(output) / '.state/control.json'
    if not path.exists():
        return False
    action = manual.read_json(path).get('action')
    if action not in ('pause', 'run'):
        raise ValueError('invalid direct checkpoint control')
    return action == 'pause'

class SharedModel:

    def __init__(self, args, output):
        self.args = args
        self.output = Path(output)
        self.client = None
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        metric_path = self.output / '.state/model-metrics.json'
        self.counts = manual.read_json(metric_path) if metric_path.exists() else {'requests': {}, 'responses': {}}

    def event(self, bucket, key):
        with self.lock:
            self.counts[bucket][key] = self.counts[bucket].get(key, 0) + 1
            core._save_state(self.output / '.state/model-metrics.json', self.counts)

    def get(self):
        if self.client is None:
            if getattr(self.args, 'dual_key_images', False):
                if not getattr(self.args, 'no_generation_retries', False) or getattr(self.args, 'resource_cooldown', False):
                    raise ValueError('dual-key mode requires no-generation-retries, without same-request resource probes')
                from dual_key_generation import DualKeyModelClient
                self.client = DualKeyModelClient(os.environ.get(core.PROVIDER.api_key_env, ''), os.environ.get('JD_LLM_API_KEY_2', ''), self.output, timeout=self.args.timeout, image_concurrency=self.args.image_concurrency, paused=lambda: pause_requested(self.output))
            else:
                self.client = core.ModelClient(os.environ.get(core.PROVIDER.api_key_env, ''), timeout=self.args.timeout, image_concurrency=self.args.image_concurrency)
            self.client.no_generation_retries = bool(getattr(self.args, 'no_generation_retries', False))
            self.client.skip_failed_images = bool(getattr(self.args, 'defer_incomplete', False))
            self.client.cancel_event = self.cancel_event
            if getattr(self.args, 'resource_cooldown', False):
                from image_resource_recovery import ImageResourceRecovery
                self.client.image_resource_recovery = ImageResourceRecovery(self.client, self.output, paused=lambda: pause_requested(self.output), window_seconds=getattr(self.args, 'resource_cooldown_window', 300))
            self.client.http.event_hooks['request'].append(lambda request: self.event('requests', request.url.path))
            self.client.http.event_hooks['response'].append(lambda response: self.event('responses', str(response.status_code)))
        return self.client

    def close(self):
        if self.client is not None:
            self.client.close()

def subset_result(original, jobs):
    selected = {job.spu_id for job in jobs}
    rows = tuple((row for row in original.prepared.rows if row.spu_id in selected))
    if {row.sku_id for row in rows} != {sku for job in jobs for sku in job.sku_ids}:
        raise ValueError('incomplete sibling SKU scope')
    return replace(original, prepared=replace(original.prepared, jobs=tuple(jobs), rows=rows, original_rows=len(rows)), reference_urls={spu: url for spu, url in original.reference_urls.items() if spu in selected})

def prepare_direct_generation(result, records, folder, args, client, cache_roots):
    import scope_revision
    with direct_pipeline.phase(folder, 'initialScope') as scope:
        client.select_shop()
        if client.expected_erp != args.erp or client.owner_erp != args.owner_erp:
            raise ValueError('authenticated ERP changed')
        result, revision = scope_revision.prepare(folder, result, args, client, records)
    with direct_pipeline.phase(folder, 'cacheMigration') as cache:
        batch = folder / '批次001'
        migration = manual.seed_cache(result.prepared, records, batch, cache_roots)
        migrate_writes(result.prepared.jobs, records, batch)
    return {'migration': migration, 'result': result, 'scopeRevision': revision, 'stageSeconds': {'initialScope': scope['elapsedSeconds'], 'cacheMigration': cache['elapsedSeconds']}}

def generate_direct_materials(result, args, folder, model, prepared):
    result = prepared.get('result', result)
    with direct_pipeline.phase(folder, 'generation') as event:
        if not getattr(args, 'cached_only', False):
            if getattr(args, 'resource_cooldown', False):
                recovery = model.get().image_resource_recovery
                recovery.run(lambda: core._generate_erp_materials(result, args, folder, model_client_factory=model.get))
            else:
                core._generate_erp_materials(result, args, folder, model_client_factory=model.get)
    prepared['stageSeconds']['generation'] = event['elapsedSeconds']
    return prepared

def execute_direct_segment(result, records, folder, args, client, cache_roots, model, *, generation=None, after_generation=None):
    started = time.monotonic()
    checkpoint = started
    stage_seconds = {}

    def finish_stage(name):
        nonlocal checkpoint
        observed = time.monotonic()
        stage_seconds[name] = round(observed - checkpoint, 3)
        checkpoint = observed
    batch = folder / '批次001'
    cached_only = bool(getattr(args, 'cached_only', False))
    if generation is None:
        prepared = prepare_direct_generation(result, records, folder, args, client, cache_roots)
        prepared = generate_direct_materials(result, args, folder, model, prepared)
    else:
        prepared = generation.result()
    result = prepared.get('result', result)
    migration = prepared['migration']
    stage_seconds.update(prepared['stageSeconds'])
    checkpoint = time.monotonic()
    if after_generation is not None:
        after_generation()
        finish_stage('lookaheadPreparation')
    state = manual.read_json(batch / '.state/task.json')
    import upload_quarantine
    quarantined = upload_quarantine.for_batch(batch)
    ready = {job.spu_id for job in result.prepared.jobs if job.spu_id not in quarantined and core._material_is_complete(job, state['jobs'].get(job.spu_id, {}), batch / '全部图片')}
    image_ready = {job.spu_id for job in result.prepared.jobs if job.spu_id in ready and core._model_kinds(job)}
    upload = core.upload_self_operated_materials(client, result.prepared, batch, args.category_id, selected_spu_ids=image_ready) if image_ready else None
    direct_failures.check_unknown_writes(batch, uploads_only=True)
    finish_stage('imageUpload')
    state = manual.read_json(batch / '.state/task.json')
    eligible = set()
    preparation_failures = []
    upload_failed = set(upload.failed_spu_ids) if upload else set()
    for job in result.prepared.jobs:
        if job.spu_id not in ready or job.spu_id in upload_failed:
            continue
        try:
            binding.build_self_operated_binding_requests(job, state['jobs'][job.spu_id])
            eligible.add(job.spu_id)
        except ValueError as error:
            preparation_failures.append({'spuId': job.spu_id, 'reason': str(error)})
    prepared_plan = binding.prepare_self_operated_binding_plan(client, result.prepared, batch, selected_spu_ids=eligible)
    failed_before_titles = upload_failed | {item['spuId'] for item in prepared_plan.preflight_failures}
    desired_titles = {sku: title for job in result.prepared.jobs for sku, title in state['jobs'].get(job.spu_id, {}).get('short_titles', {}).items() if job.spu_id in ready and job.spu_id not in failed_before_titles and (sku in job.short_title_sku_ids)}
    canonical = {'materials': [{key: request[key] for key in ('spuId', 'materialType', 'skuIds', 'body', 'fingerprint')} for request in prepared_plan.authorization_requests], 'shortTitles': desired_titles}
    freeze_requests(batch, canonical)
    wire_payload = {'directPlanToken': args.confirm_token, 'erp': args.erp, 'requests': list(prepared_plan.requests), 'shortTitles': desired_titles, 'shortTitlesBefore': {sku: args._expected_titles[sku] for sku in desired_titles}, 'skuIds': [sku for job in result.prepared.jobs for sku in job.sku_ids]}
    attempt = batch / '.state/write-attempts' / str(time.time_ns())
    token = binding.confirm_self_operated_writes(attempt, wire_payload, '')
    binding.confirm_self_operated_writes(attempt, wire_payload, token)
    finish_stage('bindingPreparation')
    client.select_shop()
    if client.expected_erp != args.erp or client.owner_erp != args.owner_erp:
        raise ValueError('authenticated ERP changed')
    client.verify_product_scope(result.prepared.jobs)
    finish_stage('preWriteScope')
    bound = binding.execute_self_operated_binding_plan(client, prepared_plan)
    finish_stage('bindingAndReadback')
    title_result = submit_direct_titles(client, result.prepared.jobs, desired_titles, batch, args._expected_titles)
    finish_stage('shortTitlesAndReadback')
    direct_failures.check_unknown_writes(batch)
    native_readback = manual.checked_json(bound.readback_path, bound.readback_sha256)
    actual, query_failures = (native_readback['materialsBySku'], native_readback['queryFailures'])
    state = manual.read_json(batch / '.state/task.json')
    checks = [audit_request(request, actual, state['jobs'][request['spuId']]) for request in prepared_plan.authorization_requests]
    title_audit = manual.read_json(batch / '.state/short-title-write.json') if desired_titles else {}
    after = {str(row['skuId']): row.get('shortTitle') for row in title_audit.get('after', []) if row.get('shortTitleKnown') is True}
    jobs = {}
    for job in result.prepared.jobs:
        material_checks = [item for item in checks if item['spuId'] == job.spu_id]
        material_ok = not core._has_material_work(job) or (job.spu_id in eligible and bool(material_checks) and (job.spu_id not in query_failures) and all((item['persisted'] for item in material_checks)))
        titles_ok = all((sku in desired_titles and after.get(sku) == desired_titles[sku] for sku in job.short_title_sku_ids))
        waiting_titles = all((sku in desired_titles and (after.get(sku) == desired_titles[sku] or sku in title_result['pending']) for sku in job.short_title_sku_ids))
        waiting_materials = material_ok or (job.spu_id in eligible and bool(material_checks) and (job.spu_id not in query_failures) and all((item['persisted'] or (item['accepted'] and item['auditStatus'] == 'mismatch') for item in material_checks)))
        jobs[job.spu_id] = {'materialVerified': material_ok, 'titlesVerified': titles_ok, 'complete': material_ok and titles_ok, 'skuCount': len(job.sku_ids), 'awaitingReadback': not (material_ok and titles_ok) and waiting_materials and waiting_titles, 'generationError': state['jobs'].get(job.spu_id, {}).get('failure', ''), 'failureReasons': direct_failures.job_failure_reasons(job, upload_failures=upload.failures if upload else [], preflight_failures=[*preparation_failures, *prepared_plan.preflight_failures], title_audit=title_audit)}
    finish_stage('verification')
    report = {'jobs': jobs, 'materialChecks': checks, 'queryFailures': query_failures, 'scopeRevision': prepared.get('scopeRevision'), 'materialReadback': actual, 'binding': asdict(bound), 'shortTitles': title_result, 'upload': asdict(upload) if upload else None, 'cacheMigration': migration, 'elapsedSeconds': round(checkpoint - started, 3), 'stageSeconds': stage_seconds, 'generationMode': 'cached-only' if cached_only else 'generate-missing', 'generationPrefetched': generation is not None, 'scoreRefreshed': False}
    if getattr(bound, 'readback_deferred', False) is True or title_result.get('readbackDeferred') is True:
        for item in jobs.values():
            item.update(complete=False, awaitingFinalReadback=True)
        report.update(readbackDeferred=True, deferredStateSha256=manual.sha(batch / '.state/task.json'), deferredDesiredSha256=manual.sha(batch / '.state/direct-desired.json'))
        for check in checks:
            check.update(persisted=False, auditStatus='not-queried', auditApproved=False, auditPending=False, auditRejected=False, reason='awaiting final readback')
    for spu, item in quarantined.items():
        jobs[spu].update(complete=False, materialVerified=False, titlesVerified=False, awaitingFinalReadback=False, awaitingReadback=False, quarantined=True, quarantine=item['evidence'], generationError=upload_quarantine.REASON)
    report = json.loads(json.dumps(report, ensure_ascii=False, default=str))
    return save_report(folder, report)

def run_direct(args, client=None):
    output = Path(args.output_dir).resolve()
    plan, snapshot = load_direct(output, args.erp, args.confirm_token)
    if args.confirm != 'GENERATE_UPLOAD_BIND_AND_VERIFY':
        raise ValueError('explicit direct authorization required')
    if not 1 <= args.batch_size <= 50 or (args.limit is not None and args.limit < 1):
        raise ValueError('invalid batch size or limit')
    cached_only = bool(getattr(args, 'cached_only', False))
    if cached_only and (args.limit is None or args.limit > 50):
        raise ValueError('cached-only execution requires a bounded limit of at most 50 SPUs')
    args.owner_erp = plan['ownerErp']
    args._expected_titles = expected_titles(snapshot)
    path = output / '.state/direct-progress.json'
    with core._erp_execution_lock(output):
        progress = manual.read_json(path) if path.exists() else {'segments': {}, 'completedSpuIds': [], 'deferredSpuIds': []}
        validate_progress(output, progress, {job.spu_id for job in snapshot.jobs})
        progress['heldSpus'] = source_blocks(plan)
        active = progress.get('activeSpuIds', [])
        if cached_only and (not (active or getattr(args, 'repair_segment', None))):
            raise ValueError('cached-only execution requires an existing active or repair segment')
        excluded = set(progress['completedSpuIds']) | set(progress['deferredSpuIds']) | set(active) | set(progress['heldSpus'])
        records = {record['spuId']: record for record in plan['cachedRecords']}
        original = manual.derive_result(snapshot, snapshot.jobs)
        prefetched = direct_pipeline.pending_group(output, progress, snapshot.jobs, original, args)
        excluded.update((job.spu_id for job in prefetched))
        import direct_titles
        reserved = direct_titles.pending_full_groups(output, plan, snapshot.jobs, progress)
        if prefetched:
            pending_ids = {job.spu_id for job in prefetched}
            for group in reserved:
                group_ids = {job.spu_id for job in group}
                if pending_ids & group_ids and pending_ids != group_ids:
                    raise ValueError('lookahead would split canonical title group')
            reserved = [group for group in reserved if not pending_ids & {job.spu_id for job in group}]
            reserved.insert(0, prefetched)
        excluded.update((job.spu_id for group in reserved for job in group))
        jobs = [job for job in snapshot.jobs if job.spu_id not in excluded]
        jobs.sort(key=lambda job: not all((records[job.spu_id].get('urls', {}).get(kind) for kind in records[job.spu_id]['requiredKinds'])))
        if args.limit is not None:
            jobs = jobs[:max(0, args.limit - len(active))]
        groups = [jobs[offset:offset + args.batch_size] for offset in range(0, len(jobs), args.batch_size)]
        if reserved:
            groups = reserved + groups
            if args.limit is not None:
                remaining = max(0, args.limit - len(active))
                limited = []
                for group in groups:
                    if len(group) > remaining:
                        break
                    limited.append(group)
                    remaining -= len(group)
                groups = limited
        if active:
            selected = {job.spu_id: job for job in snapshot.jobs}
            groups.insert(0, [selected[spu] for spu in active])
        repair = getattr(args, 'repair_segment', None)
        if repair:
            if active or repair not in progress['segments']:
                raise ValueError('repair requires a persisted segment and no active segment')
            segment = progress['segments'][repair]
            identifiers = set(segment['completed']) | set(segment['deferred'])
            if identifiers.intersection(progress['heldSpus']):
                raise ValueError('content-policy held tasks require resolution before repair')
            saved = manual.read_json(Path(segment['directory']) / '.state/self-operated-plan.json')
            ordered = [job['spu_id'] for job in saved['result']['prepared']['jobs']]
            selected = {job.spu_id: job for job in snapshot.jobs}
            if set(ordered) != identifiers:
                raise ValueError('repair segment scope changed')
            groups = [[selected[spu] for spu in ordered]]
        if cached_only:
            groups = groups[:1]
        model = SharedModel(args, output)
        client = client or binding.create_direct_client(args)
        if getattr(args, 'defer_readback', False) or getattr(client, 'defer_readback', False) is True:
            client.defer_readback = bool(getattr(args, 'defer_readback', False))
        pipeline = direct_pipeline.Lookahead(output, progress, args, client, list(records.values()), plan['cacheDirectories'], model) if getattr(args, 'pipeline', False) and (not cached_only) else None
        run_started = time.monotonic()
        run_path = output / '.state/run-events' / f'{time.time_ns()}.json'
        run_event = {'startedAt': time.time(), 'status': 'running', 'pipeline': pipeline is not None}
        if progress.get('error'):
            previous_path = output / '.state/progress-history' / f'{time.time_ns()}-before-resume.json'
            previous_path.parent.mkdir(parents=True, exist_ok=True)
            previous_path.write_bytes(path.read_bytes())
            run_event['previousProgress'] = {'path': str(previous_path), 'sha256': manual.sha(previous_path)}
            progress.pop('error')
        core._save_state(run_path, run_event)
        try:
            for group_index, selected in enumerate(groups):
                if pause_requested(output):
                    progress['status'] = 'paused-at-checkpoint'
                    break
                identifiers = [job.spu_id for job in selected]
                if progress.get('prefetchedSegment', {}).get('spuIds') == identifiers:
                    progress.pop('prefetchedSegment')
                progress.update({'activeSpuIds': identifiers, 'pid': os.getpid(), 'workerRunning': True, 'status': 'running', 'updatedAt': time.time()})
                core._save_state(path, progress)
                result = subset_result(original, selected)
                key, folder = direct_pipeline.freeze_segment(output, result, args)
                options = {}
                if pipeline is not None:
                    options['generation'] = pipeline.take(identifiers)
                    if group_index + 1 < len(groups):
                        following = subset_result(original, groups[group_index + 1])
                        options['after_generation'] = lambda: pipeline.start(following)
                with direct_pipeline.phase(folder, 'segment'):
                    report = execute_direct_segment(result, list(records.values()), folder, args, client, plan['cacheDirectories'], model, **options)
                direct_failures.check_unknown_writes(folder / '批次001')
                succeeded = [spu for spu, item in report['jobs'].items() if item['complete']]
                failed = sorted(set(identifiers) - set(succeeded))
                previous_segment = progress['segments'].get(key)
                if previous_segment:
                    core._save_state(output / '.state/progress-history' / f'{time.time_ns()}.json', previous_segment)
                progress['segments'][key] = {'directory': str(folder), 'reportPath': report['receiptPath'], 'reportSha256': manual.sha(report['receiptPath']), 'completed': succeeded, 'deferred': failed, 'elapsedSeconds': report['elapsedSeconds']}
                refresh_progress(progress)
                progress.update({'activeSpuIds': [], 'updatedAt': time.time(), 'remainingSpus': len(snapshot.jobs) - len(progress['completedSpuIds'])})
                core._save_state(path, progress)
                print(json.dumps({'segment': key, 'completedSpus': len(progress['completedSpuIds']), 'deferredSpus': len(progress['deferredSpuIds']), 'remainingSpus': progress['remainingSpus'], 'elapsedSeconds': report['elapsedSeconds']}, ensure_ascii=False), flush=True)
                if model.client is not None and model.client.quota_exhausted:
                    raise RuntimeError('model quota exhausted; cached progress preserved')
                if model.client is not None and getattr(model.client, 'authentication_failed', False):
                    raise RuntimeError('model authentication failed; cached progress preserved')
                if pipeline is not None and pipeline.scope_error is not None:
                    raise pipeline.scope_error
                if report.get('queryFailures') or (not getattr(args, 'defer_incomplete', False) and failure_fraction(report['jobs']) > 0.2):
                    progress['status'] = 'paused-failure-gate'
                    break
            else:
                accounted = set(progress['completedSpuIds']) | set(progress['deferredSpuIds']) | set(progress['heldSpus'])
                progress['status'] = 'scope-verified' if len(progress['completedSpuIds']) == len(snapshot.jobs) else 'finished-with-failures' if len(accounted) == len(snapshot.jobs) else 'checkpoint'
                if getattr(args, 'defer_readback', False) and progress['status'] == 'finished-with-failures':
                    progress['status'] = 'awaiting-final-readback'
        except _protected_core.ProtectedCoreError:
            raise
        except Exception as error:
            progress.update({'status': 'paused-error', 'error': str(error), 'updatedAt': time.time()})
            raise
        finally:
            if pipeline is not None:
                pipeline.close()
            model.close()
            progress['workerRunning'] = False
            run_event.update(endedAt=time.time(), wallSeconds=round(time.monotonic() - run_started, 3), status=progress.get('status'))
            core._save_state(run_path, run_event)
            progress['lastRun'] = {**run_event, 'path': str(run_path)}
            core._save_state(path, progress)
            try:
                direct_failures.export_failures(output, progress, snapshot.jobs, args.erp)
            except _protected_core.ProtectedCoreError:
                raise
            except Exception as error:
                progress['failureExportError'] = str(error)
                core._save_state(path, progress)
            close_images = getattr(client, 'close_image_transport', None)
            if callable(close_images):
                close_images()
        return {'status': progress['status'], 'completedSpus': len(progress['completedSpuIds']), 'deferredSpus': len(progress['deferredSpuIds']), 'remainingSpus': len(snapshot.jobs) - len(progress['completedSpuIds'])}
