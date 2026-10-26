import streamlit as st
import pandas as pd
import serpapi
from openai import OpenAI
import folium
from streamlit_folium import st_folium
from datetime import datetime
from collections import Counter
from urllib.parse import quote
import re

st.set_page_config(page_title="AI Local Map Auditor", page_icon="🗺️", layout="wide")

st.title("🗺️ AI Local Map Auditor")
st.caption("Local visibility check + AI insights. Original tool — not affiliated with any other product.")

def get_secret(name: str, label: str):
    try:
        return st.secrets[name]
    except Exception:
        return st.sidebar.text_input(label, type="password")

def clean_name(name):
    """Normalize business name for better matching."""
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'\b(llc|inc|ltd|co|company)\b', '', name)
    name = re.sub(r'[^a-z0-9\s]', '', name)
    return " ".join(name.split())

serpapi_key = get_secret("SERPAPI_KEY", "SerpAPI Key")
openai_key = get_secret("OPENAI_API_KEY", "OpenAI API Key")

if "results_ready" not in st.session_state:
    st.session_state.results_ready = False
    st.session_state.df = None
    st.session_state.target_found = False
    st.session_state.target_position = None
    st.session_state.plan = ""
    st.session_state.target_lat = None
    st.session_state.target_lon = None
    st.session_state.target_address = ""
    st.session_state.target_phone = ""
    st.session_state.auto_nap = ""
    st.session_state.visibility_score = None
    st.session_state.competitors = ""
    st.session_state.sample_content = ""
    st.session_state.biz_lat_input = 0.0
    st.session_state.biz_lon_input = 0.0

col1, col2 = st.columns(2)
with col1:
    business_name = st.text_input("Target Business Name", placeholder="e.g. Dan The Landscapin Man LLC")
    keyword = st.text_input("Keyword / Search Phrase", placeholder="e.g. landscaping")
    business_address = st.text_input("Business Address (optional override)")
    business_phone = st.text_input("Business Phone (optional override)")
with col2:
    location_input = st.text_input("Search Location (city)", placeholder="e.g. Jacksonville, FL")
    lat = st.number_input("Search Center Latitude (optional)", value=0.0, format="%.6f")
    lon = st.number_input("Search Center Longitude (optional)", value=0.0, format="%.6f")
    biz_lat = st.number_input(
        "Business Latitude (auto-filled when found)",
        value=st.session_state.biz_lat_input,
        format="%.6f",
        key="biz_lat_input"
    )
    biz_lon = st.number_input(
        "Business Longitude (auto-filled when found)",
        value=st.session_state.biz_lon_input,
        format="%.6f",
        key="biz_lon_input"
    )

do_grid = st.checkbox("Run simple 3-point visibility check (uses extra SerpAPI credits)", value=False)
zoom = st.slider("Map Zoom (for ll)", 10, 18, 14)

if st.button("Run Audit", type="primary", disabled=not (serpapi_key and openai_key)):
    if not business_name or not keyword or (not location_input and lat == 0.0):
        st.error("Please provide a business name, keyword, and a location or coordinates.")
    else:
        with st.spinner("Running audit..."):
            try:
                client = serpapi.Client(api_key=serpapi_key)
                points = []

                if lat != 0.0 and lon != 0.0:
                    center_ll = f"@{lat},{lon},{zoom}z"
                    points.append(("Center", center_ll))
                    if do_grid:
                        offset = 0.02
                        points.append(("North", f"@{lat+offset},{lon},{zoom}z"))
                        points.append(("East", f"@{lat},{lon+offset},{zoom}z"))
                else:
                    points.append(("Main", None))

                all_local = []
                point_results = []

                for label, ll in points:
                    if ll:
                        params = {"engine": "google_maps", "q": keyword, "type": "search", "hl": "en", "ll": ll}
                    else:
                        params = {"engine": "google", "q": keyword, "location": location_input, "hl": "en", "gl": "us"}

                    res = client.search(params)
                    local = res.get("local_results", [])
                    if isinstance(local, dict) and "places" in local:
                        local = local["places"]
                    all_local.extend(local or [])
                    point_results.append((label, local or []))

                if not all_local:
                    st.warning("No local results returned.")
                else:
                    main_local = point_results[0][1]
                    rows = []
                    target_lat = target_lon = None
                    target_address = target_phone = ""
                    cleaned_target = clean_name(business_name)

                    # Look deeper (top 15) for better matching
                    for item in main_local[:15]:
                        gps = item.get("gps_coordinates", {}) or {}
                        phone = item.get("phone") or item.get("phone_number") or ""
                        title = item.get("title") or ""
                        rows.append({
                            "Position": item.get("position"),
                            "Title": title,
                            "Rating": item.get("rating"),
                            "Reviews": item.get("reviews"),
                            "Address": item.get("address"),
                            "Phone": phone,
                            "Latitude": gps.get("latitude"),
                            "Longitude": gps.get("longitude"),
                        })
                        # Flexible name match
                        if cleaned_target and cleaned_target in clean_name(title):
                            target_lat = gps.get("latitude")
                            target_lon = gps.get("longitude")
                            target_address = item.get("address") or ""
                            target_phone = phone

                    # User overrides
                    if st.session_state.biz_lat_input != 0.0 and st.session_state.biz_lon_input != 0.0:
                        target_lat = st.session_state.biz_lat_input
                        target_lon = st.session_state.biz_lon_input
                    if business_address.strip():
                        target_address = business_address.strip()
                    if business_phone.strip():
                        target_phone = business_phone.strip()

                    # Fallback to search center if still no coordinates
                    if not target_lat and lat != 0.0:
                        target_lat = lat
                        target_lon = lon

                    if target_lat and target_lon:
                        st.session_state.biz_lat_input = float(target_lat)
                        st.session_state.biz_lon_input = float(target_lon)

                    # Display only top 5 in the table
                    df = pd.DataFrame(rows[:5])
                    target_found = any(cleaned_target in clean_name(str(r.get("title") or "")) for r in main_local)
                    target_position = next(
                        (r.get("position") for r in main_local
                         if cleaned_target in clean_name(str(r.get("title") or ""))),
                        None
                    )

                    top3_count = 0
                    for _, locs in point_results:
                        for item in locs[:3]:
                            if cleaned_target in clean_name(str(item.get("title") or "")):
                                top3_count += 1
                                break
                    visibility_score = round((top3_count / len(points)) * 100) if points else 0

                    titles = [item.get("title") for item in all_local if item.get("title")]
                    competitors = Counter(titles).most_common(5)
                    comp_text = "\n".join([f"{name}: {count} appearances" for name, count in competitors])

                    summary = df.to_string(index=False)
                    prompt = f"""Analyze local results for "{keyword}" near {location_input or f'{lat},{lon}'}.
Target: {business_name} (found: {target_found}, position: {target_position}, visibility score: {visibility_score}%).
Top 5 results:\n{summary}
Competitors:\n{comp_text}

1. Write a practical 5-8 bullet action plan.
2. Then write a short sample Google Business Profile post idea.
3. Then a brief outline for a local service page (3-4 headings).
Keep everything concise and realistic. Do not invent data."""

                    oai = OpenAI(api_key=openai_key)
                    completion = oai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.4,
                    )
                    full_ai = completion.choices[0].message.content
                    plan = full_ai.split("2.")[0] if "2." in full_ai else full_ai
                    sample_content = full_ai

                    st.session_state.update({
                        "results_ready": True,
                        "df": df,
                        "target_found": target_found,
                        "target_position": target_position,
                        "plan": plan,
                        "target_lat": target_lat,
                        "target_lon": target_lon,
                        "target_address": target_address,
                        "target_phone": target_phone,
                        "auto_nap": f"Name: {business_name}\nAddress: {target_address or 'N/A'}\nPhone: {target_phone or 'N/A'}",
                        "visibility_score": visibility_score,
                        "competitors": comp_text,
                        "sample_content": sample_content,
                    })

            except Exception as e:
                st.error(f"Error: {e}")

if st.session_state.results_ready and st.session_state.df is not None:
    st.metric("Visibility Score (approx. % in top 3)", f"{st.session_state.visibility_score}%")

    st.subheader("Top 5 Local Results")
    st.dataframe(st.session_state.df, use_container_width=True)

    if st.session_state.target_lat and st.session_state.target_lon:
        st.success("Auto-populated Coordinates & NAP:")
        st.code(
            f"{st.session_state.auto_nap}\n"
            f"Latitude: {st.session_state.target_lat}\n"
            f"Longitude: {st.session_state.target_lon}"
        )

    # GO TO button — now much more likely to have coordinates
    if st.session_state.target_lat and st.session_state.target_lon:
        name_encoded = quote(business_name)
        maps_url = (
            f"https://www.google.com/maps/place/{name_encoded}/"
            f"@{st.session_state.target_lat},{st.session_state.target_lon},15z"
        )
        st.link_button(f"GO to {business_name}", maps_url, type="primary")
        st.caption(f"URL uses coordinates: {st.session_state.target_lat}, {st.session_state.target_lon}")
    else:
        st.info("Could not determine coordinates. Try entering Search Center Latitude/Longitude or a more specific keyword.")

    map_df = st.session_state.df.dropna(subset=["Latitude", "Longitude"])
    if not map_df.empty or st.session_state.target_lat:
        center = [st.session_state.target_lat or map_df["Latitude"].mean(),
                  st.session_state.target_lon or map_df["Longitude"].mean()]
        m = folium.Map(location=center, zoom_start=13,
                       tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}", attr="Google Maps")

        for _, row in map_df.iterrows():
            if clean_name(business_name) not in clean_name(str(row["Title"])):
                folium.Marker([row["Latitude"], row["Longitude"]], popup=row["Title"],
                              icon=folium.Icon(color="blue")).add_to(m)

        if st.session_state.target_lat and st.session_state.target_lon:
            nap_html = f"<b style='color:red'>{business_name}</b><br>{st.session_state.target_address}<br>{st.session_state.target_phone}"
            folium.Marker([st.session_state.target_lat, st.session_state.target_lon],
                          popup=folium.Popup(nap_html, max_width=250),
                          icon=folium.Icon(color="red", icon="map-marker", prefix="fa")).add_to(m)
        st_folium(m, width=800, height=450, returned_objects=[])

    col_a, col_b = st.columns(2)
    with col_a:
        st.metric("Listed on Google Business Profile?", "Yes" if st.session_state.target_found else "No")
    with col_b:
        st.metric("Position", st.session_state.target_position or "—")

    st.subheader("Top Competitors (by appearance)")
    st.text(st.session_state.competitors)

    st.subheader("AI Action Plan")
    st.markdown(st.session_state.plan)

    st.subheader("Sample Content Ideas")
    st.markdown(st.session_state.sample_content)

    report = f"""AI Local Map Auditor Report
Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Business: {business_name}
Keyword: {keyword}
Location: {location_input or f'{lat},{lon}'}
Visibility Score: {st.session_state.visibility_score}%
Listed: {'Yes' if st.session_state.target_found else 'No'}
Position: {st.session_state.target_position or 'N/A'}

NAP:
{st.session_state.auto_nap}

Top 5 Local Results:
{st.session_state.df.to_string(index=False)}

Competitors:
{st.session_state.competitors}

AI Insights:
{st.session_state.sample_content}
"""
    st.download_button("Download Text Report", report, file_name="local_audit_report.txt", mime="text/plain")

st.sidebar.info("Name matching is more flexible. Coordinates are captured from results or fall back to search center.")
