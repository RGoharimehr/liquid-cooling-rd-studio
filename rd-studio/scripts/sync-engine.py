"""Copy the one Python engine into browser assets; no parallel implementation."""
from pathlib import Path
import sys,json,shutil
root=Path(__file__).resolve().parents[2];engine=root/'liquid_cooling_generator';public=root/'rd-studio/public'
sys.path.insert(0,str(engine))
from parameters import PRESETS,catalog
from pipeline import build
from verify import run as verify_run
from model import Config
names=[]
SKIP={'run.py','validate_design.py','benchmark.py'}   # CLI entry points; the browser never imports them
for p in engine.glob('*.py'):
    if p.name in SKIP:continue
    target=public/'engine'/p.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);names.append(p.name)
# Drop browser copies of engine modules that no longer exist upstream, so a
# deleted module cannot keep running in the worker.
for stale in sorted((public/'engine').glob('*.py')):
    if stale.name not in names:print('removing stale browser copy:',stale.name);stale.unlink()
for p in (engine/'datacenter_equipment_finder').rglob('*.py'):
    rel=p.relative_to(engine);target=public/'engine'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);names.append(str(rel))
for p in (engine/'references/corpus').glob('*'):
    if p.suffix not in ('.txt','.json'):continue
    rel=p.relative_to(engine);target=public/'engine'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);names.append(str(rel))
(public/'engine/manifest.json').write_text(json.dumps(sorted(names)))
(public/'catalog.json').write_text(json.dumps({'parameters':catalog(),'presets':PRESETS}))
g,profile=build(Config.from_dict(PRESETS['compact']['config']))
g['metadata']['verification']=verify_run(g,Config.from_dict(PRESETS['compact']['config']),profile)['summary']
# Bundle the ESM runtime matched to the installed, locked package version.
# Without an npm install there is nothing to copy; say so and keep the engine
# sources in sync rather than failing the whole sync.
runtime=root/'rd-studio/node_modules/pyodide'
if runtime.is_dir():
    for name in ['pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json']:
        shutil.copy2(runtime/name, public/'pyodide'/name)
else:
    print('WARNING: rd-studio/node_modules/pyodide is absent, so the bundled runtime was NOT refreshed. '
          'Run `npm ci` in rd-studio and re-run this script before building the studio.')
# Include add-in source as text assets so ZIP handoff includes it in the worker.
for p in (engine/'revit').rglob('*'):
    if p.is_file() and not any(x in p.parts for x in ('bin','obj')):
        rel=p.relative_to(engine);target=public/'engine'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);names.append(str(rel))
(public/'engine/manifest.json').write_text(json.dumps(sorted(names)))
(public/'initial-graph.json').write_text(json.dumps(g,separators=(',',':')))
print('Synced',len(names),'engine files; initial',len(g['components']),'objects;',g['metadata']['verification'])
