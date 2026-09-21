# MCP Experience Roadmap

This fork focuses on making Cashew useful for recurring personal-finance decisions through MCP.

## Product Goal

Turn a static Cashew SQLite export into a reliable financial decision layer:

- current spendable cash
- monthly budget status
- budget-aware spending
- upcoming expenses
- month-end cash forecasts
- data-quality checks

## Implemented In This Fork

- Read-only SQLite connections, so the MCP server cannot mutate the backup.
- Paid-only defaults for balances and summaries.
- Balance correction and transfer exclusion for cleaner spending reports.
- `get_upcoming_transactions` for future unpaid expenses.
- `get_available_cash` for day-to-day spendable cash across selected wallets.
- `get_spending_by_budget` using Cashew's `shared_reference_budget_pk` transaction link.
- `get_budgets` now calculates spend from transactions actually linked to each budget.
- `forecast_cashflow` for projecting available cash on a future date with optional salary and variable-spend estimates.
- `get_subscriptions` for upcoming recurring payments, likely subscriptions, and stale recurring entries.
- `audit_data_quality` for stale unpaid, unnamed, unbudgeted, correction, and uncategorised transactions.
- `get_month_status` for an executive monthly view with income, expenses, net, and budget/category totals.
- Config profiles through environment variables for spendable wallets, reserve wallets, correction categories, and ignored budgets.

## High-Value Next Improvements

1. **Budget period resolver**
   - Current Cashew budgets store recurrence metadata.
   - The server should infer the active period for monthly/weekly budgets instead of only using stored start/end dates.

2. **Portuguese finance prompts**
   - Add Codex/ChatGPT-friendly prompt templates for the user's routine:
     weekly check, month-end close, purchase decision, travel budget, and subscription review.

3. **Tests with fixture database**
   - Add a tiny SQLite fixture and tests for budget grouping, available cash, monthly summaries, and upcoming expenses.

4. **Forecast scenarios**
   - Add optimistic/base/conservative spend assumptions.
   - Recommend a daily allowance until the target date.

5. **Subscription confidence scoring**
   - Score recurring detections by cadence consistency and amount variance.
   - Distinguish confirmed upcoming recurring transactions from inferred subscriptions.

## Useful Queries To Support Well

- "Quanto dinheiro tenho disponivel agora?"
- "Quanto dinheiro terei no dia 27 se o salario ainda nao tiver entrado?"
- "Gastos deste mes excluindo Unaccounted e contando recebido."
- "Lista subscricoes ativas e proximas cobrancas."
- "Estou acima do budget em alguma area?"
- "Quanto posso gastar hoje sem comprometer o resto do mes?"

## Safety Principles

- Read-only by default.
- No live sync assumptions.
- Always state backup freshness limitations.
- Keep reserves and owed money separate from spendable cash.
