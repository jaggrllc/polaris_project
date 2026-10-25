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

col1, col2 = st.columns(2)
with col1:
    business_name = st.text_input("Target Business Name", placeholder="e.g. Joe's Pizza")
    keyword = st.text_input("Keyword / Search Phrase", placeholder="e.g. landscaping")
with col2:
    location_input = st.text_input("Location (city or address)", placeholder="e.g. Jacksonville, FL")
    lat = st.number_input("Latitude (optional)", value=0.0, format="%.6f")
    lon = st.number_input("Longitude (optional)", value=0.0, format="%.6f")

zoom = st.slider("Map Zoom (for SerpAPI ll)", 10, 18, 14)

if st.button("Run Audit", type="primary", disabled=not (serpapi_key and openai_key)):
    if not business_name or not keyword or (not location_input and lat == 0.0):
        st.error("Please provide a business name, keyword, and either a location or coordinates.")
        st.stop()

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
                st.json(results.get("search_metadata", {}))
                st.stop()

            rows = []
            for item in local_results[:15]:
                gps = item.get("gps_coordinates", {})
                rows.append({
                    "Position": item.get("position"),
                    "Title": item.get("title"),
                    "Rating": item.get("rating"),
                    "Reviews": item.get("reviews"),
                    "Address": item.get("address"),
                    "Type": item.get("type"),
                    "Latitude": gps.get("latitude"),
                    "Longitude": gps.get("longitude"),
                })

            df = pd.DataFrame(rows)
            st.subheader("Local Results")
            st.dataframe(df, use_container_width=True)

            map_df = df.dropna(subset=["Latitude", "Longitude"])
            if not map_df.empty:
                st.subheader("Map of Top Results (Google Maps)")
                center_lat = map_df["Latitude"].mean()
                center_lon = map_df["Longitude"].mean()

                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=12,
                    tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
                    attr="Google Maps"
                )

                for _, row in map_df.iterrows():
                    folium.Marker(
                        location=[row["Latitude"], row["Longitude"]],
                        popup=row["Title"],
                        tooltip=row["Title"]
                    ).add_to(m)

                st_folium(m, width=800, height=500)

            target_found = any(
                business_name.lower() in (str(r.get("title") or "")).lower()
                for r in local_results
            )
            target_position = next(
                (r.get("position") for r in local_results
                 if business_name.lower() in (str(r.get("title") or "")).lower()),
                None
            )

            st.metric(
                "Target Business Found in Results?",
                "Yes" if target_found else "No",
                delta=f"Position {target_position}" if target_position else "Not in top results"
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

            st.subheader("AI Action Plan")
            st.markdown(plan)

        except Exception as e:
            st.error(f"Error during audit: {str(e)}")
            st.info("Common issues: invalid API key, insufficient SerpAPI credits, or bad location format.")

st.sidebar.markdown("""
### Setup notes
- On Streamlit Cloud, add secrets in the dashboard as:
  - SERPAPI_KEY = your-key
  - OPENAI_API_KEY = your-key
- SerpAPI credits are consumed per search.
- City names work with the Google search engine. For more precise results, enter Latitude + Longitude.
""")
