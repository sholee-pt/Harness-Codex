// Independently authored adapter. Import structural APIs, never Graft CLI/init/upkeep.
import { existsSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

try {
  const request = JSON.parse(readFileSync(0, 'utf8'));
  if (Number(process.versions.node.split('.')[0]) < 20) throw new Error('Node.js 20 or newer is required');
  const load = name => import(pathToFileURL(join(request.package, 'dist', name)).href);
  const { buildGraph } = await load('graph/build.js');
  const { probeDrift, isClean } = await load('graph/fingerprint.js');
  const { acquireLockIn, releaseLockIn } = await load('util/state.js');
  const lock = join(request.cache, '.cache');
  if (!acquireLockIn(lock)) throw new Error('Graph is busy; use ordinary source search for this task');
  try {
    const drift = probeDrift(request.root, request.cache);
    let build = null;
    const ready = join(request.cache, 'harness-ready.json');
    if (request.action === 'rebuild' || !existsSync(ready) || !drift || !isClean(drift)) {
      if (existsSync(ready)) unlinkSync(ready);
      build = await buildGraph(request.root, { contextDir: request.cache, graphOnly: true, reuse: true, lsp: false });
      if (build.errors.length) throw new Error('Incomplete structural index: ' + build.errors.slice(0, 3).join('; '));
      writeFileSync(ready, JSON.stringify({ adapter: 'harness-graft-v1' }));
    }
    const result = { adapter: 'harness-graft-v1', refreshed: Boolean(build) };
    if (request.action === 'query') {
      const { ask, formatAsk } = await load('ask/ask.js');
      const answer = ask(request.root, request.question, { contextDir: request.cache, limit: request.limit, source: true, full: false });
      // Local character estimates are not observed token savings. Do not relay them.
      delete answer.saved;
      delete answer.rules;
      if (request.advice) {
        result.candidates = answer.hits.map((hit, i) => ({ id: `c${i}`,
          text: [hit.title, hit.pointer, hit.snippet, hit.code].filter(value => typeof value === 'string').join('\n').slice(0, 2400) }));
      }
      const text = formatAsk(answer);
      const notice = '\n[Result truncated; inspect relevant source.]';
      let prefix = text.slice(0, Math.max(0, request.maxChars - notice.length));
      if (/[\uD800-\uDBFF]$/.test(prefix)) prefix = prefix.slice(0, -1);
      result.text = text.length > request.maxChars ? prefix + notice.slice(0, request.maxChars) : text;
      result.hits = answer.hits.length;
      result.truncated = text.length > request.maxChars;
    } else {
      Object.assign(result, build
        ? { files: build.files, parsed: build.parsed, reused: build.reused, nodes: build.nodes, errors: build.errors }
        : { indexed: true, parsed: 0 });
    }
    process.stdout.write(JSON.stringify(result));
  } finally {
    releaseLockIn(lock);
  }
} catch (error) {
  process.stderr.write(String(error.message || error));
  process.exitCode = 1;
}
