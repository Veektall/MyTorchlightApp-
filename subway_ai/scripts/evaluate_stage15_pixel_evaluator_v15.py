#!/usr/bin/env python3
import evaluate_stage15_pixel_evaluator_v13 as v13

s = v13.s
_raw_open_game = v13.v12._base_open_game

class ProvenTrustedCanvas:
    """Use the independently verified Subway Surfers actuator exactly.

    Contract proven by the earlier input probe:
      1. make #pixi-canvas focusable,
      2. focus/click it,
      3. locator.press(key, delay=180).

    Do not clamp the hold duration and do not substitute synthetic DOM events.
    """
    def __init__(self, locator):
        self._locator = locator

    def __getattr__(self, name):
        return getattr(self._locator, name)

    def press(self, key, delay=None):
        try:
            self._locator.evaluate("c=>{c.tabIndex=0;c.focus()}")
        except Exception:
            pass
        try:
            b = self._locator.bounding_box()
            if b:
                self._locator.click(
                    position={'x': b['width']/2, 'y': b['height']/2},
                    force=True,
                )
        except Exception:
            pass
        # Exact trusted path: preserve at least the 180 ms duration that was
        # independently validated by capture-phase key event logging.
        hold = max(180, int(delay or 180))
        self._locator.press(key, delay=hold)


def open_game_proven_input(browser, video_dir):
    context, page, canvas = _raw_open_game(browser, video_dir)
    return context, page, ProvenTrustedCanvas(canvas)

s.open_game = open_game_proven_input

if __name__ == '__main__':
    s.main()
