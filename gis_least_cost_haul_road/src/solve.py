"""Reference least-cost alignment solver (golden) with switches for failure variants."""
import heapq
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BRIEF = json.loads((ROOT / "work" / "brief_values.json").read_text())

SQ2 = float(np.sqrt(2.0))
NBRS = [(-1, -1, SQ2), (-1, 0, 1.0), (-1, 1, SQ2), (0, -1, 1.0),
        (0, 1, 1.0), (1, -1, SQ2), (1, 0, 1.0), (1, 1, SQ2)]


def grade_factor(g):
    if g <= 3.0:
        return 1.0
    if g <= 6.0:
        return 1.0 + 0.05 * (g - 3.0)
    return 1.15 + 0.12 * (g - 6.0)


def load(opts):
    b = BRIEF
    dn = np.array(Image.open(ROOT / "inputs" / b["dem_file"]), dtype=np.float64)
    z_ft = b["dn_base_ft"] + b["dn_step_ft"] * dn
    z = z_ft * (1200.0 / 3937.0) if not opts.get("no_ft") else z_ft
    rgb = np.array(Image.open(ROOT / "inputs" / b["lc_file"]).convert("RGB"))
    code = np.zeros(rgb.shape[:2], np.uint8)
    for c, info in b["classes"].items():
        m = np.all(rgb == np.array(info["rgb"], np.uint8), axis=-1)
        code[m] = int(c)
    assert (code > 0).all(), "unmapped land-cover colour"
    ny, nx = dn.shape
    cell = b["dem_cell"]
    ex = b["dem_ul_e"] + cell * (np.arange(nx) + 0.5)
    ey = b["dem_ul_n"] - cell * (np.arange(ny) + 0.5)
    if opts.get("lc_same_origin"):
        # failure: assume land cover shares the DEM origin
        lj = np.floor((ex - b["dem_ul_e"]) / b["lc_cell"]).astype(int)
        li = np.floor((b["dem_ul_n"] - ey) / b["lc_cell"]).astype(int)
    else:
        lj = np.floor((ex - b["lc_ul_e"]) / b["lc_cell"]).astype(int)
        li = np.floor((b["lc_ul_n"] - ey) / b["lc_cell"]).astype(int)
    lcd = code[np.ix_(li, lj)]
    EX, EY = np.meshgrid(ex, ey)
    return z, lcd, EX, EY, code


def build_cost(opts):
    b = BRIEF
    z, lcd, EX, EY, lc_native = load(opts)
    to_utm = Transformer.from_crs(4326, b["epsg"], always_xy=True)
    pts = {k: to_utm.transform(v[1], v[0]) for k, v in b["points_latlon"].items()}
    base = np.full(z.shape, np.nan)
    for c, info in b["classes"].items():
        if info["cost"] is not None:
            base[lcd == int(c)] = info["cost"]
    # crossing windows
    for k in ("X1", "X2"):
        if opts.get("drop_" + k):
            continue
        d = np.hypot(EX - pts[k][0], EY - pts[k][1])
        base[(lcd == 6) & (d <= b["crossing_radius"])] = b["culvert_cost"]
    if opts.get("water_passable"):
        base[(lcd == 6) & np.isnan(base)] = b["culvert_cost"]
    # wetland setback measured to the edges of wetland land-cover cells
    if not opts.get("no_setback"):
        wi, wj = np.nonzero(lc_native == 7)
        half = b["lc_cell"] / 2
        cxs = b["lc_ul_e"] + b["lc_cell"] * (wj + 0.5)
        cys = b["lc_ul_n"] - b["lc_cell"] * (wi + 0.5)
        dmin = np.full(z.shape, np.inf)
        for cx_, cy_ in zip(cxs, cys):
            dx = np.maximum(np.abs(EX - cx_) - half, 0)
            dy = np.maximum(np.abs(EY - cy_) - half, 0)
            dmin = np.minimum(dmin, np.hypot(dx, dy))
        base[dmin <= b["wetland_setback"]] = np.nan
    if not opts.get("no_heritage"):
        h = pts["HERITAGE"]
        base[np.hypot(EX - h[0], EY - h[1]) <= b["heritage_radius"]] = np.nan
    return z, lcd, EX, EY, base, pts


def cell_of(pt):
    b = BRIEF
    j = int(np.floor((pt[0] - b["dem_ul_e"]) / b["dem_cell"]))
    i = int(np.floor((b["dem_ul_n"] - pt[1]) / b["dem_cell"]))
    return i, j


def slope_horn(z, cell):
    zp = np.pad(z, 1, mode="edge")
    a, bb, c = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    d, f = zp[1:-1, :-2], zp[1:-1, 2:]
    g, h, i = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * cell)
    dzdy = ((g + 2 * h + i) - (a + 2 * bb + c)) / (8 * cell)
    return 100 * np.hypot(dzdx, dzdy)


def solve(opts=None):
    opts = opts or {}
    b = BRIEF
    z, lcd, EX, EY, base, pts = build_cost(opts)
    cell = b["dem_cell"]
    ny, nx = z.shape
    iso = opts.get("isotropic")
    if iso:
        s = slope_horn(z, cell)
        base = base.copy()
        base[s > b["max_grade"]] = np.nan
    s_i, s_j = cell_of(pts["START"])
    e_i, e_j = cell_of(pts["END"])
    if opts.get("flip_rows"):
        s_i, e_i = ny - 1 - s_i, ny - 1 - e_i
    INF = np.inf
    dist = np.full((ny, nx), INF)
    prev = np.full((ny, nx), -1, np.int64)
    dist[s_i, s_j] = 0.0
    pq = [(0.0, s_i, s_j)]
    passable = ~np.isnan(base)
    while pq:
        dcur, i, j = heapq.heappop(pq)
        if dcur > dist[i, j]:
            continue
        if (i, j) == (e_i, e_j):
            break
        ci = base[i, j]
        for di, dj, k in NBRS:
            a, bq = i + di, j + dj
            if a < 0 or bq < 0 or a >= ny or bq >= nx or not passable[a, bq]:
                continue
            dd = k * cell
            if iso:
                f = grade_factor(min(s[i, j], s[a, bq])) if False else grade_factor((s[i, j] + s[a, bq]) / 2)
            else:
                g = abs(z[a, bq] - z[i, j]) / dd * 100.0
                if g > b["max_grade"]:
                    continue
                f = grade_factor(g)
            nd = dcur + dd * (ci + base[a, bq]) / 2.0 * f
            if nd < dist[a, bq]:
                dist[a, bq] = nd
                prev[a, bq] = i * nx + j
                heapq.heappush(pq, (nd, a, bq))
    if not np.isfinite(dist[e_i, e_j]):
        return None
    path = []
    cur = e_i * nx + e_j
    while cur != -1:
        path.append(divmod(int(cur), nx))
        cur = prev[path[-1]]
    path.reverse()
    return dict(z=z, lcd=lcd, EX=EX, EY=EY, base=base, pts=pts, path=path,
                cost=float(dist[e_i, e_j]), dist=dist)


def summarise(res):
    b = BRIEF
    cell = b["dem_cell"]
    z, lcd, path = res["z"], res["lcd"], res["path"]
    rows = []
    ch = 0.0
    cum = 0.0
    for k, (i, j) in enumerate(path):
        e, n = res["EX"][i, j], res["EY"][i, j]
        if k < len(path) - 1:
            a, bq = path[k + 1]
            dd = np.hypot(a - i, bq - j) * cell
            g = (z[a, bq] - z[i, j]) / dd * 100.0
            seg = dd * (res["base"][i, j] + res["base"][a, bq]) / 2 * grade_factor(abs(g))
        else:
            dd, g, seg = 0.0, float("nan"), 0.0
        rows.append(dict(seq=k + 1, easting=e, northing=n, elev_m=z[i, j], chainage_m=ch,
                         grade_pct=g, landcover=b["classes"][str(lcd[i, j])]["name"],
                         cum_cost_usd=cum))
        ch += dd
        cum += seg
    return rows, ch


if __name__ == "__main__":
    variants = {
        "golden": {},
        "no_ft_conversion": {"no_ft": True},
        "isotropic_slope": {"isotropic": True},
        "no_wetland_setback": {"no_setback": True},
        "no_heritage": {"no_heritage": True},
        "lc_same_origin": {"lc_same_origin": True},
        "water_passable_everywhere": {"water_passable": True},
    }
    sel = sys.argv[1:] or list(variants)
    for name in sel:
        r = solve(variants[name])
        if r is None:
            print(f"{name:28s} NO PATH")
            continue
        rows, L = summarise(r)
        g = max(abs(x["grade_pct"]) for x in rows[:-1])
        xs = [x for x in rows if x["landcover"] == "Watercourse"]
        xing = "none" if not xs else f"E{xs[0]['easting']:.0f} N{xs[0]['northing']:.0f}"
        print(f"{name:28s} cost ${r['cost']:,.0f}  L={L:,.1f} m  cells={len(rows)}  maxg={g:.2f}%  creek@{xing}")
