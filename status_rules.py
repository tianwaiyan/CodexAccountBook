"""流水分类专属状态的业务规则。"""

from __future__ import annotations

PUBLIC_EXPENSE_CATEGORY = "公费垫付"
REIMBURSEMENT_CATEGORY = "垫付报销"
PASS_THROUGH_EXPENSE_CATEGORY = "过手转出"
PASS_THROUGH_INCOME_CATEGORY = "过手转入"

STATUS_RULES_BY_CATEGORY: dict[str, dict[str, object]] = {
    PUBLIC_EXPENSE_CATEGORY: {
        "trade_type": "支出",
        "statuses": ["待报销", "已结清"],
        "default": "待报销",
    },
    REIMBURSEMENT_CATEGORY: {
        "trade_type": "收入",
        "statuses": ["已结清"],
        "default": "已结清",
    },
    PASS_THROUGH_INCOME_CATEGORY: {
        "trade_type": "收入",
        "statuses": ["待转出", "已转出"],
        "default": "待转出",
    },
    PASS_THROUGH_EXPENSE_CATEGORY: {
        "trade_type": "支出",
        "statuses": ["已转出"],
        "default": "已转出",
    },
}


def status_options(trade_type: str, category: str) -> list[str]:
    """返回收支与分类组合允许使用的状态。"""
    rule = STATUS_RULES_BY_CATEGORY.get(category)
    if not rule or rule["trade_type"] != trade_type:
        return []
    return list(rule["statuses"])


def default_status(trade_type: str, category: str) -> str:
    """返回收支与分类组合的新建默认状态；普通流水为空。"""
    rule = STATUS_RULES_BY_CATEGORY.get(category)
    if not rule or rule["trade_type"] != trade_type:
        return ""
    return str(rule["default"])


def normalise_new_status(trade_type: str, category: str, status: str = "") -> str:
    """标准化新建或分类切换后的状态，不兼容值回落至默认状态。"""
    options = status_options(trade_type, category)
    if not options:
        return ""
    return status if status in options else default_status(trade_type, category)
