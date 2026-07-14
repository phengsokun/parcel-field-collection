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
    "<h5 style='margin-top:0;padding-top:0'>📍 ចំរើនទ្រព្យ</h5>",
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
    # Also persist to GitHub to survive container restarts
    _persist_to_github(path, data)

# ── GitHub persistence (survives Streamlit Cloud container restarts) ──
import requests as _requests
import base64 as _base64

_GITHUB_TOKEN = None
_GITHUB_REPO = "phengsokun/parcel-field-collection"

def _get_github_token():
    global _GITHUB_TOKEN
    if _GITHUB_TOKEN is None:
        _GITHUB_TOKEN = (
            os.environ.get("GITHUB_TOKEN", "")
            or st.secrets.get("GITHUB_TOKEN", "")
        )
    return _GITHUB_TOKEN

def _persist_to_github(file_path, data):
    """Push data file to GitHub repo so it survives container restarts."""
    token = _get_github_token()
    if not token:
        return  # silently skip if no token configured
    try:
        rel_path = os.path.relpath(file_path, os.path.dirname(__file__)).replace("\\", "/")
        url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{rel_path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Get current SHA
        r = _requests.get(url, headers=headers, timeout=10)
        sha = r.json().get("sha") if r.status_code == 200 else None
        payload = {
            "message": f"auto: update {rel_path}",
            "content": _base64.b64encode(
                json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
            ).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        _requests.put(url, json=payload, headers=headers, timeout=15)
    except Exception:
        pass  # never block the app for persistence failures

# ── Load data ────────────────────────────────────────────────
if not os.path.exists(PARCELS_FILE):
    st.error(f"`parcels.geojson` not found at `{PARCELS_FILE}`. Export source data first.")
    st.stop()

parcels = load_geojson(PARCELS_FILE)
owners_raw = load_json(OWNERS_FILE, {})

# Migrate old format {uprn: "name"} → {uprn: {name, assigned_at}}
# and provide a helper to read owner names safely
owners = {}
for uprn, val in owners_raw.items():
    if isinstance(val, str):
        owners[uprn] = {"name": val, "assigned_at": ""}
    elif isinstance(val, dict):
        owners[uprn] = val
    else:
        owners[uprn] = {"name": "", "assigned_at": ""}
# Save back if migration happened
if any(isinstance(v, str) for v in owners_raw.values()):
    save_json(OWNERS_FILE, owners)

def owner_name(uprn):
    """Return the owner display name for a UPRN, or empty string."""
    entry = owners.get(uprn)
    if entry is None:
        return ""
    return (entry.get("name") or "").strip()

def has_owner(uprn):
    """True if parcel has a non-empty owner assigned."""
    return bool(owner_name(uprn))

points = load_json(POINTS_FILE, [])

# ── Session state ────────────────────────────────────────────
defaults = {
    "selected_uprn": None,
    "selected_display_name": None,
    "_last_click_uprn": None,
    "_gps_note": "",
    "show_labels": True,
    "_saved_center": None,
    "_saved_zoom": None,
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


# ── Pre-compute map center from parcel data (anti-flicker) ──
if st.session_state._saved_center is None:
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
    st.session_state._saved_center = {
        "lat": round(sum(lats) / len(lats), 5),
        "lng": round(sum(lons) / len(lons), 5),
    }
    st.session_state._saved_zoom = 14

# ── Map builder ──────────────────────────────────────────────
def build_map(parcels, owners, points, highlight_uprn=None, show_labels=True,
              saved_center=None, saved_zoom=None):
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

    # Use saved center/zoom if available (exact view preservation),
    # otherwise fit to all parcels (first load only).
    avg_lat = sum(lats) / len(lats)
    avg_lon = sum(lons) / len(lons)

    if saved_center and saved_zoom and saved_zoom > 2:
        m = folium.Map(tiles=None, location=[saved_center["lat"], saved_center["lng"]],
                       zoom_start=saved_zoom)
    else:
        m = folium.Map(tiles=None, location=[avg_lat, avg_lon], zoom_start=14)
        m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        overlay=False,
    ).add_to(m)

    def style_fn(feature):
        uprn = feature["properties"]["uprn"]
        entry = owners.get(uprn)
        owned = bool(entry and (entry.get("name") or "").strip())
        if uprn == highlight_uprn:
            return {
                "color": "#ff0000", "weight": 4,
                "fillColor": "#ff7800", "fillOpacity": 0.40,
            }
        if owned:
            return {
                "color": "#d62728", "weight": 2,
                "fillColor": "#d62728", "fillOpacity": 0.25,
            }
        return {
            "color": "#3388ff", "weight": 2,
            "fillColor": "#3388ff", "fillOpacity": 0.10,
        }

    # Build enriched GeoJSON
    features = []
    for feat in parcels["features"]:
        uprn = feat["properties"]["uprn"]
        entry = owners.get(uprn)
        _owner_display = (entry.get("name") or "").strip() if entry else ""
        features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": {
                "uprn": uprn,
                "display_name": feat["properties"]["display_name"],
                "owner": _owner_display if _owner_display else "no owner set",
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

    # UPRN text labels at centroids using DivIcon markers.
    # CSS pointer-events:none ensures clicks pass through to GeoJSON parcels.
    if show_labels:
        # Inject CSS so label markers don't intercept clicks
        m.get_root().html.add_child(
            folium.Element("""
<style>
.uprn-label, .uprn-label * {
    pointer-events: none !important;
}
</style>
""")
        )
        for feat in parcels["features"]:
            uprn = feat["properties"]["uprn"]
            c = polygon_centroid(feat)
            if c is None:
                continue
            entry = owners.get(uprn)
            o_name = (entry.get("name") or "").strip() if entry else ""
            if o_name:
                label_text = f"{uprn} - {o_name}"
                color = "#d62728"
            else:
                label_text = str(uprn)
                color = "#222"
            folium.Marker(
                location=[c[1], c[0]],
                icon=folium.DivIcon(
                    html=f'<div style="font-size:10px;font-weight:bold;color:{color};text-shadow:0 0 3px #fff,0 0 3px #fff;white-space:nowrap;">{label_text}</div>',
                    icon_size=(120, 14),
                    icon_anchor=(60, 7),
                    class_name="uprn-label",
                ),
            ).add_to(m)

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

    return m

# ── Layout ───────────────────────────────────────────────────
import copy

@st.cache_resource
def _cached_build_map(owners_json, points_json, show_labels, center_json, zoom):
    """Cache the folium Map object. When inputs are identical
    (e.g. parcel click without pan/zoom), Streamlit sees identical
    component data and keeps the existing iframe → ZERO flicker."""
    _owners = json.loads(owners_json)
    _points = json.loads(points_json)
    _center = json.loads(center_json) if center_json and center_json != "null" else None
    return build_map(parcels, _owners, _points, highlight_uprn=None,
                     show_labels=show_labels,
                     saved_center=_center, saved_zoom=zoom)

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
# Cached map object: when inputs are identical (click without pan/zoom),
# deep copy produces same HTML → Streamlit keeps the iframe → no flicker.
col_map, col_panel = st.columns([3, 1])

with col_map:
    saved_center = st.session_state.get("_saved_center")
    saved_zoom = st.session_state.get("_saved_zoom")
    cached = _cached_build_map(
        json.dumps(owners, sort_keys=True),
        json.dumps(points, sort_keys=True),
        st.session_state.show_labels,
        json.dumps(saved_center, sort_keys=True) if saved_center else "null",
        saved_zoom,
    )
    m = copy.deepcopy(cached)
    map_data = st_folium(m, width=None, height=620, key="folium_map")
    st.session_state._map_data = map_data
    # Only update saved center/zoom on meaningful changes (prevents
    # floating-point jitter from causing cache misses → flicker loop).
    if map_data.get("center") and map_data.get("zoom") and map_data["zoom"] > 2:
        nc = map_data["center"]
        nz = round(map_data["zoom"], 1)
        sc = st.session_state._saved_center or {}
        sz = st.session_state._saved_zoom or 0
        if (abs(round(nc["lat"], 5) - round(sc.get("lat", 0), 5)) > 0.0003 or
            abs(round(nc["lng"], 5) - round(sc.get("lng", 0), 5)) > 0.0003 or
            abs(nz - round(sz, 1)) > 0.3):
            st.session_state._saved_center = {"lat": round(nc["lat"], 5), "lng": round(nc["lng"], 5)}
            st.session_state._saved_zoom = nz

# Debug
with st.expander("🔧 Debug", expanded=False):
    st.write("saved_center:", st.session_state.get("_saved_center"))
    st.write("saved_zoom:", st.session_state.get("_saved_zoom"))
    st.write("map_data keys:", list(map_data.keys()) if map_data else "empty")
    st.json({k: v for k, v in map_data.items() if k not in ("all_drawings", "bounds")} if map_data else {})

# ── Detect map click & trigger owner dialog ───────────────
@st.dialog("✏️ បញ្ចូលម្ចាស់ដី", width="small")
def owner_dialog(uprn, display_name):
    st.markdown(f"**{display_name}**")
    st.caption(f"លេខឡូតិ៍: `{uprn}`")
    current = owner_name(uprn)
    if current:
        st.caption(f"ម្ចាស់បច្ចុប្បន្ន: ✅ {current}")
    new_owner = st.text_input(
        "ឈ្មោះម្ចាស់", value=current,
        key=f"dlg_owner_{uprn}",
        placeholder="ឧ. សុខ ដារ៉ា",
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("💾 រក្សាទុក", use_container_width=True):
            cleaned = new_owner.strip()
            if cleaned:
                owners[uprn] = {"name": cleaned, "assigned_at": datetime.now().isoformat()}
            elif uprn in owners:
                del owners[uprn]
            save_json(OWNERS_FILE, owners)
            _cached_build_map.clear()
            st.session_state._dialog_open = False
            st.rerun()
    with c2:
        if st.button("🗑️ លុប", use_container_width=True):
            if uprn in owners:
                del owners[uprn]
                save_json(OWNERS_FILE, owners)
            _cached_build_map.clear()
            st.session_state._dialog_open = False
            st.rerun()
    with c3:
        if st.button("បោះបង់", use_container_width=True):
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
                    o = owner_name(uprn)
                    matches.append((uprn, name, o))
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
        st.metric("Owners assigned", len([o for o in owners.values() if o.get("name", "").strip()]))
        st.metric("Points collected", len(points))


# ── Fragment: Panel ───────────────────────────────────────
@st.fragment
def render_panel():
    with col_panel:
        st.subheader("📋 ព័ត៌មានដីឡូតិ៍")

        if st.session_state.selected_uprn:
            uprn = st.session_state.selected_uprn
            st.markdown(f"**លេខឡូតិ៍:** `{uprn}`")
            st.markdown(f"**ឈ្មោះ:** {st.session_state.selected_display_name}")

            current_owner = owner_name(uprn)
            if current_owner:
                st.markdown(f"**ម្ចាស់:** ✅ {current_owner}")
            else:
                st.info("មិនទាន់មានម្ចាស់ — ចុចលើផែនទីដើម្បីបញ្ចូល")

            parcel_pts = [p for p in points if p.get("uprn") == uprn]
            if parcel_pts:
                st.divider()
                st.subheader(f"📍 ចំណុច GPS ({len(parcel_pts)})")
                for p in parcel_pts:
                    st.caption(
                        f"({p['lat']:.6f}, {p['lon']:.6f}) — {p.get('note', '')}"
                    )
        else:
            st.info("ចុចលើដីឡូតិ៍ក្នុងផែនទី")
            st.caption("🟢 Green parcels = owner assigned")
            st.caption("🔵 Blue parcels = no owner yet")


render_sidebar()
render_panel()
