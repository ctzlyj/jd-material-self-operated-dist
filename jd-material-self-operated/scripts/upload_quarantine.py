from pathlib import Path
import uuid
import jd_material_agent as core
import manual_resume as manual
CONFIRM = 'ISOLATE_SPU_WITHOUT_REPLAY'
REASON = 'quarantined unknown upload; preserve original receipt and never replay'
UNKNOWN_STATUSES = ('uploading', 'unconfirmed', 'submitted')

def reference(path):
    return {'path': str(path), 'sha256': manual.sha(path)}

def image_paths(batch, spu):
    paths = [batch / '全部图片' / name for name in core.image_names(spu).values()]
    paths.append(batch / '参考图' / (spu + '.jpg'))
    return [path for path in paths if path.is_file()]

def load(output):
    output = Path(output).resolve()
    pointer_path = output / '.state/upload-quarantine.json'
    if not pointer_path.exists():
        return {}
    return load_chain(output, manual.read_json(pointer_path))

def load_chain(output, pointer):
    records = {}
    visited = set()
    while pointer is not None:
        path = Path(pointer['path']).resolve()
        if path in visited:
            raise ValueError('quarantine evidence chain repeats')
        visited.add(path)
        record = load_record(output, pointer)
        spu = record['spuId']
        if spu in records:
            raise ValueError('quarantine cannot replace an existing SPU')
        records[spu] = record
        pointer = record.get('previous') if record['formatVersion'] == 2 else None
    return records

def load_record(output, pointer):
    path = Path(pointer['path']).resolve()
    if not path.is_relative_to(output / '.state/upload-quarantines'):
        raise ValueError('quarantine evidence escaped its original task')
    record = manual.checked_json(path, pointer['sha256'])
    if record.get('formatVersion') not in (1, 2) or record.get('confirmation') != CONFIRM or record.get('allowedWrites') != [] or (record.get('replayAllowed') is not False):
        raise ValueError('invalid quarantine authorization')
    if record['formatVersion'] == 2 and 'previous' not in record:
        raise ValueError('quarantine evidence chain is missing')
    batch = Path(record['batch']).resolve()
    if batch.parent.parent != output / 'segments' or batch.name != '批次001':
        raise ValueError('quarantine batch escaped its original task')
    for key, expected in (('sourcePlan', output / '.state/direct-plan.json'), ('segmentPlan', batch.parent / '.state/self-operated-plan.json')):
        if Path(record[key]['path']).resolve() != expected:
            raise ValueError('quarantine source path changed')
        manual.checked_json(expected, record[key]['sha256'])
    plan = manual.read_json(output / '.state/direct-plan.json')
    spu = record['spuId']
    jobs = [job for job in plan['jobs'] if job['spu_id'] == spu]
    if len(jobs) != 1 or jobs[0]['sku_ids'] != record['skuIds'] or plan['erp'] != record['erp'] or (plan['ownerErp'] != record['ownerErp']):
        raise ValueError('quarantine ERP or complete SKU scope changed')
    import scope_revision
    original = scope_revision.frozen_result(batch.parent)
    effective, revision = scope_revision.load(batch.parent, original)
    current = next((job for job in effective.prepared.jobs if job.spu_id == spu))
    if list(current.sku_ids) != record['effectiveSkuIds']:
        raise ValueError('quarantine effective SKU scope changed')
    archived = {}
    for key, value in record['before'].items():
        if not Path(value['path']).resolve().is_relative_to(path.parent):
            raise ValueError('quarantine archive escaped its evidence directory')
        archived[key] = manual.checked_json(value['path'], value['sha256'])
    state = manual.read_json(batch / '.state/task.json')
    if state.get('task_signature') != core._task_signature(effective.prepared) or state['jobs'].get(spu) != archived['task']['jobs'].get(spu):
        raise ValueError('quarantined task state changed')
    ledger = manual.read_json(batch / '.state/upload-ledger.json')['files']
    names = set(core.image_names(spu).values())
    expected = {name: item for name, item in archived['ledger']['files'].items() if name in names}
    if {name: item for name, item in ledger.items() if name in names} != expected:
        raise ValueError('quarantined upload receipt changed')
    filenames = record.get('fileNames') if record['formatVersion'] == 2 else [record['fileName']]
    if not isinstance(filenames, list) or not filenames or any((not isinstance(name, str) for name in filenames)) or (len(set(filenames)) != len(filenames)) or (record['fileName'] not in filenames):
        raise ValueError('invalid quarantine file scope')
    if record['formatVersion'] == 2 and set(filenames) != {name for name, entry in expected.items() if entry.get('status') in UNKNOWN_STATUSES}:
        raise ValueError('quarantine must freeze all current unknown uploads of its SPU')
    if any((expected.get(name, {}).get('status') not in UNKNOWN_STATUSES for name in filenames)):
        raise ValueError('quarantine requires the original unknown upload')
    paths = image_paths(batch, spu)
    if {str(item) for item in paths} != {item['path'] for item in record['images']}:
        raise ValueError('quarantined image set changed')
    for image in record['images']:
        if manual.sha(Path(image['path'])) != image['sha256']:
            raise ValueError('quarantined image content changed')
    for name in filenames:
        image = batch / '全部图片' / name
        if name not in names or not image.is_file() or manual.sha(image) != expected[name].get('sha256'):
            raise ValueError('quarantined upload has no matching frozen image')
    return {**record, 'fileNames': filenames, 'evidence': pointer}

def for_batch(batch):
    batch = Path(batch).resolve()
    if batch.name != '批次001' or batch.parent.parent.name != 'segments':
        return {}
    records = load(batch.parents[2])
    return {spu: item for spu, item in records.items() if Path(item['batch']).resolve() == batch}

def assert_write_targets(batch, spu_ids):
    if set(spu_ids).intersection(for_batch(batch)):
        raise ValueError('quarantined SPU cannot be uploaded, bound or written')

def freeze(output, erp, token, segment, spu, filename, confirm):
    if confirm != CONFIRM:
        raise ValueError('explicit unknown-upload quarantine authorization required')
    import direct_resume
    import scope_revision
    output = Path(output).resolve()
    folder = (output / 'segments' / segment).resolve()
    if folder.parent != output / 'segments' or filename not in core.image_names(spu).values():
        raise ValueError('quarantine target exceeds original scope')
    with core._erp_execution_lock(output), core._erp_execution_lock(folder):
        plan, snapshot = direct_resume.load_direct(output, erp, token)
        progress_path = output / '.state/direct-progress.json'
        if progress_path.exists() and manual.read_json(progress_path).get('workerRunning'):
            raise ValueError('settle the previous worker before quarantine')
        existing = load(output)
        if spu in existing:
            if existing[spu]['batch'] != str(folder / '批次001') or filename not in existing[spu]['fileNames']:
                raise ValueError('existing quarantine cannot be replaced')
            return {'status': 'quarantined-unknown-upload', 'reused': True, 'spuId': spu}
        pointer_path = output / '.state/upload-quarantine.json'
        previous = manual.read_json(pointer_path) if pointer_path.exists() else None
        original = scope_revision.frozen_result(folder)
        result, revision = scope_revision.load(folder, original)
        selected = [job for job in snapshot.jobs if job.spu_id == spu]
        effective = [job for job in result.prepared.jobs if job.spu_id == spu]
        if len(selected) != 1 or len(effective) != 1:
            raise ValueError('quarantine requires one original authorized SPU')
        batch = folder / '批次001'
        ledger = manual.read_json(batch / '.state/upload-ledger.json')
        entry = ledger['files'].get(filename, {})
        image = batch / '全部图片' / filename
        if entry.get('status') not in UNKNOWN_STATUSES or not image.is_file() or manual.sha(image) != entry.get('sha256'):
            raise ValueError('quarantine requires a frozen unknown upload')
        filenames = sorted((name for name in core.image_names(spu).values() if ledger['files'].get(name, {}).get('status') in UNKNOWN_STATUSES))
        destination = output / '.state/upload-quarantines' / uuid.uuid4().hex
        destination.mkdir(parents=True)
        before = {}
        for key, name in (('task', 'task.json'), ('ledger', 'upload-ledger.json')):
            archive = destination / name
            archive.write_bytes((batch / '.state' / name).read_bytes())
            before[key] = reference(archive)
        record = {'formatVersion': 2, 'previous': previous, 'erp': erp, 'ownerErp': plan['ownerErp'], 'spuId': spu, 'skuIds': list(selected[0].sku_ids), 'effectiveSkuIds': list(effective[0].sku_ids), 'batch': str(batch), 'fileName': filename, 'fileNames': filenames, 'before': before, 'sourcePlan': reference(output / '.state/direct-plan.json'), 'segmentPlan': reference(folder / '.state/self-operated-plan.json'), 'images': [reference(path) for path in image_paths(batch, spu)], 'allowedWrites': [], 'replayAllowed': False, 'confirmation': CONFIRM}
        path = destination / 'quarantine.json'
        core._save_state(path, record)
        load_chain(output, reference(path))
        core._save_state(pointer_path, reference(path))
        return {'status': 'quarantined-unknown-upload', 'spuId': spu, 'skuIds': record['skuIds'], 'fileNames': filenames, 'evidence': reference(path), 'writesPerformed': False, 'complete': False}
