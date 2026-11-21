# NYC Charter Schools Map (2025–26)

An interactive map of every New York City charter school in the official NYSED 2025–2026 charter school directory. Each school is placed using state location data matched by its state school ID.

**Live map:** https://YOUR-USERNAME.github.io/nyc-charter-schools-map/

## What the map does

- Shows one marker per charter school, colored by borough
- Lets you turn boroughs on and off, with a count for each
- Lets you search by school name, network, ZIP code or district
- Opens a popup for each school with its address, district, authorizer, year opened and SED code, plus how its location was matched
- Shows how reliable each location is: solid markers were matched by state school ID, and dashed outlines were matched by exact name and should be reviewed
- Lists schools that couldn't be reliably located under "Not on map" instead of placing them at a guessed location

## Data sources

| Role | Source | Key fields |
|---|---|---|
| **Which schools** (the authoritative list) | NYSED *2025–2026 NYS Charter School Directory*, as of 09/02/2025 (`data/source/`) | SED Code, name, district, county, region, authorizer, year opened |
| **Where (primary)** | NYS ITS Geospatial Services *Charter K-12* layer, built from NYS Education Department input ([service](https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Schools/FeatureServer/4)) | `SED_CODE`, street address, point location |
| **Where (fallback)** | NCES EDGE *Public School Locations 2024–25* ([service](https://nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0)) | name, street address, latitude/longitude |

The directory has **370** statewide records. **299** of them have Region = "New York City": Bronx 106, Brooklyn (Kings) 99, Manhattan (New York) 54, Queens 32 and Staten Island (Richmond) 8. The directory has no addresses or coordinates, which is why the location sources are needed.

## Method

`scripts/build_data.py` uses only the Python standard library. It:

1. **Filters** the directory to the 299 NYC records (`Region == "New York City"`).
2. **Downloads** both location sources.
3. **Matches** each school using the most reliable method that works:
   1. **SED code, exact match** to the state layer. This is the same 12-digit ID in both datasets, so it's the most reliable match.
   2. **Exact name and same county** in the state layer, after light cleanup (case, punctuation, "The"). Marked *review*.
   3. **Exact name and same borough** in NCES 2024–25. Marked *review*.
   - A match is used only if exactly one record matches. Ties are rejected, not guessed.
   - Every point must fall inside an NYC bounding box, or it's rejected.
4. **Writes** these files:
   - `data/nyc_charter_schools.geojson`: the mapped schools (the map reads this file)
   - `data/unmatched_schools.csv` and `.json`: schools that weren't mapped, and why
   - `data/match_report.md`: counts by match method and by borough

**Principle: no invented locations.** If a school can't be matched reliably, it's listed, not plotted.

## Results

See [`data/match_report.md`](data/match_report.md) for the current counts: how many schools were mapped, how many were matched by each method, and how many were left unmatched.

## Limitations

- **One point per charter, not per campus.** NYSED gives each charter one SED code and one reported address. Charters that run several buildings (common for large networks) show only that one address, so this is a map of charter schools as NYSED lists them, not of every building.
- **Different dates.** The directory is for 2025–26, while the location layers are updated on their own schedules. The newest schools (opened 2025 or 2026) are the most likely to be missing from the location data and to show up as unmatched.
- **Name matches need checking.** Matches marked *review* are exact name matches, not ID matches. NCES truncates names to 60 characters, so long names may not match at all. That's on purpose: a missed match is safer than a wrong one.
- **Geocoding accuracy.** Points are only as accurate as the source agencies' geocoding of each reported address.

## Run it on your computer

```bash
python3 scripts/build_data.py      # downloads sources and builds data/ (about 1 minute)
python3 -m http.server 8000        # then open http://localhost:8000
```

Opening `index.html` by double-clicking won't work, because browsers block a page opened that way from loading the data files. Use the local server above, or GitHub Pages.

## Deploy

Push to GitHub, then go to **Settings → Pages**. Set Source to *Deploy from a branch*, choose `main` and `/ (root)`, and click **Save**. The page is static: just HTML and data files, with no build step and no API keys.

## Next steps

1. **Campus-level locations:** add NYC DOE building data so that networks show every site.
2. **More detail per school:** add enrollment and grades served from NYSED report cards, with filters.
3. **Tools for families:** add "Schools near me" search and a school district boundary layer.
4. **Fresher data:** add a scheduled GitHub Action that rebuilds the data and flags changes in the unmatched list.

## How I built this

*(Edit this in your own words. For example: what you scoped in and out within the one-hour limit, how you used AI tools, and how you checked the output.)*
