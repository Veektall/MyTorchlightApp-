#!/usr/bin/env python3
import evaluate_stage11_closed_loop as stage11
from live_runtime_v2 import robust_open_game

stage11.open_game = robust_open_game

if __name__ == '__main__':
    stage11.main()
