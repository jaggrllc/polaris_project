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
st.caption("Local visibility check, competitor insight, and AI content tools. Original implementation.")

def get_secret(name: str, label: str):
    try:
        return st.secrets[name]
    except Exception:
        return st.sidebar.text_input(label, type="password")

def normalize(name):
    if not name:
        return ""
    name = name.lower()
    name = name.replace("&", "and").replace("+", "and")
    name = re.sub(r'\b(llc|inc|ltd|co|company|the)\b', '', name)
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.replace("landscaping", "landscape")
    return name

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
    st.session_state.keywords = ""
    st.session_state.website_tips = ""

col1, col2 = st.columns(2)
with col1:
    business_name = st.text_input("Target Business Name", placeholder="e.g. C&L Landscape")
    keyword = st.text_input("Keyword / Search Phrase", placeholder="e.g. landscaper")
    business_address = st.text_input("Business Address (optional override)")
    business_phone = st.text_input("Business Phone (optional override)")
with col2:
    location_input = st.text_input("Search Location (city)", placeholder="e.g. Jacksonville, FL")

if st.button("Run Audit", type="primary", disabled=not (serpapi_key and openai_key)):
    if not business_name or not keyword or not location_input:
        st.error("Please provide a business name, keyword, and a location.")
    else:
        with st.spinner("Running audit and generating insights..."):
            try:
                client = serpapi.Client(api_key=serpapi_key)
                params = {
                    "engine": "google",
                    "q": keyword,
                    "location": location_input,
                    "hl": "en",
                    "gl": "us",
                }
                res = client.search(params)
                local = res.get("local_results", [])
                if isinstance(local, dict) and "places" in local:
                    local = local["places"]
                main_local = local or []

                if not main_local:
                    st.warning("No local results returned. Try a different keyword.")
                else:
                    rows = []
                    target_lat = target_lon = None
                    target_address = target_phone = ""
                    norm_target = normalize(business_name)

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
                        if norm_target and norm_target in normalize(title):
                            target_lat = gps.get("latitude")
                            target_lon = gps.get("longitude")
                            target_address = item.get("address") or ""
                            target_phone = phone

                    if business_address.strip():
                        target_address = business_address.strip()
                    if business_phone.strip():
                        target_phone = business_phone.strip()

                    df = pd.DataFrame(rows[:5])
                    target_found = any(norm_target in normalize(str(r.get("title") or "")) for r in main_local)
                    target_position = next(
                        (r.get("position") for r in main_local
                         if norm_target in normalize(str(r.get("title") or ""))),
                        None
                    )
                    visibility_score = 100 if target_found else 0

                    titles = [item.get("title") for item in main_local if item.get("title")]
                    competitors = Counter(titles).most_common(5)
                    comp_text = "\n".join([f"{name}: {count}" for name, count in competitors])

                    summary = df.to_string(index=False)
                    prompt = f"""You are a practical local SEO advisor. Analyze results for "{keyword}" near {location_input}.
Target business: {business_name}
Found: {target_found}
Position: {target_position}
Top results:
{summary}
Competitors:
{comp_text}

Respond in clear sections:

1. ACTION PLAN
5-8 practical bullet points.

2. SAMPLE GOOGLE BUSINESS PROFILE POST
One ready-to-use post (3-5 sentences) with a call to action.

3. LOCAL PAGE OUTLINE
3-4 headings with a one-sentence description each.

4. SHORT ARTICLE SNIPPET
A 120-150 word sample paragraph a local page could use.

5. WEBSITE IMPROVEMENT TIPS
3-5 specific, realistic tips.

6. REVIEW RESPONSE IDEAS
Two short example responses (one positive, one neutral/negative).

7. SUGGESTED KEYWORDS
5 related keywords or phrases to target.
Do not invent data. Keep everything concise and useful."""

                    oai = OpenAI(api_key=openai_key)
                    completion = oai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.4,
                    )
                    full_ai = completion.choices[0].message.content

                    st.session_state.update({
                        "results_ready": True,
                        "df": df,
                        "target_found": target_found,
                        "target_position": target_position,
                        "plan": full_ai,
                        "target_lat": target_lat,
                        "target_lon": target_lon,
                        "target_address": target_address,
                        "target_phone": target_phone,
                        "auto_nap": f"Name: {business_name}\nAddress: {target_address or 'N/A'}\nPhone: {target_phone or 'N/A'}",
                        "visibility_score": visibility_score,
                        "competitors": comp_text,
                        "sample_content": full_ai,
                    })

            except Exception as e:
                st.error(f"Error: {e}")

if st.session_state.results_ready and st.session_state.df is not None:
    st.metric("Visibility Score", f"{st.session_state.visibility_score}%")

    st.subheader("Top 5 Local Results")
    st.dataframe(st.session_state.df, use_container_width=True)

    if st.session_state.target_found and st.session_state.target_lat:
        st.success("Business found — Auto-captured NAP:")
        st.code(st.session_state.auto_nap)
        name_encoded = quote(business_name)
        maps_url = f"https://www.google.com/maps/place/{name_encoded}/@{st.session_state.target_lat},{st.session_state.target_lon},15z"
        st.link_button(f"GO to {business_name}", maps_url, type="primary")
    else:
        st.warning(f"**{business_name}** was not found in the top local results for this keyword. It may still have a Google Business Profile but is not ranking for this search.")

    map_df = st.session_state.df.dropna(subset=["Latitude", "Longitude"])
    if not map_df.empty or st.session_state.target_lat:
        center = [st.session_state.target_lat or map_df["Latitude"].mean(),
                  st.session_state.target_lon or map_df["Longitude"].mean()]
        m = folium.Map(location=center, zoom_start=13,
                       tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}", attr="Google Maps")
        for _, row in map_df.iterrows():
            if normalize(business_name) not in normalize(str(row["Title"])):
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

    st.subheader("Top Competitors")
    st.text(st.session_state.competitors)

    st.subheader("AI Insights & Content Tools")
    st.markdown(st.session_state.sample_content)

    report = f"""AI Local Map Auditor Report
Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Business: {business_name}
Keyword: {keyword}
Location: {location_input}
Visibility Score: {st.session_state.visibility_score}%
Listed: {'Yes' if st.session_state.target_found else 'No'}
Position: {st.session_state.target_position or 'N/A'}

NAP:
{st.session_state.auto_nap}

Top 5 Local Results:
{st.session_state.df.to_string(index=False)}

Competitors:
{st.session_state.competitors}

AI Insights & Content:
{st.session_state.sample_content}
"""
    st.download_button("Download Full Report", report, file_name="local_audit_report.txt", mime="text/plain")

st.sidebar.info("Expanded original tools for local visibility, content, and recommendations.")
