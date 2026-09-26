"""Write the two raster input assets and the published brief values."""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer

import sitedef as S

ROOT = Path(__file__).resolve().parent.parent
INP = ROOT / "inputs"
WORK = ROOT / "work"
DEM_FILE = "CB-DEM-10m_heightmap_uint16.png"
LC_FILE = "CB-LC-20m_landcover.png"


def main():
    INP.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    dn = S.dem_dn()
    Image.fromarray(dn).save(INP / DEM_FILE)
    lc = S.landcover_codes()
    rgb = np.zeros(lc.shape + (3,), np.uint8)
    for c, (_, col, _) in S.CLASSES.items():
        rgb[lc == c] = col
    Image.fromarray(rgb, "RGB").save(INP / LC_FILE)

    to_ll = Transformer.from_crs(S.EPSG, 4326, always_xy=True)
    pts = {}
    for k, (e, n) in S.PTS_UTM.items():
        lon, lat = to_ll.transform(e, n)
        pts[k] = [round(lat, 7), round(lon, 7)]
    brief = dict(
        epsg=S.EPSG, dem_file=DEM_FILE, lc_file=LC_FILE,
        dem_ul_e=S.DEM_UL_E, dem_ul_n=S.DEM_UL_N, dem_cell=S.DEM_CELL,
        lc_ul_e=S.LC_UL_E, lc_ul_n=S.LC_UL_N, lc_cell=S.LC_CELL,
        dn_base_ft=S.DN_BASE_FT, dn_step_ft=S.DN_STEP_FT,
        classes={str(c): dict(name=n, rgb=list(col), cost=cost) for c, (n, col, cost) in S.CLASSES.items()},
        culvert_cost=S.CULVERT_COST, crossing_radius=S.CROSSING_RADIUS,
        wetland_setback=S.WETLAND_SETBACK, heritage_radius=S.HERITAGE_RADIUS,
        max_grade=S.MAX_GRADE, formation_width=S.FORMATION_WIDTH, steep_grade=S.STEEP_GRADE,
        steep_run_max=S.STEEP_RUN_MAX, max_deflection_deg=S.MAX_DEFLECTION_DEG, points_latlon=pts,
    )
    (WORK / "brief_values.json").write_text(json.dumps(brief, indent=1))
    print(json.dumps(pts, indent=1))
    z = S.terrain_m(0, 0)
    print("DN range", dn.min(), dn.max())


if __name__ == "__main__":
    main()
