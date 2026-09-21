# cashew-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that connects to your local [Cashew](https://github.com/jameskokoska/Cashew) budget app database and lets you query your finances directly from an MCP client such as Claude Code or Codex.

> Cashew is a free, open-source budgeting app. This MCP server works with the SQLite export from the app.

> **Note:** The MCP server reads from a local SQLite file — it does not sync live with the app. To query your latest transactions and balances, export a fresh backup from Cashew (**Settings → Export Data → Export as SQLite database**) before each session.

This fork is focused on a better MCP personal-finance experience: spendable cash, budget-aware reports, upcoming expenses, and month-end decision support.

---

## What you can do

Ask Claude things like:

- "How much have I spent this month?"
- "Show my top spending categories in 2025"
- "Am I over budget?"
- "Search for Swiggy transactions"
- "What's my current bank balance?"
- "How much money do I have available to spend?"
- "Show spending by budget, excluding Unaccounted"
- "Which upcoming expenses will hit before salary day?"
- "How much money should I have available on salary day?"
- "Which subscriptions look active?"
- "Audit my Cashew data quality for this month"

Or just type `/cashew` for a full financial dashboard.

---

## Requirements

- [Claude Code](https://claude.ai/code) (CLI or desktop app)
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- The Cashew app with a SQLite export saved to `~/Downloads/cashew.sqlite`

---

## Setup

### 1. Export your Cashew database

In the Cashew app:  
**Settings → Export Data → Export as SQLite database**

Save it to `~/Downloads/cashew.sqlite` (the default location).

### 2. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. Clone this repository

```bash
git clone https://github.com/YOUR_USERNAME/cashew-mcp.git
cd cashew-mcp
```

### 4. Register the MCP server with Claude Code

```bash
claude mcp add cashew -- uv run --project $(pwd) cashew-mcp
```

Or with an explicit path:

```bash
claude mcp add cashew -- uv run --project /full/path/to/cashew-mcp cashew-mcp
```

### 5. Install the `/cashew` slash command

```bash
mkdir -p ~/.claude/commands
cp .claude/commands/cashew.md ~/.claude/commands/cashew.md
```

### 6. Restart Claude Code and test

Type `/cashew` in Claude Code. You should see a dashboard with your balances, budgets, and this month's spending.

---

## Available tools

| Tool | What it does |
|------|-------------|
| `get_transactions` | Fetch transactions with filters: date range, category, wallet, type |
| `get_spending_by_category` | Total spending grouped by category for any period |
| `get_spending_by_budget` | Total spending grouped by Cashew budget using transaction budget links |
| `get_budgets` | Budget list with linked spend, remaining, and % used |
| `get_wallet_balances` | Current balance, total income, and total expenses per account |
| `get_available_cash` | Spendable cash across selected wallets, optionally net of upcoming expenses |
| `get_upcoming_transactions` | Unpaid future transactions for cash-flow forecasting |
| `search_transactions` | Full-text search across transaction names and notes |
| `get_monthly_summary` | Month-by-month income vs expenses |
| `forecast_cashflow` | Project available cash on a target date using selected wallets, upcoming transactions, optional salary, and optional variable-spend estimate |
| `get_subscriptions` | Detect upcoming recurring payments, likely subscriptions from history, and stale unpaid recurring entries |
| `audit_data_quality` | Find stale unpaid entries, missing names, unbudgeted spending, correction entries, and uncategorised transactions |
| `get_month_status` | Executive monthly status: income, expenses, net, budget totals, category totals, and net excluding selected budgets |

---

## Custom database path

If your Cashew export is somewhere other than `~/Downloads/cashew.sqlite`, set the `CASHEW_DB` environment variable when registering the server:

```bash
claude mcp add cashew -- uv run --project /path/to/cashew-mcp cashew-mcp
# then edit ~/.claude.json to add: "env": { "CASHEW_DB": "/your/path/cashew.sqlite" }
```

Or export it in your shell before launching Claude Code:

```bash
export CASHEW_DB=/custom/path/to/cashew.sqlite
```

You can also tune the default finance profile used by the decision-support tools:

```bash
export CASHEW_SPENDABLE_WALLETS=Checkings,Banco
export CASHEW_RESERVE_WALLETS="Savings,Emergency Fund,Savings-Rev,Credit Card,Owing"
export CASHEW_CORRECTION_CATEGORIES="Balance Correction,Transferencia"
export CASHEW_IGNORED_BUDGETS=Unaccounted
```

These defaults control what counts as day-to-day cash, what is treated as reserve or owed money, which categories are excluded from clean spending reports, and which budgets are ignored in "available money" style summaries.

---

## Using the `/cashew` command

| Invocation | What happens |
|---|---|
| `/cashew` | Full dashboard: balances, budgets, this month's spending by category |
| `/cashew how much did I spend on food this month?` | Answers the specific question |
| `/cashew search swiggy` | Searches transactions by name |
| `/cashew show monthly summary for 2025` | Year overview |
| `/cashew forecast cash on 2026-09-27 with salary 1484` | Cash-flow projection to a target date |
| `/cashew subscriptions` | Recurring payments and likely subscriptions |
| `/cashew audit this month` | Data-quality checks for the active month |

---

## Compatibility

Tested with the Android and iOS versions of Cashew. The SQLite schema here matches the app as of May 2025. If you hit issues, please open a GitHub issue with the output of:

```bash
sqlite3 ~/Downloads/cashew.sqlite ".schema"
```

---

## License

MIT
