# tw-stock-mcp

台灣股市資料 MCP 服務器。這個專案是整個 workspace 的資料能力層，負責對外提供 MCP tools、resources 與結構化回應。

## 專案定位

在這個 workspace 中：

- `tw-stock-mcp`：資料服務層
- `tw-stock-plugin`：工作流與插件層
- `tw-stock`：報告輸出工作區

## 當前架構

目前主入口是 `mcp_server.py`，已採用 FastMCP 為主要 transport layer。

```text
FastMCP Server
→ tools / resources
→ services
→ providers
→ external data sources
```

更完整說明請看：

- [架構說明](./docs/ARCHITECTURE.md)
- [Provider 能力比較](./docs/provider-capabilities.md)
- [錯誤處理系統](./ERROR_HANDLING_SUMMARY.md)

## 主要能力

### MCP Tools

- `get_stock_data`
- `get_price_history`
- `get_realtime_data`
- `get_best_four_points`
- `get_market_overview`
- `get_deviation_scan`
- `list_resources`
- `subscribe_resource`
- `invalidate_cache`

### MCP Resources

- `stock://info/{stock_code}`
- `stock://price/{stock_code}`
- `stock://price/{stock_code}/{period}`
- `stock://realtime/{stock_code}`
- `stock://analysis/{stock_code}`
- `market://overview`

## 模組分層

### Entry Point

- `mcp_server.py`

### Tool / Resource Adapters

- `tw_stock_agent/tools/stock_tools.py`
- `tw_stock_agent/services/mcp_resource_service.py`

### Services

- `tw_stock_agent/services/stock_service.py`
- `tw_stock_agent/services/market_service.py`
- `tw_stock_agent/services/cache_service.py`

### Providers

- `tw_stock_agent/providers/twstock_provider.py`
- `tw_stock_agent/providers/finmind_provider.py`
- `tw_stock_agent/providers/factory.py`

### Shared Support

- `tw_stock_agent/models/stock_models.py`
- `tw_stock_agent/utils/*`
- `tw_stock_agent/exceptions/*`

## Provider 策略

預設 provider 使用 `twstock`，因為它支援較完整的台股查詢能力，包含 Best Four Points。

若要使用 FinMind：

```env
STOCK_DATA_PROVIDER=finmind
FINMIND_API_TOKEN=your_token
```

注意：

- `finmind` 的 realtime 屬於 best-effort 近似值
- `finmind` 不支援 Best Four Points
- service layer 會在必要時 fallback 到 `twstock`

## 安裝

```bash
uv sync
```

## 啟動

```bash
uv run python mcp_server.py
```

## MCP 設定範例

```json
{
  "mcpServers": {
    "tw-stock-mcp": {
      "command": "uv",
      "args": ["run", "python", "mcp_server.py"],
      "cwd": "/path/to/tw-stock-mcp"
    }
  }
}
```

## 開發

```bash
uv run ruff check .
uv run ruff format .
uv run mypy tw_stock_agent
uv run pytest
```

## 備註

`TODO.md` 仍保留長期 roadmap，但 README 以目前已存在的真實架構為主，而不是過渡期規劃。
