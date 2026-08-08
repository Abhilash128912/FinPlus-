"""
news_context_fetcher.py
=======================
Fetches recent news headlines (last 5-7 days) via Google News RSS for a stock ticker/company.
Classifies context into 3 buckets using a deterministic keyword classifier:
  1. Positive Catalyst (order win, contract, upgrade, capacity expansion, earnings beat)
  2. Negative / Risk (litigation, regulatory action, investigation, downgrade, default, pledge increase)
  3. Neutral / Noise (routine board meeting, generic commentary, standard notice)

Metadata only — NOT part of PreBreakoutScore calculation/math.
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

POSITIVE_KEYWORDS = [
    "order", "contract", "upgrade", "expansion", "beat", "profit up",
    "revenue up", "acquisition", "partnership", "approval", "patent",
    "record high", "capacity expansion", "buyback", "dividend"
]

NEGATIVE_KEYWORDS = [
    "investigation", "downgrade", "default", "pledge", "litigation",
    "penalty", "raid", "resignation", "scam", "loss", "decline",
    "regulatory", "notice", "fraud", "probe", "bankrupt", "court"
]


def fetch_news_headlines(company_name: str, symbol: str, limit: int = 5) -> List[Dict[str, str]]:
    """
    Fetches latest news headlines via Google News RSS feed for given company.
    """
    clean_sym = symbol.replace(".NS", "").strip()
    query = f"{clean_sym} {company_name} NSE stock news"
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    
    headlines = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            
            for item in root.findall('.//item')[:limit]:
                title = item.findtext('title', '').strip()
                pub_date = item.findtext('pubDate', '').strip()
                link = item.findtext('link', '').strip()
                if title:
                    headlines.append({"title": title, "pub_date": pub_date, "link": link})
    except Exception:
        pass
        
    return headlines


def classify_news_context(company_name: str, symbol: str, headlines: Optional[List[Dict]] = None) -> Dict:
    """
    Classifies headlines into POSITIVE, NEGATIVE, or NEUTRAL news context bucket.
    """
    if headlines is None:
        headlines = fetch_news_headlines(company_name, symbol)
        
    if not headlines:
        return {
            "bucket": "NEUTRAL",
            "badge": "⚪ Neutral / No News",
            "badge_class": "badge-gray",
            "headlines": [],
            "risk_flag": False
        }
        
    pos_count = 0
    neg_count = 0
    flagged_headlines = []
    
    for h in headlines:
        title_lower = h["title"].lower()
        is_pos = any(kw in title_lower for kw in POSITIVE_KEYWORDS)
        is_neg = any(kw in title_lower for kw in NEGATIVE_KEYWORDS)
        
        if is_neg:
            neg_count += 1
            flagged_headlines.append(f"⚠️ {h['title']}")
        elif is_pos:
            pos_count += 1
            flagged_headlines.append(f"🟢 {h['title']}")
            
    if neg_count > 0:
        return {
            "bucket": "NEGATIVE_RISK",
            "badge": f"🔴 Risk Flag ({neg_count} Neg News)",
            "badge_class": "badge-red",
            "headlines": [h["title"] for h in headlines],
            "risk_flag": True
        }
    elif pos_count > 0:
        return {
            "bucket": "POSITIVE_CATALYST",
            "badge": f"🟢 Positive Catalyst ({pos_count} Pos News)",
            "badge_class": "badge-green",
            "headlines": [h["title"] for h in headlines],
            "risk_flag": False
        }
    else:
        return {
            "bucket": "NEUTRAL",
            "badge": "🔵 Routine / Noise",
            "badge_class": "badge-blue",
            "headlines": [h["title"] for h in headlines],
            "risk_flag": False
        }
