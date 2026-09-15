// What is wrong with this studio, locally or as deployed.
//
// The browser gets the engine as a list of files named in /engine/manifest.json
// and nothing else, so a module can be "missing" in three ways that look
// identical in the app - a ModuleNotFoundError in whichever panel reached for it
// first - and have completely different fixes:
//
//   the committed browser copy is short          -> npm run sync
//   the deployment serves fewer files than this  -> redeploy
//   the manifest names files with backslashes    -> re-sync and redeploy
//
// The third is the one that fools you: every file is present, every fetch
// succeeds, and the package still cannot be imported.
//
//   node scripts/doctor.mjs                  check this checkout
//   node scripts/doctor.mjs --url <origin>   also check what a deployment serves
import fs from 'node:fs';
import path from 'node:path';

const engine = path.resolve('../liquid_cooling_generator');
const browser = path.resolve('public/engine');
const SKIP = new Set(['run.py', 'validate_design.py', 'benchmark.py']); // CLI entry points
const ok = (m) => console.log('  ✓ ' + m);
const bad = (m) => { console.log('  ✗ ' + m); failures++; };
let failures = 0;

const sources = () => {
  const names = fs.readdirSync(engine).filter(n => n.endsWith('.py') && !SKIP.has(n));
  const pkg = path.join(engine, 'datacenter_equipment_finder');
  for (const name of fs.readdirSync(pkg).filter(n => n.endsWith('.py')))
    names.push('datacenter_equipment_finder/' + name);
  return names.sort();
};

console.log('\nThis checkout');
const expected = sources();
let manifest = [];
try { manifest = JSON.parse(fs.readFileSync(path.join(browser, 'manifest.json'), 'utf8')); }
catch { bad('public/engine/manifest.json is missing or unreadable. Run: npm run sync'); }

// A manifest written by a sync on Windows carries backslash separators. The
// files are all there and the fetches even succeed, but the browser filesystem
// treats the backslash as part of the name, so the package directory is never
// created. It presents as a missing module, not as a missing file.
const windowsPaths = manifest.filter(n => n.includes('\\'));
if (windowsPaths.length) bad(`${windowsPaths.length} manifest entr(y/ies) use Windows path separators: ${windowsPaths[0]}\n      The browser cannot build a package directory from those. Run: npm run sync (with the current scripts/sync-engine.py)`);

const listed = new Set(manifest.map(n => n.replace(/\\/g, '/')));
const unlisted = expected.filter(n => !listed.has(n));
unlisted.length
  ? bad(`${unlisted.length} engine module(s) absent from the browser manifest: ${unlisted.slice(0,6).join(', ')}${unlisted.length>6?'…':''}\n      Run: npm run sync`)
  : ok(`manifest lists all ${expected.length} engine modules${windowsPaths.length ? ' (but see the separator problem above)' : ''}`);

const absent = manifest.filter(n => !fs.existsSync(path.join(browser, n.replace(/\\/g, '/'))));
absent.length
  ? bad(`${absent.length} file(s) named in the manifest are not on disk: ${absent.slice(0,6).join(', ')}${absent.length>6?'…':''}\n      Run: npm run sync`)
  : ok(`all ${manifest.length} manifest files are present on disk`);

const stale = expected.filter(n => {
  const from = path.join(engine, n), to = path.join(browser, n);
  return fs.existsSync(to) && fs.readFileSync(from, 'utf8') !== fs.readFileSync(to, 'utf8');
});
stale.length
  ? bad(`${stale.length} browser cop(y/ies) differ from the engine source: ${stale.slice(0,6).join(', ')}${stale.length>6?'…':''}\n      Run: npm run sync`)
  : ok('browser engine copies match the engine sources');

const runtime = ['pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json']
  .filter(n => !fs.existsSync(path.join('public/pyodide', n)));
runtime.length
  ? bad(`bundled Pyodide runtime is incomplete (${runtime.join(', ')}). Run: npm ci && npm run sync`)
  : ok('bundled Pyodide runtime is complete');

fs.existsSync('public/catalog.json') ? ok('parameter catalogue is present')
  : bad('public/catalog.json is missing. Run: npm run sync');

// An interrupted `npm ci` leaves node_modules half-deleted. Nothing else here
// notices, and the failures that follow name the wrong thing: `tsc` reports
// itself uninstalled, and the sync says the Pyodide runtime is absent.
const NEEDED = {typescript: 'the type check', pyodide: 'the browser engine test and npm run sync',
                three: 'the 3D viewer', vinext: 'the dev server and the build'};
const uninstalled = Object.keys(NEEDED).filter(n => !fs.existsSync(path.join('node_modules', n)));
uninstalled.length
  ? bad(`${uninstalled.length} dependenc(y/ies) are not installed: ${uninstalled.map(n => `${n} (${NEEDED[n]})`).join(', ')}\n      Run: npm run dev:stop && npm ci`)
  : ok('dependencies are installed');

const lockfile = '.vinext/dev/lock.json';
let devRunning = false;
if (fs.existsSync(lockfile)) {
  let lock = {}; try { lock = JSON.parse(fs.readFileSync(lockfile,'utf8')); } catch {}
  try { process.kill(lock.pid, 0); devRunning = true; } catch {}
  console.log(devRunning
    ? `  · a dev server is running: pid ${lock.pid}, ${lock.appUrl || 'port ' + lock.port}. Restart with: npm run dev:restart`
    : `  · a stale dev lockfile is blocking startup. Clear it with: npm run dev:stop`);
}
// On Windows the running server holds native .node addons open, and npm ci
// deletes node_modules before reinstalling it: the unlink fails with EPERM
// partway through and leaves the tree broken.
if (devRunning && process.platform === 'win32')
  console.log('  · stop it before `npm ci`, or the install fails with EPERM on a locked .node file.');

const url = process.argv.includes('--url') ? process.argv[process.argv.indexOf('--url') + 1] : null;
if (url) {
  if (!/^https?:\/\//i.test(url)) {
    console.log(`\nDeployment check skipped: "${url}" is not a URL. Pass the real origin, for example:\n  npm run doctor -- --url https://your-studio-host`);
    process.exit(failures ? 1 : 0);
  }
  const origin = url.replace(/\/+$/, '');
  console.log(`\nDeployment at ${origin}`);
  // The deployed page and the deployed engine are separate files. A deployment
  // can be current in one and stale in the other, which is exactly the case
  // that looks like a code bug and is not one.
  const get = async (p) => { try { return await fetch(origin + p, {cache:'no-store'}); } catch (e) { return {ok:false, status:0, error:e.message}; } };
  const response = await get('/engine/manifest.json');
  if (!response.ok) {
    bad(`/engine/manifest.json returned ${response.status || response.error}. The deployment is not serving the engine at all.`);
  } else {
    let served = null;
    try { served = await response.json(); } catch { served = null; }
    if (!Array.isArray(served)) {
      bad('/engine/manifest.json did not return a file list. Something else is answering at that address.');
    } else {
      const servedWindows = served.filter(n => n.includes('\\'));
      if (servedWindows.length) bad(`the deployed manifest uses Windows path separators (${servedWindows[0]}).\n      It was built by a sync on Windows. Redeploy after running "npm run sync" with the current scripts/sync-engine.py.`);
      const servedSet = new Set(served.map(n => n.replace(/\\/g, '/')));
      const missing = expected.filter(n => !servedSet.has(n));
      missing.length
        ? bad(`the deployed manifest is short by ${missing.length} module(s): ${missing.slice(0,6).join(', ')}${missing.length>6?'…':''}\n      This is a deployment problem, not a code one. Redeploy from a checkout where "npm run doctor" passes.`)
        : ok(`deployed manifest lists all ${expected.length} engine modules`);
      // A manifest can list a file the host then refuses to serve, which fails
      // the worker at load with a 404 rather than a missing module.
      const probes = ['web_api.py', 'datacenter_equipment_finder/__init__.py', 'datacenter_equipment_finder/catalog.py'];
      for (const name of probes) {
        const probe = await get('/engine/' + name);
        const body = probe.ok ? await probe.text() : '';
        if (!probe.ok) bad(`/engine/${name} returned ${probe.status || probe.error}`);
        else if (/^\s*<(!doctype|html)/i.test(body)) bad(`/engine/${name} returned an HTML page, not Python. The host is serving a fallback page for a file it does not have.`);
        else ok(`/engine/${name} serves ${body.length} bytes of Python`);
      }
    }
  }
}

console.log(failures
  ? `\n${failures} problem(s) found.\n`
  : '\nNo problems found.\n');
process.exit(failures ? 1 : 0);
