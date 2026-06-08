import streamlit as st 
import json 
import re 
import time 
import requests 
import threading 
import pandas as pd 
from datetime import datetime, timezone 
from concurrent.futures import ThreadPoolExecutor 

# ================= MAPPING FOR RRR =================
RRR_BONUS_MAP = {
    "hide": "Martlock",
    "rock": "Bridgewatch",
    "fiber": "Lymhurst",
    "wood": "Fort Sterling",
    "ore": "Thetford",
    "potion": "Brecilien",
    "food": "Caerleon"
}

def get_rrr(city, category, use_focus, is_refining):
    """
    Calculates Resource Return Rate.
    """
    category_key = category.lower() if category else ""
    bonus_city = RRR_BONUS_MAP.get(category_key)
    is_bonus_city = (city == bonus_city)
    
    if is_refining:
        if use_focus:
            return 0.539 if is_bonus_city else 0.435
        else:
            return 0.367 if is_bonus_city else 0.153
    else:
        if use_focus:
            return 0.479 if is_bonus_city else 0.435
        else:
            # Corrected: 24.8% for Crafting + Bonus (No Focus)
            return 0.248 if is_bonus_city else 0.153

# ================= RESET FUNCTION =================
def reset_defaults():
    st.session_state['craft_type'] = "Potions"
    st.session_state['craft_cities'] = ["Bridgewatch"]
    st.session_state['sell_cities'] = ["Bridgewatch"]
    st.session_state['station_cost'] = 500
    st.session_state['min_vol'] = 100
    st.session_state['min_margin'] = 10.0
    st.session_state['use_focus'] = False
    st.session_state['focus_eff'] = 10000
    st.session_state['allowed_tiers'] = [1, 2, 3, 4, 5, 6, 7, 8]
    st.session_state['max_age'] = 48
    st.session_state['ignore_margin'] = 1000.0
    st.session_state['show_mat_age'] = False
    st.session_state['show_item_age'] = False
    st.session_state['show_vol'] = True
    st.session_state['show_avg_price'] = False
    st.session_state['show_profit'] = False
    st.session_state['show_rrr'] = False

# ================= PAGE CONFIG & STYLING ================= 
st.set_page_config(layout="wide", page_title="Albion Crafting Calculator") 

st.markdown(""" 
    <style> 
    [data-testid="stMainBlockContainer"] { padding-top: 1rem; }
    [data-testid="stDataFrame"] [role="columnheader"], 
    [data-testid="stDataFrame"] [role="gridcell"] {
        justify-content: center !important;
        text-align: center !important;
    }
    .stTable th, .stTable td { text-align: center !important; } 

    [data-testid="stMainBlockContainer"] div.stButton > button { 
        width: 100% !important; 
        height: 45px !important; 
        font-weight: bold !important; 
        font-size: 15px !important; 
        background-color: #f63366 !important; 
        color: white !important; 
        border-radius: 5px !important;
        margin-top: 10px !important;
        margin-bottom: 20px !important;
    } 

    [data-testid="stSidebar"] div.stButton > button { 
        width: 100% !important; 
        height: 36px !important; 
        font-weight: bold !important; 
        font-size: 15px !important; 
        background-color: #f63366 !important; 
        color: white !important; 
        border-radius: 5px !important;
        margin-top: 10px !important;
        margin-bottom: 20px !important;
    } 
    </style> 
    """, unsafe_allow_html=True) 

# ================= SESSION STATE INIT ================= 
if 'df' not in st.session_state: st.session_state.df = None 
if 'name_map' not in st.session_state: st.session_state.name_map = {} 
if 'market_data' not in st.session_state: st.session_state.market_data = {} 

# ================= SIDEBAR INPUTS ================= 
st.sidebar.markdown("## Config") 
ALL_CITIES = ["Bridgewatch", "Lymhurst", "Martlock", "Fort Sterling", "Thetford", "Caerleon", "Black Market", "Brecilien"]

with st.sidebar.expander("General Settings", expanded=True):
    ui_choice = st.selectbox("Craft Type", ["Potions", "Food", "Refining"], key="craft_type")
    if ui_choice == "Potions": CRAFT_TYPE = "potion"
    elif ui_choice == "Refining": CRAFT_TYPE = "refine"
    else: CRAFT_TYPE = "food"

    CRAFT_CITIES = st.multiselect("Craft City", [c for c in ALL_CITIES if c != "Black Market"], default=["Bridgewatch"], key="craft_cities") 
    SELL_CITIES = st.multiselect("Sell City", ALL_CITIES, default=["Bridgewatch"], key="sell_cities") 
    STATION_COST = st.number_input("Station Cost", value=500, key="station_cost") 
    MIN_DAILY_VOLUME = st.number_input("Min Volume (24h)", value=100, key="min_vol") 
    MIN_MARGIN = st.number_input("Min Profit Margin %", value=10.0, step=1.0, key="min_margin") 

with st.sidebar.expander("Focus Settings"):
    USE_FOCUS = st.checkbox("Use Focus", value=False, key="use_focus") 
    FOCUS_EFFICIENCY = st.number_input("Focus Efficiency Level", value=10000, key="focus_eff") 

with st.sidebar.expander("Filters"):
    ALLOWED_TIERS = st.multiselect("Allowed Tiers", [1, 2, 3, 4, 5, 6, 7, 8], default=[1, 2, 3, 4, 5, 6, 7, 8], key="allowed_tiers") 
    MAX_AGE = st.slider("Max Data Age (Hours)", 1, 1000, 48, key="max_age") 
    IGNORE_MARGIN = st.number_input("Ignore Margin > %", value=1000.0, key="ignore_margin") 

with st.sidebar.expander("Display Options"):
    SHOW_MAT_AGE = st.checkbox("Show Mat Age", value=False, key="show_mat_age") 
    SHOW_ITEM_AGE = st.checkbox("Show Item Age", value=False, key="show_item_age") 
    SHOW_VOL = st.checkbox("Show Vol Sold (24h)", value=True, key="show_vol") 
    SHOW_AVG_PRICE = st.checkbox("Show Avg Price (24h)", value=False, key="show_avg_price") 
    SHOW_PROFIT = st.checkbox("Show Profit (Silver)", value=False, key="show_profit") 
    SHOW_RRR = st.checkbox("Show Return Rate", value=False, key="show_rrr")

st.sidebar.button("Restore Default Settings", on_click=reset_defaults, use_container_width=True)

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

def normalize_id(id_str, category="refine"):
    if not id_str: return id_str
    if "@" in id_str: return id_str
    
    # Exceptions: Fish sauce and Alchemy extracts use native _LEVEL formatting without @ 
    if "FISHSAUCE" in id_str or "ALCHEMY_EXTRACT" in id_str:
        return id_str
    
    # Updated: Include all refined resource types so they all get the correct API format
    refined_categories = ["hide", "rock", "fiber", "wood", "ore", "refine"]
    
    if category.lower() in refined_categories:
        # Keeps _LEVEL1 and adds @1 resulting in T4_ROCK_LEVEL1@1
        return re.sub(r"_LEVEL(\d+)", r"\g<0>@\1", id_str)
    else:
        # Fallback for non-refined items (Potions/Food)
        return re.sub(r"_LEVEL(\d+)", r"@\1", id_str)

def get_id(r, category="refine"):
    if isinstance(r, dict):
        return normalize_id(r.get("@uniquename"), category)
    return ""

def get_base_name(id_str):
    return re.sub(r"(@\d+|(_LEVEL\d+(@\d+)?))", "", id_str)

def to_list(x): 
    if x is None: return [] 
    if isinstance(x, list): return x 
    return [x] 

def get_tier(id_str): 
    tier_match = re.search(r"T([1-8])", id_str)
    tier = tier_match.group(1) if tier_match else "0"
    
    ench_match = re.search(r"@([1-4])", id_str)
    if ench_match: return f"{tier}.{ench_match.group(1)}"
    
    # Format Fish Sauce / Extract levels to display properly as enhancements (1.1, 1.2, etc.)
    level_match = re.search(r"_LEVEL([1-4])", id_str)
    if level_match and ("FISHSAUCE" in id_str or "ALCHEMY_EXTRACT" in id_str):
        return f"{tier}.{level_match.group(1)}"
        
    return tier

def get_hours_ago(date_str): 
    if not date_str or date_str == "N/A" or date_str.startswith("0001-01-01"): 
        return 999 
    try: 
        # Strip trailing 'Z' and fractional seconds that break strptime
        clean_date = date_str.split('.')[0].replace("Z", "")
        dt = datetime.strptime(clean_date, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) 
        diff = datetime.now(timezone.utc) - dt 
        return int(diff.total_seconds() // 3600) 
    except: 
        return 999

def format_age(hours):
    if hours >= 999: return "N/A"
    return f"{hours}h"

# ================= MARKET FETCH ================= 
def fetch_market_data(ids): 
    data_map = {} 
    unique_ids = list(set(ids)) 
    all_cities = list(set(CRAFT_CITIES + SELL_CITIES))
    city_param = ",".join(all_cities) 
     
    # --- 1. FETCH LIVE PRICES ---
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
     
    # --- 2. FETCH HISTORY (AND UPDATE MISSING DATES) ---
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
                        if city in all_cities: 
                            item_id = entry.get("item_id") 
                            data_points = entry.get("data", []) 
                            if not data_points or not item_id: continue 
                            if item_id not in data_map: data_map[item_id] = {} 
                            if city not in data_map[item_id]: data_map[item_id][city] = {'price': 0, 'date': 'N/A', 'hist_price': 0, 'volume': 0} 
                            
                            recent_data = data_points[-30:] 
                            avg_vol = sum(d.get("item_count", 0) for d in recent_data) / len(recent_data) 
                            most_recent = data_points[-1] 
                            
                            update_dict = {
                                'volume': int(avg_vol), 
                                'hist_price': most_recent.get("avg_price", 0)
                            } 
                            
                            # THE FIX: Inject the history timestamp if the live date is missing/invalid
                            current_date = data_map[item_id][city].get('date', 'N/A')
                            if current_date == 'N/A' or current_date.startswith("0001-01-01"):
                                update_dict['date'] = most_recent.get("timestamp", 'N/A')
                            
                            data_map[item_id][city].update(update_dict) 
        except: continue 
        
    return data_map

# ================= PROCESS RECIPE ================= 
def process_recipe(r, name_map, market_data): 
    best_result = None 
    best_profit = -999999999

    for craft_city in CRAFT_CITIES: 
        for sell_city in SELL_CITIES:
            is_refining = (CRAFT_TYPE == "refine")
            
            # Dynamic Return Rate Calculation
            current_return = get_rrr(craft_city, r.get("category", ""), USE_FOCUS, is_refining)
            
            out_key = r['output']
            out_data = market_data.get(out_key, {}).get(sell_city, {}) 
            revenue = out_data.get('price', 0) if (out_data.get('date') != 'N/A' and get_hours_ago(out_data.get('date')) <= MAX_AGE) else out_data.get('hist_price', 0) 
            out_hours = get_hours_ago(out_data.get('date', 'N/A')) 
            
            total_mat_cost = 0.0 
            max_mat_hours = 0 
            for i in r['inputs']: 
                mat_id = i['id'] 
                mat_data = market_data.get(mat_id, {}).get(craft_city, {}) 
                price = mat_data.get('price', 0) if (mat_data.get('date') != 'N/A' and get_hours_ago(mat_data.get('date')) <= MAX_AGE) else mat_data.get('hist_price', 0) 
                max_mat_hours = max(max_mat_hours, get_hours_ago(mat_data.get('date', 'N/A'))) 
                modifier = 1.0 if i.get('ignore_return') else (1 - current_return) 
                total_mat_cost += (price * i['count'] * modifier) 
            
            if out_hours > MAX_AGE or max_mat_hours > MAX_AGE: continue 
            station_fee = ((r.get("item_value", 0) * r.get("yield", 1)) * 0.1125) * (STATION_COST / 100.0) 
            total_cost = total_mat_cost + r.get("silver_cost", 0) + station_fee 
            gross_rev = (revenue * r.get("yield", 1) * (1 - MARKET_TAX)) 
            avg_rev = (out_data.get('hist_price', 0) * r.get("yield", 1) * (1 - MARKET_TAX))
            profit = gross_rev - total_cost 
            pct = (profit / total_cost * 100) if total_cost > 0 else 0 
            
            if pct < MIN_MARGIN or pct > IGNORE_MARGIN: continue 
            if out_data.get('volume', 0) < MIN_DAILY_VOLUME: continue 
            
            if profit > best_profit: 
                best_profit = profit 
                focus_cost = int(r.get("focus_cost", 0) * (0.5 ** (FOCUS_EFFICIENCY / 10000))) 
                
                out_tier = get_tier(r['output'])
                out_name = name_map.get(get_base_name(r['output']), r['output'])
                
                if r.get("category") == "rock":
                    input_ench = 0
                    for inp in r['inputs']:
                        match = re.search(r"@([1-4])", inp['id'])
                        if match:
                            input_ench = max(input_ench, int(match.group(1)))
                    if input_ench > 0:
                        out_tier = f"{out_tier.split('.')[0]}.{input_ench}"

                best_result = { 
                    "Craft City": craft_city, "Sell City": sell_city, "Tier": out_tier, "Name": out_name, 
                    "Inputs": r['inputs'], "Mat Cost": int(total_cost), "Sell Price": int(gross_rev), "Avg Price (24h)": int(avg_rev),
                    "Profit Margin%": round(pct, 1), "Profit (Silver)": int(profit), "S/F": int(profit / focus_cost) if (USE_FOCUS and focus_cost > 0) else 0, 
                    "Focus": focus_cost, "Vol Sold (24h)": out_data.get('volume', 0), "Item Age": format_age(out_hours), "Mat Age": format_age(max_mat_hours),
                    "Return Rate": f"{current_return:.1%}"
                } 
    return best_result 

# ================= MAIN ================= 
st.markdown("<h1 style='text-align: center;'>Albion Crafting Profit Calculator</h1>", unsafe_allow_html=True) 

if st.button("Click to Calculate", use_container_width=True): 
    if not CRAFT_CITIES or not SELL_CITIES: 
        st.error("Please select at least one Craft city and one Sell city.") 
        st.stop() 
        
    try: 
        with open("items.json", "r", encoding="utf-8") as f: 
            raw_items = json.load(f) 
            root = raw_items.get("items", {}) if isinstance(raw_items, dict) else {} 
            
        with open("formattedItems.json", "r", encoding="utf-8") as f: 
            name_data = json.load(f) 
            name_lookup = {} 
            if isinstance(name_data, list): 
                for item in name_data: 
                    if item is None or not isinstance(item, dict): continue 
                    loc_names = item.get("LocalizedNames") 
                    en_name = loc_names.get("EN-US") if isinstance(loc_names, dict) else None
                    unique_name = item.get("UniqueName")
                    if unique_name and en_name: name_lookup[unique_name] = en_name
                    var_name = item.get("LocalizationNameVariable") 
                    if var_name and isinstance(var_name, str) and en_name: 
                        key = var_name.replace("@ITEMS_", "").replace("@", "") 
                        if key not in name_lookup: name_lookup[key] = en_name
    except Exception as e: 
        st.error(f"Error loading JSON: {e}") 
        st.stop() 

    recipes = [] 
    name_map = {} 
    
    for cat, items in root.items(): 
        if not isinstance(items, list): continue 
        for item in items: 
            if not isinstance(item, dict): continue 
            u_name = item.get("@uniquename") 
            if not u_name: continue 
            base_n = get_base_name(u_name)
            if base_n not in name_map: name_map[base_n] = name_lookup.get(base_n, u_name)
            
            cat_tag = item.get("@craftingcategory", "").lower()
            subcat = item.get("@shopsubcategory1", "").lower()
            is_match = (subcat == "refinedresources") if CRAFT_TYPE == "refine" else (cat_tag == CRAFT_TYPE)
            if not is_match: continue
            
            tier_match = re.match(r"T([1-8])_", u_name) 
            if tier_match and int(tier_match.group(1)) not in ALLOWED_TIERS: continue 
            
            base_val = float(item.get("@itemvalue", 0)) 
            reqs = to_list(item.get("craftingrequirements")) 
            
            def add_recipe(c, output, val, category): 
                raw_res = to_list(c.get("craftresource") or c.get("resources") or c.get("craftingresource") or []) 
                if CRAFT_TYPE == "refine":
                    for r in raw_res:
                        if "FACTION" in get_id(r, category).upper(): return 

                inputs = [{"id": get_id(r, category), "count": int(r.get("@count", 1)), "ignore_return": r.get("@maxreturnamount") == "0"} for r in raw_res if get_id(r, category)] 
                if inputs: 
                    recipes.append({"output": normalize_id(output, category), "category": category, "inputs": inputs, "silver_cost": int(c.get("@silver", 0)), "yield": int(c.get("@amountcrafted", 1)), "focus_cost": int(c.get("@craftingfocus", 0)), "item_value": val}) 

            for c in reqs: 
                if c: add_recipe(c, u_name, base_val, cat_tag) 
            enchant = item.get("enchantments") 
            if enchant: 
                for ench in to_list(enchant.get("enchantment")): 
                    lvl = int(ench.get("@enchantmentlevel", 0)) 
                    ench_output = f"{u_name}_LEVEL{lvl}" 
                    for c in to_list(ench.get("craftingrequirements")): 
                        if c: add_recipe(c, ench_output, base_val * (2 ** lvl), cat_tag) 

    lookup_ids = list(set([r['output'] for r in recipes] + [i['id'] for r in recipes for i in r['inputs']])) 
    with st.spinner('Fetching market data...'): 
        market_data = fetch_market_data(lookup_ids) 
    st.session_state.name_map = name_map 
    st.session_state.market_data = market_data 
    
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(process_recipe, r, name_map, market_data) for r in recipes]
        results = [f.result() for f in futures if f.result()]
        
    st.session_state.df = pd.DataFrame(results) 

if st.session_state.df is not None and not st.session_state.df.empty: 
    df = st.session_state.df 
    cols = ["Tier", "Name"]
    if len(CRAFT_CITIES) > 1: cols.append("Craft City")
    if len(SELL_CITIES) > 1: cols.append("Sell City")
    cols.extend(["Mat Cost", "Sell Price"])
    if SHOW_AVG_PRICE: cols.append("Avg Price (24h)")
    cols.append("Profit Margin%")
    if SHOW_PROFIT: cols.append("Profit (Silver)")
    if USE_FOCUS: cols.extend(["S/F", "Focus"])
    if SHOW_VOL: cols.append("Vol Sold (24h)")
    if SHOW_ITEM_AGE: cols.append("Item Age")
    if SHOW_MAT_AGE: cols.append("Mat Age")
    if SHOW_RRR: cols.append("Return Rate") 
    
    display_df = df[cols].copy()
    sort_col = "S/F" if USE_FOCUS else "Profit Margin%"
    if sort_col in display_df.columns: display_df = display_df.sort_values(by=sort_col, ascending=False) 
    
    col_config = {
        "Tier": st.column_config.TextColumn("Tier", alignment="center"),
        "Name": st.column_config.TextColumn("Name", alignment="center"),
        "Craft City": st.column_config.TextColumn("Craft City", alignment="center"),
        "Sell City": st.column_config.TextColumn("Sell City", alignment="center"),
        "Mat Cost": st.column_config.NumberColumn("Mat Cost", format="%,d", alignment="center"), 
        "Sell Price": st.column_config.NumberColumn("Sell Price", format="%,d", alignment="center"), 
        "Avg Price (24h)": st.column_config.NumberColumn("Avg Price (24h)", format="%,d", alignment="center"),
        "Profit Margin%": st.column_config.NumberColumn("Profit Margin%", format="%.1f%%", alignment="center"),
        "Profit (Silver)": st.column_config.NumberColumn("Profit (Silver)", format="%,d", alignment="center"),
        "S/F": st.column_config.NumberColumn("S/F", format="%,d", alignment="center"),
        "Focus": st.column_config.NumberColumn("Focus", format="%,d", alignment="center"),
        "Vol Sold (24h)": st.column_config.NumberColumn("Vol Sold (24h)", format="%,d", alignment="center"),
        "Item Age": st.column_config.TextColumn("Item Age", alignment="center"),
        "Mat Age": st.column_config.TextColumn("Mat Age", alignment="center"),
        "Return Rate": st.column_config.TextColumn("Return Rate", alignment="center"),
    }
    
    num_rows = len(display_df)
    table_height = (num_rows + 1) * 35 
    
    st.dataframe(display_df, use_container_width=True, hide_index=True, column_config=col_config, height=min(table_height, 800)) 
    st.subheader("Recipes") 
    search_term = st.text_input("Search for a recipe name:", placeholder="Type name to filter...") 
    for _, row in df.iterrows(): 
        if search_term.lower() in row['Name'].lower(): 
            with st.expander(f"Recipe: {row['Name']} (Tier {row['Tier']})"): 
                mat_data = [] 
                for item in row['Inputs']: 
                    mat_id = item['id'] 
                    m_data = st.session_state.market_data.get(mat_id, {}).get(row['Craft City'], {}) 
                    price = m_data.get('price', 0) if (m_data.get('date') != 'N/A' and get_hours_ago(m_data.get('date')) <= MAX_AGE) else m_data.get('hist_price', 0) 
                    mat_data.append({"Tier": get_tier(mat_id), "Material": st.session_state.name_map.get(get_base_name(mat_id), mat_id), "Unit Cost": f"{int(price):,}", "Quantity": item['count'], "Total Material Cost": f"{int(price * item['count']):,}"}) 
                st.table(pd.DataFrame(mat_data)) 

elif st.session_state.df is not None and st.session_state.df.empty: 
    st.warning("No items found.")
