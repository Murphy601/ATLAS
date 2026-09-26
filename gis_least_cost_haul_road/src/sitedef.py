"""Synthetic site definition for the Cedar Bluff haul road task (Rev C).

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
# C-003 haul-truck operating criteria (Rev C)
FORMATION_WIDTH = 14.0          # limit of road, 7.0 m each side of the centreline
STEEP_GRADE = 8.0               # moves steeper than this count towards a sustained run
STEEP_RUN_MAX = 60.0            # max horizontal length of a sustained run
MAX_DEFLECTION_DEG = 45.0       # max change of travel direction between consecutive moves

# escarpment (Cedar Bluff) geometry, local metres
ESC_H = 45.0
ESC_W = 225.0
CHUTE_Y, CHUTE_HALF, CHUTE_W = 1105.0, 40.0, 520.0
GAP_Y, GAP_HALF, GAP_W = 1500.0, 90.0, 1000.0
SPUR_Y, SPUR_GRADE, SPUR_FALL = 1805.0, 0.092, 0.35
SLUMP_Y, SLUMP_HALF, SLUMP_W = 2600.0, 230.0, 700.0

PTS_UTM = {
    "START": (583000 + 153.2, N0 + 402.6),     # county road tie-in
    "END": (583000 + 3318.4, N0 + 1616.9),     # quarry plant gate
    "X1": (None, N0 + 2010.0),                 # crossing windows, x filled below
    "X2": (None, N0 + 880.0),
    "HERITAGE": (None, N0 + GAP_Y + 1.9),
}


def creek_x(y):
    return 1500.0 + 120.0 * np.sin(y / 450.0)


def creek_lc_x(y):
    # the mapped channel runs straight past wetland W-1 (reach X-1)
    return np.where(np.abs(y - 2010.0) < 260.0, creek_x(2010.0), creek_x(y))


def toe_x(y):
    return 2700.0 + 40.0 * np.sin(y / 520.0)


def _smooth(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def _lowland(x, y):
    z = 370.0 + 0.02 * x + 0.004 * y
    dx = x - creek_x(y)
    z -= 20.0 * np.exp(-(dx / 200.0) ** 2)
    z += 16.0 * np.exp(-(((x - 700.0) / 260.0) ** 2 + ((y - 1150.0) / 220.0) ** 2))
    z += 2.2 * np.sin(x / 97.0 + 0.7) * np.cos(y / 131.0 - 0.3)
    z += 1.3 * np.sin((x + 2 * y) / 173.0 + 1.9)
    z += 0.35 * np.cos((3 * x - y) / 83.0 + 0.4)
    return z


def _notch(z_face, x, y, yc, half, width, h):
    """Re-entrant valley cut into the escarpment: gentler face of horizontal width `width`."""
    z_in = h * _smooth((x - toe_x(y)) / width)
    w = _smooth((np.abs(y - yc) - half) / 20.0)
    return z_in + (z_face - z_in) * w


def escarpment_rel(x, y):
    h = ESC_H
    z = h * _smooth((x - toe_x(y)) / ESC_W)
    z = _notch(z, x, y, SLUMP_Y, SLUMP_HALF, SLUMP_W, h)
    z = _notch(z, x, y, CHUTE_Y, CHUTE_HALF, CHUTE_W, h)
    z = _notch(z, x, y, GAP_Y, GAP_HALF, GAP_W, h)
    return z


def terrain_m(x, y):
    z = _lowland(x, y) + escarpment_rel(x, y)
    # spur: a one-cell crest projecting west from the plateau at a constant grade
    x_top = toe_x(SPUR_Y) + ESC_W
    z_top = _lowland(x_top, SPUR_Y) + ESC_H
    crest = z_top - SPUR_GRADE * (x_top - x)
    spur = np.where(x <= x_top, crest - SPUR_FALL * np.abs(y - SPUR_Y), -np.inf)
    return np.maximum(z, spur)


def face_slope_pct(x, y, h=1.0):
    gx = (terrain_m(x + h, y) - terrain_m(x - h, y)) / (2 * h)
    gy = (terrain_m(x, y + h) - terrain_m(x, y - h)) / (2 * h)
    return 100 * np.hypot(gx, gy)


def _fill_points():
    # offsets keep every DEM cell centre clear of the 30 m window boundary
    for k, off in (("X1", 2.9), ("X2", 2.25)):
        y = PTS_UTM[k][1] - N0
        PTS_UTM[k] = (583000 + float(creek_x(y)) + off, PTS_UTM[k][1])
    PTS_UTM["HERITAGE"] = (583000 + float(toe_x(GAP_Y)) + 301.7, PTS_UTM["HERITAGE"][1])


_fill_points()


def landcover_codes():
    """Return LC grid (LC_NY x LC_NX), row 0 = north."""
    lc = np.ones((LC_NY, LC_NX), dtype=np.uint8)
    cx = LC_UL_E + LC_CELL * (np.arange(LC_NX) + 0.5) - E0
    cy = LC_UL_N - LC_CELL * (np.arange(LC_NY) + 0.5) - N0
    X, Y = np.meshgrid(cx, cy)

    crop = (X < 1150) & (Y < 1700) & (Y > 150) & ~((X > 500) & (X < 950) & (Y > 900) & (Y < 1400))
    lc[crop] = 2
    ripar = np.abs(X - creek_x(Y)) < 210
    lc[ripar] = 3
    wood2 = ((X - 2150) / 260) ** 2 + ((Y - 700) / 380) ** 2 < 1
    lc[wood2] = 3
    wood3 = ((X - 700) / 350) ** 2 + ((Y - 2300) / 260) ** 2 < 1
    lc[wood3] = 3
    # rock outcrop on the steep bluff face
    rock = (face_slope_pct(X, Y) > 18.0) & (X > 2400) & (np.abs(Y - SPUR_Y) > 20.0)
    lc[rock] = 4
    farm = (np.abs(X - 1150) < 50) & (np.abs(Y - 2140) < 40)
    lc[farm] = 8

    track = [(140, 420), (420, 700), (760, 1000), (980, 1560), (1060, 1900), (1150, 2090)]
    _burn_polyline(lc, X, Y, track, 5, halfwidth=11.0)

    for i in range(LC_NY):
        yc = cy[i]
        xc = creek_lc_x(yc)
        j = int(np.floor((xc + E0 - LC_UL_E) / LC_CELL))
        lc[i, j] = 6
        if i > 0:
            jp = int(np.floor((creek_lc_x(cy[i - 1]) + E0 - LC_UL_E) / LC_CELL))
            lo, hi = sorted((j, jp))
            lc[i, lo:hi + 1] = 6
    # wetland on the west bank near X1, separated from the creek by two
    # 20 m land-cover columns of riparian woodland
    for i in range(LC_NY):
        if not (WET_Y0 <= cy[i] <= WET_Y1):
            continue
        t = (cy[i] - 0.5 * (WET_Y0 + WET_Y1)) / (0.5 * (WET_Y1 - WET_Y0))
        width = max(1, int(round(WET_W * np.sqrt(max(0.0, 1 - t * t)))))
        jc = int(np.floor((creek_lc_x(cy[i]) + E0 - LC_UL_E) / LC_CELL))
        lc[i, jc - WET_GAP - width:jc - WET_GAP] = 7
    return lc


WET_Y0, WET_Y1, WET_W, WET_GAP = 1830.0, 2190.0, 6, 2


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
    _clear_threshold_bands(dn)
    assert dn.min() > 0 and dn.max() < 65535, (dn.min(), dn.max())
    return dn.astype(np.uint16)


def _clear_threshold_bands(dn, band=0.02):
    """No neighbour move may grade within (T, T+band] of a published threshold, so rounding
    conventions and foot definitions cannot flip a move across 8 % or 10 %."""
    step_m = DN_STEP_FT * FT_US
    for _ in range(50):
        changed = False
        ny, nx = dn.shape
        for di, dj in ((0, 1), (1, 0), (1, 1), (1, -1)):
            L = DEM_CELL * np.hypot(di, dj)
            j0, j1 = max(0, -dj), nx - max(0, dj)
            a = dn[0:ny - di, j0:j1]
            b = dn[di:ny, j0 + dj:j1 + dj]
            g = np.abs(b - a) * step_m / L * 100.0
            bad = np.zeros(g.shape, bool)
            for t in (STEEP_GRADE, MAX_GRADE):
                bad |= (g > t) & (g <= t + band)
            for i, j in zip(*np.nonzero(bad)):
                ia, ja, ib, jb = i, j + j0, i + di, j + j0 + dj
                if dn[ib, jb] >= dn[ia, ja]:
                    dn[ib, jb] += 1
                else:
                    dn[ia, ja] += 1
                changed = True
        if not changed:
            return
    raise RuntimeError("threshold bands not cleared")
