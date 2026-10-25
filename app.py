import streamlit as st
import requests
import csv
import io

st.set_page_config(page_title="AI Local Map Auditor", layout="wide")

st.title("🗺️ AI Local Map Auditor Dashboard")
st.write("Extract unoptimized business leads straight from Google Maps and instantly generate SMS campaigns.")

# Sidebar Configuration for Credentials
st.sidebar.header("🔑 Authentication Setup")
serp_key = st.sidebar.text_input("SerpAPI Secret Key", type="password")
openai_key = st.sidebar.text_input("OpenAI Secret Key", type="password")

# Main Interface Inputs
col1, col2 = st.columns(2)
with col1:
    industry = st.text_input("Target Industry Group", value="Plumber")
with col2:
    city = st.text_input("Target City Search Market", value="Seattle")

if st.button("🚀 Execute Market Scan", type="primary"):
    if not serp_key or not openai_key:
        st.error("Please fill in your API keys in the sidebar configuration.")
    else:
        with st.spinner("Mining Google Maps and compiling market analysis... Please wait..."):
            # Fetch Map Data
            url = "https://serpapi.com"
            params = {"engine": "google_maps", "q": f"{industry} in {city}", "api_key": serp_key}
            response = requests.get(url, params=params).json()
            leads = response.get("local_results", [])
            
            if not leads:
                st.warning("No listings discovered for this parameters combination.")
            else:
                csv_buffer = io.StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(["Name", "Phone", "Rating", "Reviews", "Issue", "SMS Text Message"])
                
                valid_leads_count = 0
                
                for business in leads:
                    name = business.get("title")
                    phone = business.get("phone", "N/A")
                    rating = business.get("rating", 0)
                    reviews = business.get("reviews", 0)
                    website = business.get("website")
                    
                    is_vulnerable = False
                    gap_reason = ""
                    
                    if not website:
                        is_vulnerable = True
                        gap_reason = "Missing Website"
                    elif rating < 4.3:
                        is_vulnerable = True
                        gap_reason = f"Low Rating ({rating}⭐)"
                    elif reviews < 15:
                        is_vulnerable = True
                        gap_reason = f"Low Trust Metrics ({reviews} reviews)"
                        
                    if is_vulnerable and phone != "N/A":
                        # Fetch AI Copy
                        ai_url = "https://openai.com"
                        headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
                        prompt = f"Write a casual SMS to a business named '{name}'. Keep it under 160 characters. Mention they are: {gap_reason}. Ask if they want a fix."
                        data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.6}
                        
                        try:
                            res = requests.post(ai_url, headers=headers, json=data).json()
                            sms_text = res['choices']['message']['content'].strip()
                        except:
                            sms_text = "API limit hit or error."
                            
                        # Display output directly to dashboard layout
                        with st.expander(f"🚨 Lead: {name} | Phone: {phone} | Trigger: {gap_reason}"):
                            st.subheader("Generated Automated SMS Pitch:")
                            st.info(sms_text)
                            
                        writer.writerow([name, phone, rating, reviews, gap_reason, sms_text])
                        valid_leads_count += 1
                
                # Global file export options
                if valid_leads_count > 0:
                    st.success(f"Processing complete! {valid_leads_count} actionable leads discovered.")
                    st.download_button(
                        label="📥 Download Extracted Spreadsheet Leads (.CSV)",
                        data=csv_buffer.getvalue(),
                        file_name=f"maps_audit_{city.lower()}.csv",
                        mime="text/csv"
                    )
