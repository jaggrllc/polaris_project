import streamlit as st
import pandas as pd
import serpapi
from openai import OpenAI
import folium
from streamlit_folium import st_folium
from datetime import datetime
from collections import Counter
from urllib.parse import quote_plus
import re

st.set_page_config(page_title="AI Local Map Auditor", page_icon="🗺️", layout="wide")

st.title("🗺️ AI Local Map Auditor")
st.caption("Local visibility check + ready-to-use Google Business Profile content. Original tool.")

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
        with st.spinner("Running audit and creating owner-friendly content..."):
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
                    prompt = f"""You are helping a local business owner who is not very comfortable with computers.
Business: {business_name}
Keyword: {keyword}
Location: {location_input}
Found in Google results: {target_found}
Position: {target_position}
Top results:
{summary}
Competitors:
{comp_text}

Write everything in simple, everyday language. Use short sentences.

Create these sections:

1. ACTION PLAN
5-7 easy steps the owner can take.

2. NEW BUSINESS DESCRIPTION
A short description (under 750 characters) they can copy and paste into their Google Business Profile.

3. THREE READY-TO-POST UPDATES
Three short posts they can add to their Google Business Profile. Label them clearly (Post 1, Post 2, Post 3).

4. SUGGESTED CATEGORIES
Primary category and a few extra ones to add.

5. PHOTO IDEAS
5 simple photo ideas.

6. HOW TO REPLY TO REVIEWS
One sample reply for a good review and one for a so-so review.

7. EXTRA KEYWORDS
A few related words or phrases they should use.

Keep it friendly and easy to follow. Do not invent facts about the business."""

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

        name_encoded = quote_plus(business_name)
        maps_url = (
            f"https://www.google.com/maps/search/{name_encoded}/"
            f"@{st.session_state.target_lat},{st.session_state.target_lon},15z"
        )
        st.link_button(f"GO to {business_name}", maps_url, type="primary")
        st.caption(f"URL: {maps_url}")
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

    st.subheader("Owner-Friendly Content (Copy and Paste)")
    st.info("The sections below are written in simple language so the business owner can copy and paste them into their Google Business Profile.")
    st.markdown(st.session_state.sample_content)

    # Owner-friendly report with guide at the top
    how_to_guide = """HOW TO ADD THIS TO YOUR GOOGLE BUSINESS PROFILE
================================================

This report gives you ready-to-use words you can copy and paste.

Follow these simple steps:

1. Open Google Maps on your phone or computer.
2. Search for your business name.
3. Tap or click on your business.
4. Look for “Edit profile” or “Manage this business” and open it.
5. Copy the New Business Description from this report and paste it into the description box.
6. To add a post: look for “Add update” or “Create post”, then copy one of the three posts below and paste it.
7. Add any suggested categories if you see the option.
8. Take or upload photos based on the photo ideas.
9. When customers leave reviews, use the sample replies as a guide.

You can do these steps one at a time. You do not have to finish everything in one sitting.

================================================
"""

    report = f"""{how_to_guide}
LOCAL VISIBILITY REPORT FOR {business_name.upper()}
Date: {datetime.now().strftime('%B %d, %Y')}
Keyword searched: {keyword}
Location: {location_input}
Visibility Score: {st.session_state.visibility_score}%
Found in top results: {'Yes' if st.session_state.target_found else 'No'}
Position: {st.session_state.target_position or 'Not in top results'}

BUSINESS DETAILS
{st.session_state.auto_nap}

TOP 5 LOCAL RESULTS
{st.session_state.df.to_string(index=False)}

TOP COMPETITORS
{st.session_state.competitors}

READY-TO-USE CONTENT
{st.session_state.sample_content}

================================================
End of report. You can print this or email it to yourself.
"""
    st.download_button("Download Owner-Friendly Report", report, file_name=f"{business_name.replace(' ', '_')}_report.txt", mime="text/plain")

st.sidebar.info("The downloaded report now includes a simple step-by-step guide at the top so non-technical owners can follow along.")
