import { verifyIdentity } from './identity.mjs';

try {
  const identity = await verifyIdentity({ timeoutMs: 60_000 });
  if (typeof identity.erp !== 'string' || !/^[A-Za-z0-9_.-]+$/.test(identity.erp)) {
    throw new Error('ERP_IDENTITY_INVALID');
  }
  console.log(JSON.stringify({ ok: true, erp: identity.erp }));
} catch {
  console.log(JSON.stringify({ ok: false, code: 'ERP_IDENTITY_UNAVAILABLE' }));
  process.exitCode = 1;
}
