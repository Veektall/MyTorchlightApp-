#!/usr/bin/env python3
import time
import evaluate_stage15_pixel_evaluator as s


def robust_recording_open_game(browser, video_dir):
    context=browser.new_context(
        viewport={'width':1280,'height':720},locale='en-US',
        record_video_dir=str(video_dir),record_video_size={'width':1280,'height':720})
    page=context.new_page()
    page.goto('https://poki.com/en/g/subway-surfers',wait_until='domcontentloaded',timeout=120000)
    deadline=time.time()+100;game=None;canvas=None;seen=[]
    while time.time()<deadline:
        frames=list(page.frames);seen=[f.url for f in frames]
        ordered=sorted(frames,key=lambda f:0 if ('poki.com' in f.url or 'poki-gdn' in f.url or 'gdn.poki' in f.url) else 1)
        for frame in ordered:
            try:
                c=frame.locator('#pixi-canvas')
                if c.count():game=frame;canvas=c;break
            except Exception:continue
        if canvas is not None:break
        time.sleep(.65)
    if canvas is None:
        context.close();raise RuntimeError('official Pixi canvas not found; frame_urls='+' | '.join(seen[-12:]))
    webgl=game.evaluate("""()=>{const c=document.createElement('canvas');const gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});if(!gl)return{ok:false};const e=gl.getExtension('WEBGL_debug_renderer_info');return{ok:true,stencil:gl.getParameter(gl.STENCIL_BITS),renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}}""")
    if not webgl.get('ok'):
        context.close();raise RuntimeError('strict WebGL gate failed')
    s.focus_canvas(canvas)
    return context,page,canvas

s.open_game=robust_recording_open_game

if __name__=='__main__':
    s.main()
