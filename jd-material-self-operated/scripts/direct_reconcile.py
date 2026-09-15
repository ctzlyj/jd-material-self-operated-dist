import argparse
from copy import copy
import json
from pathlib import Path
import time
import jd_material_agent as core
import direct_binding as binding
import direct_resume as resume
import manual_resume as manual

def evaluate_job(job, state, materials, title_rows):
    checks = []
    try:
        requests = binding.build_self_operated_binding_requests(job, state)
        checks = [resume.audit_request(request, materials, state) for request in requests]
        material_ok = all((item['persisted'] for item in checks))
    except ValueError:
        material_ok = False
    wanted = {sku: state.get('short_titles', {}).get(sku) for sku in job.short_title_sku_ids}
    rows = [row for row in title_rows if str(row.get('productId')) == job.spu_id]
    identifiers = [str(row['skuId']) for row in rows]
    membership = not wanted or (len(set(identifiers)) == len(identifiers) and set(identifiers) == set(job.sku_ids))
    observed = {str(row['skuId']): row.get('shortTitle') for row in rows if row.get('shortTitleKnown') is True}
    title_ok = membership and all((value and observed.get(sku) == value for sku, value in wanted.items()))
    return {'complete': material_ok and title_ok, 'materialVerified': material_ok, 'titlesVerified': title_ok, 'materialChecks': checks, 'verifiedTitleSkuIds': [sku for sku, value in wanted.items() if value and observed.get(sku) == value]}

def verified_title_rows(client, spu_ids, scope_rows):
    if not spu_ids:
        return []
    if scope_rows is None:
        return client.short_title_rows(spu_ids)
    if not isinstance(scope_rows, list):
        raise ValueError('invalid verified scope readback')
    selected = [row for row in scope_rows if str(row.get('productId')) in spu_ids]
    if {str(row['productId']) for row in selected} != set(spu_ids):
        raise ValueError('verified scope readback is missing a requested SPU')
    return selected

def audit_deferred(args, client=None):
    output = Path(args.output_dir).resolve()
    plan, snapshot = resume.load_direct(output, args.erp, args.confirm_token)
    progress_path = output / '.state/direct-progress.json'
    progress = manual.read_json(progress_path)
    resume.validate_progress(output, progress, {job.spu_id for job in snapshot.jobs})
    deferred = set(progress['deferredSpuIds'])
    jobs = [job for job in snapshot.jobs if job.spu_id in deferred]
    destination = output / 'read-only-reconciliations' / str(time.time_ns())
    states, sources = ({}, {})
    for segment in progress['segments'].values():
        folder = Path(segment['directory'])
        if not deferred.intersection(segment['deferred']):
            continue
        state_path = folder / '批次001/.state/task.json'
        state = manual.read_json(state_path)
        sources[str(state_path)] = manual.sha(state_path)
        sources[str(segment.get('reportPath', folder / 'direct-result.json'))] = segment['reportSha256']
        states.update({spu: item for spu, item in state['jobs'].items() if spu in deferred})
    options = copy(args)
    options.output_dir = output / 'read-only-client'
    options.owner_erp = plan['ownerErp']
    client = client or core.create_self_operated_erp_client(options)
    results, material_evidence, title_evidence = ({}, {}, [])
    for offset in range(0, len(jobs), 10):
        group = jobs[offset:offset + 10]
        client.select_shop()
        if client.expected_erp != args.erp or client.owner_erp != plan['ownerErp']:
            raise ValueError('read-only reconciliation ERP mismatch')
        scope_rows = client.verify_product_scope(group)
        material_jobs = [job for job in group if core._has_material_work(job)]
        materials, _, failures = binding._query_self_operated_binding_materials(client, material_jobs)
        title_spus = [job.spu_id for job in group if job.short_title_sku_ids]
        titles = verified_title_rows(client, title_spus, scope_rows)
        material_evidence.update(materials)
        title_evidence.extend(titles)
        for job in group:
            result = evaluate_job(job, states.get(job.spu_id, {}), materials, titles)
            if job.spu_id in failures:
                result.update({'complete': False, 'materialVerified': False, 'queryFailure': failures[job.spu_id]})
            results[job.spu_id] = result
    for path, digest in sources.items():
        manual.checked_json(path, digest)
    report = {'erp': args.erp, 'directPlanSha256': manual.sha(output / '.state/direct-plan.json'), 'sourceReceipts': sources, 'jobs': results, 'materialReadback': material_evidence, 'titleReadback': title_evidence, 'writesPerformed': False, 'progressModified': False, 'completedSpuIds': [spu for spu, item in results.items() if item['complete']], 'remainingSpuIds': [spu for spu, item in results.items() if not item['complete']]}
    core._save_state(destination / 'readback.json', report)
    return {'report': str(destination / 'readback.json'), 'completedSpuIds': report['completedSpuIds'], 'remainingSpuIds': report['remainingSpuIds'], 'writesPerformed': False, 'progressModified': False}

def main():
    parser = argparse.ArgumentParser(description='Read-only exact reconciliation of deferred direct tasks')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--erp', required=True)
    parser.add_argument('--confirm-token', required=True)
    parser.add_argument('--webcli-profile')
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    print(json.dumps(audit_deferred(args), ensure_ascii=False, indent=2))
if __name__ == '__main__':
    main()
