import protected_core as _protected_core
from dataclasses import asdict, dataclass
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from types import SimpleNamespace
import uuid
import jd_material_agent as core
import direct_binding as binding
import direct_resume
import manual_resume as manual
AUTHORIZATION = 'GENERATE_UPLOAD_BIND_AND_VERIFY'
ORIGIN = 'fresh-owned-erp-v1'

def protected_erp():
    if not Path(__file__).with_name('protected-settings.json').is_file():
        return None
    try:
        result = subprocess.run(['node', str(Path(__file__).with_name('first_use_identity.mjs'))], capture_output=True, timeout=70, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        reply = json.loads(result.stdout)
        if result.returncode or reply.get('ok') is not True or (not isinstance(reply.get('erp'), str)):
            raise ValueError('ERP identity unavailable')
        return reply['erp']
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise ValueError('protected ERP identity unavailable; check HiOffice login') from error

@dataclass(frozen=True)
class FreshScope:
    path: Path
    queue: dict
    jobs: tuple

def validate_discovery(result):
    summary = result.summary
    failed = set(result.failed_spus)
    overlap = failed & {job.spu_id for job in result.prepared.jobs}
    isolated = bool(failed) and summary.get('paginationComplete') is True and (summary.get('discoveryScope') in {'full', 'selected', 'target'}) and (summary.get('incompleteSpus') == len(failed)) and (not overlap)
    if overlap or summary.get('paginationComplete') is False or (not result.safe_to_continue and (not isolated)):
        raise ValueError('native discovery is incomplete or failed scope overlaps writable jobs')

def final_report(output, result, erp):
    source = output / '.state/self-operated-plan.json'
    plan = manual.read_json(output / '.state/direct-plan.json')
    payload = manual.checked_json(source, plan['origin']['sha256'])
    discovery = payload['result']
    failures = []
    for spu in discovery['failed_spus']:
        rows = [row for row in discovery['report_rows'] if row['spuId'] == spu]
        failures.append({'spuId': spu, 'skuIds': sorted({row['skuId'] for row in rows if row.get('skuId')}) or [''], 'category': 'inspection-failed', 'reason': '; '.join(dict.fromkeys((row['inspectionError'] for row in rows if row.get('inspectionError')))) or 'inspection unavailable; SKU scope unknown', 'sourcePath': str(source), 'sourceSha256': plan['origin']['sha256']})
    index = output / '.state/failure-index.json'
    if index.exists():
        failures.extend(manual.read_json(index)['entries'])
    destination = output / '全流程失败与待核实SKU清单.csv'
    temporary = destination.with_suffix('.csv.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['SPUID', 'SKUID', '状态', '原因', '证据文件', '证据SHA256'])
        for item in failures:
            for sku in item['skuIds']:
                values = [item['spuId'], sku, item['category'], item['reason'], item['sourcePath'], item['sourceSha256']]
                writer.writerow(["'" + str(value) if str(value).startswith(('=', '+', '-', '@', '\t', '\r')) else value for value in values])
    temporary.replace(destination)
    report = {**result, 'erp': erp, 'ownerErp': erp, 'outputDir': str(output), 'inspectionFailedSpus': len(discovery['failed_spus']), 'failureList': str(destination), 'scoreRefreshed': False, 'scoreStatus': 'not-queried', 'auditStatus': 'not-final-verified'}
    if failures and report['status'] in {'scope-verified', 'nothing-to-maintain'}:
        report['status'] = 'finished-with-failures'
    core._save_state(output / 'first-use-summary.json', report)
    return report

def owned_client(args, client=None):
    service_erp = protected_erp()
    if service_erp is not None:
        if getattr(args, 'erp', None) and args.erp != service_erp:
            raise ValueError('requested ERP differs from the authenticated HiOffice ERP')
        args.erp = service_erp
    if client is None:
        timeout = float(getattr(args, 'timeout', 600))
        profile = getattr(args, 'webcli_profile', None)
        profiles = [profile] if profile else core._connected_webcli_profiles(timeout=min(timeout, 30))
        expected = core.cell_text(getattr(args, 'erp', ''))
        if len(profiles) > 1 and (not expected):
            raise ValueError('multiple browser identities; provide ERP or sign in to HiOffice')
        for profile in profiles:
            candidate = binding.WebcliSelfOperatedClient(profile=profile, session='jd-material-first-use-' + uuid.uuid4().hex, timeout=timeout)
            candidate.expected_erp = expected
            try:
                observed = candidate.select_shop()
            except _protected_core.ProtectedCoreError:
                raise
            except (ValueError, RuntimeError):
                continue
            if expected and observed.get('loginErp') != expected:
                continue
            client = candidate
            break
        if client is None:
            raise ValueError('no matching ERP browser login; connect Browser Bridge and sign in')
        client.product_bridge_path = Path(binding.__file__).with_name('self_operated_direct_product_bridge.js')
    identity = client.select_shop()
    erp = core.cell_text(identity.get('loginErp'))
    if not re.fullmatch('[A-Za-z0-9_.-]+', erp) or erp in {'.', '..'}:
        raise ValueError('authenticated ERP is unavailable')
    if getattr(args, 'erp', None) and args.erp != erp:
        raise ValueError('authenticated ERP does not match the requested ERP')
    if service_erp is not None and service_erp != erp:
        raise ValueError('HiOffice ERP differs from the business login ERP; no task was started')
    args.erp = args.owner_erp = erp
    client.expected_erp = client.owner_erp = erp
    output = core.self_operated_output(args).resolve()
    args.output_dir = output
    session = 'jd-material-erp-' + hashlib.sha256(str(output).encode()).hexdigest()[:16]
    if getattr(client, 'session', None) != session:
        client.session = session
        client.image_session = session + '-image-space'
        client.product_session = session + '-products'
        client.initialized = client.image_space_initialized = client.product_initialized = False
    return client

def discover_owned(client, args):
    if client.owner_erp != args.erp or client.expected_erp != args.erp:
        raise ValueError('own ERP filter is required before discovery')
    first = client.inventory_page(1, 1)
    if first.get('loginErp') != args.erp or first.get('scope') != 'explicit-owner-filter':
        raise ValueError('native inventory did not confirm the authenticated owner scope')
    if first.get('total') == 0 and first.get('rows') == []:
        prepared = core.PreparedSource('self-operated-live', 'owned-erp', (), (), (), 0, 0, 0)
        return core.SelfOperatedDiscoveryResult(prepared, {}, {}, (), (), {'scopeMode': 'owned-erp', 'inventorySpus': 0}, '', '', True)
    checkpoint = core.SelfOperatedCheckpointClient(client, args.output_dir)
    result = core.discover_authorized_self_operated_source(checkpoint, target_spu_id=getattr(args, 'target_spu_id', '') or '', target_spu_ids=getattr(args, 'target_spu_ids', None))
    result.summary.update({'scopeMode': 'owned-erp', 'ownerErp': args.erp})
    return result

def fresh_snapshot(plan):
    output = Path(plan['output']).resolve()
    origin = plan.get('origin', {})
    source = output / '.state/self-operated-plan.json'
    if plan.get('formatVersion') != 2 or origin.get('kind') != ORIGIN or Path(origin.get('path', '')).resolve() != source or (plan.get('ownerErp') != plan.get('erp')) or any((field in plan for field in ('handoff', 'handoffSha256', 'exclusionLedgerSha256'))):
        raise ValueError('invalid fresh owned-ERP plan; do not fabricate a legacy handoff')
    payload = manual.checked_json(source, origin['sha256'])
    result = core.load_self_operated_plan(output, erp=plan['erp'], owner_erp=plan['erp'], target=payload['target'], token=payload['confirmToken'])
    validate_discovery(result)
    source_reference = {'path': str(source), 'sha256': origin['sha256']}
    summary = {'remainingSpus': len(result.prepared.jobs), 'remainingSkus': len(result.prepared.rows), 'remainingTitleSkus': sum((len(job.short_title_sku_ids) for job in result.prepared.jobs))}
    return FreshScope(source, {'sourcePlan': source_reference, 'basis': ORIGIN, 'ownerErp': plan['erp'], 'summary': summary}, result.prepared.jobs)

def plan_new(args, client=None):
    client = owned_client(args, client)
    output = Path(args.output_dir)
    plan_path = output / '.state/direct-plan.json'
    with core._erp_execution_lock(output / '.first-use-planner'):
        if plan_path.exists():
            existing = manual.read_json(plan_path)
            if existing.get('formatVersion') != 2 or existing.get('origin', {}).get('kind') != ORIGIN:
                raise ValueError('existing legacy task retained; use its original continuation, not first use')
            plan, snapshot = direct_resume.load_direct(output, args.erp, existing['confirmToken'])
            if manual.read_json(snapshot.path)['target'] != core.self_operated_target(args):
                raise ValueError('existing first-use target scope differs; keep the original task directory')
            return {'status': 'dry-run-ready', 'erp': args.erp, 'ownerErp': args.erp, 'outputDir': str(output), 'confirmToken': plan['confirmToken'], 'summary': snapshot.queue['summary'], 'planReused': True}
        probe = core.selling_point_prompts('商品素材维护权限检查')
        if not isinstance(probe, tuple) or len(probe) != 2 or (not all((isinstance(item, str) and item for item in probe))):
            raise ValueError('protected core preflight returned an invalid result')
        source = output / '.state/self-operated-plan.json'
        if source.exists():
            payload = manual.read_json(source)
            result = core.load_self_operated_plan(output, erp=args.erp, owner_erp=args.erp, target=core.self_operated_target(args), token=payload['confirmToken'])
        else:
            result = discover_owned(client, args)
            validate_discovery(result)
            core.write_self_operated_plan(result, output, erp=args.erp, owner_erp=args.erp, target=core.self_operated_target(args))
        validate_discovery(result)
        records = manual.project_records(result.prepared.jobs, [{'spuId': job.spu_id, 'skuIds': list(job.sku_ids), 'urls': result.existing_materials.get(job.spu_id, {}).get('uploaded_urls', {}), 'sellingPoints': result.existing_materials.get(job.spu_id, {}).get('selling_points', [])} for job in result.prepared.jobs])
        payload = {'formatVersion': 2, 'variant': core.VARIANT_ID, 'version': core.SKILL_VERSION, 'erp': args.erp, 'ownerErp': args.erp, 'output': str(output), 'origin': {'kind': ORIGIN, 'path': str(source), 'sha256': manual.sha(source)}, 'cacheDirectories': [], 'cachePlans': [], 'sourceReceipts': {}, 'cachedRecords': records, 'jobs': [asdict(job) for job in result.prepared.jobs], 'delivery': 'api-binding', 'allowedWrites': ['image-space-files', 'material-fields-in-pending-scope', 'short-titles-in-pending-scope']}
        payload['confirmToken'] = 'DIRECT-' + core._auto_maintain_plan_hash(payload)
        core._save_state(plan_path, payload)
        snapshot = fresh_snapshot(payload)
        return {'status': 'dry-run-ready', 'erp': args.erp, 'ownerErp': args.erp, 'outputDir': str(output), 'confirmToken': payload['confirmToken'], 'summary': snapshot.queue['summary'], 'planReused': False}

def run_auto(args, client=None):
    if not getattr(args, 'plan_only', False) and getattr(args, 'confirm', '') != AUTHORIZATION:
        raise ValueError('explicit generation/upload/binding authorization is required')
    client = owned_client(args, client)
    output = Path(args.output_dir)
    with core._erp_execution_lock(output / '.first-use-driver'):
        reply = plan_new(args, client=client)
        if getattr(args, 'plan_only', False):
            return reply
        plan_path = output / '.state/direct-plan.json'
        digest = manual.sha(plan_path)
        state_path = output / '.state/first-use-progress.json'
        state = manual.read_json(state_path) if state_path.exists() else {'formatVersion': 1, 'erp': args.erp, 'planSha256': digest, 'stages': []}
        if state.get('erp') != args.erp or state.get('planSha256') != digest:
            raise ValueError('first-use progress differs from the frozen owner plan')
        if not reply['summary']['remainingSpus']:
            result = {'status': 'nothing-to-maintain', 'completedSpus': 0, 'remainingSpus': 0}
            state.update(result=result, updatedAt=time.time())
            core._save_state(state_path, state)
            return final_report(output, result, args.erp)
        if state.get('result', {}).get('status') in {'scope-verified', 'finished-with-failures'}:
            return final_report(output, {**state['result'], 'reused': True}, args.erp)
        options = SimpleNamespace(**vars(args))
        options.confirm_token = reply['confirmToken']
        options.confirm = AUTHORIZATION
        options.defer_incomplete = True
        options.cached_only = False
        options.repair_segment = None
        stages = [('pilot-one', 1), ('pilot-ten', 10), ('remaining', None)]
        result = state.get('result', {'status': 'checkpoint'})
        for name, limit in stages:
            if name in state['stages']:
                continue
            options.limit = limit
            try:
                result = direct_resume.run_direct(options, client=client)
            except _protected_core.ProtectedCoreError:
                raise
            except Exception as error:
                state.update(status='interrupted', error=str(error), updatedAt=time.time())
                core._save_state(state_path, state)
                final_report(output, {'status': 'interrupted'}, args.erp)
                raise
            state.update(result=result, status=result['status'], updatedAt=time.time())
            state.pop('error', None)
            if result['status'] in {'checkpoint', 'scope-verified', 'finished-with-failures'}:
                state['stages'].append(name)
            core._save_state(state_path, state)
            if result['status'] != 'checkpoint':
                break
        return final_report(output, result, args.erp)
