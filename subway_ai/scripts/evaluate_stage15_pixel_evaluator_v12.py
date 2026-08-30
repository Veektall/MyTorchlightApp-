#!/usr/bin/env python3
import evaluate_stage15_pixel_evaluator_v11 as v11

s = v11.s
_base_open_game = s.open_game

KEYCODES = {
    'ArrowLeft': 37, 'ArrowUp': 38, 'ArrowRight': 39, 'ArrowDown': 40,
    'Space': 32, 'Enter': 13,
}

class InputCanvasProxy:
    """Locator-compatible wrapper with iframe-local keyboard event fallback.

    Poki's current Subway Surfers build can render and focus normally while
    Playwright Locator.press() fails to reach the game's keyboard listener.
    Dispatch the equivalent key events inside the canvas' own frame so both
    tutorial bootstrap and benchmark policy share the same reliable actuator.
    """
    def __init__(self, locator):
        self._locator = locator

    def __getattr__(self, name):
        return getattr(self._locator, name)

    def press(self, key, delay=None):
        try:
            self._locator.evaluate('(el)=>{try{el.focus()}catch(e){}}')
        except Exception:
            pass
        # Keep the native Playwright path for compatibility.
        try:
            self._locator.press(key, delay=min(int(delay or 0), 60))
        except Exception:
            pass
        kc = int(KEYCODES.get(key, 0))
        payload = {'key': key, 'code': key, 'kc': kc}
        self._locator.evaluate("""(el,p)=>{
            const mk=(type)=>{
                const e=new KeyboardEvent(type,{key:p.key,code:p.code,bubbles:true,cancelable:true});
                try{Object.defineProperty(e,'keyCode',{get:()=>p.kc})}catch(_){}
                try{Object.defineProperty(e,'which',{get:()=>p.kc})}catch(_){}
                return e;
            };
            const targets=[window,document,document.body,el].filter(Boolean);
            for(const t of targets){try{t.dispatchEvent(mk('keydown'))}catch(_){}}
            for(const t of targets){try{t.dispatchEvent(mk('keyup'))}catch(_){}}
        }""", payload)


def open_game_with_reliable_input(browser, video_dir):
    context, page, canvas = _base_open_game(browser, video_dir)
    return context, page, InputCanvasProxy(canvas)


s.open_game = open_game_with_reliable_input

if __name__ == '__main__':
    s.main()
