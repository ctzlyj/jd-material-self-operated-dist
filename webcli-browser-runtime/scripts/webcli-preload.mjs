import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { installScopedArguments } from './scoped-arguments.mjs';
import { installCommandTransport } from './install-command-transport.mjs';

try {
  const root = dirname(dirname(fileURLToPath(import.meta.url)));
  const baseline = JSON.parse(await readFile(join(root, 'upstream-baseline.json'), 'utf8'));
  const entry = resolve(process.argv[1]);
  await installCommandTransport(entry, baseline);
  const { BasePage } = await import(pathToFileURL(join(dirname(entry), 'browser', 'base-page.js')).href);
  let candidate;
  try {
    installScopedArguments(BasePage, baseline.evaluateWithArgsSha256, (source, hash) => {
      candidate = { source, hash };
    });
  } catch (error) {
    if (candidate) {
      const folder = join(homedir(), '.webcli', 'patch-candidates', 'scoped-arguments');
      await mkdir(folder, { recursive: true });
      await writeFile(join(folder, `${candidate.hash}.js`), candidate.source, { flag: 'wx' }).catch(caught => {
        if (caught.code !== 'EEXIST') throw caught;
      });
    }
    throw error;
  }
} catch (error) {
  console.log(JSON.stringify({ ok: false, error: error.message, code: 'WEBCLI_RUNTIME_MERGE_REQUIRED' }));
  process.exit(1);
}
