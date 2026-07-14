# Parcel Field Collection App — Build Spec

## Goal
A small internal web app for a field team (2–10 users) to:
1. View parcel polygons on a map, labeled with `display_name` / `uprn`.
2. Tap a parcel to highlight it and assign/edit an owner name.
3. Collect GPS points in the field (mobile browser, iOS/Android, location enabled).

No authentication. No basemap tile dependency required beyond default OSM. Data stored as flat JSON files on disk — no external database.

## Stack
- **Frontend + backend**: Streamlit (single Python app)
- **Map engine**: Folium (Leaflet under the hood) via `streamlit-folium`
- **Geolocation**: `streamlit-js-eval` (bridges browser `navigator.geolocation` into Python — required because Folium/Leaflet alone cannot return GPS coords to the Streamlit backend)
- **Storage**: plain JSON files in `data/`
- **Hosting**: Streamlit Community Cloud (free), deployed from a GitHub repo

## Repo structure
```
.
├── app.py
├── requirements.txt
├── data/
│   ├── parcels.geojson     # static source data, exported from ArcGIS Pro/ArcPy — READ ONLY by app
│   ├── owners.json         # {uprn: owner_name} — read/write at runtime
│   └── points.json         # [{uprn, lat, lon, note, timestamp}] — read/write at runtime
└── README.md
```

## Source data contract
`data/parcels.geojson` is exported once (and re-exported whenever source data changes) from ArcGIS Pro. It is a standard GeoJSON `FeatureCollection` of **Polygon** features only. Each feature's `properties` must contain exactly:

| Property | Type | Notes |
|---|---|---|
| `uprn` | string | Unique parcel identifier. Primary key used to join `owners.json` and `points.json` back to a parcel. Must be unique across the file. |
| `display_name` | string | Human-readable label shown as the map tooltip. |

CRS must be **EPSG:4326** (WGS84 lat/lon) — Leaflet/Folium requires this. ArcPy export reference:
```python
arcpy.management.Project("parcel_fabric_layer", "parcels_wgs84", arcpy.SpatialReference(4326))
arcpy.conversion.FeaturesToJSON(
    "parcels_wgs84",
    r"data/parcels.geojson",
    geoJSON="GEOJSON"
)
```
Ensure only `uprn` and `display_name` fields survive into the export (drop or rename other attributes before export) — the app does not expect or use any other property.

## Data files (runtime, app-managed)

**owners.json** — dict keyed by `uprn`:
```json
{
  "P-0001": "Sok Dara",
  "P-0002": "Chan Sopheak"
}
```

**points.json** — list of collected field points:
```json
[
  {
    "uprn": "P-0001",
    "lat": 11.556812,
    "lon": 104.928372,
    "note": "boundary marker south corner",
    "timestamp": "2026-07-14T09:32:10"
  }
]
```
If a point is collected without an associated parcel selected, `uprn` may be `null`.

## Features / behavior

1. **Map render**: on load, read `parcels.geojson`, draw all polygons on a Folium map (OSM tiles). Tooltip on each polygon shows `display_name` and current owner from `owners.json` (or "no owner set"). Center/zoom auto-fit to the bounds of all parcels.
2. **Highlight + owner assignment**: clicking a parcel on the map highlights it (distinct style — e.g. thicker border / fill color change) and populates a side panel showing that parcel's `uprn` / `display_name`. An owner-name text input + "Save owner" button writes to `owners.json` keyed by `uprn`, then reruns to refresh the map/tooltip.
3. **GPS point collection**: a "Get current location" action triggers the browser geolocation prompt via `streamlit-js-eval`. Once coordinates are returned, display them, allow an optional note, and a "Save point" button appends to `points.json` (linked to the currently selected parcel's `uprn` if one is selected, else `null`). Collected points render as markers on the map.
4. **Backup/export**: a "Download backup" button in the sidebar exports `{owners, points}` as a single JSON file the user can download — Streamlit Community Cloud's filesystem is not guaranteed persistent across redeploys/restarts, so this is the safety net.
5. No login, no user identity tracking beyond what's optionally typed into notes.

## requirements.txt
```
streamlit
streamlit-folium
folium
streamlit-js-eval
```

## Non-functional requirements
- Must work in mobile Safari (iOS) and Chrome (Android) — geolocation requires HTTPS, which Streamlit Community Cloud provides automatically.
- Geolocation calls must be triggered by an explicit user tap (button), not on page load — iOS Safari blocks auto-prompted permission requests.
- Target scale: a few hundred parcels, rendered all at once (no pagination/bbox-loading needed at this volume).
- Keep to a single `app.py` file unless it clearly benefits from splitting (e.g. `data_io.py` for load/save helpers) — this is a small internal tool, avoid over-engineering.

## Deployment
1. Push repo to GitHub (public or private) with `data/parcels.geojson` populated.
2. Go to share.streamlit.io → connect repo → deploy `app.py`.
3. Share the resulting URL with the field team; they can "Add to Home Screen" on mobile for app-like access.

## Acceptance checklist
- [ ] Map loads and renders all parcels from `parcels.geojson` with `display_name` tooltips
- [ ] Clicking a parcel highlights it and shows `uprn` + current owner in the side panel
- [ ] Saving an owner name persists to `owners.json` and updates the tooltip after rerun
- [ ] "Get current location" prompts browser permission and returns coordinates on mobile
- [ ] Saving a point persists to `points.json` and renders a marker on the map
- [ ] Backup download button produces a valid JSON file of current owners + points
- [ ] App runs with zero required environment variables / secrets / auth
