# Match report

Generated 2026-11-20 by `scripts/build_data.py`.

- NYC schools in directory: **299**
- Mapped: **294**
- Unmatched (not mapped): **5**: see `unmatched_schools.csv`

| Match method | Schools | Confidence |
|---|---|---|
| SED code → state GIS layer | 280 | High (exact ID) |
| Exact name + county → state GIS layer | 7 | Medium, review |
| Exact name + borough → NCES 2024-25 | 7 | Medium, review |

| Borough | In directory | Mapped |
|---|---|---|
| Bronx | 106 | 105 |
| Brooklyn | 99 | 97 |
| Manhattan | 54 | 54 |
| Queens | 32 | 30 |
| Staten Island | 8 | 8 |

State layer endpoint used: https://nysgeohub.ny.gov/arcgis/rest/services/Education/NYS_Schools/MapServer/3/query
