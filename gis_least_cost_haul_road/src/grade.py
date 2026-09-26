"""Scripted grader for the objective rubric items, plus simulated failing responses for calibration.

Report-text items (statements in the PDF) are graded from a claims dict for the simulated responses
and by text search in the golden PDF.
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
CPA = (584325.0, 3349705.0)
CPB = (585715.0, 3351105.0)
CPD = (586305.0, 3350855.0)
START = (583155.0, 3349105.0)
END = (586315.0, 3350315.0)
WET_RGB = (150, 200, 210)
LC = {"R31": ("Woodland", 467.0), "R32": ("Grassland / pasture", 3935.3)}
HEADER = ["seq", "easting_m", "northing_m", "elev_m", "chainage_m", "grade_to_next_pct", "landcover_class",
          "cum_cost_usd"]

RUBRIC = [
    # id, weight, text
    ("R1", 9, "The PDF report states a total route cost of 2,618,856 USD (+/- 0.5 percent, 2,605,762 to 2,631,950 USD)."),
    ("R2", 7, "The PDF report states a horizontal route length of 5,513.4 m (+/- 0.5 percent, 5,485.8 to 5,541.0 m)."),
    ("R3", 9, "The PDF report states that no compliant route exists through crossing window X-1."),
    ("R4", 7, "The PDF report attributes the infeasibility of crossing window X-1 to the road formation width: a centreline "
              "that clears the 30 m wetland setback at X-1 still leaves the formation edge within 30 m of wetland W-1."),
    ("R5", 9, "The GeoPackage centreline has a vertex within 30 m of E 584 613.5, N 3 349 580.0 (EPSG:32614), the centre "
              "of approved crossing window X-2."),
    ("R6", 5, "The GeoPackage centreline has a vertex within 25 m of E 584 325, N 3 349 705 (EPSG:32614)."),
    ("R7", 9, "The GeoPackage centreline has a vertex within 25 m of E 585 715, N 3 351 105 (EPSG:32614)."),
    ("R8", 7, "The GeoPackage centreline has a vertex within 25 m of E 586 305, N 3 350 855 (EPSG:32614)."),
    ("R9", 9, "No two consecutive segments of the GeoPackage centreline differ in direction by more than 45 degrees."),
    ("R10", 9, "In the CSV vertex table, no unbroken sequence of rows with |grade_to_next_pct| greater than 8.0 spans more "
               "than 60.0 m of chainage (span = chainage of the row after the sequence minus chainage of its first row)."),
    ("R11", 7, "No point of the GeoPackage centreline lies within 37.0 m of any pixel of CB-LC-20m_landcover.png coloured "
               "RGB (150, 200, 210) (wetland), with the raster placed at UL corner E 582 900, N 3 351 620, 20 m pixels."),
    ("R12", 1, "No point of the GeoPackage centreline lies within 157.0 m of E 586 011.9, N 3 350 201.9 (EPSG:32614), "
               "heritage point HS-1."),
    ("R13", 1, "The first vertex of the GeoPackage centreline is at E 583 155.0, N 3 349 105.0 (EPSG:32614, +/- 1 m on each)."),
    ("R14", 1, "The last vertex of the GeoPackage centreline is at E 586 315.0, N 3 350 315.0 (EPSG:32614, +/- 1 m on each)."),
    ("R15", 1, "The CSV vertex table gives an elev_m of 374.54 m (+/- 0.05 m) on its first row."),
    ("R16", 5, "The PDF report states a maximum route grade of 9.96 percent (+/- 0.03 percentage points)."),
    ("R17", 5, "The PDF report states that a road formation width of 14.0 m (7.0 m either side of the centreline) was "
               "applied to the wetland setback and the HS-1 exclusion."),
    ("R18", 5, "The PDF report states that the direct spur ascent of the escarpment towards G1 breaks the 60 m "
               "sustained-grade limit for moves steeper than 8.0 percent."),
    ("R19", 5, "The PDF report states that the southern fall-line (chute) ascent of the escarpment needs changes of "
               "direction greater than 45 degrees between consecutive moves."),
    ("R20", 5, "The PDF report states the longest continuous run of moves steeper than 8.0 percent on the adopted route "
               "as 56.6 m (+/- 0.5 m)."),
    ("R21", 1, "Every pair of consecutive GeoPackage centreline vertices is separated by 10 m in easting, northing or "
               "both, with no other separation."),
    ("R22", 1, "The cum_cost_usd value on the last row of the CSV vertex table equals the total route cost stated in the "
               "PDF report within 1 USD."),
    ("R23", 1, "The GeoPackage centreline layer CRS is EPSG:32614 (WGS 84 / UTM zone 14N)."),
    ("R24", 1, "The GeoPackage contains a layer named 'centreline' holding exactly one LineString feature."),
    ("R25", 1, "The response delivers a GeoPackage file named exactly 'CB_HaulRoad_Centreline.gpkg'."),
    ("R26", 1, "The response delivers a CSV file named exactly 'CB_HaulRoad_Vertices.csv'."),
    ("R27", 1, "The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, "
               "landcover_class, cum_cost_usd."),
    ("R28", 1, "The response delivers a PDF file named exactly 'CB_HaulRoad_RouteReport.pdf'."),
    ("R29", 1, "The PDF report contains a plan figure showing the route centreline."),
    ("R30", 1, "The PDF report contains a long section plotting elevation against chainage along the route."),
    ("R33", 7, "The PDF report states that the adopted route climbs the escarpment by the northern slump, reaching "
               "N 3 351 475 (+/- 25 m) before returning south along the plateau to G1."),
    ("R35", 5, "The PDF report states that the saddle gap in the escarpment beside HS-1 is closed by the 150 m HS-1 "
               "exclusion measured to the edge of the road formation."),
    ("R34", 3, "The CSV vertex table has 455 data rows (+/- 2), one per route cell from start to end."),
    ("R31", 5, "The PDF report states a route length in woodland of 467.0 m (+/- 3 percent)."),
    ("R32", 5, "The PDF report states a route length in grassland / pasture of 3,935.3 m (+/- 3 percent)."),
    ("N1", -7, "The CSV vertex table contains a grade_to_next_pct value whose absolute value exceeds 10.0."),
    ("N2", -5, "The response presents the alignment as approved, issued or released for construction."),
    ("N3", -3, "The PDF report states horizontal curve radii, sight distances or earthworks volumes for the route."),
    ("N4", -5, "The PDF report states two different total cost values for the adopted route."),
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


def grade_files(d, claims):
    d = Path(d)
    res = {}
    g = d / "CB_HaulRoad_Centreline.gpkg"
    c = d / "CB_HaulRoad_Vertices.csv"
    res["R25"] = g.exists(); res["R26"] = c.exists(); res["R28"] = (d / "CB_HaulRoad_RouteReport.pdf").exists()
    gdf = gpd.read_file(g, layer="centreline")
    res["R24"] = len(gdf) == 1 and gdf.geometry.iloc[0].geom_type == "LineString"
    res["R23"] = gdf.crs is not None and gdf.crs.to_epsg() == 32614
    P = np.array(gdf.geometry.iloc[0].coords)[:, :2]
    res["R5"] = near(P, X2, 30); res["R6"] = near(P, CPA, 25); res["R7"] = near(P, CPB, 25); res["R8"] = near(P, CPD, 25)
    V = np.diff(P, axis=0)
    ang = np.degrees(np.arctan2(V[:, 1], V[:, 0]))
    dev = np.abs((np.diff(ang) + 180) % 360 - 180)
    res["R9"] = bool((dev <= 45 + 1e-6).all())
    res["R11"] = wetland_clearance(P) > 37.0
    res["R12"] = seg_point(P, np.array(HS1)) > 157.0
    res["R13"] = bool(np.all(np.abs(P[0] - START) <= 1))
    res["R14"] = bool(np.all(np.abs(P[-1] - END) <= 1))
    dP = np.abs(V)
    res["R21"] = bool(np.all(np.isin(np.round(dP, 3), [0, 10])) and np.all(dP.max(1) > 0))
    rows = list(csv.reader(open(c)))
    res["R27"] = [h.strip() for h in rows[0]] == HEADER
    body = rows[1:]
    res["R15"] = abs(float(body[0][3]) - 374.54) <= 0.05
    gr = [abs(float(r[5])) for r in body if r[5] != ""]
    ch = [float(r[4]) for r in body]
    res["N1"] = max(gr) > 10.0
    run_max, k = 0.0, 0
    while k < len(gr):
        if gr[k] > 8.0:
            s = k
            while k < len(gr) and gr[k] > 8.0:
                k += 1
            run_max = max(run_max, ch[k] - ch[s])
        else:
            k += 1
    res["R10"] = run_max <= 60.0 + 1e-6
    res["R22"] = abs(float(body[-1][7]) - claims["cost"]) <= 1
    res["R1"] = abs(claims["cost"] - 2618856) <= 0.005 * 2618856
    res["R2"] = abs(claims["length"] - 5513.4) <= 0.005 * 5513.4
    res["R34"] = abs(len(body) - 455) <= 2
    res["R16"] = abs(claims["max_grade"] - 9.96) <= 0.03
    res["R20"] = abs(claims["steep_run"] - 56.6) <= 0.5
    for k2, (cls, v) in LC.items():
        res[k2] = abs(claims["len_by"].get(cls, 0.0) - v) <= 0.03 * v
    res["R33"] = claims["slump"] and abs(claims["n_max"] - 3351475) <= 25
    for k2 in ("R35", "R3", "R4", "R17", "R18", "R19", "R29", "R30", "N2", "N3", "N4"):
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
        cost=float(f"{s['cost_usd']:.2f}"), length=round(s["length_m"], 2), max_grade=round(s["max_grade_pct"], 2),
        steep_run=round(s["max_steep_run_m"], 1), n_max=s["n_max"],
        slump="climbs the slump" in t and "returns south along the plateau" in t,
        R3="X-1 is not feasible" in t and "no compliant route" in t,
        R4="formation edge would be" in t and "35.0 m from the W-1 boundary" in t,
        R35="saddle gap next to HS-1 is closed by the 150 m exclusion measured to the formation edge" in t,
        R17="14.00 m" in t and "7.00 m either side" in t,
        R18="spur crest" in t and "breaks T3 (60 m)" in t,
        R19="chute" in t and "135 deg switchbacks" in t and "breaks T4" in t,
        R29="plan" in t.lower(), R30="long section" in t.lower(),
        len_by=s["len_by"],
        N2=False, N3=False, N4=False,
    )


def simulate():
    import tempfile
    import solve as SV
    from shapely.geometry import LineString
    base = dict(R29=True, R30=True, N2=False, N3=False, N4=False)
    # claims a response would make given which C-003 rules it applied (generous: any rule applied is also explained)
    cases = [
        ("A  C-003 not read (Rev B rules only)", {"no_width": True, "no_turn": True, "no_sustain": True}),
        ("B  T3 + T4 applied, formation width missed", {"no_width": True}),
        ("C  width + T4 applied, T3 sustained grade missed", {"no_sustain": True}),
        ("D  width + T3 applied, T4 turn limit missed", {"no_turn": True}),
        ("E  width only", {"no_turn": True, "no_sustain": True}),
        ("F  T4 only", {"no_width": True, "no_sustain": True}),
        ("G  T3 only", {"no_width": True, "no_turn": True}),
        ("H  all C-003 applied, HS-1 exclusion missed", {"no_heritage": True}),
    ]
    out = []
    for name, opts in cases:
        r = SV.solve(opts)
        rows, L = SV.summarise(r)
        cp = SV.check_path(r)
        width, turn, sus = not opts.get("no_width"), not opts.get("no_turn"), not opts.get("no_sustain")
        d = Path(tempfile.mkdtemp())
        gpd.GeoDataFrame(geometry=[LineString([(x["easting"], x["northing"]) for x in rows])], crs="EPSG:32614") \
            .to_file(d / "CB_HaulRoad_Centreline.gpkg", layer="centreline", driver="GPKG")
        with open(d / "CB_HaulRoad_Vertices.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(HEADER)
            for x in rows:
                w.writerow([x["seq"], x["easting"], x["northing"], x["elev_m"], x["chainage_m"],
                            "" if math.isnan(x["grade_pct"]) else x["grade_pct"], x["landcover"], x["cum_cost_usd"]])
        (d / "CB_HaulRoad_RouteReport.pdf").write_bytes(b"%PDF-1.4")
        lb = {}
        for a, c in zip(rows[:-1], rows[1:]):
            dd = c["chainage_m"] - a["chainage_m"]
            lb[a["landcover"]] = lb.get(a["landcover"], 0) + dd / 2
            lb[c["landcover"]] = lb.get(c["landcover"], 0) + dd / 2
        claims = dict(base, cost=r["cost"], length=L, max_grade=round(cp["max_grade"], 2),
                      steep_run=round(float(cp["max_steep_run"]), 1), len_by=lb,
                      n_max=max(x["northing"] for x in rows), slump=True,
                      R35=width and not opts.get("no_heritage"),
                      R3=width, R4=width, R17=width, R18=sus, R19=turn)
        res = grade_files(d, claims)
        s, got, pos = score(res)
        fails = [k for k, w, _ in RUBRIC if (res[k] if w < 0 else not res[k])]
        out.append((name, s, fails))
        print(f"{name:52s} {s:6.1%}  lost: {' '.join(fails)}")
    print(f"mean {np.mean([o[1] for o in out]):.1%}")
    return out


if __name__ == "__main__":
    wts = [w for _, w, _ in RUBRIC]
    print("items", len(RUBRIC), {w: wts.count(w) for w in sorted(set(wts), reverse=True)})
    tgt = sys.argv[1] if len(sys.argv) > 1 else "golden"
    if tgt == "golden":
        r = grade_files(ROOT / "golden", golden_claims())
        s, got, pos = score(r)
        print(f"GOLDEN score {s:.1%} ({got}/{pos})", [k for k, w, _ in RUBRIC if (r[k] if w < 0 else not r[k])])
    else:
        simulate()
