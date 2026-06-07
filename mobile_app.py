# =========================================================
# FINPLUS MOBILE — MINIATURE DOUBLE-ENTRY JOURNAL COMPANION
# =========================================================

import io
import json
import os
import requests
import streamlit as st
import pandas as pd
from datetime import datetime
import yfinance as yf

# -----------------------------
# PAGE CONFIG FOR MOBILE-FIRST VIEW
# -----------------------------
st.set_page_config(
    page_title="FinPlus Mobile",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Late-injected CSS for premium mobile look and feel
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', 'Outfit', sans-serif !important;
}
.stApp {
    background-color: #F8FAFC !important;
    color: #0F172A !important;
}
.block-container {
    padding: 1rem 1rem 2rem !important;
    max-width: 500px !important;
}

/* ─── METRIC CARDS (NET WORTH CARD) ─────────────────────────────────── */
.networth-panel {
    background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%) !important;
    border: 1px solid #334155 !important;
    border-left: 5px solid #10B981 !important;
    border-radius: 16px !important;
    padding: 1.25rem !important;
    margin-bottom: 1.25rem !important;
    box-shadow: 0 10px 20px rgba(15, 23, 42, 0.1) !important;
    text-align: center;
}
.networth-title {
    color: #94A3B8 !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.75rem !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 4px;
}
.networth-value {
    color: #10B981 !important;
    font-family: 'Outfit', sans-serif !important;
    font-weight: 800 !important;
    font-size: 2.1rem !important;
    letter-spacing: -0.02em;
}

/* ─── MOBILE ACCENTS & INPUTS ───────────────────────────────────────── */
.stTextInput input,
.stNumberInput input,
.stDateInput input,
textarea {
    background: #FFFFFF !important;
    color: #0F172A !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 10px !important;
}
div[data-baseweb="base-input"],
.stNumberInput div[data-baseweb="input"] {
    background: #FFFFFF !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 10px !important;
}
div[data-baseweb="select"] > div,
div[data-baseweb="select"] > div > div {
    background: #FFFFFF !important;
    color: #0F172A !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 10px !important;
}
div[data-baseweb="select"] * { color: #0F172A !important; }
div[data-baseweb="select"] svg { fill: #64748B !important; }
input::placeholder { color: #94A3B8 !important; opacity: 1 !important; }

.stButton > button,
.stButton > button * {
    color: #FFFFFF !important;
}
.stButton > button {
    background: linear-gradient(to bottom, #059669, #047857) !important;
    border: 1px solid #065F46 !important;
    border-bottom: 4px solid #064E3B !important;
    border-radius: 12px !important;
    font-family: 'Outfit', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    padding: 12px 24px !important;
    width: 100% !important;
    box-shadow: 0 4px 8px rgba(5,150,105,0.2) !important;
    transition: all 0.15s ease !important;
}
.stButton > button:hover {
    background: linear-gradient(to bottom, #10B981, #059669) !important;
    border-color: #059669 !important;
    border-bottom-color: #047857 !important;
    box-shadow: 0 6px 14px rgba(16,185,129,0.3) !important;
}
.stButton > button:active {
    border-bottom-width: 1px !important;
    transform: translateY(3px) !important;
}

/* Headers */
h2, h3, h5 {
    font-family: 'Outfit', sans-serif !important;
    color: #0F172A !important;
    font-weight: 700 !important;
}
</style>
""", unsafe_allow_html=True)

DEFAULT_COA = {
    "Cash": "Asset",
    "Punjab National Bank": "Asset",
    "Jio Payment Bank": "Asset",
    "Stock Market Asset": "Asset",
    "Gold Asset": "Asset",
    "BlinkX Account": "Asset",
    "INDmoney Account": "Asset",
    "Mutual Fund": "Asset",
    "KSFE Sugama Account 004000010006313": "Asset",
    "Bajaj Loan": "Liability",
    "PNB Gold Loan": "Liability",
    "KSFE Gold Loan": "Liability",
    "Chitty Liability": "Liability",
    "Credit Card": "Liability",
    "KSFE GOLD LOAN 00400120052099": "Liability",
    "KSFE GOLD LOAN 00400120052097": "Liability",
    "KSFE GOLD LOAN 00400120052100": "Liability",
    "Accrued Interest(KSFE Gold Loan)": "Liability",
    "Accrued Interest(PNB Gold Loan)": "Liability",
    "Retained Earnings": "Equity",
    "Opening Balance Equity": "Equity",
    "Salary": "Revenue",
    "Stock Market Gains": "Revenue",
    "Bank Interest Received": "Revenue",
    "Trading Income": "Revenue",
    "Gold Loan PNB Interest": "Expense",
    "Chitty": "Expense",
    "KSFE Interest Tiers": "Expense",
    "Innamma": "Expense",
    "Other Expenses": "Expense",
    "Stock Market Loss": "Expense",
    "Groceries": "Expense",
    "Refershment": "Expense",
    "Travelling Expense(Petrol)": "Expense",
    "Travelling Expense(Radhu)": "Expense",
    "Shopping": "Expense",
    "Mobile Expenses": "Expense",
    "Bank Charges": "Expense",
    "Bank Interest": "Expense",
    "Trading Loss": "Expense",
    "Subscription": "Expense",
    "KSFE Gold Loan Interest": "Expense"
}

# -----------------------------
# CLOUD BACKEND SYNC HELPERS
# -----------------------------
def load_from_cloud(url, secret):
    try:
        base_url = url.rstrip("/")
        if not base_url.endswith(".json"):
            fetch_url = f"{base_url}/ledger.json"
        else:
            fetch_url = base_url
            
        params = {}
        if secret:
            params["auth"] = secret
            
        response = requests.get(fetch_url, params=params, timeout=8)
        if response.status_code == 200:
            return response.json(), True
    except Exception:
        pass
    return None, False

def save_to_cloud(payload, url, secret):
    try:
        base_url = url.rstrip("/")
        if not base_url.endswith(".json"):
            write_url = f"{base_url}/ledger.json"
        else:
            write_url = base_url
            
        params = {}
        if secret:
            params["auth"] = secret
            
        response = requests.put(write_url, json=payload, params=params, timeout=8)
        return response.status_code == 200
    except Exception:
        pass
    return False

# -----------------------------
# INITIALIZE STATE
# -----------------------------
if "cloud_url" not in st.session_state:
    st.session_state.cloud_url = ""
if "cloud_secret" not in st.session_state:
    st.session_state.cloud_secret = ""
if "ledger_data" not in st.session_state:
    st.session_state.ledger_data = None
if "qe_form_version" not in st.session_state:
    st.session_state.qe_form_version = 0
if "adv_form_version" not in st.session_state:
    st.session_state.adv_form_version = 0

# Try to auto-load credentials from Streamlit Secrets if available
try:
    if not st.session_state.cloud_url and "FIREBASE_URL" in st.secrets:
        st.session_state.cloud_url = st.secrets["FIREBASE_URL"]
    if not st.session_state.cloud_secret and "FIREBASE_SECRET" in st.secrets:
        st.session_state.cloud_secret = st.secrets["FIREBASE_SECRET"]
except Exception:
    pass

# Try to auto-load credentials from local finance_data.json if available
if not st.session_state.cloud_url:
    possible_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance_data.json"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "finance_data.json"),
        os.path.join("C:\\Users\\AbhilashBabu", "finance_data.json")
    ]
    for p in possible_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
                    if local_data.get("cloud_sync_enabled", False) and local_data.get("cloud_url", ""):
                        st.session_state.cloud_url = local_data["cloud_url"]
                        st.session_state.cloud_secret = local_data.get("cloud_secret", "")
                        break
            except Exception:
                pass

# -----------------------------
# CONFIGURATION SCREEN
# -----------------------------
if not st.session_state.cloud_url:
    st.markdown("<div style='height:40px'></div>", unsafe_allow_html=True)
    st.subheader("🔗 Connect FinPlus Mobile")
    st.write("Enter your Firebase Realtime Database credentials to sync your double-entry ledger:")
    
    url_input = st.text_input("Firebase Database URL", placeholder="https://<your-project>-default-rtdb.firebaseio.com")
    secret_input = st.text_input("Database Auth Secret / Token", type="password", placeholder="Enter database secret token...")
    
    if st.button("Connect & Download Ledger"):
        if url_input.strip():
            url_clean = url_input.strip()
            secret_clean = secret_input.strip()
            data, success = load_from_cloud(url_clean, secret_clean)
            if success:
                st.session_state.cloud_url = url_clean
                st.session_state.cloud_secret = secret_clean
                if data is None:
                    # Initialize default database structure since it was empty
                    data = {
                        "owner_name": "Abhilash",
                        "accounts": {name: {"type": typ, "parent": None} for name, typ in DEFAULT_COA.items()},
                        "journal_entries": [],
                        "gold_qty": 177.0,
                        "password": "finance@2026",
                        "security_question": "What is the owner name of this finance ledger?",
                        "security_answer": "Abhilash",
                        "cloud_sync_enabled": True,
                        "cloud_url": url_clean,
                        "cloud_secret": secret_clean
                    }
                    save_to_cloud(data, url_clean, secret_clean)
                st.session_state.ledger_data = data
                st.success("✅ Successfully linked to database!")
                st.rerun()
            else:
                st.error("❌ Failed to connect. Verify your URL, Auth Secret, and internet connection.")
        else:
            st.error("Please enter a valid Firebase URL.")
    st.stop()

# -----------------------------
# FETCH/REFRESH LEDGER
# -----------------------------
if st.session_state.ledger_data is None:
    data, success = load_from_cloud(st.session_state.cloud_url, st.session_state.cloud_secret)
    if success:
        if data is None:
            data = {
                "owner_name": "Abhilash",
                "accounts": {name: {"type": typ, "parent": None} for name, typ in DEFAULT_COA.items()},
                "journal_entries": [],
                "gold_qty": 177.0,
                "password": "finance@2026",
                "security_question": "What is the owner name of this finance ledger?",
                "security_answer": "Abhilash",
                "cloud_sync_enabled": True,
                "cloud_url": st.session_state.cloud_url,
                "cloud_secret": st.session_state.cloud_secret
            }
            save_to_cloud(data, st.session_state.cloud_url, st.session_state.cloud_secret)
        st.session_state.ledger_data = data
    else:
        st.error("❌ Failed to load cloud data. Verify settings or retry.")
        if st.button("🔄 Retry Connection"):
            st.rerun()
        if st.button("⚙️ Change Credentials"):
            st.session_state.cloud_url = ""
            st.session_state.cloud_secret = ""
            st.session_state.ledger_data = None
            st.rerun()
        st.stop()

# Short reference
d = st.session_state.ledger_data

# Account utilities
def get_account_type(acc_name):
    accs = d.get("accounts", {})
    val = accs.get(acc_name, "Asset")
    if isinstance(val, dict):
        return val.get("type", "Asset")
    return val

def get_account_parent(acc_name):
    accs = d.get("accounts", {})
    val = accs.get(acc_name)
    if isinstance(val, dict):
        return val.get("parent")
    return None

def format_account_label(acc_name):
    if acc_name is None:
        return ""
    parent = get_account_parent(acc_name)
    if parent:
        return f"{parent} ➔ {acc_name}"
    return acc_name

@st.cache_data(ttl=3600)
def fetch_gold_price_inr():
    price = None
    try:
        import urllib.request
        import re
        url = "https://www.goodreturns.in/gold-rates/kerala.html"
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as response:
            html = response.read().decode('utf-8', errors='ignore')
        match = re.search(r'id="22K-price"[^>]*>&#x20b9;([\d,]+)</span>', html)
        if match:
            price = float(match.group(1).replace(",", ""))
    except Exception:
        pass
    if price is None:
        try:
            gold = yf.Ticker("GC=F")
            gold_price_usd = gold.history(period="1d")["Close"].iloc[-1]
            inr = yf.Ticker("INR=X")
            inr_rate = inr.history(period="1d")["Close"].iloc[-1]
            price = (gold_price_usd / 31.1034768) * inr_rate
        except Exception:
            price = 14000.0
    return price

def get_all_journal_entries():
    jvs = list(d.get("journal_entries", []))
    gold_qty = d.get("gold_qty", 177.0)
    gold_rate = fetch_gold_price_inr()
    gold_depreciation = 0.23
    val = gold_qty * gold_rate * (1 - gold_depreciation)
    if val > 0:
        jvs.append({
            "jv_id": "JV-VAL-GOLD",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "narration": f"Dynamic Gold Asset Valuation",
            "lines": [
                {"account": "Gold Asset", "debit": val, "credit": 0.0},
                {"account": "Opening Balance Equity", "debit": 0.0, "credit": val}
            ]
        })
    return jvs

def get_account_balance(account_name):
    account_type = get_account_type(account_name)
    total_dr = 0.0
    total_cr = 0.0
    for jv in get_all_journal_entries():
        for line in jv.get("lines", []):
            if line["account"] == account_name:
                total_dr += line.get("debit", 0.0)
                total_cr += line.get("credit", 0.0)
                
    if account_type in ["Asset", "Expense"]:
        return total_dr - total_cr
    else:
        return total_cr - total_dr

def save_and_push():
    success = save_to_cloud(d, st.session_state.cloud_url, st.session_state.cloud_secret)
    if success:
        st.session_state.ledger_data = d
        return True
    return False

# -----------------------------
# DYNAMIC NET WORTH CALCULATION
# -----------------------------
accounts_list = list(d.get("accounts", {}).keys())
asset_accounts = [name for name in accounts_list if get_account_type(name) == "Asset"]
other_assets_sum = sum(get_account_balance(name) for name in asset_accounts if name != "Gold Asset")
gold_rate = fetch_gold_price_inr()
gold_qty = d.get("gold_qty", 177.0)
gold_depreciation = 0.23
live_gold_bal = get_account_balance("Gold Asset")
current_gold_value = live_gold_bal if live_gold_bal > 0 else (gold_qty * gold_rate * (1 - gold_depreciation))
total_assets_now = other_assets_sum + current_gold_value

liab_accounts = [name for name in accounts_list if get_account_type(name) == "Liability"]
total_liabilities_now = sum(get_account_balance(name) for name in liab_accounts)

net_worth_now = total_assets_now - total_liabilities_now

# -----------------------------
# MOBILE INTERFACE LAYOUT
# -----------------------------

# Title Banner
st.markdown(f"""
<div style="text-align: center; margin-top: 10px; margin-bottom: 15px;">
    <span style="font-size: 2.2rem;">📱</span>
    <h2 style="margin: 0; font-family: 'Outfit', sans-serif; font-size: 1.6rem; color: #0F172A; font-weight: 800;">FinPlus Mobile</h2>
    <p style="margin: 2px 0 0 0; font-size: 0.8rem; color: #64748B; font-weight: 600;">Active Owner: {d.get('owner_name', 'Abhilash')}</p>
</div>
""", unsafe_allow_html=True)

# 1. Net Worth Premium Box
st.markdown(f"""
<div class="networth-panel">
    <div class="networth-title">Current Net Worth</div>
    <div class="networth-value">₹{net_worth_now:,.2f}</div>
</div>
""", unsafe_allow_html=True)

# 2. Main Navigation tabs for mobile (Quick Form vs Advanced Form)
tab_q, tab_a, tab_settings = st.tabs(["⚡ Quick Add", "🛠️ JV Splits", "⚙️ Cloud settings"])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — QUICK ADD FORM
# ─────────────────────────────────────────────────────────────────────────────
with tab_q:
    st.markdown("##### Quick Double-Entry transaction")
    
    v = st.session_state.qe_form_version
    raw_date = st.date_input("📅 Date", value=datetime.now().date(), key=f"qe_date_{v}")
    
    # Handle range date input robustly
    if isinstance(raw_date, (list, tuple)):
        qe_date = raw_date[0] if len(raw_date) > 0 else datetime.now().date()
    else:
        qe_date = raw_date
        
    # Suggestion / Narration
    unique_narrations = sorted(list(set([jv.get("narration", "").strip() for jv in d.get("journal_entries", []) if jv.get("narration", "").strip()])))
    if "-- Custom --" not in unique_narrations:
        unique_narrations = ["-- Custom --"] + unique_narrations
        
    sel_narr = st.selectbox("💡 Reuse Narration", unique_narrations, key=f"qe_sel_narr_{v}")
    
    if sel_narr == "-- Custom --":
        qe_narration = st.text_input("Narration / Description", value="", placeholder="Enter narration description...", key=f"qe_narr_txt_{v}")
    else:
        qe_narration = sel_narr
        st.info(f"Using narration: **{qe_narration}**")

    debit_options = [None] + accounts_list
    qe_debit_acc = st.selectbox(
        "📥 Debit Account (Paid to)",
        options=debit_options,
        index=0,
        format_func=format_account_label,
        key=f"qe_dr_acc_{v}"
    )

    credit_options = [None] + accounts_list
    qe_credit_acc = st.selectbox(
        "📤 Credit Account (Paid from)",
        options=credit_options,
        index=0,
        format_func=format_account_label,
        key=f"qe_cr_acc_{v}"
    )

    qe_amount = st.number_input(
        "Amount (INR)",
        min_value=0.01,
        step=50.0,
        format="%.2f",
        placeholder="0.00",
        key=f"qe_amt_{v}"
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    qe_submit = st.button("💾 Record Entry", key="btn_quick_post")

    if qe_submit:
        if not qe_narration.strip():
            st.error("⚠️ Narration is required.")
        elif not qe_credit_acc or not qe_debit_acc:
            st.error("⚠️ Please select both Credit and Debit accounts.")
        elif qe_debit_acc == qe_credit_acc:
            st.error("⚠️ Debit and Credit accounts must be different.")
        elif not qe_amount or qe_amount <= 0:
            st.error("⚠️ Enter a valid amount.")
        else:
            next_id = f"JV-{len(d.get('journal_entries', [])) + 1:05d}"
            lines = [
                {"account": qe_debit_acc, "debit": float(qe_amount), "credit": 0.0},
                {"account": qe_credit_acc, "debit": 0.0, "credit": float(qe_amount)}
            ]
            
            d["journal_entries"].append({
                "jv_id": next_id,
                "date": qe_date.strftime("%Y-%m-%d"),
                "narration": qe_narration.strip(),
                "lines": lines
            })
            
            if save_and_push():
                st.session_state.qe_form_version += 1
                st.success(f"✅ Posted Transaction {next_id} successfully!")
                st.rerun()
            else:
                st.error("❌ Failed to push data to cloud database. Try again.")# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — ADVANCED JV SPLITS EDITOR
# ─────────────────────────────────────────────────────────────────────────────
with tab_a:
    st.markdown("##### Advanced Journal Voucher Splits")
    
    v_adv = st.session_state.adv_form_version
    raw_jv_date = st.date_input("JV Date", value=datetime.now().date(), key=f"jv_new_date_{v_adv}")
    
    # Handle range date input robustly
    if isinstance(raw_jv_date, (list, tuple)):
        jv_date = raw_jv_date[0] if len(raw_jv_date) > 0 else datetime.now().date()
    else:
        jv_date = raw_jv_date
    
    unique_narrations = sorted(list(set([jv.get("narration", "").strip() for jv in d.get("journal_entries", []) if jv.get("narration", "").strip()])))
    if "-- Custom --" not in unique_narrations:
        unique_narrations = ["-- Custom --"] + unique_narrations
        
    sel_narr_a = st.selectbox("💡 Reuse Narration JV", unique_narrations, key=f"adv_sel_narr_{v_adv}")
    
    if sel_narr_a == "-- Custom --":
        jv_narration = st.text_input("Narration / Description", value="", placeholder="Salary split, grocery split...", key=f"adv_narr_txt_{v_adv}")
    else:
        jv_narration = sel_narr_a
        st.info(f"Using narration: **{jv_narration}**")

    if "new_jv_lines_list" not in st.session_state:
        st.session_state.new_jv_lines_list = [
            {"id": "row_1", "account": None, "debit": 0.0, "credit": 0.0},
            {"id": "row_2", "account": None, "debit": 0.0, "credit": 0.0}
        ]

    # Display splits as simple columns
    has_empty_account = False
    lines_to_save = []
    
    for idx in range(len(st.session_state.new_jv_lines_list)):
        line = st.session_state.new_jv_lines_list[idx]
        st.markdown(f"**Split Line #{idx + 1}**")
        
        account_options = [None] + accounts_list
        selected_acc = st.selectbox(
            f"Account Selection {idx}",
            options=account_options,
            index=0,
            format_func=format_account_label,
            key=f"adv_jv_acc_{v_adv}_{line['id']}"
        )
        line["account"] = selected_acc
        
        dr_c, cr_c = st.columns(2)
        with dr_c:
            debit_val = st.number_input(
                f"Debit Amount {idx}",
                min_value=0.0,
                value=float(line["debit"]),
                step=50.0,
                format="%.2f",
                key=f"adv_jv_dr_{v_adv}_{line['id']}"
            )
            line["debit"] = debit_val
            
        with cr_c:
            credit_val = st.number_input(
                f"Credit Amount {idx}",
                min_value=0.0,
                value=float(line["credit"]),
                step=50.0,
                format="%.2f",
                key=f"adv_jv_cr_{v_adv}_{line['id']}"
            )
            line["credit"] = credit_val
            
        if st.button("🗑️ Remove Line", key=f"adv_jv_del_{line['id']}"):
            st.session_state.new_jv_lines_list.pop(idx)
            st.rerun()
            
        if (debit_val > 0 or credit_val > 0) and selected_acc is None:
            has_empty_account = True
            
        if selected_acc is not None and (debit_val > 0 or credit_val > 0):
            lines_to_save.append({
                "account": selected_acc,
                "debit": debit_val,
                "credit": credit_val
            })
        st.markdown("---")

    if st.button("➕ Add Split Line"):
        st.session_state.new_jv_lines_list.append({
            "id": f"row_{datetime.now().timestamp()}_{len(st.session_state.new_jv_lines_list)}",
            "account": None,
            "debit": 0.0,
            "credit": 0.0
        })
        st.rerun()

    total_debit = sum(l["debit"] for l in st.session_state.new_jv_lines_list)
    total_credit = sum(l["credit"] for l in st.session_state.new_jv_lines_list)
    balance_diff = total_debit - total_credit

    st.markdown(f"**Total Debits**: ₹{total_debit:,.2f} | **Total Credits**: ₹{total_credit:,.2f}")
    
    is_balanced = abs(balance_diff) < 0.01 and total_debit > 0
    if is_balanced:
        st.success("✅ JV is balanced perfectly and ready to post.")
        if has_empty_account:
            st.warning("⚠️ Select account names for all non-zero amounts.")
            
        if st.button("💾 Record Journal Voucher", disabled=has_empty_account, key="btn_post_jv"):
            next_id = f"JV-{len(d.get('journal_entries', [])) + 1:05d}"
            
            d["journal_entries"].append({
                "jv_id": next_id,
                "date": jv_date.strftime("%Y-%m-%d"),
                "narration": jv_narration.strip() if jv_narration.strip() else "Manual JV Splits",
                "lines": lines_to_save
            })
            
            if save_and_push():
                st.session_state.new_jv_lines_list = [
                    {"id": "row_1", "account": None, "debit": 0.0, "credit": 0.0},
                    {"id": "row_2", "account": None, "debit": 0.0, "credit": 0.0}
                ]
                st.session_state.adv_form_version += 1
                st.success(f"✅ Journal Voucher {next_id} posted successfully!")
                st.rerun()
            else:
                st.error("❌ Failed to push data to cloud database.")
    elif total_debit == 0 and total_credit == 0:
        st.info("💡 Add debit and credit splits above.")
    else:
        st.error(f"❌ Difference is ₹{abs(balance_diff):,.2f}. Entry must balance.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — CLOUD SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
with tab_settings:
    st.markdown("##### Cloud Sync settings")
    st.write(f"Connected to Database URL: `{st.session_state.cloud_url}`")
    
    if st.button("⚙️ Disconnect & Change Credentials", use_container_width=True):
        st.session_state.cloud_url = ""
        st.session_state.cloud_secret = ""
        st.session_state.ledger_data = None
        st.rerun()
