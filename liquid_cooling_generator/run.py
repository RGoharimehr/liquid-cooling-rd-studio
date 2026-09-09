#!/usr/bin/env python3
"""Generate a tunable reference layout and IFC4/PCF/JSON/OBJ review package."""
import argparse
import json
from pathlib import Path
import sys
from model import Config
from pipeline import run

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',type=Path,default=Path(__file__).parent/'config.json')
    ap.add_argument('--out',type=Path,default=Path(__file__).parent/'outputs')
    ap.add_argument('--allow-nonconforming',action='store_true',help='Export a draft while retaining all failed installation checks')
    args=ap.parse_args()
    try:
        g=run(Config.from_dict(json.loads(args.config.read_text())),args.out)
        failures=g['metadata']['verification'].get('blocking_failures',0)
        print(f'Generated {len(g["components"])} components, {len(g["edges"])} connection edges. {failures} blocking findings. Outputs: {args.out}')
        return 2 if failures and not args.allow_nonconforming else 0
    except Exception as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
