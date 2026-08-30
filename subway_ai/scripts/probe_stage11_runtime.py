#!/usr/bin/env python3
import json,time
from playwright.sync_api import sync_playwright
from evaluate_stage11_closed_loop import BROWSER_ARGS

with sync_playwright() as p:
    browser=p.chromium.launch(headless=False,args=BROWSER_ARGS)
    context=browser.new_context(viewport={'width':1280,'height':720},locale='en-US')
    page=context.new_page()
    out={'target':'https://poki.com/en/g/subway-surfers','samples':[]}
    try:
        page.goto(out['target'],wait_until='domcontentloaded',timeout=120000)
        for i in range(10):
            frames=[]
            for f in page.frames:
                try:
                    frames.append({'url':f.url,'pixi_count':f.locator('#pixi-canvas').count(),'canvas_count':f.locator('canvas').count()})
                except Exception as e:
                    frames.append({'url':f.url,'error':str(e)})
            try:
                iframe_srcs=page.locator('iframe').evaluate_all("els=>els.map(e=>e.src)")
            except Exception:
                iframe_srcs=[]
            out['samples'].append({'t':i*3,'page_url':page.url,'title':page.title(),'frames':frames,'iframe_srcs':iframe_srcs})
            if any(x.get('pixi_count',0)>0 for x in frames):
                out['found_pixi']=True
                break
            time.sleep(3)
        out.setdefault('found_pixi',False)
        print(json.dumps(out,indent=2),flush=True)
    finally:
        context.close();browser.close()
