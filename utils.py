"""Utility helpers (color detection, screenshots, timing helpers)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Sequence, Tuple

import pyautogui
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BASE_DIR / "scripts"
PROGRAMS_DIR = BASE_DIR / "programs"

for _p in (SCRIPTS_DIR, PROGRAMS_DIR):
    _p.mkdir(exist_ok=True)


def screenshot_area(x: int, y: int, w: int, h: int, out: Path | str) -> None:
    """Capture rectangular region to *out* PNG."""
    region = (x, y, w, h)
    pyautogui.screenshot(region=region).save(out)


def find_color_mean(
    img_path: Path | str,
    target: Tuple[int, int, int],
    *,
    offset: Tuple[int, int] = (0, 0),
    tolerance: int = 10,
) -> Tuple[int, int] | None:
    """Return mean (x,y) of all pixels within *tolerance* of *target*."""
    with Image.open(img_path) as img:
        matches: list[Tuple[int, int]] = []
        px = img.load()
        w, h = img.size
        for yy in range(h):
            for xx in range(w):
                r, g, b = px[xx, yy][:3]
                if all(abs(c - t) <= tolerance for c, t in zip((r, g, b), target)):
                    matches.append((offset[0] + xx, offset[1] + yy))
        if not matches:
            return None
        mx = sum(x for x, _ in matches) / len(matches)
        my = sum(y for _, y in matches) / len(matches)
        return int(mx), int(my)


def save_json(obj: object, path: Path | str) -> None:
    Path(path).write_text(json.dumps(obj, indent=4))


def load_json(path: Path | str):
    return json.loads(Path(path).read_text())