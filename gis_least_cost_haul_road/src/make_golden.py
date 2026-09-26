"""Produce the golden deliverables: GeoPackage centreline, vertex CSV and PDF route report."""
import collections
import csv
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)
from shapely.geometry import LineString

import solve as SV

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "golden"
WORK = ROOT / "work"
GPKG = "CB_HaulRoad_Centreline.gpkg"
CSVF = "CB_HaulRoad_Vertices.csv"
PDFF = "CB_HaulRoad_RouteReport.pdf"
CSV_HEADER = ["seq", "easting_m", "northing_m", "elev_m", "chainage_m", "grade_to_next_pct", "landcover_class",
              "unit_rate_usd_per_m", "cum_constr_usd", "cum_haul_usd", "cum_cost_usd"]


def main():
    OUT.mkdir(exist_ok=True)
    b = SV.BRIEF
    res = SV.solve({})
    rows, L = SV.summarise(res)
    cost = res["cost"]
    g = np.array([r["grade_pct"] for r in rows[:-1]])
    chk = SV.check_path(res)
    clr = SV.clearances(res)
    assert chk["max_grade"] <= b["max_grade"] and chk["max_turn_deg"] <= b["max_deflection_deg"]
    assert chk["max_steep_run"] <= b["steep_run_max"] + 1e-9
    assert chk["max_adverse_loaded"] <= b["eff_adverse_max"] - b["rolling_resistance"]
    assert chk["min_k"] >= b["min_k"]
    t_mid, t_end = SV.tangent_lengths(b["min_radius"])
    assert chk["min_tangent"] >= t_mid and min(chk["start_tangent"], chk["end_tangent"]) >= t_end
    constr, haul = rows[-1]["cum_constr_usd"], rows[-1]["cum_haul_usd"]
    assert abs(constr + haul - cost) < 1e-6
    half = b["formation_width"] / 2
    assert clr["wetland_m"] - half >= b["wetland_setback"] and clr["heritage_m"] - half >= b["heritage_radius"]
    pe = SV.PROMPT_E
    assert chk["max_zone_run"] <= pe["zone_run_max"] + 1e-9 and chk["gate_ok"]

    with open(OUT / CSVF, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for r in rows:
            w.writerow([r["seq"], f"{r['easting']:.2f}", f"{r['northing']:.2f}", f"{r['elev_m']:.3f}",
                        f"{r['chainage_m']:.2f}", "" if np.isnan(r["grade_pct"]) else f"{r['grade_pct']:.3f}",
                        r["landcover"], f"{r['unit_rate']:.2f}", f"{r['cum_constr_usd']:.2f}",
                        f"{r['cum_haul_usd']:.2f}", f"{r['cum_cost_usd']:.2f}"])

    line = LineString([(r["easting"], r["northing"]) for r in rows])
    gdf = gpd.GeoDataFrame(
        dict(route_id=["CB-HR-01E"], total_cost_usd=[round(cost, 2)], length_m=[round(L, 2)]),
        geometry=[line], crs=f"EPSG:{b['epsg']}")
    (OUT / GPKG).unlink(missing_ok=True)
    gdf.to_file(OUT / GPKG, layer="centreline", driver="GPKG")

    # breakdowns: each move's length and cost split equally between its two end cells' classes
    len_by = collections.defaultdict(float)
    cost_by = collections.defaultdict(float)
    lease_len = 0.0
    for a, c in zip(rows[:-1], rows[1:]):
        d = c["chainage_m"] - a["chainage_m"]
        seg = c["cum_constr_usd"] - a["cum_constr_usd"]
        ca, cc = a["unit_rate"], c["unit_rate"]
        for x, share in ((a, ca / (ca + cc)), (c, cc / (ca + cc))):
            len_by[x["landcover"]] += d / 2
            cost_by[x["landcover"]] += seg * share
            if x["unit_rate"] == pe["plateau_grass_cost"]:
                lease_len += d / 2
    bands = [(0, 3), (3, 6), (6, 8), (8, 10)]
    dists = np.diff([r["chainage_m"] for r in rows])
    band_len = [float(dists[(np.abs(g) > lo) & (np.abs(g) <= hi) | ((lo == 0) & (np.abs(g) == 0))].sum())
                for lo, hi in bands]

    variants = [
        ("Adopted route (drawing set Rev D + Rev E updates)", {}),
        ("Check: Rev E updates ignored (Rev D basis)", SV.REV_E_OFF),
        ("Check: plateau lease rate not applied", {"no_plateau": True}),
        ("Check: lease rate applied to all grassland", {"plateau_all": True}),
        ("Check: slip-zone 30 m limit tested only on moves inside the band", {"zone_per_move": True}),
        ("Check: slip-zone limit ignored", {"no_zone": True}),
        ("Check: gate approach ignored", {"no_gate": True}),
        ("Check: gate approach of 3 moves (30 m)", {"gate_moves": 3}),
        ("Check: D3 loaded adverse limit ignored (or 9.0 % read as grade)", {"no_adverse": True}),
        ("Check: D5 vertical curvature ignored", {"no_vc": True}),
        ("Check: D6 curve radius ignored", {"no_tangent": True}),
        ("Check: D6 with R tan(22.5) between deflections", {"tan_single": True}),
        ("Check: D7 haulage ignored (construction cost only)", {"no_haul": True}),
        ("Check: D7 rise charged in chainage direction", {"haul_flip": True}),
        ("Check: D7 threshold 4.0 % read as grade (no rolling resistance)", {"haul_no_rr": True}),
        ("Check: D7 threshold ignored (every loaded rise charged)", {"haul_linear": True}),
        ("Check: G1 at superseded Rev C position", {"end_revc": True}),
        ("Check: EPSG:2277 read as international feet", {"end_intl": True}),
        ("Check: C-004 ignored entirely (Rev C rules)", SV.VARIANTS["revC_rules"]),
        ("Check: 45 deg direction-change limit (T4) ignored", {"no_turn": True}),
        ("Check: 60 m sustained-grade limit (T3) ignored", {"no_sustain": True}),
        ("Check: without HS-1 exclusion", {"no_heritage": True}),
    ]
    var_rows = []
    for name, o in variants:
        rr = SV.solve(o)
        rws, LL = SV.summarise(rr)
        cp = SV.check_path(rr)
        var_rows.append([name, f"{rr['cost']:,.0f}", f"{LL:,.1f}", f"{len(rws)}", SV.xing(rws),
                         f"{cp['max_adverse_loaded']:.2f}", f"{cp['min_k']:.2f}", f"{cp['min_tangent']:.1f}"])
    for o in ({"adv_flip": True}, {"adv_abs": True}, {"vc_flat": 10.0 / 1.4}):
        assert SV.solve(o) is None
    only_x1 = SV.solve({"drop_X2": True})
    assert only_x1 is None
    assert SV.solve({"gate_heading": 2}) is None
    assert SV.solve({"end_nosaf": True}) is None

    figs = plan_and_profile(res, rows)
    write_pdf(rows, L, cost, g, len_by, cost_by, band_len, var_rows, figs, chk, clr, res["pts"], constr, haul,
              lease_len)
    summary = dict(cost_usd=cost, constr_usd=constr, haul_usd=haul, loaded_rise_m=haul / b["haul_rise_cost"],
                   lease_len_m=lease_len, max_zone_run_m=chk["max_zone_run"],
                   min_k=chk["min_k"], min_tangent_m=chk["min_tangent"], start_tangent_m=chk["start_tangent"],
                   end_tangent_m=chk["end_tangent"], n_deflections=chk["n_deflections"],
                   max_adverse_loaded_pct=chk["max_adverse_loaded"], max_rise_pct=chk["max_rise"],
                   g1_utm=list(res["pts"]["END"]), length_m=L, n_vertices=len(rows), max_grade_pct=float(np.abs(g).max()),
                   max_turn_deg=chk["max_turn_deg"], max_steep_run_m=float(chk["max_steep_run"]),
                   wetland_clear_m=clr["wetland_m"], heritage_clear_m=clr["heritage_m"],
                   crossing=SV.xing(rows), n_max=max(r["northing"] for r in rows),
                   start=[rows[0]["easting"], rows[0]["northing"]], end=[rows[-1]["easting"], rows[-1]["northing"]],
                   start_elev_m=rows[0]["elev_m"], end_elev_m=rows[-1]["elev_m"],
                   len_by=len_by, cost_by=cost_by, band_len=band_len, variants=var_rows)
    (WORK / "golden_summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps(summary, indent=1, default=float))


def b_cost(name):
    for info in SV.BRIEF["classes"].values():
        if info["name"] == name:
            return info["cost"] if info["cost"] is not None else SV.BRIEF["culvert_cost"]
    raise KeyError(name)


def plan_and_profile(res, rows):
    b = SV.BRIEF
    lcd, EX, EY, z = res["lcd"], res["EX"], res["EY"], res["z"]
    rgb = np.zeros(lcd.shape + (3,))
    for c, info in b["classes"].items():
        rgb[lcd == int(c)] = np.array(info["rgb"]) / 255
    fig, ax = plt.subplots(figsize=(11, 8.2))
    ext = [b["dem_ul_e"], b["dem_ul_e"] + 3600, b["dem_ul_n"] - 2800, b["dem_ul_n"]]
    ax.imshow(rgb, extent=ext, origin="upper", interpolation="nearest")
    blocked = np.isnan(res["base"]) & (lcd != 6)
    ax.imshow(np.ma.masked_where(~blocked, blocked), extent=ext, origin="upper", cmap="Greys", alpha=0.35,
              vmin=0, vmax=1, interpolation="nearest")
    cs = ax.contour(EX, EY, z, levels=np.arange(360, 520, 5), colors="k", linewidths=0.3)
    ax.clabel(cs, cs.levels[::2], fontsize=6, fmt="%d m")
    pe = SV.PROMPT_E
    ax.axhspan(pe["zone_n_min"], pe["zone_n_max"], color="purple", alpha=0.15, lw=0,
               label=f"Rev E slip zone (runs > 8 % touching it <= {pe['zone_run_max']:.0f} m)")
    lease = (lcd == 1) & (res["base"] == pe["plateau_grass_cost"])
    ax.contour(EX, EY, lease.astype(float), levels=[0.5], colors="blue", linewidths=1.0, linestyles="--")
    ax.plot([], [], "b--", lw=1.0, label=f"Rev E plateau lease edge (grassland >= {pe['plateau_ft']:,.0f} ft)")
    p = np.array([(r["easting"], r["northing"]) for r in rows])
    ax.plot(p[:, 0], p[:, 1], color="red", lw=2.2, label="Adopted centreline CB-HR-01E")
    h = res["pts"]["HERITAGE"]
    ax.add_patch(plt.Circle(h, 150, fill=False, ec="darkred", lw=1.5, ls="--", label="HS-1 150 m exclusion"))
    for k, lab in (("START", "T1"), ("END", "G1"), ("X1", "X-1"), ("X2", "X-2"), ("HERITAGE", "HS-1")):
        ax.plot(*res["pts"][k], "k^", ms=7)
        ax.annotate(lab, res["pts"][k], (res["pts"][k][0] + 40, res["pts"][k][1] + 40), fontsize=9, weight="bold")
    for ch in range(0, int(rows[-1]["chainage_m"]), 500):
        r = min(rows, key=lambda x: abs(x["chainage_m"] - ch))
        ax.annotate(f"{ch/1000:.1f} km", (r["easting"], r["northing"]), fontsize=7, color="darkred",
                    xytext=(4, -10), textcoords="offset points")
    ax.set_aspect("equal"); ax.legend(loc="lower right", fontsize=8)
    ax.set_xlabel("Easting (m), EPSG:32614"); ax.set_ylabel("Northing (m)")
    ax.ticklabel_format(useOffset=False, style="plain"); ax.tick_params(labelsize=7)
    ax.set_title("Plan - adopted least-cost centreline (grey = prohibited / setback cells)")
    fig.tight_layout(); f1 = WORK / "golden_plan.png"; fig.savefig(f1, dpi=170); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 3.6))
    ch = [r["chainage_m"] for r in rows]; el = [r["elev_m"] for r in rows]
    ax.plot(ch, el, "k", lw=1.2)
    for a, c in zip(rows[:-1], rows[1:]):
        if abs(a["grade_pct"]) > b["steep_grade"]:
            ax.axvspan(a["chainage_m"], c["chainage_m"], color="orange", alpha=0.5, lw=0)
    ax.plot([], [], color="orange", lw=6, alpha=0.5, label="moves steeper than 8.0 % (each run <= 60.0 m); grades signed T1 to G1")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_xlabel("Chainage (m)"); ax.set_ylabel("Elevation (m, NAVD 88)"); ax.grid(alpha=0.4)
    ax.set_title("Long section along adopted centreline (terrain at DEM cell centres)")
    fig.tight_layout(); f2 = WORK / "golden_profile.png"; fig.savefig(f2, dpi=170); plt.close(fig)
    return f1, f2


def write_pdf(rows, L, cost, g, len_by, cost_by, band_len, var_rows, figs, chk, clr, pts, constr, haul, lease_len):
    b = SV.BRIEF
    pe = SV.PROMPT_E
    half = b["formation_width"] / 2
    adv = b["eff_adverse_max"] - b["rolling_resistance"]
    t_mid, t_end = SV.tangent_lengths(b["min_radius"])
    e_ft, n_ft = b["g1_surface_ftus"]
    ss = getSampleStyleSheet()
    body = ss["BodyText"]; body.fontSize = 9.5; body.leading = 12.5
    h1, h2 = ss["Heading1"], ss["Heading2"]
    doc = SimpleDocTemplate(str(OUT / PDFF), pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title="CB Haul Road - Least-Cost Route Report", author="Route study team")
    ts = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                     ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])
    S = []
    S.append(Paragraph("Cedar Bluff Quarry Haul Road - Least-Cost Route Report (route CB-HR-01E)", h1))
    S.append(Paragraph("Basis: drawing set CB-HR C-001 to C-004 Rev D and the two rasters it registers, with the three "
                       "Rev E updates in the brief (plateau lease rate, Cedar Branch slip zone, G1 gate approach), which "
                       "govern where they differ from the drawing set. "
                       "Horizontal CRS WGS 84 / UTM zone 14N (EPSG:32614); lengths are horizontal. "
                       "Status: route study only, not for construction.", body))
    S.append(Spacer(1, 4))
    S.append(Paragraph("1. Result", h2))
    x2 = [r for r in rows if r["landcover"] == "Watercourse"]
    top = max(rows, key=lambda r: r["northing"])
    res_tab = [
        ["Quantity", "Value"],
        ["Total route cost, construction + loaded haulage (USD)", f"{cost:,.2f}"],
        ["   Construction cost (C-002 rates x grade factor)", f"{constr:,.2f}"],
        [f"   Loaded haulage cost (C-004 D7: {b['haul_rise_cost']:,.0f} USD/m x charged loaded rise)", f"{haul:,.2f}  ({haul / b['haul_rise_cost']:.3f} m of rise climbed loaded above 4.0 % effective)"],
        ["Horizontal length, start cell centre to end cell centre (m)", f"{L:,.2f}"],
        ["Vertices (DEM cell centres) / moves / deflection vertices", f"{len(rows)} / {len(rows) - 1} / {chk['n_deflections']}"],
        ["Start cell centre (T1 on CR-114)", f"E {rows[0]['easting']:.2f}  N {rows[0]['northing']:.2f}  z {rows[0]['elev_m']:.2f} m"],
        ["End cell centre (G1 re-surveyed, C-004 Table 6)", f"E {rows[-1]['easting']:.2f}  N {rows[-1]['northing']:.2f}  z {rows[-1]['elev_m']:.2f} m"],
        ["Creek crossing", f"Approved window {SV.xing(rows)}, culvert on {len(x2)} watercourse cells at N {x2[0]['northing']:.0f}"],
        ["Crossing through the other window (X-1)", "None compliant: no route exists through X-1 (Section 5)"],
        ["Max grade rising / falling in chainage direction (T1 10.0 %)", f"+{chk['max_rise']:.2f} % / -{chk['max_adverse_loaded']:.2f} %"],
        ["Max loaded uphill grade (D3: 9.0 - 3.0 = 6.0 %)", f"{chk['max_adverse_loaded']:.2f} %"],
        ["Longest continuous run of moves > 8.0 % (T3 60.0 m)", f"{chk['max_steep_run']:.1f} m"],
        [f"Longest run > 8.0 % touching the slip zone N {pe['zone_n_min']:,.0f} to {pe['zone_n_max']:,.0f} (limit {pe['zone_run_max']:.1f} m)",
         f"{chk['max_zone_run']:.1f} m"],
        [f"Route length on plateau lease (grassland at or above {pe['plateau_ft']:,.2f} ft, {pe['plateau_grass_cost']:,.0f} USD/m)",
         f"{lease_len:,.1f} m"],
        ["G1 gate approach (last 40.0 m straight, due west)", "4 westward moves from "
         f"E {rows[-5]['easting']:.0f} to E {rows[-1]['easting']:.0f} at N {rows[-1]['northing']:.0f}"],
        ["Largest change of direction between moves (T4 45 deg)", f"{chk['max_turn_deg']:.0f} deg"],
        ["Smallest K between consecutive moves (D5 1.4 m/%)", f"{chk['min_k']:.3f} m/%"],
        ["Shortest tangent between deflection vertices (D6: >= 2R tan 22.5 = 37.28 m)", f"{chk['min_tangent']:.2f} m"],
        ["Start to first / last to end deflection (D6: >= R tan 22.5 = 18.64 m)", f"{chk['start_tangent']:.2f} m / {chk['end_tangent']:.2f} m"],
        ["Escarpment ascent", f"northern slump; route reaches N {top['northing']:.0f} at E {top['easting']:.0f}, "
                              f"then returns south along the plateau to G1"],
        ["Formation edge to wetland W-1 / to HS-1", f"{clr['wetland_m'] - half:.1f} m (limit 30.0) / {clr['heritage_m'] - half:.1f} m (limit 150.0)"],
    ]
    t = Table(res_tab, colWidths=[125 * mm, 140 * mm]); t.setStyle(ts); S.append(t)
    S.append(PageBreak())
    S.append(Paragraph("2. Method", h2))
    for p in [
        "<b>Terrain.</b> DEM DN converted with Elevation(ft) = 1150.00 + 0.01 x DN (C-002 Table 1), then to metres with the US "
        "survey foot (1200/3937 m). Grades use metres on both axes.",
        "<b>Georeferencing.</b> Both rasters are pixel-is-area with the registered upper-left corner. DEM cell centres are at "
        "E 583 005 + 10i, N 3 351 495 - 10j. The land-cover raster has its own origin (E 582 900, N 3 351 620) and 20 m pixels; "
        "each DEM cell takes the class of the land-cover pixel containing its centre (exact RGB match).",
        f"<b>Control points.</b> T1, X-1, X-2 and HS-1 from C-002 Table 3 (WGS 84) with PROJ. G1 from C-004 Table 6: "
        f"TxDOT surface coordinates E {e_ft:,.2f} ft, N {n_ft:,.2f} ft, divided by the surface adjustment factor "
        f"{b['g1_saf']:.5f} to grid E {e_ft / b['g1_saf']:,.2f} ft, N {n_ft / b['g1_saf']:,.2f} ft in NAD83 / Texas Central, "
        f"US survey feet (EPSG:2277), then transformed with PROJ to E {pts['END'][0]:,.2f}, N {pts['END'][1]:,.2f} "
        f"(cell E {rows[-1]['easting']:.0f}, N {rows[-1]['northing']:.0f}). Using the surface values as grid puts G1 about "
        f"110 m east and 368 m north; reading the feet as international feet moves it about 6 m south into the next cell; the "
        f"superseded Rev C position (C-002 Table 3, still plotted on C-001) is two cells west.",
        f"<b>Road footprint (C-003).</b> Formation 1.00 + 1.00 + 10.00 + 1.00 + 1.00 = {b['formation_width']:.2f} m, "
        f"{half:.2f} m either side of the centreline; setback and exclusion measured to the formation edge along every move "
        f"(centreline clearance > {b['wetland_setback'] + half:.1f} m from wetland pixels, > {b['heritage_radius'] + half:.1f} m from HS-1).",
        "<b>C-003 Table 4.</b> T1 every move at most 10.0 %; T2/T3 consecutive moves steeper than 8.0 % total at most 60.0 m; "
        "T4 direction changes by at most 45 deg between consecutive moves.",
        f"<b>C-004 loaded direction (D1-D3).</b> Loaded trucks run G1 to T1, against chainage. A move that falls in chainage "
        f"direction is climbed loaded; its effective grade is grade + 3.0 % rolling resistance, limited to 9.0 %, so its "
        f"grade may not exceed {adv:.1f} %. Moves rising in chainage direction are loaded downhill and keep the 10.0 % T1 limit.",
        "<b>Vertical curvature (D5).</b> For consecutive moves of lengths L1, L2 and signed grades g1, g2, the distance "
        "between their midpoints along the centreline is (L1 + L2)/2, so |g2 - g1| <= (L1 + L2) / (2 x 1.4): 7.14 % "
        "between two orthogonal moves, 8.62 % orthogonal-diagonal, 10.10 % between two diagonal moves.",
        f"<b>Horizontal curves (D6).</b> Every deflection on the grid is 45 deg, so an arc of radius 45 m needs a tangent length "
        f"T = R tan(22.5 deg) = {t_end:.2f} m on each side. Arcs may not overlap, so successive deflection vertices must be at "
        f"least 2T = {t_mid:.2f} m apart (4 orthogonal or 3 diagonal moves), and the first and last deflection vertices at least "
        f"T = {t_end:.2f} m from the start and end cell centres (2 moves).",
        f"<b>Objective (C-004 Note D1, D7).</b> Move cost = d x (c_i + c_j)/2 x f(|g|) + {b['haul_rise_cost']:,.0f} x (z_i - z_j) when the move is "
        f"climbed loaded (falls in chainage direction) at an effective grade above {b['haul_eff_threshold']:.1f} %, i.e. a grade above "
        f"{b['haul_eff_threshold'] - b['rolling_resistance']:.1f} % once the 3.0 % rolling resistance is added; otherwise the construction "
        "term alone. The fall is not credited; the 450 USD/m brake-wear and 6.0 % empty top-gear figures in Table 7 are "
        "information only.",
        f"<b>Rev E (a) plateau lease.</b> A DEM cell whose class is Grassland / pasture and whose ground elevation is at or above "
        f"{pe['plateau_ft']:,.2f} ft takes a base unit rate of {pe['plateau_grass_cost']:,.0f} USD/m instead of 420 USD/m. The test is made "
        f"on the DEM value in feet (1150.00 + 0.01 x DN), i.e. {pe['plateau_ft'] * 1200 / 3937:.3f} m; no DEM cell lies exactly on the threshold.",
        f"<b>Rev E (b) Cedar Branch slip zone.</b> Any continuous run of moves steeper than 8.0 % that contains a move with either "
        f"end cell centre between N {pe['zone_n_min']:,.0f} and N {pe['zone_n_max']:,.0f} is limited to {pe['zone_run_max']:.1f} m over "
        f"its whole length, including the part outside the band. The steep-run state carries a flag set by the first such move "
        f"and cleared when the run ends.",
        "<b>Rev E (c) gate approach.</b> The last four moves into the G1 cell are due west (40.0 m straight), so the route enters "
        "the gate cell from the east side. Every drawing-set rule applies on the approach as elsewhere.",
        "<b>Search.</b> T3, T4, D5 and D6 depend on the path, so the search runs on an expanded state: cell x arrival heading "
        "(which also fixes the previous move and its grade for D5) x steep-run length and slip-zone flag (for T3 and Rev E b) "
        "x moves since the last deflection vertex, with a separate counter for the first tangent (for D6). The gate approach "
        "removes every move into the last four approach cells other than the westward one. Dijkstra on this graph gives the "
        "exact optimum; the end state is accepted only if the last tangent is at least 18.64 m.",
    ]:
        S.append(Paragraph(p, body)); S.append(Spacer(1, 2.5))
    S.pop()
    S.append(PageBreak())
    rt = [["Item applied", "Value"],
          ["Grassland / pasture; cultivated cropland", "420 / 480 USD/m"],
          [f"Grassland / pasture at or above {pe['plateau_ft']:,.2f} ft (Rev E plateau lease)", f"{pe['plateau_grass_cost']:,.0f} USD/m"],
          ["Rev E slip zone; gate approach", f"N {pe['zone_n_min']:,.0f} to {pe['zone_n_max']:,.0f}, runs > 8.0 % touching it "
           f"<= {pe['zone_run_max']:.1f} m; last 40.0 m due west into G1"],
          ["Woodland (Rev B; Rev A 690 withdrawn); rock outcrop", "940 / 1,150 USD/m"],
          ["Existing gravel track; culvert cell within 30.0 m of X-1 / X-2", "160 / 3,800 USD/m"],
          ["Watercourse elsewhere, wetland, farmstead", "prohibited"],
          ["Formation width; wetland setback; HS-1 radius (to formation edge)", f"{b['formation_width']:.1f} m; 30.0 m; 150.0 m"],
          ["T1 max grade; T2/T3 steep threshold / run; T4 turn", "10.0 %; > 8.0 % / 60.0 m; 45 deg"],
          ["D1 loaded direction; D2 rolling resistance; D3 effective limit", "G1 to T1; 3.0 %; 9.0 % (grade 6.0 %)"],
          ["D5 minimum K; D6 minimum radius", "1.4 m per %; 45.0 m (tangents 37.28 m / 18.64 m)"],
          ["D7 loaded haulage", f"{b['haul_rise_cost']:,.0f} USD per m of loaded rise on moves above {b['haul_eff_threshold']:.1f} % effective ({b['haul_eff_threshold'] - b['rolling_resistance']:.1f} % grade)"],
          ["Grade factor f(g)", "1.00 (g<=3); 1.00+0.05(g-3) (3<g<=6); 1.15+0.12(g-6) (6<g<=10)"]]
    t = Table(rt, colWidths=[125 * mm, 140 * mm]); t.setStyle(ts)
    S.append(Paragraph("Rates and constraint values applied (C-002, C-003, C-004 Rev D)", h2)); S.append(t)
    S.append(PageBreak())
    S.append(Paragraph("3. Plan and long section", h2))
    S.append(RLImage(str(figs[0]), width=180 * mm, height=134 * mm))
    S.append(PageBreak())
    S.append(RLImage(str(figs[1]), width=260 * mm, height=85 * mm))
    S.append(Paragraph("4. Breakdown", h2))
    order = ["Grassland / pasture", "Cultivated cropland", "Woodland", "Rock outcrop", "Existing gravel track", "Watercourse"]
    bt = [["Land-cover class", "Length (m)", "Construction cost (USD)"]]
    for k in order:
        if len_by.get(k, 0) > 0:
            bt.append([k if k != "Watercourse" else "Watercourse at X-2 (culvert)", f"{len_by[k]:,.1f}", f"{cost_by[k]:,.0f}"])
    bt.append(["Total", f"{sum(len_by.values()):,.1f}", f"{sum(cost_by.values()):,.0f}"])
    t = Table(bt, colWidths=[80 * mm, 35 * mm, 45 * mm]); t.setStyle(ts); S.append(t)
    S.append(Paragraph("Each move's length is split equally between its two end cells; its construction cost is split in "
                       "proportion to the two cells' unit rates. Loaded haulage is not allocated to classes.", body))
    gt = [["Grade band (abs)", "0-3 %", "3-6 %", "6-8 %", "8-10 %"], ["Length (m)"] + [f"{v:,.1f}" for v in band_len]]
    t = Table(gt, colWidths=[45 * mm] + [28 * mm] * 4); t.setStyle(ts); S.append(Spacer(1, 4)); S.append(t)
    S.append(PageBreak())
    S.append(Paragraph("5. What controls the alignment", h2))
    S.append(Paragraph(
        f"<b>Creek crossing - X-1 is not feasible.</b> At X-1 the eastern watercourse column is 35.0 m from the W-1 boundary; "
        f"the formation edge would be 35.0 - {half:.1f} = {35.0 - half:.1f} m from the wetland. With X-2 removed the search "
        f"finds no compliant route, so the only crossing is X-2.", body))
    S.append(Spacer(1, 2))
    S.append(Paragraph(
        "<b>Cedar Bluff escarpment.</b> The saddle gap next to HS-1 is closed by the 150 m exclusion measured to the formation "
        "edge; the spur crest grades at about 9.2 % for over 600 m and breaks T3 (60 m); the chute needs 90 and 135 deg "
        "switchbacks and breaks T4. The route climbs the northern slump and returns south along the plateau to G1.", body))
    S.append(Spacer(1, 2))
    S.append(Paragraph(
        f"<b>C-004.</b> The loaded-uphill limit (6.0 % on moves falling in chainage direction) reshapes the descent into the "
        f"Cedar Branch valley and the plateau return; applied the wrong way round (to chainage-rising moves) or to both "
        f"directions it closes every escarpment ascent, so no route exists. The 45 m radius forces tangents of at least "
        f"{t_mid:.2f} m between deflections and removes the short zig-zags the unconstrained optimum uses. K = 1.4 alters the "
        f"slump climb where steep runs are broken. Loaded haulage adds {haul:,.0f} USD and moves the route to one with less "
        f"loaded climbing above the top-gear range; because of the {b['haul_eff_threshold']:.1f} % threshold, charging the rise in "
        f"chainage direction, dropping the rolling resistance from the threshold or charging every loaded rise each gives a "
        f"different line. Each run below breaks exactly one stated rule and is not an option.", body))
    S.append(Spacer(1, 2))
    S.append(Paragraph(
        f"<b>Rev E.</b> The plateau lease cannot be avoided (G1 is on the plateau). At {pe['plateau_grass_cost']:,.0f} USD/m the grade "
        f"factor multiplies a larger base rate, which changes the trade-off between grade, length and loaded haulage on the "
        f"plateau: the plateau leg moves off the line it takes without the lease, although the length on leased ground "
        f"({lease_len:,.1f} m) is the same. The slip zone breaks "
        f"the two 56.6 m steep runs of the Rev D climb out of the Cedar Branch valley into runs of at most "
        f"{chk['max_zone_run']:.1f} m. The gate approach turns the end of the route to arrive from the east. Applying the "
        f"30 m limit only to moves inside the band, or ignoring any one of the three updates, gives a different line.", body))
    S.append(Spacer(1, 3))
    vt = [["Run", "Total (USD)", "Length (m)", "Vertices", "Xing", "Max loaded uphill %", "Min K", "Min tangent (m)"]] + var_rows
    vt.append(["D3 applied to chainage-rising moves / to both directions", "no route", "", "", "", "", "", ""])
    vt.append(["D5 read as a flat 7.14 % grade-change limit", "no route", "", "", "", "", "", ""])
    vt.append(["Only X-1 available", "no route", "", "", "", "", "", ""])
    vt.append(["Gate approach read as travelling east into G1", "no route", "", "", "", "", "", ""])
    vt.append(["G1 surface coordinates used as grid (SAF ignored): gate approach leaves the DEM", "no route", "", "", "", "", "", ""])
    t = Table(vt, colWidths=[98 * mm, 25 * mm, 22 * mm, 16 * mm, 12 * mm, 30 * mm, 16 * mm, 26 * mm]); t.setStyle(ts)
    S.append(t)
    S.append(Spacer(1, 5))
    S.append(Paragraph("6. Compliance and limitations", h2))
    for p in [
        f"Every move is at or below 10.0 % (max {chk['max_grade']:.2f} %); loaded uphill at most {chk['max_adverse_loaded']:.2f} %; "
        f"the longest run over 8.0 % is {chk['max_steep_run']:.1f} m; no change of direction exceeds {chk['max_turn_deg']:.0f} deg; "
        f"K >= {chk['min_k']:.3f}; tangents >= {chk['min_tangent']:.2f} m (ends {chk['start_tangent']:.2f} / {chk['end_tangent']:.2f} m); "
        f"the formation edge stays {clr['wetland_m'] - half:.1f} m from W-1 and {clr['heritage_m'] - half:.1f} m from HS-1; "
        f"the only watercourse cells used are within 30 m of X-2; the longest steep run touching the slip zone is "
        f"{chk['max_zone_run']:.1f} m; the last 40.0 m run due west into G1.",
        "The centreline is a 10 m raster least-cost path screened against C-004 geometry; it is a corridor, not a geometric "
        "design. Tie-break order, international versus US survey foot for the DEM, and thresholds moved by 0.02 (grade), "
        "0.01 (K) or 1 m (radius) give the same route.",
        "Deliverables: CB_HaulRoad_Centreline.gpkg (layer 'centreline', one LineString, EPSG:32614, fields route_id, "
        "total_cost_usd, length_m), CB_HaulRoad_Vertices.csv (one row per vertex, start to end, 11 columns; unit_rate_usd_per_m "
        "is the base rate of the vertex cell; cum_cost_usd = cum_constr_usd + cum_haul_usd), "
        "this report.",
    ]:
        S.append(Paragraph(p, body)); S.append(Spacer(1, 3))
    doc.build(S)


if __name__ == "__main__":
    main()
