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
    "show_labels": True,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Helpers ──────────────────────────────────────────────────
def polygon_centroid(feat):
    """Approximate centroid from exterior ring — good enough for labelling."""
    geom = feat["geometry"]
    if geom["type"] == "Polygon":
        ring = geom["coordinates"][0]
    elif geom["type"] == "MultiPolygon":
        ring = geom["coordinates"][0][0]
    else:
        return None
    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def build_index(parcels):
    """Build a lookup {display_name_lower: feature} and {uprn: feature}."""
    by_name = {}
    by_uprn = {}
    for f in parcels["features"]:
        uprn = f["properties"]["uprn"]
        name = f["properties"]["display_name"]
        by_uprn[uprn] = f
        by_name.setdefault(name.lower(), []).append(f)
    return by_name, by_uprn


# ── Map builder ──────────────────────────────────────────────
def build_map(parcels, owners, points, highlight_uprn=None, show_labels=True):
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

    m = folium.Map(tiles=None)
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        overlay=False,
    ).add_to(m)

    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        name="Google Satellite",
        attr="Google",
        overlay=False,
    ).add_to(m)

    def style_fn(feature):
        uprn = feature["properties"]["uprn"]
        has_owner = uprn in owners and owners[uprn].strip()
        if uprn == highlight_uprn:
            return {
                "color": "#ff0000", "weight": 4,
                "fillColor": "#ff7800", "fillOpacity": 0.40,
            }
        if has_owner:
            return {
                "color": "#2ca02c", "weight": 2,
                "fillColor": "#2ca02c", "fillOpacity": 0.15,
            }
        return {
            "color": "#3388ff", "weight": 2,
            "fillColor": "#3388ff", "fillOpacity": 0.10,
        }

    # Build enriched GeoJSON
    features = []
    for feat in parcels["features"]:
        uprn = feat["properties"]["uprn"]
        owner = owners.get(uprn, "").strip()
        features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": {
                "uprn": uprn,
                "display_name": feat["properties"]["display_name"],
                "owner": owner if owner else "no owner set",
            },
        })

    GeoJson(
        {"type": "FeatureCollection", "features": features},
        style_function=style_fn,
        tooltip=GeoJsonTooltip(
            fields=["display_name", "uprn", "owner"],
            aliases=["Name:", "UPRN:", "Owner:"],
            sticky=False,
        ),
        name="parcels",
        highlight_function=lambda x: {"weight": 3, "fillOpacity": 0.50},
    ).add_to(m)

    # UPRN text labels at centroids
    if show_labels:
        for feat in parcels["features"]:
            uprn = feat["properties"]["uprn"]
            c = polygon_centroid(feat)
            if c is None:
                continue
            label_html = (
                f'<div style="font-size:10px;font-weight:bold;color:#222;'
                f'text-shadow:0 0 3px #fff,0 0 3px #fff;'
                f'white-space:nowrap;pointer-events:none;">{uprn}</div>'
            )
            folium.Marker(
                location=[c[1], c[0]],
                icon=folium.DivIcon(
                    html=label_html, icon_size=(40, 14), icon_anchor=(20, 7)
                ),
            ).add_to(m)
        # Make all div-based markers transparent to clicks
        m.get_root().header.add_child(
            folium.Element(
                "<style>div.leaflet-marker-icon{pointer-events:none!important}</style>"
            )
        )

    # Collected GPS points
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

    LocateControl(
        auto_start=False,
        keepCurrentZoomLevel=True,
        strings={"title": "📍 Use my location", "popup": "You are here"},
    ).add_to(m)

    folium.LayerControl().add_to(m)
    return m

# ── Layout ───────────────────────────────────────────────────

# ── GPS eval (must run in main flow for JS bridge) ────────
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
                st.sidebar.error(f"GPS Error: {result['error']}")
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
                st.sidebar.success(
                    f"✅ Saved at {result['lat']:.6f}, {result['lon']:.6f}"
                )
        st.rerun()
    except ImportError:
        st.sidebar.error("`streamlit-js-eval` not installed. GPS unavailable.")
        st.session_state._gps_pending = False

# ── Map ───────────────────────────────────────────────────
col_map, col_panel = st.columns([3, 1])

with col_map:
    m = build_map(parcels, owners, points, st.session_state.selected_uprn, st.session_state.show_labels)
    map_data = st_folium(m, width=None, height=620)
    st.session_state._map_data = map_data

# ── Fragment: Sidebar ─────────────────────────────────────
@st.fragment
def render_sidebar():
    with st.sidebar:
        st.header("🔧 Tools")

        st.subheader("🔍 Search Parcel")
        search = st.text_input("Name or UPRN", key="search_input", placeholder="e.g. Parcel 42 or 42")
        if search:
            s = search.strip().lower()
            matches = []
            for f in parcels["features"]:
                uprn = f["properties"]["uprn"]
                name = f["properties"]["display_name"]
                if s in name.lower() or s == uprn.lower():
                    owner = owners.get(uprn, "").strip()
                    matches.append((uprn, name, owner))
            if matches:
                for u, n, o in matches[:25]:
                    label = f"{n}  |  {o}" if o else f"{n}  |  —"
                    if st.button(label, key=f"srch_{u}", use_container_width=True):
                        st.session_state.selected_uprn = u
                        st.session_state.selected_display_name = n
                        st.session_state._last_click_uprn = u
                        st.rerun()
            else:
                st.caption("No matches")
        st.divider()

        show = st.checkbox("Show UPRN labels on map", value=st.session_state.show_labels, key="show_labels_cb")
        if show != st.session_state.show_labels:
            st.session_state.show_labels = show
            st.rerun()
        st.divider()

        st.subheader("📍 Save Location")
        if st.button("📍 Save My Location", use_container_width=True):
            st.session_state._gps_pending = True
            st.rerun()

        gps_note = st.text_input("Note for next point (optional)", key="_gps_note_cb")
        if gps_note:
            st.session_state._gps_note = gps_note

        st.divider()

        st.subheader("💾 Backup")
        backup_payload = json.dumps(
            {"owners": owners, "points": points, "exported_at": datetime.now().isoformat()},
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

        st.subheader("📊 Stats")
        st.metric("Parcels", len(parcels["features"]))
        st.metric("Owners assigned", len([o for o in owners.values() if o]))
        st.metric("Points collected", len(points))


# ── Fragment: Panel ───────────────────────────────────────
@st.fragment
def render_panel():
    md = st.session_state.get("_map_data") or {}

    with col_panel:
        # Handle map click
        if md.get("last_object_clicked"):
            clicked = md["last_object_clicked"]
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

        st.subheader("📋 Parcel Details")

        if st.session_state.selected_uprn:
            uprn = st.session_state.selected_uprn
            st.markdown(f"**UPRN:** `{uprn}`")
            st.markdown(f"**Parcel:** {st.session_state.selected_display_name}")

            current_owner = owners.get(uprn, "").strip()
            if current_owner:
                st.markdown(f"**Owner:** ✅ {current_owner}")
            else:
                st.warning("⚠️ No owner assigned — type a name below and save.")

            st.divider()

            new_owner = st.text_input(
                "Owner name",
                value=current_owner,
                key="owner_input",
                placeholder="e.g. Sok Dara",
            )
            if st.button("💾 Save Owner", use_container_width=True):
                cleaned = new_owner.strip()
                if cleaned:
                    owners[uprn] = cleaned
                elif uprn in owners:
                    del owners[uprn]
                save_json(OWNERS_FILE, owners)
                st.rerun()

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
            st.caption("🟢 Green parcels = owner assigned")
            st.caption("🔵 Blue parcels = no owner yet")


render_sidebar()
render_panel()
