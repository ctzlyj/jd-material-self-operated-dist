import { randomUUID } from 'node:crypto';

const GATEWAY = 'https://api.m.jd.com';
const CALLER = process.platform === 'darwin' ? 'hio_plugin_joydesk_Mac' : 'hio_plugin_joydesk';

function failure(code) {
  return Object.assign(new Error(code), { code });
}

export async function resolveErpFromTicket(ticket, { fetchImpl = fetch, signal = AbortSignal.timeout(10_000) } = {}) {
  if (typeof ticket !== 'string' || !ticket.trim() || ticket.length > 8192 || /[\r\n;]/.test(ticket)) throw failure('ERP_NOT_LOGGED_IN');
  try {
    const functionId = 'joymail.authentication.publickey';
    const response = await fetchImpl(`${GATEWAY}/api`, {
      method: 'POST', redirect: 'error', signal,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Cookie: `me_token=${ticket.trim()};`, functionid: functionId, logintype: '15', referer: GATEWAY,
      },
      body: new URLSearchParams({ appid: 'joymail', body: '{}', functionId, lang: 'zh_CN', loginType: '15', cthr: '1', t: String(Date.now()), uuid: randomUUID().replaceAll('-', '').slice(0, 20) }),
    });
    if (!response.ok) throw failure(response.status === 401 || response.status === 403 ? 'ERP_NOT_LOGGED_IN' : 'ERP_AUTH_UNAVAILABLE');
    const payload = await response.json();
    const erp = typeof payload?.Data?.pin === 'string' ? payload.Data.pin.trim().toLowerCase() : '';
    if (payload?.IsSuccess !== true || !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(erp)) throw failure('ERP_NOT_LOGGED_IN');
    return { authenticated: true, erp };
  } catch (error) {
    throw failure(['ERP_NOT_LOGGED_IN', 'ERP_AUTH_UNAVAILABLE'].includes(error.code) ? error.code : signal.aborted ? 'ERP_AUTH_TIMEOUT' : 'ERP_AUTH_UNAVAILABLE');
  }
}

export async function verifyIdentity({ fetchImpl = fetch, timeoutMs = 12_000, authorize } = {}) {
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), timeoutMs);
  async function request(url, options, signal = controller.signal) {
    const response = await fetchImpl(url, { ...options, redirect: 'error', signal });
    if (!response.ok) throw failure(response.status === 401 || response.status === 403 ? 'ERP_NOT_LOGGED_IN' : 'ERP_AUTH_UNAVAILABLE');
    return response;
  }
  async function gateway(functionId, body) {
    const response = await request(`${GATEWAY}?functionId=${encodeURIComponent(functionId)}&appid=JDME_DESKTOP`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ functionId, body, appid: 'JDME_DESKTOP' }),
    });
    return response.json();
  }
  try {
    const encrypted = await gateway('desk.agent.auth.encrypt', {
      content: JSON.stringify({ method: 'query', param: 'appToken', timestamp: String(Math.floor(Date.now() / 1000)), from: CALLER, to: 'HiOfficeClient' }),
      jdmeAppId: 'ee',
    });
    if (encrypted?.code !== 0 || !encrypted.data?.aesKey || !encrypted.data?.content) throw failure('ERP_AUTH_UNAVAILABLE');
    let localTicket = null;
    for (let port = 8988; port <= 9006; port += 2) {
      if (controller.signal.aborted) throw failure('ERP_AUTH_TIMEOUT');
      try {
        const response = await request(`http://127.0.0.1:${port}/hioffice?from=${CALLER}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-AES-Key': encrypted.data.aesKey },
          body: encrypted.data.content,
        }, AbortSignal.any([controller.signal, AbortSignal.timeout(1_200)]));
        const aesKey = response.headers.get('X-AES-Key');
        if (!aesKey) continue;
        localTicket = { aesKey, token: await response.text() };
        break;
      } catch {
        if (controller.signal.aborted) throw failure('ERP_AUTH_TIMEOUT');
      }
    }
    if (!localTicket?.token) throw failure('ERP_NOT_LOGGED_IN');
    const exchanged = await gateway('desk.agent.auth.getWebToken', {
      ...localTicket, tenantCode: 'CN.JD.GROUP', deviceUuid: 'noDeviceId', jdmeAppId: 'ee',
    });
    const ticket = exchanged?.data?.accessToken;
    if (exchanged?.code !== 0 || typeof ticket !== 'string' || !ticket.trim() || /[\r\n;]/.test(ticket)) {
      throw failure('ERP_NOT_LOGGED_IN');
    }
    const identity = await resolveErpFromTicket(ticket, { fetchImpl, signal: controller.signal });
    return authorize ? await authorize({ ...identity, ticket: ticket.trim() }) : identity;
  } catch (error) {
    const code = ['ERP_AUTH_TIMEOUT', 'ERP_NOT_LOGGED_IN', 'ERP_AUTH_UNAVAILABLE', 'ERP_NOT_ALLOWED', 'ERP_AUTH_INVALID'].includes(error.code)
      ? error.code : controller.signal.aborted ? 'ERP_AUTH_TIMEOUT' : 'ERP_AUTH_UNAVAILABLE';
    throw failure(code);
  } finally {
    clearTimeout(deadline);
  }
}
