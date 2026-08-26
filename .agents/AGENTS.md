# Stock Screener Application Rules & System Constraints

## 1. Stock of the Day Rules & Constraints
- **Cap Category Restriction**: Stock of the Day MUST ONLY be selected from Large Cap or Mid Cap stocks (`LARGE_CAP_SYMBOLS`, `MID_CAP_SYMBOLS`, or `cap_category` in `["Large Cap", "Mid Cap"]`). Small Cap and micro-cap stocks are strictly prohibited.
- **Price Floor**: Stock of the Day MUST have an LTP >= ₹100.0 (strictly no penny stocks).
- **Status Persistence & Replacement**:
  - Today's official Stock of the Day remains locked as long as its status is `ACTIVE` (`status == "ACTIVE"`).
  - If a locked stock's status deteriorates to `INACTIVE` (score < 45) or `INVALIDATED` (score < 55), it MUST NOT remain as Stock of the Day.
  - The system MUST automatically discard the inactive/invalidated stock and select the next best eligible active qualified stock for Stock of the Day.

## 2. Fundamental Data & Caching Rules
- The quoteSummary fetcher and yfinance fallback MUST populate genuine fundamental metrics (`P/E`, `ROE%`, `D/E`, `Net Profit Margin%`).
- Cache files missing fundamental metrics MUST be invalidated immediately so fresh metrics are fetched.

## 3. F&O / Options Signals Criteria & Filtering Rules
- **Quantity & Selection**: The system MUST ALWAYS select and output exactly 15 qualified F&O stocks.
- **Eligibility Criteria**: Options signals MUST ONLY be generated for stocks meeting:
  - `LTP >= 1000.0`
  - `lot_size < 500`
  - Mandatory Exception: `RELIANCE` (`symbol == "RELIANCE"`)
- **RELIANCE Mandatory Inclusion**: `RELIANCE` MUST ALWAYS be included in the official Top 15 F&O options picks regardless of its conviction ranking.

## 4. LT Segment Capital Accumulator & Day Counter Rules
- **Trading Days Only**: The LT Segment Day Counter (`days_active`) MUST ONLY count active NSE market trading days (Mondays through Fridays, excluding Saturdays, Sundays, and official NSE holidays). Simple calendar day subtraction (`(today - start_date).days + 1`) is strictly prohibited as it incorrectly counts non-trading weekends.
- **Client-Side Recalculation**: `recalcDaysActive()` in Javascript MUST iterate day-by-day and count only valid NSE market trading days so the browser UI dynamically displays the correct trading day count even when using static HTML or cached data.
- **Dual HTTP Method Support**: The `/api/lt-portfolio/status` endpoint MUST be supported in both `do_GET` (for standard browser `fetch()`) and `do_POST` in `fetch_and_build.py`.

## 5. Modal HTML Hierarchy & Un-nested Structure
- **Top-Level Modals**: `ltAddModalBg` MUST ALWAYS be a top-level element placed directly under `<body>` (or at root modal container level). It MUST NEVER be nested inside another `<div class="modal-bg">` (such as `bseModalBg`) because parent `display:none` styles render child modals completely invisible.


