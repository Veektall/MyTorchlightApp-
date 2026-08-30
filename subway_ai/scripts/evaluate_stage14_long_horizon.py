#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path
import evaluate_stage11_closed_loop as s11
from live_runtime_v2 import robust_open_game

s11.open_game=robust_open_game

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--checkpoint',required=True);ap.add_argument('--out',required=True);ap.add_argument('--episodes',type=int,default=3);ap.add_argument('--max-seconds',type=float,default=60);args=ap.parse_args()
    old=sys.argv;sys.argv=[old[0],'--checkpoint',args.checkpoint,'--out',args.out,'--episodes',str(args.episodes),'--max-seconds',str(args.max_seconds)]
    code=0
    try:s11.main()
    except SystemExit as e:code=int(e.code or 0)
    finally:sys.argv=old
    p=Path(args.out)/'stage11_summary.json'
    if not p.exists():raise SystemExit(code or 42)
    x=json.loads(p.read_text());x['stage']='14-official-long-horizon-benchmark-v1';x['previous_stage11_horizon_sec']=28.0;x['previous_stage11_episodes_per_policy']=2;x['longer_than_stage11']=bool(args.max_seconds>28 and args.episodes>2);x['completed']=bool(x.get('benchmark_complete') and x['longer_than_stage11']);
    (Path(args.out)/'stage14_summary.json').write_text(json.dumps(x,indent=2));print(json.dumps(x,indent=2),flush=True)
    raise SystemExit(0 if x['completed'] else (code or 42))
