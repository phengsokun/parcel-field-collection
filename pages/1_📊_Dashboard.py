import streamlit as st
import json
import os
from datetime import datetime, timedelta, timezone
from collections import Counter

st.set_page_config(page_title="Dashboard", layout="wide")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OWNERS_FILE = os.path.join(DATA_DIR, "owners.json")
PARCELS_FILE = os.path.join(DATA_DIR, "parcels.geojson")
POINTS_FILE = os.path.join(DATA_DIR, "points.json")

ICT = timezone(timedelta(hours=7))

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

owners = load_json(OWNERS_FILE, {})
parcels = load_json(PARCELS_FILE, {})
points = load_json(POINTS_FILE, [])

now = datetime.now(ICT)
today_str = now.strftime("%Y-%m-%d")

st.markdown("## 📊 Dashboard")
st.caption(f"Date: **{today_str}**  |  Server time: {now.strftime('%H:%M')} ICT")

# ── Summary cards ──────────────────────────────────────────
total_parcels = len(parcels.get("features", []))

today_assignments = []
for uprn, entry in owners.items():
    if isinstance(entry, dict):
        assigned_at = entry.get("assigned_at", "")
        name = entry.get("name", "").strip()
        if assigned_at and name:
            try:
                dt = datetime.fromisoformat(assigned_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc).astimezone(ICT)
                if dt.strftime("%Y-%m-%d") == today_str:
                    today_assignments.append({
                        "uprn": uprn,
                        "owner": name,
                        "time": dt.strftime("%H:%M:%S"),
                    })
            except (ValueError, TypeError):
                pass

total_owned = sum(
    1 for e in owners.values()
    if isinstance(e, dict) and e.get("name", "").strip()
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Parcels", total_parcels)
col2.metric("Total Assigned", total_owned)
col3.metric("Assigned Today", len(today_assignments))
col4.metric("GPS Points", len(points))

st.divider()

# ── Today's assignments ────────────────────────────────────
st.subheader(f"📋 Assignments Today ({today_str})")

parcel_names = {}
for f in parcels.get("features", []):
    uprn = f["properties"]["uprn"]
    parcel_names[uprn] = f["properties"]["display_name"]

if today_assignments:
    st.dataframe(
        [{
            "UPRN": a["uprn"],
            "Parcel": parcel_names.get(a["uprn"], f"Parcel {a['uprn']}"),
            "Owner": a["owner"],
            "Time": a["time"],
        } for a in today_assignments],
        use_container_width=True,
        hide_index=True,
        column_config={
            "UPRN": st.column_config.TextColumn("UPRN", width="small"),
            "Parcel": st.column_config.TextColumn("Parcel Name"),
            "Owner": st.column_config.TextColumn("Owner Name"),
            "Time": st.column_config.TextColumn("Time (ICT)", width="small"),
        },
    )
    st.caption(f"**{len(today_assignments)}** parcels assigned today")
else:
    st.info("No parcels assigned today yet.")

st.divider()

# ── All assigned parcels ───────────────────────────────────
st.subheader("🏠 ដីឡូតិ៍មានម្ចាស់ (All Assigned Parcels)")

all_owned = []
for f in parcels.get("features", []):
    uprn = f["properties"]["uprn"]
    entry = owners.get(str(uprn), owners.get(uprn))
    if isinstance(entry, dict) and entry.get("name", "").strip():
        assigned_at = entry.get("assigned_at", "")
        try:
            dt = datetime.fromisoformat(assigned_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc).astimezone(ICT)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            date_str = assigned_at or "—"
        all_owned.append({
            "uprn": uprn,
            "parcel": f["properties"]["display_name"],
            "owner": entry["name"],
            "assigned": date_str,
        })

if all_owned:
    st.dataframe(
        all_owned,
        use_container_width=True,
        hide_index=True,
        column_config={
            "uprn": st.column_config.TextColumn("លេខឡូតិ៍", width="small"),
            "parcel": st.column_config.TextColumn("ឈ្មោះ"),
            "owner": st.column_config.TextColumn("ម្ចាស់"),
            "assigned": st.column_config.TextColumn("ថ្ងៃបញ្ចូល", width="small"),
        },
    )
    st.caption(f"**{len(all_owned)}** / {total_parcels} parcels assigned "
               f"({len(all_owned)/total_parcels*100:.0f}%)")
else:
    st.info("មិនទាន់មានដីឡូតិ៍បញ្ចូលម្ចាស់")

st.divider()

# ── Last 7 days ────────────────────────────────────────────
st.subheader("📅 Recent Assignments (Last 7 Days)")

all_assignments = []
for uprn, entry in owners.items():
    if isinstance(entry, dict):
        assigned_at = entry.get("assigned_at", "")
        name = entry.get("name", "").strip()
        if assigned_at and name:
            try:
                dt = datetime.fromisoformat(assigned_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc).astimezone(ICT)
                all_assignments.append({
                    "uprn": uprn,
                    "owner": name,
                    "date": dt.strftime("%Y-%m-%d"),
                    "time": dt.strftime("%H:%M:%S"),
                    "dt": dt,
                })
            except (ValueError, TypeError):
                pass

cutoff = now - timedelta(days=7)
recent = [a for a in all_assignments if a["dt"] >= cutoff]
recent.sort(key=lambda a: a["dt"], reverse=True)

if recent:
    st.dataframe(
        [{
            "Date": a["date"],
            "UPRN": a["uprn"],
            "Parcel": parcel_names.get(a["uprn"], f"Parcel {a['uprn']}"),
            "Owner": a["owner"],
            "Time": a["time"],
        } for a in recent],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Date": st.column_config.TextColumn("Date", width="small"),
            "UPRN": st.column_config.TextColumn("UPRN", width="small"),
            "Parcel": st.column_config.TextColumn("Parcel Name"),
            "Owner": st.column_config.TextColumn("Owner Name"),
            "Time": st.column_config.TextColumn("Time (ICT)", width="small"),
        },
    )

    by_date = Counter(a["date"] for a in recent)
    st.caption(" | ".join(
        f"**{d}**: {c}" for d, c in sorted(by_date.items(), reverse=True)
    ))
else:
    st.info("No assignments in the last 7 days.")
