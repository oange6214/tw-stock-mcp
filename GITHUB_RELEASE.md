# `tw-stock-mcp` GitHub 發布摘要

這個 repo 適合作為 **MCP server / data tools layer** 單獨發布。

## 應發布內容

- MCP server 程式碼
- `tw_stock_mcp/`
- `docs/`
- `tests/`
- `README.md`
- `pyproject.toml`
- `uv.lock`

## 不應發布內容

- `.env`
- `.venv/`
- `.claude/`
- `__pycache__/`
- cache / log / coverage 產物

## 發布前檢查

在此目錄執行：

```bash
git status --short --ignored=matching
```

你應該看到像這樣的本機內容被忽略：

- `.env`
- `.venv/`
- `.claude/`
- `__pycache__/`

## 目前重點

這個 repo 目前主要需要提交的是：

- `.gitignore` 的忽略規則更新

如果 `git status` 沒有其他業務邏輯變更，代表這個 repo 已接近可直接發布狀態。

## 建議提交順序

```bash
git add .gitignore GITHUB_RELEASE.md
git status
```

確認沒有把以下內容加進去：

- `.env`
- `.venv/`
- `.claude/`
- `__pycache__/`
