"""数据库层：SQLite 建表、CRUD、聚合查询。

所有 SQL 使用参数化查询防止注入，数据库文件保存在用户目录下。
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
import os, sys
from pathlib import Path
from typing import Generator, Optional


# ── 数据库路径 ──────────────────────────────────────────────────────
def _db_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent / "data"
    else:
        base = Path(__file__).resolve().parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base

DB_PATH = _db_dir() / "account_book.db"
PUBLIC_EXPENSE_CATEGORY = "公费垫付"
REIMBURSEMENT_CATEGORY = "垫付报销"

# ── 建表 ────────────────────────────────────────────────────────────
def init_db() -> None:
    """初始化数据库：建表 + 索引，幂等操作。"""
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS transactions (
                id          TEXT PRIMARY KEY,
                trade_time  DATETIME NOT NULL,
                platform    TEXT NOT NULL,
                trade_type  TEXT NOT NULL,
                amount      REAL NOT NULL,
                category    TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                counterparty TEXT NOT NULL DEFAULT '',
                payment_channel TEXT NOT NULL DEFAULT '',
                import_hash TEXT UNIQUE NOT NULL,
                reimbursement_status TEXT NOT NULL DEFAULT ''
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_time ON transactions(trade_time DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_platform ON transactions(platform)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_category ON transactions(category)"
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
        if "reimbursement_status" not in columns:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN reimbursement_status TEXT NOT NULL DEFAULT ''"
            )


# ── 连接管理 ────────────────────────────────────────────────────────
def _get_connection() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        raise sqlite3.OperationalError(
            f"无法打开数据库文件 {DB_PATH}: {e}\n请检查文件权限或关闭其他正在运行的实例。"
        ) from e

@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """上下文管理器，自动 commit/close。"""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── 写入操作 ────────────────────────────────────────────────────────
def insert_transactions(rows: list[dict]) -> tuple[int, int]:
    """批量插入流水，利用 import_hash 唯一约束自动跳过重复记录。

    Returns:
        (inserted_count, skipped_count)
    """
    if not rows:
        return 0, 0

    total = len(rows)
    inserted = 0

    with get_connection() as conn:
        for row in rows:
            try:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO transactions
                       (id, trade_time, platform, trade_type, amount,
                        category, description, counterparty, payment_channel,
                        import_hash, reimbursement_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        row["trade_time"],
                        row["platform"],
                        row["trade_type"],
                        row["amount"],
                        row.get("category", ""),
                        row.get("description", ""),
                        row.get("counterparty", ""),
                        row.get("payment_channel", ""),
                        row["import_hash"],
                        row.get("reimbursement_status", ""),
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
            except sqlite3.IntegrityError:
                pass

    return inserted, total - inserted


def delete_transaction(transaction_id: str) -> bool:
    """删除单条流水，返回是否成功。"""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        return cursor.rowcount > 0


def update_transaction(
    transaction_id: str,
    trade_time: Optional[str] = None,
    platform: Optional[str] = None,
    trade_type: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    counterparty: Optional[str] = None,
    payment_channel: Optional[str] = None,
    reimbursement_status: Optional[str] = None,
) -> bool:
    """更新单条流水字段，仅更新传入的字段。"""
    fields: dict[str, object] = {}
    if trade_time is not None:
        fields["trade_time"] = trade_time
    if platform is not None:
        fields["platform"] = platform
    if trade_type is not None:
        fields["trade_type"] = trade_type
    if amount is not None:
        fields["amount"] = amount
    if category is not None:
        fields["category"] = category
    if description is not None:
        fields["description"] = description
    if counterparty is not None:
        fields["counterparty"] = counterparty
    if payment_channel is not None:
        fields["payment_channel"] = payment_channel
    if reimbursement_status is not None:
        fields["reimbursement_status"] = reimbursement_status

    if not fields:
        return False

    set_clause = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [transaction_id]

    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE transactions SET {set_clause} WHERE id = ?", values
        )
        return cursor.rowcount > 0


# ── 查询操作 ────────────────────────────────────────────────────────
def query_transactions(
    year_month: str,
    page: int = 1,
    page_size: Optional[int] = 50,
    keyword: str = "",
) -> tuple[list[dict], int]:
    """查询某月流水，支持关键字搜索和可选分页。

    Args:
        year_month: "2026-07" 格式。
        page: 页码，从 1 开始；仅 page_size 非空时生效。
        page_size: 每页条数；传入 None 时返回全部匹配记录。
        keyword: 搜索关键字，模糊匹配 商品说明、分类、交易对方。

    Returns:
        (rows, total_count)
    """
    where = "WHERE strftime('%Y-%m', trade_time) = ?"
    params: list[object] = [year_month]

    if keyword:
        where += " AND (description LIKE ? OR category LIKE ? OR counterparty LIKE ?)"
        like = f"%{keyword}%"
        params.extend([like, like, like])

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM transactions {where}", params
        ).fetchone()[0]

        sql = f"SELECT * FROM transactions {where} ORDER BY trade_time DESC"
        if page_size is not None:
            offset = (page - 1) * page_size
            sql += " LIMIT ? OFFSET ?"
            rows = conn.execute(sql, params + [page_size, offset]).fetchall()
        else:
            rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows], total


def get_available_months() -> list[str]:
    """获取所有有交易记录的月份（降序）。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT strftime('%Y-%m', trade_time) AS m FROM transactions ORDER BY m DESC"
        ).fetchall()
    return [row["m"] for row in rows]


# ── 聚合统计（SQL 层完成，避免前端遍历） ────────────────────────────
def get_monthly_stats() -> list[dict]:
    """月度收支汇总：每月总收入、总支出、条数。

    SQL 层 GROUP BY 聚合，前端直接用于折线图。
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                strftime('%Y-%m', trade_time) AS month,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS expense,
                COUNT(*) AS count
            FROM transactions
            WHERE category NOT IN (?, ?)
            GROUP BY month
            ORDER BY month ASC"""
            , (PUBLIC_EXPENSE_CATEGORY, REIMBURSEMENT_CATEGORY)
        ).fetchall()
    return [dict(row) for row in rows]


def get_monthly_category_stats(year_month: str) -> list[dict]:
    """某月各分类支出汇总（仅支出类，SQL 层聚合）。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                category,
                SUM(ABS(amount)) AS total,
                COUNT(*) AS count
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ? AND amount < 0 AND category != ''
              AND category NOT IN (?, ?)
            GROUP BY category
            ORDER BY total DESC""",
            (year_month, PUBLIC_EXPENSE_CATEGORY, REIMBURSEMENT_CATEGORY),
        ).fetchall()
    return [dict(row) for row in rows]


def get_platform_stats(year_month: str) -> list[dict]:
    """某月各平台支出来源分布。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                platform,
                SUM(ABS(amount)) AS total,
                COUNT(*) AS count
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ? AND amount < 0
              AND category NOT IN (?, ?)
            GROUP BY platform
            ORDER BY total DESC""",
            (year_month, PUBLIC_EXPENSE_CATEGORY, REIMBURSEMENT_CATEGORY),
        ).fetchall()
    return [dict(row) for row in rows]


def get_month_summary(year_month: str) -> dict:
    """某月收支概览：收入总额、支出总额、结余。"""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT
                COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS income,
                COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) AS expense,
                COUNT(*) AS count
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ?
              AND category NOT IN (?, ?)""",
            (year_month, PUBLIC_EXPENSE_CATEGORY, REIMBURSEMENT_CATEGORY),
        ).fetchone()
    result = dict(row)
    result["balance"] = result["income"] - result["expense"]
    return result


def get_reimbursement_summary() -> dict:
    """返回虚拟应收报销账户的待报销与已结清余额。"""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT
                COALESCE(SUM(CASE WHEN reimbursement_status = '待报销' THEN ABS(amount) ELSE 0 END), 0) AS pending,
                COALESCE(SUM(CASE WHEN reimbursement_status = '已结清' THEN ABS(amount) ELSE 0 END), 0) AS settled
            FROM transactions
            WHERE category = ? AND amount < 0""",
            (PUBLIC_EXPENSE_CATEGORY,),
        ).fetchone()
    return dict(row)


def get_reimbursement_records() -> list[dict]:
    """返回全部公费垫付流水，用于仪表盘报销跟踪清单。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT trade_time, counterparty, description, ABS(amount) AS amount,
                      reimbursement_status
            FROM transactions
            WHERE category = ? AND amount < 0
            ORDER BY CASE reimbursement_status WHEN '待报销' THEN 0 ELSE 1 END,
                     trade_time DESC""",
            (PUBLIC_EXPENSE_CATEGORY,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_transactions_count() -> int:
    """总记录数（用于侧边栏展示）。"""
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
