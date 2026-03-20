# tw-stock-agent

台灣股市資料 MCP 伺服器。負責對外提供 MCP tools、resources 與結構化回應。

## 套件管理

只使用 `uv`，禁止使用 pip。

## 專案結構

```
mcp_server.py                        # 主入口（FastMCP）
tw_stock_agent/
├── tools/stock_tools.py             # MCP Tool 實作
├── services/
│   ├── stock_service.py             # 核心股票資料服務
│   ├── market_service.py            # 大盤資料服務
│   ├── cache_service.py             # 快取
│   ├── deviation_service.py         # 乖離率掃描
│   └── mcp_resource_service.py      # MCP Resource 管理
├── providers/
│   ├── twstock_provider.py
│   └── finmind_provider.py
├── models/stock_models.py           # Pydantic 資料模型
├── exceptions/                      # 自訂例外層級
└── utils/                           # 驗證、設定、連線池等
```

## 資料來源限制

- **`get_best_four_points`**：TWSE API 不穩定，fallback 以 `get_price_history` 計算 RSI/MACD/KD
- **廣度資料（上漲/下跌家數）**：MI_INDEX 不提供，`get_market_overview` 的這些欄位回傳 `null`，預期行為
- **TWSE SSL**：`*.twse.com.tw` 有憑證擴充問題，連線池設定略過 SSL 驗證
- **外資/投信籌碼**：目前無法透過 MCP tools 取得，為已知限制

## 新增 Tool 後需重啟

Claude Code 在 session 啟動時載入 MCP tools。新增或修改 `mcp_server.py` 後需重啟才會生效。

臨時解法：直接呼叫底層服務：

```bash
uv run python -c "
import asyncio
from tw_stock_agent.services.deviation_service import run_deviation_scan, fetch_twse_stock_list, _last_n_months
async def main():
    stocks = await fetch_twse_stock_list()
    result = await run_deviation_scan(stocks, _last_n_months(4))
    print(result)
asyncio.run(main())
"
```
