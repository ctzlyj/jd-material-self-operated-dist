import protected_core as _protected_core
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import shutil
import time
import jd_material_agent as agent
import manual_import_export as exporter

@dataclass(frozen=True)
class Handoff:
    path: Path
    receipt: dict
    queue: dict
    exclusions: dict
    jobs: tuple

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def checked_json(path, expected):
    if sha(path) != expected:
        raise ValueError('SHA mismatch; preserve the original receipt and stop')
    return read_json(path)

def load_handoff(path, erp):
    path = Path(path).resolve()
    receipt = read_json(path)
    if receipt.get('erp') != erp:
        raise ValueError('handoff ERP mismatch')
    if receipt.get('status') != 'paused-for-independent-skills-split' or receipt.get('legacyRunnerMustNotResume') is not True:
        raise ValueError('unknown handoff policy; never resume a legacy writer')
    queue = checked_json(receipt['pendingQueue'], receipt['pendingQueueSha256'])
    exclusions = checked_json(receipt['exclusionLedger'], receipt['exclusionLedgerSha256'])
    if queue.get('erp') != erp or exclusions.get('erp') != erp or queue.get('ownerErp', '') != exclusions.get('ownerErp', ''):
        raise ValueError('queue/exclusion ERP mismatch')
    if queue.get('formatVersion') != 1 or exclusions.get('formatVersion') != 1:
        raise ValueError('unsupported queue/exclusion schema')
    if exclusions.get('status') != 'user-taking-over-manual-import':
        raise ValueError('expected a manual takeover exclusion ledger')
    if agent._auto_maintain_plan_hash(exclusions) != queue['exclusions']['sha256']:
        raise ValueError('semantic exclusion SHA mismatch')
    checked_json(queue['sourcePlan']['path'], queue['sourcePlan']['sha256'])
    jobs, seen_spus, seen_skus = ([], set(), set())
    removed = set(queue['fullyRemovedSpuIds'])
    for raw in queue['jobs']:
        job = agent.SpuJob(**{**raw, 'sku_ids': tuple(raw['sku_ids']), 'skus': tuple((tuple(row) for row in raw['skus'])), 'short_title_sku_ids': tuple(raw['short_title_sku_ids'])})
        if job.spu_id in removed:
            raise ValueError('fully excluded SPU was reintroduced')
        if job.spu_id in seen_spus or not job.spu_id.isdecimal() or (not job.sku_ids):
            raise ValueError('invalid or duplicate SPU')
        if len(set(job.sku_ids)) != len(job.sku_ids) or seen_skus.intersection(job.sku_ids) or set(job.sku_ids) != {sku for sku, title in job.skus} or (not set(job.short_title_sku_ids) <= set(job.sku_ids)):
            raise ValueError('incomplete or duplicate SKU membership')
        material = exclusions['materials'].get(job.spu_id)
        if material:
            if set(material['skuIds']) != set(job.sku_ids):
                raise ValueError('manual delivery SKU membership changed')
            if any((getattr(job, field) for field in material['fields'])):
                raise ValueError('excluded material field was reintroduced')
        for sku in job.sku_ids:
            delivered = exclusions['shortTitles'].get(sku)
            if delivered and (delivered['spuId'] != job.spu_id or sku in job.short_title_sku_ids):
                raise ValueError('excluded short title was reintroduced or changed owner')
        if not agent._has_material_work(job) and (not job.short_title_sku_ids):
            raise ValueError('pending queue contains a completed job')
        jobs.append(job)
        seen_spus.add(job.spu_id)
        seen_skus.update(job.sku_ids)
    counts = {'remainingSpus': len(jobs), 'remainingSkus': sum((len(job.sku_ids) for job in jobs)), 'remainingTitleSkus': sum((len(job.short_title_sku_ids) for job in jobs))}
    if any((queue['summary'][key] != value for key, value in counts.items())):
        raise ValueError('pending queue count mismatch')
    return Handoff(path, receipt, queue, exclusions, tuple(jobs))

def project_records(jobs, records):
    cached = {record['spuId']: record for record in records}
    projected = []
    for job in jobs:
        record = cached.get(job.spu_id, {})
        if record and set(record['skuIds']) != set(job.sku_ids):
            raise ValueError('cache SKU membership differs from the pending queue')
        projected.append({**record, 'spuId': job.spu_id, 'skuIds': list(job.sku_ids), 'requiredKinds': agent._model_kinds(job) + (['transparent'] if job.needs_white else []), 'needsSellingPoints': job.needs_selling_points, 'shortTitleSkuIds': list(job.short_title_sku_ids), 'sellingPoints': record.get('sellingPoints', []), 'shortTitles': {sku: record.get('shortTitles', {}).get(sku) for sku in job.short_title_sku_ids if record.get('shortTitles', {}).get(sku)}, 'urls': dict(record.get('urls', {})), 'sourceFiles': record.get('sourceFiles', [])})
    return projected

def plan_resume(handoff_path, erp, output, cache_dirs):
    snapshot = load_handoff(handoff_path, erp)
    output = Path(output).resolve()
    roots = [Path(path).resolve() for path in cache_dirs]
    if any((output == root or output.is_relative_to(root) for root in roots)):
        raise ValueError('new independent state must be outside the legacy cache directories')
    records, sources = exporter.collect_cached_records(roots, erp, owner_erp=snapshot.queue.get('ownerErp', ''))
    projected = project_records(snapshot.jobs, records)
    payload = {'formatVersion': 1, 'variant': agent.VARIANT_ID, 'version': agent.SKILL_VERSION, 'erp': erp, 'ownerErp': snapshot.queue.get('ownerErp', ''), 'output': str(output), 'handoff': str(snapshot.path), 'handoffSha256': sha(snapshot.path), 'pendingQueueSha256': snapshot.receipt['pendingQueueSha256'], 'exclusionLedgerSha256': snapshot.receipt['exclusionLedgerSha256'], 'cacheDirectories': [str(path) for path in roots], 'cachePlans': sources, 'jobs': [asdict(job) for job in snapshot.jobs], 'cachedRecords': projected, 'allowedWrites': ['image-space-files-only'], 'delivery': 'manual-workbooks'}
    payload['confirmToken'] = 'MANUAL-' + agent._auto_maintain_plan_hash(payload)
    destination = output / '.state/resume-plan.json'
    if destination.exists() and read_json(destination) != payload:
        raise ValueError('independent frozen resume plan changed; use a new output directory')
    agent._save_state(destination, payload)
    return {'status': 'dry-run-ready', 'confirmToken': payload['confirmToken'], 'summary': snapshot.queue['summary'], 'cachedSpus': sum((bool(record['sourceFiles']) for record in projected)), 'oldWritesReplayed': False, 'platformCompletionVerified': False}

def load_plan(output, erp, token):
    output = Path(output).resolve()
    plan = read_json(output / '.state/resume-plan.json')
    frozen = dict(plan)
    actual = frozen.pop('confirmToken')
    if actual != token or actual != 'MANUAL-' + agent._auto_maintain_plan_hash(frozen):
        raise ValueError('independent confirm token mismatch')
    if plan['output'] != str(output) or plan['erp'] != erp or plan['variant'] != agent.VARIANT_ID:
        raise ValueError('independent state identity mismatch')
    checked_json(plan['handoff'], plan['handoffSha256'])
    snapshot = load_handoff(plan['handoff'], erp)
    if plan['pendingQueueSha256'] != snapshot.receipt['pendingQueueSha256'] or plan['exclusionLedgerSha256'] != snapshot.receipt['exclusionLedgerSha256'] or json.loads(json.dumps([asdict(job) for job in snapshot.jobs])) != plan['jobs']:
        raise ValueError('pending job scope changed')
    for source in plan['cachePlans']:
        checked_json(source['path'], source['sha256'])
    return (plan, snapshot)

def export_pending(output, erp, token, destination):
    plan, snapshot = load_plan(output, erp, token)
    records = {record['spuId']: record for record in plan['cachedRecords']}
    progress_path = Path(output) / '.state/resume-progress.json'
    if progress_path.exists():
        for segment in read_json(progress_path)['segments'].values():
            receipt = checked_json(Path(segment['directory']) / '手动上传表/导出清单.json', segment['reportSha256'])
            records.update({record['spuId']: record for record in receipt['records']})
    report = exporter.export_records(project_records(snapshot.jobs, records.values()), destination)
    report.update({'erp': erp, 'sourcePlanSha256': sha(Path(output) / '.state/resume-plan.json'), 'exclusionLedgerSha256': snapshot.receipt['exclusionLedgerSha256'], 'modelCalls': 0, 'newImageUploads': 0, 'platformCompletionVerified': False})
    agent._save_state(Path(destination) / '导出清单.json', report)
    return report

def seed_cache(prepared, records, folder, cache_roots):
    folder = Path(folder).resolve()
    state_path = folder / '.state/task.json'
    migration_path = folder / '.state/cache-migration.json'
    if state_path.exists():
        state = read_json(state_path)
        if state.get('variant') != agent.VARIANT_ID or state.get('task_signature') != agent._task_signature(prepared):
            raise ValueError('independent seeded state scope mismatch')
        return {**read_json(migration_path), 'alreadySeeded': True}
    roots = [Path(root).resolve() for root in cache_roots]
    by_spu = {record['spuId']: record for record in records}
    selected_sources = {}
    carried_receipts = {}
    evidence, copied = ([], 0)
    for job in prepared.jobs:
        record = by_spu.get(job.spu_id, {})
        paths = []
        for source in record.get('sourceFiles', []):
            path = Path(source).resolve()
            if not any((path.is_relative_to(root) for root in roots)):
                raise ValueError('cache source is outside the authorized roots')
            if not path.exists():
                continue
            ledger_path = path.with_name('upload-ledger.json')
            ledger = read_json(ledger_path).get('files', {}) if ledger_path.exists() else {}
            for filename in agent.image_names(job.spu_id).values():
                receipt = ledger.get(filename, {})
                if receipt.get('status') not in ('uploading', 'unconfirmed', 'submitted', 'unknown', 'upload_submitted'):
                    continue
                image = path.parent.parent / '全部图片' / filename
                if not image.is_file() or receipt.get('sha256') != sha(image):
                    raise ValueError('unknown legacy upload has no matching frozen local image')
                carried_receipts[filename] = {**receipt, 'status': 'uploading', 'sourceLedgerSha256': sha(ledger_path), 'sourceLedger': str(ledger_path)}
            evidence.append({'path': str(path), 'sha256': sha(path)})
            paths.append(path)
        selected_sources[job.spu_id] = paths
    state = {'jobs': {}}
    for job in prepared.jobs:
        record = by_spu.get(job.spu_id, {})
        item = {'selling_points': record.get('sellingPoints', []), 'short_titles': record.get('shortTitles', {}), 'uploaded_urls': record.get('urls', {})}
        state['jobs'][job.spu_id] = item
        for kind, filename in agent.image_names(job.spu_id).items():
            for path in reversed(selected_sources[job.spu_id]):
                candidate = path.parent.parent / '全部图片' / filename
                if agent.valid_material_image(candidate, kind):
                    destination = folder / '全部图片' / filename
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(candidate, destination)
                    copied += 1
                    evidence.append({'path': str(candidate), 'sha256': sha(candidate)})
                    break
        for path in reversed(selected_sources[job.spu_id]):
            candidate = path.parent.parent / '参考图' / f'{job.spu_id}.jpg'
            if candidate.is_file():
                destination = folder / '参考图' / candidate.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate, destination)
                evidence.append({'path': str(candidate), 'sha256': sha(candidate)})
                break
    migration = {'reusedImages': copied, 'sources': evidence, 'alreadySeeded': False, 'legacyWritesReplayed': False}
    agent._save_state(migration_path, migration)
    if carried_receipts:
        agent._save_upload_ledger(folder / '.state/upload-ledger.json', {'version': 1, 'files': carried_receipts})
    agent._bind_state(state, prepared, state_path)
    return migration

def derive_result(snapshot, jobs):
    source_path = Path(snapshot.queue['sourcePlan']['path'])
    payload = read_json(source_path)
    original = agent.load_self_operated_plan(source_path.parent.parent, erp=payload['erp'], owner_erp=payload['ownerErp'], target=payload['target'], token=payload['confirmToken'])
    selected = {job.spu_id: job for job in jobs}
    rows_by_spu = {spu: [] for spu in selected}
    for row in original.prepared.rows:
        if row.spu_id in selected:
            rows_by_spu[row.spu_id].append(row)
    rows = []
    for job in jobs:
        if {row.sku_id for row in rows_by_spu[job.spu_id]} != set(job.sku_ids):
            raise ValueError('original frozen plan does not retain every pending SKU')
        rows.extend(rows_by_spu[job.spu_id])
    prepared = replace(original.prepared, jobs=tuple(jobs), rows=tuple(rows), original_rows=len(rows), filtered_rows=0, duplicate_rows=0)
    return replace(original, prepared=prepared, failed_spus=(), safe_to_continue=True, reference_urls={spu: url for spu, url in original.reference_urls.items() if spu in selected}, existing_materials={}, report_rows=(), summary={'source': snapshot.queue['basis']})

def execute_segment(result, records, folder, args, client, cache_roots):
    started = time.monotonic()
    client.select_shop()
    if client.expected_erp != args.erp or client.owner_erp != args.owner_erp:
        raise ValueError('authenticated ERP changed before generation')
    client.verify_product_scope(result.prepared.jobs)
    migration = seed_cache(result.prepared, records, folder / '批次001', cache_roots)
    agent._generate_erp_materials(result, args, folder)
    state = read_json(folder / '批次001/.state/task.json')
    ready = {job.spu_id for job in result.prepared.jobs if agent._model_kinds(job) and agent._material_is_complete(job, state['jobs'].get(job.spu_id, {}), folder / '批次001/全部图片')}
    upload = None
    if ready:
        client.select_shop()
        client.verify_product_scope([job for job in result.prepared.jobs if job.spu_id in ready])
        upload = agent.upload_self_operated_materials(client, result.prepared, folder / '批次001', args.category_id, selected_spu_ids=ready)
    records, sources = exporter.collect_cached_records([folder], args.erp, owner_erp=args.owner_erp)
    projected = project_records(result.prepared.jobs, records)
    delivery = folder / '手动上传表' / str(time.time_ns())
    report = exporter.export_records(projected, delivery)
    report.update({'erp': args.erp, 'sourcePlans': sources, 'cacheMigration': migration, 'records': projected, 'elapsedSeconds': round(time.monotonic() - started, 3), 'imageUpload': json.loads(json.dumps(asdict(upload), default=str)) if upload else None, 'shortTitleWritePerformed': False, 'platformCompletionVerified': False, 'deliveryDirectory': str(delivery)})
    agent._save_state(delivery / '导出清单.json', report)
    agent._save_state(folder / '手动上传表/导出清单.json', report)
    return report

def run_resume(args, client=None):
    output = Path(args.output_dir).resolve()
    plan, snapshot = load_plan(output, args.erp, args.confirm_token)
    if args.confirm != 'GENERATE_AND_UPLOAD_IMAGES_ONLY':
        raise ValueError('requires the already-authorized generation and image-only scope')
    if not 1 <= args.batch_size <= 50 or (args.limit is not None and args.limit < 1):
        raise ValueError('invalid SPU batch size or limit')
    args.owner_erp = plan['ownerErp']
    progress_path = output / '.state/resume-progress.json'
    with agent._erp_execution_lock(output):
        progress = read_json(progress_path) if progress_path.exists() else {'segments': {}, 'completedSpuIds': []}
        completed = set(progress['completedSpuIds'])
        active = progress.get('activeSpuIds', [])
        deferred = progress.setdefault('deferredSegments', {})
        deferred_spus = {spu for item in deferred.values() for spu in item['failedSpuIds']}
        jobs = [job for job in snapshot.jobs if job.spu_id not in completed and job.spu_id not in active and (job.spu_id not in deferred_spus)]
        if args.limit is not None:
            jobs = jobs[:max(0, args.limit - len(active))]
        groups = [jobs[offset:offset + args.batch_size] for offset in range(0, len(jobs), args.batch_size)]
        if active:
            by_spu = {job.spu_id: job for job in snapshot.jobs}
            groups.insert(0, [by_spu[spu] for spu in active])
        client = client or agent.create_self_operated_erp_client(args)
        for selected in groups:
            load_plan(output, args.erp, args.confirm_token)
            identifiers = [job.spu_id for job in selected]
            progress['activeSpuIds'] = identifiers
            agent._save_state(progress_path, progress)
            key = agent._auto_maintain_plan_hash({'spuIds': identifiers})[:20]
            folder = output / 'segments' / key
            result = derive_result(snapshot, selected)
            plan_path = folder / '.state/self-operated-plan.json'
            if not plan_path.exists():
                agent.write_self_operated_plan(result, folder, erp=args.erp, owner_erp=args.owner_erp, target=','.join(sorted(identifiers)))
            else:
                saved = read_json(plan_path)
                previous = agent.load_self_operated_plan(folder, erp=args.erp, owner_erp=args.owner_erp, target=','.join(sorted(identifiers)), token=saved['confirmToken'])
                if asdict(previous) != asdict(result):
                    raise ValueError('derived segment scope changed')
            try:
                report = execute_segment(result, plan['cachedRecords'], folder, args, client, plan['cacheDirectories'])
            except _protected_core.ProtectedCoreError:
                raise
            except Exception as error:
                progress['status'] = 'paused'
                progress['stopType'] = type(error).__name__
                progress['currentSegment'] = key
                agent._save_state(progress_path, progress)
                raise
            progress['segments'][key] = {'directory': str(folder), 'elapsedSeconds': report['elapsedSeconds'], 'materialRows': report['materialRows'], 'shortTitleRows': report['shortTitleRows'], 'reportSha256': sha(folder / '手动上传表/导出清单.json')}
            failed = {item['spuId'] for item in report['incomplete']}
            upload_path = folder / '批次001/.state/upload-ledger.json'
            upload_entries = read_json(upload_path).get('files', {}).values() if upload_path.exists() else []
            new_unknown = any((item.get('status') in ('uploading', 'unconfirmed', 'submitted') and (not item.get('sourceLedgerSha256')) for item in upload_entries))
            may_defer = getattr(args, 'defer_incomplete', False) and (not new_unknown)
            if not failed:
                completed.update(identifiers)
                progress['activeSpuIds'] = []
                deferred.pop(key, None)
            elif may_defer:
                completed.update(set(identifiers) - failed)
                progress['activeSpuIds'] = []
                deferred[key] = {'spuIds': identifiers, 'failedSpuIds': sorted(failed), 'directory': str(folder)}
            progress['completedSpuIds'] = sorted(completed)
            progress['status'] = 'paused-with-incomplete' if failed else 'checkpoint-complete'
            agent._save_state(progress_path, progress)
            deferred_count = len({spu for item in deferred.values() for spu in item['failedSpuIds']})
            processed_count = len(completed) + deferred_count
            failure_stop = processed_count >= 10 and deferred_count / processed_count > 0.2
            if failed and (not may_defer or failure_stop):
                break
        return {key: value for key, value in progress.items() if key != 'completedSpuIds'} | {'completedSpus': len(completed), 'remainingSpus': len(snapshot.jobs) - len(completed), 'deferredSpus': len({spu for item in deferred.values() for spu in item['failedSpuIds']}), 'platformCompletionVerified': False}
