#!/usr/bin/env python3
import evaluate_stage15_pixel_evaluator_v13 as v13

s = v13.s
_raw_open_game = v13.v12._base_open_game
KEYCODES={'ArrowLeft':37,'ArrowUp':38,'ArrowRight':39,'ArrowDown':40,'Space':32,'Enter':13}

class TrustedKeyboardCanvas:
    def __init__(self, locator, page):
        self._locator=locator; self._page=page
    def __getattr__(self,name):
        return getattr(self._locator,name)
    def press(self,key,delay=None):
        # Explicitly make the game canvas the focused element in its iframe.
        try:
            self._locator.evaluate("c=>{c.tabIndex=0;c.focus()}")
            b=self._locator.bounding_box()
            if b:
                self._locator.click(position={'x':b['width']/2,'y':b['height']/2},force=True)
        except Exception:
            pass
        # Primary path: Playwright keyboard/CDP events. These follow browser input
        # routing to the focused iframe instead of relying on untrusted DOM events.
        try:
            self._page.keyboard.press(key,delay=min(int(delay or 0),90))
            return
        except Exception:
            pass
        # Compatibility fallbacks.
        try:
            self._locator.press(key,delay=min(int(delay or 0),60))
            return
        except Exception:
            pass
        kc=int(KEYCODES.get(key,0));payload={'key':key,'code':key,'kc':kc}
        try:
            self._locator.evaluate("""(el,p)=>{
              const mk=(type)=>{const e=new KeyboardEvent(type,{key:p.key,code:p.code,bubbles:true,cancelable:true});
                try{Object.defineProperty(e,'keyCode',{get:()=>p.kc})}catch(_){};try{Object.defineProperty(e,'which',{get:()=>p.kc})}catch(_){};return e};
              for(const t of [window,document,document.body,el].filter(Boolean)){try{t.dispatchEvent(mk('keydown'));t.dispatchEvent(mk('keyup'))}catch(_){}}
            }""",payload)
        except Exception:
            pass


def open_game_trusted_keyboard(browser,video_dir):
    context,page,canvas=_raw_open_game(browser,video_dir)
    return context,page,TrustedKeyboardCanvas(canvas,page)

s.open_game=open_game_trusted_keyboard

if __name__=='__main__':
    s.main()
