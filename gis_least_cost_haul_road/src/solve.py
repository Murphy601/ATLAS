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
# Rev E: rules stated in the prompt only (the drawing set and rasters are unchanged)
PROMPT_E = json.loads((ROOT / "work" / "prompt_e.json").read_text())

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
    e_ft, n_ft = b["g1_surface_ftus"]
    if not opts.get("end_nosaf"):
        e_ft, n_ft = e_ft / b["g1_saf"], n_ft / b["g1_saf"]
    if opts.get("end_intl"):
        pts["END"] = Transformer.from_crs(32139, b["epsg"], always_xy=True).transform(e_ft * 0.3048, n_ft * 0.3048)
    elif opts.get("end_revc"):
        pts["END"] = pts["END_REVC"]
    else:
        pts["END"] = Transformer.from_crs(b["g1_spcs_epsg"], b["epsg"], always_xy=True).transform(e_ft, n_ft)
    base = np.full(z.shape, np.nan)
    for c, info in b["classes"].items():
        if info["cost"] is not None:
            base[lcd == int(c)] = info["cost"]
    pe = PROMPT_E
    if not opts.get("no_plateau"):
        if opts.get("plateau_all"):
            lease = lcd == 1
        elif opts.get("plateau_m"):
            lease = (lcd == 1) & (z >= pe["plateau_ft"])
        else:
            thr = opts.get("plateau_ft", pe["plateau_ft"])
            dn = np.array(Image.open(ROOT / "inputs" / b["dem_file"]), dtype=np.float64)
            lease = (lcd == 1) & (b["dn_base_ft"] + b["dn_step_ft"] * dn >= thr)
        base[lease] = opts.get("plateau_cost", pe["plateau_grass_cost"])
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
    if not opts.get("no_gate"):
        # the last gate_moves moves into G1 are one straight run on gate_heading
        gh = opts.get("gate_heading", pe["gate_heading"])
        ei, ej = cell_of(pts["END"])
        for k in range(opts.get("gate_moves", pe["gate_moves"])):
            ti, tj = ei - k * DIRS[gh, 0], ej - k * DIRS[gh, 1]
            for h in range(8):
                si_, sj_ = ti - DIRS[h, 0], tj - DIRS[h, 1]
                if h != gh and 0 <= si_ < ny and 0 <= sj_ < nx:
                    move_ok[si_, sj_, h] = False
    return z, lcd, EX, EY, base, pts, move_ok


def cell_of(pt):
    b = BRIEF
    j = int(np.floor((pt[0] - b["dem_ul_e"]) / b["dem_cell"]))
    i = int(np.floor((b["dem_ul_n"] - pt[1]) / b["dem_cell"]))
    return i, j


@nb.njit(cache=True)
def _dijkstra(z, base, move_ok, dirs, dlen, cell, max_g, steep_g, turn_on, sustain_on, nxt, nrun,
              si, sj, ei, ej, rev_order, adv_mode, adv_max, vc_k, vc_flat, tan_mid, tan_end, TS, F, haul_c, haul_thr,
              zmode, zone, short_ok):
    """State = (cell, heading of last move or 8 at start, steep-run state, tangent counter).

    adv_mode: 0 off, 1 adverse-loaded limit on moves falling in chainage direction (loaded
    trucks travel END -> START), -1 same limit on rising moves, 2 limit on |grade|.
    vc_k: minimum K (m per % grade change); consecutive moves may differ in grade by at most
    (L1 + L2) / 2 / K.  vc_flat: flat limit on the grade change instead.  <= 0 disables.
    Tangent counter: 0..TS = moves since the last deflection vertex (TS saturated); TS+1+k =
    k moves on the first tangent from the start (k saturates at F).  tan_mid is the minimum
    distance between successive deflection vertices, tan_end between the start (or end) and
    the nearest deflection vertex.  tan_mid <= 0 disables (TS = F = 0).
    haul_c: USD per metre of rise climbed by loaded trucks (END -> START), i.e. charged on moves
    that fall in chainage direction by more than haul_thr percent; a negative value charges rising
    moves instead.
    zmode: steep runs touching `zone` cells are limited to run states with short_ok.  1: a run
    that has had any move with an end cell in the zone keeps the shorter limit over its whole
    length (the steep-run state carries a zone flag); 2: the shorter limit is tested only on
    moves that are themselves in the zone; 0 off.
    """
    ny, nx = z.shape
    NH = 9
    tan_on = tan_mid > 0.0
    ntan = TS + F + 2 if tan_on else 1
    nstate = ny * nx * NH * nrun * ntan
    dist = np.full(nstate, np.inf)
    prev = np.full(nstate, -1, np.int32)
    cap = 1 << 25
    hk = np.empty(cap, np.float64)
    hv = np.empty(cap, np.int64)
    n = 0
    s0 = (((si * nx + sj) * NH + 8) * nrun) * ntan + (TS + 1 if tan_on else 0)
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
        tc = s % ntan
        u = s // ntan
        r = u % nrun
        t = u // nrun
        hd = t % NH
        cidx = t // NH
        i = cidx // nx
        j = cidx % nx
        if i == ei and j == ej:
            if not tan_on or tc > TS or tc == TS or tc * dlen[hd] * cell >= tan_end - 1e-9:
                best_end = s
                break
        g_last = 0.0
        if hd != 8:
            pi = i - dirs[hd, 0]; pj = j - dirs[hd, 1]
            g_last = (z[i, j] - z[pi, pj]) / (dlen[hd] * cell) * 100.0
        for q in range(8):
            h = 7 - q if rev_order else q
            if not move_ok[i, j, h]:
                continue
            if turn_on and hd != 8:
                dd = (h - hd) % 8
                if dd != 0 and dd != 1 and dd != 7:
                    continue
            ntc = 0
            if tan_on:
                if hd == 8:
                    ntc = TS + 1 + min(1, F)
                elif tc > TS:
                    k = tc - TS - 1
                    if h == hd:
                        ntc = TS + 1 + min(k + 1, F)
                    else:
                        if k < F and k * dlen[hd] * cell < tan_end - 1e-9:
                            continue
                        ntc = 1
                elif h == hd:
                    ntc = min(tc + 1, TS)
                else:
                    if tc < TS and tc * dlen[hd] * cell < tan_mid - 1e-9:
                        continue
                    ntc = 1
            a = i + dirs[h, 0]; bq = j + dirs[h, 1]
            if np.isnan(base[a, bq]):
                continue
            L = dlen[h] * cell
            gs = (z[a, bq] - z[i, j]) / L * 100.0
            g = abs(gs)
            if g > max_g:
                continue
            if adv_mode == 1 and -gs > adv_max:
                continue
            if adv_mode == -1 and gs > adv_max:
                continue
            if adv_mode == 2 and g > adv_max:
                continue
            if hd != 8:
                if vc_k > 0.0 and abs(gs - g_last) > (dlen[hd] + dlen[h]) * cell / 2.0 / vc_k:
                    continue
                if vc_flat > 0.0 and abs(gs - g_last) > vc_flat:
                    continue
            nr = 0
            if sustain_on and g > steep_g:
                zf = 2 if zmode == 1 else 1
                nidx = nxt[r // zf, 1 if h % 2 == 1 else 0]
                if nidx < 0:
                    continue
                inz = zone[i, j] or zone[a, bq]
                if zmode == 1:
                    nflag = 1 if (r % 2 == 1 or inz) else 0
                    if nflag == 1 and not short_ok[nidx]:
                        continue
                    nr = nidx * 2 + nflag
                else:
                    if zmode == 2 and inz and not short_ok[nidx]:
                        continue
                    nr = nidx
            if g <= 3.0:
                f = 1.0
            elif g <= 6.0:
                f = 1.0 + 0.05 * (g - 3.0)
            else:
                f = 1.15 + 0.12 * (g - 6.0)
            nd = dcur + L * (base[i, j] + base[a, bq]) / 2.0 * f
            if haul_c > 0.0 and -gs > haul_thr:
                nd += haul_c * (z[i, j] - z[a, bq])
            elif haul_c < 0.0 and gs > haul_thr:
                nd += -haul_c * (z[a, bq] - z[i, j])
            ns = (((a * nx + bq) * NH + h) * nrun + nr) * ntan + ntc
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


def tangent_lengths(R, opts=None):
    """Minimum straight lengths implied by a minimum curve radius R at 45 deg deflections:
    between successive deflection vertices 2 R tan(22.5 deg), and R tan(22.5 deg) between the
    start / end cell and the nearest deflection vertex."""
    opts = opts or {}
    if R <= 0:
        return 0.0, 0.0
    T = R * np.tan(np.radians(22.5))
    if opts.get("tan_no_ends"):
        return 2 * T, 0.0
    if opts.get("tan_single"):
        return T, T
    return 2 * T, T


def solve(opts=None):
    opts = opts or {}
    b = BRIEF
    z, lcd, EX, EY, base, pts, move_ok = build_cost(opts)
    ny, nx = z.shape
    st, nxt = run_states(b["steep_run_max"], b["dem_cell"])
    turn_on = not opts.get("no_turn")
    sustain_on = not opts.get("no_sustain")
    zmode = 0 if (opts.get("no_zone") or not sustain_on) else (2 if opts.get("zone_per_move") else 1)
    zone = ((EY >= opts.get("zone_n_min", PROMPT_E["zone_n_min"]))
            & (EY <= opts.get("zone_n_max", PROMPT_E.get("zone_n_max", np.inf))))
    short_ok = np.array([b["dem_cell"] * (a_ + SQ2 * b_) <= opts.get("zone_run_max", PROMPT_E["zone_run_max"]) + 1e-9
                         for a_, b_ in st])
    nrun = (len(st) * (2 if zmode == 1 else 1)) if sustain_on else 1
    adv_max = opts.get("adv_max", b.get("adverse_max", 0.0))
    adv_mode = 0 if (opts.get("no_adverse") or not adv_max) else (
        -1 if opts.get("adv_flip") else 2 if opts.get("adv_abs") else 1)
    vc_k = 0.0 if opts.get("no_vc") else opts.get("vc_k", b.get("min_k", 0.0))
    vc_flat = opts.get("vc_flat", 0.0)
    if vc_flat:
        vc_k = 0.0
    haul_c = 0.0 if opts.get("no_haul") else opts.get("haul_c", b.get("haul_rise_cost", 0.0))
    if opts.get("haul_flip"):
        haul_c = -haul_c
    haul_thr = opts.get("haul_thr", b.get("haul_eff_threshold", 0.0) - b.get("rolling_resistance", 0.0)
                        if b.get("haul_eff_threshold") else 0.0)
    if opts.get("haul_no_rr"):
        haul_thr = b["haul_eff_threshold"]
    if opts.get("haul_linear"):
        haul_thr = 0.0
    R = 0.0 if opts.get("no_tangent") else opts.get("radius", b.get("min_radius", 0.0))
    tan_mid, tan_end = tangent_lengths(R, opts)
    TS = int(np.ceil(tan_mid / b["dem_cell"] - 1e-9)) if tan_mid > 0 else 0
    F = int(np.ceil(tan_end / b["dem_cell"] - 1e-9)) if tan_mid > 0 else 0
    si, sj = cell_of(pts["START"])
    ei, ej = cell_of(pts["END"])
    end, dist, prev = _dijkstra(z, base, move_ok, DIRS, DLEN, b["dem_cell"], b["max_grade"], b["steep_grade"],
                                turn_on, sustain_on, nxt, nrun, si, sj, ei, ej, bool(opts.get("rev_order")),
                                adv_mode, float(adv_max), float(vc_k), float(vc_flat), float(tan_mid),
                                float(tan_end), TS, F, float(haul_c), float(haul_thr), zmode, zone, short_ok)
    if end < 0:
        return None
    path = []
    s = end
    ntan = TS + F + 2 if tan_mid > 0 else 1
    while s != -1:
        c = ((s // ntan) // nrun) // 9
        path.append((int(c // nx), int(c % nx)))
        s = prev[s]
    path.reverse()
    return dict(z=z, lcd=lcd, EX=EX, EY=EY, base=base, pts=pts, path=path, cost=float(dist[end]),
                move_ok=move_ok, haul_c=float(haul_c), haul_thr=float(haul_thr), zone=zone)


def solve_gate_append(opts=None):
    """Failure mode: route to the start of the gate approach as if it were the end, then append the approach."""
    opts = dict(opts or {}, no_gate=True)
    gh, n = PROMPT_E["gate_heading"], PROMPT_E["gate_moves"]
    orig = build_cost

    def moved_end(o):
        out = list(orig(o))
        pts = dict(out[5])
        ei, ej = cell_of(pts["END"])
        pts["END"] = (out[2][ei - n * DIRS[gh, 0], ej - n * DIRS[gh, 1]], out[3][ei - n * DIRS[gh, 0], ej - n * DIRS[gh, 1]])
        pts["END_TRUE"] = orig(o)[5]["END"]
        out[5] = pts
        return tuple(out)

    globals()["build_cost"] = moved_end
    try:
        r = solve(opts)
    finally:
        globals()["build_cost"] = orig
    ei, ej = cell_of(r["pts"]["END_TRUE"])
    r["path"] = r["path"] + [(ei - k * DIRS[gh, 0], ej - k * DIRS[gh, 1]) for k in range(n - 1, -1, -1)]
    r["pts"]["END"] = r["pts"]["END_TRUE"]
    rows, _ = summarise(r)
    r["cost"] = rows[-1]["cum_cost_usd"]
    return r


def summarise(res):
    b = BRIEF
    cell = b["dem_cell"]
    z, lcd, path = res["z"], res["lcd"], res["path"]
    rows = []
    ch = 0.0
    cum = 0.0
    hcum = 0.0
    for k, (i, j) in enumerate(path):
        e, n = res["EX"][i, j], res["EY"][i, j]
        if k < len(path) - 1:
            a, bq = path[k + 1]
            dd = np.hypot(a - i, bq - j) * cell
            g = (z[a, bq] - z[i, j]) / dd * 100.0
            seg = dd * (res["base"][i, j] + res["base"][a, bq]) / 2 * grade_factor(abs(g))
            hc, ht = res.get("haul_c", 0.0), res.get("haul_thr", 0.0)
            hl = hc * (z[i, j] - z[a, bq]) if hc > 0 and -g > ht else (-hc * (z[a, bq] - z[i, j]) if hc < 0 and g > ht else 0.0)
        else:
            dd, g, seg, hl = 0.0, float("nan"), 0.0, 0.0
        rows.append(dict(seq=k + 1, easting=e, northing=n, elev_m=z[i, j], chainage_m=ch,
                         grade_pct=g, landcover=b["classes"][str(lcd[i, j])]["name"], unit_rate=res["base"][i, j],
                         cum_constr_usd=cum, cum_haul_usd=hcum, cum_cost_usd=cum + hcum))
        ch += dd
        cum += seg
        hcum += hl
    return rows, ch


def check_path(res, opts=None):
    """Independent re-check of a path against every drawing rule."""
    b = BRIEF
    rows, _ = summarise(res)
    g = np.array([r["grade_pct"] for r in rows[:-1]])
    P = res["path"]
    hd = [int(np.nonzero((DIRS == (a[0] - p[0], a[1] - p[1])).all(1))[0][0]) for p, a in zip(P[:-1], P[1:])]
    turns = [min((y - x) % 8, (x - y) % 8) for x, y in zip(hd[:-1], hd[1:])]
    run = 0.0; run_max = 0.0; zrun_max = 0.0; touched = False
    zone = res.get("zone")
    for k, (gg, h) in enumerate(zip(g, hd)):
        if abs(gg) > b["steep_grade"]:
            run += b["dem_cell"] * DLEN[h]
            touched |= zone is not None and bool(zone[P[k]] or zone[P[k + 1]])
        else:
            run, touched = 0.0, False
        run_max = max(run_max, run)
        if touched:
            zrun_max = max(zrun_max, run)
    ng = PROMPT_E["gate_moves"]
    gate_ok = len(hd) >= ng and all(x == PROMPT_E["gate_heading"] for x in hd[-ng:])
    # deflection vertices = interior vertices where the heading changes
    defl = [k + 1 for k in range(len(hd) - 1) if hd[k] != hd[k + 1]]
    ch = np.concatenate([[0.0], np.cumsum([b["dem_cell"] * DLEN[h] for h in hd])])
    tans = [ch[q] - ch[p] for p, q in zip(defl[:-1], defl[1:])]
    Ls = np.array([b["dem_cell"] * DLEN[h] for h in hd])
    dg = np.abs(np.diff(g))
    kk = (Ls[:-1] + Ls[1:]) / 2 / np.maximum(dg, 1e-12)
    return dict(max_grade=float(np.abs(g).max()), max_turn_deg=45 * max(turns), max_steep_run=run_max,
                max_zone_run=zrun_max, gate_ok=gate_ok,
                max_adverse_loaded=float(max(0.0, (-g).max())), max_rise=float(g.max()),
                max_grade_change=float(dg.max()), min_k=float(kk.min()),
                min_tangent=float(min(tans)) if tans else float("inf"), n_deflections=len(defl),
                start_tangent=float(ch[defl[0]]) if defl else float("inf"),
                end_tangent=float(ch[-1] - ch[defl[-1]]) if defl else float("inf"))


def clearances(res):
    """Minimum centreline-segment distance to the wetland boundary and to the HS-1 point (m)."""
    cell = BRIEF["dem_cell"]
    P = res["path"]
    A = np.array([(res["EX"][p], res["EY"][p]) for p in P[:-1]])
    B = np.array([(res["EX"][p], res["EY"][p]) for p in P[1:]])
    wi, wj = np.nonzero(res["lcd"] == 7)
    wet = np.inf
    for i, j in zip(wi, wj):
        cx, cy = res["EX"][i, j], res["EY"][i, j]
        d = _seg_box_dist(A[:, 0], A[:, 1], B[:, 0], B[:, 1], cx - cell / 2, cx + cell / 2, cy - cell / 2, cy + cell / 2)
        wet = min(wet, float(d.min()))
    h = res["pts"]["HERITAGE"]
    her = float(_seg_point_dist(A[:, 0], A[:, 1], B[:, 0], B[:, 1], h[0], h[1]).min())
    return dict(wetland_m=wet, heritage_m=her)


def xing(rows):
    xs = [x for x in rows if x["landcover"] == "Watercourse"]
    if not xs:
        return "none"
    return "X-1" if xs[0]["northing"] > 3350200 else "X-2"


REV_E_OFF = {"no_plateau": True, "no_zone": True, "no_gate": True}

VARIANTS = {
    "golden": {},
    # Rev E prompt levers
    "revD_golden": REV_E_OFF,                     # prompt addendum ignored: the Rev D answer
    "no_plateau": {"no_plateau": True},
    "plateau_all": {"plateau_all": True},         # lease rate applied to all grassland
    "plateau_m": {"plateau_m": True},             # 1,500 ft compared with metres (no cell qualifies)
    "plateau_intl": {"plateau_ft": 1500.0 * 0.3048 / (1200.0 / 3937.0)},  # threshold via international foot
    "no_zone": {"no_zone": True},
    "zone_per_move": {"zone_per_move": True},     # 30 m tested only on moves inside the zone
    "no_gate": {"no_gate": True},
    "gate_3": {"gate_moves": 3},                  # 40 m read as 3 moves / 30 m
    "gate_east": {"gate_heading": 2},             # approach read as travelling east into G1
    # Rev D levers
    "no_adverse": {"no_adverse": True},           # also the 9 % effective limit read as grade
    "adv_flip": {"adv_flip": True},               # adverse limit applied to chainage-rising moves
    "adv_abs": {"adv_abs": True},                 # 6 % applied in both directions
    "no_vc": {"no_vc": True},
    "vc_flat_orth": {"vc_flat": 10.0 / 1.4},      # K applied with L = 10 m for every pair
    "vc_flat_diag": {"vc_flat": 10.0 * SQ2 / 1.4},
    "no_radius": {"no_tangent": True},
    "radius_single": {"tan_single": True},        # R tan(22.5) between deflections
    "radius_no_ends": {"tan_no_ends": True},
    "no_haul": {"no_haul": True},                 # construction cost only
    "haul_flip": {"haul_flip": True},             # rise charged in chainage direction
    "haul_no_rr": {"haul_no_rr": True},           # 4.0 % threshold read as grade, not effective grade
    "haul_linear": {"haul_linear": True},         # every loaded rise charged (threshold ignored)
    "end_revc": {"end_revc": True},               # superseded Rev C gate
    "end_intl": {"end_intl": True},               # EPSG:2277 read as international feet
    "end_nosaf": {"end_nosaf": True},             # surface coordinates used as grid (SAF ignored)
    "revC_rules": {"no_adverse": True, "no_vc": True, "no_tangent": True, "no_haul": True, "end_revc": True},
    # Rev C levers (with Rev D rules on)
    "no_width": {"no_width": True},
    "no_turn": {"no_turn": True},
    "no_sustain": {"no_sustain": True},
    "no_setback": {"no_setback": True},
    "no_heritage": {"no_heritage": True},
    "only_X1": {"drop_X2": True},
    # robustness
    "intl_ft_dem": {"intl_ft": True},
    "vertex_only": {"vertex_only": True},
    "rev_order": {"rev_order": True},
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
              f"turn<={c['max_turn_deg']}  run<={c['max_steep_run']:.1f}  adv={c['max_adverse_loaded']:.2f}  "
              f"dg={c['max_grade_change']:.2f}  tan>={c['min_tangent']:.1f}  zrun={c['max_zone_run']:.1f}  "
              f"gate={'Y' if c['gate_ok'] else 'n'}  {xing(rows)}  "
              f"Nmax={max(x['northing'] for x in rows):.0f}")
