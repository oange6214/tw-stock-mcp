"""Bulk deviation scan service — fetches TWSE STOCK_DAY data and calculates 60MA deviation."""

import asyncio
import json
import logging
import os
import sqlite3
import ssl
import time
from datetime import date
from typing import Any

import aiohttp

logger = logging.getLogger("tw-stock-agent.deviation_service")

TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TWSE_STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# --- Stock list cache ---
_STOCK_LIST_CACHE_KEY = "twse:stock_list"
_STOCK_LIST_CACHE_MAX_AGE = 7 * 24 * 3600  # 7 days


def _cache_db_path() -> str:
    cache_dir = os.path.join(os.path.expanduser("~"), ".tw_stock_mcp", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "cache.db")


def _load_stock_list_from_cache() -> list[tuple[str, str]] | None:
    """Return cached (code, name) list if recorded within the last 7 days, else None."""
    try:
        db_path = _cache_db_path()
        if not os.path.exists(db_path):
            return None
        cutoff = int(time.time()) - _STOCK_LIST_CACHE_MAX_AGE
        with sqlite3.connect(db_path, timeout=10) as conn:
            row = conn.execute(
                "SELECT value FROM cache WHERE key = ? AND created_at >= ?",
                (_STOCK_LIST_CACHE_KEY, cutoff),
            ).fetchone()
        if row:
            stocks = [(item["code"], item["name"]) for item in json.loads(row[0])]
            logger.info("Stock list loaded from cache: %d stocks", len(stocks))
            return stocks
    except Exception as exc:
        logger.warning("Failed to load stock list from cache: %s", exc)
    return None


def _save_stock_list_to_cache(stocks: list[tuple[str, str]]) -> None:
    """Persist (code, name) list to the shared SQLite cache."""
    try:
        db_path = _cache_db_path()
        now = int(time.time())
        value = json.dumps([{"code": c, "name": n} for c, n in stocks], ensure_ascii=False)
        expire_at = now + _STOCK_LIST_CACHE_MAX_AGE
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache
                    (key, value, expire_at, created_at, last_accessed, data_type, size_bytes)
                VALUES (?, ?, ?, ?, ?, 'json', ?)
                """,
                (_STOCK_LIST_CACHE_KEY, value, expire_at, now, now, len(value.encode())),
            )
            conn.commit()
        logger.info("Stock list saved to cache: %d stocks", len(stocks))
    except Exception as exc:
        logger.warning("Failed to save stock list to cache: %s", exc)


# Minimum closes needed: 60 (MA window) + 30 (eval window) + 1 (today)
_MIN_CLOSES = 91

# TWSE rate limit: 3 req / 5 sec.  We target 2 req/s to stay safely below.
# A global token bucket ensures the limit is respected across all concurrent tasks.
_RATE_LOCK = asyncio.Lock()
_RATE_INTERVAL = 0.5   # seconds between requests (= 2 req/s)
_last_request_time: float = 0.0


async def _rate_limited_sleep() -> None:
    """Enforce global minimum interval between TWSE requests."""
    global _last_request_time
    async with _RATE_LOCK:
        now = time.monotonic()
        wait = _RATE_INTERVAL - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


def _build_ssl_context() -> ssl.SSLContext:
    """Return an SSL context that skips certificate verification.

    TWSE's www.twse.com.tw certificate is missing the Subject Key Identifier
    extension, which causes standard verification to fail.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _last_n_months(n: int) -> list[str]:
    """Return the first day of the last *n* calendar months as 'YYYYMMDD' strings."""
    today = date.today()
    months: list[str] = []
    year, month = today.year, today.month
    for _ in range(n):
        months.append(f"{year}{month:02d}01")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()
    return months


async def _fetch_month_closes(
    session: aiohttp.ClientSession,
    ssl_ctx: ssl.SSLContext,
    code: str,
    year_month: str,
) -> list[float]:
    """Fetch daily closing prices for *code* in *year_month* (format: YYYYMMDD)."""
    url = f"{TWSE_STOCK_DAY_URL}?response=json&date={year_month}&stockNo={code}"
    await _rate_limited_sleep()
    try:
        async with session.get(
            url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15), ssl=ssl_ctx
        ) as resp:
            if resp.status != 200:
                return []
            body = await resp.read()
            import json as _json
            data = _json.loads(body.decode("utf-8"))
            if data.get("stat") != "OK" or "data" not in data:
                return []
            closes: list[float] = []
            for row in data["data"]:
                try:
                    closes.append(float(row[6].replace(",", "")))
                except Exception:
                    pass
            return closes
    except Exception as exc:
        logger.debug("Failed fetching %s %s: %s", code, year_month, exc)
        return []


async def _scan_single(
    session: aiohttp.ClientSession,
    ssl_ctx: ssl.SSLContext,
    semaphore: asyncio.Semaphore,
    code: str,
    name: str,
    months: list[str],
) -> dict[str, Any]:
    """Evaluate one stock against both deviation conditions."""
    async with semaphore:
        closes: list[float] = []
        for month in months:
            month_closes = await _fetch_month_closes(session, ssl_ctx, code, month)
            closes.extend(month_closes)
            # Rate limiting is handled globally by _rate_limited_sleep() inside _fetch_month_closes

        if len(closes) < _MIN_CLOSES:
            return {"code": code, "name": name, "matched": False, "skipped": True}

        # Condition 1: today's deviation 0–5% relative to 60MA
        today_close = closes[-1]
        ma60 = sum(closes[-60:]) / 60
        today_dev = (today_close - ma60) / ma60 * 100

        if not (0 < today_dev <= 5):
            return {
                "code": code,
                "name": name,
                "close": today_close,
                "ma60": round(ma60, 2),
                "today_deviation": round(today_dev, 2),
                "matched": False,
            }

        # Condition 2: ≥24 of last 30 evaluable days below MA60
        neg_days = 0
        count = 0
        start = max(60, len(closes) - 30)
        for i in range(start, len(closes) - 1):
            day_ma60 = sum(closes[i - 59 : i + 1]) / 60
            if (closes[i] - day_ma60) / day_ma60 * 100 < 0:
                neg_days += 1
            count += 1

        neg_ratio = (neg_days / count * 100) if count > 0 else 0.0
        matched = neg_days >= 24

        return {
            "code": code,
            "name": name,
            "close": today_close,
            "ma60": round(ma60, 2),
            "today_deviation": round(today_dev, 2),
            "negative_days_30": neg_days,
            "negative_ratio_30": round(neg_ratio, 1),
            "matched": matched,
        }


async def run_deviation_scan(
    stocks: list[tuple[str, str]],
    months: list[str] | None = None,
    concurrency: int = 3,
) -> dict[str, Any]:
    """Scan all *stocks* for 60MA deviation criteria.

    Args:
        stocks: List of (code, name) tuples.
        months: YYYYMMDD month-start strings to fetch (default: last 5 months).
        concurrency: Max simultaneous TWSE requests.

    Returns:
        Dict with ``matched`` list, ``total_scanned``, ``total_stocks``, ``months``.
    """
    if months is None:
        months = _last_n_months(5)

    ssl_ctx = _build_ssl_context()
    semaphore = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency * 2)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _scan_single(session, ssl_ctx, semaphore, code, name, months)
            for code, name in stocks
        ]
        results: list[dict[str, Any]] = await asyncio.gather(*tasks)

    matched = [r for r in results if r.get("matched")]
    scanned = [r for r in results if not r.get("skipped")]

    return {
        "total_stocks": len(stocks),
        "total_scanned": len(scanned),
        "matched_count": len(matched),
        "matched": matched,
        "months": months,
    }


async def fetch_twse_stock_list(min_trade_value: int = 100_000_000) -> list[tuple[str, str]]:
    """Fetch today's TWSE stock list and return (code, name) pairs.

    Filters:
    - 4-digit numeric codes only (excludes ETFs starting with '00', DR, warrants)
    - TradeValue (成交金額) > *min_trade_value* (default 1 億)

    Resilience:
    - On success: saves result to SQLite cache (TTL 7 days).
    - On failure or empty response (e.g. non-trading day): falls back to the
      most recent cached list (up to 7 days old) before raising.
    """
    ssl_ctx = _build_ssl_context()
    connector = aiohttp.TCPConnector()
    fetch_error: Exception | None = None
    rows: list = []

    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.get(
                TWSE_STOCK_DAY_ALL_URL,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
                ssl=ssl_ctx,
            ) as resp:
                if resp.status != 200:
                    fetch_error = RuntimeError(f"STOCK_DAY_ALL returned HTTP {resp.status}")
                else:
                    rows = await resp.json(content_type=None)
        except Exception as exc:
            fetch_error = exc

    stocks: list[tuple[str, str]] = []
    for row in rows:
        code = str(row.get("Code", "")).strip()
        name = str(row.get("Name", "")).strip()
        # Keep only 4-digit pure numeric codes, excluding '00xx' ETFs
        if not (len(code) == 4 and code.isdigit() and not code.startswith("00")):
            continue
        try:
            trade_value = int(str(row.get("TradeValue", "0")).replace(",", ""))
        except ValueError:
            trade_value = 0
        if trade_value > min_trade_value:
            stocks.append((code, name))

    if stocks:
        logger.info("Fetched TWSE stock list: %d stocks after filtering", len(stocks))
        _save_stock_list_to_cache(stocks)
        return stocks

    # Empty result — non-trading day or API error; try cache fallback
    reason = str(fetch_error) if fetch_error else "STOCK_DAY_ALL returned empty list (non-trading day?)"
    logger.warning("Live stock list unavailable (%s); trying cache fallback", reason)

    cached = _load_stock_list_from_cache()
    if cached:
        logger.info("Using cached stock list: %d stocks (up to 7 days old)", len(cached))
        return cached

    # No cache available either
    raise RuntimeError(
        f"Failed to fetch TWSE stock list and no cache available. Reason: {reason}"
    )
