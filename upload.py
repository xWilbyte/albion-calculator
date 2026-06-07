import streamlit as st
import json
import re
import time
import requests
import threading
import pandas as pd
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# ================= PAGE CONFIG =================
st.set_page_config(layout="wide", page_title="Albion Crafting Calculator")

# ================= SIDEBAR INPUTS =================
st.sidebar.header("Crafting Config")
# Changed to Capitalized versions, forced to lower() for internal logic compatibility
CRAFT_TYPE = st.sidebar.selectbox("Craft Type", ["Potion", "Food"]).lower() 
CRAFT_CITY = st.sidebar.selectbox("City", ["Bridgewatch", "Lymhurst", "Martlock", "Fort Sterling", "Thetford", "Caerleon", "Black Market"])
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
# Updated to include tiers 1-8 as default
ALLOWED_TIERS = st.sidebar.multiselect("Allowed Tiers", [1, 2, 3, 4, 5, 6, 7, 8], default=[1, 2, 3, 4, 5, 6, 7, 8])
# Updated max age to 1000
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
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self.last_call = time.time()

limiter = RateLimiter(1/150)

# ================= UTILS =================
def to_list(x):
    if x is None: return []
    if isinstance(x, list): return x
    return [x]

def get_hours_ago(date_str):
    if date_str == "N/A": return 999
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        return int(diff.total_seconds() // 3600)
    except: return 999

def format_age(hours):
    return "N/A" if hours == 999 else f"{hours}h"

def get_id(x):
    if not isinstance(x, dict): return None
    return x.get("@uniquename") or x.get("id")

# ================= MARKET FETCH =================
def fetch_market_data(ids):
    data_map = {i: {'price': 0, 'date': 'N/A', 'hist_price': 0, 'hist_date': 'N/A', 'volume': 0} for i in ids}
    unique_ids = list(set(ids))
    for i in range(0, len(unique_ids), BATCH_SIZE):
        limiter.wait()
        chunk = unique_ids[i : i + BATCH_SIZE]
        url = f"{API_URL}{','.join(chunk)}?locations={CRAFT_CITY}"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                for row in r.json():
                    item_id = row.get("item_id")
                    price = row.get("sell_price_min", 0)
                    if price > 0 and item_id in data_map:
                        data_map[item_id].update({'price': price, 'date': row.get('sell_price_min_date', 'N/A')})
        except: continue
    for i in range(0, len(unique_ids), HIST_BATCH_SIZE):
        limiter.wait()
        chunk = unique_ids[i : i + HIST_BATCH_SIZE]
        url = f"{HISTORY_URL}{','.join(chunk)}.json?locations={CRAFT_CITY}&time-scale=24"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                resp = r.json()
                if isinstance(resp, list):
                    for entry in resp:
                        if entry.get("location") == CRAFT_CITY:
                            item_id = entry.get("item_id")
                            data_points = entry.get("data", [])
                            if not data_points or not item_id or item_id not in data_map: continue
                            recent_data = data_points[-30:]
                            avg_vol = sum(d.get("item_count", 0) for d in recent_data) / len(recent_data)
                            most_recent = data_points[-1]
                            data_map[item_id].update({'volume': int(avg_vol), 'hist_price': most_recent.get("avg_price", 0), 'hist_date': most_recent.get("timestamp", "N/A")})
        except: continue
    return data_map

# ================= PROCESS RECIPE =================
def process_recipe(r, name_map, market_data):
    out_key = r['output']
    out_data = market_data.get(out_key, {})
    revenue = out_data['price'] if (out_data.get('date') != 'N/A' and get_hours_ago(out_data['date']) <= MAX_AGE) else out_data.get('hist_price', 0)
    out_hours = get_hours_ago(out_data.get('date', 'N/A'))

    total_mat_cost = 0.0
    max_mat_hours = 0
    current_return = FOCUS_RETURN_RATE if USE_FOCUS else BASE_RETURN_RATE

    for i in r['inputs']:
        mat_id = i['id']
        mat_data = market_data.get(mat_id, {})
        price = mat_data.get('price', 0) if (mat_data.get('date') != 'N/A' and get_hours_ago(mat_data.get('date')) <= MAX_AGE) else mat_data.get('hist_price', 0)
        max_mat_hours = max(max_mat_hours, get_hours_ago(mat_data.get('date', 'N/A')))
        modifier = 1.0 if i.get('ignore_return') else (1 - current_return)
        total_mat_cost += (price * i['count'] * modifier)

    if out_hours > MAX_AGE or max_mat_hours > MAX_AGE: return None

    station_fee = ((r.get("item_value", 0) * r.get("yield", 1)) * 0.1125) * (STATION_COST / 100.0)
    total_cost = total_mat_cost + r.get("silver_cost", 0) + station_fee
    gross_rev = (revenue * r.get("yield", 1) * (1 - MARKET_TAX))
    profit = gross_rev - total_cost
    pct = (profit / total_cost * 100) if total_cost > 0 else 0
    
    # Filter by margin (can now include negative values)
    if pct < MIN_MARGIN or pct > IGNORE_MARGIN: return None
    if out_data.get('volume', 0) < MIN_DAILY_VOLUME: return None

    focus_cost = int((r.get("focus_cost", 0) * (0.5 ** (FOCUS_EFFICIENCY / 10000))) * r.get("yield", 1))
    
    return {
        "Name": name_map.get(r['output'], r['output']),
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

# ================= MAIN =================
st.title("Albion Crafting Calculator")

if st.button("Calculate"):
    try:
        with open("items.json", "r", encoding="utf-8") as f:
            root = json.load(f)["items"]
    except FileNotFoundError:
        st.error("items.json missing!")
        st.stop()

    recipes = []
    name_map = {}

    for cat, items in root.items():
        if not isinstance(items, list): continue
        for item in items:
            name = item.get("localizednames", {}).get("EN-US", item["@uniquename"])
            name_map[item["@uniquename"]] = name
            # Updated to handle tiers 1-8
            tier_match = re.match(r"T([1-8])_", item["@uniquename"])
            if tier_match and int(tier_match.group(1)) not in ALLOWED_TIERS: continue

            if item.get("@craftingcategory") == CRAFT_TYPE and CRAFT_TYPE in ("food", "potion"):
                base_val = float(item.get("@itemvalue", 0))
                reqs = to_list(item.get("craftingrequirements"))
                
                def add_recipe(c, output, val):
                    raw_res = to_list(c.get("craftresource") or c.get("resources") or c.get("craftingresource") or [])
                    inputs = [{"id": get_id(r), "count": int(r.get("@count", 1)), "ignore_return": r.get("@maxreturnamount") == "0"} for r in raw_res if get_id(r)]
                    if inputs:
                        recipes.append({"output": output, "inputs": inputs, "silver_cost": int(c.get("@silver", 0)), 
                                        "yield": int(c.get("@amountcrafted", 1)), "focus_cost": int(c.get("@craftingfocus", 0)), 
                                        "item_value": val})

                for c in reqs:
                    if c: add_recipe(c, item["@uniquename"], base_val)
                enchant = item.get("enchantments")
                if enchant:
                    for ench in to_list(enchant.get("enchantment")):
                        lvl = int(ench.get("@enchantmentlevel", 0))
                        ench_output = f"{item['@uniquename']}@{lvl}"
                        name_map[ench_output] = f"{name} (Ench {lvl})"
                        for c in to_list(ench.get("craftingrequirements")):
                            if c: add_recipe(c, ench_output, base_val * (2 ** lvl))

    lookup_ids = list(set([r['output'] for r in recipes] + [i['id'] for r in recipes for i in r['inputs']]))
    with st.spinner('Fetching market data...'):
        market_data = fetch_market_data(lookup_ids)
    
    results = [f.result() for f in [ThreadPoolExecutor(max_workers=THREADS).submit(process_recipe, r, name_map, market_data) for r in recipes] if f.result()]
    df = pd.DataFrame(results)
    
    if not df.empty:
        if not USE_FOCUS:
            df = df.drop(columns=["S/F", "Focus"], errors='ignore')
            df = df.sort_values(by="Margin%", ascending=False)
        else:
            df = df.sort_values(by="S/F", ascending=False)
            
        st.dataframe(
            df, 
            width='stretch', 
            height=800,
            column_config={
                "Cost": st.column_config.NumberColumn("Cost", format="%,d"),
                "Price": st.column_config.NumberColumn("Price", format="%,d"),
                "Price (24h)": st.column_config.NumberColumn("Price (24h)", format="%,d"),
                "Focus": st.column_config.NumberColumn("Focus", format="%,d"),
                "Vol(24h)": st.column_config.NumberColumn("Vol(24h)", format="%,d"),
            }
        )
    else:
        st.warning("No items found.")
