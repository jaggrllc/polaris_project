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
from reportlab.lib.enums import TA_CENTER, TA_LEFT

st.set_page_config(page_title="AI Local Map Auditor", page_icon="🗺️", layout="wide")

st.title("🗺️ AI Local Map Auditor")
st.caption("Local visibility check + owner-friendly PDF reports. Original tool.")

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

# Google brand colors
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
        with st.spinner("Running audit and creating PDF report..."):
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

def format_address(addr):
    """Stack street over city/state/zip when possible."""
    if not addr or not isinstance(addr, str):
        return ""
    addr = addr.strip()
    # Simple split on comma (most common format)
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) >= 2:
        street = truncate(parts[0], 28)
        rest = ", ".join(parts[1:])
        rest = truncate(rest, 28)
        return f"{street}<br/>{rest}"
    return truncate(addr, 30)

def create_pdf_report():
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []

    # Logo
    try:
        logo = Image("Jaguar-Group-LLC.png", width=1*inch, height=1*inch)
        logo.hAlign = 'CENTER'
        story.append(logo)
        story.append(Spacer(1, 0.2*inch))
    except Exception:
        story.append(Paragraph("<b>Jaguar Group LLC</b>", styles['Title']))

    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        textColor=GOOGLE_BLUE,
        alignment=TA_CENTER,
        fontSize=18,
        spaceAfter=12
    )
    story.append(Paragraph(f"Local Visibility Report for {business_name}", title_style))
    story.append(Spacer(1, 0.1*inch))

    guide_style = ParagraphStyle(
        'Guide',
        parent=styles['Normal'],
        textColor=GOOGLE_RED,
        fontSize=11,
        leading=14,
        spaceAfter=6
    )
    story.append(Paragraph("<b>HOW TO ADD THIS TO YOUR GOOGLE BUSINESS PROFILE</b>", guide_style))
    guide_text = """
    1. Open Google Maps on your phone or computer.<br/>
    2. Search for your business name.<br/>
    3. Tap or click on your business.<br/>
    4. Look for “Edit profile” or “Manage this business” and open it.<br/>
    5. Copy the New Business Description below and paste it into the description box.<br/>
    6. To add a post: look for “Add update” or “Create post”, then copy one of the three posts and paste it.<br/>
    7. Add any suggested categories if you see the option.<br/>
    8. Take or upload photos based on the photo ideas.<br/>
    9. When customers leave reviews, use the sample replies as a guide.
    """
    story.append(Paragraph(guide_text, styles['Normal']))
    story.append(Spacer(1, 0.2*inch))

    # Summary table
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
    story.append(Paragraph("<b>Report Summary</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_GREEN)))
    story.append(summary_table)
    story.append(Spacer(1, 0.2*inch))

    # NAP
    story.append(Paragraph("<b>Business Details (NAP)</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_YELLOW)))
    story.append(Paragraph(st.session_state.auto_nap.replace("\n", "<br/>"), styles['Normal']))
    story.append(Spacer(1, 0.15*inch))

    # Top results table with truncated titles and stacked addresses
    if st.session_state.df is not None and not st.session_state.df.empty:
        story.append(Paragraph("<b>Top 5 Local Results</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_RED)))

        # Build table with Paragraphs for multi-line support
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

    # Competitors
    story.append(Paragraph("<b>Top Competitors</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_GREEN)))
    story.append(Paragraph(st.session_state.competitors.replace("\n", "<br/>"), styles['Normal']))
    story.append(Spacer(1, 0.15*inch))

    # AI Content
    story.append(Paragraph("<b>Ready-to-Use Content</b>", ParagraphStyle('H2', parent=styles['Heading2'], textColor=GOOGLE_BLUE)))
    content_para = Paragraph(st.session_state.sample_content.replace("\n", "<br/>"), styles['Normal'])
    story.append(content_para)

    doc.build(story)
    buffer.seek(0)
    return buffer

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
        label="Download PDF Report",
        data=pdf_buffer,
        file_name=f"{business_name.replace(' ', '_')}_Report.pdf",
        mime="application/pdf"
    )

st.sidebar.info("PDF tables now trim long titles and stack street address over city/state/zip.")
