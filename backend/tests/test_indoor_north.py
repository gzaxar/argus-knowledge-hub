"""Where north is on a floor plan placed on the map, for the north arrow and a phone's compass (the plan is shown
as drawn: north is wherever the drawing put it)."""
import math
from types import SimpleNamespace

import pytest

from app.services import indoor

LAT0, LON0 = 41.8217, 12.6726                       # Frascati
KY = 111_320.0
KX = KY * math.cos(math.radians(LAT0))


def plan_turned(top_faces: float, w=1000, h=800, m_per_px=0.05):
    """A plan whose picture's top faces compass bearing `top_faces` (0: drawn north-up), placed by three points."""
    b = math.radians(top_faces)

    def lonlat(x, y):
        dx, dy = (x - w / 2) * m_per_px, (y - h / 2) * m_per_px          # right, down on the picture
        # The picture's right faces bearing b + 90°, its up faces b; a bearing's unit vector is (sin, cos).
        east = dx * math.cos(b) - dy * math.sin(b)
        north = -dx * math.sin(b) - dy * math.cos(b)
        return LON0 + east / KX, LAT0 + north / KY
    pts = [{"x": x, "y": y, "longitude": lonlat(x, y)[0], "latitude": lonlat(x, y)[1]}
           for x, y in ((100, 100), (900, 700), (850, 150))]
    fit = indoor.fit(pts, w, h)
    return SimpleNamespace(transform=fit["transform"], width_px=w, height_px=h)


@pytest.mark.parametrize("top_faces", [0, 30, 90, 180, 270])
def test_north_is_where_the_drawing_puts_it(top_faces):
    north = indoor.north_deg(plan_turned(top_faces))
    expected = (360 - top_faces) % 360                  # top facing east (90°): north is to the left (270°)
    assert min(abs(north - expected), 360 - abs(north - expected)) < 0.05
    c = indoor.centre(plan_turned(top_faces))
    assert c["latitude"] == pytest.approx(LAT0, abs=1e-6) and c["longitude"] == pytest.approx(LON0, abs=1e-6)


def test_a_plan_not_on_the_map_has_no_north():
    plan = SimpleNamespace(transform=None, width_px=10, height_px=10)
    assert indoor.north_deg(plan) is None and indoor.centre(plan) is None
