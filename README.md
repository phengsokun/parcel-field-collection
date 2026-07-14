# Parcel Field Collection App

Internal web app for field teams to view parcel polygons, assign owners, and collect GPS points on mobile.

## Quick Start (local)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501 in your browser.

## Deployment (Streamlit Community Cloud)

1. Push this repo to GitHub:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/phengsokun/parcel-field-collection.git
   git push -u origin main
   ```

2. Go to [share.streamlit.io](https://share.streamlit.io), connect your GitHub, and deploy `app.py`.

3. Share the URL with the field team. On mobile, "Add to Home Screen" for app-like access.

## Data

| File                 | Purpose                                      | Managed by |
|----------------------|----------------------------------------------|------------|
| `data/parcels.geojson` | Static polygon data (EPSG:4326)             | ArcGIS export |
| `data/owners.json`     | `{uprn: owner_name}` dict                  | App runtime  |
| `data/points.json`     | `[{uprn, lat, lon, note, timestamp}]` list | App runtime  |

## Updating parcel data

Re-export from ArcGIS Pro and overwrite `data/parcels.geojson`. The app reads
it fresh on every load — no restart needed.

## Requirements

- Streamlit
- streamlit-folium
- folium
- streamlit-js-eval
