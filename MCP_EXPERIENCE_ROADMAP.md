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

## High-Value Next Improvements

1. **Cash-flow forecast tool**
   - Inputs: date, expected salary amount/date, selected wallets, excluded budgets.
   - Output: projected available cash with scenarios.

2. **Budget period resolver**
   - Current Cashew budgets store recurrence metadata.
   - The server should infer the active period for monthly/weekly budgets instead of only using stored start/end dates.

3. **Subscription detector**
   - Detect recurring subscriptions from paid and upcoming transactions.
   - Flag stale future transactions and likely cancelled subscriptions.

4. **Data-quality audit**
   - Find uncategorised transactions, unbudgeted transactions, old unpaid transactions, empty names, and corrections included in spending.

5. **Portuguese finance prompts**
   - Add Codex/ChatGPT-friendly prompt templates for the user's routine:
     weekly check, month-end close, purchase decision, travel budget, and subscription review.

6. **Config profiles**
   - Let users define spendable wallets, reserve wallets, ignored budgets, and correction categories in an env/config file.

7. **Tests with fixture database**
   - Add a tiny SQLite fixture and tests for budget grouping, available cash, monthly summaries, and upcoming expenses.

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
