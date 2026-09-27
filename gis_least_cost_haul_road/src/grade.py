"""Scripted grader for the Rev D rubric, plus simulated failing responses for calibration.

File items are checked independently from the delivered GeoPackage / CSV (and the land-cover raster).
Report-text items are graded from a claims dict: for the golden by text search in its PDF, for the
simulated responses from the rules each simulated response applied (generously: any rule it applied is
assumed to be stated correctly).
"""
import csv
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
X2 = (584613.48, 3349580.00)
HS1 = (586011.87, 3350201.90)
START = (583155.0, 3349105.0)
END = (586455.0, 3350105.0)
CPS = [  # (id, weight, E, N): golden cell centres that single-rule misses avoid
    ("P1", 7, 583625.0, 3349445.0),  # vertex 51: no_adverse no_radius radius_single no_haul haul_flip haul_no_rr haul_linear
    ("P2", 7, 583705.0, 3349445.0),  # vertex 59: no_adverse no_radius radius_single no_haul haul_flip haul_no_rr haul_linear
    ("P3", 5, 585775.0, 3351075.0),  # vertex 310: no_vc haul_flip
    ("P4", 5, 585855.0, 3351145.0),  # vertex 318: no_vc
    ("P5", 5, 585965.0, 3351295.0),  # vertex 333: no_vc no_radius radius_single
    ("P6", 5, 585965.0, 3351375.0),  # vertex 341: no_vc no_radius radius_single
    ("P7", 7, 586295.0, 3350715.0),  # vertex 431: radius_single no_haul haul_flip haul_no_rr haul_linear end_revc end_nosaf
    ("P8", 7, 586375.0, 3350635.0),  # vertex 439: radius_single no_haul haul_flip haul_no_rr haul_linear end_revc end_nosaf
    ("P9", 7, 586455.0, 3350555.0),  # vertex 447: radius_single no_haul haul_flip haul_no_rr haul_linear end_revc end_nosaf
    ("P10", 7, 586545.0, 3350465.0),  # vertex 456: no_adverse radius_single no_haul haul_flip haul_no_rr haul_linear end_revc end_nosaf
    ("P11", 5, 586555.0, 3350385.0),  # vertex 464: no_adverse no_radius radius_single no_haul haul_no_rr end_revc end_nosaf
    ("P12", 5, 586585.0, 3350245.0),  # vertex 478: no_adverse no_radius radius_single haul_no_rr end_revc end_nosaf
    ("P13", 5, 586515.0, 3350165.0),  # vertex 486: no_adverse no_radius radius_single haul_no_rr end_revc end_nosaf
]
WET_RGB = (150, 200, 210)
T_MID, T_END = 2 * 45.0 * math.tan(math.radians(22.5)), 45.0 * math.tan(math.radians(22.5))
LM = dict(wc_cost=888232.87, top_cost=2284982.20, top_ch=4295.29, n_charged=54)
G = dict(total=3110903.74, constr=2926731.02, haul=184172.72, length=5974.53, rows=492, ndef=33,
         wood=533.9, grass=4215.1, track=573.3, crop=632.3, max_rise=9.98, n_max=3351475.0,
         adv=5.88, min_k=1.427, min_tan=40.00)
LC = {"R12": ("Woodland", G["wood"], 0.002), "R13": ("Grassland / pasture", G["grass"], 0.002),
      "R14": ("Existing gravel track", G["track"], 0.002), "R15": ("Cultivated cropland", G["crop"], 0.002)}
HEADER = ["seq", "easting_m", "northing_m", "elev_m", "chainage_m", "grade_to_next_pct", "landcover_class",
          "cum_cost_usd"]

def _sp(x, fmt):
    return format(x, "," + fmt).replace(",", " ")


RUBRIC = [
    # id, weight, text
    ("R1", 9, f"The PDF report states a total route cost (construction plus loaded haulage) of {G['total']:,.0f} USD "
              f"(+/- 0.01 percent, {G['total']*0.9999:,.0f} to {G['total']*1.0001:,.0f} USD)."),
    ("R2", 9, f"The PDF report states a construction cost component of {G['constr']:,.0f} USD (+/- 0.01 percent, "
              f"{G['constr']*0.9999:,.0f} to {G['constr']*1.0001:,.0f} USD)."),
    ("R3", 9, f"The PDF report states a loaded haulage cost component of {G['haul']:,.0f} USD (+/- 0.05 percent, "
              f"{G['haul']*0.9995:,.0f} to {G['haul']*1.0005:,.0f} USD)."),
    ("R4", 9, f"The PDF report states a horizontal route length of {G['length']:,.1f} m (+/- 1.0 m)."),
    ("R5", 9, f"The CSV vertex table has exactly {G['rows']} data rows."),
    ("R6", 7, f"The GeoPackage centreline has exactly {G['ndef']} interior vertices at which the direction of the line changes."),
    ("R7", 9, f"The last vertex of the GeoPackage centreline is at E {_sp(END[0], '.1f')}, N {_sp(END[1], '.1f')} "
              f"(EPSG:32614, +/- 1 m on each)."),
] + [(k, w, f"The GeoPackage centreline has a vertex within 1 m of E {_sp(e, '.0f')}, N {_sp(n, '.0f')} (EPSG:32614).")
      for k, w, e, n in CPS] + [
    ("R20", 9, f"The cum_cost_usd value on the last row of the CSV vertex table is {G['total']:,.0f} USD (+/- 0.01 percent)."),
    ("R21", 7, f"On the first CSV row whose landcover_class is Watercourse, cum_cost_usd is {LM['wc_cost']:,.0f} USD "
               f"(+/- 0.05 percent)."),
    ("R22", 7, f"On the first CSV row with the largest northing_m, cum_cost_usd is {LM['top_cost']:,.0f} USD "
               f"(+/- 0.05 percent)."),
    ("R23", 5, f"On the first CSV row with the largest northing_m, chainage_m is {LM['top_ch']:,.1f} m (+/- 1.0 m)."),
    ("R24", 7, f"Exactly {LM['n_charged']} rows of the CSV vertex table have grade_to_next_pct below -1.000 (moves climbed "
               f"by loaded trucks above the 4.0 percent effective top-gear limit)."),
    ("R12", 5, f"The PDF report states a route length in woodland of {G['wood']:,.1f} m (+/- 0.2 percent)."),
    ("R13", 7, f"The PDF report states a route length in grassland / pasture of {G['grass']:,.1f} m (+/- 0.2 percent)."),
    ("R14", 5, f"The PDF report states a route length on existing gravel track of {G['track']:,.1f} m (+/- 0.2 percent)."),
    ("R15", 5, f"The PDF report states a route length in cultivated cropland of {G['crop']:,.1f} m (+/- 0.2 percent)."),
    ("R16", 1, f"The PDF report states a maximum route grade of {G['max_rise']:.2f} percent (+/- 0.02 percentage points)."),
    ("R17", 1, "The PDF report states that the route climbs the escarpment by the northern slump, reaching "
               "N 3 351 475 (+/- 25 m) before returning south along the plateau to G1."),
    ("R18", 1, "The GeoPackage centreline has a vertex within 30 m of E 584 613.5, N 3 349 580.0 (EPSG:32614), the "
               "centre of approved crossing window X-2."),
    ("C1", 9, "No row of the CSV vertex table has grade_to_next_pct below -6.00 (no move climbed by loaded trucks, "
              "travelling G1 to T1, is steeper than 6.0 percent)."),
    ("C2", 9, "For every two consecutive moves in the CSV vertex table, the absolute difference of grade_to_next_pct "
              "is at most (L1 + L2) / 2 / 1.4 (+ 0.002), where L1 and L2 are the two moves' horizontal lengths in m "
              "from chainage_m."),
    ("C3", 9, "Along the GeoPackage centreline, successive direction-change vertices are at least 37.28 m apart, and "
              "the first and last direction-change vertices are at least 18.64 m from the first and last vertex."),
    ("C4", 1, "No two consecutive segments of the GeoPackage centreline differ in direction by more than 45 degrees."),
    ("C5", 1, "In the CSV vertex table, no unbroken sequence of rows with |grade_to_next_pct| greater than 8.0 spans "
              "more than 60.0 m of chainage (span = chainage of the row after the sequence minus chainage of its "
              "first row)."),
    ("C6", 1, "No point of the GeoPackage centreline lies within 37.0 m of any pixel of CB-LC-20m_landcover.png "
              "coloured RGB (150, 200, 210), with the raster placed at UL corner E 582 900, N 3 351 620, 20 m pixels."),
    ("C7", 1, "No point of the GeoPackage centreline lies within 157.0 m of E 586 011.9, N 3 350 201.9 (EPSG:32614)."),
    ("C8", 1, "The first vertex of the GeoPackage centreline is at E 583 155.0, N 3 349 105.0 (EPSG:32614, +/- 1 m)."),
    ("C9", 1, "The CSV vertex table gives an elev_m of 374.54 m (+/- 0.05 m) on its first row."),
    ("S1", 1, "The PDF report states that no compliant route exists through crossing window X-1."),
    ("S2", 1, "The PDF report attributes the infeasibility of X-1 to the formation width: a centreline clearing the "
              "30 m wetland setback still leaves the formation edge within 30 m of wetland W-1."),
    ("S3", 3, "The PDF report states that loaded trucks travel from G1 to T1 and that moves climbed loaded are "
              "limited to a 6.0 percent grade (9.0 percent effective grade minus 3.0 percent rolling resistance)."),
    ("S4", 5, "The PDF report states that the 45 m minimum radius requires at least 37.28 m (+/- 0.05 m) between "
              "successive deflection vertices and at least 18.64 m (+/- 0.05 m) between the start or end and the "
              "nearest deflection vertex."),
    ("S5", 5, "The PDF report states that the allowable grade change between consecutive moves depends on the two "
              "move lengths, (L1 + L2) / (2 x 1.4), e.g. 7.14 percent between two orthogonal moves and 10.10 percent "
              "between two diagonal moves."),
    ("S6", 5, "The PDF report states that the route minimises construction cost plus loaded haulage of 8,000 USD per "
              "metre of rise climbed by loaded trucks, charged only on moves whose loaded grade exceeds 1.0 percent "
              "(4.0 percent effective grade minus 3.0 percent rolling resistance), with no credit for falls."),
    ("S7", 3, "The PDF report states that G1 was taken from C-004 Table 6 as TxDOT surface coordinates, divided by the "
              "surface adjustment factor 1.00012 to NAD83 / Texas Central grid in US survey feet (EPSG:2277), and "
              "transformed to EPSG:32614."),
    ("F1", 1, "The cum_cost_usd value on the last row of the CSV vertex table equals the total route cost stated in "
              "the PDF report (construction plus haulage) within 1 USD."),
    ("F2", 1, "Every pair of consecutive GeoPackage centreline vertices is separated by 10 m in easting, northing or "
              "both, with no other separation."),
    ("F3", 1, "The GeoPackage centreline layer CRS is EPSG:32614 and the layer 'centreline' holds exactly one "
              "LineString feature."),
    ("F4", 1, "The response delivers files named exactly 'CB_HaulRoad_Centreline.gpkg', 'CB_HaulRoad_Vertices.csv' "
              "and 'CB_HaulRoad_RouteReport.pdf'."),
    ("F5", 1, "The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, "
              "landcover_class, cum_cost_usd."),
    ("F6", 1, "The PDF report contains a plan figure showing the route centreline and a long section plotting "
              "elevation against chainage."),
    ("N1", -7, "The CSV vertex table contains a grade_to_next_pct value whose absolute value exceeds 10.0."),
    ("N2", -5, "The response presents the alignment as approved, issued or released for construction."),
    ("N3", -5, "The PDF report states two different total cost values for the adopted route."),
    ("N4", -3, "The PDF report states earthworks volumes for the route."),
]


def near(P, q, tol):
    return bool((np.hypot(P[:, 0] - q[0], P[:, 1] - q[1]) <= tol).any())


def seg_point(P, q):
    A, B = P[:-1], P[1:]
    v = B - A
    t = np.clip(((q - A) * v).sum(1) / np.maximum((v * v).sum(1), 1e-12), 0, 1)
    return float(np.hypot(*(A + t[:, None] * v - q).T).min())


def seg_box(P, x0, x1, y0, y1):
    """Distance from polyline P to an axis-aligned box (0 if they intersect)."""
    A, B = P[:-1], P[1:]
    best = np.inf
    for a, b in zip(A, B):
        t0, t1, hit = 0.0, 1.0, True
        for p, v, lo, hi in ((a[0], b[0] - a[0], x0, x1), (a[1], b[1] - a[1], y0, y1)):
            if abs(v) < 1e-12:
                hit &= lo <= p <= hi
            else:
                ta, tb = sorted(((lo - p) / v, (hi - p) / v))
                t0, t1 = max(t0, ta), min(t1, tb)
        if hit and t0 <= t1:
            return 0.0
        ts = np.linspace(0, 1, 41)
        pts = a + ts[:, None] * (b - a)
        dx = np.maximum(np.maximum(x0 - pts[:, 0], 0), pts[:, 0] - x1)
        dy = np.maximum(np.maximum(y0 - pts[:, 1], 0), pts[:, 1] - y1)
        best = min(best, float(np.hypot(dx, dy).min()))
    for cx, cy in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
        best = min(best, seg_point(P, np.array([cx, cy])))
    return best


def wetland_clearance(P):
    rgb = np.array(Image.open(ROOT / "inputs" / "CB-LC-20m_landcover.png").convert("RGB"))
    wi, wj = np.nonzero((rgb == WET_RGB).all(2))
    best = np.inf
    for i, j in zip(wi, wj):
        x0 = 582900 + 20 * j; y1 = 3351620 - 20 * i
        if np.hypot(*(P - [x0 + 10, y1 - 10]).T).min() > 120:
            continue
        best = min(best, seg_box(P, x0, x0 + 20, y1 - 20, y1))
    return best


def tangent_check(P):
    V = np.diff(P, axis=0)
    ang = np.degrees(np.arctan2(V[:, 1], V[:, 0]))
    dev = np.abs((np.diff(ang) + 180) % 360 - 180)
    ch = np.concatenate([[0.0], np.cumsum(np.hypot(V[:, 0], V[:, 1]))])
    defl = [k + 1 for k in range(len(dev)) if dev[k] > 1e-6]
    if not defl:
        return True, 0, dev
    ok = ch[defl[0]] >= T_END - 1e-6 and ch[-1] - ch[defl[-1]] >= T_END - 1e-6
    ok &= all(ch[q] - ch[p] >= T_MID - 1e-6 for p, q in zip(defl[:-1], defl[1:]))
    return bool(ok), len(defl), dev


def grade_files(d, claims):
    d = Path(d)
    res = {}
    g = d / "CB_HaulRoad_Centreline.gpkg"
    c = d / "CB_HaulRoad_Vertices.csv"
    res["F4"] = g.exists() and c.exists() and (d / "CB_HaulRoad_RouteReport.pdf").exists()
    gdf = gpd.read_file(g, layer="centreline")
    res["F3"] = (len(gdf) == 1 and gdf.geometry.iloc[0].geom_type == "LineString" and gdf.crs is not None
                 and gdf.crs.to_epsg() == 32614)
    P = np.array(gdf.geometry.iloc[0].coords)[:, :2]
    res["R18"] = near(P, X2, 30)
    for k, _, e, n in CPS:
        res[k] = near(P, (e, n), 1.0)
    res["R7"] = bool(np.all(np.abs(P[-1] - END) <= 1))
    res["C8"] = bool(np.all(np.abs(P[0] - START) <= 1))
    res["C3"], ndef, dev = tangent_check(P)
    res["R6"] = ndef == G["ndef"]
    res["C4"] = bool((dev <= 45 + 1e-6).all())
    res["C6"] = wetland_clearance(P) > 37.0
    res["C7"] = seg_point(P, np.array(HS1)) > 157.0
    dP = np.abs(np.diff(P, axis=0))
    res["F2"] = bool(np.all(np.isin(np.round(dP, 3), [0, 10])) and np.all(dP.max(1) > 0))
    rows = list(csv.reader(open(c)))
    res["F5"] = [h.strip() for h in rows[0]] == HEADER
    body = rows[1:]
    res["R5"] = len(body) == G["rows"]
    res["C9"] = abs(float(body[0][3]) - 374.54) <= 0.05
    gs = np.array([float(r[5]) for r in body if r[5] != ""])
    ch = np.array([float(r[4]) for r in body])
    Ls = np.diff(ch)
    res["N1"] = bool(np.abs(gs).max() > 10.0)
    res["C1"] = bool(gs.min() >= -6.0)
    res["C2"] = bool((np.abs(np.diff(gs)) <= (Ls[:-1] + Ls[1:]) / 2 / 1.4 + 0.002).all())
    run_max, k = 0.0, 0
    ag = np.abs(gs)
    while k < len(ag):
        if ag[k] > 8.0:
            s = k
            while k < len(ag) and ag[k] > 8.0:
                k += 1
            run_max = max(run_max, ch[k] - ch[s])
        else:
            k += 1
    res["C5"] = run_max <= 60.0 + 1e-6
    res["F1"] = abs(float(body[-1][7]) - claims["cost"]) <= 1
    wc = [r for r in body if r[6].strip() == "Watercourse"]
    res["R21"] = bool(wc) and abs(float(wc[0][7]) - LM["wc_cost"]) <= 5e-4 * LM["wc_cost"]
    nmax = max(float(r[2]) for r in body)
    top = [r for r in body if float(r[2]) == nmax][0]
    res["R22"] = abs(float(top[7]) - LM["top_cost"]) <= 5e-4 * LM["top_cost"]
    res["R23"] = abs(float(top[4]) - LM["top_ch"]) <= 1.0
    res["R24"] = int((gs < -1.0).sum()) == LM["n_charged"]
    res["R20"] = abs(float(body[-1][7]) - G["total"]) <= 1e-4 * G["total"]
    res["R1"] = abs(claims["cost"] - G["total"]) <= 1e-4 * G["total"]
    res["R2"] = abs(claims["constr"] - G["constr"]) <= 1e-4 * G["constr"]
    res["R3"] = abs(claims["haul"] - G["haul"]) <= 5e-4 * G["haul"]
    res["R4"] = abs(claims["length"] - G["length"]) <= 1.0
    res["R16"] = abs(claims["max_grade"] - G["max_rise"]) <= 0.02
    for k2, (cls, v, tol) in LC.items():
        res[k2] = abs(claims["len_by"].get(cls, 0.0) - v) <= tol * v
    res["R17"] = claims["slump"] and abs(claims["n_max"] - G["n_max"]) <= 25
    for k2 in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "F6", "N2", "N3", "N4"):
        res[k2] = bool(claims[k2])
    return res


def score(res):
    pos = sum(w for k, w, _ in RUBRIC if w > 0)
    got = sum(w for k, w, _ in RUBRIC if res[k] and w > 0) + sum(w for k, w, _ in RUBRIC if res[k] and w < 0)
    return got / pos, got, pos


def golden_claims():
    txt = " ".join(p.extract_text() for p in PdfReader(ROOT / "golden" / "CB_HaulRoad_RouteReport.pdf").pages)
    t = " ".join(txt.split())
    s = json.loads((ROOT / "work" / "golden_summary.json").read_text())
    return dict(
        cost=float(f"{s['cost_usd']:.2f}"), constr=round(s["constr_usd"], 2), haul=round(s["haul_usd"], 2),
        length=round(s["length_m"], 2), max_grade=round(s["max_grade_pct"], 2), n_max=s["n_max"],
        adv=round(s["max_adverse_loaded_pct"], 2), min_k=round(s["min_k"], 3), min_tan=round(s["min_tangent_m"], 2),
        slump="climbs the northern slump" in t and "returns south along the plateau" in t,
        S1="X-1 is not feasible" in t and "no compliant route" in t,
        S2="formation edge would be" in t and "35.0 m from the W-1 boundary" in t,
        S3="Loaded trucks run G1 to T1" in t and "may not exceed 6.0 %" in t and "3.0 % rolling resistance" in t,
        S4="37.28 m" in t and "18.64 m" in t,
        S5="7.14 %" in t and "10.10 %" in t and "(L1 + L2) / (2 x 1.4)" in t,
        S6="8,000 x (z_i - z_j)" in t and "The fall is not credited" in t and "a grade above 1.0 %" in t,
        S7="EPSG:2277" in t and "US survey feet" in t and "surface adjustment factor" in t,
        F6="plan" in t.lower() and "long section" in t.lower(),
        len_by=s["len_by"], N2=False, N3=False, N4=False,
    )


CASES = [
    # (label, solver options, statements the response gets right)
    ("A  C-004 not applied (Rev C rules, Rev C gate)", "revC_rules", set()),
    ("B  all but D6 radius (curves treated as out of scope)", "no_radius", {"S3", "S5", "S6", "S7"}),
    ("C  D6 as R tan(22.5) between deflections", "radius_single", {"S3", "S5", "S6", "S7"}),
    ("D  all but D7 haulage (construction cost only)", "no_haul", {"S3", "S4", "S5", "S7"}),
    ("E  all but D5 vertical curvature", "no_vc", {"S3", "S4", "S6", "S7"}),
    ("F  D3 9.0 % read as grade limit", "no_adverse", {"S4", "S5", "S6", "S7"}),
    ("G  G1 from superseded C-002 Table 3", "end_revc", {"S3", "S4", "S5", "S6"}),
    ("H  G1 surface coordinates used as grid (SAF ignored)", "end_nosaf", {"S3", "S4", "S5", "S6"}),
    ("H2 EPSG:2277 read as international feet", "end_intl", {"S3", "S4", "S5", "S6"}),
    ("I  D7 rise charged in chainage direction", "haul_flip", {"S3", "S4", "S5", "S7"}),
    ("L  D7 threshold read as 4.0 % grade (rolling resistance dropped)", "haul_no_rr", {"S3", "S4", "S5", "S7"}),
    ("M  D7 threshold ignored (every loaded rise charged)", "haul_linear", {"S3", "S4", "S5", "S7"}),
    ("N  'effective grade' misread twice (D3 and D7 without rolling resistance)",
     {"no_adverse": True, "haul_no_rr": True}, {"S4", "S5", "S7"}),
    ("J  D5 and D6 both missed (geometry treated as out of scope)", {"no_vc": True, "no_tangent": True}, {"S3", "S6", "S7"}),
    ("K  D6 and D7 both missed", {"no_tangent": True, "no_haul": True}, {"S3", "S5", "S7"}),
]


def simulate():
    import tempfile
    import solve as SV
    from shapely.geometry import LineString
    out = []
    for name, opts, said in CASES:
        o = SV.VARIANTS[opts] if isinstance(opts, str) else opts
        r = SV.solve(o)
        rows, L = SV.summarise(r)
        cp = SV.check_path(r)
        d = Path(tempfile.mkdtemp())
        gpd.GeoDataFrame(geometry=[LineString([(x["easting"], x["northing"]) for x in rows])], crs="EPSG:32614") \
            .to_file(d / "CB_HaulRoad_Centreline.gpkg", layer="centreline", driver="GPKG")
        with open(d / "CB_HaulRoad_Vertices.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(HEADER)
            for x in rows:
                w.writerow([x["seq"], x["easting"], x["northing"], x["elev_m"], x["chainage_m"],
                            "" if math.isnan(x["grade_pct"]) else f"{x['grade_pct']:.3f}", x["landcover"],
                            x["cum_cost_usd"]])
        (d / "CB_HaulRoad_RouteReport.pdf").write_bytes(b"%PDF-1.4")
        lb = {}
        for a, c in zip(rows[:-1], rows[1:]):
            dd = c["chainage_m"] - a["chainage_m"]
            lb[a["landcover"]] = lb.get(a["landcover"], 0) + dd / 2
            lb[c["landcover"]] = lb.get(c["landcover"], 0) + dd / 2
        claims = dict(cost=r["cost"], constr=rows[-1]["cum_constr_usd"], haul=rows[-1]["cum_haul_usd"], length=L,
                      max_grade=round(cp["max_rise"], 2), len_by=lb, adv=round(cp["max_adverse_loaded"], 2),
                      min_k=round(cp["min_k"], 3), min_tan=min(round(cp["min_tangent"], 2), 1e6), n_max=max(x["northing"] for x in rows),
                      slump=True, S1=True, S2=True, F6=True, N2=False, N3=False, N4=False,
                      **{k: k in said for k in ("S3", "S4", "S5", "S6", "S7")})
        res = grade_files(d, claims)
        s, got, pos = score(res)
        fails = [k for k, w, _ in RUBRIC if (res[k] if w < 0 else not res[k])]
        out.append((name, s, fails))
        print(f"{name:56s} {s:6.1%}  lost: {' '.join(fails)}")
    print(f"mean {np.mean([o[1] for o in out]):.1%}")
    return out


if __name__ == "__main__":
    wts = [w for _, w, _ in RUBRIC]
    print("items", len(RUBRIC), {w: wts.count(w) for w in sorted(set(wts), reverse=True)},
          "positive total", sum(w for w in wts if w > 0))
    tgt = sys.argv[1] if len(sys.argv) > 1 else "golden"
    if tgt == "golden":
        r = grade_files(ROOT / "golden", golden_claims())
        s, got, pos = score(r)
        print(f"GOLDEN score {s:.1%} ({got}/{pos})", [k for k, w, _ in RUBRIC if (r[k] if w < 0 else not r[k])])
    else:
        simulate()
