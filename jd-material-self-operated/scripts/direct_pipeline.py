import protected_core as _protected_core
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import time
import jd_material_agent as core
import manual_resume as manual

@contextmanager
def phase(folder, name):
    path = Path(folder) / '.state/phase-events' / f'{time.time_ns()}-{name}.json'
    started = time.monotonic()
    event = {'phase': name, 'startedAt': time.time(), 'status': 'running'}
    core._save_state(path, event)
    try:
        yield event
        event['status'] = 'completed'
    except _protected_core.ProtectedCoreError:
        raise
    except BaseException as error:
        event.update(status='interrupted', errorType=type(error).__name__)
        raise
    finally:
        event.update(endedAt=time.time(), elapsedSeconds=round(time.monotonic() - started, 3))
        core._save_state(path, event)

def freeze_segment(output, result, args):
    identifiers = [job.spu_id for job in result.prepared.jobs]
    key = core._auto_maintain_plan_hash({'spuIds': identifiers})[:20]
    folder = Path(output) / 'segments' / key
    path = folder / '.state/self-operated-plan.json'
    target = ','.join(sorted(identifiers))
    if path.exists():
        saved = manual.read_json(path)
        previous = core.load_self_operated_plan(folder, erp=args.erp, owner_erp=args.owner_erp, target=target, token=saved['confirmToken'])
        if asdict(previous) != asdict(result):
            raise ValueError('direct segment frozen scope changed')
    else:
        core.write_self_operated_plan(result, folder, erp=args.erp, owner_erp=args.owner_erp, target=target)
    return (key, folder)

def pending_group(output, progress, jobs, original, args):
    pending = progress.get('prefetchedSegment')
    if not pending:
        return []
    identifiers = pending['spuIds']
    selected = {job.spu_id: job for job in jobs}
    accounted = set(progress['completedSpuIds']) | set(progress['deferredSpuIds']) | set(progress.get('activeSpuIds', []))
    if not identifiers or len(identifiers) > 50 or len(set(identifiers)) != len(identifiers) or (not set(identifiers) <= set(selected)) or set(identifiers) & accounted:
        raise ValueError('prefetched segment scope changed')
    key = core._auto_maintain_plan_hash({'spuIds': identifiers})[:20]
    expected = Path(output).resolve() / 'segments' / key / '.state/self-operated-plan.json'
    if Path(pending['planPath']).resolve() != expected:
        raise ValueError('prefetched segment path changed')
    manual.checked_json(expected, pending['planSha256'])
    import direct_resume as resume
    group = [selected[spu] for spu in identifiers]
    freeze_segment(output, resume.subset_result(original, group), args)
    return group

class Lookahead:

    def __init__(self, output, progress, args, client, records, roots, model):
        self.output, self.progress, self.args = (Path(output), progress, args)
        self.client, self.records, self.roots, self.model = (client, records, roots, model)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='direct-generation')
        self.future = None
        self.identifiers = None
        self.scope_error = None

    def start(self, result):
        import direct_resume as resume
        if self.scope_error is not None:
            raise self.scope_error
        if self.future is not None:
            raise ValueError('only one lookahead segment is allowed')
        if resume.pause_requested(self.output):
            return
        _, folder = freeze_segment(self.output, result, self.args)
        identifiers = [job.spu_id for job in result.prepared.jobs]
        path = folder / '.state/self-operated-plan.json'
        self.progress['prefetchedSegment'] = {'spuIds': identifiers, 'planPath': str(path), 'planSha256': manual.sha(path)}
        core._save_state(self.output / '.state/direct-progress.json', self.progress)
        try:
            prepared = resume.prepare_direct_generation(result, self.records, folder, self.args, self.client, self.roots)
        except ValueError as error:
            if str(error) not in {'SKU scope changed since confirmation; create a new plan', 'authorized product scope changed since confirmation'}:
                raise
            self.scope_error = error
            return
        self.identifiers = identifiers
        self.future = self.executor.submit(resume.generate_direct_materials, result, self.args, folder, self.model, prepared)

    def take(self, identifiers):
        if self.future is None:
            return None
        if identifiers != self.identifiers:
            raise ValueError('lookahead consumed out of order')
        future, self.future = (self.future, None)
        self.identifiers = None
        return future

    def close(self):
        self.model.cancel_event.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
