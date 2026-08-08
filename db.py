"""数据库层：SQLite 建表、CRUD、聚合查询。

所有 SQL 使用参数化查询防止注入，数据库文件保存在用户目录下。
"""

from __future__ import annotations

import sqlite3
import uuid
import re
from contextlib import contextmanager
from datetime import datetime
import os, sys
from pathlib import Path
from typing import Generator, Optional
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from status_rules import default_life_tag, normalise_life_tag, normalise_new_status


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
PASS_THROUGH_EXPENSE_CATEGORY = "过手转出"
PASS_THROUGH_INCOME_CATEGORY = "过手转入"
PERSONAL_STATS_EXCLUDED_CATEGORIES = (
    PUBLIC_EXPENSE_CATEGORY,
    REIMBURSEMENT_CATEGORY,
    PASS_THROUGH_EXPENSE_CATEGORY,
    PASS_THROUGH_INCOME_CATEGORY,


)

OPTION_DEFAULTS: dict[str, list[tuple[str, str]]] = {
    "account": [
        ("支付宝", ""), ("微信", ""), ("现金", ""),
        ("北京银行卡", ""), ("中国银行卡", ""), ("交通银行卡", ""), ("美团月付", ""),
    ],
    "expense_category": [
        ("生活费用", ""), ("伙食费用", ""), ("交通出行", ""), ("休闲娱乐", ""),
        ("办公学习", ""), ("外出旅游", ""), ("医疗保健", ""), ("服饰鞋帽", ""),
        ("非日用品", ""), ("其它支出", ""), ("过手转出", "pass_through_expense"),
        ("公费垫付", "public_expense"),
    ],
    "income_category": [
        ("工资收入", ""), ("奖金收入", ""), ("转账收入", ""), ("银行利息", ""),
        ("兼职收入", ""), ("其它收入", ""), ("过手转入", "pass_through_income"),
        ("垫付报销", "reimbursement"),
    ],
    "expense_tag": [("生存刚需", ""), ("品质生活", ""), ("自我投资", ""), ("人情往来", "")],
    "income_tag": [("劳动收入", ""), ("财产收入", ""), ("转移收入", "")],
}

DEFAULT_INCOME_CATEGORY_TAGS = {
    "工资收入": "劳动收入",
    "兼职收入": "劳动收入",
    "银行利息": "财产收入",
    "其它收入": "转移收入",
}

INCOME_CATEGORY_REPLACEMENT_MIGRATION = "replace_living_fee_income_with_bonus_v1"


def round_amount(value: object) -> float:
    """按财务常用的四舍五入规则保留两位小数。"""
    try:
        rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"金额无法转换为数字：{value}") from exc

    return float(rounded)
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
                account     TEXT NOT NULL,
                trade_type  TEXT NOT NULL,
                amount      REAL NOT NULL,
                category    TEXT NOT NULL DEFAULT '',
                remark      TEXT NOT NULL DEFAULT '',
                counterparty TEXT NOT NULL DEFAULT '',
                payment_channel TEXT NOT NULL DEFAULT '',
                import_hash TEXT UNIQUE NOT NULL,
                reimbursement_status TEXT NOT NULL DEFAULT '',
                life_tag TEXT NOT NULL DEFAULT ''
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS option_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                option_type TEXT NOT NULL,
                value TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                system_key TEXT NOT NULL DEFAULT '',
                UNIQUE(option_type, value)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS income_category_tag_mappings (
                category TEXT PRIMARY KEY,
                life_tag TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS category_tag_mappings (
                category_type TEXT NOT NULL,
                category TEXT NOT NULL,
                life_tag TEXT NOT NULL,
                PRIMARY KEY(category_type, category)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS app_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )"""
        )
        for option_type, defaults in OPTION_DEFAULTS.items():
            for sort_order, (value, system_key) in enumerate(defaults):
                conn.execute(
                    """INSERT OR IGNORE INTO option_items
                       (option_type, value, sort_order, system_key) VALUES (?, ?, ?, ?)""",
                    (option_type, value, sort_order, system_key),
                )
        for category, life_tag in DEFAULT_INCOME_CATEGORY_TAGS.items():
            conn.execute(
                """INSERT OR IGNORE INTO income_category_tag_mappings (category, life_tag)
                   VALUES (?, ?)""",
                (category, life_tag),
            )
            conn.execute(
                """INSERT OR IGNORE INTO category_tag_mappings
                   (category_type, category, life_tag) VALUES ('income_category', ?, ?)""",
                (category, life_tag),
            )
        migration = conn.execute(
            "SELECT 1 FROM app_migrations WHERE migration_key = ?",
            (INCOME_CATEGORY_REPLACEMENT_MIGRATION,),
        ).fetchone()
        if migration is None:
            # 仅移除后续可选项与旧映射，历史流水中的旧分类值继续保留。
            conn.execute(
                "DELETE FROM option_items WHERE option_type = 'income_category' AND value = ?",
                ("生活费收入",),
            )
            conn.execute(
                "DELETE FROM income_category_tag_mappings WHERE category = ?",
                ("生活费收入",),
            )
            conn.execute(
                "DELETE FROM category_tag_mappings "
                "WHERE category_type = 'income_category' AND category = ?",
                ("生活费收入",),
            )
            conn.execute(
                "INSERT INTO app_migrations (migration_key, applied_at) VALUES (?, ?)",
                (
                    INCOME_CATEGORY_REPLACEMENT_MIGRATION,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        # 兼容已有版本仅存于旧收入映射表中的用户设置。
        legacy_mappings = conn.execute(
            "SELECT category, life_tag FROM income_category_tag_mappings"
        ).fetchall()
        for mapping in legacy_mappings:
            conn.execute(
                """INSERT INTO category_tag_mappings (category_type, category, life_tag)
                   VALUES ('income_category', ?, ?)
                   ON CONFLICT(category_type, category)
                   DO UPDATE SET life_tag = excluded.life_tag""",
                (mapping["category"], mapping["life_tag"]),
            )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
        if "platform" in columns and "account" not in columns:
            conn.execute("ALTER TABLE transactions RENAME COLUMN platform TO account")
        if "description" in columns and "remark" not in columns:
            conn.execute("ALTER TABLE transactions RENAME COLUMN description TO remark")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
        if "reimbursement_status" not in columns:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN reimbursement_status TEXT NOT NULL DEFAULT ''"
            )
        if "life_tag" not in columns:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN life_tag TEXT NOT NULL DEFAULT ''"
            )
        amount_rows = conn.execute("SELECT id, amount FROM transactions").fetchall()
        amount_updates = [
            (round_amount(row["amount"]), row["id"])
            for row in amount_rows
            if round_amount(row["amount"]) != row["amount"]
        ]
        if amount_updates:
            conn.executemany("UPDATE transactions SET amount = ? WHERE id = ?", amount_updates)
        conn.execute("DROP INDEX IF EXISTS idx_platform")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_time ON transactions(trade_time DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_account ON transactions(account)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_category ON transactions(category)"
        )


def get_option_values(option_type: str) -> list[str]:
    """按用户配置顺序返回可选项。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT value FROM option_items WHERE option_type = ? ORDER BY sort_order, id",
            (option_type,),
        ).fetchall()
    return [str(row["value"]) for row in rows]


def get_option_items(option_type: str) -> list[dict]:
    """返回某类选项及其系统角色，供选项管理界面使用。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT value, system_key FROM option_items
               WHERE option_type = ? ORDER BY sort_order, id""",
            (option_type,),
        ).fetchall()
    return [dict(row) for row in rows]


def reorder_option_values(option_type: str, values: list[str]) -> None:
    """按给定完整顺序持久化某类可选项的展示顺序。"""
    ordered_values = [str(value).strip() for value in values]
    if not ordered_values or any(not value for value in ordered_values):
        raise ValueError("排序内容不能为空")
    if len(ordered_values) != len(set(ordered_values)):
        raise ValueError("排序内容不能重复")

    with get_connection() as conn:
        existing_values = [
            str(row["value"])
            for row in conn.execute(
                "SELECT value FROM option_items WHERE option_type = ? ORDER BY sort_order, id",
                (option_type,),
            ).fetchall()
        ]
        if set(ordered_values) != set(existing_values):
            raise ValueError("排序内容必须与当前可选项完全一致")
        for sort_order, value in enumerate(ordered_values):
            conn.execute(
                "UPDATE option_items SET sort_order = ? WHERE option_type = ? AND value = ?",
                (sort_order, option_type, value),
            )


def save_option_items(
    option_type: str,
    rows: list[dict[str, object]],
    *,
    mapping_type: str | None = None,
    locked_categories: set[str] | None = None,
) -> None:
    """原子保存选项的新增、删除、重命名、标签关联和展示顺序。"""
    if not rows:
        raise ValueError("至少保留一个条目")
    locked_categories = locked_categories or set()
    normalised = [
        {
            "old_value": str(row.get("原名称", "") or "").strip(),
            "value": str(row.get("名称", "") or "").strip(),
            "deleted": bool(row.get("删除", False)),
            "life_tag": str(row.get("自动关联标签", "") or "").strip(),
        }
        for row in rows
    ]
    retained = [row for row in normalised if not row["deleted"]]
    values = [str(row["value"]) for row in retained]
    if not values or any(not value for value in values):
        raise ValueError("至少保留一个条目，且名称不能为空")
    if len(values) != len(set(values)):
        raise ValueError("名称不能重复")

    field_by_type = {
        "account": "account",
        "expense_category": "category",
        "income_category": "category",
        "expense_tag": "life_tag",
        "income_tag": "life_tag",
    }
    field = field_by_type[option_type]
    deleted_values = {str(row["old_value"]) for row in normalised if row["deleted"] and row["old_value"]}
    rename_targets = {
        str(row["old_value"]): str(row["value"])
        for row in retained
        if row["old_value"] and row["old_value"] != row["value"]
    }
    retained_old_values = {
        str(row["old_value"])
        for row in retained
        if row["old_value"]
    }
    occupied_targets = set(rename_targets.values()) & retained_old_values
    if occupied_targets:
        raise ValueError(f"请先使用未占用的名称：{'、'.join(sorted(occupied_targets))} 已存在")

    with get_connection() as conn:
        existing_values = {
            str(row["value"])
            for row in conn.execute(
                "SELECT value FROM option_items WHERE option_type = ?", (option_type,)
            ).fetchall()
        }
        referenced_values = {str(row["old_value"]) for row in normalised if row["old_value"]}
        if existing_values - referenced_values:
            raise ValueError("选项已变化，请刷新后重新编辑")
        if not referenced_values <= existing_values:
            raise ValueError("选项已变化，请刷新后重新编辑")

        for value in deleted_values:
            conn.execute("DELETE FROM option_items WHERE option_type = ? AND value = ?", (option_type, value))
            if option_type == "income_category":
                conn.execute("DELETE FROM income_category_tag_mappings WHERE category = ?", (value,))
            if option_type in ("income_category", "expense_category"):
                conn.execute(
                    "DELETE FROM category_tag_mappings WHERE category_type = ? AND category = ?",
                    (option_type, value),
                )
            elif option_type == "income_tag":
                conn.execute("DELETE FROM income_category_tag_mappings WHERE life_tag = ?", (value,))
                conn.execute("DELETE FROM category_tag_mappings WHERE life_tag = ?", (value,))
            elif option_type == "expense_tag":
                conn.execute("DELETE FROM category_tag_mappings WHERE life_tag = ?", (value,))

        for old_value, new_value in rename_targets.items():
            conn.execute(
                "UPDATE option_items SET value = ? WHERE option_type = ? AND value = ?",
                (new_value, option_type, old_value),
            )
            conn.execute(f"UPDATE transactions SET {field} = ? WHERE {field} = ?", (new_value, old_value))
            if option_type == "income_category":
                conn.execute("UPDATE income_category_tag_mappings SET category = ? WHERE category = ?", (new_value, old_value))
            if option_type in ("income_category", "expense_category"):
                conn.execute(
                    "UPDATE category_tag_mappings SET category = ? WHERE category_type = ? AND category = ?",
                    (new_value, option_type, old_value),
                )
            elif option_type == "income_tag":
                conn.execute("UPDATE income_category_tag_mappings SET life_tag = ? WHERE life_tag = ?", (new_value, old_value))
                conn.execute("UPDATE category_tag_mappings SET life_tag = ? WHERE life_tag = ?", (new_value, old_value))
            elif option_type == "expense_tag":
                conn.execute("UPDATE category_tag_mappings SET life_tag = ? WHERE life_tag = ?", (new_value, old_value))

        existing_after_changes = {
            str(row["value"])
            for row in conn.execute(
                "SELECT value FROM option_items WHERE option_type = ?", (option_type,)
            ).fetchall()
        }
        for value in values:
            if value not in existing_after_changes:
                conn.execute(
                    "INSERT INTO option_items (option_type, value, sort_order) VALUES (?, ?, ?)",
                    (option_type, value, len(existing_after_changes)),
                )
                existing_after_changes.add(value)

        if mapping_type:
            for row in retained:
                value = str(row["value"])
                if value in locked_categories:
                    continue
                conn.execute(
                    """INSERT INTO category_tag_mappings (category_type, category, life_tag)
                       VALUES (?, ?, ?)
                       ON CONFLICT(category_type, category) DO UPDATE SET life_tag = excluded.life_tag""",
                    (mapping_type, value, str(row["life_tag"])),
                )
                if mapping_type == "income_category":
                    conn.execute(
                        """INSERT INTO income_category_tag_mappings (category, life_tag)
                           VALUES (?, ?)
                           ON CONFLICT(category) DO UPDATE SET life_tag = excluded.life_tag""",
                        (value, str(row["life_tag"])),
                    )

        for sort_order, value in enumerate(values):
            conn.execute(
                "UPDATE option_items SET sort_order = ? WHERE option_type = ? AND value = ?",
                (sort_order, option_type, value),
            )


def add_option_value(option_type: str, value: str) -> None:
    """添加一个用户可维护的账户、分类或标签。"""
    value = value.strip()
    if not value:
        raise ValueError("名称不能为空")
    with get_connection() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM option_items WHERE option_type = ?",
            (option_type,),
        ).fetchone()[0]
        try:
            conn.execute(
                "INSERT INTO option_items (option_type, value, sort_order) VALUES (?, ?, ?)",
                (option_type, value, max_order + 1),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该名称已存在") from exc


def rename_option_value(option_type: str, old_value: str, new_value: str) -> int:
    """重命名选项，并同步更新已有流水与收入自动标签关联。"""
    new_value = new_value.strip()
    if not new_value:
        raise ValueError("名称不能为空")
    if old_value == new_value:
        return 0
    field_by_type = {
        "account": "account",
        "expense_category": "category",
        "income_category": "category",
        "expense_tag": "life_tag",
        "income_tag": "life_tag",
    }
    field = field_by_type[option_type]
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "UPDATE option_items SET value = ? WHERE option_type = ? AND value = ?",
                (new_value, option_type, old_value),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该名称已存在") from exc
        if cursor.rowcount == 0:
            raise ValueError("未找到要修改的条目")
        updated = conn.execute(
            f"UPDATE transactions SET {field} = ? WHERE {field} = ?",
            (new_value, old_value),
        ).rowcount
        if option_type == "income_category":
            conn.execute(
                "UPDATE income_category_tag_mappings SET category = ? WHERE category = ?",
                (new_value, old_value),
            )
        if option_type in ("income_category", "expense_category"):
            conn.execute(
                """UPDATE category_tag_mappings SET category = ?
                   WHERE category_type = ? AND category = ?""",
                (new_value, option_type, old_value),
            )
        elif option_type == "income_tag":
            conn.execute(
                "UPDATE income_category_tag_mappings SET life_tag = ? WHERE life_tag = ?",
                (new_value, old_value),
            )
            conn.execute(
                "UPDATE category_tag_mappings SET life_tag = ? WHERE life_tag = ?",
                (new_value, old_value),
            )
        elif option_type == "expense_tag":
            conn.execute(
                "UPDATE category_tag_mappings SET life_tag = ? WHERE life_tag = ?",
                (new_value, old_value),
            )
    return max(updated, 0)


def delete_option_value(option_type: str, value: str) -> int:
    """删除后续可选项，但保留已有流水中的历史值。"""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM option_items WHERE option_type = ? AND value = ?",
            (option_type, value),
        )
        if option_type == "income_category":
            conn.execute("DELETE FROM income_category_tag_mappings WHERE category = ?", (value,))
        if option_type in ("income_category", "expense_category"):
            conn.execute(
                "DELETE FROM category_tag_mappings WHERE category_type = ? AND category = ?",
                (option_type, value),
            )
        elif option_type == "income_tag":
            conn.execute("DELETE FROM income_category_tag_mappings WHERE life_tag = ?", (value,))
            conn.execute("DELETE FROM category_tag_mappings WHERE life_tag = ?", (value,))
        elif option_type == "expense_tag":
            conn.execute("DELETE FROM category_tag_mappings WHERE life_tag = ?", (value,))
    return max(cursor.rowcount, 0)


def get_income_category_tag_mappings() -> dict[str, str]:
    """返回收入分类的自动标签建议。"""
    return get_category_tag_mappings("income_category")


def get_expense_category_tag_mappings() -> dict[str, str]:
    """返回支出分类（含退款）的自动标签建议。"""
    return get_category_tag_mappings("expense_category")


def get_category_tag_mappings(category_type: str) -> dict[str, str]:
    """返回指定分类的自动标签建议。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT category, life_tag FROM category_tag_mappings WHERE category_type = ?",
            (category_type,),
        ).fetchall()
    return {str(row["category"]): str(row["life_tag"]) for row in rows}


def set_income_category_tag_mapping(category: str, life_tag: str) -> None:
    """设置或清除收入分类切换时的自动标签建议。"""
    set_category_tag_mapping("income_category", category, life_tag)
    with get_connection() as conn:
        if life_tag:
            conn.execute(
                """INSERT INTO income_category_tag_mappings (category, life_tag) VALUES (?, ?)
                   ON CONFLICT(category) DO UPDATE SET life_tag = excluded.life_tag""",
                (category, life_tag),
            )
        else:
            conn.execute("DELETE FROM income_category_tag_mappings WHERE category = ?", (category,))


def set_expense_category_tag_mapping(category: str, life_tag: str) -> None:
    """设置或清除支出分类（含退款）的自动标签建议。"""
    set_category_tag_mapping("expense_category", category, life_tag)


def set_category_tag_mapping(category_type: str, category: str, life_tag: str) -> None:
    """设置或清除指定分类的自动标签建议。"""
    with get_connection() as conn:
        if life_tag:
            conn.execute(
                """INSERT INTO category_tag_mappings (category_type, category, life_tag)
                   VALUES (?, ?, ?)
                   ON CONFLICT(category_type, category) DO UPDATE SET life_tag = excluded.life_tag""",
                (category_type, category, life_tag),
            )
        else:
            conn.execute(
                "DELETE FROM category_tag_mappings WHERE category_type = ? AND category = ?",
                (category_type, category),
            )


def get_special_categories() -> dict[str, str]:
    """按系统角色返回当前名称，分类重命名后业务规则仍然生效。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT system_key, value FROM option_items WHERE system_key != ''"
        ).fetchall()
    values = {str(row["system_key"]): str(row["value"]) for row in rows}
    return {
        "public_expense": values.get("public_expense", PUBLIC_EXPENSE_CATEGORY),
        "reimbursement": values.get("reimbursement", REIMBURSEMENT_CATEGORY),
        "pass_through_expense": values.get("pass_through_expense", PASS_THROUGH_EXPENSE_CATEGORY),
        "pass_through_income": values.get("pass_through_income", PASS_THROUGH_INCOME_CATEGORY),
    }


def get_status_rules() -> dict[str, dict[str, object]]:
    """返回适用于当前分类名称的业务状态规则。"""
    from status_rules import build_status_rules

    categories = get_special_categories()
    return build_status_rules(
        public_expense_category=categories["public_expense"],
        reimbursement_category=categories["reimbursement"],
        pass_through_expense_category=categories["pass_through_expense"],
        pass_through_income_category=categories["pass_through_income"],
    )


def get_tag_options(trade_type: str) -> list[str]:
    """返回收支类型对应的当前标签选项。"""
    if trade_type in ("支出", "退款"):
        return get_option_values("expense_tag")
    if trade_type == "收入":
        return get_option_values("income_tag")
    return []


def _personal_stats_excluded_categories() -> tuple[str, str, str, str]:
    categories = get_special_categories()
    return (
        categories["public_expense"],
        categories["reimbursement"],
        categories["pass_through_expense"],
        categories["pass_through_income"],
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
    expense_tags = get_option_values("expense_tag")
    income_tags = get_option_values("income_tag")
    income_category_tags = get_income_category_tag_mappings()
    expense_category_tags = get_expense_category_tag_mappings()
    status_rules = get_status_rules()

    with get_connection() as conn:
        for row in rows:
            try:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO transactions
                       (id, trade_time, account, trade_type, amount,
                        category, remark, counterparty, payment_channel,
                        import_hash, reimbursement_status, life_tag)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        row["trade_time"],
                        row["account"],
                        row["trade_type"],
                        round_amount(row["amount"]),
                        row.get("category", ""),
                        row.get("remark", ""),
                        row.get("counterparty", ""),
                        row.get("payment_channel", ""),
                        row["import_hash"],
                        normalise_new_status(
                            row["trade_type"], row.get("category", ""),
                            row.get("reimbursement_status", ""),
                            status_rules,
                        ),
                        normalise_life_tag(
                            row["trade_type"], row.get("category", ""),
                            row.get("life_tag", ""),
                            expense_tags,
                            income_tags,
                            status_rules,
                        ) or default_life_tag(
                            row["trade_type"], row.get("category", ""),
                            income_category_tags, expense_category_tags, status_rules,
                        ),
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
            except sqlite3.IntegrityError:
                pass

    return inserted, total - inserted


def create_transaction(
    *,
    trade_time: str,
    account: str,
    trade_type: str,
    amount: float,
    category: str = "",
    life_tag: str = "",
    reimbursement_status: str = "",
    remark: str = "",
    counterparty: str = "",
    payment_channel: str = "",
) -> bool:
    """创建一条流水并生成新的去重标识。"""
    inserted, _ = insert_transactions([{
        "trade_time": trade_time,
        "account": account,
        "trade_type": trade_type,
        "amount": amount,
        "category": category,
        "life_tag": life_tag,
        "reimbursement_status": reimbursement_status,
        "remark": remark,
        "counterparty": counterparty,
        "payment_channel": payment_channel,
        "import_hash": f"manual-copy:{uuid.uuid4()}",
    }])
    return inserted == 1


def copy_transaction(transaction_id: str) -> bool:
    """复制一条已有流水，副本使用新的记录 ID 和去重标识。"""
    with get_connection() as conn:
        source = conn.execute(
            """SELECT trade_time, account, trade_type, amount, category, remark,
                      counterparty, payment_channel, reimbursement_status, life_tag
               FROM transactions WHERE id = ?""",
            (transaction_id,),
        ).fetchone()
        if source is None:
            return False
        cursor = conn.execute(
            """INSERT INTO transactions
               (id, trade_time, account, trade_type, amount, category, remark,
                counterparty, payment_channel, import_hash, reimbursement_status, life_tag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), source["trade_time"], source["account"],
                source["trade_type"], round_amount(source["amount"]), source["category"],
                source["remark"], source["counterparty"], source["payment_channel"],
                f"manual-copy:{uuid.uuid4()}", source["reimbursement_status"], source["life_tag"],
            ),
        )
        return cursor.rowcount > 0


def delete_transaction(transaction_id: str) -> bool:
    """删除单条流水，返回是否成功。"""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        return cursor.rowcount > 0


def delete_transactions(transaction_ids: list[str]) -> int:
    """在一次事务内批量删除流水，返回实际删除数量。"""
    ids = list(dict.fromkeys(transaction_id for transaction_id in transaction_ids if transaction_id))
    if not ids:
        return 0

    deleted = 0
    # SQLite 默认最多接受 999 个绑定参数；分块删除仍会共用同一个事务。
    with get_connection() as conn:
        for start in range(0, len(ids), 900):
            batch = ids[start:start + 900]
            placeholders = ", ".join("?" for _ in batch)
            cursor = conn.execute(
                f"DELETE FROM transactions WHERE id IN ({placeholders})", batch
            )
            deleted += max(cursor.rowcount, 0)
    return deleted


def update_transaction(
    transaction_id: str,
    trade_time: Optional[str] = None,
    account: Optional[str] = None,
    trade_type: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    remark: Optional[str] = None,
    counterparty: Optional[str] = None,
    payment_channel: Optional[str] = None,
    reimbursement_status: Optional[str] = None,
    life_tag: Optional[str] = None,
) -> bool:
    """更新单条流水字段，仅更新传入的字段。"""
    fields: dict[str, object] = {}
    if trade_time is not None:
        fields["trade_time"] = trade_time
    if account is not None:
        fields["account"] = account
    if trade_type is not None:
        fields["trade_type"] = trade_type
    if amount is not None:
        fields["amount"] = round_amount(amount)
    if category is not None:
        fields["category"] = category
    if remark is not None:
        fields["remark"] = remark
    if counterparty is not None:
        fields["counterparty"] = counterparty
    if payment_channel is not None:
        fields["payment_channel"] = payment_channel
    if reimbursement_status is not None:
        fields["reimbursement_status"] = reimbursement_status
    if life_tag is not None:
        fields["life_tag"] = life_tag

    if not fields:
        return False

    expense_tags = get_option_values("expense_tag")
    income_tags = get_option_values("income_tag")
    income_category_tags = get_income_category_tag_mappings()
    expense_category_tags = get_expense_category_tag_mappings()
    status_rules = get_status_rules()
    with get_connection() as conn:
        if {"trade_type", "category", "life_tag"} & fields.keys():
            current = conn.execute(
                "SELECT trade_type, category, life_tag FROM transactions WHERE id = ?",
                (transaction_id,),
            ).fetchone()
            if current is None:
                return False
            effective_trade_type = str(fields.get("trade_type", current["trade_type"]))
            effective_category = str(fields.get("category", current["category"]))
            if "life_tag" in fields:
                fields["life_tag"] = normalise_life_tag(
                    effective_trade_type,
                    effective_category,
                    str(fields["life_tag"]),
                    expense_tags,
                    income_tags,
                    status_rules,
                )
            elif "category" in fields or "trade_type" in fields:
                automatic_tag = default_life_tag(
                    effective_trade_type, effective_category,
                    income_category_tags, expense_category_tags, status_rules,
                )
                if automatic_tag:
                    fields["life_tag"] = automatic_tag
                elif "trade_type" in fields:
                    fields["life_tag"] = normalise_life_tag(
                        effective_trade_type,
                        effective_category,
                        str(current["life_tag"]),
                        expense_tags,
                        income_tags,
                        status_rules,
                    )

        set_clause = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [transaction_id]
        cursor = conn.execute(
            f"UPDATE transactions SET {set_clause} WHERE id = ?", values
        )
        return cursor.rowcount > 0


# ── 查询操作 ────────────────────────────────────────────────────────
def _parse_keyword_expression(keyword: str) -> list[list[str]]:
    """解析全局搜索表达式：AND/且 优先于 OR/或。"""
    expression = keyword.strip()
    if not expression:
        return []
    or_groups = re.split(r"\s+\bOR\b\s+|或", expression, flags=re.IGNORECASE)
    return [
        [term.strip() for term in re.split(r"\s+\bAND\b\s+|且", group, flags=re.IGNORECASE) if term.strip()]
        for group in or_groups
        if group.strip()
    ]


def matches_keyword(
    remark: object,
    category: object,
    counterparty: object,
    keyword: str = "",
) -> bool:
    """按查询流水的相同 AND/OR 规则匹配一条草稿记录。"""
    groups = _parse_keyword_expression(keyword)
    if not groups:
        return True
    fields = [str(value or "").casefold() for value in (remark, category, counterparty)]
    return any(
        all(any(term.casefold() in field for field in fields) for term in terms)
        for terms in groups
    )


def query_transactions(
    year_month: Optional[str],
    page: int = 1,
    page_size: Optional[int] = 50,
    keyword: str = "",
) -> tuple[list[dict], int]:
    """查询流水，支持按月份、关键字和可选分页。

    Args:
        year_month: "2026-07" 格式；传入 None 时查询全部月份。
        page: 页码，从 1 开始；仅 page_size 非空时生效。
        page_size: 每页条数；传入 None 时返回全部匹配记录。
        keyword: 搜索表达式，模糊匹配备注、分类、交易对方；支持 AND/且、OR/或。

    Returns:
        (rows, total_count)
    """
    conditions: list[str] = []
    params: list[object] = []

    if year_month:
        conditions.append("strftime('%Y-%m', trade_time) = ?")
        params.append(year_month)

    if keyword:
        keyword_groups = _parse_keyword_expression(keyword)
        group_clauses = []
        for terms in keyword_groups:
            term_clauses = []
            for term in terms:
                term_clauses.append("(remark LIKE ? OR category LIKE ? OR counterparty LIKE ?)")
                like = f"%{term}%"
                params.extend([like, like, like])
            group_clauses.append("(" + " AND ".join(term_clauses) + ")")
        if group_clauses:
            conditions.append("(" + " OR ".join(group_clauses) + ")")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

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
                SUM(CASE WHEN trade_type = '收入' THEN ABS(amount) ELSE 0 END) AS income,
                SUM(CASE WHEN trade_type = '支出' THEN ABS(amount) WHEN trade_type = '退款' THEN -ABS(amount) ELSE 0 END) AS expense,
                COUNT(*) AS count
            FROM transactions
            WHERE category NOT IN (?, ?, ?, ?)
            GROUP BY month
            ORDER BY month ASC"""
            , _personal_stats_excluded_categories()
        ).fetchall()
    return [dict(row) for row in rows]


def get_yearly_category_stats(year: str) -> list[dict]:
    """某年各月份支出分类汇总（个人统计口径）。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                CAST(strftime('%m', trade_time) AS INTEGER) AS month,
                category,
                SUM(CASE WHEN trade_type = '支出' THEN ABS(amount) WHEN trade_type = '退款' THEN -ABS(amount) ELSE 0 END) AS total
            FROM transactions
            WHERE strftime('%Y', trade_time) = ?
              AND trade_type IN ('支出', '退款')
              AND category != ''
              AND category NOT IN (?, ?, ?, ?)
            GROUP BY month, category
            ORDER BY month ASC, category ASC""",
            (year, *_personal_stats_excluded_categories()),
        ).fetchall()
    return [dict(row) for row in rows]


def get_monthly_category_stats(year_month: str) -> list[dict]:
    """某月各分类支出汇总（仅支出类，SQL 层聚合）。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                category,
                SUM(CASE WHEN trade_type = '支出' THEN ABS(amount) WHEN trade_type = '退款' THEN -ABS(amount) ELSE 0 END) AS total,
                COUNT(*) AS count
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ? AND trade_type IN ('支出', '退款') AND category != ''
              AND category NOT IN (?, ?, ?, ?)
            GROUP BY category
            HAVING total > 0
            ORDER BY total DESC""",
            (year_month, *_personal_stats_excluded_categories()),
        ).fetchall()
    return [dict(row) for row in rows]


def get_monthly_income_tag_stats(year_month: str) -> list[dict]:
    """某月个人收入的标签占比。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                life_tag,
                SUM(ABS(amount)) AS total,
                COUNT(*) AS count
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ?
              AND trade_type = '收入'
              AND life_tag != ''
              AND category NOT IN (?, ?, ?, ?)
            GROUP BY life_tag
            ORDER BY total DESC""",
            (year_month, *_personal_stats_excluded_categories()),
        ).fetchall()
    return [dict(row) for row in rows]


def get_monthly_expense_tag_stats(year_month: str) -> list[dict]:
    """某月个人净支出的标签占比，退款按标签抵扣。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                life_tag,
                SUM(CASE WHEN trade_type = '支出' THEN ABS(amount)
                         WHEN trade_type = '退款' THEN -ABS(amount) ELSE 0 END) AS total,
                COUNT(*) AS count
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ?
              AND trade_type IN ('支出', '退款')
              AND life_tag != ''
              AND category NOT IN (?, ?, ?, ?)
            GROUP BY life_tag
            HAVING total > 0
            ORDER BY total DESC""",
            (year_month, *_personal_stats_excluded_categories()),
        ).fetchall()
    return [dict(row) for row in rows]


def get_account_stats(year_month: str) -> list[dict]:
    """某月各账户支出分布。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                account,
                SUM(CASE WHEN trade_type = '支出' THEN ABS(amount) WHEN trade_type = '退款' THEN -ABS(amount) ELSE 0 END) AS total,
                COUNT(*) AS count
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ? AND trade_type IN ('支出', '退款')
              AND category NOT IN (?, ?, ?, ?)
            GROUP BY account
            HAVING total > 0
            ORDER BY total DESC""",
            (year_month, *_personal_stats_excluded_categories()),
        ).fetchall()
    return [dict(row) for row in rows]


def get_month_summary(year_month: str) -> dict:
    """某月收支概览：收入总额、支出总额、结余。"""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT
                COALESCE(SUM(CASE WHEN trade_type = '收入' THEN ABS(amount) ELSE 0 END), 0) AS income,
                COALESCE(SUM(CASE WHEN trade_type = '支出' THEN ABS(amount) WHEN trade_type = '退款' THEN -ABS(amount) ELSE 0 END), 0) AS expense,
                COUNT(*) AS count
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ?
              AND category NOT IN (?, ?, ?, ?)""",
            (year_month, *_personal_stats_excluded_categories()),
        ).fetchone()
    result = dict(row)
    result["balance"] = result["income"] - result["expense"]
    return result


def get_pass_through_summary(year_month: str) -> dict:
    """返回某月过手转出的支出额与过手转入的收入额。"""
    categories = get_special_categories()
    with get_connection() as conn:
        row = conn.execute(
            """SELECT
                COALESCE(SUM(CASE WHEN category = ? AND amount < 0 THEN ABS(amount) ELSE 0 END), 0) AS outgoing,
                COALESCE(SUM(CASE WHEN category = ? AND amount > 0 THEN amount ELSE 0 END), 0) AS incoming
            FROM transactions
            WHERE strftime('%Y-%m', trade_time) = ?""",
            (categories["pass_through_expense"], categories["pass_through_income"], year_month),
        ).fetchone()
    return dict(row)


def get_reimbursement_summary() -> dict:
    """返回虚拟应收报销账户的待报销与已结清余额。"""
    public_expense_category = get_special_categories()["public_expense"]
    with get_connection() as conn:
        row = conn.execute(
            """SELECT
                COALESCE(SUM(CASE WHEN reimbursement_status = '待报销' THEN ABS(amount) ELSE 0 END), 0) AS pending,
                COALESCE(SUM(CASE WHEN reimbursement_status = '已结清' THEN ABS(amount) ELSE 0 END), 0) AS settled
            FROM transactions
            WHERE category = ? AND amount < 0""",
            (public_expense_category,),
        ).fetchone()
    return dict(row)


def get_reimbursement_records() -> list[dict]:
    """返回待报销的公费垫付流水，用于仪表盘报销跟踪清单。"""
    public_expense_category = get_special_categories()["public_expense"]
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT trade_time, counterparty, remark, ABS(amount) AS amount,
                      reimbursement_status
            FROM transactions
            WHERE category = ? AND amount < 0 AND reimbursement_status = '待报销'
            ORDER BY trade_time DESC""",
            (public_expense_category,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_pending_pass_through_income_records() -> list[dict]:
    """返回尚未转出的过手转入流水，用于仪表盘待转出清单。"""
    pass_through_income_category = get_special_categories()["pass_through_income"]
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT trade_time, counterparty, remark, ABS(amount) AS amount,
                      reimbursement_status
               FROM transactions
               WHERE category = ? AND amount > 0 AND reimbursement_status = '待转出'
               ORDER BY trade_time DESC""",
            (pass_through_income_category,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_transactions_count() -> int:
    """总记录数（用于侧边栏展示）。"""
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
