"""Volume-backed support/resistance signals.

The trading idea, in one place: a level only counts if real money built it, and
the trade is taken when price returns to that level and turns away from it.

    support built on buying volume    + price turns up off it   -> BUY
    resistance built on selling volume + price turns down off it -> SELL

This borrows the ChartPrime construction -- pivots filtered by delta volume, ATR-
wide boxes -- but not its signal logic. That script fires when price *crosses* a
box edge, which is the opposite trade: it treats the level as something being
abandoned. Here the level is where the position is entered, because a level that
absorbed real volume is where the next move is defended from.

Targets come from the opposite box rather than a flat percentage. That matters:
on the 04 Sep intraday set, four of five longs carried a +1.5% T1 while sitting
0.7-1.6% below 1h resistance, asking price to travel straight through the level
most likely to stop it.
"""

import numpy as np
import pandas as pd

GATES: dict = {
    "pivot_lookback": 20,      # bars either side of a pivot (ChartPrime's default)
    "vol_len": 2,              # delta-volume comparison window
    "atr_period": 200,
    "box_atr_mult": 1.0,       # box depth, in ATR
    # How close to a level counts as a touch, as a multiple of box depth. Measured
    # across 100 liquid names, the median distance to the nearest volume-backed
    # level is 4.67 depths and the 25th percentile is 2.29, so a 1.0 window rejects
    # roughly three-quarters of genuinely level-adjacent setups and yielded one
    # signal in a hundred. 2.0 keeps "at the level" meaningful while admitting the
    # approach, which on a 1h chart is where the position is actually taken.
    "near_box_mult": 2.0,
    # The turn must carry volume or it is drift, not a defence of the level.
    # Measured against the recent average rather than an absolute.
    "min_turn_vol_ratio": 1.1,
    "vol_avg_window": 20,
    "min_bars": 60,
    # Bars to look back for the touch. Proximity has to be measured from how close
    # price *came* to the level, not where it sits now: the turn that makes the
    # setup is itself a move away from the level, so measuring from the current
    # close rejects exactly the setups being looked for.
    "touch_lookback": 3,
    # A level-based stop can sit an ATR below a level that is itself far from
    # price, which on FLUOROCHEM produced a 6.46% stop -- not an intraday stop at
    # any size. None disables the cap for holding horizons that can absorb it.
    "max_stop_pct": None,
    # The opposite level is where the trade is going, so if it is nearer than the
    # stop the setup is upside-down however clean it looks. FLUOROCHEM risked
    # 6.46% to make 2.33%; INDHOTEL 2.81% to make 0.90%.
    "min_reward_risk": None,
    # The opposite level can be a swing move away: DRREDDY's next resistance sat
    # +21.65% off, which is not a same-day target however real the level is. Capping
    # it keeps the reward figure honest for the horizon being traded; the untouched
    # level is still reported as srv_level_target.
    "max_target_pct": None,
    # What counts as a turn. "close > open, or close > the last close" admits a
    # doji and a one-tick drift: TATACHEM printed a 0.07 body/range doji at support
    # and then a 0.65 rupee (+0.10%) bar, and was called a BUY while flat on the
    # day. A level being defended looks like a decisive bar, not a pause.
    "min_body_range": 0.40,       # doji filter: body as a share of the bar's range
    "min_close_position": 0.60,   # close must sit in the top 40% of the range (buy)
    "min_turn_atr": 0.25,         # and cover real distance, in box depths
    # Previous day's high and low. Intraday trades against these constantly and a
    # 60-day pivot scan cannot see them: TATACHEM spent a session under a 630.00
    # previous-day low, 1.96% down and never reclaiming it, while its nearest
    # volume pivot sat at 624.00 -- still below price, so the model said nothing.
    # A break of the level held through the session is the signal, not a poke.
    "use_prev_day_levels": False,
    # A stop exactly on the broken level is a 25-paise stop that any tick reclaims,
    # and it flatters reward:risk into meaninglessness -- TATACHEM showed 23.0 on a
    # 0.04% risk. The stop belongs beyond the level by a fraction of a box depth.
    "break_stop_atr": 0.5,
    # A break with no volume behind it is the fake breakout this whole model exists
    # to avoid: price slips past a level on nothing and snaps back. Bounces were
    # gated on volume from the start and breaks were not, which was an omission --
    # breaks are exactly where the trap lives. Measured on the heaviest completed
    # hour of the session, since the break itself is what needed participation.
    # TATACHEM broke 630.00 on 303,146 against a 60,929 average: 4.98x.
    "min_break_vol_ratio": 1.5,
}

NO_SIGNAL = {
    "srv_available": False,
    "srv_signal": "NONE",
    "srv_strength": 0.0,
    "srv_support": None,
    "srv_resistance": None,
    "srv_reason": "",
}


def strip_forming_bars(d):
    """Drop trailing synthetic bars so the turn is judged on completed candles.

    The 1h feed stamps the live price as a bar of its own -- zero volume, and
    open=high=low=close. Left in, it is the bar every signal gets judged on: its
    volume ratio is always 0, so the volume gate could never pass and the model
    returned no signal for any symbol. Its direction is meaningless too, since
    open and close are the same tick.

    Also drops any other zero-volume trailing bars (holidays, feed gaps), which
    are not comparable to a real hour's volume either.
    """
    while len(d) > 1:
        last = d.iloc[-1]
        degenerate = (
            float(last["Volume"]) <= 0
            or (last["Open"] == last["High"] == last["Low"] == last["Close"])
        )
        if not degenerate:
            break
        d = d.iloc[:-1]
    return d


def last_bar_volume_run_rate(d, cap_scale: float = 6.0):
    """Last bar's volume, scaled to a whole bar when that bar is still forming.

    Comparing a part-formed hour against an average of complete hours understates
    it by exactly the fraction of the hour still to come, and that is not a small
    effect: at 10:37 the 10:15 bar is a third elapsed, so TATACHEM's 25,245 read as
    0.44x its 56,847 average purely because the hour was young. Every symbol failed
    the volume gate for the same reason, which is why the model produced almost no
    signals during market hours and widening the proximity window changed nothing.

    Scaling to a run rate compares like with like. The scale-up is capped because
    the first minutes of a bar divide by a very small number, which would turn a
    handful of early trades into an apparent volume surge.
    """
    v = float(d["Volume"].values[-1])
    try:
        idx = d.index
        last_ts = idx[-1]
        if getattr(last_ts, "tzinfo", None) is None and not hasattr(last_ts, "to_pydatetime"):
            return v
        bar_sec = float(pd.Series(idx).diff().dt.total_seconds().median())
        if not (bar_sec > 0):
            return v
        now_ts = pd.Timestamp.now(tz=last_ts.tz) if last_ts.tzinfo else pd.Timestamp.now()
        elapsed = (now_ts - last_ts).total_seconds()
        if 0 < elapsed < bar_sec:
            v *= min(cap_scale, bar_sec / elapsed)
    except Exception:
        pass
    return v


def delta_volume(opens, closes, volumes):
    """Volume signed by candle direction, carrying the last direction through a doji."""
    out = np.zeros(len(closes))
    is_buy = True
    for i in range(len(closes)):
        if closes[i] > opens[i]:
            is_buy = True
        elif closes[i] < opens[i]:
            is_buy = False
        out[i] = volumes[i] if is_buy else -volumes[i]
    return out


def find_volume_levels(o, h, l, c, v, g, price):
    """Nearest volume-backed support below price, and resistance above it.

    Collects every pivot that cleared its delta-volume filter, then picks the ones
    price is actually trading against: the highest qualifying low at or below it,
    and the lowest qualifying high at or above it.

    Taking the most *recent* qualifying pivot instead -- the obvious reading, and
    what this did first -- produces levels price left behind long ago. HAVELLS came
    back with support at 1254.30 while trading at 1164.30: a level it had broken
    weeks earlier, so no signal could ever fire against it. Recency still counts,
    but as a tiebreak through `age` in the strength score, not as the selector.

    Returns (support, resistance) dicts of level/delta-volume/age, either possibly
    None. A level with no volume behind it is deliberately not substituted for --
    an invented level produces invented signals.
    """
    n = len(c)
    dv = delta_volume(o, c, v)
    vl = int(g["vol_len"])
    vol_hi = np.array([np.max(dv[max(0, i - vl + 1):i + 1] / 2.5) for i in range(n)])
    vol_lo = np.array([np.min(dv[max(0, i - vl + 1):i + 1] / 2.5) for i in range(n)])

    lb = int(g["pivot_lookback"])
    lows, highs = [], []
    for i in range(lb, n - lb):
        if l[i] == l[i - lb:i + lb + 1].min() and dv[i] > vol_hi[i]:
            lows.append({"level": float(l[i]), "dv": float(dv[i]), "age": n - 1 - i})
        if h[i] == h[i - lb:i + lb + 1].max() and dv[i] < vol_lo[i]:
            highs.append({"level": float(h[i]), "dv": float(dv[i]), "age": n - 1 - i})

    below = [x for x in lows if x["level"] <= price]
    above = [x for x in highs if x["level"] >= price]
    support = max(below, key=lambda x: x["level"]) if below else None
    resistance = min(above, key=lambda x: x["level"]) if above else None
    return support, resistance


def previous_day_levels(d):
    """Previous trading day's high and low, from an intraday frame."""
    try:
        days = d.index.normalize()
        uniq = sorted(set(days))
        if len(uniq) < 2:
            return None, None
        mask = days == uniq[-2]
        return float(d["High"][mask].max()), float(d["Low"][mask].min())
    except Exception:
        return None, None


def atr_depth(h, l, c, g):
    """Box depth in price terms, from ATR."""
    n = len(c)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = pd.Series(tr).rolling(int(g["atr_period"]), min_periods=10).mean().values
    last = atr[-1]
    return float(last * g["box_atr_mult"]) if last == last else 0.0


def compute_signal(df, gates: dict = None) -> dict:
    """BUY at volume-backed support, SELL at volume-backed resistance.

    Works on any OHLCV frame, so the same model serves equities on 1h candles and
    the MCX commodities -- the construction has nothing equity-specific in it.
    """
    g = dict(GATES)
    if gates:
        g.update(gates)

    if df is None or len(df) < g["min_bars"]:
        return dict(NO_SIGNAL)

    try:
        d = df.rename(columns={col: str(col).capitalize() for col in df.columns})
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col not in d.columns:
                return dict(NO_SIGNAL)
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d.dropna(subset=["Open", "High", "Low", "Close"])
        # The live price rides in on a synthetic trailing bar. Keep it for measuring
        # distance to a level -- that should reflect where price is now -- but judge
        # the turn and its volume on completed candles.
        live_price = float(d["Close"].iloc[-1]) if len(d) else None
        d = strip_forming_bars(d)
        if len(d) < g["min_bars"]:
            return dict(NO_SIGNAL)

        o = d["Open"].values.astype(float)
        h = d["High"].values.astype(float)
        l = d["Low"].values.astype(float)
        c = d["Close"].values.astype(float)
        v = np.nan_to_num(d["Volume"].values.astype(float))

        depth = atr_depth(h, l, c, g)
        if depth <= 0:
            return dict(NO_SIGNAL)

        vol_avg = float(np.mean(v[-int(g["vol_avg_window"]):]))
        last_vol = last_bar_volume_run_rate(d)
        vol_ratio = float(last_vol / vol_avg) if vol_avg > 0 else 0.0
        price = live_price if live_price else float(c[-1])
        near = depth * float(g["near_box_mult"])
        support, resistance = find_volume_levels(o, h, l, c, v, g, price)

        # The turn bar, judged on its own shape rather than on a bare comparison.
        bar_rng = float(h[-1] - l[-1])
        body = abs(float(c[-1] - o[-1]))
        body_ratio = (body / bar_rng) if bar_rng > 0 else 0.0
        close_pos = ((c[-1] - l[-1]) / bar_rng) if bar_rng > 0 else 0.5
        decisive = body_ratio >= float(g["min_body_range"])
        travelled_up = (c[-1] - l[-1]) >= float(g["min_turn_atr"]) * depth
        travelled_down = (h[-1] - c[-1]) >= float(g["min_turn_atr"]) * depth

        turned_up = (
            c[-1] > o[-1] and decisive
            and close_pos >= float(g["min_close_position"])
            and travelled_up
        )
        turned_down = (
            c[-1] < o[-1] and decisive
            and close_pos <= 1.0 - float(g["min_close_position"])
            and travelled_down
        )
        has_vol = vol_ratio >= float(g["min_turn_vol_ratio"])

        # How close price actually came to each level in the last few bars.
        tb = max(1, int(g["touch_lookback"]))
        recent_low = float(np.min(l[-tb:]))
        recent_high = float(np.max(h[-tb:]))

        out = dict(NO_SIGNAL)
        out.update({
            "srv_available": True,
            "srv_support": round(support["level"], 2) if support else None,
            "srv_resistance": round(resistance["level"], 2) if resistance else None,
            "srv_box_depth": round(depth, 2),
            "srv_vol_ratio": round(vol_ratio, 2),
        })

        def cap_target(entry, target, is_long):
            """Trim a target that lies further away than the horizon can travel."""
            cap = g.get("max_target_pct")
            if cap is None or not entry:
                return target
            limit = entry * (1 + float(cap) / 100.0) if is_long else entry * (1 - float(cap) / 100.0)
            return round(min(target, limit), 2) if is_long else round(max(target, limit), 2)

        def trade_shape(entry, stop, target):
            """Risk, reward and their ratio, as percentages of entry."""
            risk = abs(entry - stop) / entry * 100 if entry else 0.0
            reward = abs(target - entry) / entry * 100 if entry else 0.0
            return round(risk, 2), round(reward, 2), round(reward / risk, 2) if risk else 0.0

        def shape_ok(risk, rr):
            """Reject trades whose geometry fails the caller's limits."""
            cap = g.get("max_stop_pct")
            floor = g.get("min_reward_risk")
            if cap is not None and risk > float(cap):
                return False
            if floor is not None and rr < float(floor):
                return False
            return True

        def strength(dist, level_dv, age):
            """Nearer the level, heavier the volume that built it, fresher: stronger."""
            prox = max(0.0, 1.0 - (dist / near)) if near > 0 else 0.0
            volq = min(1.0, vol_ratio / 2.0)
            mass = min(1.0, abs(level_dv) / (vol_avg * 2.0)) if vol_avg > 0 else 0.0
            fresh = max(0.0, 1.0 - (age / (int(g["pivot_lookback"]) * 6.0)))
            return round(100.0 * (0.40 * prox + 0.25 * volq + 0.20 * mass + 0.15 * fresh), 1)

        # Support is tested first when price sits near both: the long has a defined
        # level beneath it, and defined risk beats defined reward.
        # Touched the level recently, has not broken decisively through it, and is
        # now turning away from it on volume.
        # Price must still be above the level. Allowing it a depth below meant a
        # support that had already broken -- price falling away from it, which is
        # the short -- still read as a buy.
        if (support
                and abs(recent_low - support["level"]) <= near
                and price > support["level"]):
            if turned_up and has_vol:
                res = resistance["level"] if resistance else None
                b_entry = round(price, 2)
                b_stop = round(support["level"] - depth, 2)
                b_level_t = round(res, 2) if res else round(price + depth * 2, 2)
                b_t1 = cap_target(b_entry, b_level_t, True)
                b_risk, b_rew, b_rr = trade_shape(b_entry, b_stop, b_t1)
                if not shape_ok(b_risk, b_rr):
                    return out
                out.update({
                    "srv_risk_pct": b_risk, "srv_reward_pct": b_rew, "srv_rr": b_rr,
                    "srv_level_target": b_level_t,
                    "srv_signal": "BUY",
                    "srv_strength": strength(abs(recent_low - support["level"]), support["dv"], support["age"]),
                    "srv_entry": b_entry,
                    "srv_stop": b_stop,
                    "srv_target1": b_t1,
                    "srv_target2": round(res + depth, 2) if res else round(price + depth * 3, 2),
                    "srv_target_is_level": bool(res),
                    "srv_reason": (
                        f"Turned up off support {support['level']:.2f} built on buying volume, "
                        f"on {vol_ratio:.1f}x volume"
                    ),
                })
                return out

        if (resistance
                and abs(recent_high - resistance["level"]) <= near
                and price < resistance["level"]):
            if turned_down and has_vol:
                sup = support["level"] if support else None
                s_entry = round(price, 2)
                s_stop = round(resistance["level"] + depth, 2)
                s_level_t = round(sup, 2) if sup else round(price - depth * 2, 2)
                s_t1 = cap_target(s_entry, s_level_t, False)
                s_risk, s_rew, s_rr = trade_shape(s_entry, s_stop, s_t1)
                if not shape_ok(s_risk, s_rr):
                    return out
                out.update({
                    "srv_risk_pct": s_risk, "srv_reward_pct": s_rew, "srv_rr": s_rr,
                    "srv_level_target": s_level_t,
                    "srv_signal": "SELL",
                    "srv_strength": strength(abs(recent_high - resistance["level"]), resistance["dv"], resistance["age"]),
                    "srv_entry": s_entry,
                    "srv_stop": s_stop,
                    "srv_target1": s_t1,
                    "srv_target2": round(sup - depth, 2) if sup else round(price - depth * 3, 2),
                    "srv_target_is_level": bool(sup),
                    "srv_reason": (
                        f"Turned down off resistance {resistance['level']:.2f} built on selling volume, "
                        f"on {vol_ratio:.1f}x volume"
                    ),
                })
                return out

        # Previous-day levels, checked after the volume boxes: a break that has held
        # through the session is a position, and requiring a decisive bar right now
        # would miss it, because the break may be hours old and price merely
        # drifting since -- which is the setup, not a disqualification.
        if g.get("use_prev_day_levels"):
            pdh, pdl = previous_day_levels(d)
            out["srv_pdh"] = round(pdh, 2) if pdh else None
            out["srv_pdl"] = round(pdl, 2) if pdl else None

            # Confirmation is a close beyond the level, not a distance past it: an
            # arbitrary percentage buffer rejected TATACHEM's genuine break by
            # 0.04%. "Not reclaimed" is judged on today's closes only -- the
            # rolling window used first reached back into the previous session and
            # compared against 646.00, that day's own high, so a break could never
            # qualify.
            try:
                days = d.index.normalize()
                today = sorted(set(days))[-1]
                today_closes = c[(days == today).values]
            except Exception:
                today_closes = c[-1:]
            # Heaviest completed hour of today, relative to a normal hour.
            try:
                today_vols = v[(days == today).values] if hasattr(days == today, "values") else v[days == today]
                break_vol_ratio = float(np.max(today_vols) / vol_avg) if vol_avg > 0 and len(today_vols) else 0.0
            except Exception:
                break_vol_ratio = vol_ratio
            out["srv_break_vol_ratio"] = round(break_vol_ratio, 2)
            break_has_vol = break_vol_ratio >= float(g["min_break_vol_ratio"])

            closed_below = len(today_closes) > 0 and float(today_closes[-1]) < (pdl or 0)
            closed_above = len(today_closes) > 0 and float(today_closes[-1]) > (pdh or float("inf"))
            reclaimed_up = bool((today_closes > pdl).any()) if pdl is not None else True
            reclaimed_down = bool((today_closes < pdh).any()) if pdh is not None else True

            if pdl and price < pdl and closed_below and not reclaimed_up and break_has_vol:
                t_level = support["level"] if support else round(price - depth * 2, 2)
                entry = round(price, 2)
                stop = round(pdl + float(g["break_stop_atr"]) * depth, 2)
                t1 = cap_target(entry, round(t_level, 2), False)
                risk, rew, rr = trade_shape(entry, stop, t1)
                if shape_ok(risk, rr):
                    out.update({
                        "srv_signal": "SELL", "srv_setup": "PDL_BREAK",
                        "srv_strength": round(min(100.0, 35.0
                                                   + min(35.0, (break_vol_ratio - 1.0) * 20.0)
                                                   + min(30.0, (pdl - price) / depth * 25.0)), 1),
                        "srv_entry": entry, "srv_stop": stop, "srv_target1": t1,
                        "srv_level_target": round(t_level, 2),
                        "srv_risk_pct": risk, "srv_reward_pct": rew, "srv_rr": rr,
                        "srv_reason": (
                            f"Broke the previous day's low {pdl:.2f} on {break_vol_ratio:.1f}x volume "
                            f"and no hour today has closed back above it"
                        ),
                    })
                    return out

            if pdh and price > pdh and closed_above and not reclaimed_down and break_has_vol:
                t_level = resistance["level"] if resistance else round(price + depth * 2, 2)
                entry = round(price, 2)
                stop = round(pdh - float(g["break_stop_atr"]) * depth, 2)
                t1 = cap_target(entry, round(t_level, 2), True)
                risk, rew, rr = trade_shape(entry, stop, t1)
                if shape_ok(risk, rr):
                    out.update({
                        "srv_signal": "BUY", "srv_setup": "PDH_BREAK",
                        "srv_strength": round(min(100.0, 35.0
                                                   + min(35.0, (break_vol_ratio - 1.0) * 20.0)
                                                   + min(30.0, (price - pdh) / depth * 25.0)), 1),
                        "srv_entry": entry, "srv_stop": stop, "srv_target1": t1,
                        "srv_level_target": round(t_level, 2),
                        "srv_risk_pct": risk, "srv_reward_pct": rew, "srv_rr": rr,
                        "srv_reason": (
                            f"Broke the previous day's high {pdh:.2f} on {break_vol_ratio:.1f}x volume "
                            f"and no hour today has closed back below it"
                        ),
                    })
                    return out

        return out
    except Exception:
        return dict(NO_SIGNAL)
