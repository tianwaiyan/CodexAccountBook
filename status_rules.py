"""流水分类专属状态的业务规则。"""

from __future__ import annotations

PUBLIC_EXPENSE_CATEGORY = "公费垫付"
REIMBURSEMENT_CATEGORY = "垫付报销"
PASS_THROUGH_EXPENSE_CATEGORY = "过手转出"
PASS_THROUGH_INCOME_CATEGORY = "过手转入"

EXPENSE_TAGS = ["生存刚需", "品质生活", "自我投资", "人情往来"]
INCOME_TAGS = ["劳动收入", "财产收入", "转移收入"]
EXPENSE_TRADE_TYPES = ("支出", "退款")
INCOME_CATEGORY_TAGS = {
    "工资收入": "劳动收入",
    "兼职收入": "劳动收入",
    "银行利息": "财产收入",
    "其它收入": "转移收入",
}

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


# 这些业务分类不属于个人消费/收入标签体系，标签始终固定为空。
LOCKED_TAG_CATEGORIES = frozenset(STATUS_RULES_BY_CATEGORY)


def build_status_rules(
    public_expense_category: str = PUBLIC_EXPENSE_CATEGORY,
    reimbursement_category: str = REIMBURSEMENT_CATEGORY,
    pass_through_expense_category: str = PASS_THROUGH_EXPENSE_CATEGORY,
    pass_through_income_category: str = PASS_THROUGH_INCOME_CATEGORY,
) -> dict[str, dict[str, object]]:
    """根据当前分类名称生成带业务状态的规则。"""
    return {
        public_expense_category: {
            "trade_type": "支出",
            "statuses": ["待报销", "已结清"],
            "default": "待报销",
        },
        reimbursement_category: {
            "trade_type": "收入",
            "statuses": ["已结清"],
            "default": "已结清",
        },
        pass_through_income_category: {
            "trade_type": "收入",
            "statuses": ["待转出", "已转出"],
            "default": "待转出",
        },
        pass_through_expense_category: {
            "trade_type": "支出",
            "statuses": ["已转出"],
            "default": "已转出",
        },
    }


def status_options(
    trade_type: str,
    category: str,
    rules: dict[str, dict[str, object]] | None = None,
) -> list[str]:
    """返回收支与分类组合允许使用的状态。"""
    rule = (rules or STATUS_RULES_BY_CATEGORY).get(category)
    if not rule or rule["trade_type"] != trade_type:
        return []
    return list(rule["statuses"])


def default_status(
    trade_type: str,
    category: str,
    rules: dict[str, dict[str, object]] | None = None,
) -> str:
    """返回收支与分类组合的新建默认状态；普通流水为空。"""
    rule = (rules or STATUS_RULES_BY_CATEGORY).get(category)
    if not rule or rule["trade_type"] != trade_type:
        return ""
    return str(rule["default"])


def normalise_new_status(
    trade_type: str,
    category: str,
    status: str = "",
    rules: dict[str, dict[str, object]] | None = None,
) -> str:
    """标准化新建或分类切换后的状态，不兼容值回落至默认状态。"""
    options = status_options(trade_type, category, rules)
    if not options:
        return ""
    return status if status in options else default_status(trade_type, category, rules)


def tag_options(
    trade_type: str,
    expense_tags: list[str] | None = None,
    income_tags: list[str] | None = None,
) -> list[str]:
    """返回指定收支类型可用的标签。"""
    if trade_type in EXPENSE_TRADE_TYPES:
        return list(expense_tags if expense_tags is not None else EXPENSE_TAGS)
    if trade_type == "收入":
        return list(income_tags if income_tags is not None else INCOME_TAGS)
    return []


def uses_expense_categories(trade_type: str) -> bool:
    """判断收支类型是否使用支出分类与标签。"""
    return trade_type in EXPENSE_TRADE_TYPES


def normalise_life_tag(
    trade_type: str,
    category: str,
    life_tag: str = "",
    expense_tags: list[str] | None = None,
    income_tags: list[str] | None = None,
    locked_categories: object | None = None,
) -> str:
    """标准化标签，保留用户在有效选项中的手动选择。"""
    categories = locked_categories if locked_categories is not None else LOCKED_TAG_CATEGORIES
    if category in categories:
        return ""
    return life_tag if life_tag in tag_options(trade_type, expense_tags, income_tags) else ""


def default_life_tag(
    trade_type: str,
    category: str,
    income_category_tags: dict[str, str] | None = None,
    expense_category_tags: dict[str, str] | None = None,
    locked_categories: object | None = None,
) -> str:
    """返回分类切换或新建流水时建议填入的默认标签。"""
    categories = locked_categories if locked_categories is not None else LOCKED_TAG_CATEGORIES
    if category in categories:
        return ""
    if trade_type == "收入":
        return (income_category_tags or INCOME_CATEGORY_TAGS).get(category, "")
    if uses_expense_categories(trade_type):
        return (expense_category_tags or {}).get(category, "")
    return ""
