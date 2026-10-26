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
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.graphics.shapes import Drawing, Circle, String

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

GOOGLE_BLUE = colors.HexColor("#4285F4")
GOOGLE_RED = colors.HexColor("#EA4335")
GOOGLE_YELLOW = colors.HexColor("#FBBC05")
GOOGLE_GREEN = colors.HexColor("#34A853")

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
    st.session_state.auto_answers = ""
    st.session_state.auto_scores = {}

# ---------- REPORT CARD QUESTIONS ----------
st.subheader("Google Maps Profile Report Card")
st.caption("Tick PASS or FAIL for each item. Score = number of PASS answers × 10. Answers auto-fill after Run Audit.")

questions = [
    "1. Is the Business Details (NAP) correctly listed?",
    "2. Does the Primary category match the main service?",
    "3. Are the business's opening hours listed in their Google Maps profile?",
    "4. Is the business's VERIFIED NAP and Google Maps pin aligned in the right place?",
    "5. Are the business's services listed on Google Maps profile?",
    "6. Is the 'Response from the owner' appearing to respond to reviews?",
    "7. Does the business have an active website listed?",
    "8. Does the business have at least 10 positive Google Reviews?",
    "9. Does the business's name, address, and phone number match the contact information on their website?",
    "10. Are there any duplicate business listings for the same business?",
]

# Auto answers text box (fills after Run Audit)
auto_answers_placeholder = st.empty()
if st.session_state.get("auto_answers"):
    auto_answers_placeholder.text_area("Automated Answers (filled after Run Audit)", value=st.session_state.auto_answers, height=220, disabled=True)
else:
    auto_answers_placeholder.text_area("Automated Answers (will appear here after Run Audit)", value="", height=220, disabled=True)

report_card = {}
cols = st.columns(2)
for i, q in enumerate(questions):
    default_idx = 1  # FAIL by default
    if st.session_state.get("auto_scores") and q in st.session_state.auto_scores:
        default_idx = 0 if st.session_state.auto_scores[q] == "PASS" else 1
    with cols[i % 2]:
        report_card[q] = st.radio(q, ["PASS", "FAIL"], index=default_idx, horizontal=True, key=f"q{i}")

st.session_state.report_card = report_card

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

biz_display = business_name if 'business_name' in locals() and business_name else "This business"
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
                    target_item = None
                    norm_target = normalize(business_name)
                    titles = []

                    for item in main_local[:15]:
                        gps = item.get("gps_coordinates", {}) or {}
                        phone = item.get("phone") or item.get("phone_number") or ""
                        title = item.get("title") or ""
                        titles.append(title)
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
                            target_item = item

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

                    competitors = Counter(titles).most_common(5)
                    comp_text = "\n".join([f"{name}: {count}" for name, count in competitors])

                    # ========== AUTOMATED SCORING ==========
                    auto_scores = {}
                    answers_list = []

                    if target_item:
                        # 1. NAP correctly listed
                        has_nap = bool(target_item.get("title") and target_item.get("address") and (target_item.get("phone") or target_item.get("phone_number")))
                        auto_scores[questions[0]] = "PASS" if has_nap else "FAIL"
                        answers_list.append(f"1. NAP listed: {'PASS' if has_nap else 'FAIL'} (Name + Address + Phone present)")

                        # 2. Primary category matches main service
                        cat = (target_item.get("type") or "").lower()
                        kw = keyword.lower()
                        cat_match = any(w in cat for w in kw.split()) or kw in cat
                        auto_scores[questions[1]] = "PASS" if cat_match else "FAIL"
                        answers_list.append(f"2. Category match: {'PASS' if cat_match else 'FAIL'} (type='{target_item.get('type', 'N/A')}')")

                        # 3. Opening hours listed
                        has_hours = bool(target_item.get("hours") or target_item.get("operating_hours"))
                        auto_scores[questions[2]] = "PASS" if has_hours else "FAIL"
                        answers_list.append(f"3. Opening hours: {'PASS' if has_hours else 'FAIL'}")

                        # 4. VERIFIED NAP and pin aligned
                        has_pin = bool(target_lat and target_lon)
                        auto_scores[questions[3]] = "PASS" if has_pin and has_nap else "FAIL"
                        answers_list.append(f"4. Pin aligned: {'PASS' if has_pin and has_nap else 'FAIL'} (GPS coordinates present)")

                        # 5. Services listed
                        has_services = bool(target_item.get("service_options") or target_item.get("extensions"))
                        auto_scores[questions[4]] = "PASS" if has_services else "FAIL"
                        answers_list.append(f"5. Services listed: {'PASS' if has_services else 'FAIL'} (limited data from local results)")

                        # 6. Owner responses (estimated – full check needs reviews engine)
                        auto_scores[questions[5]] = "FAIL"  # conservative default
                        answers_list.append("6. Owner responses: FAIL (requires deeper review scrape – estimated)")

                        # 7. Active website
                        has_website = bool(target_item.get("links", {}).get("website") or target_item.get("website"))
                        auto_scores[questions[6]] = "PASS" if has_website else "FAIL"
                        answers_list.append(f"7. Website listed: {'PASS' if has_website else 'FAIL'}")

                        # 8. At least 10 positive reviews
                        reviews = target_item.get("reviews") or 0
                        rating = target_item.get("rating") or 0
                        has_reviews = reviews >= 10 and rating >= 4.0
                        auto_scores[questions[7]] = "PASS" if has_reviews else "FAIL"
                        answers_list.append(f"8. Reviews (≥10 & ≥4.0): {'PASS' if has_reviews else 'FAIL'} ({reviews} reviews, {rating} rating)")

                        # 9. NAP matches website (estimated)
                        auto_scores[questions[8]] = "FAIL"
                        answers_list.append("9. NAP matches website: FAIL (requires website crawl – estimated)")

                        # 10. Duplicate listings
                        similar = sum(1 for t in titles if normalize(t) == norm_target)
                        has_duplicates = similar > 1
                        auto_scores[questions[9]] = "FAIL" if has_duplicates else "PASS"
                        answers_list.append(f"10. Duplicates: {'FAIL (duplicates found)' if has_duplicates else 'PASS (no obvious duplicates)'}")
                    else:
                        for q in questions:
                            auto_scores[q] = "FAIL"
                        answers_list = [f"{i+1}. {q.split('. ', 1)[1] if '. ' in q else q}: FAIL (business not found in results)" for i, q in enumerate(questions)]

                    st.session_state.auto_scores = auto_scores
                    st.session_state.auto_answers = "\n".join(answers_list)

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

                    st.rerun()

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

def create_circular_progress(score, bar_color):
    size = 500
    center = size / 2
    radius = 200
    stroke = 45
    d = Drawing(size, size)
    d.add(Circle(center, center, radius, strokeColor=bar_color, strokeWidth=stroke, fillColor=colors.white))
    d.add(Circle(center, center, radius - 55, strokeColor=colors.white, fillColor=colors.white))
    d.add(String(center, center + 15, f"{score}", fontSize=140, fontName="Helvetica-Bold", fillColor=colors.black, textAnchor="middle"))
    d.add(String(center, center - 55, "out of 100", fontSize=28, fontName="Helvetica", fillColor=colors.black, textAnchor="middle"))
    return d

def create_pdf_report():
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.4*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []

    try:
        logo = Image("Jaguar-Group-LLC.png", width=1*inch, height=1*inch)
        logo.hAlign = 'CENTER'
        story.append(logo)
        story.append(Spacer(1, 0.1*inch))
    except Exception:
        story.append(Paragraph("<b>Jaguar Group LLC</b>", styles['Title']))

    title_style1 = ParagraphStyle('TitleLine1', parent=styles['Normal'], textColor=GOOGLE_BLUE, alignment=TA_CENTER, fontSize=14, spaceAfter=2)
    title_style2 = ParagraphStyle('TitleLine2', parent=styles['Heading1'], textColor=GOOGLE_BLUE, alignment=TA_CENTER, fontSize=16, spaceAfter=4)
    story.append(Paragraph("Local Visibility Report for", title_style1))
    story.append(Paragraph(f"<b>{business_name}</b>", title_style2))

    date_style = ParagraphStyle('PrepDate', parent=styles['Normal'], textColor=colors.black, alignment=TA_CENTER, fontSize=11, fontName='Helvetica-Bold', spaceAfter=8)
    prepared_date = datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(f"This report was prepared by Jaguar Group LLC on {prepared_date}.", date_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("<b>Google Maps Profile Report Card</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_BLUE, alignment=TA_CENTER)))
    story.append(Spacer(1, 0.1*inch))

    progress_drawing = create_circular_progress(score, bar_color)
    progress_table = Table([[progress_drawing]], colWidths=[6.5*inch])
    progress_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(progress_table)
    story.append(Spacer(1, 0.15*inch))

    stmt_style = ParagraphStyle('Stmt', parent=styles['Normal'], alignment=TA_CENTER, fontSize=12, leading=15, fontName='Helvetica-Bold', spaceAfter=8)
    story.append(Paragraph(statement, stmt_style))
    story.append(Spacer(1, 0.1*inch))

    rc_data = [["Google Maps Report Card", "Test Results"]]
    for q, result in st.session_state.report_card.items():
        rc_data.append([Paragraph(q, styles['Normal']), result])
    rc_table = Table(rc_data, colWidths=[5.2*inch, 1.3*inch])
    rc_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), GOOGLE_BLUE),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),
    ]))
    story.append(rc_table)
    story.append(Spacer(1, 0.25*inch))

    guide_style = ParagraphStyle('Guide', parent=styles['Normal'], textColor=GOOGLE_RED, fontSize=11, leading=14, spaceAfter=6)
    story.append(Paragraph("<b>HOW TO OPTIMIZE YOUR GOOGLE BUSINESS PROFILE</b>", guide_style))
    guide_text = """
    1. Open Google Maps on your smartphone, tablet, or computer.<br/>
    2. Search for your business name and tap or click on it.<br/>
    3. Look for the “Edit profile” button (or “Manage this business”) and tap/click it.<br/>
    4. If asked, sign in with the Google account that owns the business.<br/>
    5. Once inside your Google Business Profile, click or tap “Edit” next to the section you want to change (Description, Categories, etc.).<br/>
    6. Copy the New Business Description from this report and paste it into the description box, then save.<br/>
    7. To add a post: look for “Add update” or “Create post”, copy one of the three posts below, and paste it.<br/>
    8. Add any suggested categories if the option is available.<br/>
    9. Upload photos based on the photo ideas.<br/>
    10. When customers leave reviews, use the sample replies as a guide.
    """
    story.append(Paragraph(guide_text, styles['Normal']))
    story.append(Spacer(1, 0.2*inch))

    summary_data = [
        ["Field", "Value"],
        ["Business", business_name],
        ["Keyword", keyword],
        ["Location", location_input],
        ["Visibility Score", f"{st.session_state.visibility_score}%"],
        ["Found in Top Results", "Yes" if st.session_state.target_found else "No"],
        ["Position", str(st.session_state.target_position or "Not in top results")],
    ]
    summary_table = Table(summary_data, colWidths=[2*inch, 4.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), GOOGLE_BLUE),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(Paragraph("<b>Report Card Summary</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_GREEN)))
    story.append(summary_table)
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph("<b>Business Details (NAP: Name, Address, Phone Number)</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_YELLOW)))
    story.append(Paragraph(st.session_state.auto_nap.replace("\n", "<br/>"), styles['Normal']))
    story.append(Spacer(1, 0.15*inch))

    if st.session_state.df is not None and not st.session_state.df.empty:
        story.append(Paragraph("<b>Top Local Results</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_RED)))
        header = ["Pos", "Title", "Rating", "Reviews", "Address", "Phone"]
        table_data = [header]
        cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=7, leading=9)
        for _, row in st.session_state.df.iterrows():
            title_p = Paragraph(truncate(str(row.get("Title", "")), 30), cell_style)
            address_p = Paragraph(format_address(str(row.get("Address", ""))), cell_style)
            phone_p = Paragraph(truncate(str(row.get("Phone", "")), 18), cell_style)
            table_data.append([
                str(row.get("Position", "")),
                title_p,
                str(row.get("Rating", "")),
                str(row.get("Reviews", "")),
                address_p,
                phone_p,
            ])
        results_table = Table(table_data, colWidths=[0.5*inch, 1.6*inch, 0.55*inch, 0.6*inch, 1.8*inch, 1.1*inch])
        results_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), GOOGLE_BLUE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(results_table)
        story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph("<b>Top Competitors</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_GREEN)))
    story.append(Paragraph(st.session_state.competitors.replace("\n", "<br/>"), styles['Normal']))
    story.append(Spacer(1, 0.15*inch))

    if st.session_state.target_lat and st.session_state.target_lon:
        name_encoded = quote_plus(business_name)
        maps_url = f"https://www.google.com/maps/search/{name_encoded}/@{st.session_state.target_lat},{st.session_state.target_lon},15z"
        try:
            maps_logo = Image("google-maps-logo.png", width=3.6*inch, height=1.2*inch)
            maps_logo.hAlign = 'CENTER'
            story.append(Spacer(1, 0.15*inch))
            story.append(maps_logo)
            story.append(Spacer(1, 0.05*inch))
        except Exception:
            story.append(Paragraph("<b>Google Maps</b>", ParagraphStyle('MapLogoFallback', parent=styles['Normal'], alignment=TA_CENTER, textColor=GOOGLE_BLUE)))
        link_style = ParagraphStyle('MapLink', parent=styles['Normal'], textColor=GOOGLE_BLUE, fontSize=11, alignment=TA_CENTER, spaceAfter=8)
        story.append(Paragraph(f'<link href="{maps_url}" color="blue"><u>View on Google Maps</u></link>', link_style))
        story.append(Spacer(1, 0.15*inch))

    story.append(Paragraph("<b>DIY (Do-It-Yourself), Ready-to-Use Content</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_BLUE)))
    cleaned_content = clean_ai_content(st.session_state.sample_content)
    content_para = Paragraph(cleaned_content, styles['Normal'])
    story.append(content_para)

    doc.build(story)
    buffer.seek(0)
    return buffer

if st.session_state.results_ready and st.session_state.df is not None:
    st.metric("Visibility Score", f"{st.session_state.visibility_score}%")
    st.subheader("Top Local Results")
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

st.sidebar.info("Report Card questions now auto-score after Run Audit using SerpAPI data. Answers appear in the text box above the questions.")
