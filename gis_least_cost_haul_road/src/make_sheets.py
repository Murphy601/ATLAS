"""Render drawing sheets C-001 / C-002 as raster images and embed them in a PDF."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrow
import numpy as np
from PIL import Image
from pyproj import Transformer
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas

import sitedef as S

ROOT = Path(__file__).resolve().parent.parent
B = json.loads((ROOT / "work" / "brief_values.json").read_text())
DPI = 200
W_IN, H_IN = 17.0, 11.0
TITLE = "CEDAR BLUFF AGGREGATES LLC  -  QUARRY HAUL ROAD ROUTE STUDY"


def title_block(fig, sheet, name):
    ax = fig.add_axes([0.80, 0.02, 0.185, 0.96])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, fill=False, lw=2))
    y = 0.97
    def line(txt, size=11, weight="normal", dy=0.03):
        nonlocal y
        ax.text(0.05, y, txt, fontsize=size, weight=weight, va="top", family="DejaVu Sans")
        y -= dy
    line("CLIENT", 8, "bold", 0.02); line("Cedar Bluff Aggregates LLC", 11, dy=0.045)
    line("PROJECT", 8, "bold", 0.02); line("Quarry Haul Road", 11, dy=0.025)
    line("Route Optioneering Study", 11, dy=0.045)
    line("DRAWING", 8, "bold", 0.02)
    for t in name:
        line(t, 12, "bold", 0.028)
    y -= 0.02
    line("REVISIONS", 8, "bold", 0.025)
    line("A  2026-08-03  Issued for route study", 9, dy=0.022)
    line("B  2026-09-14  Woodland clearing rate", 9, dy=0.018)
    line("                   revised (C-002 Table 2)", 9, dy=0.022)
    line("C  2026-09-24  Plant gate G1 relocated;", 9, dy=0.018)
    line("                   haul truck criteria and", 9, dy=0.018)
    line("                   typical section added", 9, dy=0.018)
    line("                   (Sheet C-003)", 9, dy=0.03)
    line("Rev C supersedes Rev B in full.", 9, "bold", 0.04)
    line("Horizontal: WGS 84 / UTM zone 14N", 9, dy=0.02)
    line("(EPSG:32614), metres", 9, dy=0.025)
    line("Vertical: NAVD 88, US survey feet", 9, dy=0.05)
    line("NOT FOR CONSTRUCTION", 12, "bold", 0.06)
    ax.plot([0, 1], [0.16, 0.16], "k", lw=1)
    ax.text(0.05, 0.14, "SHEET", fontsize=8, weight="bold", va="top")
    ax.text(0.05, 0.11, sheet, fontsize=30, weight="bold", va="top")
    ax.text(0.62, 0.14, "REV", fontsize=8, weight="bold", va="top")
    ax.text(0.62, 0.11, "C", fontsize=30, weight="bold", va="top")
    ax.text(0.05, 0.035, "Drawn: R.O.  Checked: J.M.  Date: 2026-09-24", fontsize=8)


def hillshade(z, cell, az=315, alt=45):
    gy, gx = np.gradient(z, cell)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azr, altr = np.radians(az), np.radians(alt)
    hs = np.sin(altr) * np.cos(slope) + np.cos(altr) * np.sin(slope) * np.cos(azr - aspect)
    return np.clip(hs, 0, 1)


def sheet1(path):
    dn = np.array(Image.open(ROOT / "inputs" / B["dem_file"]), float)
    zft = B["dn_base_ft"] + B["dn_step_ft"] * dn
    lc = np.array(Image.open(ROOT / "inputs" / B["lc_file"]).convert("RGB"))
    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI)
    fig.patch.set_facecolor("white")
    fig.add_artist(Rectangle((0.005, 0.005), 0.99, 0.99, fill=False, lw=2.5, transform=fig.transFigure))
    ax = fig.add_axes([0.05, 0.08, 0.72, 0.86])
    ext_dem = [B["dem_ul_e"], B["dem_ul_e"] + 3600, B["dem_ul_n"] - 2800, B["dem_ul_n"]]
    ext_lc = [B["lc_ul_e"], B["lc_ul_e"] + 20 * lc.shape[1], B["lc_ul_n"] - 20 * lc.shape[0], B["lc_ul_n"]]
    hs = hillshade(zft * S.FT_US, 10.0)
    ax.imshow(lc, extent=ext_lc, origin="upper", interpolation="nearest")
    ax.imshow(hs, extent=ext_dem, origin="upper", cmap="gray", alpha=0.35, vmin=0, vmax=1)
    ex = B["dem_ul_e"] + 10 * (np.arange(dn.shape[1]) + 0.5)
    ey = B["dem_ul_n"] - 10 * (np.arange(dn.shape[0]) + 0.5)
    cs = ax.contour(ex, ey, zft, levels=np.arange(1200, 1700, 10), colors="#3a2a1a", linewidths=0.35)
    maj = [l for l in cs.levels if l % 50 == 0]
    ax.contour(ex, ey, zft, levels=maj, colors="#3a2a1a", linewidths=0.9)
    ax.clabel(ax.contour(ex, ey, zft, levels=maj, colors="none"), fmt="%d", fontsize=7)

    to_utm = Transformer.from_crs(4326, B["epsg"], always_xy=True)
    P = {k: to_utm.transform(v[1], v[0]) for k, v in B["points_latlon"].items()}
    # indicative 2025 desk-study route (superseded)
    ind = [P["START"], (583420, 3349390), (583760, 3349700), (583980, 3350260), (584060, 3350600),
           (584180, 3350760), P["X1"], (584700, 3350700), (585250, 3350505), (585900, 3350505),
           (586150, 3350400), P["END"]]
    ind = np.array(ind)
    ax.plot(ind[:, 0], ind[:, 1], ls=(0, (6, 4)), color="#7a1fa2", lw=1.6)
    ax.annotate("INDICATIVE ROUTE - 2025 DESK STUDY\n(SUPERSEDED, NOT VERIFIED - SEE NOTE 7)",
                (584700, 3350850), (584750, 3351300), fontsize=8, color="#7a1fa2", weight="bold",
                arrowprops=dict(arrowstyle="->", color="#7a1fa2"))
    # county road
    ax.plot([583000, 583000], [3348700, 3351500], color="k", lw=4, solid_capstyle="butt")
    ax.text(583030, 3348760, "COUNTY ROAD CR-114 (EXISTING PAVED)", rotation=90, fontsize=8, weight="bold", va="bottom")
    sym = dict(START=("s", "TIE-IN T1\n(CR-114)"), END=("s", "QUARRY PLANT\nGATE G1"),
               X1=("D", "APPROVED CROSSING\nWINDOW X-1"), X2=("D", "APPROVED CROSSING\nWINDOW X-2"),
               HERITAGE=("*", "HERITAGE SITE HS-1\n(SYMBOL NOT TO SCALE)"))
    offs = dict(START=(40, 60), END=(-420, 90), X1=(60, 40), X2=(60, -120), HERITAGE=(60, -140))
    for k, (m, lab) in sym.items():
        ax.plot(*P[k], marker=m, ms=11 if m != "*" else 18, mfc="yellow" if k != "HERITAGE" else "red",
                mec="k", mew=1.2, ls="none", zorder=5)
        ax.annotate(lab, P[k], (P[k][0] + offs[k][0], P[k][1] + offs[k][1]), fontsize=8, weight="bold",
                    bbox=dict(fc="white", ec="k", lw=0.6, alpha=0.85), zorder=6)
    ax.text(584420, 3348780, "CEDAR BRANCH\n(PERENNIAL)", color="#1b4fa0", fontsize=9, weight="bold", rotation=80)
    ax.text(583950, 3351250, "FARMSTEAD", fontsize=8, weight="bold", color="#8a1010")
    ax.text(584120, 3350330, "WETLAND W-1", fontsize=8, weight="bold", color="#135c6b")
    ax.text(583300, 3349330, "EXISTING GRAVEL\nFARM TRACK", fontsize=8, weight="bold", color="#5a2d10", rotation=40)
    ax.text(585950, 3349050, "CEDAR BLUFF\nESCARPMENT", fontsize=9, weight="bold", color="#40342a")
    ax.set_xlim(582880, 586720); ax.set_ylim(3348600, 3351640)
    ax.set_aspect("equal")
    xt = np.arange(583000, 586700, 500); yt = np.arange(3348700, 3351600, 500)
    ax.set_xticks(xt); ax.set_xticklabels([f"E {v:,.0f}" for v in xt], fontsize=7)
    ax.set_yticks(yt); ax.set_yticklabels([f"N {v:,.0f}" for v in yt], fontsize=7)
    ax.grid(True, color="k", lw=0.25, alpha=0.4)
    # north arrow + scale bar
    ax.add_patch(FancyArrow(586560, 3351300, 0, 230, width=25, head_width=90, head_length=110, color="k"))
    ax.text(586560, 3351230, "N", ha="center", va="top", fontsize=14, weight="bold")
    for i in range(5):
        ax.add_patch(Rectangle((585700 + i * 100, 3348680), 100, 30, fc="k" if i % 2 == 0 else "w", ec="k"))
    ax.text(585700, 3348725, "0", fontsize=7); ax.text(586180, 3348725, "500 m", fontsize=7)
    ax.set_title("SITE CONSTRAINTS PLAN  -  PRESENTATION ONLY, DO NOT SCALE (SEE C-002 NOTE 1)", fontsize=13, weight="bold", loc="left")
    # legend
    lx = fig.add_axes([0.05, 0.005, 0.72, 0.065]); lx.axis("off"); lx.set_xlim(0, 1); lx.set_ylim(0, 1)
    items = [(B["classes"][c]["name"], np.array(B["classes"][c]["rgb"]) / 255) for c in sorted(B["classes"])]
    for n, (lab, col) in enumerate(items):
        x = 0.01 + (n % 4) * 0.25; y = 0.66 - (n // 4) * 0.36
        lx.add_patch(Rectangle((x, y), 0.03, 0.26, fc=col, ec="k"))
        lx.text(x + 0.035, y + 0.13, lab, va="center", fontsize=8)
    lx.text(0.01, 0.08, "Contours from CB-DEM-10m, 10 ft interval (50 ft index), NAVD 88 US survey feet.  "
            "Land-cover colours as C-002 Table 2.", fontsize=7.5)
    title_block(fig, "C-001", ["SITE CONSTRAINTS", "PLAN"])
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def table(ax, x, y, cols, rows, widths, size=9.5, rh=0.0255, head_fc="#d9d9d9"):
    xs = np.concatenate([[0], np.cumsum(widths)]) + x
    for c, t in enumerate(cols):
        ax.add_patch(Rectangle((xs[c], y - rh), widths[c], rh, fc=head_fc, ec="k", lw=0.8))
        ax.text(xs[c] + 0.004, y - rh / 2, t, va="center", fontsize=size, weight="bold")
    for r, row in enumerate(rows):
        yy = y - rh * (r + 2)
        for c, t in enumerate(row):
            ax.add_patch(Rectangle((xs[c], yy), widths[c], rh, fc="white", ec="k", lw=0.6))
            ax.text(xs[c] + 0.004, yy + rh / 2, t, va="center", fontsize=size)
    return y - rh * (len(rows) + 1)


def sheet2(path):
    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI)
    fig.add_artist(Rectangle((0.005, 0.005), 0.99, 0.99, fill=False, lw=2.5, transform=fig.transFigure))
    ax = fig.add_axes([0.02, 0.02, 0.77, 0.96]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.0, 0.985, "DATA REGISTER, UNIT RATES AND ROUTING CONSTRAINTS", fontsize=15, weight="bold", va="top")
    ax.text(0.0, 0.945, "TABLE 1 - RASTER DATA REGISTER (issued with this drawing)", fontsize=11, weight="bold", va="top")
    y = table(ax, 0.0, 0.93, ["Item", "CB-DEM-10m_heightmap_uint16.png", "CB-LC-20m_landcover.png"], [
        ["Content", "Bare-earth terrain model (LiDAR 2026-03)", "Land-cover classification (field verified 2026-07)"],
        ["Raster size", "360 columns x 280 rows, 1 band", "190 columns x 150 rows, 3 bands"],
        ["Pixel type", "16-bit unsigned integer (DN)", "8-bit RGB, classes per Table 2"],
        ["CRS", "WGS 84 / UTM zone 14N (EPSG:32614)", "WGS 84 / UTM zone 14N (EPSG:32614)"],
        ["UL corner of UL pixel", "E 583 000.00 m   N 3 351 500.00 m", "E 582 900.00 m   N 3 351 620.00 m"],
        ["Pixel size", "10.00 m x 10.00 m (square)", "20.00 m x 20.00 m (square)"],
        ["Row / column order", "Row 1 = north edge, column 1 = west edge", "Row 1 = north edge, column 1 = west edge"],
        ["Value", "Elevation = 1150.00 + 0.01 x DN  (US survey feet, NAVD 88)", "Exact RGB triplet = class (no anti-aliasing)"],
    ], [0.15, 0.40, 0.40], size=9)

    ax.text(0.0, y - 0.012, "TABLE 2 - LAND-COVER CLASSES AND BASE UNIT RATES (REV B, UNCHANGED AT REV C)", fontsize=11, weight="bold", va="top")
    rows = []
    for c in sorted(B["classes"]):
        info = B["classes"][c]
        r, g, b = info["rgb"]
        if info["cost"] is None:
            rate = "PROHIBITED" if info["name"] != "Watercourse" else "PROHIBITED (Note 3)"
        elif info["name"] == "Woodland":
            rate = "940   (Rev B;  Rev A value 690 withdrawn)"
        else:
            rate = f"{info['cost']:,.0f}"
        rows.append([c, info["name"], f"({r}, {g}, {b})", rate])
    rows.append(["-", "Culvert at approved crossing window", "-", f"{B['culvert_cost']:,.0f}  (Note 3)"])
    y = table(ax, 0.0, y - 0.027, ["Code", "Class", "RGB", "Base unit rate  c  (USD per metre of road)"], rows,
              [0.06, 0.29, 0.13, 0.47], size=9)

    ax.text(0.0, y - 0.012, "TABLE 3 - CONTROL POINTS (WGS 84 geographic, decimal degrees)", fontsize=11, weight="bold", va="top")
    lab = dict(START="T1  Tie-in to CR-114 (route start)", END="G1  Quarry plant gate (route end)",
               X1="X-1  Approved crossing window centre", X2="X-2  Approved crossing window centre",
               HERITAGE="HS-1  Heritage site (recorded point)")
    rows = [[lab[k], f"{v[0]:.7f}", f"{v[1]:.7f}"] for k, v in B["points_latlon"].items()]
    y = table(ax, 0.0, y - 0.027, ["Point", "Latitude", "Longitude"], rows, [0.45, 0.2, 0.2], size=9)

    notes = [
        "NOTES",
        "1. The two rasters in Table 1 govern. Sheet C-001 is a presentation plot of them and is not to be scaled or digitised.",
        "2. Route start and end are the DEM cells containing control points T1 and G1.",
        "3. Watercourse cells may be traversed only at approved crossing windows X-1 and X-2: a watercourse cell is passable where",
        "    its DEM cell centre lies within 30.0 m of a window centre, and is then costed at the culvert rate. All other watercourse cells are prohibited.",
        "4. Wetland W-1: wetland cells are prohibited and no part of the road may lie within 30.0 m of the mapped wetland boundary.",
        "5. Heritage site HS-1: exclusion zone of radius 150.0 m about the recorded point (Texas Historical Commission consultation, 2026).",
        "6. Maximum grade 10.0 percent for loaded 40 t haul trucks, in either direction of travel.",
        "7. The indicative route on C-001 is from a 2025 desk study that pre-dates the LiDAR, the land-cover survey and Notes 3 to 5.",
        "8. Haul truck operating criteria and the road typical section are on Sheet C-003. Where C-003 and these notes differ, C-003 governs.",
    ]
    yy = y - 0.02
    for i, t in enumerate(notes):
        ax.text(0.0, yy, t, fontsize=9.5 if i else 11, weight="bold" if i == 0 else "normal", va="top")
        yy -= 0.023
    title_block(fig, "C-002", ["DATA REGISTER,", "UNIT RATES AND", "CONSTRAINTS"])
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def dim(ax, x0, x1, y, txt, size=9):
    ax.annotate("", (x0, y), (x1, y), arrowprops=dict(arrowstyle="<|-|>", lw=0.8, color="k", shrinkA=0, shrinkB=0))
    ax.text((x0 + x1) / 2, y + 0.12, txt, ha="center", va="bottom", fontsize=size)


def sheet3(path):
    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI)
    fig.add_artist(Rectangle((0.005, 0.005), 0.99, 0.99, fill=False, lw=2.5, transform=fig.transFigure))
    ax0 = fig.add_axes([0.02, 0.02, 0.77, 0.96]); ax0.axis("off"); ax0.set_xlim(0, 1); ax0.set_ylim(0, 1)
    ax0.text(0.0, 0.985, "HAUL ROAD TYPICAL SECTION AND HAUL TRUCK OPERATING CRITERIA", fontsize=15, weight="bold", va="top")
    ax0.text(0.0, 0.945, "TYPICAL SECTION A-A  (TANGENT, CUT/FILL NOT SHOWN)   SCALE 1:100 AT A3 - DO NOT SCALE FROM THIS PLOT",
             fontsize=11, weight="bold", va="top")

    ax = fig.add_axes([0.04, 0.50, 0.73, 0.40]); ax.axis("off")
    ax.set_xlim(-12, 12); ax.set_ylim(-3.2, 4.2)
    # ground and formation
    ax.fill_between([-12, 12], -3.2, -1.2, color="#d8c7a8", zorder=0)
    ax.plot([-12, -10, 10, 12], [-1.2, -1.2, -1.2, -1.2], color="#6b5a3a", lw=1)
    xs = [-7, -6, -5, 5, 6, 7]
    ax.fill([-7, -7, -6.4, -6, -6], [-1.2, -0.2, 0.25, 0.25, -1.2], color="#9c8f7a", ec="k", lw=0.8)   # berm
    ax.fill([7, 7, 6.4, 6, 6], [-1.2, -0.2, 0.25, 0.25, -1.2], color="#9c8f7a", ec="k", lw=0.8)
    ax.fill([-6, -5, -5, -6], [-1.2, -1.2, -0.05, -0.1], color="#c9bda3", ec="k", lw=0.8)                 # shoulder
    ax.fill([6, 5, 5, 6], [-1.2, -1.2, -0.05, -0.1], color="#c9bda3", ec="k", lw=0.8)
    ax.fill([-5, 0, 5, 5, -5], [-0.05, 0.0, -0.05, -1.2, -1.2], color="#8a8a8a", ec="k", lw=0.8)          # running surface
    ax.plot([0, 0], [-1.6, 3.9], color="k", lw=0.8, ls=(0, (8, 3, 2, 3)))
    ax.text(0, 3.95, "CL  (route centreline =\nDEM cell centres, C-002 Note 2)", ha="center", va="bottom", fontsize=9)
    for x in (-7, -6, -5, 5, 6, 7):
        ax.plot([x, x], [0.35, 2.55], color="k", lw=0.5)
    y = 1.1
    dim(ax, -7, -6, y, "1.00"); dim(ax, -6, -5, y, "1.00"); dim(ax, -5, 5, y, "10.00")
    dim(ax, 5, 6, y, "1.00"); dim(ax, 6, 7, y, "1.00")
    ax.text(-6.5, 2.0, "SAFETY\nBERM", ha="center", fontsize=8.5, weight="bold")
    ax.text(-5.5, 2.0, "SHLDR", ha="center", fontsize=8.5, weight="bold")
    ax.text(0, 2.0, "RUNNING SURFACE (2 LANES, 150 mm CRUSHED LIMESTONE)", ha="center", fontsize=8.5, weight="bold")
    ax.text(5.5, 2.0, "SHLDR", ha="center", fontsize=8.5, weight="bold")
    ax.text(6.5, 2.0, "SAFETY\nBERM", ha="center", fontsize=8.5, weight="bold")
    ax.text(-7.1, -0.2, "FORMATION\nEDGE", ha="right", va="center", fontsize=8.5, weight="bold")
    ax.text(7.1, -0.2, "FORMATION\nEDGE", ha="left", va="center", fontsize=8.5, weight="bold")
    ax.annotate("CLEARING LIMIT 3.0 m BEYOND FORMATION EDGE\n(CLEARING QUANTITIES ONLY - SEE NOTE C3)",
                (-10, -1.2), (-11.8, -2.9), fontsize=8, arrowprops=dict(arrowstyle="->"))
    ax.plot([-10, -10], [-1.2, -0.6], color="#2a6a2a", lw=1.2, ls="--")
    ax.plot([10, 10], [-1.2, -0.6], color="#2a6a2a", lw=1.2, ls="--")
    ax.text(2.2, -0.55, "3.0 % CROSSFALL", fontsize=8)
    ax.text(6.5, 0.6, "1.2 m", fontsize=7.5, ha="center")
    ax.text(8.2, -2.7, "DIMENSIONS IN METRES", fontsize=8, style="italic")

    y = 0.46
    ax0.text(0.0, y, "TABLE 4 - HAUL TRUCK OPERATING CRITERIA (40 t ARTICULATED HAUL TRUCK, LOADED)", fontsize=11, weight="bold", va="top")
    y = table(ax0, 0.0, y - 0.017, ["Ref", "Criterion", "Value", "Application to the route study"], [
        ["T1", "Maximum grade, either direction", "10.0 %", "Every move; as C-002 Note 6"],
        ["T2", "Sustained steep grade", "> 8.0 %", "A move steeper than 8.0 % is a steep move"],
        ["T3", "Maximum continuous run of steep moves", "60.0 m", "Horizontal length; any move at 8.0 % or flatter ends the run"],
        ["T4", "Maximum change of direction between", "45 deg", "Measured between consecutive grid moves; the first move"],
        ["", "   consecutive moves", "", "   from the start cell is unrestricted"],
        ["T5", "Design speed (loaded)", "40 km/h", "Information only"],
        ["T6", "Rated payload / gross vehicle mass", "40 t / 72 t", "Information only"],
    ], [0.04, 0.29, 0.09, 0.53], size=9)
    notes = [
        "NOTES",
        "C1. 'The road' in C-002 Notes 4 and 5 means the full formation shown in Section A-A. Wetland setback and heritage exclusion are",
        "      measured to the formation edge on either side of the centreline, along every straight move between cell centres.",
        "C2. The crossing-window test of C-002 Note 3 is applied to centreline cell centres only.",
        "C3. The clearing limit and batters are for quantities only and are not routing constraints.",
        "C4. Criteria T1 to T4 apply together. Unit rates (C-002 Table 2) and the grade factor are unchanged by this sheet.",
    ]
    yy = y - 0.025
    for i, t in enumerate(notes):
        ax0.text(0.0, yy, t, fontsize=9.5 if i else 11, weight="bold" if i == 0 else "normal", va="top")
        yy -= 0.022
    title_block(fig, "C-003", ["TYPICAL SECTION", "AND HAUL TRUCK", "CRITERIA"])
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def main():
    w = ROOT / "work"
    p1, p2, p3 = w / "C-001.png", w / "C-002.png", w / "C-003.png"
    sheet1(p1); sheet2(p2); sheet3(p3)
    for old in (ROOT / "inputs").glob("CB-HR-*.pdf"):
        old.unlink()
    out = ROOT / "inputs" / "CB-HR-C001-C003_RevC.pdf"
    c = canvas.Canvas(str(out), pagesize=landscape((11 * 72, 17 * 72)))
    for p in (p1, p2, p3):
        c.drawImage(str(p), 0, 0, width=17 * 72, height=11 * 72)
        c.showPage()
    c.save()
    print("wrote", out)


if __name__ == "__main__":
    main()
