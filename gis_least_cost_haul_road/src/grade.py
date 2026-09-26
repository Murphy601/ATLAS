"""Scripted grader for the Rev E rubric, plus simulated failing responses for calibration.

File items are checked independently from the delivered GeoPackage / CSV (and the land-cover raster).
Report-text items are graded from a claims dict: for the golden by text search in its PDF, for the
simulated responses from the rules each simulated response applied (generously: any rule it applied is
assumed to be stated correctly).
"""
import csv
import json
import math
import re
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
    ("P1", 7, 584655.0, 3349555.0),  # vertex 154: revD_golden plateau_all zone_per_move no_zone no_adverse no_radius no_haul
    ("P2", 7, 584715.0, 3349575.0),  # vertex 160: revD_golden plateau_all zone_per_move no_zone no_adverse no_radius no_haul
    ("P3", 7, 584795.0, 3349895.0),  # vertex 192: revD_golden plateau_all zone_per_move no_zone no_adverse no_radius no_haul haul_flip
    ("P4", 7, 584795.0, 3349955.0),  # vertex 198: revD_golden plateau_all zone_per_move no_zone no_adverse no_radius no_haul haul_flip
    ("P5", 7, 584815.0, 3350015.0),  # vertex 204: revD_golden plateau_all zone_per_move no_zone no_adverse no_radius no_haul haul_flip
    ("P6", 7, 584875.0, 3350075.0),  # vertex 210: revD_golden plateau_all zone_per_move no_zone no_adverse no_radius no_haul haul_flip
    ("P7", 7, 584935.0, 3350135.0),  # vertex 216: revD_golden plateau_all zone_per_move no_zone no_adverse no_radius no_haul haul_flip
    ("P8", 7, 584965.0, 3350195.0),  # vertex 222: revD_golden plateau_all zone_per_move no_zone no_adverse no_radius no_haul haul_flip
    ("P9", 7, 584975.0, 3350255.0),  # vertex 228: plateau_all no_vc no_haul haul_flip
    ("P10", 7, 586035.0, 3351495.0),  # vertex 362: revD_golden no_plateau plateau_all no_vc no_radius
    ("P11", 7, 586095.0, 3351455.0),  # vertex 368: revD_golden no_plateau plateau_all no_vc no_radius
    ("P12", 7, 586105.0, 3351245.0),  # vertex 389: revD_golden no_plateau no_vc no_haul end_revc
    ("P13", 7, 586165.0, 3351185.0),  # vertex 395: revD_golden no_plateau no_vc no_haul end_revc
    ("P14", 7, 586225.0, 3351125.0),  # vertex 401: revD_golden no_plateau no_vc no_haul end_revc
    ("P15", 7, 586285.0, 3351065.0),  # vertex 407: revD_golden no_plateau no_vc no_haul end_revc
    ("P16", 7, 586305.0, 3350735.0),  # vertex 440: revD_golden no_plateau no_haul haul_flip end_revc
    ("P17", 7, 586545.0, 3350495.0),  # vertex 464: revD_golden no_plateau no_adverse no_haul haul_flip end_revc
    ("P18", 7, 586575.0, 3350245.0),  # vertex 489: revD_golden no_gate no_adverse no_radius end_revc
    ("P19", 7, 586525.0, 3350185.0),  # vertex 495: revD_golden no_gate gate_3 no_radius end_revc
    ("P20", 7, 586515.0, 3350125.0),  # vertex 501: revD_golden no_gate gate_3 no_radius end_revc
]
WET_RGB = (150, 200, 210)
REV_E_OFF_OPTS = {"no_plateau": True, "no_zone": True, "no_gate": True}
T_MID, T_END = 2 * 45.0 * math.tan(math.radians(22.5)), 45.0 * math.tan(math.radians(22.5))
LM = dict(wc_cost=885343.37, top_cost=2450318.07, top_ch=4335.58, n_charged=59, lease=1826.67)
G = dict(total=4899456.85, constr=4709285.66, haul=190171.20, length=6062.40, rows=507, ndef=34,
         wood=584.9, grass=4260.2, track=573.3, crop=624.0, max_rise=10.00, n_max=3351495.0,
         adv=5.73, min_k=1.404, min_tan=40.00)
LC = {"R12": ("Woodland", G["wood"], 0.002), "R13": ("Grassland / pasture", G["grass"], 0.002),
      "R14": ("Existing gravel track", G["track"], 0.002), "R15": ("Cultivated cropland", G["crop"], 0.002)}
HEADER = ["seq", "easting_m", "northing_m", "elev_m", "chainage_m", "grade_to_next_pct", "landcover_class",
          "unit_rate_usd_per_m", "cum_constr_usd", "cum_haul_usd", "cum_cost_usd"]
CLASS_NAMES = {"Grassland / pasture", "Cultivated cropland", "Woodland", "Rock outcrop", "Existing gravel track",
               "Watercourse", "Wetland", "Farmstead / structures"}
LEASE_M = 1500.0 * 1200.0 / 3937.0
LEASE_RATE = 1300.0
ZONE = (3349600.0, 3349800.0, 30.0)
DP = {"easting_m": 2, "northing_m": 2, "elev_m": 3, "chainage_m": 2, "grade_to_next_pct": 3,
      "unit_rate_usd_per_m": 2, "cum_constr_usd": 2, "cum_haul_usd": 2, "cum_cost_usd": 2}

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
    ("R25", 9, f"The cum_haul_usd value on the last row of the CSV vertex table is {G['haul']:,.0f} USD (+/- 0.05 percent)."),
    ("E1", 9, "The last four segments of the GeoPackage centreline each run due west (easting decreasing by 10 m, northing "
              "unchanged), ending at the G1 cell."),
    ("E2", 9, "In the CSV vertex table, no unbroken sequence of rows with |grade_to_next_pct| greater than 8.0 that contains "
              "a move with either end row's northing_m between 3 349 600 and 3 349 800 spans more than 30.0 m of chainage."),
    ("E3", 9, "In the CSV vertex table, unit_rate_usd_per_m is 1300.00 on every grassland row (any label containing 'grassland') with elev_m at or "
              "above 457.20 m (1,500 ft) and 420.00 on every other grassland row (rows within 0.006 m of 457.201 m "
              "are not tested)."),
    ("E4", 7, f"The PDF report states a route length on the plateau lease of {LM['lease']:,.1f} m (+/- 0.5 percent)."),
    ("E5", 3, "The PDF report states that the 1,300 USD/m lease rate replaces the grassland rate only on grassland cells at "
              "or above 1,500 ft (457.20 m)."),
    ("E6", 7, "The PDF report states that the 30 m slip-zone limit applies over the whole length of any steep run that "
              "touches the band, including the part outside it."),
    ("R12", 5, f"The PDF report states a route length in woodland of {G['wood']:,.1f} m (+/- 0.2 percent)."),
    ("R13", 7, f"The PDF report states a route length in grassland / pasture of {G['grass']:,.1f} m (+/- 0.2 percent)."),
    ("R14", 5, f"The PDF report states a route length on existing gravel track of {G['track']:,.1f} m (+/- 0.2 percent)."),
    ("R15", 5, f"The PDF report states a route length in cultivated cropland of {G['crop']:,.1f} m (+/- 0.2 percent)."),
    ("R16", 1, f"The PDF report states a maximum route grade of {G['max_rise']:.2f} percent (+/- 0.02 percentage points)."),
    ("R17", 1, "The PDF report states that the route climbs the escarpment by the northern slump, reaching "
               "N 3 351 475 (+/- 25 m) before returning south along the plateau to G1."),
    ("R18", 1, "The GeoPackage centreline has a vertex within 30 m of E 584 613.5, N 3 349 580.0 (EPSG:32614), the "
               "centre of approved crossing window X-2."),
    ("C1", 5, "No row of the CSV vertex table has grade_to_next_pct below -6.00 (no move climbed by loaded trucks, "
              "travelling G1 to T1, is steeper than 6.0 percent)."),
    ("C2", 5, "For every two consecutive moves in the CSV vertex table, the absolute difference of grade_to_next_pct "
              "is at most (L1 + L2) / 2 / 1.4 (+ 0.002), where L1 and L2 are the two moves' horizontal lengths in m "
              "from chainage_m."),
    ("C3", 5, "Along the GeoPackage centreline, successive direction-change vertices are at least 37.28 m apart, and "
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
    ("F5", 3, "The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, "
              "landcover_class, unit_rate_usd_per_m, cum_constr_usd, cum_haul_usd, cum_cost_usd."),
    ("F7", 5, "Every landcover_class value in the CSV is exactly one of the class names in C-002 Table 2 (for example "
              "'Grassland / pasture'; culvert cells 'Watercourse'), with no codes, prefixes or other labels."),
    ("F8", 1, "In the CSV, easting_m, northing_m, chainage_m and the four USD columns have exactly 2 decimals, elev_m and "
              "grade_to_next_pct exactly 3 decimals, and no value has a thousands separator."),
    ("F9", 1, "On every CSV row cum_cost_usd equals cum_constr_usd plus cum_haul_usd within 1 USD."),
    ("F10", 1, "The GeoPackage feature has route_id 'CB-HR-01E', total_cost_usd within 1 USD of the last CSV cum_cost_usd, "
               "and length_m within 0.1 m of the last CSV chainage_m."),
    ("F6", 1, "The PDF report contains a plan figure showing the route centreline and a long section plotting "
              "elevation against chainage."),
    ("N1", -7, "The CSV vertex table contains a grade_to_next_pct value whose absolute value exceeds 10.0."),
    ("N2", -5, "The response presents the alignment as approved, issued or released for construction."),
    ("N3", -5, "The PDF report states two different total cost values for the adopted route."),
    ("N4", -3, "The PDF report states earthworks volumes for the route."),
    ("N5", -7, "The PDF report states that the route meets every criterion, while the delivered files fail at least one "
               "of C1 to C7, E1 or E2."),
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
    raw = list(csv.reader(open(c)))
    hdr = [h.strip() for h in raw[0]]
    res["F5"] = hdr == HEADER
    body = [{h: v.strip() for h, v in zip(hdr, r)} for r in raw[1:]]
    col = lambda name: [r.get(name, "") for r in body]  # noqa: E731
    num = lambda name: np.array([float(v) if v not in ("", None) else np.nan for v in col(name)])  # noqa: E731
    res["R5"] = len(body) == G["rows"]
    elev, ch, north = num("elev_m"), num("chainage_m"), num("northing_m")
    res["C9"] = abs(elev[0] - 374.54) <= 0.05
    gs = num("grade_to_next_pct")[:-1]
    Ls = np.diff(ch)
    lc = col("landcover_class")
    cost_col = num("cum_cost_usd")
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
    inz = (north >= ZONE[0]) & (north <= ZONE[1])
    zrun, k = 0.0, 0
    while k < len(ag):
        if ag[k] > 8.0:
            s, touched = k, False
            while k < len(ag) and ag[k] > 8.0:
                touched |= bool(inz[k] or inz[k + 1])
                k += 1
            if touched:
                zrun = max(zrun, ch[k] - ch[s])
        else:
            k += 1
    res["E2"] = zrun <= ZONE[2] + 1e-6
    rate = num("unit_rate_usd_per_m")
    grass = np.array(["grassland" in v.lower() for v in lc])
    sure = grass & (np.abs(elev - LEASE_M) > 0.006)
    res["E3"] = bool(sure.any()) and bool(np.all(np.where(elev[sure] >= LEASE_M, LEASE_RATE, 420.0)
                                                 == np.round(rate[sure], 2)))
    res["F7"] = all(v in CLASS_NAMES for v in lc)

    def dp_ok(name, n):
        return all(v == "" or (re.fullmatch(r"-?\d+\.\d{%d}" % n, v) is not None) for v in col(name))
    res["F8"] = all(name in hdr and dp_ok(name, n) for name, n in DP.items())
    constr_col, haul_col = num("cum_constr_usd"), num("cum_haul_usd")
    res["F9"] = bool(np.all(np.abs(constr_col + haul_col - cost_col) <= 1.0))
    res["R25"] = abs(haul_col[-1] - G["haul"]) <= 5e-4 * G["haul"]
    attrs = gdf.iloc[0]
    try:
        res["F10"] = (str(attrs.get("route_id")) == "CB-HR-01E" and abs(float(attrs["total_cost_usd"]) - cost_col[-1]) <= 1
                      and abs(float(attrs["length_m"]) - ch[-1]) <= 0.1)
    except (KeyError, TypeError, ValueError):
        res["F10"] = False
    dPw = np.diff(P[-5:], axis=0)
    res["E1"] = len(P) >= 5 and bool(np.all(np.abs(dPw - [-10.0, 0.0]) <= 1e-3)) and res["R7"]
    res["F1"] = abs(cost_col[-1] - claims["cost"]) <= 1
    wc = [k for k, v in enumerate(lc) if v == "Watercourse"]
    res["R21"] = bool(wc) and abs(cost_col[wc[0]] - LM["wc_cost"]) <= 5e-4 * LM["wc_cost"]
    top = int(np.argmax(north))
    res["R22"] = abs(cost_col[top] - LM["top_cost"]) <= 5e-4 * LM["top_cost"]
    res["R23"] = abs(ch[top] - LM["top_ch"]) <= 1.0
    res["R24"] = int((gs < -1.0).sum()) == LM["n_charged"]
    res["R20"] = abs(cost_col[-1] - G["total"]) <= 1e-4 * G["total"]
    res["E4"] = abs(claims.get("lease", 0.0) - LM["lease"]) <= 5e-3 * LM["lease"]
    res["R1"] = abs(claims["cost"] - G["total"]) <= 1e-4 * G["total"]
    res["R2"] = abs(claims["constr"] - G["constr"]) <= 1e-4 * G["constr"]
    res["R3"] = abs(claims["haul"] - G["haul"]) <= 5e-4 * G["haul"]
    res["R4"] = abs(claims["length"] - G["length"]) <= 1.0
    res["R16"] = abs(claims["max_grade"] - G["max_rise"]) <= 0.02
    for k2, (cls, v, tol) in LC.items():
        res[k2] = abs(claims["len_by"].get(cls, 0.0) - v) <= tol * v
    res["R17"] = claims["slump"] and abs(claims["n_max"] - G["n_max"]) <= 25
    for k2 in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "E5", "E6", "F6", "N2", "N3", "N4"):
        res[k2] = bool(claims[k2])
    res["N5"] = bool(claims.get("claims_compliance", True)) and not all(
        res[k2] for k2 in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "E1", "E2"))
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
        E5="takes a base unit rate of 1,300 USD/m instead of 420 USD/m" in t and "1,500.00 ft" in t and "457.201 m" in t,
        E6="over its whole length, including the part outside the band" in t,
        lease=round(s["lease_len_m"], 1), len_by=s["len_by"], N2=False, N3=False, N4=False,
    )


def write_deliverables(d, rows, L, cost, labels=None, dp=None):
    """GeoPackage + CSV in the Rev E format from solver rows (optionally relabelled / re-rounded) and a stub PDF."""
    from shapely.geometry import LineString
    labels = labels or {}
    dp = dict(DP, **(dp or {}))
    gpd.GeoDataFrame(dict(route_id=["CB-HR-01E"], total_cost_usd=[round(cost, 2)], length_m=[round(L, 2)]),
                     geometry=[LineString([(x["easting"], x["northing"]) for x in rows])], crs="EPSG:32614") \
        .to_file(d / "CB_HaulRoad_Centreline.gpkg", layer="centreline", driver="GPKG")
    key = dict(easting_m="easting", northing_m="northing", elev_m="elev_m", chainage_m="chainage_m",
               grade_to_next_pct="grade_pct", unit_rate_usd_per_m="unit_rate", cum_constr_usd="cum_constr_usd",
               cum_haul_usd="cum_haul_usd", cum_cost_usd="cum_cost_usd")
    with open(d / "CB_HaulRoad_Vertices.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for x in rows:
            out = []
            for h in HEADER:
                if h == "seq":
                    out.append(x["seq"])
                elif h == "landcover_class":
                    out.append(labels.get(x["landcover"], x["landcover"]))
                else:
                    v = x[key[h]]
                    out.append("" if (isinstance(v, float) and math.isnan(v)) else f"{v:.{dp[h]}f}")
            w.writerow(out)
    if not (d / "CB_HaulRoad_RouteReport.pdf").exists():
        (d / "CB_HaulRoad_RouteReport.pdf").write_bytes(b"%PDF-1.4")


def lease_length(rows):
    s = 0.0
    for a, c in zip(rows[:-1], rows[1:]):
        dd = c["chainage_m"] - a["chainage_m"]
        s += dd / 2 * (int(a["unit_rate"] == LEASE_RATE) + int(c["unit_rate"] == LEASE_RATE))
    return s


SAY = ("S3", "S4", "S5", "S6", "S7", "E5", "E6")
ALL = set(SAY)
CASES = [
    # (label, solver options, statements the response gets right)
    ("A  Rev E updates ignored (exact Rev D answer)", "revD_golden", ALL - {"E5", "E6"}),
    ("B  plateau lease rate not applied", "no_plateau", ALL - {"E5"}),
    ("C  lease rate applied to all grassland", "plateau_all", ALL - {"E5"}),
    ("D  slip-zone 30 m tested only on moves inside the band", "zone_per_move", ALL - {"E6"}),
    ("E  slip-zone limit ignored", "no_zone", ALL - {"E6"}),
    ("F  gate approach ignored", "no_gate", ALL),
    ("G  gate approach as 3 moves (30 m)", "gate_3", ALL),
    ("G2 gate approach appended after routing to its start cell", "gate_append", ALL),
    ("H  slip zone per move and gate ignored", {"zone_per_move": True, "no_gate": True}, ALL - {"E6"}),
    ("I  all but D6 radius", "no_radius", ALL - {"S4"}),
    ("J  all but D7 haulage", "no_haul", ALL - {"S6"}),
    ("K  all but D5 vertical curvature", "no_vc", ALL - {"S5"}),
    ("L  D3 9.0 % read as grade limit", "no_adverse", ALL - {"S3"}),
    ("M  G1 from superseded C-002 Table 3", "end_revc", ALL - {"S7"}),
    ("N  D7 rise charged in chainage direction", "haul_flip", ALL - {"S6"}),
    ("O  Rev D relaxed path (no D5, D6, T3; updates ignored)",
     dict(REV_E_OFF_OPTS, no_vc=True, no_tangent=True, no_sustain=True), ALL - {"E5", "E6"}),
]


def simulate(cases=None, verbose=True):
    import tempfile
    import solve as SV
    out = []
    for name, opts, said in cases or CASES:
        if opts == "gate_append":
            r = SV.solve_gate_append()
        else:
            r = SV.solve(SV.VARIANTS[opts] if isinstance(opts, str) else opts)
        rows, L = SV.summarise(r)
        cp = SV.check_path(r)
        d = Path(tempfile.mkdtemp())
        write_deliverables(d, rows, L, r["cost"])
        lb = {}
        for a, c in zip(rows[:-1], rows[1:]):
            dd = c["chainage_m"] - a["chainage_m"]
            lb[a["landcover"]] = lb.get(a["landcover"], 0) + dd / 2
            lb[c["landcover"]] = lb.get(c["landcover"], 0) + dd / 2
        claims = dict(cost=r["cost"], constr=rows[-1]["cum_constr_usd"], haul=rows[-1]["cum_haul_usd"], length=L,
                      max_grade=round(cp["max_rise"], 2), len_by=lb, n_max=max(x["northing"] for x in rows),
                      lease=lease_length(rows), slump=True, S1=True, S2=True, F6=True, N2=False, N3=False, N4=False,
                      **{k: k in said for k in SAY})
        res = grade_files(d, claims)
        s, got, pos = score(res)
        fails = [k for k, w, _ in RUBRIC if (res[k] if w < 0 else not res[k])]
        out.append((name, s, fails, r["cost"], rows[-1]["cum_haul_usd"], L))
        if verbose:
            print(f"{name:58s} {r['cost']:>12,.0f} {L:8.1f}  {s:6.1%}  lost: {' '.join(fails)}", flush=True)
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
