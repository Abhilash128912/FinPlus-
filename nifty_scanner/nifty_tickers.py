import pandas as pd
import os
import streamlit as st

# Predefined fallback list of top Nifty 100/major tickers in case network is down
FALLBACK_TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
    "BHARTIARTL.NS", "SBI.NS", "LICI.NS", "ITC.NS", "HINDUNILVR.NS",
    "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "ADANIENT.NS", "KOTAKBANK.NS", "TATAMOTORS.NS", "AXISBANK.NS", "NTPC.NS",
    "ONGC.NS", "COALINDIA.NS", "ADANIPORTS.NS", "POWERGRID.NS", "TITAN.NS",
    "ULTRACEMCO.NS", "M&M.NS", "BAJAJFINSV.NS", "SBILIFE.NS", "BPCL.NS",
    "WIPRO.NS", "GRASIM.NS", "JSWSTEEL.NS", "HINDALCO.NS", "ADANIPOWER.NS",
    "TATASTEEL.NS", "LTIM.NS", "NESTLEIND.NS", "IOC.NS", "HAL.NS",
    "BAJAJ-AUTO.NS", "INDUSINDBK.NS", "DLF.NS", "VBL.NS", "PFC.NS",
    "RECL.NS", "BEL.NS", "SIEMENS.NS", "IRFC.NS", "CIPLA.NS",
    "TRENT.NS", "TATACOMM.NS", "HAVELLS.NS", "TATACONSUM.NS", "PIDILITIND.NS",
    "DRREDDY.NS", "GAIL.NS", "PNB.NS", "SHRIRAMFIN.NS", "APOLLOHOSP.NS",
    "BPCL.NS", "CANBK.NS", "TV18BRDCST.NS", "ZOMATO.NS", "JIOFIN.NS"
]

# Accurate list of active NSE F&O underlying symbols
FNO_UNDERLYINGS = {
    "360ONE", "ABB", "ABCAPITAL", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS", "ADANIPOWER",
    "ALKEM", "AMBER", "AMBUJACEM", "ANGELONE", "APLAPOLLO", "APOLLOHOSP", "ASHOKLEY", "ASIANPAINT",
    "ASTRAL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJAJHLDNG", "BAJFINANCE",
    "BANDHANBNK", "BANKBARODA", "BANKINDIA", "BANKNIFTY", "BDL", "BEL", "BHARATFORG", "BHARTIARTL",
    "BHEL", "BIOCON", "BLUESTARCO", "BOSCHLTD", "BPCL", "BRITANNIA", "BSE", "CAMS",
    "CANBK", "CDSL", "CGPOWER", "CHOLAFIN", "CIPLA", "COALINDIA", "COCHINSHIP", "COFORGE",
    "COLPAL", "CONCOR", "CROMPTON", "CUMMINSIND", "DABUR", "DALBHARAT", "DELHIVERY", "DIVISLAB",
    "DIXON", "DLF", "DMART", "DRREDDY", "EICHERMOT", "ETERNAL", "EXIDEIND", "FEDERALBNK",
    "FINNIFTY", "FORCEMOT", "FORTIS", "GAIL", "GLENMARK", "GMRAIRPORT", "GODFRYPHLP", "GODREJCP",
    "GODREJPROP", "GRASIM", "GVT&D", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDPETRO", "HINDUNILVR", "HINDZINC", "HYUNDAI", "ICICIBANK",
    "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "INDHOTEL", "INDIANB", "INDIGO",
    "INDUSINDBK", "INDUSTOWER", "INFY", "INOXWIND", "IOC", "IREDA", "IRFC", "ITC",
    "JINDALSTEL", "JIOFIN", "JSWENERGY", "JSWSTEEL", "JUBLFOOD", "KALYANKJIL", "KAYNES", "KEI",
    "KFINTECH", "KOTAKBANK", "KPITTECH", "LAURUSLABS", "LICHSGFIN", "LICI", "LODHA", "LT",
    "LTF", "LTM", "LUPIN", "M&M", "MANAPPURAM", "MANKIND", "MARICO", "MARUTI",
    "MAXHEALTH", "MAZDOCK", "MCX", "MFSL", "MIDCPNIFTY", "MOTHERSON", "MOTILALOFS", "MPHASIS",
    "MUTHOOTFIN", "NAM-INDIA", "NATIONALUM", "NAUKRI", "NBCC", "NESTLEIND", "NHPC", "NIFTY",
    "NIFTYNXT50", "NMDC", "NTPC", "NUVAMA", "NYKAA", "OBEROIRLTY", "OFSS", "OIL",
    "ONGC", "PAGEIND", "PATANJALI", "PAYTM", "PERSISTENT", "PETRONET", "PFC", "PGEL",
    "PHOENIXLTD", "PIDILITIND", "PIIND", "PNB", "PNBHOUSING", "POLICYBZR", "POLYCAB", "POWERGRID",
    "POWERINDIA", "PREMIERENE", "PRESTIGE", "RADICO", "RBLBANK", "RECLTD", "RELIANCE", "RVNL",
    "SAIL", "SAMMAANCAP", "SBICARD", "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS",
    "SOLARINDS", "SONACOMS", "SRF", "SUNPHARMA", "SUPREMEIND", "SUZLON", "SWIGGY", "TATACONSUM",
    "TATAELXSI", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TIINDIA", "TITAN", "TMPV",
    "TORNTPHARM", "TRENT", "TVSMOTOR", "ULTRACEMCO", "UNIONBANK", "UNITDSPR", "UNOMINDA", "UPL",
    "VBL", "VEDL", "VMM", "VOLTAS", "WAAREEENER", "WIPRO", "YESBANK", "ZYDUSLIFE"
}

def get_nifty500_tickers() -> list:
    """
    Downloads the official Nifty 500 constituent list from NSE India dynamically.
    Falls back to a robust static list of top NSE leaders if network request fails.
    """
    csv_url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    
    try:
        # Use custom headers to avoid bot detection blocks by NSE archives
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        import urllib.request
        req = urllib.request.Request(csv_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            df = pd.read_csv(response)
            
        if "Symbol" in df.columns:
            # Format to Yahoo Finance ticker style (.NS)
            tickers = [f"{sym.strip().replace('&', '%26')}.NS" for sym in df["Symbol"].dropna().tolist()]
            return tickers
    except Exception as e:
        # Silently catch and use fallback
        pass
        
    return FALLBACK_TICKERS

def get_fno_symbols() -> set:
    """
    Returns the set of active F&O underlying symbols.
    """
    return FNO_UNDERLYINGS
