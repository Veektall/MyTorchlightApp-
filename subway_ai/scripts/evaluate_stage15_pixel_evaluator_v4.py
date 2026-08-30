#!/usr/bin/env python3
import re
from collections import Counter
from PIL import ImageOps, ImageEnhance, Image
import pytesseract
import evaluate_stage15_pixel_evaluator_v3 as v3

s=v3.s


def six_digit_score_candidate(im):
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
            if 4<=len(d)<=8:reads.append(d)
    if not reads:return []
    exact=[d for d in reads if len(d)==6]
    pool=exact if exact else reads
    best=Counter(pool).most_common(1)[0][0]
    try:value=int(best)
    except Exception:return []
    return [{'value':value,'x':.9275,'y':.0675,'w':.135,'h':.105,'conf':99.0}]

s.digit_candidates=six_digit_score_candidate

if __name__=='__main__':
    s.main()
