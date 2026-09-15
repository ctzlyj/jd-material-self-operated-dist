import { readFile } from 'node:fs/promises';
import { verifyIdentity } from './identity.mjs';

const endpoint = 'https://material-auth.space.jd.com/__space/ssa-free/skills/v1/execute';
const settings = JSON.parse(await readFile(new URL('./protected-settings.json', import.meta.url), 'utf8'));
const chunks = [];
let size = 0;
try {
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 8 * 1024 * 1024) throw new Error('CORE_REQUEST_TOO_LARGE');
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (input?.version !== 1 || input.product !== settings.product || input.operation !== 'core-call') throw new Error('CORE_REQUEST_INVALID');
  const body = JSON.stringify(input);
  let responseBody;
  await verifyIdentity({ timeoutMs: 60_000, authorize: async ({ ticket }) => {
    const response = await fetch(endpoint, {
      method: 'POST', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(45_000),
      headers: { 'content-type': 'application/json', Authorization: `Bearer ${ticket}` }, body,
    });
    const responseChunks = [];
    let received = 0;
    for await (const chunk of response.body) {
      received += chunk.length;
      if (received > 8 * 1024 * 1024) throw new Error('CORE_RESPONSE_INVALID');
      responseChunks.push(chunk);
    }
    responseBody = JSON.parse(Buffer.concat(responseChunks).toString('utf8'));
    if (!response.ok && responseBody?.ok !== false) throw new Error('CORE_RESPONSE_INVALID');
    return { authenticated: true };
  } });
  if (responseBody?.ok !== true && !/^[A-Z_]{1,64}$/.test(responseBody?.code || '')) throw new Error('CORE_RESPONSE_INVALID');
  console.log(JSON.stringify(responseBody));
  if (!responseBody.ok) process.exitCode = 1;
} catch (error) {
  const code = ['ERP_NOT_LOGGED_IN', 'ERP_AUTH_TIMEOUT', 'ERP_AUTH_UNAVAILABLE', 'CORE_REQUEST_TOO_LARGE', 'CORE_REQUEST_INVALID', 'CORE_RESPONSE_INVALID'].includes(error.code || error.message) ? error.code || error.message : 'CORE_RESULT_UNKNOWN';
  console.log(JSON.stringify({ ok: false, code }));
  process.exitCode = 1;
}
