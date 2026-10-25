import streamlit as st
import urllib.parse

st.set_page_config(page_title="AI Local Map Auditor Tool", layout="wide")

st.title("🗺️ AI Local Map Auditor Tool")
st.write("Generate highly targeted Google Maps scan links and tailored outreach scripts instantly without any complex setups.")

# Main Interface Inputs
col1, col2 = st.columns(2)
with col1:
    industry = st.text_input("Target Industry Group (e.g., Plumber, Roofer)", value="Plumber")
with col2:
    city = st.text_input("Target City Search Market", value="Seattle")

if st.button("🚀 Generate Map Scan Profile", type="primary"):
    # Combine industry and city into a clean search string
    search_query = f"{industry} {city}"
    encoded_query = urllib.parse.quote_plus(search_query)
    
    # ADDED THE CRUCIAL FORWARD SLASH PATHWAY (com/maps) TO PREVENT WEB LINK BLEEDING
    google_maps_url = f"https://google.com{encoded_query}"
    
    st.markdown("---")
    st.subheader("🎯 Step 1: Analyze Your Market Openings")
    st.write("Click the button below to open Google Maps for your target town. Look at the businesses on the left side and isolate profiles missing website links or with low review scores:")
    
    # Large visual action link button
    st.link_button(f"🌐 Open Google Maps for {industry} in {city}", google_maps_url)
    
    st.markdown("---")
    st.subheader("💬 Step 2: Your Conversion Outreach Scripts")
    st.write("Once you spot an unoptimized business on the map, copy one of these fine-tuned, proven SMS scripts to close them as a marketing client:")
    
    # High-converting template fields
    tab1, tab2 = st.tabs(["❌ Missing Website Campaign", "⭐ Low Rating Campaign"])
    
    with tab1:
        st.write("**Best for profiles completely missing an online website button:**")
        st.code(
            f"Hey [Owner Name], noticed your business on Maps is missing a website link. "
            f"Did you know Google filters out profiles without links? Do you have an active site? I help locals fix this fast.", 
            language="text"
        )
        
    with tab2:
        st.write("**Best for profiles sitting under a 4.3 star average score:**")
        st.code(
            f"Hi [Owner Name], found your map listing while looking for {industry} in {city}. "
            f"Your team has great reviews, but your map visibility is dropping due to review velocity. "
            f"Can I text you a quick tool we use to fix this?", 
            language="text"
        )
