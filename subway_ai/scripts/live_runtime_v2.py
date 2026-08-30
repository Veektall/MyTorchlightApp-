#!/usr/bin/env python3
import time


def focus_canvas(canvas):
    canvas.evaluate("c=>{c.tabIndex=0;c.focus()}")
    b=canvas.bounding_box()
    if b:
        try:
            canvas.click(position={'x':b['width']/2,'y':b['height']/2},force=True)
        except Exception:
            pass


def robust_open_game(browser, episode_id):
    """Open only the official Poki Subway Surfers page and locate its real Pixi canvas.

    The old evaluator assumed the game iframe hostname always contained
    `.gdn.poki.com`. The official page can change CDN/frame routing without changing
    the game. We therefore scan every frame belonging to the official page for the
    unique #pixi-canvas element, then retain the same strict WebGL gate.
    """
    context=browser.new_context(viewport={'width':1280,'height':720},locale='en-US')
    page=context.new_page()
    page.goto('https://poki.com/en/g/subway-surfers',wait_until='domcontentloaded',timeout=120000)
    deadline=time.time()+100
    game=None
    canvas=None
    seen=[]
    while time.time()<deadline:
        frames=list(page.frames)
        seen=[f.url for f in frames]
        # Prefer Poki/CDN frames, but accept the unique Pixi canvas from any frame
        # embedded by this official Poki page. This changes discovery only, never
        # gameplay state or policy inputs.
        ordered=sorted(frames,key=lambda f: 0 if ('poki.com' in f.url or 'poki-gdn' in f.url or 'gdn.poki' in f.url) else 1)
        for frame in ordered:
            try:
                c=frame.locator('#pixi-canvas')
                if c.count():
                    game=frame
                    canvas=c
                    break
            except Exception:
                continue
        if canvas is not None:
            break
        time.sleep(.65)
    if canvas is None:
        context.close()
        compact=' | '.join(seen[-12:])
        raise RuntimeError(f'official Pixi canvas not found; frame_urls={compact}')
    webgl=game.evaluate("""()=>{const c=document.createElement('canvas');const gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});if(!gl)return{ok:false};const e=gl.getExtension('WEBGL_debug_renderer_info');return{ok:true,stencil:gl.getParameter(gl.STENCIL_BITS),renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}}""")
    if not webgl.get('ok'):
        context.close()
        raise RuntimeError('strict WebGL gate failed')
    focus_canvas(canvas)
    return context,page,canvas,webgl
