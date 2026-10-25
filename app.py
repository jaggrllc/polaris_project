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
        st.error("⚠️ Please fill in both your SerpAPI and OpenAI keys in the sidebar configuration.")
    else:
        # Prepare Clean Keys
        clean_serp = serp_key.strip()
        clean_openai = openai_key.strip()
        
        with st.spinner("Running System Connection Diagnostics..."):
            # Diagnostic Step 1: Test SerpAPI Connection directly
            test_url = f"https://serpapi.com{clean_serp}"
            try:
                test_res = requests.get(test_url, timeout=10)
                if test_res.status_code == 401:
                    st.error("❌ Diagnostic Failure: Your SerpAPI Key is Invalid or has been pasted incorrectly. Please log into SerpAPI.com, copy your key fresh, and re-paste it.")
                    st.stop()
                elif test_res.status_code == 403:
                    st.error("❌ Diagnostic Failure: SerpAPI access forbidden. Your account free search quota may have run out.")
                    st.stop()
            except Exception as e:
                st.error(f"❌ Could not reach SerpAPI servers. Network issue: {e}")
                st.stop()

        with st.spinner("Mining Google Maps listings... Please wait..."):
            url = "https://serpapi.com/search.json"
            params = {"engine": "google_maps", "q": f"{industry} in {city}", "api_key": clean_serp}
            
            try:
                response = requests.get(url, params=params, timeout=15)
                response_data = response.json()
                
                # Check for explicit errors sent by SerpAPI
                if "error" in response_data:
                    st.error(f"❌ SerpAPI returned a specific blocker: {response_data['error']}")
                    st.stop()
                    
                # Look at map search health
                search_info = response_data.get("search_information", {})
                if search_info.get("local_results_state") == "Fully empty" or "Google hasn't returned any results" in str(response_data):
                    st.warning(f"⚠️ Google Maps has 0 records matching '{industry}' inside '{city}'. Try testing a broader industry keyword (like 'Roofing') or a bigger metropolitan area.")
                    st.stop()
                
                leads = response_data.get("local_results", [])
                
                if not leads:
                    st.warning("No listings found. Google Maps might not have found matching businesses in this exact area.")
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
                            # Process OpenAI Safely
                            ai_url = "https://openai.com"
                            headers = {"Authorization": f"Bearer {clean_openai}", "Content-Type": "application/json"}
                            prompt = f"Write a casual SMS text message to a local business named '{name}'. Keep it under 160 characters. Point out that their profile is showing as: {gap_reason}. Ask if they want a fast fix."
                            data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.6}
                            
                            try:
                                ai_response = requests.post(ai_url, headers=headers, json=data, timeout=10)
                                if ai_response.status_code == 401:
                                    sms_text = "[OpenAI Error: Your Secret Key is invalid or has expired.]"
                                elif ai_response.status_code == 429:
                                    sms_text = "[OpenAI Error: You have hit your limit or your prepaid $5 account balance is empty.]"
                                elif ai_response.status_code != 200:
                                    sms_text = f"[AI Engine Issue: Error Code {ai_response.status_code}]"
                                else:
                                    res_json = ai_response.json()
                                    sms_text = res_json['choices']['message']['content'].strip()
                            except:
                                sms_text = "Could not parse AI message generation."
                                
                            with st.expander(f"🚨 Lead: {name} | Phone: {phone} | Trigger: {gap_reason}"):
                                st.subheader("Generated Automated SMS Pitch:")
                                st.info(sms_text)
                                
                            writer.writerow([name, phone, rating, reviews, gap_reason, sms_text])
                            valid_leads_count += 1
                    
                    if valid_leads_count > 0:
                        st.success(f"Processing complete! {valid_leads_count} actionable leads discovered.")
                        st.download_button(
                            label="📥 Download Extracted Spreadsheet Leads (.CSV)",
                            data=csv_buffer.getvalue(),
                            file_name=f"maps_audit_{city.lower()}.csv",
                            mime="text/csv"
                        )
                    else:
                        st.info("Found local map business listings, but all profiles were already heavily optimized!")
            except Exception as e:
                st.error(f"Network Connection Interrupted: {e}")
