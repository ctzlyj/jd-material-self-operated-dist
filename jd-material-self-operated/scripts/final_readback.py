from copy import copy
from pathlib import Path
import time
import direct_failures
import direct_reconcile as reconcile
import direct_resume as resume
import jd_material_agent as core
import manual_resume as manual

def report_hashes(progress):
    return {key: item['reportSha256'] for key, item in progress['segments'].items()}

def finalize(args, client=None):
    import upload_quarantine
    output = Path(args.output_dir).resolve()
    plan, snapshot = resume.load_direct(output, args.erp, args.confirm_token)
    progress_path = output / '.state/direct-progress.json'
    marker_path = output / '.state/final-readback.json'
    with core._erp_execution_lock(output):
        previous_marker = None
        progress = manual.read_json(progress_path)
        resume.validate_progress(output, progress, {job.spu_id for job in snapshot.jobs})
        if progress.get('activeSpuIds') or progress.get('workerRunning'):
            raise ValueError('finish in-flight writes before final readback')
        sources = {}
        for segment in progress['segments'].values():
            batch = Path(segment['directory']) / '批次001'
            direct_failures.check_unknown_writes(batch)
            state_path = batch / '.state/task.json'
            sources[str(state_path)] = manual.sha(state_path)
            report = manual.checked_json(Path(segment.get('reportPath', Path(segment['directory']) / 'direct-result.json')), segment['reportSha256'])
            if report.get('readbackDeferred'):
                if report.get('deferredStateSha256') != manual.sha(state_path):
                    raise ValueError('deferred state changed before final readback')
                if report.get('deferredDesiredSha256') and manual.sha(batch / '.state/direct-desired.json') != report['deferredDesiredSha256']:
                    raise ValueError('deferred desired payload changed before final readback')
        if marker_path.exists():
            marker = manual.read_json(marker_path)
            if marker['reportHashes'] == report_hashes(progress) and marker['stateHashes'] == sources:
                manual.checked_json(Path(marker['evidence']['path']), marker['evidence']['sha256'])
                if not getattr(args, 'refresh_readback', False):
                    return {**marker['summary'], 'reused': True}
            if getattr(args, 'refresh_readback', False):
                archived = output / '.state/final-readback-history' / f'{time.time_ns()}.json'
                archived.parent.mkdir(parents=True, exist_ok=True)
                archived.write_bytes(marker_path.read_bytes())
                previous_marker = {'path': str(archived), 'sha256': manual.sha(archived)}
        quarantined = upload_quarantine.load(output)
        selected = set(progress['deferredSpuIds']) - set(quarantined)
        options = copy(args)
        options.owner_erp = plan['ownerErp']
        options.include_completed = False
        options.spu_ids = sorted(selected) if selected else None
        if selected or not quarantined:
            result = reconcile.audit_deferred(options, client=client)
            evidence_path = Path(result['report'])
        else:
            evidence_path = output / 'read-only-reconciliations' / str(time.time_ns()) / 'readback.json'
            core._save_state(evidence_path, {'jobs': {}, 'writesPerformed': False, 'directPlanSha256': manual.sha(output / '.state/direct-plan.json'), 'quarantinedSpus': sorted(quarantined), 'reason': 'no non-quarantined deferred work'})
        evidence = manual.read_json(evidence_path)
        if evidence.get('writesPerformed') is not False or set(evidence['jobs']) != selected or evidence['directPlanSha256'] != manual.sha(output / '.state/direct-plan.json'):
            raise ValueError('final readback evidence scope changed')
        for source, digest in sources.items():
            if manual.sha(Path(source)) != digest:
                raise ValueError('source state changed during final readback')
        proof = {'path': str(evidence_path), 'sha256': manual.sha(evidence_path)}
        previous_progress = output / '.state/progress-history' / f'{time.time_ns()}-before-final-readback.json'
        previous_progress.parent.mkdir(parents=True, exist_ok=True)
        previous_progress.write_bytes(progress_path.read_bytes())
        for key, segment in progress['segments'].items():
            relevant = selected & (set(segment['completed']) | set(segment['deferred']))
            if not relevant:
                continue
            folder = Path(segment['directory'])
            original_path = Path(segment.get('reportPath', folder / 'direct-result.json'))
            report = manual.checked_json(original_path, segment['reportSha256'])
            report['previousReport'] = {'path': str(original_path), 'sha256': segment['reportSha256']}
            for spu in relevant:
                observed = evidence['jobs'][spu]
                report['jobs'][spu].update({key: value for key, value in observed.items() if key != 'materialChecks'})
                report['jobs'][spu].update(awaitingFinalReadback=False, awaitingReadback=False)
            report.update(readbackDeferred=False, finalReadback=proof)
            report['materialChecks'] = [check for check in report.get('materialChecks', []) if check['spuId'] not in relevant]
            report['materialChecks'].extend((check for spu in relevant for check in evidence['jobs'][spu]['materialChecks']))
            updated = resume.save_report(folder, report)
            segment.update(reportPath=updated['receiptPath'], reportSha256=manual.sha(Path(updated['receiptPath'])), completed=sorted((spu for spu, item in updated['jobs'].items() if item['complete'])), deferred=sorted((spu for spu, item in updated['jobs'].items() if not item['complete'])))
        resume.refresh_progress(progress)
        accounted = set(progress['completedSpuIds']) | set(progress['deferredSpuIds']) | set(progress.get('heldSpus', {}))
        status = 'scope-verified' if len(progress['completedSpuIds']) == len(snapshot.jobs) else 'finished-with-failures' if len(accounted) == len(snapshot.jobs) else 'checkpoint'
        progress.update(status=status, finalReadback=proof, updatedAt=time.time())
        core._save_state(progress_path, progress)
        direct_failures.export_failures(output, progress, snapshot.jobs, args.erp)
        summary = {'status': status, 'completedSpus': len(progress['completedSpuIds']), 'deferredSpus': len(progress['deferredSpuIds']), 'remainingSpus': len(snapshot.jobs) - len(progress['completedSpuIds']), 'finalReadback': proof, 'writesPerformed': False, 'scoreRefreshed': False}
        marker = {'reportHashes': report_hashes(progress), 'stateHashes': sources, 'evidence': proof, 'summary': summary}
        if previous_marker:
            marker['previousMarker'] = previous_marker
        core._save_state(marker_path, marker)
        return summary
