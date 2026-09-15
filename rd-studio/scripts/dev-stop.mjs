// Stop a dev server this directory left running.
//
// `vinext dev` refuses to start while another one holds the lock, and prints a
// PID to kill by hand. That is a papercut every time you restart, so this reads
// the same lockfile and does it.
import fs from 'node:fs';
import path from 'node:path';

const lockfile = path.resolve('.vinext/dev/lock.json');
const gone = (pid) => { try { process.kill(pid, 0); return false; } catch { return true; } };
const sleep = (ms) => new Promise(done => setTimeout(done, ms));

if (!fs.existsSync(lockfile)) {
  console.log('No dev server lockfile. Nothing to stop.');
  process.exit(0);
}
let lock;
try { lock = JSON.parse(fs.readFileSync(lockfile, 'utf8')); }
catch { console.log('Dev server lockfile is unreadable; removing it.'); fs.rmSync(lockfile, {force:true}); process.exit(0); }

const {pid, port, appUrl} = lock;
if (typeof pid !== 'number' || gone(pid)) {
  // A crash or a killed terminal leaves the lock behind and blocks the next
  // start even though nothing is listening.
  console.log(`No process ${pid} is running. Clearing the stale lockfile.`);
  fs.rmSync(lockfile, {force:true});
  process.exit(0);
}

console.log(`Stopping dev server pid ${pid}${port ? ` on port ${port}` : ''}${appUrl ? ` (${appUrl})` : ''}…`);
try { process.kill(pid, 'SIGTERM'); } catch (error) {
  console.log(`Could not signal ${pid}: ${error.message}`);
  fs.rmSync(lockfile, {force:true});
  process.exit(0);
}
for (let i = 0; i < 40 && !gone(pid); i++) await sleep(250);
if (!gone(pid)) {
  console.log('It did not exit on SIGTERM. Sending SIGKILL.');
  try { process.kill(pid, 'SIGKILL'); } catch {}
  for (let i = 0; i < 20 && !gone(pid); i++) await sleep(250);
}
fs.rmSync(lockfile, {force:true});
console.log(gone(pid) ? 'Stopped.' : `Process ${pid} is still alive. Kill it by hand: kill -9 ${pid}`);
process.exit(gone(pid) ? 0 : 1);
