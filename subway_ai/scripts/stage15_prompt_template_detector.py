#!/usr/bin/env python3
"""Fast pixels-only detector for Subway Surfers tutorial prompts.

Bootstrap-only sensing: this module never reads DOM/game internals and must never become learned
policy input. The canvas is normalized to 640x360, white glyph interiors adjacent to black outlines
are isolated, a shared "Press Arrow Key" prefix template establishes prompt presence, and an
independent suffix template classifies Up/Down/Left/Right. Matching is translation-invariant in Y,
so the detector tolerates the prompt moving vertically during tutorial animations.

Templates were extracted from visually verified v25 rendered frames and independently validated on
v24 footage.
"""
from __future__ import annotations
import base64
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import cv2
import numpy as np
from PIL import Image

NORMALIZED_SIZE=(640,360)
PRESENCE_THRESHOLD=0.55
SUFFIX_THRESHOLD=0.62
SUFFIX_MARGIN_THRESHOLD=0.08
PREFIX_SEARCH=(0.15,0.20,0.75,0.92)
SUFFIX_SEARCH=(0.35,0.20,0.80,0.92)

_PACKED={
    'prefix': ((47, 135), 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHwAAAAAAHgAAAAAABjgAAAA/gAAAAAA+AAAAAAAMcAAAAH8AAAAAAMwAAAAAABnAAAAAxyIIDAwBmESMMAAAM4GAAAGObHx+fgN43bnxzGB+B85wA5z5/ODgBnHz8/OYwIQfjOAH8MMZwcAc4cOOZzuBCDOZgA/Bh3Pj4DnDhhzmdwPwZj8AHgMPw8Pgf4YMOc3sBnD8NAAwBhgBwcDvjBhzG2gM8YB4AGAMOBOTg4ccMH488BjzEPAAwBg+Pj4HDjhg+DngMcPg4AAAABg4GAAAAABgAAAAAQOAAAAAAAAAAAAAAAAAAAAABwAAAAAAAAAAAAAAAAAAAAAOAAAAAAAAAAAAAAAAAAAAABgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='),
    'suffix_up': ((45, 73), 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABhgAAAAAAAAABxwAAAAAAAAAA44AAAAAAAwAAccAAAAAAA+c4OOdwAAAAAfGcHHP8AAAAAJzMDjj+AAAAAEx+BxxzgAAAAD4aA445wAAAABAPAf8cwAAAAAiHgH+P4AAAAAfBwB+H4AAAAACBwAIDgAAAAAAA4AABwAAAAAAAcAAA4AAAAAAAMAAAcAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'),
    'suffix_down': ((45, 73), 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+AAAAAAAAAAAfwAAAAAAAAAAP8AAAAAAAAAADPBAAARgAAAMBjj4xnf4AAAGAxz+Zzv8AAAHAY5nM9jmAAAHAM8zmexzAAABgGeYxvY5gAAAwD+M4v8cwAAAwD+H8eeOYAAAYB+B8POHMAAAMAAAIAAAAAAAEAAAAAAAAAAACAAAAAAAAAAAAAAAAAAAAAAAAIAAAAAAAAAAAcAAAAAAAAAAACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'),
    'suffix_left': ((45, 73), 'AAAAAAAYAAAAAAAAAAAGAAAAAAAAAAABgAAAAAAAAAAA4AAAAAAAAAAAGAAAAAAAAAAABgAAAAAAAAAAA4AAAAAAAAAAAGAAAAAAAAAAABgAAAAAAAAAAAYAAAAAAAAAAAGAAAAAAAAAAABAAAAAAAAAAAAQAAAAAAAAAAAGAAAAA4AAcAABwAAAAcAAeAAAYAAAAOAAMMAAGAAAAHAMOGAABwAnODgfP/wAAcATmBwf374AAFAIzA4MYwwAABwEfgcHcYYAAAMCHgOD8MMAAAHADwH5wEGAAABwB4D84DDAAAAcQ8B+PhhgAAAHAcIABgAAAAABwOAAAAAAAAAAcGAAAAAAAAAAGDAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'),
    'suffix_right': ((45, 73), 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPwwAAAAAAAAAHAAAAAAAAAAACAAAAAAAAAAABPg4AGAAAAAEPn8cADAAAAAABh/AADgMAAAAAQzgABwHAAAAjIZzh8/HwAAATkMxx+Pz4AAAN2H453OY4AAAGzD8cxnMcAAADZhuOYzmOAAABoA3nO5zGAAAAUk5zn85jgAAAKAc5x+MxwAAAEAAAADAAAAAAHAABABgAAAAADgAP8PwAAAAABgAAAHwAAAAAADAAAAAAAAAAAfgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'),
}

@dataclass(frozen=True)
class PromptDetection:
    direction: Optional[str]
    presence_score: float
    suffix_score: float
    suffix_margin: float
    suffix_scores: Dict[str,float]

def _unpack(shape: Tuple[int,int], encoded: str) -> np.ndarray:
    raw=np.frombuffer(base64.b64decode(encoded),dtype=np.uint8)
    bits=np.unpackbits(raw)[:shape[0]*shape[1]]
    return bits.reshape(shape).astype(np.float32)

_TEMPLATES={k:_unpack(*v) for k,v in _PACKED.items()}

def _rgb(image) -> np.ndarray:
    if isinstance(image,Image.Image):
        arr=np.asarray(image.convert("RGB"))
    else:
        arr=np.asarray(image)
        if arr.ndim==2:
            arr=np.repeat(arr[...,None],3,axis=2)
        elif arr.ndim==3 and arr.shape[2]>=3:
            arr=arr[...,:3]
        else:
            raise ValueError("expected PIL image or HxWx3-like array")
    return cv2.resize(arr,NORMALIZED_SIZE,interpolation=cv2.INTER_AREA)

def _outlined_white_mask(rgb: np.ndarray) -> np.ndarray:
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    local_min=cv2.erode(gray,np.ones((5,5),np.uint8))
    local_max=cv2.dilate(gray,np.ones((3,3),np.uint8))
    contrast=local_max.astype(np.int16)-local_min.astype(np.int16)
    return ((gray>=205)&(local_min<=90)&(contrast>=100)).astype(np.float32)

def _crop(mask: np.ndarray, box) -> np.ndarray:
    h,w=mask.shape;x1,y1,x2,y2=box
    return mask[int(y1*h):int(y2*h),int(x1*w):int(x2*w)]

def _match(search: np.ndarray, template: np.ndarray) -> float:
    if search.shape[0]<template.shape[0] or search.shape[1]<template.shape[1]:
        return 0.0
    res=cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED)
    if not res.size:
        return 0.0
    score=float(np.nanmax(res))
    return score if np.isfinite(score) else 0.0

def score_prompt_direction(image) -> PromptDetection:
    mask=_outlined_white_mask(_rgb(image))
    prefix_score=_match(_crop(mask,PREFIX_SEARCH),_TEMPLATES["prefix"])
    suffix_search=_crop(mask,SUFFIX_SEARCH)
    suffix_scores={
        d:_match(suffix_search,_TEMPLATES[f"suffix_{d}"])
        for d in ("up","down","left","right")
    }
    best=max(suffix_scores,key=suffix_scores.get)
    ordered=sorted(suffix_scores.values(),reverse=True)
    suffix_score=suffix_scores[best]
    margin=ordered[0]-ordered[1]
    direction=None
    if prefix_score>=PRESENCE_THRESHOLD and suffix_score>=SUFFIX_THRESHOLD and margin>=SUFFIX_MARGIN_THRESHOLD:
        direction=best
    return PromptDetection(direction,prefix_score,suffix_score,margin,suffix_scores)

def detect_prompt_direction(image) -> Optional[str]:
    return score_prompt_direction(image).direction
