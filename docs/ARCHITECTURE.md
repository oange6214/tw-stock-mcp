# tw-stock-agent Architecture

`tw-stock-agent` 是台股資料 MCP 服務層，負責把外部資料來源整理成穩定的 MCP tools 與 resources。

## 分層

```text
FastMCP Server (mcp_server.py)
        ↓
Tool / Resource Adapters
        ↓
Services
        ↓
Providers
        ↓
External Data Sources
```

## 模組責任

### Entry Point

- `mcp_server.py`
  - 註冊 MCP tools 與 resources
  - 啟動 FastMCP server
  - 在 transport 邊界把資料轉成 Pydantic response

### Tool Adapters

- `tw_stock_agent/tools/stock_tools.py`
  - 參數驗證
  - period 轉換
  - MCP 回應格式化
  - 不直接處理外部 API 細節

### Resource Adapters

- `tw_stock_agent/services/mcp_resource_service.py`
  - 處理 `stock://...` / `market://...` resource URI
  - 做 resource discovery、resource cache、resource rate limiting
  - 透過 service layer 取資料

### Services

- `tw_stock_agent/services/stock_service.py`
  - 股票資料查詢
  - 快取、重試、provider orchestration
- `tw_stock_agent/services/market_service.py`
  - 大盤總覽與市場摘要
  - 優先使用官方 market API，必要時 fallback
- `tw_stock_agent/services/service_container.py`
  - 共用 service singleton，讓 tools/resources 使用相同的 service 實例

### Providers

- `tw_stock_agent/providers/twstock_provider.py`
- `tw_stock_agent/providers/finmind_provider.py`
- `tw_stock_agent/providers/factory.py`

provider 只負責跟外部資料源溝通，並輸出標準化 dict 給 service 層。

### Cross-cutting

- `tw_stock_agent/models/stock_models.py`: Pydantic response models
- `tw_stock_agent/utils/validation.py`: 參數驗證
- `tw_stock_agent/utils/mcp_error_handler.py`: MCP 錯誤與回應格式
- `tw_stock_agent/exceptions/*`: typed exception hierarchy

## 呼叫鏈

### Tool 路徑

```text
MCP Tool
→ stock_tools
→ stock_service / market_service
→ provider
→ external API
```

### Resource 路徑

```text
MCP Resource URI
→ ResourceManager
→ stock_service / market_service
→ provider or official market API
```

## 目前設計原則

- `tools` 與 `resources` 都是 adapter，不承載核心商業邏輯
- `services` 是主要邏輯邊界
- `providers` 可替換，但能力不一定相同
- 對外回應盡量走 Pydantic model 與一致的 metadata
