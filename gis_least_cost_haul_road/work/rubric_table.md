| # | Wt | Criterion |
|---|---|---|
| R1 | +9 | The PDF report states a total route cost (construction plus loaded haulage) of 3,110,904 USD (+/- 0.01 percent, 3,110,593 to 3,111,215 USD). |
| R2 | +9 | The PDF report states a construction cost component of 2,926,731 USD (+/- 0.01 percent, 2,926,438 to 2,927,024 USD). |
| R3 | +9 | The PDF report states a loaded haulage cost component of 184,173 USD (+/- 0.05 percent, 184,081 to 184,265 USD). |
| R4 | +9 | The PDF report states a horizontal route length of 5,974.5 m (+/- 1.0 m). |
| R5 | +9 | The CSV vertex table has exactly 492 data rows. |
| R6 | +7 | The GeoPackage centreline has exactly 33 interior vertices at which the direction of the line changes. |
| R7 | +9 | The last vertex of the GeoPackage centreline is at E 586 455.0, N 3 350 105.0 (EPSG:32614, +/- 1 m on each). |
| P1 | +7 | The GeoPackage centreline has a vertex within 1 m of E 583 625, N 3 349 445 (EPSG:32614). |
| P2 | +7 | The GeoPackage centreline has a vertex within 1 m of E 583 705, N 3 349 445 (EPSG:32614). |
| P3 | +5 | The GeoPackage centreline has a vertex within 1 m of E 585 775, N 3 351 075 (EPSG:32614). |
| P4 | +5 | The GeoPackage centreline has a vertex within 1 m of E 585 855, N 3 351 145 (EPSG:32614). |
| P5 | +5 | The GeoPackage centreline has a vertex within 1 m of E 585 965, N 3 351 295 (EPSG:32614). |
| P6 | +5 | The GeoPackage centreline has a vertex within 1 m of E 585 965, N 3 351 375 (EPSG:32614). |
| P7 | +7 | The GeoPackage centreline has a vertex within 1 m of E 586 295, N 3 350 715 (EPSG:32614). |
| P8 | +7 | The GeoPackage centreline has a vertex within 1 m of E 586 375, N 3 350 635 (EPSG:32614). |
| P9 | +7 | The GeoPackage centreline has a vertex within 1 m of E 586 455, N 3 350 555 (EPSG:32614). |
| P10 | +7 | The GeoPackage centreline has a vertex within 1 m of E 586 545, N 3 350 465 (EPSG:32614). |
| P11 | +5 | The GeoPackage centreline has a vertex within 1 m of E 586 555, N 3 350 385 (EPSG:32614). |
| P12 | +5 | The GeoPackage centreline has a vertex within 1 m of E 586 585, N 3 350 245 (EPSG:32614). |
| P13 | +5 | The GeoPackage centreline has a vertex within 1 m of E 586 515, N 3 350 165 (EPSG:32614). |
| R20 | +9 | The cum_cost_usd value on the last row of the CSV vertex table is 3,110,904 USD (+/- 0.01 percent). |
| R21 | +7 | On the first CSV row whose landcover_class is Watercourse, cum_cost_usd is 888,233 USD (+/- 0.05 percent). |
| R22 | +7 | On the first CSV row with the largest northing_m, cum_cost_usd is 2,284,982 USD (+/- 0.05 percent). |
| R23 | +5 | On the first CSV row with the largest northing_m, chainage_m is 4,295.3 m (+/- 1.0 m). |
| R24 | +7 | Exactly 54 rows of the CSV vertex table have grade_to_next_pct below -1.000 (moves climbed by loaded trucks above the 4.0 percent effective top-gear limit). |
| R12 | +5 | The PDF report states a route length in woodland of 533.9 m (+/- 0.2 percent). |
| R13 | +7 | The PDF report states a route length in grassland / pasture of 4,215.1 m (+/- 0.2 percent). |
| R14 | +5 | The PDF report states a route length on existing gravel track of 573.3 m (+/- 0.2 percent). |
| R15 | +5 | The PDF report states a route length in cultivated cropland of 632.3 m (+/- 0.2 percent). |
| R16 | +1 | The PDF report states a maximum route grade of 9.98 percent (+/- 0.02 percentage points). |
| R17 | +1 | The PDF report states that the route climbs the escarpment by the northern slump, reaching N 3 351 475 (+/- 25 m) before returning south along the plateau to G1. |
| R18 | +1 | The GeoPackage centreline has a vertex within 30 m of E 584 613.5, N 3 349 580.0 (EPSG:32614), the centre of approved crossing window X-2. |
| C1 | +9 | No row of the CSV vertex table has grade_to_next_pct below -6.00 (no move climbed by loaded trucks, travelling G1 to T1, is steeper than 6.0 percent). |
| C2 | +9 | For every two consecutive moves in the CSV vertex table, the absolute difference of grade_to_next_pct is at most (L1 + L2) / 2 / 1.4 (+ 0.002), where L1 and L2 are the two moves' horizontal lengths in m from chainage_m. |
| C3 | +9 | Along the GeoPackage centreline, successive direction-change vertices are at least 37.28 m apart, and the first and last direction-change vertices are at least 18.64 m from the first and last vertex. |
| C4 | +1 | No two consecutive segments of the GeoPackage centreline differ in direction by more than 45 degrees. |
| C5 | +1 | In the CSV vertex table, no unbroken sequence of rows with \|grade_to_next_pct\| greater than 8.0 spans more than 60.0 m of chainage (span = chainage of the row after the sequence minus chainage of its first row). |
| C6 | +1 | No point of the GeoPackage centreline lies within 37.0 m of any pixel of CB-LC-20m_landcover.png coloured RGB (150, 200, 210), with the raster placed at UL corner E 582 900, N 3 351 620, 20 m pixels. |
| C7 | +1 | No point of the GeoPackage centreline lies within 157.0 m of E 586 011.9, N 3 350 201.9 (EPSG:32614). |
| C8 | +1 | The first vertex of the GeoPackage centreline is at E 583 155.0, N 3 349 105.0 (EPSG:32614, +/- 1 m). |
| C9 | +1 | The CSV vertex table gives an elev_m of 374.54 m (+/- 0.05 m) on its first row. |
| S1 | +1 | The PDF report states that no compliant route exists through crossing window X-1. |
| S2 | +1 | The PDF report attributes the infeasibility of X-1 to the formation width: a centreline clearing the 30 m wetland setback still leaves the formation edge within 30 m of wetland W-1. |
| S3 | +3 | The PDF report states that loaded trucks travel from G1 to T1 and that moves climbed loaded are limited to a 6.0 percent grade (9.0 percent effective grade minus 3.0 percent rolling resistance). |
| S4 | +5 | The PDF report states that the 45 m minimum radius requires at least 37.28 m (+/- 0.05 m) between successive deflection vertices and at least 18.64 m (+/- 0.05 m) between the start or end and the nearest deflection vertex. |
| S5 | +5 | The PDF report states that the allowable grade change between consecutive moves depends on the two move lengths, (L1 + L2) / (2 x 1.4), e.g. 7.14 percent between two orthogonal moves and 10.10 percent between two diagonal moves. |
| S6 | +5 | The PDF report states that the route minimises construction cost plus loaded haulage of 8,000 USD per metre of rise climbed by loaded trucks, charged only on moves whose loaded grade exceeds 1.0 percent (4.0 percent effective grade minus 3.0 percent rolling resistance), with no credit for falls. |
| S7 | +3 | The PDF report states that G1 was taken from C-004 Table 6 as TxDOT surface coordinates, divided by the surface adjustment factor 1.00012 to NAD83 / Texas Central grid in US survey feet (EPSG:2277), and transformed to EPSG:32614. |
| F1 | +1 | The cum_cost_usd value on the last row of the CSV vertex table equals the total route cost stated in the PDF report (construction plus haulage) within 1 USD. |
| F2 | +1 | Every pair of consecutive GeoPackage centreline vertices is separated by 10 m in easting, northing or both, with no other separation. |
| F3 | +1 | The GeoPackage centreline layer CRS is EPSG:32614 and the layer 'centreline' holds exactly one LineString feature. |
| F4 | +1 | The response delivers files named exactly 'CB_HaulRoad_Centreline.gpkg', 'CB_HaulRoad_Vertices.csv' and 'CB_HaulRoad_RouteReport.pdf'. |
| F5 | +1 | The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, cum_cost_usd. |
| F6 | +1 | The PDF report contains a plan figure showing the route centreline and a long section plotting elevation against chainage. |
| N1 | -7 | The CSV vertex table contains a grade_to_next_pct value whose absolute value exceeds 10.0. |
| N2 | -5 | The response presents the alignment as approved, issued or released for construction. |
| N3 | -5 | The PDF report states two different total cost values for the adopted route. |
| N4 | -3 | The PDF report states earthworks volumes for the route. |
