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
    "_dialog_open": False,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

from shapely.geometry import Point, shape

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


def find_parcel_at_point(lat, lng, parcels):
    """Return the GeoJSON feature whose polygon contains (lat, lng)."""
    pt = Point(lng, lat)
    for feat in parcels["features"]:
        geom = shape(feat["geometry"])
        if geom.contains(pt) or geom.touches(pt) or geom.distance(pt) < 1e-8:
            return feat
    return None


# ── Map builder ──────────────────────────────────────────────
def build_map(parcels, owners, points, highlight_uprn=None, show_labels=True,
              center=None, zoom=None):
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
    if center and zoom:
        m.location = [center["lat"], center["lng"]]
        m.zoom_start = zoom
    else:
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
            style="font-size:11px;padding:4px 6px;max-width:180px;",
        ),
        name="parcels",
        highlight_function=lambda x: {"weight": 3, "fillOpacity": 0.50},
    ).add_to(m)

    # UPRN text labels at centroids — use folium CircleMarker with
    # permanent tooltips. Zero-radius invisible markers that don't
    # intercept clicks, with always-visible labels beside them.
    if show_labels:
        for feat in parcels["features"]:
            uprn = feat["properties"]["uprn"]
            c = polygon_centroid(feat)
            if c is None:
                continue
            folium.CircleMarker(
                location=[c[1], c[0]],
                radius=0,
                fill=False,
                color="transparent",
                weight=0,
                interactive=False,
            ).add_to(m)

        # Add labels as JS-injected text in a custom pane BELOW the overlay pane
        # so clicks always pass through to GeoJSON parcels.
        labels_data = []
        for feat in parcels["features"]:
            uprn = feat["properties"]["uprn"]
            c = polygon_centroid(feat)
            if c is None:
                continue
            labels_data.append([c[1], c[0], str(uprn)])

        labels_json = json.dumps(labels_data)
        m.get_root().html.add_child(
            folium.Element(f"""
<script>
(function() {{
    var _labels = {labels_json};
    var _tries = 0;
    function _addLabels() {{
        var maps = document.querySelectorAll('.folium-map');
        if (!maps.length || !maps[0]._leaflet_map) {{
            if (++_tries < 100) setTimeout(_addLabels, 200);
            return;
        }}
        var _map = maps[0]._leaflet_map;
        // Create a custom pane with z-index between tilePane (200) and overlayPane (400)
        if (!_map.getPane('labelPane')) {{
            _map.createPane('labelPane');
            _map.getPane('labelPane').style.zIndex = 300;
            _map.getPane('labelPane').style.pointerEvents = 'none';
        }}
        _labels.forEach(function(l) {{
            var icon = L.divIcon({{
                html: '<div style="font-size:10px;font-weight:bold;color:#222;text-shadow:0 0 3px #fff,0 0 3px #fff;white-space:nowrap;">' + l[2] + '</div>',
                iconSize: [40, 14],
                iconAnchor: [20, 7],
                className: ''
            }});
            L.marker([l[0], l[1]], {{
                icon: icon,
                interactive: false,
                keyboard: false,
                bubblingMouseEvents: false,
                pane: 'labelPane'
            }}).addTo(_map);
        }});
    }}
    if (document.readyState === 'complete') _addLabels();
    else window.addEventListener('load', _addLabels);
}})();
</script>
""")
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
    # Use saved view if valid (not the bogus {lat:0,lng:0} from initial load)
    saved_center = st.session_state.get("_map_center")
    saved_zoom = st.session_state.get("_map_zoom")
    # Validate: center must be within +-20 degrees of parcel area to be usable
    if saved_center and saved_zoom:
        clat, clng = saved_center.get("lat", 0), saved_center.get("lng", 0)
        if abs(clat) < 1 and abs(clng) < 1:  # near 0,0 = bogus default
            saved_center = None
            saved_zoom = None

    m = build_map(parcels, owners, points, st.session_state.selected_uprn,
                  st.session_state.show_labels,
                  center=saved_center, zoom=saved_zoom)
    map_data = st_folium(m, width=None, height=620, key="folium_map")
    st.session_state._map_data = map_data

    # Save view for next render, but only if it looks real
    if map_data.get("center") and map_data.get("zoom"):
        c = map_data["center"]
        if abs(c.get("lat", 0)) > 1 or abs(c.get("lng", 0)) > 1:
            st.session_state._map_center = c
            st.session_state._map_zoom = map_data["zoom"]

# ── DEBUG: show raw map_data ─────────────────────────────
with st.expander("🔧 Debug: st_folium return data", expanded=False):
    st.json(map_data)
    st.write("selected_uprn:", st.session_state.get("selected_uprn"))
    st.write("_last_click_uprn:", st.session_state.get("_last_click_uprn"))

# ── Detect map click & trigger owner dialog ───────────────
@st.dialog("✏️ Assign Owner", width="small")
def owner_dialog(uprn, display_name):
    st.markdown(f"**{display_name}**")
    st.caption(f"UPRN: `{uprn}`")
    current = owners.get(uprn, "").strip()
    if current:
        st.caption(f"Current owner: ✅ {current}")
    new_owner = st.text_input(
        "Owner name", value=current,
        key=f"dlg_owner_{uprn}",
        placeholder="e.g. Sok Dara",
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Save", use_container_width=True):
            cleaned = new_owner.strip()
            if cleaned:
                owners[uprn] = cleaned
            elif uprn in owners:
                del owners[uprn]
            save_json(OWNERS_FILE, owners)
            st.session_state._dialog_open = False
            st.rerun()
    with c2:
        if st.button("Cancel", use_container_width=True):
            st.session_state._dialog_open = False
            st.rerun()

if map_data.get("last_object_clicked"):
    clicked = map_data["last_object_clicked"]
    if isinstance(clicked, dict) and "lat" in clicked and "lng" in clicked:
        lat, lng = clicked["lat"], clicked["lng"]
        feat = find_parcel_at_point(lat, lng, parcels)
        if feat:
            new_uprn = feat["properties"]["uprn"]
            if new_uprn != st.session_state.get("_last_click_uprn"):
                st.session_state.selected_uprn = new_uprn
                st.session_state.selected_display_name = feat["properties"].get(
                    "display_name", f"Parcel {new_uprn}"
                )
                st.session_state._last_click_uprn = new_uprn
                st.session_state._dialog_open = True
                # No st.rerun() — dialog renders on this same cycle,
                # map stays at its current view.

if st.session_state.get("_dialog_open"):
    owner_dialog(st.session_state.selected_uprn, st.session_state.selected_display_name)

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
    with col_panel:
        st.subheader("📋 Parcel Details")

        if st.session_state.selected_uprn:
            uprn = st.session_state.selected_uprn
            st.markdown(f"**UPRN:** `{uprn}`")
            st.markdown(f"**Parcel:** {st.session_state.selected_display_name}")

            current_owner = owners.get(uprn, "").strip()
            if current_owner:
                st.markdown(f"**Owner:** ✅ {current_owner}")
            else:
                st.info("No owner — click the parcel on the map to assign one.")

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
