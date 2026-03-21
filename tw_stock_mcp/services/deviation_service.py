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

# --- Cache constants ---
_STOCK_LIST_CACHE_KEY = "twse:stock_list"
_STOCK_LIST_CACHE_MAX_AGE = 7 * 24 * 3600       # 7 days
_MONTH_CACHE_TTL_PAST = 7 * 24 * 3600            # 過去月份：7天（資料不會再變）
_MONTH_CACHE_TTL_CURRENT = 1 * 3600              # 當月：1小時（當天可能更新）


def _cache_db_path() -> str:
    cache_dir = os.path.join(os.path.expanduser("~"), ".tw_stock_mcp", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "cache.db")


def _ensure_cache_table() -> None:
    """確保 cache 資料表存在（首次執行時自動建立）。"""
    try:
        db_path = _cache_db_path()
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expire_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_accessed INTEGER NOT NULL,
                    data_type TEXT DEFAULT 'json',
                    size_bytes INTEGER DEFAULT 0
                )
                """
            )
            conn.commit()
    except Exception as exc:
        logger.warning("無法建立 cache 資料表：%s", exc)


# 模組載入時自動初始化資料表
_ensure_cache_table()


# ---------------------------------------------------------------------------
# 月份收盤資料快取
# ---------------------------------------------------------------------------

def _month_cache_key(code: str, year_month: str) -> str:
    return f"twse:month:{code}:{year_month}"


def _is_current_month(year_month: str) -> bool:
    today = date.today()
    return year_month == f"{today.year}{today.month:02d}01"


def _load_month_closes_from_cache(code: str, year_month: str) -> list[float] | None:
    """從快取讀取月份收盤資料，若已過期則回傳 None。"""
    try:
        db_path = _cache_db_path()
        key = _month_cache_key(code, year_month)
        ttl = _MONTH_CACHE_TTL_CURRENT if _is_current_month(year_month) else _MONTH_CACHE_TTL_PAST
        cutoff = int(time.time()) - ttl
        with sqlite3.connect(db_path, timeout=10) as conn:
            row = conn.execute(
                "SELECT value FROM cache WHERE key = ? AND created_at >= ?",
                (key, cutoff),
            ).fetchone()
        if row:
            return json.loads(row[0])
    except Exception as exc:
        logger.debug("讀取月份快取失敗 %s %s：%s", code, year_month, exc)
    return None


def _save_month_closes_to_cache(code: str, year_month: str, closes: list[float]) -> None:
    """將月份收盤資料寫入快取。"""
    if not closes:
        return
    try:
        db_path = _cache_db_path()
        key = _month_cache_key(code, year_month)
        ttl = _MONTH_CACHE_TTL_CURRENT if _is_current_month(year_month) else _MONTH_CACHE_TTL_PAST
        now = int(time.time())
        value = json.dumps(closes)
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache
                    (key, value, expire_at, created_at, last_accessed, data_type, size_bytes)
                VALUES (?, ?, ?, ?, ?, 'json', ?)
                """,
                (key, value, now + ttl, now, now, len(value.encode())),
            )
            conn.commit()
    except Exception as exc:
        logger.debug("寫入月份快取失敗 %s %s：%s", code, year_month, exc)


# ---------------------------------------------------------------------------
# 股票清單快取
# ---------------------------------------------------------------------------

def _load_stock_list_from_cache() -> list[tuple[str, str]] | None:
    """若 7 天內有快取則回傳 (code, name) 清單，否則回傳 None。"""
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
            logger.info("從快取載入股票清單：%d 支", len(stocks))
            return stocks
    except Exception as exc:
        logger.warning("讀取股票清單快取失敗：%s", exc)
    return None


def _save_stock_list_to_cache(stocks: list[tuple[str, str]]) -> None:
    """將 (code, name) 清單寫入 SQLite 快取。"""
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
        logger.info("股票清單已快取：%d 支", len(stocks))
    except Exception as exc:
        logger.warning("寫入股票清單快取失敗：%s", exc)


# ---------------------------------------------------------------------------
# 速率限制與 SSL
# ---------------------------------------------------------------------------

# 最少需要 60（MA窗口）+ 30（評估窗口）+ 1（今日）= 91 筆收盤價
_MIN_CLOSES = 91

# TWSE 速率限制：3 req / 5 sec。我們目標 2 req/s 保持安全邊際。
_RATE_LOCK = asyncio.Lock()
_RATE_INTERVAL = 0.5   # 每請求間隔（秒）
_last_request_time: float = 0.0


async def _rate_limited_sleep() -> None:
    """全域速率限制，確保 TWSE 請求不超速。"""
    global _last_request_time
    async with _RATE_LOCK:
        now = time.monotonic()
        wait = _RATE_INTERVAL - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


def _build_ssl_context() -> ssl.SSLContext:
    """回傳略過憑證驗證的 SSL context。

    TWSE 的 www.twse.com.tw 憑證缺少 Subject Key Identifier，
    導致標準驗證失敗。
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _last_n_months(n: int) -> list[str]:
    """回傳最近 n 個月的月初日期字串（格式 YYYYMMDD）。"""
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


# ---------------------------------------------------------------------------
# 核心掃描邏輯
# ---------------------------------------------------------------------------

async def _fetch_month_closes(
    session: aiohttp.ClientSession,
    ssl_ctx: ssl.SSLContext,
    code: str,
    year_month: str,
) -> list[float]:
    """取得 *code* 在 *year_month* 的每日收盤價（優先讀快取）。"""
    # 優先讀快取
    cached = _load_month_closes_from_cache(code, year_month)
    if cached is not None:
        return cached

    # 快取未命中，向 TWSE 發請求
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
            # 寫入快取
            _save_month_closes_to_cache(code, year_month, closes)
            return closes
    except Exception as exc:
        logger.debug("抓取失敗 %s %s：%s", code, year_month, exc)
        return []


async def _scan_single(
    session: aiohttp.ClientSession,
    ssl_ctx: ssl.SSLContext,
    semaphore: asyncio.Semaphore,
    code: str,
    name: str,
    months: list[str],
    progress: dict[str, Any],
) -> dict[str, Any]:
    """評估單一股票是否符合雙重乖離條件。"""
    async with semaphore:
        closes: list[float] = []
        for month in months:
            month_closes = await _fetch_month_closes(session, ssl_ctx, code, month)
            closes.extend(month_closes)

        # 更新進度
        progress["done"] += 1
        done = progress["done"]
        total = progress["total"]
        if done % 30 == 0 or done == total:
            pct = done / total * 100
            matched_so_far = progress["matched"]
            print(
                f"掃描進度：{done}/{total}（{pct:.0f}%）目前命中 {matched_so_far} 支",
                flush=True,
            )

        if len(closes) < _MIN_CLOSES:
            return {"code": code, "name": name, "matched": False, "skipped": True}

        # 條件一：今日乖離率 0–5%（剛站上 60MA）
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

        # 條件二：近 30 個可評估交易日中，≥24 天為負乖離
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

        if matched:
            progress["matched"] += 1

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
    """掃描所有 *stocks* 的 60MA 乖離條件。

    Args:
        stocks: (code, name) 的清單。
        months: 要抓取的月份（格式 YYYYMMDD），預設最近 6 個月。
        concurrency: 最大並發 TWSE 請求數。

    Returns:
        含 ``matched`` 清單、``total_scanned``、``total_stocks``、``months`` 的字典。
    """
    if months is None:
        months = _last_n_months(6)  # 6個月確保取得足夠的 91+ 筆收盤價

    total = len(stocks)
    progress: dict[str, Any] = {"done": 0, "total": total, "matched": 0}
    print(f"開始掃描 {total} 支股票，月份範圍：{months[0]} ~ {months[-1]}", flush=True)

    ssl_ctx = _build_ssl_context()
    semaphore = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency * 2)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _scan_single(session, ssl_ctx, semaphore, code, name, months, progress)
            for code, name in stocks
        ]
        results: list[dict[str, Any]] = await asyncio.gather(*tasks)

    matched = [r for r in results if r.get("matched")]
    scanned = [r for r in results if not r.get("skipped")]

    print(f"掃描完成：共 {total} 支，有效 {len(scanned)} 支，命中 {len(matched)} 支", flush=True)

    return {
        "total_stocks": total,
        "total_scanned": len(scanned),
        "matched_count": len(matched),
        "matched": matched,
        "months": months,
    }


async def fetch_twse_stock_list(min_trade_value: int = 100_000_000) -> list[tuple[str, str]]:
    """從 TWSE 取得當日股票清單，回傳 (code, name) 對。

    篩選條件：
    - 4位純數字代號（排除 '00xx' ETF、DR、權證）
    - TradeValue（成交金額）> min_trade_value（預設 1 億）

    容錯機制：
    - 成功時：將結果存入 SQLite 快取（TTL 7天）。
    - 失敗或空回應（非交易日）：先嘗試快取回退（最多 7 天前）再拋出例外。
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
                    fetch_error = RuntimeError(f"STOCK_DAY_ALL 回傳 HTTP {resp.status}")
                else:
                    rows = await resp.json(content_type=None)
        except Exception as exc:
            fetch_error = exc

    stocks: list[tuple[str, str]] = []
    for row in rows:
        code = str(row.get("Code", "")).strip()
        name = str(row.get("Name", "")).strip()
        if not (len(code) == 4 and code.isdigit() and not code.startswith("00")):
            continue
        try:
            trade_value = int(str(row.get("TradeValue", "0")).replace(",", ""))
        except ValueError:
            trade_value = 0
        if trade_value > min_trade_value:
            stocks.append((code, name))

    if stocks:
        logger.info("從 TWSE 取得股票清單：篩選後 %d 支", len(stocks))
        _save_stock_list_to_cache(stocks)
        return stocks

    # 空結果 — 非交易日或 API 異常，嘗試快取回退
    reason = str(fetch_error) if fetch_error else "STOCK_DAY_ALL 回傳空清單（非交易日？）"
    logger.warning("無法取得即時股票清單（%s），嘗試快取回退", reason)

    cached = _load_stock_list_from_cache()
    if cached:
        logger.info("使用快取股票清單：%d 支（最多 7 天前）", len(cached))
        return cached

    raise RuntimeError(
        f"無法取得 TWSE 股票清單，且無可用快取。原因：{reason}"
    )
