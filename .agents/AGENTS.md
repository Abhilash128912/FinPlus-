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
