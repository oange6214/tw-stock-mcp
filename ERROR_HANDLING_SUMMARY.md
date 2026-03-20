# 台灣股票代理 - 錯誤處理系統

## 概覽

tw-stock-mcp MCP 伺服器已實作一套完整的生產就緒錯誤處理系統，提供結構化錯誤回應、適當的驗證、重試機制和斷路器模式，確保強健的運行品質。

## 核心元件

### 1. 自訂例外層級

**基礎例外**：`TwStockAgentError`

- 結構化錯誤資訊，包含代碼、嚴重度和上下文
- 錯誤豐富化能力
- 符合 MCP 協議規範
- 支援 JSON 序列化

**特化例外**：

- **股票例外**：`StockNotFoundError`、`InvalidStockCodeError`、`StockDataUnavailableError`、`StockMarketClosedError`
- **API 例外**：`RateLimitError`、`DataSourceUnavailableError`、`ExternalAPIError`、`TimeoutError`
- **快取例外**：`CacheConnectionError`、`CacheKeyError`、`CacheSerializationError`
- **MCP 例外**：`MCPValidationError`、`MCPResourceError`、`MCPToolError`
- **驗證例外**：`ParameterValidationError`、`DataFormatError`、`TypeValidationError`

### 2. 輸入驗證系統

**股票代號驗證**：

- 台灣股票代號格式驗證（4-6 位數）
- 支援 ETF（0050-0999）和一般股票（1000-9999）
- 股票類型偵測與市場分類
- 批量驗證能力

**參數驗證**：

- 型別檢查與轉換
- 範圍驗證
- 列舉驗證
- 字串長度驗證
- 日期格式驗證

### 3. 錯誤上下文與豐富化

**錯誤上下文**：`ErrorContext`

- 追蹤用的關聯 ID
- 時間戳記
- 股票代號
- 操作名稱
- 使用者 ID
- 請求 ID
- 額外元資料

**錯誤豐富化**：`ErrorEnricher`

- 自動加入上下文
- 例外類型映射
- 嚴重度判斷
- 錯誤原因鏈保存

### 4. 生產錯誤處理模式

**重試管理器**：

- 帶抖動的指數退避
- 可設定的重試策略
- 不可重試錯誤偵測
- 最大重試次數限制

**斷路器**：

- 失敗閾值監控
- 自動狀態管理（CLOSED/OPEN/HALF_OPEN）
- 服務恢復偵測
- 優雅降級

**錯誤裝飾器**：

- `@with_error_handling` - 同步錯誤處理
- `@with_async_error_handling` - 非同步錯誤處理
- `@with_retry` - 重試機制
- `@mcp_error_handler` - MCP tool 錯誤處理

### 5. MCP 協議整合

**MCP 錯誤處理器**：`MCPErrorHandler`

- Tool 錯誤處理
- Resource 錯誤處理
- 驗證錯誤處理
- 符合 JSON-RPC 規範的回應

**回應格式化器**：`MCPResponseFormatter`

- 股票資料格式化
- 價格資料格式化
- 錯誤回應格式化
- 元資料保存

### 6. 日誌與監控

**結構化日誌**：`ErrorLogger`

- 依嚴重度的日誌層級
- 關聯 ID 追蹤
- 上下文保存
- 可設定的輸出

## 實作範例

### 基本錯誤處理

```python
from tw_stock_agent.exceptions import StockNotFoundError
from tw_stock_agent.utils.validation import StockCodeValidator

# 驗證股票代號
try:
    validated_code = StockCodeValidator.validate_stock_code("2330")
except InvalidStockCodeError as e:
    print(f"錯誤：{e.message}")
    print(f"建議：{e.suggestions}")
```

### 服務層搭配裝飾器

```python
@with_async_error_handling(operation="fetch_stock_data")
@with_retry(max_retries=3, base_delay=1.0)
async def fetch_stock_data(stock_code: str):
    # 服務實作
    pass
```

### MCP Tool 錯誤處理

```python
@mcp_error_handler("get_stock_data")
async def get_stock_data_tool(stock_code: str):
    try:
        return await get_stock_data(stock_code)
    except TwStockAgentError as e:
        # 由裝飾器自動處理
        raise
```

### 斷路器使用

```python
circuit_breaker = CircuitBreaker(failure_threshold=3)

async def api_call():
    return await circuit_breaker.acall(external_api_function)
```

## 錯誤回應格式

### 標準錯誤回應

```json
{
  "error": true,
  "error_code": "STOCK_NOT_FOUND",
  "message": "找不到股票代號 '9999' 的股票",
  "severity": "medium",
  "timestamp": "2023-12-01T10:00:00.000000",
  "correlation_id": "abc123-def456-ghi789",
  "stock_code": "9999",
  "suggestions": [
    "請確認股票代號是否正確",
    "請確認該股票是否在台灣股票交易所上市"
  ]
}
```

### MCP 錯誤回應

```json
{
  "error": {
    "code": "STOCK_NOT_FOUND",
    "message": "找不到股票代號 '9999' 的股票",
    "data": {
      "severity": "medium",
      "correlation_id": "abc123-def456-ghi789",
      "timestamp": "2023-12-01T10:00:00.000000",
      "suggestions": ["請確認股票代號是否正確"],
      "context": {
        "stock_code": "9999",
        "operation": "tool_execution_get_stock_data"
      }
    }
  }
}
```

## 驗證規則

### 台灣股票代號

- **格式**：僅限 4-6 位數
- **ETF**：0050-0999（例如 0050 台灣 50 ETF）
- **一般股票**：1000-9999（例如 2330 台積電）
- **保留代號**：0000-0003、9999（無效）

### 常見股票代號範例

- `2330` - 台灣積體電路製造（台積電）
- `2317` - 鴻海精密工業
- `1301` - 台灣塑膠工業
- `0050` - 元大台灣 50 ETF
- `1101` - 台灣水泥

## 測試

錯誤處理系統包含完整的測試：

### 單元測試

- 例外建立與序列化
- 驗證邏輯
- 錯誤豐富化
- 重試機制
- 斷路器功能
- MCP 錯誤處理

### 整合測試

- 端對端錯誤流程
- 服務層整合
- MCP 協議合規性
- 並發錯誤處理
- 真實場景測試

### 執行測試

```bash
# 執行所有錯誤處理測試
uv run pytest tests/unit/test_exceptions.py -v
uv run pytest tests/unit/test_validation.py -v
uv run pytest tests/unit/test_mcp_resource_service.py -v

# 執行整合測試
uv run pytest tests/integration/test_error_handling_integration.py -v
```

## 優點

1. **強健的錯誤處理**：覆蓋所有錯誤情境
2. **生產就緒**：斷路器、重試機制和優雅降級
3. **開發者友善**：清晰的錯誤訊息和有用的建議
4. **MCP 合規**：正確的 JSON-RPC 錯誤回應
5. **可除錯**：關聯 ID 和結構化日誌
6. **可維護**：乾淨的例外層級和錯誤處理模式
7. **高效能**：最小開銷的錯誤處理
8. **可測試**：所有元件的完整測試覆蓋

## 檔案結構

```
tw_stock_agent/
├── exceptions/
│   ├── __init__.py              # 例外匯出
│   ├── base.py                  # 基礎例外類別
│   ├── stock_exceptions.py      # 股票相關例外
│   ├── api_exceptions.py        # API 相關例外
│   ├── cache_exceptions.py      # 快取相關例外
│   ├── mcp_exceptions.py        # MCP 協議例外
│   └── validation_exceptions.py # 驗證例外
├── utils/
│   ├── error_handler.py         # 錯誤處理工具
│   ├── validation.py            # 輸入驗證
│   └── mcp_error_handler.py     # MCP 錯誤處理
└── services/
    └── stock_service.py         # 整合錯誤處理的服務層

tests/
├── unit/
│   ├── test_exceptions.py
│   ├── test_validation.py
│   └── test_mcp_resource_service.py
└── integration/
    └── test_error_handling_integration.py
```

本錯誤處理系統為建立可靠、生產就緒的台灣股票代理 MCP 伺服器應用程式提供了堅實的基礎。
