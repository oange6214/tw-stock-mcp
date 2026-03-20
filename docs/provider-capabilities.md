# Provider Capabilities

這份文件說明 `tw-stock-agent` 目前各 provider 的能力差異。

## Capability Matrix

| Capability | `twstock` | `finmind` | Notes |
|---|---|---|---|
| Stock info | Yes | Yes | 皆可提供基本個股資料 |
| Price history | Yes | Yes | `finmind` 以 REST API 取資料 |
| Realtime data | Yes | Partial | `finmind` 以當日最新價格近似 realtime |
| Best Four Points | Yes | No | `finmind` 不支援，service 會 fallback 到 `twstock` |
| Market overview | No | No | 由 `MarketService` 使用官方 market API 提供 |

## 預設 provider

系統預設使用 `twstock`，原因：

- 功能較完整
- 不依賴 FinMind token
- 可支援 Best Four Points 分析

若需要較穩定的歷史價格 REST API，可切換為 `finmind`：

```env
STOCK_DATA_PROVIDER=finmind
FINMIND_API_TOKEN=...
```

## 設計原則

- provider 只保證自己支援的能力
- 不把 market overview 視為 stock provider 的責任
- 若功能缺口是可接受的，交由 service layer fallback 或明確回錯
