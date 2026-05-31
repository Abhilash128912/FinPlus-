import os

# SQLite Database Settings
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_journal.db")

# Default Brokerage Rates (Per Buy and Per Sell)
DEFAULT_BROKERAGE = {
    "Equity - Delivery": {"buy": 0.0, "sell": 0.0},
    "Equity - Intraday": {"buy": 20.0, "sell": 20.0},
    "F&O - Index Futures": {"buy": 20.0, "sell": 20.0},
    "F&O - Index Options": {"buy": 20.0, "sell": 20.0},
    "F&O - Stock Options": {"buy": 30.0, "sell": 30.0},
    "Commodities": {"buy": 45.0, "sell": 45.0}
}

# Standard Tax Rates (Indian Stock Market)
# Can be updated by the user through settings and persists in DB.
DEFAULT_TAX_RATES = {
    "Equity - Delivery": {
        "stt_buy_pct": 0.1,         # 0.1% on buy
        "stt_sell_pct": 0.1,        # 0.1% on sell
        "exc_charge_pct": 0.00297,  # NSE Exchange transaction charge
        "sebi_pct": 0.0001,         # Rs 10 per crore (0.0001%)
        "stamp_buy_pct": 0.015,     # 0.015% on buy
        "gst_pct": 18.0,            # 18% GST on (Brokerage + Exchange + SEBI)
    },
    "Equity - Intraday": {
        "stt_buy_pct": 0.0,
        "stt_sell_pct": 0.025,      # 0.025% on sell only
        "exc_charge_pct": 0.00297,
        "sebi_pct": 0.0001,
        "stamp_buy_pct": 0.003,     # 0.003% on buy only
        "gst_pct": 18.0,
    },
    "F&O - Index Futures": {
        "stt_buy_pct": 0.0,
        "stt_sell_pct": 0.0125,     # 0.0125% on sell side turnover
        "exc_charge_pct": 0.0019,   # 0.0019% of turnover
        "sebi_pct": 0.0001,
        "stamp_buy_pct": 0.002,     # 0.002% on buy side
        "gst_pct": 18.0,
    },
    "F&O - Index Options": {
        "stt_buy_pct": 0.0,
        "stt_sell_pct": 0.0625,     # 0.0625% on sell premium
        "exc_charge_pct": 0.05,     # 0.05% on premium
        "sebi_pct": 0.0001,
        "stamp_buy_pct": 0.003,     # 0.003% on buy premium
        "gst_pct": 18.0,
    },
    "F&O - Stock Options": {
        "stt_buy_pct": 0.0,
        "stt_sell_pct": 0.0625,     # 0.0625% on sell premium
        "exc_charge_pct": 0.05,     # 0.05% on premium
        "sebi_pct": 0.0001,
        "stamp_buy_pct": 0.003,     # 0.003% on buy premium
        "gst_pct": 18.0,
    },
    "Commodities": {
        "stt_buy_pct": 0.0,
        "stt_sell_pct": 0.01,       # CTT 0.01% on sell futures
        "exc_charge_pct": 0.0026,   # MCX Exchange charge
        "sebi_pct": 0.0001,
        "stamp_buy_pct": 0.002,     # Stamp duty buy side
        "gst_pct": 18.0,
    }
}

# Supported strategies and emotional trading mistakes
DEFAULT_STRATEGIES = [
    "Breakout", 
    "Breakdown",
    "Pullback / Retest", 
    "Support / Resistance Bounce", 
    "Moving Average Crossover", 
    "VWAP Pullback", 
    "Trend Following", 
    "Mean Reversion",
    "Scalping",
    "News Based"
]

DEFAULT_MISTAKES = [
    "None",
    "FOMO Entry",
    "Overtrading",
    "Revenge Trading",
    "Early Exit (Fear)",
    "Wide Stop Loss (Greed)",
    "Averaging Down on Loser",
    "Rule Violation",
    "No Stop Loss set"
]
