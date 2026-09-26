"""Reference least-cost alignment solver (golden) with switches for failure variants.

The search runs on an expanded state graph (cell, heading of the last move, sustained-steep-run
state), so the C-003 tracking and sustained-grade criteria are enforced exactly.
"""
import json
import sys
from pathlib import Path

import numba as nb
import numpy as np
from PIL import Image
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BRIEF = json.loads((ROOT / "work" / "brief_values.json").read_text())

SQ2 = float(np.sqrt(2.0))
# heading index -> (d_row, d_col); 0 = north, clockwise
DIRS = np.array([(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)], np.int64)
DLEN = np.array([1.0, SQ2, 1.0, SQ2, 1.0, SQ2, 1.0, SQ2])


def grade_factor(g):
    if g <= 3.0:
        return 1.0
    if g <= 6.0:
        return 1.0 + 0.05 * (g - 3.0)
    return 1.15 + 0.12 * (g - 6.0)


def run_states(run_max, cell):
    """Enumerate (orthogonal, diagonal) steep-move counts whose horizontal length fits run_max."""
    st = [(a, b) for b in range(20) for a in range(20) if cell * (a + SQ2 * b) <= run_max + 1e-9]
    idx = {s: k for k, s in enumerate(st)}
    nxt = np.full((len(st), 2), -1, np.int64)
    for k, (a, b) in enumerate(st):
        nxt[k, 0] = idx.get((a + 1, b), -1)
        nxt[k, 1] = idx.get((a, b + 1), -1)
    return st, nxt


def load(opts):
    b = BRIEF
    dn = np.array(Image.open(ROOT / "inputs" / b["dem_file"]), dtype=np.float64)
    z_ft = b["dn_base_ft"] + b["dn_step_ft"] * dn
    ft = 0.3048 if opts.get("intl_ft") else 1200.0 / 3937.0
    z = z_ft * ft if not opts.get("no_ft") else z_ft
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
    lj = np.floor((ex - b["lc_ul_e"]) / b["lc_cell"]).astype(int)
    li = np.floor((b["lc_ul_n"] - ey) / b["lc_cell"]).astype(int)
    lcd = code[np.ix_(li, lj)]
    EX, EY = np.meshgrid(ex, ey)
    return z, lcd, EX, EY, code


def _seg_point_dist(ax, ay, bx, by, px, py):
    vx, vy = bx - ax, by - ay
    t = np.clip(((px - ax) * vx + (py - ay) * vy) / np.maximum(vx * vx + vy * vy, 1e-12), 0, 1)
    return np.hypot(ax + t * vx - px, ay + t * vy - py)


def _seg_box_dist(ax, ay, bx, by, x0, x1, y0, y1):
    """Exact distance from segments to an axis-aligned box (0 if they meet)."""
    def pbox(px, py):
        return np.hypot(np.maximum(np.maximum(x0 - px, 0), px - x1), np.maximum(np.maximum(y0 - py, 0), py - y1))
    d = np.minimum(pbox(ax, ay), pbox(bx, by))
    for cx, cy in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
        d = np.minimum(d, _seg_point_dist(ax, ay, bx, by, cx, cy))
    # segment passing through the box (slab clipping)
    t0 = np.zeros(np.shape(ax)); t1 = np.ones(np.shape(ax)); hit = np.ones(np.shape(ax), bool)
    for p, v, lo, hi in ((ax, bx - ax, x0, x1), (ay, by - ay, y0, y1)):
        par = np.abs(v) < 1e-12
        hit &= ~(par & ((p < lo) | (p > hi)))
        with np.errstate(divide="ignore", invalid="ignore"):
            ta = np.where(par, -np.inf, (lo - p) / v)
            tb = np.where(par, np.inf, (hi - p) / v)
        t0 = np.maximum(t0, np.minimum(ta, tb))
        t1 = np.minimum(t1, np.maximum(ta, tb))
    hit &= t0 <= t1
    return np.where(hit, 0.0, d)


def build_cost(opts):
    b = BRIEF
    z, lcd, EX, EY, lc_native = load(opts)
    to_utm = Transformer.from_crs(4326, b["epsg"], always_xy=True)
    pts = {k: to_utm.transform(v[1], v[0]) for k, v in b["points_latlon"].items()}
    base = np.full(z.shape, np.nan)
    for c, info in b["classes"].items():
        if info["cost"] is not None:
            base[lcd == int(c)] = info["cost"]
    for k in ("X1", "X2"):
        if opts.get("drop_" + k):
            continue
        d = np.hypot(EX - pts[k][0], EY - pts[k][1])
        base[(lcd == 6) & (d <= b["crossing_radius"])] = b["culvert_cost"]

    ny, nx = z.shape
    half = 0.0 if opts.get("no_width") else b["formation_width"] / 2.0
    move_ok = np.ones((ny, nx, 8), bool)
    # moves leaving the grid
    for h, (di, dj) in enumerate(DIRS):
        if di < 0: move_ok[0, :, h] = False
        if di > 0: move_ok[-1, :, h] = False
        if dj < 0: move_ok[:, 0, h] = False
        if dj > 0: move_ok[:, -1, h] = False
    cell = b["dem_cell"]
    AX = EX[..., None] + 0 * DIRS[:, 1]
    AY = EY[..., None] + 0 * DIRS[:, 0]
    BX = EX[..., None] + cell * DIRS[:, 1]
    BY = EY[..., None] - cell * DIRS[:, 0]
    if opts.get("vertex_only"):
        AX, AY = BX, BY   # clearance checked at the destination vertex only
    if not opts.get("no_setback"):
        wi, wj = np.nonzero(lc_native == 7)
        lh = b["lc_cell"] / 2
        cxs = b["lc_ul_e"] + b["lc_cell"] * (wj + 0.5)
        cys = b["lc_ul_n"] - b["lc_cell"] * (wi + 0.5)
        lim = b["wetland_setback"] + half
        near = (EX > cxs.min() - 200) & (EX < cxs.max() + 200) & (EY > cys.min() - 200) & (EY < cys.max() + 200)
        ii, jj = np.nonzero(near)
        dmin = np.full((len(ii), 8), np.inf)
        dv = np.full(len(ii), np.inf)
        for cx_, cy_ in zip(cxs, cys):
            dmin = np.minimum(dmin, _seg_box_dist(AX[ii, jj], AY[ii, jj], BX[ii, jj], BY[ii, jj],
                                                  cx_ - lh, cx_ + lh, cy_ - lh, cy_ + lh))
            dv = np.minimum(dv, _seg_box_dist(EX[ii, jj], EY[ii, jj], EX[ii, jj], EY[ii, jj],
                                              cx_ - lh, cx_ + lh, cy_ - lh, cy_ + lh))
        move_ok[ii, jj] &= dmin > lim
        bad = np.zeros(z.shape, bool); bad[ii, jj] = dv <= lim
        base[bad] = np.nan
    if not opts.get("no_heritage"):
        h = pts["HERITAGE"]
        lim = b["heritage_radius"] + half
        move_ok &= _seg_point_dist(AX, AY, BX, BY, h[0], h[1]) > lim
        base[np.hypot(EX - h[0], EY - h[1]) <= lim] = np.nan
    return z, lcd, EX, EY, base, pts, move_ok


def cell_of(pt):
    b = BRIEF
    j = int(np.floor((pt[0] - b["dem_ul_e"]) / b["dem_cell"]))
    i = int(np.floor((b["dem_ul_n"] - pt[1]) / b["dem_cell"]))
    return i, j


@nb.njit(cache=True)
def _dijkstra(z, base, move_ok, dirs, dlen, cell, max_g, steep_g, turn_on, sustain_on, nxt, nrun,
              si, sj, ei, ej, rev_order):
    ny, nx = z.shape
    NH = 9
    nstate = ny * nx * NH * nrun
    dist = np.full(nstate, np.inf)
    prev = np.full(nstate, -1, np.int64)
    cap = 1 << 22
    hk = np.empty(cap, np.float64)
    hv = np.empty(cap, np.int64)
    n = 0
    s0 = ((si * nx + sj) * NH + 8) * nrun
    dist[s0] = 0.0
    hk[0] = 0.0; hv[0] = s0; n = 1
    best_end = -1
    while n > 0:
        dcur = hk[0]; s = hv[0]
        n -= 1
        if n > 0:
            k = hk[n]; v = hv[n]; p = 0
            while True:
                c = 2 * p + 1
                if c >= n:
                    break
                if c + 1 < n and (hk[c + 1] < hk[c] or (hk[c + 1] == hk[c] and hv[c + 1] < hv[c])):
                    c += 1
                if hk[c] < k or (hk[c] == k and hv[c] < v):
                    hk[p] = hk[c]; hv[p] = hv[c]; p = c
                else:
                    break
            hk[p] = k; hv[p] = v
        if dcur > dist[s]:
            continue
        r = s % nrun
        t = s // nrun
        hd = t % NH
        cidx = t // NH
        i = cidx // nx
        j = cidx % nx
        if i == ei and j == ej:
            best_end = s
            break
        for q in range(8):
            h = 7 - q if rev_order else q
            if not move_ok[i, j, h]:
                continue
            if turn_on and hd != 8:
                dd = (h - hd) % 8
                if dd != 0 and dd != 1 and dd != 7:
                    continue
            a = i + dirs[h, 0]; bq = j + dirs[h, 1]
            if np.isnan(base[a, bq]):
                continue
            L = dlen[h] * cell
            g = abs(z[a, bq] - z[i, j]) / L * 100.0
            if g > max_g:
                continue
            nr = 0
            if sustain_on and g > steep_g:
                nr = nxt[r, 1 if h % 2 == 1 else 0]
                if nr < 0:
                    continue
            if g <= 3.0:
                f = 1.0
            elif g <= 6.0:
                f = 1.0 + 0.05 * (g - 3.0)
            else:
                f = 1.15 + 0.12 * (g - 6.0)
            nd = dcur + L * (base[i, j] + base[a, bq]) / 2.0 * f
            nh = h if turn_on else 0
            ns = ((a * nx + bq) * NH + nh) * nrun + nr
            if nd < dist[ns]:
                dist[ns] = nd
                prev[ns] = s
                if n >= cap:
                    raise ValueError("heap overflow")
                p = n; n += 1
                while p > 0:
                    pp = (p - 1) // 2
                    if hk[pp] > nd or (hk[pp] == nd and hv[pp] > ns):
                        hk[p] = hk[pp]; hv[p] = hv[pp]; p = pp
                    else:
                        break
                hk[p] = nd; hv[p] = ns
    return best_end, dist, prev


def solve(opts=None):
    opts = opts or {}
    b = BRIEF
    z, lcd, EX, EY, base, pts, move_ok = build_cost(opts)
    ny, nx = z.shape
    st, nxt = run_states(b["steep_run_max"], b["dem_cell"])
    turn_on = not opts.get("no_turn")
    sustain_on = not opts.get("no_sustain")
    nrun = len(st) if sustain_on else 1
    si, sj = cell_of(pts["START"])
    ei, ej = cell_of(pts["END"])
    end, dist, prev = _dijkstra(z, base, move_ok, DIRS, DLEN, b["dem_cell"], b["max_grade"], b["steep_grade"],
                                turn_on, sustain_on, nxt, nrun, si, sj, ei, ej, bool(opts.get("rev_order")))
    if end < 0:
        return None
    path = []
    s = end
    while s != -1:
        c = (s // nrun) // 9
        path.append((int(c // nx), int(c % nx)))
        s = prev[s]
    path.reverse()
    return dict(z=z, lcd=lcd, EX=EX, EY=EY, base=base, pts=pts, path=path, cost=float(dist[end]),
                move_ok=move_ok)


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


def check_path(res, opts=None):
    """Independent re-check of a path against every drawing rule."""
    b = BRIEF
    rows, _ = summarise(res)
    g = np.array([r["grade_pct"] for r in rows[:-1]])
    P = res["path"]
    hd = [int(np.nonzero((DIRS == (a[0] - p[0], a[1] - p[1])).all(1))[0][0]) for p, a in zip(P[:-1], P[1:])]
    turns = [min((y - x) % 8, (x - y) % 8) for x, y in zip(hd[:-1], hd[1:])]
    run = 0.0; run_max = 0.0
    for gg, h in zip(g, hd):
        run = run + b["dem_cell"] * DLEN[h] if abs(gg) > b["steep_grade"] else 0.0
        run_max = max(run_max, run)
    return dict(max_grade=float(np.abs(g).max()), max_turn_deg=45 * max(turns), max_steep_run=run_max)


def xing(rows):
    xs = [x for x in rows if x["landcover"] == "Watercourse"]
    if not xs:
        return "none"
    return "X-1" if xs[0]["northing"] > 3350200 else "X-2"


VARIANTS = {
    "golden": {},
    "no_width": {"no_width": True},
    "no_turn": {"no_turn": True},
    "no_sustain": {"no_sustain": True},
    "no_turn_no_sustain": {"no_turn": True, "no_sustain": True},
    "no_width_no_turn": {"no_width": True, "no_turn": True},
    "no_width_no_sustain": {"no_width": True, "no_sustain": True},
    "revB_only": {"no_width": True, "no_turn": True, "no_sustain": True},
    "vertex_only": {"vertex_only": True},
    "intl_ft": {"intl_ft": True},
    "rev_order": {"rev_order": True},
    "no_setback": {"no_setback": True},
    "no_heritage": {"no_heritage": True},
    "only_X1": {"drop_X2": True},
}


if __name__ == "__main__":
    sel = sys.argv[1:] or list(VARIANTS)
    for name in sel:
        r = solve(VARIANTS[name])
        if r is None:
            print(f"{name:22s} NO PATH")
            continue
        rows, L = summarise(r)
        c = check_path(r)
        print(f"{name:22s} cost ${r['cost']:,.0f}  L={L:,.1f} m  cells={len(rows)}  maxg={c['max_grade']:.2f}%  "
              f"turn<={c['max_turn_deg']}  run<={c['max_steep_run']:.1f}  {xing(rows)}  "
              f"Nmax={max(x['northing'] for x in rows):.0f}")
