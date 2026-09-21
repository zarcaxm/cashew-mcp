"""
Cashew budget app MCP server.
Connects to the local SQLite database and exposes tools for querying
transactions, spending by category, budgets, and wallet balances.

Database path: ~/Downloads/cashew.sqlite by default.
Override with the CASHEW_DB environment variable.
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

_default_db = Path.home() / "Downloads" / "cashew.sqlite"
DB_PATH = Path(os.environ.get("CASHEW_DB", str(_default_db)))
DEFAULT_SPENDABLE_WALLETS = [
    item.strip()
    for item in os.environ.get("CASHEW_SPENDABLE_WALLETS", "Checkings,Banco").split(",")
    if item.strip()
]
DEFAULT_RESERVE_WALLETS = [
    item.strip()
    for item in os.environ.get(
        "CASHEW_RESERVE_WALLETS",
        "Savings,Emergency Fund,Savings-Rev,Credit Card,Owing",
    ).split(",")
    if item.strip()
]
DEFAULT_CORRECTION_CATEGORIES = [
    item.strip()
    for item in os.environ.get(
        "CASHEW_CORRECTION_CATEGORIES",
        "Balance Correction,Transferencia",
    ).split(",")
    if item.strip()
]
DEFAULT_IGNORED_BUDGETS = [
    item.strip()
    for item in os.environ.get("CASHEW_IGNORED_BUDGETS", "").split(",")
    if item.strip()
]

mcp = FastMCP("cashew-budget")


def get_conn() -> sqlite3.Connection:
    # Open the exported Cashew database read-only. The MCP server is for analysis,
    # not for changing the user's source data.
    conn = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def ts_to_date(ts: int | None) -> str | None:
    """Convert Unix timestamp to ISO date string."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def date_to_ts(date_str: str) -> int:
    """Convert YYYY-MM-DD to Unix timestamp (start of day UTC)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def build_date_filters(
    start_date: str | None,
    end_date: str | None,
    column: str = "t.date_created",
) -> tuple[list[str], list[Any]]:
    """Build SQLite timestamp filters from optional ISO date strings."""
    where: list[str] = []
    params: list[Any] = []
    if start_date:
        where.append(f"{column} >= ?")
        params.append(date_to_ts(start_date))
    if end_date:
        where.append(f"{column} < ?")
        params.append(date_to_ts(end_date) + 86400)
    return where, params


def today_iso() -> str:
    """Return today's local date as YYYY-MM-DD."""
    return datetime.now().strftime("%Y-%m-%d")


def placeholders(values: list[Any]) -> str:
    """Return a SQL placeholder list for a non-empty sequence."""
    return ", ".join("?" for _ in values)


def add_exclusion_filter(
    where: list[str],
    params: list[Any],
    expression: str,
    values: list[str],
) -> None:
    """Append a NOT IN filter when values exist."""
    if values:
        where.append(f"COALESCE({expression}, '') NOT IN ({placeholders(values)})")
        params += values


def add_in_filter(
    where: list[str],
    params: list[Any],
    expression: str,
    values: list[str],
) -> None:
    """Append an IN filter when values exist."""
    if values:
        where.append(f"{expression} IN ({placeholders(values)})")
        params += values


@mcp.tool()
def get_transactions(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    wallet: str | None = None,
    type: str = "all",
    limit: int = 50,
    paid_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Fetch transactions with optional filters.

    Args:
        start_date: Filter from this date (YYYY-MM-DD), inclusive.
        end_date: Filter until this date (YYYY-MM-DD), inclusive.
        category: Filter by category name (case-insensitive, partial match).
        wallet: Filter by wallet name (case-insensitive, partial match).
        type: 'expense', 'income', or 'all' (default).
        limit: Maximum rows to return (default 50, max 500).
        paid_only: If True, only include paid/cleared transactions.

    Returns:
        List of transactions with date, name, amount, category, wallet fields.
    """
    limit = min(limit, 500)

    where: list[str] = []
    params: list[Any] = []

    if paid_only:
        where.append("t.paid = 1")
    date_where, date_params = build_date_filters(start_date, end_date)
    where += date_where
    params += date_params
    if category:
        where.append("(c.name LIKE ? OR c2.name LIKE ?)")
        params += [f"%{category}%", f"%{category}%"]
    if wallet:
        where.append("w.name LIKE ?")
        params.append(f"%{wallet}%")
    if type == "expense":
        where.append("t.income = 0")
    elif type == "income":
        where.append("t.income = 1")

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT
            t.transaction_pk,
            t.name,
            t.amount,
            t.income,
            t.note,
            t.date_created,
            c.name  AS category,
            c2.name AS sub_category,
            w.name  AS wallet,
            w.currency
        FROM transactions t
        LEFT JOIN categories c  ON c.category_pk  = t.category_fk
        LEFT JOIN categories c2 ON c2.category_pk = t.sub_category_fk
        LEFT JOIN wallets w     ON w.wallet_pk     = t.wallet_fk
        {where_clause}
        ORDER BY t.date_created DESC
        LIMIT ?
    """
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "id": r["transaction_pk"],
            "date": ts_to_date(r["date_created"]),
            "name": r["name"],
            "amount": r["amount"],
            "type": "income" if r["income"] else "expense",
            "note": r["note"],
            "category": r["category"],
            "sub_category": r["sub_category"],
            "wallet": r["wallet"],
            "currency": r["currency"],
        }
        for r in rows
    ]


@mcp.tool()
def get_spending_by_category(
    start_date: str | None = None,
    end_date: str | None = None,
    wallet: str | None = None,
    include_income: bool = False,
    paid_only: bool = True,
    exclude_balance_corrections: bool = True,
) -> list[dict[str, Any]]:
    """
    Return total spending (or income) grouped by category.

    Args:
        start_date: Start of period (YYYY-MM-DD). Defaults to all time.
        end_date: End of period (YYYY-MM-DD). Defaults to today.
        wallet: Filter by wallet name (case-insensitive, partial match).
        include_income: If True, include income categories in the result.
        paid_only: If True, only include paid/cleared transactions.
        exclude_balance_corrections: If True, omit balance corrections and transfers.

    Returns:
        List of {category, total, count, currency} sorted by total descending.
    """
    where: list[str] = []
    params: list[Any] = []

    if not include_income:
        where.append("t.income = 0")
    if paid_only:
        where.append("t.paid = 1")
    if exclude_balance_corrections:
        add_exclusion_filter(where, params, "c.name", DEFAULT_CORRECTION_CATEGORIES)

    if start_date:
        where.append("t.date_created >= ?")
        params.append(date_to_ts(start_date))
    if end_date:
        where.append("t.date_created < ?")
        params.append(date_to_ts(end_date) + 86400)
    if wallet:
        where.append("w.name LIKE ?")
        params.append(f"%{wallet}%")

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT
            COALESCE(c.name, 'Uncategorised') AS category,
            SUM(t.amount)                      AS total,
            COUNT(*)                           AS count,
            w.currency
        FROM transactions t
        LEFT JOIN categories c ON c.category_pk = t.category_fk
        LEFT JOIN wallets w    ON w.wallet_pk    = t.wallet_fk
        {where_clause}
        GROUP BY t.category_fk, w.currency
        ORDER BY total ASC
    """

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "category": r["category"],
            "total": round(r["total"], 2),
            "count": r["count"],
            "currency": r["currency"],
        }
        for r in rows
    ]


@mcp.tool()
def get_budgets(include_archived: bool = False) -> list[dict[str, Any]]:
    """
    Return all budgets with their current spending progress.

    Args:
        include_archived: Include archived budgets (default False).

    Returns:
        List of budgets with name, allocated amount, spent, remaining, and period info.
    """
    where = "" if include_archived else "WHERE b.archived = 0"

    sql2 = f"""
        SELECT
            b.budget_pk,
            b.name,
            b.amount       AS budget_amount,
            b.start_date,
            b.end_date,
            b.archived,
            b.reoccurrence,
            b.period_length,
            w.name         AS wallet,
            w.currency     AS wallet_currency
        FROM budgets b
        LEFT JOIN wallets w ON w.wallet_pk = b.wallet_fk
        {where}
        ORDER BY b.name
    """

    recurrence_map = {0: "custom", 1: "monthly", 2: "weekly", 3: "yearly", 4: "daily"}

    with get_conn() as conn:
        budgets = conn.execute(sql2).fetchall()

        result = []
        for b in budgets:
            # Compute spend directly associated with this budget. Cashew records
            # this link on each transaction in shared_reference_budget_pk.
            spent_row = conn.execute(
                """
                SELECT COALESCE(SUM(t.amount), 0) AS spent
                FROM transactions t
                WHERE t.income = 0
                  AND t.paid = 1
                  AND t.shared_reference_budget_pk = ?
                  AND t.date_created >= ?
                  AND t.date_created <  ?
                """,
                (b["budget_pk"], b["start_date"], b["end_date"] + 1),
            ).fetchone()

            spent = abs(spent_row["spent"]) if spent_row else 0
            budget_amount = b["budget_amount"]
            remaining = budget_amount - spent

            result.append(
                {
                    "id": b["budget_pk"],
                    "name": b["name"],
                    "budget_amount": budget_amount,
                    "spent": round(spent, 2),
                    "remaining": round(remaining, 2),
                    "utilisation_pct": round(spent / budget_amount * 100, 1)
                    if budget_amount
                    else None,
                    "start_date": ts_to_date(b["start_date"]),
                    "end_date": ts_to_date(b["end_date"]),
                    "recurrence": recurrence_map.get(b["reoccurrence"], "custom"),
                    "period_length": b["period_length"],
                    "wallet": b["wallet"],
                    "currency": b["wallet_currency"],
                    "archived": bool(b["archived"]),
                }
            )

    return result


@mcp.tool()
def get_wallet_balances(paid_only: bool = True) -> list[dict[str, Any]]:
    """
    Return all wallets with their current balance (sum of all transactions).

    Args:
        paid_only: If True, only include paid/cleared transactions in balances.

    Returns:
        List of wallets: name, currency, balance, income_total, expense_total.
    """
    paid_filter = "AND t.paid = 1" if paid_only else ""

    sql = """
        SELECT
            w.wallet_pk,
            w.name,
            w.currency,
            w.archived,
            COALESCE(SUM(t.amount), 0)                             AS balance,
            COALESCE(SUM(CASE WHEN t.income = 1 THEN t.amount ELSE 0 END), 0) AS income_total,
            COALESCE(SUM(CASE WHEN t.income = 0 THEN t.amount ELSE 0 END), 0) AS expense_total
        FROM wallets w
        LEFT JOIN transactions t ON t.wallet_fk = w.wallet_pk {paid_filter}
        GROUP BY w.wallet_pk
        ORDER BY w.archived, w."order"
    """.format(paid_filter=paid_filter)

    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()

    return [
        {
            "name": r["name"],
            "currency": r["currency"],
            "balance": round(r["balance"], 2),
            "income_total": round(r["income_total"], 2),
            "expense_total": round(r["expense_total"], 2),
            "archived": bool(r["archived"]),
        }
        for r in rows
    ]


@mcp.tool()
def get_available_cash(
    wallets: list[str] | None = None,
    exclude_wallets: list[str] | None = None,
    upcoming_from: str | None = None,
    upcoming_until: str | None = None,
) -> dict[str, Any]:
    """
    Return spendable cash across selected wallets, optionally net of upcoming expenses.

    Args:
        wallets: Wallet names to include. Defaults to day-to-day wallets:
            Checkings and Banco.
        exclude_wallets: Wallet names to exclude from the total. Defaults to
            long-term/reserve buckets: Savings, Emergency Fund, Savings-Rev,
            Credit Card, and Owing.
        upcoming_from: If provided, only include unpaid future expenses from this
            date onward (YYYY-MM-DD). Defaults to today's local date.
        upcoming_until: If provided, subtract unpaid future expenses through this
            date (YYYY-MM-DD) for the included wallets.

    Returns:
        Current balances, total available cash, upcoming expenses, and projected cash.
    """
    included_wallets = wallets or DEFAULT_SPENDABLE_WALLETS
    excluded_wallets = exclude_wallets or DEFAULT_RESERVE_WALLETS

    wallet_placeholders = ", ".join("?" for _ in included_wallets)
    excluded_placeholders = ", ".join("?" for _ in excluded_wallets)
    where = [f"w.name IN ({wallet_placeholders})"]
    params: list[Any] = list(included_wallets)
    if excluded_wallets:
        where.append(f"w.name NOT IN ({excluded_placeholders})")
        params += excluded_wallets

    sql = f"""
        SELECT
            w.name,
            w.currency,
            COALESCE(SUM(t.amount), 0) AS balance
        FROM wallets w
        LEFT JOIN transactions t ON t.wallet_fk = w.wallet_pk AND t.paid = 1
        WHERE {" AND ".join(where)}
        GROUP BY w.wallet_pk
        ORDER BY w."order"
    """

    with get_conn() as conn:
        balance_rows = conn.execute(sql, params).fetchall()

        upcoming_rows: list[sqlite3.Row] = []
        if upcoming_until:
            from_date = upcoming_from or today_iso()
            from_ts = date_to_ts(from_date)
            upcoming_sql = f"""
                SELECT
                    date(t.date_created, 'unixepoch') AS date,
                    t.name,
                    t.amount,
                    c.name AS category,
                    w.name AS wallet,
                    w.currency
                FROM transactions t
                LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
                LEFT JOIN categories c ON c.category_pk = t.category_fk
                WHERE t.paid = 0
                  AND t.income = 0
                  AND w.name IN ({wallet_placeholders})
                  AND t.date_created >= ?
                  AND t.date_created < ?
                ORDER BY t.date_created ASC
            """
            upcoming_rows = conn.execute(
                upcoming_sql,
                [*included_wallets, from_ts, date_to_ts(upcoming_until) + 86400],
            ).fetchall()

    balances = [
        {
            "wallet": r["name"],
            "currency": r["currency"],
            "balance": round(r["balance"], 2),
        }
        for r in balance_rows
    ]
    total_available = round(sum(r["balance"] for r in balance_rows), 2)
    upcoming = [
        {
            "date": r["date"],
            "name": r["name"],
            "amount": round(r["amount"], 2),
            "category": r["category"],
            "wallet": r["wallet"],
            "currency": r["currency"],
        }
        for r in upcoming_rows
    ]
    upcoming_total = round(sum(r["amount"] for r in upcoming_rows), 2)

    return {
        "wallets": balances,
        "total_available": total_available,
        "upcoming_expenses": upcoming,
        "upcoming_total": upcoming_total,
        "projected_available": round(total_available + upcoming_total, 2),
    }


@mcp.tool()
def search_transactions(
    query: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """
    Full-text search over transaction names and notes.

    Args:
        query: Search string (case-insensitive).
        limit: Max results (default 30, max 200).

    Returns:
        Matching transactions ordered by date descending.
    """
    limit = min(limit, 200)
    pattern = f"%{query}%"

    sql = """
        SELECT
            t.transaction_pk,
            t.name,
            t.amount,
            t.income,
            t.note,
            t.date_created,
            c.name  AS category,
            w.name  AS wallet,
            w.currency
        FROM transactions t
        LEFT JOIN categories c ON c.category_pk = t.category_fk
        LEFT JOIN wallets w    ON w.wallet_pk    = t.wallet_fk
        WHERE t.name LIKE ? OR t.note LIKE ?
        ORDER BY t.date_created DESC
        LIMIT ?
    """

    with get_conn() as conn:
        rows = conn.execute(sql, [pattern, pattern, limit]).fetchall()

    return [
        {
            "id": r["transaction_pk"],
            "date": ts_to_date(r["date_created"]),
            "name": r["name"],
            "amount": r["amount"],
            "type": "income" if r["income"] else "expense",
            "note": r["note"],
            "category": r["category"],
            "wallet": r["wallet"],
            "currency": r["currency"],
        }
        for r in rows
    ]


@mcp.tool()
def get_spending_by_budget(
    start_date: str | None = None,
    end_date: str | None = None,
    exclude_budgets: list[str] | None = None,
    include_unbudgeted: bool = True,
    include_income: bool = False,
    exclude_balance_corrections: bool = True,
) -> list[dict[str, Any]]:
    """
    Return spending grouped by Cashew budget using transaction budget links.

    Args:
        start_date: Start of period (YYYY-MM-DD).
        end_date: End of period (YYYY-MM-DD).
        exclude_budgets: Budget names to omit, e.g. ["Unaccounted"].
        include_unbudgeted: Include transactions with no linked budget.
        include_income: Include income transactions in the grouping.
        exclude_balance_corrections: Omit correction/transfer categories.

    Returns:
        List of budget totals with count and amount.
    """
    where: list[str] = ["t.paid = 1"]
    params: list[Any] = []

    if not include_income:
        where.append("t.income = 0")
    if not include_unbudgeted:
        where.append("b.name IS NOT NULL")
    if exclude_balance_corrections:
        add_exclusion_filter(where, params, "c.name", DEFAULT_CORRECTION_CATEGORIES)

    date_where, date_params = build_date_filters(start_date, end_date)
    where += date_where
    params += date_params

    if exclude_budgets:
        placeholders = ", ".join("?" for _ in exclude_budgets)
        where.append(f"COALESCE(b.name, '') NOT IN ({placeholders})")
        params += exclude_budgets

    sql = f"""
        SELECT
            COALESCE(b.name, 'Unbudgeted') AS budget,
            COALESCE(SUM(t.amount), 0) AS total,
            COUNT(*) AS count
        FROM transactions t
        LEFT JOIN categories c ON c.category_pk = t.category_fk
        LEFT JOIN budgets b ON b.budget_pk = t.shared_reference_budget_pk
        WHERE {" AND ".join(where)}
        GROUP BY COALESCE(b.name, 'Unbudgeted')
        ORDER BY total ASC
    """

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "budget": r["budget"],
            "total": round(r["total"], 2),
            "count": r["count"],
        }
        for r in rows
    ]


@mcp.tool()
def get_monthly_summary(
    year: int | None = None,
    wallet: str | None = None,
    paid_only: bool = True,
    exclude_balance_corrections: bool = True,
) -> list[dict[str, Any]]:
    """
    Monthly income vs expense summary.

    Args:
        year: Filter to a specific year (e.g. 2025). Defaults to all years.
        wallet: Filter by wallet name (case-insensitive, partial match).
        paid_only: If True, only include paid/cleared transactions.
        exclude_balance_corrections: If True, omit balance corrections and transfers.

    Returns:
        List of {month, income, expenses, net} sorted chronologically.
    """
    where: list[str] = []
    params: list[Any] = []

    if paid_only:
        where.append("t.paid = 1")
    if exclude_balance_corrections:
        add_exclusion_filter(where, params, "c.name", DEFAULT_CORRECTION_CATEGORIES)
    if wallet:
        where.append("w.name LIKE ?")
        params.append(f"%{wallet}%")

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT
            strftime('%Y-%m', datetime(t.date_created, 'unixepoch')) AS month,
            COALESCE(SUM(CASE WHEN t.income = 1 THEN t.amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN t.income = 0 THEN t.amount ELSE 0 END), 0) AS expenses
        FROM transactions t
        LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
        LEFT JOIN categories c ON c.category_pk = t.category_fk
        {where_clause}
        GROUP BY month
        ORDER BY month
    """

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    result = []
    for r in rows:
        if year and not r["month"].startswith(str(year)):
            continue
        income = round(r["income"], 2)
        expenses = round(r["expenses"], 2)
        result.append(
            {
                "month": r["month"],
                "income": income,
                "expenses": expenses,
                "net": round(income + expenses, 2),
            }
        )

    return result


@mcp.tool()
def get_upcoming_transactions(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Return unpaid future transactions, useful for cash-flow forecasting.

    Args:
        start_date: Filter from this date (YYYY-MM-DD), inclusive.
        end_date: Filter until this date (YYYY-MM-DD), inclusive.
        limit: Maximum rows to return (default 100, max 500).

    Returns:
        Unpaid transactions with date, amount, category, and wallet.
    """
    limit = min(limit, 500)
    where: list[str] = ["t.paid = 0"]
    params: list[Any] = []

    date_where, date_params = build_date_filters(start_date, end_date)
    where += date_where
    params += date_params

    sql = f"""
        SELECT
            t.transaction_pk,
            t.name,
            t.amount,
            t.income,
            t.date_created,
            c.name AS category,
            w.name AS wallet,
            w.currency
        FROM transactions t
        LEFT JOIN categories c ON c.category_pk = t.category_fk
        LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
        WHERE {" AND ".join(where)}
        ORDER BY t.date_created ASC
        LIMIT ?
    """
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "id": r["transaction_pk"],
            "date": ts_to_date(r["date_created"]),
            "name": r["name"],
            "amount": round(r["amount"], 2),
            "type": "income" if r["income"] else "expense",
            "category": r["category"],
            "wallet": r["wallet"],
            "currency": r["currency"],
        }
        for r in rows
    ]


@mcp.tool()
def forecast_cashflow(
    target_date: str,
    start_date: str | None = None,
    wallets: list[str] | None = None,
    expected_income_amount: float = 0,
    expected_income_date: str | None = None,
    expected_income_wallet: str | None = None,
    include_upcoming: bool = True,
    average_daily_spend_days: int = 0,
    exclude_budgets: list[str] | None = None,
) -> dict[str, Any]:
    """
    Forecast available cash on a future date.

    Args:
        target_date: Forecast end date (YYYY-MM-DD).
        start_date: Forecast start date. Defaults to today.
        wallets: Wallets to include. Defaults to configured spendable wallets.
        expected_income_amount: Optional expected income to add, such as salary.
        expected_income_date: Date expected income arrives. Included if within range.
        expected_income_wallet: Wallet where expected income arrives.
        include_upcoming: Include unpaid future transactions in the range.
        average_daily_spend_days: If > 0, estimate variable spend from this many
            recent paid days and project it across the forecast window.
        exclude_budgets: Budget names to exclude from historical variable spend.

    Returns:
        Forecast inputs, current cash, known upcoming movements, estimated
        variable spend, expected income, and projected cash.
    """
    included_wallets = wallets or DEFAULT_SPENDABLE_WALLETS
    from_date = start_date or today_iso()
    ignored_budgets = exclude_budgets if exclude_budgets is not None else DEFAULT_IGNORED_BUDGETS

    with get_conn() as conn:
        wallet_filter = placeholders(included_wallets)
        current_rows = conn.execute(
            f"""
            SELECT w.name, w.currency, COALESCE(SUM(t.amount), 0) AS balance
            FROM wallets w
            LEFT JOIN transactions t ON t.wallet_fk = w.wallet_pk AND t.paid = 1
            WHERE w.name IN ({wallet_filter})
            GROUP BY w.wallet_pk
            ORDER BY w."order"
            """,
            included_wallets,
        ).fetchall()

        upcoming_rows: list[sqlite3.Row] = []
        if include_upcoming:
            upcoming_rows = conn.execute(
                f"""
                SELECT
                    date(t.date_created, 'unixepoch') AS date,
                    t.name,
                    t.amount,
                    c.name AS category,
                    b.name AS budget,
                    w.name AS wallet,
                    w.currency
                FROM transactions t
                LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
                LEFT JOIN categories c ON c.category_pk = t.category_fk
                LEFT JOIN budgets b ON b.budget_pk = t.shared_reference_budget_pk
                WHERE t.paid = 0
                  AND w.name IN ({wallet_filter})
                  AND t.date_created >= ?
                  AND t.date_created < ?
                ORDER BY t.date_created ASC
                """,
                [*included_wallets, date_to_ts(from_date), date_to_ts(target_date) + 86400],
            ).fetchall()

        avg_daily_spend = 0.0
        historical_days = 0
        if average_daily_spend_days > 0:
            where = [
                "t.paid = 1",
                "t.income = 0",
                f"w.name IN ({wallet_filter})",
                "t.date_created >= ?",
                "t.date_created < ?",
            ]
            params: list[Any] = [
                *included_wallets,
                date_to_ts(from_date) - average_daily_spend_days * 86400,
                date_to_ts(from_date),
            ]
            add_exclusion_filter(where, params, "c.name", DEFAULT_CORRECTION_CATEGORIES)
            add_exclusion_filter(where, params, "b.name", ignored_budgets)
            spend_row = conn.execute(
                f"""
                SELECT COALESCE(SUM(t.amount), 0) AS total_spend
                FROM transactions t
                LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
                LEFT JOIN categories c ON c.category_pk = t.category_fk
                LEFT JOIN budgets b ON b.budget_pk = t.shared_reference_budget_pk
                WHERE {" AND ".join(where)}
                """,
                params,
            ).fetchone()
            historical_days = average_daily_spend_days
            avg_daily_spend = (spend_row["total_spend"] or 0) / average_daily_spend_days

    current_balances = [
        {
            "wallet": r["name"],
            "currency": r["currency"],
            "balance": round(r["balance"], 2),
        }
        for r in current_rows
    ]
    current_total = round(sum(r["balance"] for r in current_rows), 2)

    upcoming = [
        {
            "date": r["date"],
            "name": r["name"],
            "amount": round(r["amount"], 2),
            "type": "income" if r["amount"] > 0 else "expense",
            "category": r["category"],
            "budget": r["budget"],
            "wallet": r["wallet"],
            "currency": r["currency"],
        }
        for r in upcoming_rows
    ]
    upcoming_total = round(sum(r["amount"] for r in upcoming_rows), 2)

    expected_income_included = (
        expected_income_amount
        if expected_income_amount
        and expected_income_date
        and from_date <= expected_income_date <= target_date
        else 0
    )

    days = max(0, (date_to_ts(target_date) - date_to_ts(from_date)) // 86400 + 1)
    estimated_variable_spend = round(avg_daily_spend * days, 2)

    return {
        "start_date": from_date,
        "target_date": target_date,
        "wallets": current_balances,
        "current_available": current_total,
        "upcoming_transactions": upcoming,
        "upcoming_total": upcoming_total,
        "expected_income": {
            "date": expected_income_date,
            "wallet": expected_income_wallet,
            "amount": round(expected_income_included, 2),
        },
        "variable_spend_estimate": {
            "based_on_days": historical_days,
            "average_daily_spend": round(avg_daily_spend, 2),
            "forecast_days": days,
            "amount": estimated_variable_spend,
        },
        "projected_available": round(
            current_total + upcoming_total + expected_income_included + estimated_variable_spend,
            2,
        ),
    }


@mcp.tool()
def get_subscriptions(
    start_date: str | None = None,
    end_date: str | None = None,
    min_months: int = 3,
    max_average_amount: float = 100,
    include_stale_unpaid: bool = True,
) -> dict[str, Any]:
    """
    Detect subscriptions from upcoming recurring transactions and paid history.

    Args:
        start_date: Paid-history start date. Defaults to one year before today.
        end_date: Paid-history end date. Defaults to today.
        min_months: Minimum distinct months to treat a merchant as recurring.
        max_average_amount: Maximum absolute average amount for detected services.
        include_stale_unpaid: Include unpaid recurring entries before today.

    Returns:
        Upcoming recurring transactions, detected recurring merchants, and stale
        unpaid recurring entries.
    """
    end = end_date or today_iso()
    start = start_date or ts_to_date(date_to_ts(end) - 365 * 86400) or end

    with get_conn() as conn:
        upcoming_rows = conn.execute(
            """
            SELECT
                date(t.date_created, 'unixepoch') AS date,
                t.name,
                t.amount,
                c.name AS category,
                w.name AS wallet,
                w.currency,
                t.type,
                t.period_length,
                t.reoccurrence
            FROM transactions t
            LEFT JOIN categories c ON c.category_pk = t.category_fk
            LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
            WHERE t.paid = 0
              AND (t.type IN (1, 2) OR t.period_length IS NOT NULL OR t.reoccurrence IS NOT NULL)
              AND t.date_created >= ?
            ORDER BY t.date_created ASC
            """,
            [date_to_ts(end)],
        ).fetchall()

        detected_rows = conn.execute(
            """
            SELECT
                t.name,
                c.name AS category,
                w.name AS wallet,
                w.currency,
                COUNT(*) AS count,
                COUNT(DISTINCT strftime('%Y-%m', t.date_created, 'unixepoch')) AS months,
                AVG(t.amount) AS average_amount,
                SUM(t.amount) AS total,
                MIN(date(t.date_created, 'unixepoch')) AS first_date,
                MAX(date(t.date_created, 'unixepoch')) AS last_date
            FROM transactions t
            LEFT JOIN categories c ON c.category_pk = t.category_fk
            LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
            WHERE t.paid = 1
              AND t.income = 0
              AND COALESCE(t.name, '') != ''
              AND t.date_created >= ?
              AND t.date_created < ?
            GROUP BY lower(t.name), c.name, w.name, w.currency
            HAVING months >= ? AND ABS(average_amount) <= ?
            ORDER BY total ASC
            """,
            [date_to_ts(start), date_to_ts(end) + 86400, min_months, max_average_amount],
        ).fetchall()

        stale_rows: list[sqlite3.Row] = []
        if include_stale_unpaid:
            stale_rows = conn.execute(
                """
                SELECT
                    date(t.date_created, 'unixepoch') AS date,
                    t.name,
                    t.amount,
                    c.name AS category,
                    w.name AS wallet,
                    w.currency
                FROM transactions t
                LEFT JOIN categories c ON c.category_pk = t.category_fk
                LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
                WHERE t.paid = 0
                  AND t.date_created < ?
                  AND (t.type IN (1, 2, 3) OR t.period_length IS NOT NULL OR t.reoccurrence IS NOT NULL)
                ORDER BY t.date_created ASC
                """,
                [date_to_ts(end)],
            ).fetchall()

    return {
        "period": {"start_date": start, "end_date": end},
        "upcoming_recurring": [
            {
                "date": r["date"],
                "name": r["name"],
                "amount": round(r["amount"], 2),
                "category": r["category"],
                "wallet": r["wallet"],
                "currency": r["currency"],
                "type": r["type"],
            }
            for r in upcoming_rows
        ],
        "detected_recurring": [
            {
                "name": r["name"],
                "category": r["category"],
                "wallet": r["wallet"],
                "currency": r["currency"],
                "count": r["count"],
                "months": r["months"],
                "average_amount": round(r["average_amount"], 2),
                "total": round(r["total"], 2),
                "first_date": r["first_date"],
                "last_date": r["last_date"],
            }
            for r in detected_rows
        ],
        "stale_unpaid": [
            {
                "date": r["date"],
                "name": r["name"],
                "amount": round(r["amount"], 2),
                "category": r["category"],
                "wallet": r["wallet"],
                "currency": r["currency"],
            }
            for r in stale_rows
        ],
    }


@mcp.tool()
def audit_data_quality(
    start_date: str | None = None,
    end_date: str | None = None,
    stale_unpaid_before: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Audit common Cashew data-quality issues.

    Args:
        start_date: Start date for paid-transaction checks. Defaults to month start.
        end_date: End date for paid-transaction checks. Defaults to today.
        stale_unpaid_before: Unpaid entries before this date are considered stale.
            Defaults to today.
        limit: Maximum sample rows per issue.

    Returns:
        Issue counts and samples for stale unpaid transactions, missing names,
        unbudgeted spending, correction categories, and uncategorised entries.
    """
    today = today_iso()
    end = end_date or today
    start = start_date or f"{end[:7]}-01"
    stale_before = stale_unpaid_before or today
    limit = min(limit, 200)

    def issue(conn: sqlite3.Connection, sql: str, params: list[Any]) -> dict[str, Any]:
        count_row = conn.execute(f"SELECT COUNT(*) AS count FROM ({sql}) issue_rows", params).fetchone()
        rows = conn.execute(f"{sql} LIMIT ?", [*params, limit]).fetchall()
        return {"count": count_row["count"], "samples": [dict(r) for r in rows]}

    with get_conn() as conn:
        stale_unpaid = issue(
            conn,
            """
            SELECT date(t.date_created, 'unixepoch') AS date, t.name, t.amount, c.name AS category, w.name AS wallet
            FROM transactions t
            LEFT JOIN categories c ON c.category_pk = t.category_fk
            LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
            WHERE t.paid = 0 AND t.date_created < ?
            ORDER BY t.date_created ASC
            """,
            [date_to_ts(stale_before)],
        )
        unnamed = issue(
            conn,
            """
            SELECT date(t.date_created, 'unixepoch') AS date, t.name, t.amount, c.name AS category, w.name AS wallet
            FROM transactions t
            LEFT JOIN categories c ON c.category_pk = t.category_fk
            LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
            WHERE t.paid = 1 AND COALESCE(t.name, '') = ''
              AND t.date_created >= ? AND t.date_created < ?
            ORDER BY t.date_created DESC
            """,
            [date_to_ts(start), date_to_ts(end) + 86400],
        )
        unbudgeted = issue(
            conn,
            """
            SELECT date(t.date_created, 'unixepoch') AS date, t.name, t.amount, c.name AS category, w.name AS wallet
            FROM transactions t
            LEFT JOIN categories c ON c.category_pk = t.category_fk
            LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
            LEFT JOIN budgets b ON b.budget_pk = t.shared_reference_budget_pk
            WHERE t.paid = 1 AND t.income = 0 AND b.name IS NULL
              AND t.date_created >= ? AND t.date_created < ?
            ORDER BY t.date_created DESC
            """,
            [date_to_ts(start), date_to_ts(end) + 86400],
        )
        if DEFAULT_CORRECTION_CATEGORIES:
            correction_filter = placeholders(DEFAULT_CORRECTION_CATEGORIES)
            corrections = issue(
                conn,
                f"""
                SELECT date(t.date_created, 'unixepoch') AS date, t.name, t.amount, c.name AS category, w.name AS wallet
                FROM transactions t
                LEFT JOIN categories c ON c.category_pk = t.category_fk
                LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
                WHERE t.paid = 1 AND c.name IN ({correction_filter})
                  AND t.date_created >= ? AND t.date_created < ?
                ORDER BY t.date_created DESC
                """,
                [*DEFAULT_CORRECTION_CATEGORIES, date_to_ts(start), date_to_ts(end) + 86400],
            )
        else:
            corrections = {"count": 0, "samples": []}
        uncategorised = issue(
            conn,
            """
            SELECT date(t.date_created, 'unixepoch') AS date, t.name, t.amount, w.name AS wallet
            FROM transactions t
            LEFT JOIN wallets w ON w.wallet_pk = t.wallet_fk
            WHERE t.paid = 1 AND t.category_fk IS NULL
              AND t.date_created >= ? AND t.date_created < ?
            ORDER BY t.date_created DESC
            """,
            [date_to_ts(start), date_to_ts(end) + 86400],
        )

    return {
        "period": {"start_date": start, "end_date": end},
        "stale_unpaid": stale_unpaid,
        "unnamed_transactions": unnamed,
        "unbudgeted_expenses": unbudgeted,
        "balance_corrections": corrections,
        "uncategorised_transactions": uncategorised,
    }


@mcp.tool()
def get_month_status(
    month: str | None = None,
    exclude_budgets: list[str] | None = None,
) -> dict[str, Any]:
    """
    Return an executive monthly status summary.

    Args:
        month: Month to analyse in YYYY-MM format. Defaults to current month.
        exclude_budgets: Budget names to exclude from net-with-exclusions.
            Defaults to configured ignored budgets.

    Returns:
        Income, expenses, net, budget totals, category totals, and net excluding
        selected budgets.
    """
    selected_month = month or today_iso()[:7]
    start = f"{selected_month}-01"
    year = int(selected_month[:4])
    month_num = int(selected_month[5:7])
    if month_num == 12:
        next_month = f"{year + 1}-01-01"
    else:
        next_month = f"{year}-{month_num + 1:02d}-01"
    ignored_budgets = exclude_budgets if exclude_budgets is not None else DEFAULT_IGNORED_BUDGETS

    with get_conn() as conn:
        summary_where = [
            "t.paid = 1",
            "t.date_created >= ?",
            "t.date_created < ?",
        ]
        summary_params: list[Any] = [date_to_ts(start), date_to_ts(next_month)]
        add_exclusion_filter(summary_where, summary_params, "c.name", DEFAULT_CORRECTION_CATEGORIES)
        income_expense = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN t.income = 1 THEN t.amount ELSE 0 END), 0) AS income,
                COALESCE(SUM(CASE WHEN t.income = 0 THEN t.amount ELSE 0 END), 0) AS expenses
            FROM transactions t
            LEFT JOIN categories c ON c.category_pk = t.category_fk
            WHERE {" AND ".join(summary_where)}
            """,
            summary_params,
        ).fetchone()

        budget_where = [
            "t.paid = 1",
            "t.income = 0",
            "t.date_created >= ?",
            "t.date_created < ?",
        ]
        budget_params: list[Any] = [date_to_ts(start), date_to_ts(next_month)]
        add_exclusion_filter(budget_where, budget_params, "c.name", DEFAULT_CORRECTION_CATEGORIES)
        category_sql = f"""
            SELECT c.name AS category, COALESCE(SUM(t.amount), 0) AS total, COUNT(*) AS count
            FROM transactions t
            LEFT JOIN categories c ON c.category_pk = t.category_fk
            WHERE {" AND ".join(budget_where)}
            GROUP BY c.name
            ORDER BY total ASC
        """
        category_rows = conn.execute(category_sql, budget_params).fetchall()

        budget_sql = f"""
            SELECT COALESCE(b.name, 'Unbudgeted') AS budget, COALESCE(SUM(t.amount), 0) AS total, COUNT(*) AS count
            FROM transactions t
            LEFT JOIN categories c ON c.category_pk = t.category_fk
            LEFT JOIN budgets b ON b.budget_pk = t.shared_reference_budget_pk
            WHERE {" AND ".join(budget_where)}
            GROUP BY COALESCE(b.name, 'Unbudgeted')
            ORDER BY total ASC
        """
        budget_rows = conn.execute(budget_sql, budget_params).fetchall()

        excluded_total = 0.0
        if ignored_budgets:
            excluded_row = conn.execute(
                f"""
                SELECT COALESCE(SUM(t.amount), 0) AS total
                FROM transactions t
                LEFT JOIN categories c ON c.category_pk = t.category_fk
                LEFT JOIN budgets b ON b.budget_pk = t.shared_reference_budget_pk
                WHERE {" AND ".join(budget_where)}
                  AND b.name IN ({placeholders(ignored_budgets)})
                """,
                [*budget_params, *ignored_budgets],
            ).fetchone()
            excluded_total = excluded_row["total"] or 0.0

    income = round(income_expense["income"], 2)
    expenses = round(income_expense["expenses"], 2)

    return {
        "month": selected_month,
        "income": income,
        "expenses": expenses,
        "net": round(income + expenses, 2),
        "excluded_budgets": ignored_budgets,
        "excluded_budget_expenses": round(excluded_total, 2),
        "net_excluding_budgets": round(income + expenses - excluded_total, 2),
        "by_budget": [
            {"budget": r["budget"], "total": round(r["total"], 2), "count": r["count"]}
            for r in budget_rows
        ],
        "by_category": [
            {"category": r["category"], "total": round(r["total"], 2), "count": r["count"]}
            for r in category_rows
        ],
    }


def main():
    mcp.run()


if __name__ == "__main__":
    main()
