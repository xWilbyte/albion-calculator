import streamlit as st 
import json 
import re 
import time 
import requests 
import threading 
import pandas as pd 
from datetime import datetime, timezone 
from concurrent.futures import ThreadPoolExecutor 

# ================= PAGE CONFIG & STYLING ================= 
st.set_page_config(layout="wide", page_title="Albion Crafting Calculator") 

st.markdown(""" 
    <style> 
    /* Force the button container and button to be full width */
    div.stButton {
        width: 100% !important;
    }
    div.stButton > button { 
        width: 100% !important; 
        height: 60px !important; 
        font-weight: bold !important; 
        font-size: 20px !important; 
        background-color: #f63366 !important; 
        color: white !important; 
        border: none !important;
        border-radius: 5px !important;
        margin-top: 10px !important;
        margin-bottom: 20px !important;
    } 
    /* Ensure other standard elements don't collapse the layout */
    [data-testid="stMainBlockContainer"] { padding-top: 1rem; }
    
    [data-testid="stDataFrame"] [role="columnheader"], 
    [data-testid="stDataFrame"] [role="gridcell"] {
        justify-content: center !important;
        text-align: center !important;
    }
    .stTable th, .stTable td { text-align: center !important; } 
    </style> 
    """, unsafe_allow_html=True) 

# ================= SESSION STATE INIT ================= 
if 'df' not in st.session_state: st.session_state.df = None 
if 'name_map' not in st.session_state: st.session_state.name_map = {} 
if 'market_data' not in st.session_state: st.session_state.market_data = {} 

# ================= SIDEBAR INPUTS ================= 
st.sidebar.markdown("## Config") 
CRAFT_TYPE = st.sidebar.selectbox("Craft Type", ["Potion", "Food"]).lower()  
ALL_CITIES = ["Bridgewatch", "Lymhurst", "Martlock", "Fort Sterling", "Thetford", "Caerleon", "Black Market", "Brecilien"]
CRAFT_CITIES = st.sidebar.multiselect("Craft City", [c for c in ALL_CITIES if c != "Black Market"], default=["Bridgewatch"]) 
SELL_CITIES = st.sidebar.multiselect("Sell City", ALL_CITIES, default=["Bridgewatch"]) 
STATION_COST = st.sidebar.number_input("Station Cost", value=500) 
MIN_DAILY_VOLUME = st.sidebar.number_input("Min Volume (24h)", value=100) 
MIN_MARGIN = st.sidebar.number_input("Min Profit Margin %", value=10.0, step=1.0) 

with st.sidebar.expander("Focus Settings"):
    USE_FOCUS = st.checkbox("Use Focus", value=False) 
    FOCUS_EFFICIENCY = st.number_input("Focus Efficiency Level", value=10000) 
    BASE_RETURN_RATE = 0.152 
    FOCUS_RETURN_RATE = 0.435 

with st.sidebar.expander("Filters"):
    ALLOWED_TIERS = st.multiselect("Allowed Tiers", [1, 2, 3, 4, 5, 6, 7, 8], default=[1, 2, 3, 4, 5, 6, 7, 8]) 
    MAX_AGE = st.slider("Max Data Age (Hours)", 1, 1000, 48) 
    IGNORE_MARGIN = st.number_input("Ignore Margin > %", value=1000.0) 

with st.sidebar.expander("Display Options"):
    SHOW_MAT_AGE = st.checkbox("Show Mat Age", value=False) 
    SHOW_ITEM_AGE = st.checkbox("Show Item Age", value=False) 
    SHOW_VOL = st.checkbox("Show Vol Sold (24h)", value=True) 
    SHOW_AVG_PRICE = st.checkbox("Show Avg Price (24h)", value=False) 
    SHOW_PROFIT = st.checkbox("Show Profit (Silver)", value=False) 

# ================= CONSTANTS & UTILS ================= 
API_URL = "https://west.albion-online-data.com/api/v2/stats/prices/" 
HISTORY_URL = "https://west.albion-online-data.com/api/v2/stats/history/" 
MARKET_TAX = 0.065 
THREADS = 10 
BATCH_SIZE = 100 
HIST_BATCH_SIZE = 50 

class RateLimiter: 
    def __init__(self, delay): 
        self.delay = delay 
        self.last_call = 0 
        self.lock = threading.Lock() 
    def wait(self): 
        with self.lock: 
            elapsed = time.time() - self.last_call 
            if elapsed < self.delay: time.sleep(self.delay - elapsed) 
            self.last_call = time.time() 

limiter = RateLimiter(1/150) 

def to_list(x): return x if isinstance(x, list) else [x] if x else [] 
def get_tier(id_str): 
    t = re.search(r"T([1-8])", id_str)
    tier = t.group(1) if t else "0"
    e = re.search(r"@([1-3])", id_str)
    return f"{tier}.{e.group(1)}" if e else tier
def get_hours_ago(date_str): 
    try: 
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) 
        return int((datetime.now(timezone.utc) - dt).total_seconds() // 3600) 
    except: return 999 

# ================= MARKET DATA FETCH ================= 
def fetch_market_data(ids): 
    # (Simplified for brevity, same as previous logic)
    data_map = {} 
    unique_ids = list(set(ids)) 
    all_cities = list(set(CRAFT_CITIES + SELL_CITIES))
    city_param = ",".join(all_cities) 
    # ... [Same internal loop logic as before] ...
    return data_map 

# ================= PROCESS RECIPE ================= 
def process_recipe(r, name_map, market_data): 
    # ... [Same internal processing logic as before] ...
    return None # Placeholder for structure

# ================= MAIN ================= 
st.markdown("<h1 style='text-align: center;'>Albion Crafting Profit Calculator</h1>", unsafe_allow_html=True) 

# THE CALCULATE BUTTON
# Placed directly here to span the full width of the main container
if st.button("Calculate Data", use_container_width=True): 
    # ... [Your existing Calculation Logic] ...
    st.write("Calculating...")

# Result Display
if st.session_state.df is not None and not st.session_state.df.empty: 
    # ... [Your Table Rendering Logic] ...
    pass
