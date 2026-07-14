import streamlit as st
from streamlit_folium import st_folium
import folium
from folium.features import GeoJson, GeoJsonTooltip
from folium.plugins import LocateControl
import json
import os
from datetime import datetime

# ── Page config ──────────────────────────────────────────────
st.set_page_config(page_title="Parcel Field Collection", layout="wide")
st.markdown(
    "<h3 style='margin-top:0;padding-top:0'>📍 Parcel Field Collection</h3>",
    unsafe_allow_html=True,
)

# ── Constants ────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PARCELS_FILE = os.path.join(DATA_DIR, "parcels.geojson")
OWNERS_FILE = os.path.join(DATA_DIR, "owners.json")
POINTS_FILE = os.path.join(DATA_DIR, "points.json")

# ── Data I/O helpers ────────────────────────────────────────
def load_geojson(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ── Load data ────────────────────────────────────────────────
if not os.path.exists(PARCELS_FILE):
    st.error(f"`parcels.geojson` not found at `{PARCELS_FILE}`. Export source data first.")
    st.stop()

parcels = load_geojson(PARCELS_FILE)
owners = load_json(OWNERS_FILE, {})
points = load_json(POINTS_FILE, [])

# ── Session state ────────────────────────────────────────────
defaults = {
    "selected_uprn": None,
    "selected_display_name": None,
    "_last_click_uprn": None,
    "_gps_note": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Map builder ──────────────────────────────────────────────
def build_map(parcels, owners, points, highlight_uprn=None):
    # Compute bounds from all parcel coordinates
    all_coords = []
    for feat in parcels["features"]:
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            all_coords.extend(geom["coordinates"][0])
        elif geom["type"] == "MultiPolygon":
            for ring in geom["coordinates"]:
                all_coords.extend(ring[0])
    lats = [c[1] for c in all_coords]
    lons = [c[0] for c in all_coords]

    m = folium.Map(tiles="OpenStreetMap")
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])

    def style_fn(feature):
        if feature["properties"]["uprn"] == highlight_uprn:
            return {
                "color": "#ff0000", "weight": 4,
                "fillColor": "#ff7800", "fillOpacity": 0.35,
            }
        return {
            "color": "#3388ff", "weight": 2,
            "fillColor": "#3388ff", "fillOpacity": 0.12,
        }

    # Enrich features with owner info for tooltip
    features = []
    for feat in parcels["features"]:
        uprn = feat["properties"]["uprn"]
        owner = owners.get(uprn, "no owner set")
        f = {
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": {
                "uprn": uprn,
                "display_name": feat["properties"]["display_name"],
                "owner": owner,
            },
        }
        features.append(f)

    GeoJson(
        {"type": "FeatureCollection", "features": features},
        style_function=style_fn,
        tooltip=GeoJsonTooltip(
            fields=["display_name", "uprn", "owner"],
            aliases=["Name:", "UPRN:", "Owner:"],
            sticky=False,
        ),
        name="parcels",
        highlight_function=lambda x: {"weight": 3, "fillOpacity": 0.45},
    ).add_to(m)

    # Collected GPS points as markers
    for pt in points:
        popup_html = (
            f"<b>UPRN:</b> {pt.get('uprn', 'none')}<br>"
            f"<b>Note:</b> {pt.get('note', '')}<br>"
            f"<b>Time:</b> {pt.get('timestamp', '')}"
        )
        folium.Marker(
            location=[pt["lat"], pt["lon"]],
            popup=folium.Popup(popup_html, max_width=250),
            icon=folium.Icon(color="green", icon="map-marker", prefix="fa"),
        ).add_to(m)

    # Locate button directly on the map
    LocateControl(
        auto_start=False,
        keepCurrentZoomLevel=True,
        strings={"title": "📍 Use my location", "popup": "You are here"},
    ).add_to(m)

    folium.LayerControl().add_to(m)
    return m

# ── Layout ───────────────────────────────────────────────────
col_map, col_panel = st.columns([3, 1])

with col_map:
    m = build_map(parcels, owners, points, st.session_state.selected_uprn)
    map_data = st_folium(m, width=None, height=620)

with col_panel:
    # ── Handle map click ──
    if map_data and map_data.get("last_object_clicked"):
        clicked = map_data["last_object_clicked"]
        # st_folium may return full Feature or raw properties dict
        if isinstance(clicked, dict):
            props = clicked.get("properties", clicked)
            if props and "uprn" in props:
                new_uprn = props["uprn"]
                if new_uprn != st.session_state._last_click_uprn:
                    st.session_state.selected_uprn = new_uprn
                    st.session_state.selected_display_name = props.get(
                        "display_name", f"Parcel {new_uprn}"
                    )
                    st.session_state._last_click_uprn = new_uprn
                    st.rerun()

    # ── Panel content ──
    st.subheader("📋 Parcel Details")

    if st.session_state.selected_uprn:
        uprn = st.session_state.selected_uprn
        st.markdown(f"**UPRN:** `{uprn}`")
        st.markdown(f"**Name:** {st.session_state.selected_display_name}")

        current_owner = owners.get(uprn, "")
        st.markdown(
            f"**Current Owner:** _{current_owner if current_owner else 'No owner set'}_"
        )

        st.divider()
        st.subheader("✏️ Update Owner")
        new_owner = st.text_input(
            "Owner name", value=current_owner, key="owner_input"
        )

        if st.button("💾 Save Owner", use_container_width=True):
            cleaned = new_owner.strip()
            if cleaned:
                owners[uprn] = cleaned
            elif uprn in owners:
                del owners[uprn]
            save_json(OWNERS_FILE, owners)
            st.rerun()

        # Show collected points for this parcel
        parcel_pts = [p for p in points if p.get("uprn") == uprn]
        if parcel_pts:
            st.divider()
            st.subheader(f"📍 Points ({len(parcel_pts)})")
            for p in parcel_pts:
                st.caption(
                    f"({p['lat']:.6f}, {p['lon']:.6f}) — {p.get('note', '')}"
                )
    else:
        st.info("Click a parcel on the map to select it.")

# ── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.header("🔧 Tools")

    # ── GPS ──
    st.subheader("📍 Save Location")

    if st.button("📍 Save My Location", use_container_width=True):
        st.session_state._gps_pending = True
        st.rerun()

    if st.session_state.get("_gps_pending"):
        try:
            from streamlit_js_eval import streamlit_js_eval

            js_code = """
            new Promise((resolve) => {
                if (!navigator.geolocation) {
                    resolve({error: "Geolocation not supported by this browser"});
                    return;
                }
                navigator.geolocation.getCurrentPosition(
                    (pos) => resolve({lat: pos.coords.latitude, lon: pos.coords.longitude}),
                    (err) => resolve({error: err.message}),
                    {enableHighAccuracy: true, timeout: 15000, maximumAge: 0}
                );
            })
            """
            result = streamlit_js_eval(js_expressions=js_code, key="gps_eval")
            st.session_state._gps_pending = False
            if result:
                if "error" in result:
                    st.error(f"GPS Error: {result['error']}")
                elif "lat" in result:
                    new_point = {
                        "uprn": st.session_state.selected_uprn,
                        "lat": result["lat"],
                        "lon": result["lon"],
                        "note": st.session_state.get("_gps_note", ""),
                        "timestamp": datetime.now().isoformat(),
                    }
                    points.append(new_point)
                    save_json(POINTS_FILE, points)
                    st.success(
                        f"✅ Saved at {result['lat']:.6f}, {result['lon']:.6f}"
                    )
                    st.rerun()
        except ImportError:
            st.error("`streamlit-js-eval` not installed. GPS unavailable.")
            st.session_state._gps_pending = False

    # Optional note that gets attached to next GPS save
    gps_note = st.text_input("Note for next point (optional)", key="_gps_note")
    if gps_note:
        st.session_state._gps_note = gps_note

    st.divider()

    # ── Backup ──
    st.subheader("💾 Backup")
    backup_payload = json.dumps(
        {
            "owners": owners,
            "points": points,
            "exported_at": datetime.now().isoformat(),
        },
        indent=2,
        ensure_ascii=False,
    )
    st.download_button(
        label="📥 Download Backup",
        data=backup_payload,
        file_name=f"field_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        use_container_width=True,
    )

    st.divider()

    # ── Stats ──
    st.subheader("📊 Stats")
    st.metric("Parcels", len(parcels["features"]))
    st.metric("Owners assigned", len([o for o in owners.values() if o]))
    st.metric("Points collected", len(points))
