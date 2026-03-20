"""Bulk deviation scan service — fetches TWSE STOCK_DAY data and calculates 60MA deviation."""

import asyncio
import logging
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
    """
    ssl_ctx = _build_ssl_context()
    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.get(
                TWSE_STOCK_DAY_ALL_URL,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
                ssl=ssl_ctx,
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"STOCK_DAY_ALL returned HTTP {resp.status}")
                rows = await resp.json(content_type=None)
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch TWSE stock list: {exc}") from exc

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

    logger.info("Fetched TWSE stock list: %d stocks after filtering", len(stocks))
    return stocks
