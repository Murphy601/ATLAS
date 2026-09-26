# Project Neutron: GIS, least-cost path road alignment

**Task:** Cedar Bluff Quarry haul road, least-cost corridor from image-only survey deliverables.

## 1. Prompt (paste as-is)

> I'm the civil lead on the new haul road for Cedar Bluff Aggregates. Before we start geometric design, I need the least-cost corridor from the tie-in on County Road CR-114 (point T1) to the quarry plant gate (G1). You'll find everything on drawing CB-HR-C001-C002_RevB.pdf (C-001 site constraints plan and C-002 data register, unit rates and constraints) and in the two rasters it registers: CB-DEM-10m_heightmap_uint16.png (terrain) and CB-LC-20m_landcover.png (land cover). The rasters and the C-002 tables and notes govern; C-001 is only a picture of them. Work in the environment's GIS stack (GDAL/PROJ, through QGIS or Python), and georeference the data before routing.
>
> Our cost model for route studies is as follows. Route on the 10 m DEM grid, moving from a cell centre to any of its 8 neighbouring cell centres. A move costs its horizontal length, times the average of the two cells' base unit rates from C-002, times a grade factor f(g). Here g is the absolute grade of that move in percent: the elevation difference between the two cell centres divided by the horizontal length of the move. f = 1.00 for g ≤ 3; f = 1.00 + 0.05(g − 3) for 3 < g ≤ 6; f = 1.15 + 0.12(g − 6) for 6 < g ≤ 10. Any move steeper than the C-002 grade limit is not allowed. Apply every constraint on C-002. The route is the chain of moves with the lowest total cost from the start cell to the end cell, and the route cost is the sum of its move costs in USD.
>
> Send me three files, with all coordinates in EPSG:32614 metres:
>
> 1. **CB_HaulRoad_Centreline.gpkg**: a GeoPackage with one layer named `centreline`. It holds a single LineString running from start to end, with a vertex at every route cell centre in travel order.
> 2. **CB_HaulRoad_Vertices.csv**: one row per vertex in travel order, with columns `seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, cum_cost_usd`. Give elevations in metres. Chainage is horizontal and starts at 0. Grade is signed, positive uphill in the direction of travel, and blank on the last row. `cum_cost_usd` is the accumulated route cost at each vertex.
> 3. **CB_HaulRoad_RouteReport.pdf**: the total route cost to the dollar; the horizontal length to 0.1 m; the maximum grade; the route length in each land-cover class; the start and end cell centres; which approved crossing window the route uses, and whether a compliant route through the other window exists; a short explanation of what controls the alignment; the unit rates and constraint values you applied; a plan of the route over the constraints; and a long section.
>
> This is for internal option selection, not for construction. Don't do geometric design (curves, sight distance) or earthworks.

## 2. Input assets (upload all three from `inputs/`)

| File | Type | What it is |
|---|---|---|
| `CB-HR-C001-C002_RevB.pdf` | PDF, 2 pages, each one embedded 3400×2200 raster image; no text layer | C-001 site constraints plan and C-002 data register, rate table, control points and notes |
| `CB-DEM-10m_heightmap_uint16.png` | PNG, 16-bit greyscale, 360×280 | Terrain as a heightmap; DN maps to elevation in US survey feet |
| `CB-LC-20m_landcover.png` | PNG, 8-bit RGB, 190×150 | Land cover as exact RGB classes, on its own 20 m grid and origin |

All three assets are original. The terrain, land cover, place names and drawings were generated from scratch by `src/` (analytic surfaces; no third-party data). The location is a real UTM zone, but the site is fictional.

The traps live in the assets; the prompt announces none of them:

1. **Vertical units** (domain outlier). The DEM value is `Elevation = 1150.00 + 0.01 × DN` in **US survey feet**, while the grid is in metres. If feet are not converted, grades come out 3.28 times too large and no route under 10% exists.
2. **Two grids** (data reconciliation). The land-cover raster has a different origin (E 582 900, N 3 351 620) and a 20 m pixel. Assuming it shares the DEM origin misplaces every class by 100 m east and 120 m north.
3. **Pixel-is-area georeferencing.** Coordinates are given for the upper-left *corner* of the upper-left pixel, so cell centres fall at …5 m. The start cell centre is E 583 155, N 3 349 105; the end cell centre is E 586 315, N 3 350 995.
4. **Control points in WGS 84 lat/long** (Table 3). T1, G1, X-1, X-2 and HS-1 must be projected to EPSG:32614 with PROJ.
5. **Wetland setback** (implicit variable, Note 4). Wetland W-1 sits one 20 m land-cover column west of Cedar Branch at X-1. Without the 30 m setback that gap is open, and the cheapest route (1.99 M USD) follows the existing farm track to X-1. With the setback, X-1 cannot be reached at all.
6. **Heritage exclusion** (Note 5). HS-1 is a point with a 150 m radius, and its symbol on C-001 is not to scale. It sits on the lowest saddle of Cedar Bluff Ridge. Ignoring it gives a 2.11 M USD route through the saddle.
7. **Revision B rate** (source-of-truth tension). The woodland rate is 940 USD/m; the Rev A value of 690 is shown as withdrawn. Using 690 gives 2.19 M USD, which is 6.3% low.
8. **Grade is per move, not a slope raster.** A 20%+ hillside can be crossed on a diagonal move at under 10%. An isotropic terrain-slope mask gives a different route (2.59 M USD).
9. **Superseded indicative route** on C-001, drawn through X-1 and HS-1 and labelled superseded. Following it breaks Notes 4 and 5.

## 3. Golden deliverable (upload all three from `golden/`)

- `CB_HaulRoad_Centreline.gpkg`: layer `centreline`, one LineString with 419 vertices, EPSG:32614.
- `CB_HaulRoad_Vertices.csv`: 419 rows with the columns exactly as specified.
- `CB_HaulRoad_RouteReport.pdf`: result table, method, rates applied, plan, long section, land-cover and grade breakdowns, option checks and compliance.

Headline values:

- **Route cost:** 2,339,944.02 USD.
- **Horizontal length:** 4,921.44 m (239 orthogonal and 179 diagonal moves).
- **Start and end cells:** start E 583 155, N 3 349 105 at z 374.54 m; end E 586 315, N 3 350 995 at z 462.35 m.
- **Crossing:** approved window **X-2**, on two watercourse cells at N 3 349 605.
- **X-1:** no compliant route exists.
- **Route shape:** the route climbs round the north end of Cedar Bluff Ridge; its northernmost vertex is E 585 385, N 3 351 355. It passes no closer than 424 m to HS-1.
- **Maximum grade:** 9.48% (steepest downhill −8.14%).
- **Length by land-cover class:** grassland 3,343.4 m, existing track 876.1 m, woodland 467.0 m, cropland 215.0 m, watercourse (culvert) 20.0 m.

How robust the answer is (checked in `src/`):

- An international-foot conversion, three neighbour tie-break orders, blocking diagonal corner-cutting, and centre-in-circle versus cell-overlaps-circle exclusions all give the same cost to within 1 USD and the same length. Tied paths stay within 10 m of the golden path.
- Alternative class-length attribution rules (half to each cell, all to the start cell, or all to the end cell) change the land-cover lengths by 5 m at most.
- Every DEM cell centre is at least 0.54 m from the HS-1 boundary and at least 1.06 m from each crossing-window boundary, so 7-decimal lat/long rounding cannot flip a cell.
- Land-cover pixel edges coincide with DEM cell edges, so every resampling method gives the same classes.

## 4. Key components

1. The route cost is **2,339,944 USD** over **4,921.4 m**. It comes only from applying all C-002 constraints, the Rev B woodland rate of 940 USD/m, the stated per-move grade factor, and the 10% limit on every move.
2. DEM values are feet: `1150.00 + 0.01 × DN` US survey feet, converted to metres before any grade is computed. The first-vertex elevation is 374.54 m.
3. Both rasters are georeferenced from their own C-002 Table 1 entries, using pixel-is-area corners. The land-cover grid is offset by 100 m east and 120 m north from the DEM grid, with 20 m pixels. Route vertices sit at cell centres ending in 5.
4. T1, G1, X-1, X-2 and HS-1 are converted from WGS 84 lat/long to EPSG:32614. The start and end are the DEM cells containing T1 and G1: E 583 155, N 3 349 105 and E 586 315, N 3 350 995.
5. Crossing window **X-1 is infeasible**, because the 30 m wetland setback closes the only strip between W-1 and Cedar Branch. The route crosses at **X-2**.
6. The Cedar Bluff Ridge saddle lies inside the 150 m HS-1 exclusion, so the route goes round the north end of the ridge instead: through about E 585 125, N 3 350 405 and E 585 695, N 3 351 315.
7. Grade is computed per move, from the two cell-centre elevations over the move length, and no move exceeds 10%. The maximum is 9.48%.
8. Length by land-cover class: woodland 467.0 m, existing track 876.1 m, grassland 3,343.4 m.
9. The three files use the exact names, layer name, CSV columns and EPSG:32614. The report is internal and not for construction, with no curve, sight-distance or earthworks design.

## 5. Rubric (32 items)

Weights: +9 ×4, +7 ×4, +5 ×6, +3 ×7, +1 ×7, and 4 penalties (−7, −5, −5, −3). The penalties are 12.5% of the items. The golden deliverable scores 100% (122/122) with `python3 src/grade.py`.

| # | Wt | Type | Criterion |
|---|---|---|---|
| R1 | 9 | implicit | The PDF report states a total route cost of 2,339,944 USD (+/- 0.5 percent, 2,328,244 to 2,351,644 USD). |
| R2 | 7 | implicit | The PDF report states a horizontal route length of 4,921.4 m (+/- 1 percent, 4,872.2 to 4,970.7 m). |
| R3 | 9 | implicit | The PDF report states that no compliant route exists through crossing window X-1. |
| R4 | 5 | implicit | The PDF report attributes the infeasibility of crossing window X-1 to the 30 m wetland setback closing the west-bank approach to X-1. |
| R5 | 9 | implicit | The GeoPackage centreline has a vertex within 30 m of E 584 613.5, N 3 349 580.0 (EPSG:32614), the centre of approved crossing window X-2. |
| R6 | 7 | implicit | The GeoPackage centreline has a vertex within 25 m of E 584 205, N 3 349 705 (EPSG:32614). |
| R7 | 5 | implicit | The GeoPackage centreline has a vertex within 25 m of E 585 125, N 3 350 405 (EPSG:32614). |
| R8 | 7 | implicit | The GeoPackage centreline has a vertex within 25 m of E 585 695, N 3 351 315 (EPSG:32614). |
| R9 | 9 | implicit | Every vertex of the GeoPackage centreline lies more than 150 m from E 585 511.9, N 3 350 201.9 (EPSG:32614). |
| R10 | 3 | implicit | The first vertex of the GeoPackage centreline is at E 583 155.0, N 3 349 105.0 (EPSG:32614, +/- 1 m on each). |
| R11 | 3 | implicit | The last vertex of the GeoPackage centreline is at E 586 315.0, N 3 350 995.0 (EPSG:32614, +/- 1 m on each). |
| R12 | 7 | implicit | The CSV vertex table gives an elev_m of 374.54 m (+/- 0.05 m) on its first row. |
| R14 | 3 | implicit | The PDF report states a maximum route grade of 9.48 percent (+/- 0.10 percentage points). |
| R15 | 3 | explicit | Every pair of consecutive GeoPackage centreline vertices is separated by 10 m in easting, northing or both, with no other separation. |
| R16 | 1 | explicit | The cum_cost_usd value on the last row of the CSV vertex table equals the total route cost stated in the PDF report within 1 USD. |
| R17 | 3 | implicit | The PDF report states a woodland base unit rate of 940 USD per metre. |
| R18 | 5 | implicit | The PDF report states that the saddle (lowest pass) over Cedar Bluff Ridge lies within the 150 m HS-1 heritage exclusion. |
| R19 | 5 | explicit | The GeoPackage centreline layer CRS is EPSG:32614 (WGS 84 / UTM zone 14N). |
| R20 | 3 | explicit | The GeoPackage contains a layer named 'centreline' holding exactly one LineString feature. |
| R21 | 1 | explicit | The response delivers a GeoPackage file named exactly 'CB_HaulRoad_Centreline.gpkg'. |
| R22 | 1 | explicit | The response delivers a CSV file named exactly 'CB_HaulRoad_Vertices.csv'. |
| R23 | 1 | explicit | The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, cum_cost_usd. |
| R24 | 1 | explicit | The response delivers a PDF file named exactly 'CB_HaulRoad_RouteReport.pdf'. |
| R25 | 1 | explicit | The PDF report contains a plan figure showing the route centreline. |
| R26 | 1 | explicit | The PDF report contains a long section plotting elevation against chainage along the route. |
| R28 | 5 | implicit | The PDF report states a route length in woodland of 467.0 m (+/- 3 percent). |
| R29 | 5 | implicit | The PDF report states a route length on the existing gravel track of 876.1 m (+/- 3 percent). |
| R30 | 3 | implicit | The PDF report states a route length in grassland / pasture of 3,343.4 m (+/- 3 percent). |
| N1 | −7 | implicit | The CSV vertex table contains a grade_to_next_pct value whose absolute value exceeds 10.0. |
| N2 | −5 | explicit | The response presents the alignment as approved, issued or released for construction. |
| N3 | −3 | explicit | The PDF report states horizontal curve radii, sight distances or earthworks volumes for the route. |
| N4 | −5 | implicit | The PDF report states two different total cost values for the adopted route. |

The IDs have gaps (no R13 or R27) because two draft items were dropped during calibration. Renumber them if the platform needs consecutive numbers.

How each criterion traces back to the prompt:

- **Cost, length, maximum grade:** R1, R2, R14.
- **Crossing window and the other window:** R3, R4, R5.
- **What controls the alignment:** R18.
- **Rates applied:** R17.
- **Land-cover lengths:** R28 to R30.
- **Start and end cells:** R10, R11.
- **Vertex at every route cell centre:** R15.
- **Elevation in metres:** R12.
- **Minimum-cost route under the constraints:** R6 to R9, and N1.
- **Files and format:** R16, R19 to R26.
- **Scope limits:** N2, N3.
- **Internal consistency:** N4.

## 6. Calibration against simulated failures

`python3 src/grade.py sim` writes complete GeoPackage and CSV deliverables for each failure mode, then scores them against the rubric. Report-text items are set the way that failure would state them.

| Simulated failure | Cost (USD) | Score |
|---|---|---|
| A. Wetland setback missed, so the route uses X-1 | 1,989,674 | 35.2% |
| B. HS-1 exclusion missed, so the route takes the saddle | 2,105,916 | 56.6% |
| C. Only the Rev A woodland rate used | 2,191,398 | 90.2% |
| D. Isotropic slope mask used instead of per-move grade | 2,592,445 | 68.0% |
| E. Setback and Rev A rate both missed | 1,820,331 | 32.8% |
| F. Setback, HS-1 and Rev A rate all missed (HS-1 no longer matters once X-1 is open) | 1,820,331 | 32.8% |
| G. HS-1 and Rev A rate both missed | 1,961,749 | 54.1% |
| H. Feet not converted | no feasible route | not simulated (no compliant route to deliver) |

A single miss of the setback or the unit conversion lands at or below 40%. A single miss of HS-1, the grade model or the rate revision does not. The ≤40% average therefore relies on rollouts missing the setback or feet, or stacking two or more traps. That is plausible here, because every constraint value can only be read from an image-only PDF.

If a rollout clears too many traps, strengthen the task with these levers, which fit the existing assets:

- Make the X-1 crossing cheaper, so the setback trap costs even more.
- Add a second revision cloud, for example on the culvert rate.
- Move HS-1 so it also blocks an X-2 approach.

## 7. Judging the rollouts

For each rollout:

1. Open its GeoPackage in QGIS, or with `ogrinfo`, and overlay the golden centreline.
2. Check which crossing it used and whether it passes within 150 m of HS-1.
3. Read the CSV's first `elev_m`: about 1228.8 means feet were not converted, and 374.5 is correct.
4. Look for the woodland rate in its report.

Write up each failure with concrete values, the way the Building8 example does.

## 8. Reproducing

```bash
cd src
python3 make_rasters.py     # DEM + land-cover PNGs, published brief values
python3 make_sheets.py      # C-001 / C-002 image-only PDF
python3 solve.py            # golden + failure-variant solves
python3 make_golden.py      # golden GPKG / CSV / PDF
python3 grade.py            # golden vs rubric
python3 grade.py sim        # simulated failure calibration
```

Dependencies: Python 3.12, numpy, pillow, pyproj, shapely, geopandas, pyogrio, matplotlib, reportlab, pypdf, and GDAL 3.8 for `ogrinfo` checks.
