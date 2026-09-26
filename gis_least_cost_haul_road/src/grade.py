"""Scripted grader for the objective rubric items, plus simulated failing responses for calibration.

Report-text items (statements in the PDF) are graded from a small claims dict for the simulated
responses and by text search in the golden PDF.
"""
import csv
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
X2 = (584613.48, 3349580.00)
HS1 = (585511.90, 3350201.90)
C1 = (584205.0, 3349705.0)
C2 = (585125.0, 3350405.0)
C3 = (585695.0, 3351315.0)
LC = {"R28": "Woodland", "R29": "Existing gravel track", "R30": "Grassland / pasture"}
HEADER = ["seq", "easting_m", "northing_m", "elev_m", "chainage_m", "grade_to_next_pct", "landcover_class",
          "cum_cost_usd"]

RUBRIC = [
    # id, weight, text
    ("R1", 9, "The PDF report states a total route cost of 2,339,944 USD (+/- 0.5 percent, 2,328,244 to 2,351,644 USD)."),
    ("R2", 7, "The PDF report states a horizontal route length of 4,921.4 m (+/- 1 percent, 4,872.2 to 4,970.7 m)."),
    ("R3", 9, "The PDF report states that no compliant route exists through crossing window X-1."),
    ("R4", 5, "The PDF report attributes the infeasibility of crossing window X-1 to the 30 m wetland setback closing the west-bank approach to X-1."),
    ("R5", 9, "The GeoPackage centreline has a vertex within 30 m of E 584 613.5, N 3 349 580.0 (EPSG:32614), the centre of approved crossing window X-2."),
    ("R6", 7, "The GeoPackage centreline has a vertex within 25 m of E 584 205, N 3 349 705 (EPSG:32614)."),
    ("R7", 5, "The GeoPackage centreline has a vertex within 25 m of E 585 125, N 3 350 405 (EPSG:32614)."),
    ("R8", 7, "The GeoPackage centreline has a vertex within 25 m of E 585 695, N 3 351 315 (EPSG:32614)."),
    ("R9", 9, "Every vertex of the GeoPackage centreline lies more than 150 m from E 585 511.9, N 3 350 201.9 (EPSG:32614)."),
    ("R10", 3, "The first vertex of the GeoPackage centreline is at E 583 155.0, N 3 349 105.0 (EPSG:32614, +/- 1 m on each)."),
    ("R11", 3, "The last vertex of the GeoPackage centreline is at E 586 315.0, N 3 350 995.0 (EPSG:32614, +/- 1 m on each)."),
    ("R12", 7, "The CSV vertex table gives an elev_m of 374.54 m (+/- 0.05 m) on its first row."),
    ("R14", 3, "The PDF report states a maximum route grade of 9.48 percent (+/- 0.10 percentage points)."),
    ("R15", 3, "Every pair of consecutive GeoPackage centreline vertices is separated by 10 m in easting, northing or both, with no other separation."),
    ("R16", 1, "The cum_cost_usd value on the last row of the CSV vertex table equals the total route cost stated in the PDF report within 1 USD."),
    ("R17", 3, "The PDF report states a woodland base unit rate of 940 USD per metre."),
    ("R18", 5, "The PDF report states that the saddle (lowest pass) over Cedar Bluff Ridge lies within the 150 m HS-1 heritage exclusion."),
    ("R19", 5, "The GeoPackage centreline layer CRS is EPSG:32614 (WGS 84 / UTM zone 14N)."),
    ("R20", 3, "The GeoPackage contains a layer named 'centreline' holding exactly one LineString feature."),
    ("R21", 1, "The response delivers a GeoPackage file named exactly 'CB_HaulRoad_Centreline.gpkg'."),
    ("R22", 1, "The response delivers a CSV file named exactly 'CB_HaulRoad_Vertices.csv'."),
    ("R23", 1, "The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, cum_cost_usd."),
    ("R24", 1, "The response delivers a PDF file named exactly 'CB_HaulRoad_RouteReport.pdf'."),
    ("R25", 1, "The PDF report contains a plan figure showing the route centreline."),
    ("R26", 1, "The PDF report contains a long section plotting elevation against chainage along the route."),
    ("R28", 5, "The PDF report states a route length in woodland of 467.0 m (+/- 3 percent)."),
    ("R29", 5, "The PDF report states a route length on the existing gravel track of 876.1 m (+/- 3 percent)."),
    ("R30", 3, "The PDF report states a route length in grassland / pasture of 3,343.4 m (+/- 3 percent)."),
    ("N1", -7, "The CSV vertex table contains a grade_to_next_pct value whose absolute value exceeds 10.0."),
    ("N2", -5, "The response presents the alignment as approved, issued or released for construction."),
    ("N3", -3, "The PDF report states horizontal curve radii, sight distances or earthworks volumes for the route."),
    ("N4", -5, "The PDF report states two different total cost values for the adopted route."),
]


def near(P, q, tol):
    return bool((np.hypot(P[:, 0] - q[0], P[:, 1] - q[1]) <= tol).any())


def grade_files(d, claims):
    d = Path(d)
    res = {}
    g = d / "CB_HaulRoad_Centreline.gpkg"
    c = d / "CB_HaulRoad_Vertices.csv"
    res["R21"] = g.exists(); res["R22"] = c.exists(); res["R24"] = (d / "CB_HaulRoad_RouteReport.pdf").exists()
    gdf = gpd.read_file(g, layer="centreline")
    res["R20"] = len(gdf) == 1 and gdf.geometry.iloc[0].geom_type == "LineString"
    res["R19"] = gdf.crs is not None and gdf.crs.to_epsg() == 32614
    P = np.array(gdf.geometry.iloc[0].coords)[:, :2]
    res["R5"] = near(P, X2, 30); res["R6"] = near(P, C1, 25); res["R7"] = near(P, C2, 25); res["R8"] = near(P, C3, 25)
    res["R9"] = bool((np.hypot(P[:, 0] - HS1[0], P[:, 1] - HS1[1]) > 150).all())
    res["R10"] = bool(np.all(np.abs(P[0] - [583155, 3349105]) <= 1))
    res["R11"] = bool(np.all(np.abs(P[-1] - [586315, 3350995]) <= 1))
    dP = np.abs(np.diff(P, axis=0))
    res["R15"] = bool(np.all(np.isin(np.round(dP, 3), [0, 10])) and np.all(dP.max(1) > 0))
    rows = list(csv.reader(open(c)))
    res["R23"] = [h.strip() for h in rows[0]] == HEADER
    body = rows[1:]
    res["R12"] = abs(float(body[0][3]) - 374.54) <= 0.05
    gr = [abs(float(r[5])) for r in body if r[5] != ""]
    res["N1"] = max(gr) > 10.0
    res["R16"] = abs(float(body[-1][7]) - claims["cost"]) <= 1
    res["R1"] = abs(claims["cost"] - 2339944) <= 0.005 * 2339944
    res["R2"] = abs(claims["length"] - 4921.4) <= 0.01 * 4921.4
    res["R14"] = abs(claims["max_grade"] - 9.48) <= 0.10
    for k, v, tol in (("R28", 467.0, 0.03), ("R29", 876.1, 0.03), ("R30", 3343.4, 0.03)):
        res[k] = abs(claims["len_by"].get(LC[k], 0.0) - v) <= tol * v
    for k in ("R3", "R4", "R17", "R18", "R25", "R26", "N2", "N3", "N4"):
        res[k] = bool(claims[k])
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
        R3="X-1 is not feasible" in t and "no compliant route" in t,
        R4="30 m wetland setback" in t,
        R17="940 USD/m" in t,
        R18="saddle" in t and "HS-1 150 m exclusion" in t,
        R25="plan" in t.lower(), R26="long section" in t.lower(),
        len_by=s["len_by"],
        N2=False, N3=False, N4=False,
    )


def simulate():
    import tempfile
    import solve as SV
    from shapely.geometry import LineString
    base = dict(R25=True, R26=True, N2=False, N3=False, N4=False)
    cases = [
        ("A  misses 30 m wetland setback (uses X-1)", {"no_setback": True}, None,
         dict(R3=False, R4=False, R17=True, R18=False)),
        ("B  misses HS-1 exclusion (takes saddle)", {"no_heritage": True}, None,
         dict(R3=True, R4=True, R17=True, R18=False)),
        ("C  uses Rev A woodland rate only", {}, 690.0, dict(R3=True, R4=True, R17=False, R18=True)),
        ("D  isotropic slope raster instead of move grade", {"isotropic": True}, None,
         dict(R3=True, R4=True, R17=True, R18=True)),
        ("E  setback + Rev A missed", {"no_setback": True}, 690.0, dict(R3=False, R4=False, R17=False, R18=False)),
        ("F  setback + HS-1 + Rev A missed", {"no_setback": True, "no_heritage": True}, 690.0,
         dict(R3=False, R4=False, R17=False, R18=False)),
        ("G  HS-1 + Rev A missed", {"no_heritage": True}, 690.0, dict(R3=True, R4=True, R17=False, R18=False)),
    ]
    out = []
    for name, opts, wood, cl in cases:
        keep = SV.BRIEF["classes"]["3"]["cost"]
        if wood:
            SV.BRIEF["classes"]["3"]["cost"] = wood
        r = SV.solve(opts)
        rows, L = SV.summarise(r)
        SV.BRIEF["classes"]["3"]["cost"] = keep
        d = Path(tempfile.mkdtemp())
        gpd.GeoDataFrame(geometry=[LineString([(x["easting"], x["northing"]) for x in rows])], crs="EPSG:32614") \
            .to_file(d / "CB_HaulRoad_Centreline.gpkg", layer="centreline", driver="GPKG")
        with open(d / "CB_HaulRoad_Vertices.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(HEADER)
            for x in rows:
                w.writerow([x["seq"], x["easting"], x["northing"], x["elev_m"], x["chainage_m"],
                            "" if np.isnan(x["grade_pct"]) else x["grade_pct"], x["landcover"], x["cum_cost_usd"]])
        (d / "CB_HaulRoad_RouteReport.pdf").write_bytes(b"%PDF-1.4")
        mg = max(abs(x["grade_pct"]) for x in rows[:-1])
        lb = {}
        for a, c in zip(rows[:-1], rows[1:]):
            dd = c["chainage_m"] - a["chainage_m"]
            lb[a["landcover"]] = lb.get(a["landcover"], 0) + dd / 2
            lb[c["landcover"]] = lb.get(c["landcover"], 0) + dd / 2
        claims = dict(base, cost=r["cost"], length=L, max_grade=round(mg, 2), len_by=lb, **cl)
        res = grade_files(d, claims)
        s, got, pos = score(res)
        fails = [k for k, w, _ in RUBRIC if (res[k] if w < 0 else not res[k])]
        out.append((name, s, fails))
        print(f"{name:52s} {s:6.1%}  lost: {' '.join(fails)}")
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
