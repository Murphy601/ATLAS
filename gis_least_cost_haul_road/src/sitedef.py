"""Synthetic site definition for the Cedar Bluff haul road task.

All geometry is authored here from analytic functions; nothing is derived
from third-party data.  Local coordinates: x east, y north, metres, origin at
the south-west corner of the DEM extent.
"""
import numpy as np

EPSG = 32614
DEM_UL_E, DEM_UL_N = 583000.0, 3351500.0
DEM_CELL = 10.0
DEM_NX, DEM_NY = 360, 280
LC_UL_E, LC_UL_N = 582900.0, 3351620.0
LC_CELL = 20.0
LC_NX, LC_NY = 190, 150

FT_US = 1200.0 / 3937.0
DN_BASE_FT, DN_STEP_FT = 1150.00, 0.01

E0 = DEM_UL_E
N0 = DEM_UL_N - DEM_NY * DEM_CELL

# land-cover classes: code -> (name, RGB, base unit cost USD/m or None if prohibited)
CLASSES = {
    1: ("Grassland / pasture", (201, 222, 150), 420.0),
    2: ("Cultivated cropland", (240, 214, 120), 480.0),
    3: ("Woodland", (86, 140, 72), 940.0),
    4: ("Rock outcrop", (168, 150, 140), 1150.0),
    5: ("Existing gravel track", (120, 72, 40), 160.0),
    6: ("Watercourse", (60, 120, 220), None),
    7: ("Wetland", (150, 200, 210), None),
    8: ("Farmstead / structures", (220, 60, 60), None),
}
CULVERT_COST = 3800.0
CROSSING_RADIUS = 30.0
WETLAND_SETBACK = 30.0
HERITAGE_RADIUS = 150.0
MAX_GRADE = 10.0

# key points in UTM (authored); published to the brief as WGS84 lat/long
PTS_UTM = {
    "START": (583000 + 153.2, N0 + 402.6),     # county road tie-in
    "END": (583000 + 3318.4, N0 + 2296.9),     # quarry plant gate
    "X1": (None, N0 + 2010.0),                 # crossing windows, x filled below
    "X2": (None, N0 + 880.0),
    "HERITAGE": (583000 + 2511.9, N0 + 1501.9),
}


def creek_x(y):
    return 1500.0 + 120.0 * np.sin(y / 450.0)


def ridge_x(y):
    return 2500.0 + 80.0 * np.sin(y / 600.0 + 1.0)


def terrain_m(x, y):
    z = 370.0 + 0.02 * x + 0.004 * y
    # creek valley
    dx = x - creek_x(y)
    z -= 20.0 * np.exp(-(dx / 200.0) ** 2)
    # ridge with a saddle near y = 1500, fading out to the north
    dr = x - ridge_x(y)
    h = 58.0 - 32.0 * np.exp(-((y - 1500.0) / 230.0) ** 2)
    h *= 1.0 / (1.0 + np.exp((y - 2560.0) / 70.0))
    z += h * np.exp(-(dr / 170.0) ** 2)
    # quarry plateau east of the ridge
    z += 18.0 / (1.0 + np.exp(-(x - 2900.0) / 120.0))
    # knoll south-west
    z += 16.0 * np.exp(-(((x - 700.0) / 260.0) ** 2 + ((y - 1150.0) / 220.0) ** 2))
    # gentle texture
    z += 2.2 * np.sin(x / 97.0 + 0.7) * np.cos(y / 131.0 - 0.3)
    z += 1.3 * np.sin((x + 2 * y) / 173.0 + 1.9)
    z += 0.35 * np.cos((3 * x - y) / 83.0 + 0.4)
    return z


def _fill_crossings():
    # offsets keep every DEM cell centre >= 1 m from the 30 m window boundary
    for k, off in (("X1", 2.9), ("X2", 2.25)):
        y = PTS_UTM[k][1] - N0
        PTS_UTM[k] = (583000 + float(creek_x(y)) + off, PTS_UTM[k][1])


_fill_crossings()


def landcover_codes():
    """Return LC grid (LC_NY x LC_NX), row 0 = north."""
    lc = np.ones((LC_NY, LC_NX), dtype=np.uint8)
    cx = LC_UL_E + LC_CELL * (np.arange(LC_NX) + 0.5) - E0
    cy = LC_UL_N - LC_CELL * (np.arange(LC_NY) + 0.5) - N0
    X, Y = np.meshgrid(cx, cy)

    # cropland west of creek, south half
    crop = (X < 1150) & (Y < 1700) & (Y > 150) & ~((X > 500) & (X < 950) & (Y > 900) & (Y < 1400))
    lc[crop] = 2
    # woodland: riparian band + ridge east flank + patch north-west
    ripar = np.abs(X - creek_x(Y)) < 210
    lc[ripar] = 3
    wood2 = ((X - 2150) / 260) ** 2 + ((Y - 700) / 380) ** 2 < 1
    lc[wood2] = 3
    wood3 = ((X - 700) / 350) ** 2 + ((Y - 2300) / 260) ** 2 < 1
    lc[wood3] = 3
    # rock outcrop on ridge crest south and north of saddle
    rdr = np.abs(X - ridge_x(Y))
    rock = (rdr < 110) & (np.abs(Y - 1500) > 330) & (Y < 2450)
    lc[rock] = 4
    rock2 = ((X - 2830) / 150) ** 2 + ((Y - 1900) / 120) ** 2 < 1
    lc[rock2] = 4
    # farmstead north-west of X1
    farm = (np.abs(X - 1150) < 50) & (np.abs(Y - 2140) < 40)
    lc[farm] = 8

    # existing gravel track: polyline from county road to farmstead
    track = [(140, 420), (420, 700), (760, 1000), (980, 1560), (1060, 1900), (1150, 2090)]
    _burn_polyline(lc, X, Y, track, 5, halfwidth=11.0)

    # watercourse: 4-connected rasterisation of the creek centreline
    for i in range(LC_NY):
        yc = cy[i]
        xc = creek_x(yc)
        j = int(np.floor((xc + E0 - LC_UL_E) / LC_CELL))
        lc[i, j] = 6
        if i > 0:
            jp = int(np.floor((creek_x(cy[i - 1]) + E0 - LC_UL_E) / LC_CELL))
            lo, hi = sorted((j, jp))
            lc[i, lo:hi + 1] = 6
    # wetland on the west bank near X1, separated from the creek by one
    # 20 m land-cover column of riparian woodland
    for i in range(LC_NY):
        if not (WET_Y0 <= cy[i] <= WET_Y1):
            continue
        t = (cy[i] - 0.5 * (WET_Y0 + WET_Y1)) / (0.5 * (WET_Y1 - WET_Y0))
        width = max(1, int(round(WET_W * np.sqrt(max(0.0, 1 - t * t)))))
        jc = int(np.nonzero(lc[i] == 6)[0].min())
        lc[i, jc - 1 - width:jc - 1] = 7
    return lc


WET_Y0, WET_Y1, WET_W = 1830.0, 2190.0, 6


def _burn_polyline(lc, X, Y, pts, code, halfwidth):
    P = np.stack([X, Y], -1)
    mask = np.zeros(X.shape, bool)
    for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
        a = np.array([x1, y1]); b = np.array([x2, y2])
        ab = b - a
        t = np.clip(((P - a) @ ab) / (ab @ ab), 0, 1)
        d = np.linalg.norm(P - (a + t[..., None] * ab), axis=-1)
        mask |= d <= halfwidth
    lc[mask & (lc != 7) & (lc != 8)] = code


def dem_dn():
    cx = E0 + DEM_CELL * (np.arange(DEM_NX) + 0.5) - E0
    cy = DEM_UL_N - DEM_CELL * (np.arange(DEM_NY) + 0.5) - N0
    X, Y = np.meshgrid(cx, cy)
    z_m = terrain_m(X, Y)
    z_ft = z_m / FT_US
    dn = np.round((z_ft - DN_BASE_FT) / DN_STEP_FT).astype(np.int64)
    assert dn.min() > 0 and dn.max() < 65535, (dn.min(), dn.max())
    return dn.astype(np.uint16)
