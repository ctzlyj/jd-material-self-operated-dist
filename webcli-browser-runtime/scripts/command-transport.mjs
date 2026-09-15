import { createHash } from 'node:crypto';

async function sendCommandRaw(action, params) {
  const seconds = typeof params.timeout === 'number' && params.timeout > 0 ? params.timeout : 120;
  if (!Number.isFinite(seconds)) throw new Error('Browser command timeout must be finite');
  const rawWindowMode = process.env.WEBCLI_WINDOW;
  const envWindowMode = ['foreground', 'background', 'current'].includes(rawWindowMode) ? rawWindowMode : undefined;
  const contextId = params.contextId ?? resolveProfileContextId();
  const windowMode = params.windowMode ?? envWindowMode;
  const command = { id: generateId(), action, ...params, timeout: seconds, ...(contextId && { contextId }), ...(windowMode && { windowMode }) };
  const unknown = () => new BrowserCommandError(
    'Browser command result is unknown; the operation may have completed.',
    'command_result_unknown', 'Inspect persisted results before retrying. Never blindly replay a write.',
  );
  let response;
  let result;
  try {
    response = await requestDaemon('/command', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(command), timeout: seconds * 1000 + 10000,
    });
    result = await response.json();
  } catch {
    throw unknown();
  }
  if (!result || typeof result.ok !== 'boolean') throw unknown();
  if (result.ok && response.ok !== false) return result;
  const message = result.error ?? 'Browser command failed';
  if (result.errorCode === 'profile_disconnected') {
    throw new BrowserCommandError(message, result.errorCode, result.errorHint);
  }
  if (result.errorCode === 'command_result_unknown' || [408, 409].includes(response.status)
      || response.status >= 500 || /timeout|timed out|Duplicate command id/i.test(message)
      || classifyBrowserError(new Error(message)).retryable) {
    throw unknown();
  }
  throw new BrowserCommandError(message, result.errorCode, result.errorHint);
}

export function transformCommandTransport(source, expectedHash, onConflict = () => {}) {
  const normalized = source.replace(/\r\n/g, '\n');
  const start = normalized.indexOf('async function sendCommandRaw(');
  const closing = normalized.indexOf('\n}', start);
  const end = closing < 0 ? normalized.length : closing + 2;
  const original = start < 0 ? normalized : normalized.slice(start, end).trimEnd();
  const hash = createHash('sha256').update(original).digest('hex');
  if (start < 0 || hash !== expectedHash) {
    onConflict(original, hash);
    throw new Error('WebCLI upstream command transport changed; merge and test the runtime overlay before use');
  }
  return normalized.slice(0, start) + sendCommandRaw.toString() + '\n' + normalized.slice(end);
}
