import streamlit as st
import pandas as pd
import serpapi
from openai import OpenAI
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="AI Local Map Auditor", page_icon="🗺️", layout="wide")

st.title("🗺️ AI Local Map Auditor")
st.caption("Simple local visibility check + AI action plan. Uses SerpAPI + OpenAI. Not affiliated with any other product.")

def get_secret(name: str, label: str):
    try:
        return st.secrets[name]
    except Exception:
        return st.sidebar.text_input(label, type="password", help="Enter temporarily for local testing. On Streamlit Cloud, put this in secrets.")

serpapi_key = get_secret("SERPAPI_KEY", "SerpAPI Key")
openai_key = get_secret("OPENAI_API_KEY", "OpenAI API Key")

if "results_ready" not in st.session_state:
    st.session_state.results_ready = False
    st.session_state.df = None
    st.session_state.local_results = None
    st.session_state.target_found = False
    st.session_state.target_position = None
    st.session_state.plan = ""
    st.session_state.target_lat = None
    st.session_state.target_lon = None
    st.session_state.target_address = ""
    st.session_state.target_phone = ""

col1, col2 = st.columns(2)
with col1:
    business_name = st.text_input("Target Business Name", placeholder="e.g. Joe's Pizza")
    keyword = st.text_input("Keyword / Search Phrase", placeholder="e.g. landscaping")
    business_address = st.text_input("Business Address (optional – for red pin)", placeholder="Full street address")
    business_phone = st.text_input("Business Phone (optional – for NAP)", placeholder="e.g. (555) 123-4567")
with col2:
    location_input = st.text_input("Search Location (city or address)", placeholder="e.g. Jacksonville, FL")
    lat = st.number_input("Search Center Latitude (optional)", value=0.0, format="%.6f")
    lon = st.number_input("Search Center Longitude (optional)", value=0.0, format="%.6f")
    biz_lat = st.number_input("Business Latitude (optional – for red pin)", value=0.0, format="%.6f")
    biz_lon = st.number_input("Business Longitude (optional – for red pin)", value=0.0, format="%.6f")

zoom = st.slider("Map Zoom (for SerpAPI ll)", 10, 18, 14)

if st.button("Run Audit", type="primary", disabled=not (serpapi_key and openai_key)):
    if not business_name or not keyword or (not location_input and lat == 0.0):
        st.error("Please provide a business name, keyword, and either a location or coordinates.")
    else:
        with st.spinner("Fetching local results from SerpAPI..."):
            try:
                client = serpapi.Client(api_key=serpapi_key)

                if lat != 0.0 and lon != 0.0:
                    params = {
                        "engine": "google_maps",
                        "q": keyword,
                        "type": "search",
                        "hl": "en",
                        "ll": f"@{lat},{lon},{zoom}z",
                    }
                else:
                    params = {
                        "engine": "google",
                        "q": keyword,
                        "location": location_input,
                        "hl": "en",
                        "gl": "us",
                    }

                results = client.search(params)

                if "local_results" in results:
                    local_results = results["local_results"]
                    if isinstance(local_results, dict) and "places" in local_results:
                        local_results = local_results["places"]
                else:
                    local_results = results.get("local_results", {}).get("places", [])

                if not local_results:
                    st.warning("No local results returned. Try a different keyword or location.")
                else:
                    rows = []
                    target_lat = None
                    target_lon = None
                    target_address = business_address
                    target_phone = business_phone

                    for item in local_results[:15]:
                        gps = item.get("gps_coordinates", {})
                        phone = item.get("phone") or item.get("phone_number") or ""
                        rows.append({
                            "Position": item.get("position"),
                            "Title": item.get("title"),
                            "Rating": item.get("rating"),
                            "Reviews": item.get("reviews"),
                            "Address": item.get("address"),
                            "Phone": phone,
                            "Type": item.get("type"),
                            "Latitude": gps.get("latitude"),
                            "Longitude": gps.get("longitude"),
                        })

                        # Capture target business coordinates and NAP if found
                        if business_name.lower() in (str(item.get("title") or "")).lower():
                            target_lat = gps.get("latitude")
                            target_lon = gps.get("longitude")
                            if not target_address:
                                target_address = item.get("address", "")
                            if not target_phone:
                                target_phone = phone

                    # Prefer user-supplied business coordinates if provided
                    if biz_lat != 0.0 and biz_lon != 0.0:
                        target_lat = biz_lat
                        target_lon = biz_lon

                    df = pd.DataFrame(rows)

                    target_found = any(
                        business_name.lower() in (str(r.get("title") or "")).lower()
                        for r in local_results
                    )
                    target_position = next(
                        (r.get("position") for r in local_results
                         if business_name.lower() in (str(r.get("title") or "")).lower()),
                        None
                    )

                    summary_text = df.to_string(index=False)
                    prompt = f"""You are a helpful local SEO assistant. Analyze these Google Maps / local results for the keyword "{keyword}" near "{location_input or f'{lat},{lon}'}".

Target business: {business_name}
Found in results: {target_found}
Position (if found): {target_position}

Top results:
{summary_text}

Write a clear, practical action plan (5-8 bullet points) the business owner could take to improve local visibility. Focus on realistic steps: Google Business Profile optimization, reviews, website/local content, photos, categories, posts, etc. Keep language simple and non-technical. Do not invent data."""

                    with st.spinner("Generating AI action plan..."):
                        oai = OpenAI(api_key=openai_key)
                        completion = oai.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[
                                {"role": "system", "content": "You are a practical local marketing advisor. Be concise and actionable."},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.4,
                        )
                        plan = completion.choices[0].message.content

                    st.session_state.results_ready = True
                    st.session_state.df = df
                    st.session_state.local_results = local_results
                    st.session_state.target_found = target_found
                    st.session_state.target_position = target_position
                    st.session_state.plan = plan
                    st.session_state.target_lat = target_lat
                    st.session_state.target_lon = target_lon
                    st.session_state.target_address = target_address
                    st.session_state.target_phone = target_phone

            except Exception as e:
                st.error(f"Error during audit: {str(e)}")
                st.info("Common issues: invalid API key, insufficient SerpAPI credits, or bad location format.")

if st.session_state.results_ready and st.session_state.df is not None:
    st.subheader("Local Results")
    st.dataframe(st.session_state.df, use_container_width=True)

    map_df = st.session_state.df.dropna(subset=["Latitude", "Longitude"])
    if not map_df.empty or (st.session_state.target_lat and st.session_state.target_lon):
        st.subheader("Map of Top Results (Google Maps) — BIG RED PIN = Target Business")

        # Center map on target if available, otherwise on results average
        if st.session_state.target_lat and st.session_state.target_lon:
            center_lat = st.session_state.target_lat
            center_lon = st.session_state.target_lon
        else:
            center_lat = map_df["Latitude"].mean()
            center_lon = map_df["Longitude"].mean()

        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=13,
            tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
            attr="Google Maps"
        )

        # Normal pins for other results
        for _, row in map_df.iterrows():
            if business_name.lower() not in str(row["Title"]).lower():
                folium.Marker(
                    location=[row["Latitude"], row["Longitude"]],
                    popup=f"{row['Title']}<br>{row.get('Address','')}",
                    tooltip=row["Title"],
                    icon=folium.Icon(color="blue", icon="info-sign")
                ).add_to(m)

        # BIG RED PIN for target business + NAP
        if st.session_state.target_lat and st.session_state.target_lon:
            nap_html = f"""
            <div style="font-family: Arial; font-size: 14px; width: 220px;">
                <b style="color: red; font-size: 16px;">{business_name}</b><br>
                <b>Address:</b> {st.session_state.target_address or 'Not available'}<br>
                <b>Phone:</b> {st.session_state.target_phone or 'Not available'}
            </div>
            """
            folium.Marker(
                location=[st.session_state.target_lat, st.session_state.target_lon],
                popup=folium.Popup(nap_html, max_width=250),
                tooltip=f"TARGET: {business_name}",
                icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
            ).add_to(m)
        else:
            st.info("No coordinates available for the target business. Enter Business Latitude/Longitude (or ensure it appears in results) to place the BIG RED PIN.")

        st_folium(m, width=800, height=500, returned_objects=[])

    col_a, col_b = st.columns(2)
    with col_a:
        st.metric(
            "Listed on Google Business Profile?",
            "Yes" if st.session_state.target_found else "No",
            delta="Found in local results" if st.session_state.target_found else "Not found in local results"
        )
    with col_b:
        st.metric(
            "Ranking Position",
            st.session_state.target_position if st.session_state.target_position else "—",
            delta="Top results" if st.session_state.target_position else "Not ranking for this search"
        )

    if not st.session_state.target_found:
        st.warning(f"**{business_name}** does not appear to be listed (or is not ranking) in the Google Business Profile / Maps results for this search.")

    st.subheader("AI Action Plan")
    st.markdown(st.session_state.plan)

st.sidebar.markdown("""
### Setup notes
- On Streamlit Cloud, add secrets in the dashboard as:
  - SERPAPI_KEY = your-key
  - OPENAI_API_KEY = your-key
- SerpAPI credits are consumed per search.
- City names work with the Google search engine. For more precise results, enter Latitude + Longitude.
- To pin a business that is NOT listed, fill in Business Address, Phone, and Latitude/Longitude.
""")
