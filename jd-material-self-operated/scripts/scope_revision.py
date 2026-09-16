from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import time
import direct_failures
import jd_material_agent as core
import manual_resume as manual

def project(result, inventory, rows, erp):
    jobs = {job.spu_id: job for job in result.prepared.jobs}
    native = inventory.get('rows', [])
    if inventory.get('loginErp') != erp:
        raise ValueError('current SKU ERP mismatch')
    if inventory.get('page') != 1 or inventory.get('total') != len(jobs) or len(native) != len(jobs) or ({str(row.get('spuId')) for row in native} != set(jobs)):
        raise ValueError('current product inventory is incomplete')
    observed = {spu: set() for spu in jobs}
    seen = set()
    for row in rows:
        spu, sku = (str(row.get('productId', '')), str(row.get('skuId', '')))
        if spu not in jobs or not sku.isdecimal() or sku in seen:
            raise ValueError('unexpected or duplicate current SKU')
        observed[spu].add(sku)
        seen.add(sku)
    for row in native:
        spu = str(row['spuId'])
        if not observed[spu] or row.get('declaredSkuCount') != len(observed[spu]):
            raise ValueError('current SKU inventory is incomplete or empty')
        if not observed[spu] <= set(jobs[spu].sku_ids):
            raise ValueError('new SKU exceeds frozen scope; reduction authorization cannot expand it')
    revised = []
    for job in jobs.values():
        retained = observed[job.spu_id]
        skus = tuple((pair for pair in job.skus if pair[0] in retained))
        revised.append(replace(job, sku_ids=tuple((sku for sku in job.sku_ids if sku in retained)), skus=skus, short_title_sku_ids=tuple((sku for sku in job.short_title_sku_ids if sku in retained)), representative_sku_id=job.representative_sku_id if job.representative_sku_id in retained else skus[0][0]))
    kept_rows = tuple((row for row in result.prepared.rows if row.sku_id in seen))
    if len(kept_rows) != len(seen):
        raise ValueError('current SKU rows differ from frozen source')
    return replace(result, prepared=replace(result.prepared, jobs=tuple(revised), rows=kept_rows, original_rows=len(kept_rows)))

def proof(path):
    return {'path': str(path), 'sha256': manual.sha(path)}

def frozen_result(folder):
    path = Path(folder) / '.state/self-operated-plan.json'
    saved = manual.read_json(path)
    return core.load_self_operated_plan(Path(folder), erp=saved['erp'], owner_erp=saved['ownerErp'], target=saved['target'], token=saved['confirmToken'])

def load(folder, original=None, *, expected=None, activate=False):
    folder = Path(folder).resolve()
    pointer_path = folder / '.state/scope-revision.json'
    if not pointer_path.exists():
        if expected:
            raise ValueError('scope revision missing')
        return (original, None)
    pointer = manual.read_json(pointer_path)
    if expected is not None and expected != pointer:
        raise ValueError('scope revision changed after report')
    path = Path(pointer['path']).resolve()
    if not path.is_relative_to(folder / '.state/scope-revisions'):
        raise ValueError('scope revision path escaped segment')
    revision = manual.checked_json(path, pointer['sha256'])
    plan_path = folder / '.state/self-operated-plan.json'
    direct_path = folder.parent.parent / '.state/direct-plan.json'
    for key, source in (('sourcePlan', plan_path), ('directPlan', direct_path)):
        if Path(revision[key]['path']).resolve() != source:
            raise ValueError('scope revision source path changed')
        manual.checked_json(source, revision[key]['sha256'])
    original = original or frozen_result(folder)
    if core._auto_maintain_plan_hash(asdict(original)) != revision['originalResultHash']:
        raise ValueError('scope revision original result changed')
    revised = project(original, revision['inventory'], revision['skuRows'], revision['erp'])
    if core._task_signature(revised.prepared) != revision['effectiveSignature']:
        raise ValueError('scope revision effective scope changed')
    if activate and revision.get('stateTransition'):
        transition = revision['stateTransition']
        manual.checked_json(transition['before']['path'], transition['before']['sha256'])
        after = manual.checked_json(transition['after']['path'], transition['after']['sha256'])
        if after['task_signature'] != revision['effectiveSignature']:
            raise ValueError('scope revision state signature changed')
        state_path = folder / '批次001/.state/task.json'
        current = manual.read_json(state_path)
        if manual.sha(state_path) == transition['before']['sha256']:
            core._save_state(state_path, after)
        elif current.get('task_signature') != after['task_signature']:
            raise ValueError('scope revision cache changed before activation')
    return (revised, pointer)

def ensure_unwritten(folder, previous, revised, records):
    changed = {old.spu_id: old for old, new in zip(previous.prepared.jobs, revised.prepared.jobs) if old.sku_ids != new.sku_ids}
    batch = Path(folder) / '批次001'
    direct_failures.check_unknown_writes(batch)
    sources = {batch / '.state/task.json'}
    sources.update((Path(path) for record in records if record['spuId'] in changed for path in record.get('sourceFiles', [])))
    for source in sources:
        state = manual.read_json(source) if source.exists() else {}
        for spu in changed:
            item = state.get('jobs', {}).get(spu, {})
            if item.get('material_submission_intents') or item.get('material_submission_receipts'):
                raise ValueError('cannot revise a written scope; reconcile original receipts first')
        title_path = source.with_name('short-title-write.json')
        if title_path.exists():
            titles = manual.read_json(title_path)
            identifiers = {sku for job in changed.values() for sku in job.sku_ids}
            if any((identifiers & set(titles.get(key, {})) for key in ('submittedTitles', 'unconfirmedTitles', 'rejectedTitles'))):
                raise ValueError('cannot revise a written scope; preserve title receipts')
    desired_path = batch / '.state/direct-desired.json'
    if desired_path.exists():
        desired = manual.read_json(desired_path)['payload']
        identifiers = {sku for job in changed.values() for sku in job.sku_ids}
        if any((item['spuId'] in changed for item in desired['materials'])) or identifiers & set(desired['shortTitles']):
            raise ValueError('cannot revise a written scope with frozen requests')

def prepare(folder, original, args, client, records):
    previous, pointer = load(folder, original, activate=True)
    if not getattr(args, 'current_visible_skus', False):
        client.verify_product_scope(previous.prepared.jobs)
        return (previous, pointer)
    identifiers = [job.spu_id for job in previous.prepared.jobs]
    inventory = client.scoped_inventory_page(identifiers)
    rows = client.short_title_rows(identifiers)
    revised = project(previous, inventory, rows, args.erp)
    if asdict(revised) == asdict(previous):
        return (previous, pointer)
    ensure_unwritten(folder, previous, revised, records)
    root = Path(folder) / '.state/scope-revisions' / str(time.time_ns())
    root.mkdir(parents=True)
    state_path = Path(folder) / '批次001/.state/task.json'
    transition = None
    if state_path.exists():
        state = manual.read_json(state_path)
        if state.get('task_signature') != core._task_signature(previous.prepared):
            raise ValueError('scope revision cache signature mismatch')
        archived = root / 'task-before.json'
        archived.write_bytes(state_path.read_bytes())
        after = deepcopy(state)
        after['task_signature'] = core._task_signature(revised.prepared)
        for job in revised.prepared.jobs:
            item = after['jobs'].get(job.spu_id, {})
            item['short_titles'] = {sku: title for sku, title in item.get('short_titles', {}).items() if sku in job.short_title_sku_ids}
        after_path = root / 'task-after.json'
        core._save_state(after_path, after)
        transition = {'before': proof(archived), 'after': proof(after_path)}
    revision = {'erp': args.erp, 'ownerErp': args.owner_erp, 'authorization': 'current-visible-sku-reduction', 'sourcePlan': proof(Path(folder) / '.state/self-operated-plan.json'), 'directPlan': proof(Path(args.output_dir).resolve() / '.state/direct-plan.json'), 'originalResultHash': core._auto_maintain_plan_hash(asdict(original)), 'effectiveSignature': core._task_signature(revised.prepared), 'inventory': inventory, 'skuRows': rows, 'previousRevision': pointer, 'stateTransition': transition, 'changes': [{'spuId': old.spu_id, 'originalSkuIds': list(old.sku_ids), 'currentSkuIds': list(new.sku_ids), 'removedSkuIds': sorted(set(old.sku_ids) - set(new.sku_ids))} for old, new in zip(original.prepared.jobs, revised.prepared.jobs) if old.sku_ids != new.sku_ids]}
    path = root / 'revision.json'
    core._save_state(path, revision)
    core._save_state(Path(folder) / '.state/scope-revision.json', proof(path))
    return load(folder, original, activate=True)
