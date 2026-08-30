#!/usr/bin/env python3
import re
from PIL import ImageOps, ImageEnhance, Image
import pytesseract
import evaluate_stage15_pixel_evaluator_v2 as v2

s=v2.s


def direct_score_candidate(im):
    # Official Subway Surfers HUD: score is the fixed six-digit field at upper-right.
    # Read only rendered canvas pixels; exclude multiplier to the left and coins below.
    w,h=im.size
    roi=im.crop((int(w*.86),int(h*.015),int(w*.995),int(h*.12)))
    g=ImageOps.grayscale(roi).resize((roi.width*6,roi.height*6),Image.Resampling.BICUBIC)
    variants=[g,ImageEnhance.Contrast(g).enhance(2.5),g.point(lambda p:255 if p>150 else 0)]
    reads=[]
    for v in variants:
        for psm in (8,7,6,13):
            try:txt=pytesseract.image_to_string(v,config=f'--psm {psm} -c tessedit_char_whitelist=0123456789')
            except Exception:continue
            d=re.sub(r'\D','',txt)
            if 4<=len(d)<=8:
                reads.append(d)
    if not reads:return []
    # Prefer the modal read, then six-digit padded HUD form.
    from collections import Counter
    counts=Counter(reads)
    best=sorted(counts.items(),key=lambda kv:(kv[1],len(kv[0])==6,-abs(len(kv[0])-6)),reverse=True)[0][0]
    try:value=int(best)
    except Exception:return []
    return [{'value':value,'x':.9275,'y':.0675,'w':.135,'h':.105,'conf':99.0}]

s.digit_candidates=direct_score_candidate

if __name__=='__main__':
    s.main()
