import protected_core as _protected_core
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
import jd_material_agent as core
import manual_resume as manual
import direct_binding as binding
import direct_failures
import direct_resume as direct

def group_key(jobs):
    return core._auto_maintain_plan_hash({'spuIds': [job.spu_id for job in jobs]})[:20]

def reserved_groups(output, plan, jobs):
    path = Path(output) / '.state/title-only-plan.json'
    if not path.exists():
        return []
    payload = manual.read_json(path)
    digest = payload.pop('sha256')
    if digest != core._auto_maintain_plan_hash(payload) or payload['directPlanSha256'] != manual.sha(Path(output) / '.state/direct-plan.json') or payload['directPlanToken'] != plan['confirmToken']:
        raise ValueError('title reservation hash or original plan changed')
    by_spu = {job.spu_id: job for job in jobs}
    selected = [spu for group in payload['groups'] for spu in group]
    if len(selected) != len(set(selected)) or not set(selected) <= set(by_spu) or any((not by_spu[spu].short_title_sku_ids for spu in selected)) or any((not 1 <= len(group) <= 50 for group in payload['groups'])):
        raise ValueError('title reservation exceeds pending field scope')
    return [[by_spu[spu] for spu in group] for group in payload['groups']]

def reserve_groups(output, plan, jobs, progress, batch_size, first_limit):
    path = Path(output) / '.state/title-only-plan.json'
    if not path.exists():
        excluded = set(progress['completedSpuIds']) | set(progress['deferredSpuIds']) | set(progress.get('activeSpuIds', [])) | set(progress.get('heldSpus', {}))
        selected = [job for job in jobs if job.short_title_sku_ids and job.spu_id not in excluded]
        first_size = min(batch_size, first_limit) if first_limit else batch_size
        groups = [selected[:first_size]] if selected else []
        groups.extend((selected[offset:offset + batch_size] for offset in range(first_size, len(selected), batch_size)))
        payload = {'directPlanSha256': manual.sha(Path(output) / '.state/direct-plan.json'), 'directPlanToken': plan['confirmToken'], 'fields': ['shortTitles'], 'groups': [[job.spu_id for job in group] for group in groups]}
        core._save_state(path, {**payload, 'sha256': core._auto_maintain_plan_hash(payload)})
    return reserved_groups(output, plan, jobs)

def pending_full_groups(output, plan, jobs, progress):
    accounted = set(progress['completedSpuIds']) | set(progress['deferredSpuIds']) | set(progress.get('activeSpuIds', []))
    pending = []
    for group in reserved_groups(output, plan, jobs):
        identifiers = {job.spu_id for job in group}
        if identifiers & accounted:
            if not identifiers <= accounted:
                raise ValueError('partially accounted title reservation would split canonical receipts')
            continue
        pending.append(group)
    return pending

def generate_titles(jobs, batch, model, concurrency):
    path = Path(batch) / '.state/task.json'
    state = manual.read_json(path)
    pending = {}
    for job in jobs:
        cached = state['jobs'][job.spu_id].get('short_titles', {})
        rows = [(sku, title) for sku, title in job.skus if sku in job.short_title_sku_ids and (not core.valid_short_title(cached.get(sku)))]
        if rows:
            pending[job.spu_id] = rows
    if not pending:
        return {}
    client = model.get()
    failures = {}
    owners = {sku: spu for spu, rows in pending.items() for sku, _ in rows}
    rows = [row for group in pending.values() for row in group]
    if len(owners) != len(rows):
        raise ValueError('duplicate SKU across title generation groups')
    with ThreadPoolExecutor(max_workers=max(1, min(50, concurrency))) as executor:
        futures = {executor.submit(client.short_titles, rows[offset:offset + 50]): {sku for sku, _ in rows[offset:offset + 50]} for offset in range(0, len(rows), 50)}
        for future in as_completed(futures):
            allowed = futures[future]
            try:
                values = future.result()
                if set(values) != allowed or not all((core.valid_short_title(value) for value in values.values())):
                    raise ValueError('generated title scope or format mismatch')
                for sku, title in values.items():
                    state['jobs'][owners[sku]].setdefault('short_titles', {})[sku] = title
                core._save_state(path, state)
            except _protected_core.ProtectedCoreError:
                raise
            except Exception as error:
                failures.update({owners[sku]: str(error) for sku in allowed})
    if getattr(client, 'quota_exhausted', False) is True or getattr(client, 'authentication_failed', False) is True:
        raise RuntimeError('text model quota or authentication pause; cached titles preserved')
    return failures

def execute_title_segment(result, plan, folder, args, client, model, original_values):
    started = time.monotonic()
    batch = folder / '批次001'
    client.select_shop()
    if client.expected_erp != args.erp or client.owner_erp != plan['ownerErp']:
        raise ValueError('authenticated ERP changed')
    client.verify_product_scope(result.prepared.jobs)
    manual.seed_cache(result.prepared, plan['cachedRecords'], batch, plan['cacheDirectories'])
    direct.migrate_writes(result.prepared.jobs, plan['cachedRecords'], batch)
    failures = generate_titles(result.prepared.jobs, batch, model, args.spu_concurrency)
    state = manual.read_json(batch / '.state/task.json')
    desired = {sku: title for job in result.prepared.jobs for sku, title in state['jobs'][job.spu_id].get('short_titles', {}).items() if sku in job.short_title_sku_ids and core.valid_short_title(title)}
    direct.freeze_requests(batch, {'materials': [], 'shortTitles': desired})
    payload = {'directPlanToken': args.confirm_token, 'erp': args.erp, 'requests': [], 'shortTitles': desired, 'shortTitlesBefore': {sku: original_values[sku] for sku in desired}, 'skuIds': [sku for job in result.prepared.jobs for sku in job.sku_ids]}
    attempt = batch / '.state/write-attempts' / str(time.time_ns())
    token = binding.confirm_self_operated_writes(attempt, payload, '')
    binding.confirm_self_operated_writes(attempt, payload, token)
    client.select_shop()
    client.verify_product_scope(result.prepared.jobs)
    result_titles = direct.submit_direct_titles(client, result.prepared.jobs, desired, batch, original_values)
    direct_failures.check_unknown_writes(batch)
    audit = batch / '.state/short-title-write.json'
    return {'spuIds': [job.spu_id for job in result.prepared.jobs], 'skuIds': payload['skuIds'], 'shortTitles': result_titles, 'generationFailures': failures, 'imageRequests': 0, 'materialCompletionEstablished': False, 'elapsedSeconds': round(time.monotonic() - started, 3), 'titleAuditSha256': manual.sha(audit) if audit.exists() else None}

def run_titles(args, client=None):
    output = Path(args.output_dir).resolve()
    plan, snapshot = direct.load_direct(output, args.erp, args.confirm_token)
    if args.confirm != 'GENERATE_UPLOAD_BIND_AND_VERIFY':
        raise ValueError('explicit direct authorization required')
    if not 1 <= args.batch_size <= 50 or (args.limit is not None and args.limit < 1):
        raise ValueError('invalid batch size or limit')
    args.owner_erp = plan['ownerErp']
    with core._erp_execution_lock(output):
        main = manual.read_json(output / '.state/direct-progress.json')
        direct.validate_progress(output, main, {job.spu_id for job in snapshot.jobs})
        if main.get('activeSpuIds'):
            raise ValueError('finish or reconcile active direct segment before title-only work')
        groups = reserve_groups(output, plan, snapshot.jobs, main, args.batch_size, args.limit)
        pending = {group_key(group) for group in pending_full_groups(output, plan, snapshot.jobs, main)}
        path = output / '.state/title-only-progress.json'
        progress = manual.read_json(path) if path.exists() else {'reports': {}}
        for key, record in progress['reports'].items():
            expected = output / 'segments' / key / 'title-results'
            receipt = Path(record['path']).resolve()
            if not receipt.is_relative_to(expected) or key not in {group_key(group) for group in groups}:
                raise ValueError('title progress receipt scope changed')
            report = manual.checked_json(receipt, record['sha256'])
            if report['spuIds'] != next(([job.spu_id for job in group] for group in groups if group_key(group) == key)):
                raise ValueError('title progress contradicts persisted scope')
        original = manual.derive_result(snapshot, snapshot.jobs)
        original_values = direct.expected_titles(snapshot)
        model = direct.SharedModel(args, output)
        processed = 0
        try:
            client = client or binding.create_direct_client(args)
            for group in groups:
                key = group_key(group)
                if key in progress['reports'] or key not in pending:
                    continue
                if direct.pause_requested(output) or (args.limit is not None and processed + len(group) > args.limit):
                    progress['status'] = 'checkpoint'
                    break
                folder = output / 'segments' / key
                result = direct.subset_result(original, group)
                target = ','.join(sorted((job.spu_id for job in group)))
                plan_path = folder / '.state/self-operated-plan.json'
                if not plan_path.exists():
                    core.write_self_operated_plan(result, folder, erp=args.erp, owner_erp=args.owner_erp, target=target)
                else:
                    saved = manual.read_json(plan_path)
                    previous = core.load_self_operated_plan(folder, erp=args.erp, owner_erp=args.owner_erp, target=target, token=saved['confirmToken'])
                    if asdict(previous) != asdict(result):
                        raise ValueError('title canonical segment scope changed')
                progress.update({'activeSpuIds': [job.spu_id for job in group], 'pid': os.getpid(), 'workerRunning': True, 'status': 'running', 'updatedAt': time.time()})
                core._save_state(path, progress)
                report = execute_title_segment(result, plan, folder, args, client, model, original_values)
                receipt = folder / 'title-results' / f'{time.time_ns()}.json'
                core._save_state(receipt, report)
                progress['reports'][key] = {'path': str(receipt), 'sha256': manual.sha(receipt)}
                progress.update({'activeSpuIds': [], 'updatedAt': time.time()})
                core._save_state(path, progress)
                processed += len(group)
                print(json.dumps({'titleSegment': key, **report['shortTitles'], 'elapsedSeconds': report['elapsedSeconds']}, ensure_ascii=False), flush=True)
            else:
                progress['status'] = 'titles-attempted-materials-still-pending'
        except _protected_core.ProtectedCoreError:
            raise
        except Exception as error:
            progress.update({'status': 'paused-error', 'error': str(error)})
            raise
        finally:
            model.close()
            progress.update({'workerRunning': False, 'updatedAt': time.time()})
            core._save_state(path, progress)
        return {'status': progress['status'], 'processedSpus': processed, 'fullSpuCompletionAdded': 0}
