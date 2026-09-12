"""
Per-instrument configuration for the two MCX energy contracts.

Crude oil and natural gas are NOT the same trade wearing two tickers, and
until now the signal model treated them as if they were -- both ran on the
single INTRADAY_SR_GATES profile in signal_engine.py. Natural gas is the
most volatile of the mainstream commodities: EIA-storage Thursdays, winter
heating / summer power-burn demand, hurricane supply scares, and a much
higher day-to-day ATR mean it produces far more failed breaks and needs a
wider stop and heavier volume confirmation than crude before a level is
worth trusting. Crude is calmer and more mean-reverting intraday. Giving
each its own gate profile is the single cheapest accuracy gain available.

Contract specs are the real MCX front-month (big) lots -- the same contract
mcx_feed.fetch_mcx_futures() selects (front month by volume of the CRUDEOIL
/ NATURALGAS symbol). Mini specs are recorded too so position_size() can
suggest the mini contract when one big lot overshoots the risk budget.
"""
from __future__ import annotations

import math

# Base profile = signal_engine.INTRADAY_SR_GATES, kept in sync by intent:
# same-day trades judged against same-day reference points, previous-day
# level breaks enabled. Each instrument then overrides what its own
# volatility demands. Only keys that differ from sr_volume.GATES are set;
# signal_engine merges these over the base gates.
CRUDE_GATES: dict = {
    "max_stop_pct": 2.5,
    "min_reward_risk": 1.5,
    "max_target_pct": 3.0,
    "use_prev_day_levels": True,
    # Crude's intraday breaks are more often real than gas's, but a fake
    # breakout is still the thing to avoid: keep the base 1.5x break gate.
    "min_break_vol_ratio": 1.5,
    "min_turn_vol_ratio": 1.1,
}

NATGAS_GATES: dict = {
    # Gas routinely travels 3-5% in a session; a 2.5% stop is inside the
    # noise and gets taken out before the thesis plays. Widen the whole
    # geometry and demand more volume behind a break before believing it.
    "max_stop_pct": 3.5,
    "min_reward_risk": 1.4,
    "max_target_pct": 5.0,
    "use_prev_day_levels": True,
    "min_break_vol_ratio": 1.8,
    "min_turn_vol_ratio": 1.25,
}

GATES_BY_SYMBOL = {"CRUDEOIL": CRUDE_GATES, "NATURALGAS": NATGAS_GATES}


# MCX contract specifications. `unit_per_lot` is how many priced units
# (barrels / mmBtu) one lot controls, so rupee risk on a trade is
# stop_distance_in_rupees * unit_per_lot * lots. `tick` is the minimum
# price increment (₹/unit). Values are the long-standing MCX energy specs;
# if the exchange revises a lot size the feed's own `mcx_unit` field is the
# authority and position_size() will note a mismatch rather than mislead.
CONTRACT_SPECS = {
    "CRUDEOIL": {
        "name": "Crude Oil",
        "unit": "barrel",
        "unit_per_lot": 100,
        "tick": 1.0,
        "mini": {"symbol": "CRUDEOILM", "unit_per_lot": 10},
    },
    "NATURALGAS": {
        "name": "Natural Gas",
        "unit": "mmBtu",
        "unit_per_lot": 1250,
        "tick": 0.10,
        "mini": {"symbol": "NATURALGASM", "unit_per_lot": 250},
    },
}

# Default rupee risk budget per trade. Deliberately conservative; the UI /
# caller can override. This is a *suggestion* input, never an instruction to
# trade -- the app makes no sizing decision on the user's behalf.
DEFAULT_RISK_BUDGET_INR = 5000.0


def gates_for(mcx_symbol: str) -> dict:
    """The gate overrides for a symbol, or an empty dict (base gates) if the
    symbol is unknown -- an unrecognised instrument should fall back to the
    conservative base, not crash."""
    return dict(GATES_BY_SYMBOL.get(mcx_symbol, {}))


def position_size(mcx_symbol: str, entry: float | None, stop: float | None,
                  risk_budget_inr: float = DEFAULT_RISK_BUDGET_INR) -> dict | None:
    """How many lots keep the loss-at-stop within `risk_budget_inr`.

    Returns None when the inputs can't produce an honest number (no entry,
    no stop, zero distance, unknown contract) -- a sizing suggestion built
    on a missing stop is worse than none. The result reports the big-lot
    count and, when even one big lot exceeds the budget, the mini-lot
    alternative, so the user always sees a tradeable size or an explicit
    "one lot already risks ₹X, above your ₹Y budget" warning.
    """
    spec = CONTRACT_SPECS.get(mcx_symbol)
    if not spec or entry is None or stop is None:
        return None
    dist = abs(float(entry) - float(stop))
    if dist <= 0:
        return None

    def risk_per_lot(units):
        return dist * units

    big_units = spec["unit_per_lot"]
    big_risk = risk_per_lot(big_units)
    big_lots = int(math.floor(risk_budget_inr / big_risk)) if big_risk > 0 else 0

    out = {
        "risk_budget_inr": round(risk_budget_inr, 0),
        "stop_distance": round(dist, 2),
        "unit": spec["unit"],
        "risk_per_big_lot": round(big_risk, 0),
        "big_lots": big_lots,
        "big_lot_units": big_units,
    }
    if big_lots >= 1:
        out["suggested"] = f"{big_lots} lot{'s' if big_lots > 1 else ''}"
        out["suggested_risk"] = round(big_risk * big_lots, 0)
    else:
        mini = spec.get("mini")
        if mini:
            mini_risk = risk_per_lot(mini["unit_per_lot"])
            mini_lots = int(math.floor(risk_budget_inr / mini_risk)) if mini_risk > 0 else 0
            out["mini_symbol"] = mini["symbol"]
            out["mini_lots"] = mini_lots
            out["risk_per_mini_lot"] = round(mini_risk, 0)
            if mini_lots >= 1:
                out["suggested"] = f"{mini_lots} {mini['symbol']} mini lot{'s' if mini_lots > 1 else ''}"
                out["suggested_risk"] = round(mini_risk * mini_lots, 0)
            else:
                out["suggested"] = None
                out["note"] = (f"One {mini['symbol']} mini lot risks ₹{mini_risk:,.0f}, "
                               f"above the ₹{risk_budget_inr:,.0f} budget")
        else:
            out["suggested"] = None
            out["note"] = f"One lot risks ₹{big_risk:,.0f}, above the ₹{risk_budget_inr:,.0f} budget"
    return out
