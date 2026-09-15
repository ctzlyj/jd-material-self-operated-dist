import { createHash } from 'node:crypto';

const patched = Symbol.for('webcli-browser-runtime.scoped-arguments');

export function installScopedArguments(PageType, expectedHash, onConflict = () => {}) {
  const original = PageType.prototype.evaluateWithArgs;
  if (original[patched]) return false;
  const source = original.toString();
  const actualHash = createHash('sha256').update(source).digest('hex');
  if (actualHash !== expectedHash) {
    onConflict(source, actualHash);
    throw new Error('WebCLI upstream evaluateWithArgs changed; merge and test the runtime overlay before use');
  }
  async function scopedEvaluate(source, args) {
    const declarations = Object.entries(args).map(([key, value]) => {
      if (!/^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(key)) {
        throw new Error(`evaluateWithArgs: invalid key "${key}"`);
      }
      return `const ${key} = ${JSON.stringify(value)};`;
    }).join('\n');
    return this.evaluate(`{\n${declarations}\n${source}\n}`);
  }
  scopedEvaluate[patched] = true;
  PageType.prototype.evaluateWithArgs = scopedEvaluate;
  return true;
}
