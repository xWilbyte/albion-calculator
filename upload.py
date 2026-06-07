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
    div[data-testid="stDataFrame"] { text-align: center !important; }
    th, td { text-align: center !important; }
    </style>
    """, unsafe_allow_html=True)

# ================= SESSION STATE INIT =================
if 'df' not in st.session_state: st.session_state.df = None
if 'name_map' not in st.session_state: st.session_state.name_map = {}
if 'market_data' not in st.session_state: st.session_state.market_data = {}

# ================= SIDEBAR INPUTS =================
st.sidebar.header("Config")
CRAFT_TYPE = st.sidebar.selectbox("Craft Type", ["Potion", "Food"]).lower() 
CRAFT_CITIES = st.sidebar.multiselect("Cities", ["Bridgewatch", "Lymhurst", "Martlock", "Fort Sterling", "Thetford", "Caerleon", "Black Market", "Brecilien"], default=["Bridgewatch"])
STATION_COST = st.sidebar.number_input("Station Cost", value=500)
MIN_DAILY_VOLUME = st.sidebar.number_input("Min Daily Volume", value=100)
MIN_MARGIN = st.sidebar.number_input("Min Margin %", value=10.0, step=1.0)
IGNORE_MARGIN = st.sidebar.number_input("Ignore Margin > %", value=1000.0)

st.sidebar.header("Focus Settings")
USE_FOCUS = st.sidebar.checkbox("Use Focus", value=False)
FOCUS_EFFICIENCY = st.sidebar.number_input("Focus Efficiency Level", value=10000)
BASE_RETURN_RATE = 0.152
FOCUS_RETURN_RATE = 0.435

st.sidebar.header("Filters")
ALLOWED_TIERS = st.sidebar.multiselect("Allowed Tiers", [1, 2, 3, 4, 5, 6, 7, 8], default=[1, 2, 3, 4, 5, 6, 7, 8])
MAX_AGE = st.sidebar.slider("Max Data Age (Hours)", 1, 1000, 72)

# ================= CONSTANTS & RATE LIMITER =================
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

# ================= UTILS =================
def to_list(x): return x if isinstance(x, list) else [x] if x else []
def get_tier(id_str):
    match = re.search(r"T([1-8])", id_str)
    return int(match.group(1)) if match else 0
def get_hours_ago(date_str):
    if date_str == "N/A": return 999
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        return int(diff.total_seconds() // 3600)
    except: return 999
def format_age(hours): return "N/A" if hours == 999 else f"{hours}h"
def get_id(x): return x.get("@uniquename") or x.get("id") if isinstance(x, dict) else None

# ================= MARKET FETCH =================
def fetch_market_data(ids):
    data_map = {} 
    unique_ids = list(set(ids))
    city_param = ",".join(CRAFT_CITIES)
    
    for i in range(0, len(unique_ids), BATCH_SIZE):
        limiter.wait()
        chunk = unique_ids[i : i + BATCH_SIZE]
        url = f"{API_URL}{','.join(chunk)}?locations={city_param}"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                for row in r.json():
                    item_id = row.get("item_id")
                    city = row.get("city")
                    price = row.get("sell_price_min", 0)
                    if item_id not in data_map: data_map[item_id] = {}
                    if city not in data_map[item_id]: data_map[item_id][city] = {'price': 0, 'date': 'N/A', 'hist_price': 0, 'volume': 0}
                    if price > 0:
                        data_map[item_id][city].update({'price': price, 'date': row.get('sell_price_min_date', 'N/A')})
        except: continue
        
    for i in range(0, len(unique_ids), HIST_BATCH_SIZE):
        limiter.wait()
        chunk = unique_ids[i : i + HIST_BATCH_SIZE]
        url = f"{HISTORY_URL}{','.join(chunk)}.json?locations={city_param}&time-scale=24"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                resp = r.json()
                if isinstance(resp, list):
                    for entry in resp:
                        city = entry.get("location")
                        if city in CRAFT_CITIES:
                            item_id = entry.get("item_id")
                            if item_id not in data_map: data_map[item_id] = {}
                            if city not in data_map[item_id]: data_map[item_id][city] = {'price': 0, 'date': 'N/A', 'hist_price': 0, 'volume': 0}
                            data_points = entry.get("data", [])
                            if data_points:
                                recent_data = data_points[-30:]
                                avg_vol = sum(d.get("item_count", 0) for d in recent_data) / len(recent_data)
                                data_map[item_id][city].update({'volume': int(avg_vol), 'hist_price': data_points[-1].get("avg_price", 0)})
        except: continue
    return data_map

# ================= PROCESS RECIPE =================
def process_recipe(r, name_map, market_data):
    best_result = None
    best_profit = -999999999
    current_return = FOCUS_RETURN_RATE if USE_FOCUS else BASE_RETURN_RATE

    for city in CRAFT_CITIES:
        out_key = r['output']
        out_data = market_data.get(out_key, {}).get(city, {})
        
        rev_price = out_data.get('price') if (out_data.get('date') != 'N/A' and get_hours_ago(out_data.get('date')) <= MAX_AGE) else out_data.get('hist_price', 0)
        if rev_price == 0: continue
        
        total_mat_cost = 0.0
        for i in r['inputs']:
            mat_data = market_data.get(i['id'], {}).get(city, {})
            price = mat_data.get('price') if (mat_data.get('date') != 'N/A' and get_hours_ago(mat_data.get('date')) <= MAX_AGE) else mat_data.get('hist_price', 0)
            modifier = 1.0 if i.get('ignore_return') else (1 - current_return)
            total_mat_cost += (price * i['count'] * modifier)

        station_fee = ((r.get("item_value", 0) * r.get("yield", 1)) * 0.1125) * (STATION_COST / 100.0)
        total_cost = total_mat_cost + r.get("silver_cost", 0) + station_fee
        gross_rev = (rev_price * r.get("yield", 1) * (1 - MARKET_TAX))
        profit = gross_rev - total_cost
        
        if profit > best_profit:
            best_profit = profit
            pct = (profit / total_cost * 100) if total_cost > 0 else 0
            if pct < MIN_MARGIN or pct > IGNORE_MARGIN: continue
            
            focus_cost = int(r.get("focus_cost", 0) * (0.5 ** (FOCUS_EFFICIENCY / 10000)))
            
            best_result = {
                "Best City": city,
                "Tier": get_tier(r['output']),
                "Name": name_map.get(r['output'], r['output']),
                "Inputs": r['inputs'], 
                "Cost": int(total_cost),
                "Price": int(gross_rev),
                "Margin%": round(pct, 1),
                "S/F": int(profit / focus_cost) if (USE_FOCUS and focus_cost > 0) else 0,
                "Focus": focus_cost,
                "Vol(24h)": out_data.get('volume', 0)
            }
    
    return best_result

# ================= MAIN =================
st.title("Albion Crafting Calculator")

if st.button("Calculate"):
    if not CRAFT_CITIES:
        st.error("Please select at least one city.")
        st.stop()
        
    try:
        with open("items.json", "r", encoding="utf-8") as f:
            root = json.load(f).get("items", {})
        with open("formattedItems.json", "r", encoding="utf-8") as f:
            name_data = json.load(f)
            name_lookup = {item["LocalizationNameVariable"].replace("@ITEMS_", "").replace("@", ""): item["LocalizedNames"].get("EN-US") for item in name_data if isinstance(item, dict) and "LocalizationNameVariable" in item}
    except Exception as e:
        st.error(f"Error loading JSON: {e}")
        st.stop()

    recipes, name_map = [], {}
    for cat, items in root.items():
        if not isinstance(items, list): continue
        for item in items:
            u_name = item.get("@uniquename")
            if not u_name: continue
            name_map[u_name] = name_lookup.get(u_name, u_name)
            if item.get("@craftingcategory") == CRAFT_TYPE and CRAFT_TYPE in ("food", "potion"):
                base_val = float(item.get("@itemvalue", 0))
                for c in to_list(item.get("craftingrequirements")):
                    raw_res = to_list(c.get("craftresource") or c.get("resources") or c.get("craftingresource") or [])
                    inputs = [{"id": get_id(r), "count": int(r.get("@count", 1)), "ignore_return": r.get("@maxreturnamount") == "0"} for r in raw_res if get_id(r)]
                    if inputs: recipes.append({"output": u_name, "inputs": inputs, "silver_cost": int(c.get("@silver", 0)), "yield": int(c.get("@amountcrafted", 1)), "focus_cost": int(c.get("@craftingfocus", 0)), "item_value": base_val})
                if item.get("enchantments"):
                    for ench in to_list(item.get("enchantments").get("enchantment")):
                        lvl = int(ench.get("@enchantmentlevel", 0))
                        ench_output = f"{u_name}@{lvl}"
                        name_map[ench_output] = f"{name_map[u_name]} (Ench {lvl})"
                        for c in to_list(ench.get("craftingrequirements")):
                            recipes.append({"output": ench_output, "inputs": [{"id": get_id(r), "count": int(r.get("@count", 1)), "ignore_return": r.get("@maxreturnamount") == "0"} for r in to_list(c.get("craftresource") or c.get("resources") or []) if get_id(r)], "silver_cost": int(c.get("@silver", 0)), "yield": int(c.get("@amountcrafted", 1)), "focus_cost": int(c.get("@craftingfocus", 0)), "item_value": base_val * (2 ** lvl)})

    lookup_ids = list(set([r['output'] for r in recipes] + [i['id'] for r in recipes for i in r['inputs']]))
    with st.spinner('Fetching market data...'):
        market_data = fetch_market_data(lookup_ids)
    
    st.session_state.name_map = name_map
    st.session_state.market_data = market_data
    results = [f.result() for f in [ThreadPoolExecutor(max_workers=THREADS).submit(process_recipe, r, name_map, market_data) for r in recipes] if f.result()]
    st.session_state.df = pd.DataFrame(results)

# Display
if st.session_state.df is not None and not st.session_state.df.empty:
    df = st.session_state.df
    display_df = df.drop(columns=["Inputs"], errors='ignore')
    sort_col = "S/F" if USE_FOCUS else "Margin%"
    st.dataframe(display_df.sort_values(by=sort_col, ascending=False), width='stretch', hide_index=True)
    st.write(f"**Calculated using Best City for each individual item across:** {', '.join(CRAFT_CITIES)}")

    st.divider()
    st.subheader("Detailed Recipes")
    search_term = st.text_input("🔍 Search for a recipe name:", placeholder="Type name to filter...")
    for _, row in df.iterrows():
        if search_term.lower() in row['Name'].lower():
            with st.expander(f"Recipe: {row['Name']} (Tier {row['Tier']}) | Best City: {row['Best City']}"):
                mat_data = []
                for item in row['Inputs']:
                    m_data = st.session_state.market_data.get(item['id'], {}).get(row['Best City'], {})
                    price = m_data.get('price') if (m_data.get('date') != 'N/A' and get_hours_ago(m_data.get('date')) <= MAX_AGE) else m_data.get('hist_price', 0)
                    mat_data.append({"Tier": get_tier(item['id']), "Material": st.session_state.name_map.get(item['id'], item['id']), "Quantity": item['count'], "Unit Cost": f"{int(price):,}", "Total": f"{int(price * item['count']):,}"})
                st.table(pd.DataFrame(mat_data))
