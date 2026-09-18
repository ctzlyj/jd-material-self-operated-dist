(async () => {
  const action = __JD_OSW_TITLE_ACTION__;
  const prefix = 'https://storage.360buyimg.com/pubfree-bucket/commodity-backend-fe/prod/';
  const versions = [
    {base: prefix + 'd6069ca/assets/', main: 'index.4c6d2437.js', batch: 'batch.016fe8c9.js'},
    {base: prefix + 'e5e2d19/assets/', main: 'index.e44ce2eb.js', batch: 'batch.f9863095.js'},
  ].filter(version => Array.from(document.scripts).some(script => script.src === version.base + version.main));
  if (versions.length !== 1) {
    throw Error('OSW task frontend version changed; verify contract before writes');
  }
  const version = versions[0];
  const main = await import(version.base + version.main);
  const api = await import(version.base + version.batch);
  if (!action.erp || main.d() !== action.erp) throw Error('authenticated ERP mismatch');
  const lookup = async () => {
    const reply = await api.m({page: 1, rows: 5, type: 272, name: action.name}, true);
    if (reply.success !== true || !Array.isArray(reply.obj?.rows)) throw Error('OSW task query failed');
    return {total: reply.obj.total, rows: reply.obj.rows.map(row => ({id: row._id, name: row.name,
      erp: row.commiter, type: row.type, status: row.status}))};
  };
  if (action.kind === 'lookup') return await lookup();
  if (action.kind === 'file') {
    const task = await lookup();
    if (task.total !== 1 || task.rows[0].id !== action.taskId || task.rows[0].erp !== action.erp ||
        task.rows[0].name !== action.name || ![0, 3].includes(task.rows[0].status) ||
        !['downsourcefile', 'downlog'].includes(action.fileKind)) throw Error('OSW download task mismatch');
    const reply = await api.o({downloadUrl: '/site/task/' + action.fileKind + '?id=' + action.taskId});
    const blob = reply instanceof Blob ? reply : reply.data;
    if (!(blob instanceof Blob)) throw Error('OSW missing result file');
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let encoded = '';
    for (const byte of bytes) encoded += String.fromCharCode(byte);
    return {bytes: bytes.length, base64: btoa(encoded)};
  }
  const page = await api.x({tab: 1}, true);
  const task = Object.values((page.obj || page).spesGroup || {}).flat().find(item => item.type === 272);
  if (task?.hasPermission !== true || task.siteId !== 384 || task.clzName !== 'batchModifyShortTitleMerge') {
    throw Error('OSW task permission or contract changed');
  }
  if (action.kind === 'prepare') return {ready: true};
  if (action.kind !== 'create') throw Error('unsupported OSW action');
  const existing = await lookup();
  if (existing.total !== 0 || existing.rows.length) throw Error('OSW task already exists; reconcile');
  const bytes = Uint8Array.from(atob(action.base64), character => character.charCodeAt(0));
  const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (hash !== action.sourceSha256 || bytes.length >= 5 * 1024 * 1024) throw Error('OSW source hash or size mismatch');
  const stateKey = '__jdOswTitle_' + hash;
  if (window[stateKey]) throw Error('OSW request already dispatched; reconcile');
  const form = new FormData();
  form.append('upload', new File([bytes], 'short-titles.xlsx', {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));
  form.append('type', '272');
  form.append('taskname', action.name);
  window[stateKey] = {state: 'unknown'};
  const reply = await api.y(form);
  const receipt = {success: reply?.success, data: reply?.data};
  window[stateKey].receipt = receipt;
  return receipt;
})()
