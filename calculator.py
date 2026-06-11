from typing import Dict, Any
from config import DEFAULT_TAX_RATES

def calculate_trade_metrics(
    segment: str,
    action: str,  # "BUY" (Long: Buy then Sell) or "SELL" (Short: Sell then Buy)
    quantity: float,
    entry_price: float,
    exit_price: float,
    brokerage_input: float,  # Overridden or default brokerage (total, or buy+sell)
    tax_rates: Dict[str, Any] = None
) -> Dict[str, float]:
    """
    Calculates detailed taxes, charges, and PNL for a trade.
    
    Taxes follow standard Indian Market rules (NSE / MCX).
    Stamp Duty is charged on the BUY side.
    STT is charged on the SELL side (except Equity Delivery, where it's on both).
    Exchange charges & SEBI fees are charged on both BUY and SELL (Total Turnover).
    GST is 18% of (Brokerage + Exchange Charges + SEBI Fees).
    """
    if tax_rates is None:
        tax_rates = DEFAULT_TAX_RATES.get(segment, {})

    # 1. Turnover Calculations
    buy_turnover = quantity * (entry_price if action == "BUY" else exit_price)
    sell_turnover = quantity * (exit_price if action == "BUY" else entry_price)
    total_turnover = buy_turnover + sell_turnover

    # 2. Brokerage
    # Brokerage is taken directly from user input, but forced to 0.0 for Equity - Delivery
    if segment == "Equity - Delivery":
        brokerage = 0.0
    else:
        brokerage = brokerage_input

    # 3. STT / CTT (Securities / Commodity Transaction Tax)
    stt = 0.0
    if segment == "Equity - Delivery":
        # 0.1% on Buy and 0.1% on Sell
        stt_buy_rate = tax_rates.get("stt_buy_pct", 0.1) / 100.0
        stt_sell_rate = tax_rates.get("stt_sell_pct", 0.1) / 100.0
        stt = (buy_turnover * stt_buy_rate) + (sell_turnover * stt_sell_rate)
    elif segment in ["Equity - Intraday", "Commodities"]:
        # Intraday (0.025% on sell) / Commodities (CTT 0.01% on sell futures)
        stt_sell_rate = tax_rates.get("stt_sell_pct", 0.0) / 100.0
        stt = sell_turnover * stt_sell_rate
    elif segment == "F&O - Index Futures":
        # Futures (0.0125% on sell)
        stt_sell_rate = tax_rates.get("stt_sell_pct", 0.0125) / 100.0
        stt = sell_turnover * stt_sell_rate
    elif segment in ["F&O - Index Options", "F&O - Stock Options"]:
        # Options (0.0625% on sell premium)
        stt_sell_rate = tax_rates.get("stt_sell_options_pct", tax_rates.get("stt_sell_pct", 0.0625)) / 100.0
        stt = sell_turnover * stt_sell_rate

    # 4. Exchange Transaction Charges
    exc_rate = 0.0
    if segment in ["F&O - Index Options", "F&O - Stock Options"]:
        exc_rate = tax_rates.get("exc_charge_options_pct", tax_rates.get("exc_charge_pct", 0.05)) / 100.0
    elif segment == "F&O - Index Futures":
        exc_rate = tax_rates.get("exc_charge_pct", 0.0019) / 100.0
    else:
        exc_rate = tax_rates.get("exc_charge_pct", 0.0) / 100.0
    
    exchange_charges = total_turnover * exc_rate

    # 5. SEBI Turnover Charges (Rs 10 / Crore = 0.0001% of total turnover)
    sebi_rate = tax_rates.get("sebi_pct", 0.0001) / 100.0
    sebi_charges = total_turnover * sebi_rate

    # 6. Stamp Duty (Charged on BUY side turnover only)
    stamp_rate = 0.0
    if segment in ["F&O - Index Options", "F&O - Stock Options"]:
        stamp_rate = tax_rates.get("stamp_buy_options_pct", tax_rates.get("stamp_buy_pct", 0.003)) / 100.0
    elif segment == "F&O - Index Futures":
        stamp_rate = tax_rates.get("stamp_buy_futures_pct", tax_rates.get("stamp_buy_pct", 0.002)) / 100.0
    else:
        stamp_rate = tax_rates.get("stamp_buy_pct", 0.0) / 100.0
        
    stamp_duty = buy_turnover * stamp_rate

    # 7. GST (18% on Brokerage + Exchange Charges + SEBI Charges)
    gst_rate = tax_rates.get("gst_pct", 18.0) / 100.0
    gst = (brokerage + exchange_charges + sebi_charges) * gst_rate

    # 8. Summary of Charges
    total_charges = brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst

    # 9. PNL Calculations
    # Gross PNL
    if action == "BUY":
        # Long trade: Exit - Entry
        gross_pnl = (exit_price - entry_price) * quantity
    else:
        # Short trade: Entry - Exit
        gross_pnl = (entry_price - exit_price) * quantity
        
    net_pnl = gross_pnl - total_charges

    return {
        "turnover": round(total_turnover, 2),
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_charges": round(exchange_charges, 2),
        "sebi_charges": round(sebi_charges, 2),
        "stamp_duty": round(stamp_duty, 2),
        "gst": round(gst, 2),
        "total_charges": round(total_charges, 2),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2)
    }
