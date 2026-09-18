import csv
from pathlib import Path
import re
import jd_material_agent as core
import manual_resume as manual

def job_failure_reasons(job, *, upload_failures, preflight_failures, title_audit):
    reasons = [str(reason) for reason in upload_failures if re.search('(?<!\\d)' + re.escape(job.spu_id) + '(?!\\d)', str(reason))]
    reasons.extend((str(item['reason']) for item in preflight_failures if item['spuId'] == job.spu_id))
    rejected = title_audit.get('rejectedTitles', {})
    reasons.extend((f"SKU {sku}: {rejected[sku].get('reason') or 'short-title rejected'}" for sku in job.short_title_sku_ids if sku in rejected))
    return list(dict.fromkeys(reasons))

def check_unknown_writes(batch, *, uploads_only=False):
    import upload_quarantine
    quarantined = upload_quarantine.for_batch(batch)
    held_names = {name for item in quarantined.values() for name in item['fileNames']}
    folder = Path(batch) / '.state'
    ledger = folder / 'upload-ledger.json'
    if ledger.exists():
        entries = [item for name, item in manual.read_json(ledger).get('files', {}).items() if name not in held_names]
        if any((item.get('status') in ('uploading', 'unconfirmed', 'submitted') and (not item.get('sourceLedgerSha256')) for item in entries)):
            raise RuntimeError('unconfirmed image upload; reconcile without replay')
    if uploads_only:
        return
    state = folder / 'task.json'
    if state.exists() and any((item.get('material_submission_intents') for item in manual.read_json(state).get('jobs', {}).values())):
        raise RuntimeError('unknown material binding receipt; reconcile without replay')
    titles = folder / 'short-title-write.json'
    if titles.exists() and manual.read_json(titles).get('unconfirmedTitles'):
        raise RuntimeError('unconfirmed short-title receipt; reconcile without replay')

def export_failures(output, progress, jobs, erp):
    import upload_quarantine
    output = Path(output)
    evidence = {}
    for segment in progress['segments'].values():
        path = Path(segment.get('reportPath', Path(segment['directory']) / 'direct-result.json'))
        report = manual.checked_json(path, segment['reportSha256'])
        for spu, item in report['jobs'].items():
            if item['complete']:
                continue
            checks = [check for check in report.get('materialChecks', []) if check['spuId'] == spu]
            reasons = [str(item.get('generationError') or '')]
            reasons.extend(item.get('failureReasons', []))
            reasons.extend((str(check.get('reason') or check.get('auditStatus', '')) for check in checks if not check.get('persisted')))
            if not item.get('titlesVerified', True):
                reasons.append('short-title not verified; see source receipt')
            if spu in report.get('queryFailures', {}):
                reasons.append(str(report['queryFailures'][spu]))
            evidence[spu] = {'category': 'awaiting-final-readback' if item.get('awaitingFinalReadback') else 'awaiting-readback' if item.get('awaitingReadback') else 'failed', 'reason': '; '.join((reason for reason in reasons if reason)) or 'incomplete material; see source receipt', 'sourcePath': str(path), 'sourceSha256': segment['reportSha256']}
    for spu, item in progress.get('heldSpus', {}).items():
        evidence.setdefault(spu, {'category': item.get('category', 'skipped-previous-image-failure'), 'reason': item['reason'], 'sourcePath': item['path'], 'sourceSha256': item['sha256']})
    for spu in progress.get('activeSpuIds', []):
        evidence.setdefault(spu, {'category': 'interrupted-unverified', 'reason': progress.get('error', 'interrupted'), 'sourcePath': '', 'sourceSha256': ''})
    completed = set(progress['completedSpuIds'])
    for spu, item in upload_quarantine.load(output).items():
        if spu in completed:
            raise ValueError('quarantined SPU cannot be marked complete')
        evidence[spu] = {'category': 'quarantined-unknown-upload', 'reason': upload_quarantine.REASON, 'sourcePath': item['evidence']['path'], 'sourceSha256': item['evidence']['sha256']}
    entries = [{'spuId': job.spu_id, 'skuIds': list(job.sku_ids), **evidence[job.spu_id]} for job in jobs if job.spu_id not in completed and job.spu_id in evidence]
    accounted = completed | set(evidence)
    report = {'erp': erp, 'status': progress['status'], 'completedSpus': len(completed), 'unprocessedSpus': sum((job.spu_id not in accounted for job in jobs)), 'entries': entries, 'scopeSize': len(jobs), 'scoreRefreshed': False}
    core._save_state(output / '.state/failure-index.json', report)
    destination = output / '失败与待核实SKU清单.csv'
    temporary = destination.with_suffix('.csv.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['SPUID', 'SKUID', '状态', '原因', '证据文件', '证据SHA256'])
        for item in entries:
            for sku in item['skuIds']:
                values = [item['spuId'], sku, item['category'], item['reason'], item['sourcePath'], item['sourceSha256']]
                writer.writerow(["'" + str(value) if str(value).startswith(('=', '+', '-', '@', '\t', '\r')) else value for value in values])
    temporary.replace(destination)
    return report
