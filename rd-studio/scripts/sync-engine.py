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
for p in engine.glob('*.py'):
    if p.name in ('report.py','run.py'):continue
    target=public/'engine'/p.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);names.append(p.name)
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
for name in ['pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json']:
    shutil.copy2(root/'rd-studio/node_modules/pyodide'/name, public/'pyodide'/name)
# Include add-in source as text assets so ZIP handoff includes it in the worker.
for p in (engine/'revit').rglob('*'):
    if p.is_file() and not any(x in p.parts for x in ('bin','obj')):
        rel=p.relative_to(engine);target=public/'engine'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);names.append(str(rel))
(public/'engine/manifest.json').write_text(json.dumps(sorted(names)))
(public/'initial-graph.json').write_text(json.dumps(g,separators=(',',':')))
print('Synced',len(names),'engine files; initial',len(g['components']),'objects;',g['metadata']['verification'])
