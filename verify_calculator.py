from calculator import calculate_trade_metrics

def test_calculator():
    print("==================================================")
    print("RUNNING PRECISION TAX CALCULATOR AUDIT")
    print("==================================================")
    
    # Test Scenario 1: Equity Intraday (Long Trade)
    # 100 Qty, Buy at 1000, Sell at 1010, Brokerage Rs 40 (Flat 20 buy + 20 sell)
    metrics_intraday = calculate_trade_metrics(
        segment="Equity - Intraday",
        action="BUY",
        quantity=100,
        entry_price=1000.0,
        exit_price=1010.0,
        brokerage_input=40.0
    )
    
    print("\nScenario 1: Equity Intraday (Long) - 100 Qty, Buy 1000 / Sell 1010")
    print(f"  Turnover Value  : {metrics_intraday['turnover']} (Expected: 201000.00)")
    print(f"  Brokerage Cost  : {metrics_intraday['brokerage']} (Expected: 40.00)")
    print(f"  STT (Sell side) : {metrics_intraday['stt']} (Expected: 25.25)")
    print(f"  Exchange Fee    : {metrics_intraday['exchange_charges']} (Expected: 5.97)")
    print(f"  SEBI Fee        : {metrics_intraday['sebi_charges']} (Expected: 0.20)")
    print(f"  Stamp Duty (Buy): {metrics_intraday['stamp_duty']} (Expected: 3.00)")
    print(f"  GST (18% on fees): {metrics_intraday['gst']} (Expected: 8.31)")
    print(f"  Total Charges   : {metrics_intraday['total_charges']} (Expected: 82.73)")
    print(f"  Gross PNL       : {metrics_intraday['gross_pnl']} (Expected: 1000.00)")
    print(f"  Net PNL         : {metrics_intraday['net_pnl']} (Expected: 917.27)")
    
    assert abs(metrics_intraday['turnover'] - 201000.00) < 0.1
    assert abs(metrics_intraday['stt'] - 25.25) < 0.1
    assert abs(metrics_intraday['exchange_charges'] - 5.97) < 0.1
    assert abs(metrics_intraday['stamp_duty'] - 3.00) < 0.1
    assert abs(metrics_intraday['total_charges'] - 82.73) < 0.1
    assert abs(metrics_intraday['net_pnl'] - 917.27) < 0.1
    print(" [OK] Scenario 1 Passed Successfully!")

    # Test Scenario 2: Equity Delivery (Long Trade, High Volume)
    # 50 Qty, Buy at 3000, Sell at 3100, Brokerage Free
    metrics_delivery = calculate_trade_metrics(
        segment="Equity - Delivery",
        action="BUY",
        quantity=50,
        entry_price=3000.0,
        exit_price=3100.0,
        brokerage_input=0.0
    )
    
    print("\nScenario 2: Equity Delivery (Long) - 50 Qty, Buy 3000 / Sell 3100")
    print(f"  Turnover Value  : {metrics_delivery['turnover']}")
    print(f"  STT (Buy+Sell)  : {metrics_delivery['stt']} (Expected: 305.00)")
    print(f"  Stamp Duty (Buy): {metrics_delivery['stamp_duty']} (Expected: 22.50)")
    print(f"  Exchange Fee    : {metrics_delivery['exchange_charges']}")
    print(f"  GST (18% on fees): {metrics_delivery['gst']}")
    print(f"  Total Charges   : {metrics_delivery['total_charges']}")
    print(f"  Net PNL         : {metrics_delivery['net_pnl']}")
    
    assert abs(metrics_delivery['stt'] - 305.00) < 0.1
    assert abs(metrics_delivery['stamp_duty'] - 22.50) < 0.1
    print(" [OK] Scenario 2 Passed Successfully!")

    # Test Scenario 3: F&O Options (Short Trade)
    # 500 Qty, Sell (Short Entry) at 100.0, Buy (Short Exit) at 80.0, Brokerage flat Rs 60
    metrics_options = calculate_trade_metrics(
        segment="F&O - Index Options",
        action="SELL",
        quantity=500,
        entry_price=100.0,
        exit_price=80.0,
        brokerage_input=60.0
    )
    
    print("\nScenario 3: F&O Index Options (Short) - 500 Qty, Entry 100 / Exit 80")
    print(f"  Turnover Value  : {metrics_options['turnover']}")
    # STT on sell side premium (entry is Sell in a Short trade)
    # Sell side turnover = 500 * 100 = 50,000. STT = 0.0625% of 50,000 = 31.25
    print(f"  STT (Sell premium): {metrics_options['stt']} (Expected: 31.25)")
    # Stamp Duty on buy side premium (exit is Buy in a Short trade)
    # Buy side turnover = 500 * 80 = 40,000. Stamp Duty = 0.003% of 40,000 = 1.20
    print(f"  Stamp Duty (Buy)  : {metrics_options['stamp_duty']} (Expected: 1.20)")
    print(f"  Exchange Fee (0.05%): {metrics_options['exchange_charges']} (Expected: 45.00)")
    print(f"  Total Charges     : {metrics_options['total_charges']}")
    print(f"  Gross PNL (Short) : {metrics_options['gross_pnl']} (Expected: 10000.00)")
    print(f"  Net PNL           : {metrics_options['net_pnl']}")
    
    assert abs(metrics_options['stt'] - 31.25) < 0.1
    assert abs(metrics_options['stamp_duty'] - 1.20) < 0.1
    assert abs(metrics_options['exchange_charges'] - 45.00) < 0.1
    assert abs(metrics_options['gross_pnl'] - 10000.00) < 0.1
    print(" [OK] Scenario 3 Passed Successfully!")

    print("\n==================================================")
    print("ALL PRECISION AUDIT SCENARIOS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    test_calculator()
