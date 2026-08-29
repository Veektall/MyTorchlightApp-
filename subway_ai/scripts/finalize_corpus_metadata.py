#!/usr/bin/env python3
import argparse, csv, json
from pathlib import Path


def truthy(v):
    return str(v or '').strip().lower() in {'1','true','yes','y'}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifest',required=True)
    ap.add_argument('--root',required=True)
    args=ap.parse_args()
    root=Path(args.root)
    manifest={r['source_id']:r for r in csv.DictReader(open(args.manifest,newline=''))}
    summary=json.loads((root/'summary.json').read_text())

    by_id={}
    for s in summary.get('sources',[]):
        row=manifest.get(s['source_id'],{})
        eligible=truthy(row.get('training_eligible'))
        s['training_eligible']=eligible
        s['corpus_role']='training' if eligible else 'qc_or_holdout'
        if row.get('direct_media_url') and s.get('acquisition')=='browser_capture':
            # prepare_video_corpus treats any pre-positioned media as browser_capture.
            # Preserve the actual provenance when CI acquired bytes from a direct URL.
            s['acquisition']='preacquired_direct_media'
        by_id[s['source_id']]=s

    records=[]
    for line in (root/'index.jsonl').read_text().splitlines():
        if not line.strip(): continue
        r=json.loads(line)
        sm=by_id.get(r['source_id'],{})
        r['training_eligible']=bool(sm.get('training_eligible',False))
        r['corpus_role']=sm.get('corpus_role','qc_or_holdout')
        records.append(r)
    with open(root/'index.jsonl','w') as f:
        for r in records:
            f.write(json.dumps(r,sort_keys=True)+'\n')

    summary['clips_training_eligible']=sum(1 for r in records if r.get('accepted') and r.get('training_eligible'))
    summary['quality_gate']='A clip can train the policy only when motion QC passes AND its manifest source is explicitly training_eligible=yes after reuse/quality verification.'
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({'sources':[{k:s.get(k) for k in ['source_id','acquisition','training_eligible','corpus_role']} for s in summary.get('sources',[])],
                      'clips_training_eligible':summary['clips_training_eligible']},indent=2))

if __name__=='__main__':
    main()
