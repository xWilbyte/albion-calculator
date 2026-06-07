import streamlit as st
import json
import re
import time
import requests
import pandas as pd
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# ================= PAGE CONFIG =================
st.set_page_config(layout="wide", page_title="Albion Crafting Calculator")

# ================= SIDEBAR INPUTS =================
st.sidebar.header("Configuration")
CRAFT_TYPE = st.sidebar.selectbox("Craft Type", ["potion", "food"])
CRAFT_CITY = st.sidebar.selectbox("City", ["Bridgewatch", "Lymhurst", "Martlock", "Fort Sterling", "Thetford", "Caerleon", "Black Market"])
STATION_COST = st.sidebar.number_input("Station Cost", value=500)
MIN_DAILY_VOLUME = st.sidebar.number_input("Min Daily Volume", value=100)
MIN_MARGIN = st.sidebar.number_input("Min Margin %", value=10.0)

st.sidebar.header("Focus Settings")
USE_FOCUS = st.sidebar.checkbox("Use Focus", value=False)
FOCUS_EFFICIENCY = st.sidebar.number_input("Focus Efficiency Level", value=10000)
FOCUS_RETURN_RATE = 0.435
BASE_RETURN_RATE = 0.152

st.sidebar.header("Filters")
ALLOWED_TIERS = st.sidebar.multiselect("Allowed Tiers", [3, 4, 5, 6, 7, 8], default=[3, 4, 5, 6])
MAX_AGE = st.sidebar.slider("Max Data Age (Hours)", 1, 168, 72)

# ================= CONSTANTS =================
API_URL = "https://west.albion-online-data.com/api/v2/stats/prices/"
HISTORY_URL = "https://west.albion-online-data.com/api/v2/stats/history/"
MARKET_TAX = 0.065
THREADS = 10
BATCH_SIZE = 100
HIST_BATCH_SIZE = 50

# ================= UTILS =================
def get_hours_ago(date_str):
    if date_str == "N/A": return 999
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        return int(diff.total_seconds() // 3600)
    except: return 999

def format_age(hours):
    return "N/A" if hours == 999 else f"{hours}h"

@st.cache_data(ttl=3600)
def fetch_market_data(ids):
    data_map = {i: {'price': 0, 'date': 'N/A', 'hist_price': 0, 'hist_date': 'N/A', 'volume': 0} for i in ids}
    
    # Prices
    for i in range(0, len(ids), BATCH_SIZE):
        chunk = ids[i : i + BATCH_SIZE]
        url = f"{API_URL}{','.join(chunk)}?locations={CRAFT_CITY}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                for row in r.json():
                    item_id = row.get("item_id")
                    if row.get("sell_price_min", 0) > 0:
                        data_map[item_id].update({'price': row['sell_price_min'], 'date': row.get('sell_price_min_date', 'N/A')})
        except: continue
        
    # History
    for i in range(0, len(ids), HIST_BATCH_SIZE):
        chunk = ids[i : i + HIST_BATCH_SIZE]
        url = f"{HISTORY_URL}{','.join(chunk)}.json?locations={CRAFT_CITY}&time-scale=24"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                for entry in r.json():
                    if entry.get("location") == CRAFT_CITY and entry.get("data"):
                        item_id = entry["item_id"]
                        data = entry["data"][-1]
                        data_map[item_id].update({'hist_price': data.get("avg_price", 0), 'hist_date': data.get("timestamp", "N/A"), 'volume': int(sum(d.get("item_count", 0) for d in entry["data"][-30:])/30)})
        except: continue
    return data_map

def process_recipe(r, name_map, market_data):
    out_key = r['output']
    out_data = market_data.get(out_key, {})
    
    revenue = out_data['price'] if (out_data.get('date') != 'N/A' and get_hours_ago(out_data['date']) <= MAX_AGE) else out_data.get('hist_price', 0)
    out_hours = get_hours_ago(out_data.get('date', 'N/A'))

    total_mat_cost = 0.0
    max_mat_hours = 0
    current_return = FOCUS_RETURN_RATE if USE_FOCUS else BASE_RETURN_RATE

    for i in r['inputs']:
        mat_data = market_data.get(i['id'], {})
        price = mat_data['price'] if (mat_data.get('date') != 'N/A' and get_hours_ago(mat_data['date']) <= MAX_AGE) else mat_data.get('hist_price', 0)
        max_mat_hours = max(max_mat_hours, get_hours_ago(mat_data.get('date', 'N/A')))
        
        modifier = 1.0 if i.get('ignore_return') else (1 - current_return)
        total_mat_cost += (price * i['count'] * modifier)

    if out_hours > MAX_AGE or max_mat_hours > MAX_AGE: return None
    
    station_fee = ((r.get("item_value", 0) * r.get("yield", 1)) * 0.1125) * (STATION_COST / 100.0)
    total_cost = total_mat_cost + r.get("silver_cost", 0) + station_fee
    gross_rev = (revenue * r.get("yield", 1) * (1 - MARKET_TAX))
    profit = gross_rev - total_cost
    pct = (profit / total_cost * 100) if total_cost > 0 else 0
    
    if pct < MIN_MARGIN or out_data.get('volume', 0) < MIN_DAILY_VOLUME: return None

    focus_cost = int((r.get("focus_cost", 0) * (0.5 ** (FOCUS_EFFICIENCY / 10000))) * r.get("yield", 1))
    
    return {
        "Item Name": name_map.get(r['output'], r['output']),
        "Cost": int(total_cost),
        "Price": int(gross_rev),
        "Price (24h)": int(out_data.get('hist_price', 0) * r.get("yield", 1) * (1 - MARKET_TAX)),
        "Margin%": round(pct, 1),
        "S/F": int(profit / focus_cost) if (USE_FOCUS and focus_cost > 0) else 0,
        "Focus": focus_cost,
        "Vol(24h)": out_data.get('volume', 0),
        "Item Age": format_age(out_hours),
        "Mat Age": format_age(max_mat_hours)
    }

# ================= MAIN APP =================
st.title("Albion Crafting Calculator")

if st.button("Calculate Recipes"):
    try:
        with open("items.json", "r", encoding="utf-8") as f:
            root = json.load(f)["items"]
    except FileNotFoundError:
        st.error("items.json not found! Please place it in the script directory.")
        st.stop()

    recipes = []
    name_map = {}
    
    # Recipe Loading Logic
    for cat, items in root.items():
        if not isinstance(items, list): continue
        for item in items:
            name = item.get("localizednames", {}).get("EN-US", item["@uniquename"])
            tier = int(re.match(r"T([1-8])_", item["@uniquename"]).group(1)) if re.match(r"T([1-8])_", item["@uniquename"]) else 0
            if tier not in ALLOWED_TIERS or item.get("@craftingcategory") != CRAFT_TYPE: continue
            
            name_map[item["@uniquename"]] = name
            reqs = item.get("craftingrequirements")
            if not isinstance(reqs, list): reqs = [reqs] if reqs else []
            
            for c in reqs:
                if not c: continue
                raw_res = c.get("craftresource") or c.get("resources") or c.get("craftingresource") or []
                if not isinstance(raw_res, list): raw_res = [raw_res]
                
                inputs = [{"id": r.get("@uniquename") or r.get("id"), "count": int(r.get("@count", 1)), "ignore_return": r.get("@maxreturnamount") == "0"} for r in raw_res]
                recipes.append({
                    "output": item["@uniquename"], "inputs": inputs, "silver_cost": int(c.get("@silver", 0)),
                    "yield": int(c.get("@amountcrafted", 1)), "focus_cost": int(c.get("@craftingfocus", 0)),
                    "item_value": float(item.get("@itemvalue", 0))
                })

    # Fetch and process
    lookup_ids = list(set([r['output'] for r in recipes] + [i['id'] for r in recipes for i in r['inputs']]))
    with st.spinner('Fetching market data...'):
        market_data = fetch_market_data(lookup_ids)
    
    results = []
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(process_recipe, r, name_map, market_data) for r in recipes]
        results = [f.result() for f in futures if f.result()]

    df = pd.DataFrame(results)
    
    # Sorting
    if not df.empty:
        sort_col = "S/F" if USE_FOCUS else "Margin%"
        df = df.sort_values(by=sort_col, ascending=False)
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("No profitable items found with current settings.")