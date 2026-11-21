"""Build the map data for NYC charter schools.

What it does, in order:
  1. Reads the official NYSED 2025-26 charter school directory (data/source/).
  2. Keeps only NYC schools (Region == "New York City").
  3. Downloads location data (address + latitude/longitude):
       A. NYSED / NYS ITS "Charter K-12" GIS layer  (has the same SED code)
       B. NCES EDGE "Public School Locations 2024-25" (federal; no SED code)
  4. Matches each school, most reliable method first:
       1) SED code exact match to layer A                 -> "sed_code"
       2) Exact normalized name + same county in layer A  -> "name_state"
       3) Exact normalized name + same borough in layer B -> "name_nces"
     Anything else is left UNMATCHED. No locations are guessed.
  5. Writes:
       data/nyc_charter_schools.geojson   matched schools (used by the map)
       data/unmatched_schools.csv/.json    schools with no reliable location
       data/match_report.md                counts and method breakdown

Run from the project folder:   python3 scripts/build_data.py
Uses only the Python standard library (nothing to install).
"""
import csv
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRECTORY_CSV = ROOT / "data" / "source" / "nys-charter-school-directory-2025-26.csv"
OUT_GEOJSON = ROOT / "data" / "nyc_charter_schools.geojson"
OUT_UNMATCHED = ROOT / "data" / "unmatched_schools.csv"
OUT_REPORT = ROOT / "data" / "match_report.md"

# Source A: NYS ITS Geospatial Services, Charter K-12 layer (input from NYSED).
# Two published endpoints for the same layer; the second is a backup.
STATE_LAYER_URLS = [
    "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Schools/FeatureServer/4/query",
    "https://nysgeohub.ny.gov/arcgis/rest/services/Education/NYS_Schools/MapServer/3/query",
]
# Source B: NCES EDGE Public School Locations 2024-25.
NCES_URL = ("https://nces.ed.gov/opengis/rest/services/K12_School_Locations/"
            "EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0/query")

# Directory "County" -> borough name, and the county FIPS code NCES uses.
COUNTIES = {
    "New York": ("Manhattan", "36061"),
    "Bronx": ("Bronx", "36005"),
    "Kings": ("Brooklyn", "36047"),
    "Queens": ("Queens", "36081"),
    "Richmond": ("Staten Island", "36085"),
}
FIPS_TO_COUNTY = {fips: county for county, (_, fips) in COUNTIES.items()}

# NYC bounding box: a sanity check that a point is really in the city.
NYC_BOX = {"lat": (40.47, 40.93), "lng": (-74.27, -73.68)}


# ---------------------------------------------------------------- helpers
def fetch_json(base_url, params):
    url = base_url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-charter-map/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.load(r)
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def fetch_all(base_url, where, out_fields):
    """Page through an ArcGIS layer and return all features as plain dicts
    with 'lat' and 'lng' added (WGS84)."""
    rows, offset = [], 0
    base = {"where": where, "outFields": out_fields, "returnGeometry": "true",
            "outSR": "4326", "f": "json"}
    while True:
        try:
            data = fetch_json(base_url, {**base, "resultOffset": offset,
                                         "resultRecordCount": 1000})
        except RuntimeError:
            if offset:  # paging broke midway: don't silently return partial data
                raise
            data = fetch_json(base_url, base)  # server without paging support
            data["exceededTransferLimit"] = False
            if len(data.get("features", [])) >= 1000:
                print("  WARNING: server returned 1000+ rows without paging; results may be cut off.")
        feats = data.get("features", [])
        for f in feats:
            a = dict(f.get("attributes", {}))
            g = f.get("geometry") or {}
            a["lng"], a["lat"] = g.get("x"), g.get("y")
            rows.append(a)
        if not feats or not data.get("exceededTransferLimit"):
            return rows
        offset += len(feats)


def norm_name(s):
    """Conservative name normalization for exact matching."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(the\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\bthe\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def in_nyc(lat, lng):
    return (lat is not None and lng is not None
            and NYC_BOX["lat"][0] <= lat <= NYC_BOX["lat"][1]
            and NYC_BOX["lng"][0] <= lng <= NYC_BOX["lng"][1])


def title(s):
    return " ".join(w.capitalize() if w.isupper() else w for w in str(s or "").split())


# ---------------------------------------------------------------- steps
def read_directory():
    with open(DIRECTORY_CSV, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    # The file has a title line or two before the real header row.
    h = next(i for i, r in enumerate(rows) if r and r[0].strip() == "ACTIVE_DATE")
    header = [c.strip() for c in rows[h]]
    out = []
    for r in rows[h + 1:]:
        if not r or not r[0].strip():
            continue
        rec = {header[i]: r[i].strip() for i in range(len(header)) if header[i]}
        out.append(rec)
    return out


def load_state_layer():
    last_err = None
    for url in STATE_LAYER_URLS:
        try:
            rows = fetch_all(url, "1=1", "*")
            if rows:
                print(f"  State layer: {len(rows)} charter records from {url.split('/rest/')[0]}")
                return rows, url
        except Exception as e:  # try the backup endpoint
            last_err = e
            print(f"  State layer endpoint failed ({e}); trying backup...")
    raise SystemExit(f"Could not download the state charter layer: {last_err}")


def load_nces():
    fips = ",".join(f"'{f}'" for f in FIPS_TO_COUNTY)
    try:
        rows = fetch_all(NCES_URL, f"CNTY IN ({fips})",
                         "NCESSCH,NAME,STREET,CITY,ZIP,CNTY,NMCNTY,LAT,LON")
        print(f"  NCES layer: {len(rows)} NYC public school records")
        return rows
    except Exception as e:
        print(f"  NCES layer unavailable ({e}); continuing without it.")
        return []


def main():
    print("1. Reading directory...")
    directory = read_directory()
    nyc = [r for r in directory if r.get("Region") == "New York City"]
    print(f"  {len(directory)} statewide records, {len(nyc)} in NYC")
    bad = [r for r in nyc if r.get("County") not in COUNTIES]
    if bad:
        sys.exit(f"Unexpected county values: {sorted({r['County'] for r in bad})}")

    print("2. Downloading location sources...")
    state_rows, state_url = load_state_layer()
    nces_rows = load_nces()

    # Index the sources
    state_by_code = {}
    for r in state_rows:
        code = str(r.get("SED_CODE") or "").strip()
        if code:
            state_by_code.setdefault(code, []).append(r)
    state_by_name = {}
    for r in state_rows:
        key = (norm_name(r.get("LEGAL_NAME")), str(r.get("COUNTY_DESC") or "").strip().title())
        state_by_name.setdefault(key, []).append(r)
    nces_by_name = {}
    for r in nces_rows:
        county = FIPS_TO_COUNTY.get(str(r.get("CNTY") or "").strip())
        nces_by_name.setdefault((norm_name(r.get("NAME")), county), []).append(r)

    print("3. Matching...")
    features, unmatched, methods = [], [], Counter()
    for s in nyc:
        code, county = s["SED Code"], s["County"]
        borough = COUNTIES[county][0]
        hit, method, note = None, None, ""

        cands = state_by_code.get(code, [])
        if len(cands) == 1:
            hit, method = cands[0], "sed_code"
        elif len(cands) > 1:
            note = f"SED code appears {len(cands)} times in state layer"

        if not hit:
            cands = state_by_name.get((norm_name(s["Charter School Name"]), county), [])
            if len(cands) == 1:
                hit, method = cands[0], "name_state"

        if not hit:
            cands = nces_by_name.get((norm_name(s["Charter School Name"]), county), [])
            if len(cands) == 1:
                hit, method = cands[0], "name_nces"

        if hit and not in_nyc(hit.get("lat"), hit.get("lng")):
            note = f"matched by {method} but point is outside NYC ({hit.get('lat')}, {hit.get('lng')})"
            hit, method = None, None

        if not hit:
            unmatched.append({**s, "Borough": borough,
                              "Reason": note or "No SED-code or exact-name match in location sources"})
            continue

        methods[method] += 1
        if method in ("sed_code", "name_state"):
            addr = ", ".join(x for x in [title(hit.get("PHYSADDRLINE1")), title(hit.get("PHYSADDRLINE2"))] if x)
            city, zipc = title(hit.get("PHYSCITY")), hit.get("PHYSZIPCD5") or ""
            src = "NYSED / NYS ITS Charter K-12 GIS layer"
        else:
            addr, city, zipc = title(hit.get("STREET")), title(hit.get("CITY")), hit.get("ZIP") or ""
            src = "NCES EDGE Public School Locations 2024-25"

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(hit["lng"], 6), round(hit["lat"], 6)]},
            "properties": {
                "name": s["Charter School Name"],
                "sed_code": code,
                "borough": borough,
                "district": s["School District"],
                "authorizer": s["Authorizer"],
                "year_opened": s["Year Opened"],
                "address": addr, "city": city, "zip": str(zipc),
                "match_method": method,
                "location_source": src,
            },
        })

    features.sort(key=lambda f: f["properties"]["name"])
    OUT_GEOJSON.write_text(json.dumps({
        "type": "FeatureCollection",
        "metadata": {
            "generated": date.today().isoformat(),
            "directory": "NYSED 2025-2026 NYS Charter School Directory",
            "nyc_schools_in_directory": len(nyc),
            "matched": len(features),
            "unmatched": len(unmatched),
            "match_methods": dict(methods),
        },
        "features": features,
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    cols = ["Charter School Name", "SED Code", "Borough", "School District",
            "Authorizer", "Year Opened", "Reason"]
    with open(OUT_UNMATCHED, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(unmatched, key=lambda r: r["Charter School Name"]))
    # Same list as JSON so the map page can show it without a CSV parser.
    (ROOT / "data" / "unmatched_schools.json").write_text(json.dumps(
        [{"name": r["Charter School Name"], "sed_code": r["SED Code"], "borough": r["Borough"],
          "year_opened": r["Year Opened"], "reason": r["Reason"]}
         for r in sorted(unmatched, key=lambda r: r["Charter School Name"])],
        indent=1, ensure_ascii=False), encoding="utf-8")

    by_boro = Counter(f["properties"]["borough"] for f in features)
    dir_boro = Counter(COUNTIES[s["County"]][0] for s in nyc)
    lines = [
        "# Match report", "",
        f"Generated {date.today().isoformat()} by `scripts/build_data.py`.", "",
        f"- NYC schools in directory: **{len(nyc)}**",
        f"- Mapped: **{len(features)}**",
        f"- Unmatched (not mapped): **{len(unmatched)}**: see `unmatched_schools.csv`", "",
        "| Match method | Schools | Confidence |", "|---|---|---|",
        f"| SED code → state GIS layer | {methods['sed_code']} | High (exact ID) |",
        f"| Exact name + county → state GIS layer | {methods['name_state']} | Medium, review |",
        f"| Exact name + borough → NCES 2024-25 | {methods['name_nces']} | Medium, review |", "",
        "| Borough | In directory | Mapped |", "|---|---|---|",
        *[f"| {b} | {dir_boro[b]} | {by_boro[b]} |" for b in sorted(dir_boro)], "",
        f"State layer endpoint used: {state_url}",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nDone. Mapped {len(features)} of {len(nyc)} NYC schools; {len(unmatched)} unmatched.")
    for m, n in methods.most_common():
        print(f"  {m}: {n}")
    print(f"Files written to {OUT_GEOJSON.parent}")


if __name__ == "__main__":
    main()
