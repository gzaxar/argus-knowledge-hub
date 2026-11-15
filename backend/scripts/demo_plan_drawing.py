"""The demo floor plans, redrawn as a room schedule: the drawing is app/services/plan_drawing.py (the same that draws
a plan from a layout in metres, "Draw a plan"). Used by scripts/rack_demos.py; on its own it redraws files in place:

    python scripts/demo_plan_drawing.py a.svg b.svg
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.plan_drawing import MARK, PX_PER_M, _fit, draw, read, redraw  # noqa: E402,F401

if __name__ == "__main__":
    for p in map(Path, sys.argv[1:]):
        p.write_text(redraw(p.read_text()))
