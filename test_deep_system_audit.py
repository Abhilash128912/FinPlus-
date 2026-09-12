import sys
import json
import urllib.request
import urllib.error
import time

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:5850"

ROUTES_TO_TEST = [
    ("/", "Crude Dashboard"),
    ("/scan", "Multi-Timeframe Breakout Screener"),
    ("/swing", "Quality Swing Screener"),
    ("/lt", "Long-Term Wealth Compounders"),
    ("/penny", "Quality Debt-Free Micro-Cap Screen"),
]

APIS_TO_TEST = [
    ("/api/fast_ltp", "Crude Fast LTP"),
    ("/api/token_status", "INDmoney Token Status"),
    ("/api/momentum_fast_ltp", "Momentum Fast LTP"),
    ("/api/swing", "Swing Engine State"),
    ("/api/lt", "Long-Term Engine State"),
    ("/api/penny", "Penny Engine State"),
]

def audit():
    print("=" * 80)
    print("🚀 STARTING PRODUCTION SYSTEM AUDIT (INDMONEY CRUDE & SCREENER APP)")
    print("=" * 80)

    total_tests = 0
    passed_tests = 0
    failures = []

    # 1. Test HTML Web Pages
    print("\n[SECTION 1: HTML PAGES AUDIT]")
    for route, label in ROUTES_TO_TEST:
        total_tests += 1
        url = BASE_URL + route
        try:
            t0 = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "AuditBot/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                elapsed = (time.time() - t0) * 1000
                status = resp.status
                html = resp.read().decode("utf-8")
                
                # Integrity checks
                has_html_tags = "<html" in html and "</html>" in html
                has_nav = "navbar" in html or "nav" in html
                no_traceback = "Traceback (most recent call last)" not in html
                no_internal_error = "Internal Server Error" not in html

                if status == 200 and has_html_tags and no_traceback and no_internal_error:
                    passed_tests += 1
                    print(f"  ✅ PASS: {label:<35} {route:<10} | HTTP 200 | {len(html):>6} bytes | {elapsed:.1f}ms")
                else:
                    failures.append((label, route, f"HTTP {status} with HTML errors"))
                    print(f"  ❌ FAIL: {label:<35} {route:<10} | HTTP {status}")
        except Exception as e:
            failures.append((label, route, str(e)))
            print(f"  ❌ ERROR: {label:<35} {route:<10} | {e}")

    # 2. Test JSON API Endpoints
    print("\n[SECTION 2: JSON API ENDPOINTS AUDIT]")
    for route, label in APIS_TO_TEST:
        total_tests += 1
        url = BASE_URL + route
        try:
            t0 = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "AuditBot/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                elapsed = (time.time() - t0) * 1000
                status = resp.status
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)

                if status == 200 and isinstance(data, dict):
                    passed_tests += 1
                    keys_summary = ", ".join(list(data.keys())[:4])
                    print(f"  ✅ PASS: {label:<35} {route:<24} | HTTP 200 | {len(raw):>6} bytes | {elapsed:.1f}ms | Keys: [{keys_summary}]")
                else:
                    failures.append((label, route, f"Invalid JSON structure (HTTP {status})"))
                    print(f"  ❌ FAIL: {label:<35} {route:<24} | Invalid JSON")
        except Exception as e:
            failures.append((label, route, str(e)))
            print(f"  ❌ ERROR: {label:<35} {route:<24} | {e}")

    # 3. Deep Cohort Content Validation
    print("\n[SECTION 3: PORTFOLIO & COHORT DATA AUDIT]")
    
    # 3a. Audit Long-Term Cohort (/api/lt)
    total_tests += 1
    try:
        with urllib.request.urlopen(BASE_URL + "/api/lt", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            lt_res = data.get("result") or {}
            cohort = lt_res.get("monthly_cohort") or {}
            picks = cohort.get("picks") or []
            
            # Check 40/40/20 balance
            caps = [p.get("cap_category") for p in picks]
            large = caps.count("Large Cap")
            mid = caps.count("Mid Cap")
            small = caps.count("Small Cap")
            symbols = [p.get("symbol") for p in picks]
            
            has_bel = "BEL" in symbols
            has_fed = "FEDERALBNK" in symbols
            no_kotak = "KOTAKBANK" not in symbols
            no_groww = "GROWW" not in symbols
            
            if len(picks) == 10 and large == 4 and mid == 4 and small == 2 and has_bel and has_fed and no_kotak and no_groww:
                passed_tests += 1
                print(f"  ✅ PASS: Long-Term 40/40/20 Balance: 4 Large ({large}), 4 Mid ({mid}), 2 Small ({small}) | BEL & FEDERALBNK present, KOTAK & GROWW removed.")
            else:
                failures.append(("LT Cohort Balance", "/api/lt", f"Picks={len(picks)}, L={large}, M={mid}, S={small}, BEL={has_bel}, FED={has_fed}"))
                print(f"  ❌ FAIL: Long-Term Balance: count={len(picks)}, L={large}, M={mid}, S={small}")
    except Exception as e:
        failures.append(("LT Cohort Audit", "/api/lt", str(e)))
        print(f"  ❌ ERROR in LT audit: {e}")

    # 3b. Audit Penny Cohort (/api/penny)
    total_tests += 1
    try:
        with urllib.request.urlopen(BASE_URL + "/api/penny", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            penny_res = data.get("result") or {}
            cohort = penny_res.get("monthly_cohort") or {}
            picks = cohort.get("picks") or []
            
            all_debt_free = all(float(p.get("de_ratio") or 0.0) <= 0.10 for p in picks)
            all_under_75 = all(5.0 <= float(p.get("ltp") or 0.0) <= 75.0 for p in picks)
            sectors = [p.get("sector") for p in picks]
            distinct_sectors = len(set(sectors))
            health_count = sum(1 for s in sectors if "Health" in str(s) or "Pharma" in str(s))
            
            if len(picks) == 10 and all_debt_free and all_under_75 and health_count <= 1:
                passed_tests += 1
                print(f"  ✅ PASS: Penny Debt-Free Cohort: 10/10 Debt-Free (D/E <= 0.10) | Price ₹5-₹75: 100% | Distinct Sectors: {distinct_sectors}/10 | Healthcare: {health_count}/10")
            else:
                failures.append(("Penny Cohort Audit", "/api/penny", f"count={len(picks)}, debt_free={all_debt_free}, under_75={all_under_75}, health={health_count}"))
                print(f"  ❌ FAIL: Penny Debt-Free Cohort: count={len(picks)}, debt_free={all_debt_free}, health={health_count}")
    except Exception as e:
        failures.append(("Penny Cohort Audit", "/api/penny", str(e)))
        print(f"  ❌ ERROR in Penny audit: {e}")

    # 4. Summary
    print("\n" + "=" * 80)
    print(f"AUDIT SUMMARY: {passed_tests}/{total_tests} Tests Passed ({(passed_tests/total_tests)*100:.1f}%)")
    if failures:
        print(f"⚠️ FAILURES ({len(failures)}):")
        for f in failures:
            print(f"   - {f[0]} ({f[1]}): {f[2]}")
    else:
        print("🎉 ALL SYSTEMS PASSING WITH ZERO ERRORS. SYSTEM IS PRODUCTION-GRADE.")
    print("=" * 80)

if __name__ == "__main__":
    audit()
