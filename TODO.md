# TODO

## 待完成

- [ ] 資料庫持久化快取（SQLite 開發 / PostgreSQL 生產）
- [ ] 健康檢查 endpoint
- [ ] OAuth 2.1 / API key 驗證（進階）
- [ ] MCP Prompts 支援（互動式股票分析提示）
- [ ] 加密貨幣或總經指標整合（進階）

## 已完成

- [x] 整合為純 FastMCP 架構（移除 FastAPI）
- [x] 全面 async/await（aiohttp）
- [x] Pydantic 結構化輸出模型
- [x] 自訂例外層級（stock / api / cache / mcp / validation）
- [x] 輸入驗證（股票代號格式、參數範圍）
- [x] 重試機制與斷路器
- [x] MCP Resources 實作
- [x] 連線池與速率限制
- [x] 乖離率掃描（`get_deviation_scan`）
