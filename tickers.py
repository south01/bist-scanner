"""
tickers.py — Auto-fetch and cache the full BIST ticker universe.
Refreshes weekly. Falls back to a hardcoded seed list (~500 tickers) if fetching fails.
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE_FILE = os.path.join(DATA_DIR, "bist_tickers.json")
CACHE_TTL_DAYS = 7

# ── Comprehensive BIST All Shares seed list (~500 tickers, updated 2025) ────
# Used only if all live fetch methods fail.
SEED_TICKERS = [
    'ACPEN', 'ACSEL', 'ADEL', 'ADESE', 'ADGYO', 'AEFES', 'AFYON', 'AGESA', 'AGHOL', 'AGROT',
    'AGYO', 'AHGAZ', 'AKBNK', 'AKCNS', 'AKFGY', 'AKFYE', 'AKGRT', 'AKINV', 'AKMGY', 'AKSA',
    'AKSEN', 'AKSGY', 'AKSUE', 'AKTIF', 'ALARK', 'ALBRK', 'ALCAR', 'ALCTL', 'ALFAS', 'ALGYO',
    'ALKA', 'ALKIM', 'ALKLC', 'ALMAD', 'ALTIN', 'ALTNY', 'ALVES', 'ANELE', 'ANGEN', 'ANHYT',
    'ANKAS', 'ANSGR', 'ARASE', 'ARCLK', 'ARDYZ', 'ARENA', 'ARFYO', 'ARSAN', 'ARTMS', 'ARZUM',
    'ASELS', 'ASGYO', 'ASPEN', 'ASTOR', 'ASTRL', 'ATAGY', 'ATAKP', 'ATATP', 'ATEKS', 'ATLAS',
    'AVGYO', 'AVHOL', 'AVOD', 'AVTUR', 'AYCES', 'AYES', 'AYGAZ', 'AZTEK',
    'BAGFS', 'BAKAB', 'BALAT', 'BANVT', 'BASCM', 'BASGZ', 'BAYRK', 'BBGYO', 'BERA', 'BEYAZ',
    'BFREN', 'BGFON', 'BIMAS', 'BINBN', 'BIOEN', 'BISAS', 'BIZIM', 'BJKAS', 'BLCYT', 'BMSCH',
    'BMSTL', 'BNTAS', 'BOBET', 'BOSSA', 'BRISA', 'BRKSN', 'BRKVY', 'BRLSM', 'BRSAN', 'BRYAT',
    'BSOKE', 'BTCIM', 'BUCIM', 'BURCE', 'BURVA', 'BVSAN', 'BYDNR',
    'CANTE', 'CASGM', 'CCOLA', 'CELHA', 'CEMAS', 'CEMTS', 'CEOEM', 'CIMSA', 'CLEBI', 'CLGYO',
    'CMBTN', 'CMENT', 'CONSE', 'COSMO', 'CRDFA', 'CRFSA', 'CUSAN', 'CVKMD', 'CWENE',
    'DAGHL', 'DAGI', 'DAPGM', 'DARDL', 'DENGE', 'DERHL', 'DERIM', 'DEVA', 'DGATE', 'DGGYO',
    'DGNMO', 'DITAS', 'DMSAS', 'DNISI', 'DOAS', 'DOBUR', 'DOCO', 'DOGUB', 'DOKTA', 'DURDO',
    'DYOBY', 'DZGYO',
    'ECILC', 'ECZYT', 'EDATA', 'EDIP', 'EGEEN', 'EGGUB', 'EGPRO', 'EGSER', 'EKGYO', 'EKSUN',
    'ELITE', 'EMKEL', 'EMNIS', 'ENKAI', 'ENSRI', 'EPLAS', 'ERBOS', 'ERCB', 'EREGE', 'ESCAR',
    'ESCOM', 'ESEN', 'ETILR', 'ETYAT', 'EUHOL', 'EUPWR', 'EUREN', 'EUYO', 'EVREN',
    'FADE', 'FENER', 'FMIZP', 'FONET', 'FORMT', 'FORTE', 'FROTO', 'FZLGY',
    'GARFA', 'GEDIK', 'GEDZA', 'GENIL', 'GENTS', 'GEREL', 'GESAN', 'GLBMD', 'GLCVY', 'GLRYH',
    'GLYHO', 'GMTAS', 'GOKNR', 'GOLTS', 'GOODY', 'GOZDE', 'GRNYO', 'GRSEL', 'GRTRK', 'GSDDE',
    'GSDHO', 'GSRAY', 'GUBRF', 'GWIND', 'GZNMI',
    'HALKB', 'HATEK', 'HDFGS', 'HEDEF', 'HEKTS', 'HKTM', 'HLGYO', 'HRKET', 'HTTBT', 'HUBVC',
    'HUNER', 'HURGZ',
    'ICBCT', 'ICUGS', 'IDEAS', 'IEYHO', 'IHEVA', 'IHGZT', 'IHLAS', 'IHLGM', 'IHYAY', 'IMASM',
    'INDES', 'INFO', 'INTEM', 'INVEO', 'IPEKE', 'ISATR', 'ISBIR', 'ISFIN', 'ISGSY', 'ISGYO',
    'ISKPL', 'ISKUR', 'ISMEN', 'ISYAT', 'ITTFH', 'IZENR', 'IZFAS', 'IZGYO', 'IZINV', 'IZMDC',
    'JANTS',
    'KAPLM', 'KARCE', 'KARSN', 'KARTN', 'KATMR', 'KAYSE', 'KBORU', 'KCAER', 'KCHOL', 'KENT',
    'KERVN', 'KERVT', 'KFEIN', 'KGYO', 'KIMMR', 'KINDS', 'KLGYO', 'KLKIM', 'KLMSN', 'KLNMA',
    'KLRHO', 'KLSYN', 'KMPUR', 'KNFRT', 'KOKAR', 'KONKA', 'KONTR', 'KONYA', 'KOPOL', 'KORDS',
    'KRDMA', 'KRDMB', 'KRDMD', 'KRPLS', 'KRSTL', 'KRTEK', 'KRVGD', 'KSTUR', 'KTLEV', 'KTSKR',
    'KUTPO', 'KUVVA', 'KUYAS',
    'LIDER', 'LIDFA', 'LILAK', 'LINK', 'LKMNH', 'LMKDC', 'LOGO', 'LRSHO', 'LUKSK',
    'MAALT', 'MACKO', 'MAGEN', 'MAKIM', 'MAKTK', 'MANAS', 'MARBL', 'MARKA', 'MARTI', 'MAVI',
    'MEDTR', 'MEGAP', 'MEPET', 'MERCN', 'MERIT', 'MERKO', 'METRO', 'METUR', 'MGROS', 'MHRTN',
    'MIPAZ', 'MMCAS', 'MNDRS', 'MNVRL', 'MOBTL', 'MOGAN', 'MSGYO', 'MTRKS', 'MTRYO', 'MUGLA',
    'MZHLD',
    'NATEN', 'NETAS', 'NIBAS', 'NTGAZ', 'NTHOL', 'NTTUR', 'NUHCM', 'NUROL',
    'OBAMS', 'OBASE', 'ODAS', 'ODINE', 'OFSYM', 'ONCSM', 'ONRYT', 'ORCAY', 'ORGE', 'ORMA',
    'OSMEN', 'OSTIM', 'OTKAR', 'OTTO', 'OYAKC', 'OYAYO', 'OYLUM', 'OZGYO', 'OZKGY', 'OZRDN',
    'OZSUB',
    'PAGYO', 'PAMEL', 'PAPIL', 'PARSN', 'PASEU', 'PCILT', 'PENGD', 'PENTA', 'PETKM', 'PETUN',
    'PGSUS', 'PKART', 'PKENT', 'PLTUR', 'PNLSN', 'POLHO', 'POLTK', 'PRDGS', 'PRZMA', 'PSDTC',
    'PSGYO', 'PTOFS',
    'QNBFB', 'QNBFL',
    'RALYH', 'RAYSG', 'REEDR', 'RGYAS', 'RHGYO', 'RODRG', 'ROYAL', 'RTALB', 'RUBNS', 'RYGYO',
    'SAFKR', 'SAHOL', 'SAMAT', 'SAMFA', 'SANEL', 'SANFM', 'SANKO', 'SARKY', 'SASA', 'SAYAS',
    'SDTTR', 'SEGYO', 'SEKFK', 'SEKUR', 'SELEC', 'SELGD', 'SELVA', 'SEYKM', 'SILVR', 'SISE',
    'SKBNK', 'SKYLP', 'SMART', 'SMRTG', 'SNGYO', 'SNICA', 'SNKRN', 'SNPAM', 'SODSN', 'SOKM',
    'SONME', 'SRVGY', 'SUMAS', 'SUNTK', 'SUWEN',
    'TABGD', 'TATGD', 'TAVHL', 'TBORG', 'TCELL', 'TDGYO', 'TEKTU', 'TERA', 'TETMT', 'TEZOL',
    'TGSAS', 'THYAO', 'TIRE', 'TKFEN', 'TKNSA', 'TLMAN', 'TMSN', 'TOASO', 'TRCAS', 'TRGYO',
    'TRILC', 'TSGYO', 'TSKB', 'TSPOR', 'TTKOM', 'TTRAK', 'TUCLK', 'TUGGL', 'TUPRS', 'TUREX',
    'TURGG', 'TURKB', 'TURSG',
    'UFUK', 'ULKER', 'ULUFA', 'ULUSE', 'ULUUN', 'UMASH', 'UNLU', 'USAK', 'USDOS', 'UZERB',
    'VAKBN', 'VAKFN', 'VAKKO', 'VANGD', 'VBTYZ', 'VERUS', 'VESBE', 'VESTL', 'VKFYO', 'VKGYO',
    'VOBNK', 'VRGYO',
    'YATAS', 'YAYLA', 'YBTAS', 'YGYO', 'YKSLN', 'YONGA', 'YOYAS', 'YPKGB', 'YSLTC', 'YUNSA',
    'ZEDUR', 'ZOREN', 'ZRGYO',
]


def _load_cache() -> Optional[dict]:
    """Load cached ticker data if it exists and is fresh."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        fetched_at = datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
        if datetime.now() - fetched_at < timedelta(days=CACHE_TTL_DAYS):
            return data
        logger.info("Ticker cache expired, will refresh.")
        return None
    except Exception as e:
        logger.warning(f"Cache read error: {e}")
        return None


def _save_cache(tickers: list[str], source: str) -> None:
    """Save ticker list to cache."""
    os.makedirs(DATA_DIR, exist_ok=True)
    data = {
        "tickers": tickers,
        "count": len(tickers),
        "source": source,
        "fetched_at": datetime.now().isoformat(),
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(tickers)} tickers from '{source}' to cache.")


def _fetch_from_isyatirim() -> Optional[list]:
    """
    Fetch BIST tickers from isyatirim.com.tr JSON API.
    Returns list of base tickers (without .IS suffix) or None on failure.
    """
    try:
        api_url = (
            "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/"
            "Data.aspx/HisseSenediGetir"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://www.isyatirim.com.tr/",
        }
        resp = requests.get(api_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            tickers = [item["kod"] for item in data.get("d", []) if item.get("kod")]
            if len(tickers) > 100:
                logger.info(f"isyatirim: fetched {len(tickers)} tickers")
                return sorted(set(tickers))
    except Exception as e:
        logger.warning(f"isyatirim fetch failed: {e}")
    return None


def _fetch_from_kap() -> Optional[list]:
    """
    Fetch BIST tickers from KAP (Public Disclosure Platform) API.
    """
    try:
        url = "https://www.kap.org.tr/tr/api/general/currentValueInfo"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.kap.org.tr/",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            tickers = []
            for item in data:
                code = item.get("stock") or item.get("code") or item.get("ticker")
                if code and 2 <= len(code) <= 6 and code.replace(".", "").isalnum():
                    tickers.append(code.upper().strip())
            if len(tickers) > 100:
                logger.info(f"KAP: fetched {len(tickers)} tickers")
                return sorted(set(tickers))
    except Exception as e:
        logger.warning(f"KAP fetch failed: {e}")
    return None


def _fetch_from_borsaistanbul() -> Optional[list]:
    """
    Scrape BIST tickers from Borsa Istanbul public equity page.
    """
    try:
        url = "https://www.borsaistanbul.com/tr/endeksler/bist-pay-endeksleri/pay-endeksleri"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        tickers = set()
        for td in soup.find_all("td"):
            text = td.get_text(strip=True)
            if 3 <= len(text) <= 6 and text.isupper() and text.isalpha():
                tickers.add(text)
        if len(tickers) > 50:
            logger.info(f"borsaistanbul: fetched {len(tickers)} tickers")
            return sorted(tickers)
    except Exception as e:
        logger.warning(f"borsaistanbul fetch failed: {e}")
    return None


def get_bist_tickers(force_refresh: bool = False) -> list[str]:
    """
    Get the full BIST ticker list as Yahoo Finance symbols (with .IS suffix).
    Uses cache if available and fresh. Tries multiple sources on refresh.
    Falls back to the built-in ~500-ticker seed list if all sources fail.

    Returns list like: ['THYAO.IS', 'AKBNK.IS', ...]
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            tickers = cached["tickers"]
            logger.info(
                f"Using cached tickers: {len(tickers)} tickers "
                f"(source: {cached.get('source')})"
            )
            return tickers

    logger.info("Fetching fresh BIST ticker list...")

    base_tickers = None
    source = "unknown"

    for fetch_fn, name in [
        (_fetch_from_isyatirim, "isyatirim"),
        (_fetch_from_kap, "kap"),
        (_fetch_from_borsaistanbul, "borsaistanbul"),
    ]:
        result = fetch_fn()
        if result and len(result) > 100:
            base_tickers = result
            source = name
            break

    if not base_tickers or len(base_tickers) < 50:
        logger.warning("All live fetch sources failed. Using built-in seed ticker list.")
        base_tickers = list(SEED_TICKERS)
        source = "seed_fallback"

    # Clean: keep only valid BIST ticker codes
    cleaned = []
    for t in base_tickers:
        t = t.strip().upper()
        if 2 <= len(t) <= 6 and t.isalpha():
            cleaned.append(t)

    cleaned = sorted(set(cleaned))

    # Add .IS suffix for Yahoo Finance
    yf_tickers = [f"{t}.IS" for t in cleaned]

    _save_cache(yf_tickers, source)
    return yf_tickers


def get_ticker_info() -> dict:
    """Return info about the current cached ticker list."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "count": data.get("count", 0),
                "source": data.get("source", "unknown"),
                "fetched_at": data.get("fetched_at", ""),
            }
        except Exception:
            pass
    return {"count": 0, "source": "none", "fetched_at": ""}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tickers = get_bist_tickers(force_refresh=True)
    print(f"\nFetched {len(tickers)} tickers.")
    print("Sample:", tickers[:10])
