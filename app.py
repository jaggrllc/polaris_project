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
from io import BytesIO
from weasyprint import HTML

st.set_page_config(page_title="AI Local Map Auditor", page_icon="🗺️", layout="wide")

st.title("🗺️ AI Local Map Auditor")
st.caption("Local visibility check + Report Card with Circular Progress Bar. Original tool.")

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

def truncate(text, length=30):
    if not text or not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "..."

def get_current_season():
    month = datetime.now().month
    if month in (12, 1, 2):
        return "Winter"
    elif month in (3, 4, 5):
        return "Spring"
    elif month in (6, 7, 8):
        return "Summer"
    else:
        return "Fall"

def clean_ai_content(text):
    """Clean AI content while preserving icons under post headings."""
    if not text:
        return ""
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'(?i)^h[1-6]\.?\s*', '', text, flags=re.MULTILINE)
    replacements = {
        r'(?i)1\.?\s*ACTION PLAN': '1. ACTION PLAN',
        r'(?i)2\.?\s*NEW BUSINESS DESCRIPTION': '2. NEW BUSINESS DESCRIPTION',
        r'(?i)3\.?\s*THREE READY-TO-POST UPDATES': '3. THREE READY-TO-POST UPDATES',
        r'(?i)4\.?\s*SUGGESTED CATEGORIES': '4. SUGGESTED CATEGORIES',
        r'(?i)5\.?\s*PHOTO IDEAS': '5. PHOTO IDEAS',
        r'(?i)6\.?\s*HOW TO REPLY TO REVIEWS': '6. HOW TO REPLY TO REVIEWS',
        r'(?i)7\.?\s*EXTRA KEYWORDS': '7. EXTRA KEYWORDS',
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^[1-7]\.\s+(ACTION PLAN|NEW BUSINESS DESCRIPTION|THREE READY-TO-POST UPDATES|SUGGESTED CATEGORIES|PHOTO IDEAS|HOW TO REPLY TO REVIEWS|EXTRA KEYWORDS)', stripped, re.I):
            cleaned_lines.append(stripped)
        elif re.match(r'(?i)Post\s*[123]\s*:', stripped) or 'Fall Clean-Up' in stripped or 'Clean-Up' in stripped:
            cleaned_lines.append(line)
        elif re.match(r'^\d+\.\s+', stripped) and not any(x in stripped.lower() for x in ['post ', 'fall', 'clean-up', 'winter', 'spring', 'summer']):
            cleaned_lines.append('★ ' + re.sub(r'^\d+\.\s+', '', stripped))
        else:
            cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)
    text = text.replace('**', '').replace('###', '')
    text = text.replace('\n', '<br/>')
    return text

GOOGLE_BLUE = "#4285F4"
GOOGLE_RED = "#EA4335"
GOOGLE_YELLOW = "#FBBC05"
GOOGLE_GREEN = "#34A853"

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
    st.session_state.report_card = {}
    st.session_state.owner_letter = ""

# ---------- REPORT CARD QUESTIONS ----------
st.subheader("Google Maps Profile Report Card")
st.caption("Tick PASS or FAIL for each item. Score = number of PASS answers × 10.")

questions = [
    "1. Is the business details (VERIFIED NAP: name, address, and phone number) correctly listed?",
    "2. Does the primary category match the main service?",
    "3. Are the business's opening hours listed on their Google Maps profile?",
    "4. Is the business's VERIFIED NAP and Google Maps Pin aligned in the right place?",
    "5. Are the business's services listed on their Google Maps profile?",
    "6. Is the 'Response from the owner' appearing to respond to reviews?",
    "7. Does the business have an active website listed?",
    "8. Does the business have at least 10 positive reviews on Google, Yelp, etc?",
    "9. Does the business's VERIFIED NAP match the contact information on their website?",
    "10. Are there any duplicate business listings for the same business?",
]

report_card = {}
cols = st.columns(2)
for i, q in enumerate(questions):
    with cols[i % 2]:
        report_card[q] = st.radio(q, ["PASS", "FAIL"], index=1, horizontal=True, key=f"q{i}")

st.session_state.report_card = report_card

# ---------- EDITABLE LETTER TO OWNER ----------
st.subheader("Letter to Business Owner")
st.caption("Type or paste a personal letter. It will appear at the bottom of the downloaded Report Card PDF.")
owner_letter = st.text_area(
    "Letter to the business owner",
    value=st.session_state.owner_letter,
    height=220,
    placeholder="Dear [Business Owner],\n\nThank you for the opportunity to review your Google Maps profile...\n\nBest regards,\nJaguar Group LLC",
    key="owner_letter_input"
)
st.session_state.owner_letter = owner_letter

pass_count = sum(1 for v in report_card.values() if v == "PASS")
score = pass_count * 10

if score >= 80:
    bar_color = GOOGLE_GREEN
    color_name = "Green"
elif score >= 50:
    bar_color = GOOGLE_YELLOW
    color_name = "Yellow"
else:
    bar_color = GOOGLE_RED
    color_name = "Red"

biz_display = "This business"
statement = ""
if score == 100:
    statement = f"{biz_display} has a well-optimized Google Maps profile."
elif score in (80, 90):
    statement = f"{biz_display} has a Google Maps profile that need improvement."
else:
    statement = f"{biz_display} has a poorly-optimized Google Maps profile."

st.metric("Current Report Card Score", f"{score} out of 100", help=f"Border color: {color_name}")
st.info(statement)

# ---------- MAIN AUDIT FORM ----------
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
        with st.spinner("Running audit and creating seasonal content..."):
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
                        address = item.get("address") or ""
                        rows.append({
                            "Position": item.get("position"),
                            "Title": title,
                            "Rating": item.get("rating"),
                            "Reviews": item.get("reviews"),
                            "Address": address,
                            "Phone": phone,
                            "Latitude": gps.get("latitude"),
                            "Longitude": gps.get("longitude"),
                        })
                        if norm_target and norm_target in normalize(title):
                            target_lat = gps.get("latitude")
                            target_lon = gps.get("longitude")
                            target_address = address
                            target_phone = phone

                    if business_address.strip():
                        target_address = business_address.strip()
                    if business_phone.strip():
                        target_phone = business_phone.strip()

                    df = pd.DataFrame(rows[:5])

                    # Only keep NAP-verified businesses (have both Address and Phone)
                    if not df.empty:
                        df = df[
                            df["Address"].notna() & df["Phone"].notna()
                            & (df["Address"].astype(str).str.strip() != "")
                            & (df["Phone"].astype(str).str.strip() != "")
                        ]

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

                    current_season = get_current_season()
                    summary = df.to_string(index=False)
                    prompt = f"""You are helping a local business owner who is not very comfortable with computers.
Business: {business_name}
Keyword: {keyword}
Location: {location_input}
Current Season: {current_season}
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
Create three short posts that are timely for the current season ({current_season}). 
Make them relevant to seasonal changes, weather, or customer needs right now. 
Label them clearly (Post 1, Post 2, Post 3) and include a call to action in each.
You may include simple icons or emojis under each post if they help the owner.

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

def format_address(addr):
    if not addr or not isinstance(addr, str):
        return ""
    addr = addr.strip()
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) >= 2:
        street = truncate(parts[0], 28)
        rest = ", ".join(parts[1:])
        rest = truncate(rest, 28)
        return f"{street}<br/>{rest}"
    return truncate(addr, 30)

def create_pdf_report():
    buffer = BytesIO()
    score = sum(1 for v in st.session_state.report_card.values() if v == "PASS") * 10
    bar_color = GOOGLE_GREEN if score >= 80 else GOOGLE_YELLOW if score >= 50 else GOOGLE_RED

    progress_svg = f"""
    <svg width="220" height="220" viewBox="0 0 220 220" style="margin: 10px auto; display: block;">
        <circle cx="110" cy="110" r="90" stroke="{bar_color}" stroke-width="22" fill="none"/>
        <text x="110" y="120" text-anchor="middle" font-size="52" font-weight="bold" fill="#000">{score}</text>
        <text x="110" y="150" text-anchor="middle" font-size="16" fill="#333">out of 100</text>
    </svg>
    """

    # Only NAP-verified rows
    df_nap = st.session_state.df
    results_rows = ""
    if df_nap is not None and not df_nap.empty:
        for _, row in df_nap.iterrows():
            results_rows += f"""
            <tr>
                <td>{row.get('Position','')}</td>
                <td>{truncate(str(row.get('Title','')), 30)}</td>
                <td>{row.get('Rating','')}</td>
                <td>{row.get('Reviews','')}</td>
                <td>{format_address(str(row.get('Address','')))}</td>
                <td>{truncate(str(row.get('Phone','')), 18)}</td>
            </tr>"""

    cleaned_content = clean_ai_content(st.session_state.sample_content)

    letter_html = ""
    if st.session_state.get("owner_letter") and st.session_state.owner_letter.strip():
        letter_html = f"""
        <h2 style="color:{GOOGLE_BLUE};">Letter to the Business Owner</h2>
        <p>{st.session_state.owner_letter.replace(chr(10), '<br/>')}</p>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: letter; margin: 0.5in; }}
            body {{
                font-family: "DejaVu Sans", "Noto Sans", "Noto Color Emoji", "Apple Color Emoji", "Segoe UI Emoji", sans-serif;
                font-size: 11pt;
                line-height: 1.45;
                color: #222;
            }}
            h1, h2 {{ color: {GOOGLE_BLUE}; text-align: center; }}
            table {{ width: 100%; border-collapse: collapse; margin: 14px 0; }}
            th {{ background: {GOOGLE_BLUE}; color: white; padding: 7px; text-align: left; }}
            td {{ border: 0.5px solid #ccc; padding: 6px; vertical-align: top; background: #f8f8f8; }}
            .center {{ text-align: center; }}
            .emoji {{ font-family: "Noto Color Emoji", "Apple Color Emoji", "Segoe UI Emoji", sans-serif; }}
        </style>
    </head>
    <body>
        <h1>Local Visibility Report for<br><b>{business_name}</b></h1>
        <p class="center"><b>This report was prepared by Jaguar Group LLC on {datetime.now().strftime("%B %d, %Y")}.</b></p>

        <h2>Google Maps Profile Report Card</h2>
        {progress_svg}
        <p class="center"><b>{statement}</b></p>

        <table>
            <tr><th>Google Maps Report Card</th><th>Test Results</th></tr>
            {''.join(f'<tr><td>{q}</td><td class="center">{r}</td></tr>' for q, r in st.session_state.report_card.items())}
        </table>

        <h2 style="color:{GOOGLE_RED};">HOW TO OPTIMIZE YOUR GOOGLE BUSINESS PROFILE</h2>
        <p>
        1. Open Google Maps on your smartphone, tablet, or computer.<br/>
        2. Search for your business name and tap or click on it.<br/>
        3. Look for the “Edit profile” button (or “Manage this business”) and tap/click it.<br/>
        4. If asked, sign in with the Google account that owns the business.<br/>
        5. Once inside your Google Business Profile, click or tap “Edit” next to the section you want to change.<br/>
        6. Copy the New Business Description from this report and paste it into the description box, then save.<br/>
        7. To add a post: look for “Add update” or “Create post”, copy one of the three posts below, and paste it.<br/>
        8. Add any suggested categories if the option is available.<br/>
        9. Upload photos based on the photo ideas.<br/>
        10. When customers leave reviews, use the sample replies as a guide.
        </p>

        <h2 style="color:{GOOGLE_GREEN};">Report Card Summary</h2>
        <table>
            <tr><th>Field</th><th>Value</th></tr>
            <tr><td>Business</td><td>{business_name}</td></tr>
            <tr><td>Keyword</td><td>{keyword}</td></tr>
            <tr><td>Location</td><td>{location_input}</td></tr>
            <tr><td>Visibility Score</td><td>{st.session_state.visibility_score}%</td></tr>
            <tr><td>Found in Top Results</td><td>{"Yes" if st.session_state.target_found else "No"}</td></tr>
            <tr><td>Position</td><td>{st.session_state.target_position or "Not in top results"}</td></tr>
        </table>

        <h2 style="color:{GOOGLE_YELLOW};">Business Details (NAP: Name, Address, Phone Number)</h2>
        <p>{st.session_state.auto_nap.replace(chr(10), "<br/>")}</p>

        <h2 style="color:{GOOGLE_RED};">Top Local Results (NAP Verified Only)</h2>
        <table>
            <tr><th>Pos</th><th>Title</th><th>Rating</th><th>Reviews</th><th>Address</th><th>Phone</th></tr>
            {results_rows}
        </table>

        <h2 style="color:{GOOGLE_GREEN};">Top Competitors</h2>
        <p>{st.session_state.competitors.replace(chr(10), "<br/>")}</p>

        <h2 style="color:{GOOGLE_BLUE};">DIY (Do-It-Yourself), Ready-to-Use Content</h2>
        <div class="emoji">{cleaned_content}</div>

        {letter_html}
    </body>
    </html>
    """

    HTML(string=html).write_pdf(buffer)
    buffer.seek(0)
    return buffer

# ---------- RESULTS DISPLAY + NAP WARNING ----------
if st.session_state.results_ready and st.session_state.df is not None:
    # NAP verification check
    nap_verified = bool(
        business_name
        and st.session_state.get("target_address")
        and st.session_state.get("target_phone")
        and str(st.session_state.target_address).strip() not in ("", "N/A")
        and str(st.session_state.target_phone).strip() not in ("", "N/A")
    )

    if not nap_verified:
        st.markdown(
            """
            <div id="nap-warning" style="
                position: fixed;
                top: 0; left: 0; right: 0;
                background: #ff0000;
                color: white;
                font-size: 28px;
                font-weight: bold;
                text-align: center;
                padding: 14px;
                z-index: 9999;
                animation: blink 0.6s linear infinite;
                box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            ">
                ⚠️ NOT NAP VERIFIED ⚠️
            </div>
            <style>
                @keyframes blink {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.15; }
                }
            </style>
            <script>
                setTimeout(function() {
                    var el = document.getElementById('nap-warning');
                    if (el) el.style.display = 'none';
                }, 30000);
            </script>
            """,
            unsafe_allow_html=True,
        )

    st.metric("Visibility Score", f"{st.session_state.visibility_score}%")
    st.subheader("Top Local Results (NAP Verified Only)")
    st.dataframe(st.session_state.df, use_container_width=True)

    if st.session_state.target_found and st.session_state.target_lat:
        st.success("Business found — Auto-captured NAP:")
        st.code(st.session_state.auto_nap)
        name_encoded = quote_plus(business_name)
        maps_url = f"https://www.google.com/maps/search/{name_encoded}/@{st.session_state.target_lat},{st.session_state.target_lon},15z"
        st.link_button(f"GO to {business_name}", maps_url, type="primary")
        st.caption(f"URL: {maps_url}")
    else:
        st.warning(f"**{business_name}** was not found in the top local results for this keyword.")

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

    st.subheader("Owner-Friendly Content")
    st.markdown(st.session_state.sample_content)

    pdf_buffer = create_pdf_report()
    st.download_button(
        label="Download Google Maps Profile Report Card",
        data=pdf_buffer,
        file_name=f"{business_name.replace(' ', '_')}_Report.pdf",
        mime="application/pdf"
    )

st.sidebar.info("Editable letter box added under the 10 questions. The letter appears at the bottom of the PDF.")
