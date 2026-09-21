# cashew-mcp

This project is an MCP server for the Cashew budget app. It exposes read-only SQLite query tools to Claude.

## What this project is

`src/cashew_mcp/server.py` — MCP server using `mcp[cli]` via FastMCP.
`src/cashew_mcp/__init__.py` — public exports for direct imports and tests.
`pyproject.toml` — declares the `cashew-mcp` entry point for `uv run`.
`.claude/commands/cashew.md` — slash command prompt for the `/cashew` dashboard.
`docs/mcp-experience-roadmap.md` — roadmap for product and MCP experience improvements.

## Running the server

```bash
uv run cashew-mcp
```

The server connects to the SQLite file at `~/Downloads/cashew.sqlite` by default.  
Override with `CASHEW_DB=/path/to/file.sqlite uv run cashew-mcp`.

## Database

- `transactions` — `amount` is negative for expenses, positive for income; `date_created` is a Unix timestamp (seconds)
- `categories` — `income=1` marks income categories; `main_category_pk` points to parent for sub-categories
- `budgets` — `reoccurrence`: 0=custom, 1=monthly, 2=weekly, 3=yearly, 4=daily
- `wallets` — each has its own `currency` code (e.g. `inr`, `usd`, `thb`, `omr`)

## Adding a new tool

1. Add a `@mcp.tool()` decorated function to `src/cashew_mcp/server.py`
2. Use `get_conn()` for all DB access
3. Convert timestamps with `ts_to_date()` / `date_to_ts()`
4. Test it: `uv run python3 -c "from cashew_mcp import your_function; print(your_function())"`

## Testing

```bash
uv run python3 -c "from cashew_mcp import get_wallet_balances; import json; print(json.dumps(get_wallet_balances(), indent=2))"
```

## Do not

- Write to the database — all tools are read-only by design
- Commit `cashew.sqlite` — it contains personal financial data
