import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';
import * as nodeModule from 'node:module';
import { transformCommandTransport } from './command-transport.mjs';

export async function installCommandTransport(entry, baseline) {
  if (typeof nodeModule.registerHooks !== 'function') {
    throw new Error('The safe WebCLI transport requires Node.js 22.15 or newer; update the Node runtime before use');
  }
  const path = join(dirname(entry), 'browser', 'daemon-client.js');
  const url = pathToFileURL(path).href;
  const source = await readFile(path, 'utf8');
  let candidate;
  let patched;
  try {
    patched = transformCommandTransport(source, baseline.commandTransportSha256, (source, hash) => {
      candidate = { source, hash };
    });
  } catch (error) {
    if (candidate) {
      const folder = join(homedir(), '.webcli', 'patch-candidates', 'command-transport');
      await mkdir(folder, { recursive: true });
      await writeFile(join(folder, `${candidate.hash}.js`), candidate.source, { flag: 'wx' }).catch(caught => {
        if (caught.code !== 'EEXIST') throw caught;
      });
    }
    throw error;
  }
  return nodeModule.registerHooks({
    load(specifier, context, nextLoad) {
      const result = nextLoad(specifier, context);
      return specifier === url ? { ...result, source: patched } : result;
    },
  });
}
