"""个人记账系统 —— Streamlit 前端。

页面：仪表盘 / 流水列表 / 导入账单 / 手动记账。
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import math

from matplotlib import colormaps, colors
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import time
import uuid

import db
import status_rules as sr
from local_transaction_editor import (
    local_table_viewer,
    option_editor,
    segmented_time_input,
    transaction_editor,
    transaction_viewer,
    yearly_category_viewer,
)
import parser as p


DATETIME_24H_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── 页面配置 ─────────────────────────────────────────────────────────
st.set_page_config(page_title="个人记账系统", page_icon="💰", layout="wide")

# ── 初始化数据库 ─────────────────────────────────────────────────────
db.init_db()

# ── 统一样式 ─────────────────────────────────────────────────────────
STYLE = """
<style>
    .stat-card {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    .stat-card .label { font-size: 13px; color: #6b7280; }
    .stat-card .value { font-size: 24px; font-weight: 700; }
    .income { color: #10b981; }
    .expense { color: #ef4444; }
    .balance { color: #3b82f6; }
    [data-testid="stMainBlockContainer"],
    section.main > div.block-container {
        padding-top: 3rem;
        padding-bottom: 1.5rem;
    }
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div:first-child {
        width: 240px !important;
        min-width: 240px !important;
        max-width: 240px !important;
        flex-basis: 240px !important;
    }
    [data-testid="stSidebar"] div[style*="cursor: col-resize"] {
        display: none !important;
    }
    [class*="st-key-tx_month_button_"] button {
        min-height: 36px;
        padding-inline: 0.15rem;
        font-size: 0.75rem;
        width: calc(100% - 5px) !important;
    }
    .st-key-tx_year [data-testid="stSelectbox"] {
        width: calc(100% - 5px);
    }
    .st-key-dashboard_period_toolbar [data-testid="stHorizontalBlock"] {
        column-gap: 10px !important;
    }
    .st-key-dashboard_period_toolbar [data-testid="stColumn"] {
        min-width: 0;
    }
    .st-key-dashboard_period_toolbar [data-testid="stButton"] button {
        width: 100%;
    }
    .st-key-dashboard_period_toolbar [data-testid="stSelectbox"] {
        min-width: 0;
    }
    /* Streamlit 会为带 key 的容器增加一层只有工具栏高度的包装层，
       吸顶定位必须作用在该包装层，才能随主内容区域持续固定。 */
    [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"]:has(> .st-key-dashboard_period_toolbar) {
        position: sticky;
        top: 3rem;
        z-index: 10;
        background: var(--background-color, #ffffff);
        padding: 0.35rem 0 0.6rem;
        border-bottom: 1px solid rgba(148, 163, 184, 0.28);
    }
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)

# ── 常量 ─────────────────────────────────────────────────────────────
ACCOUNTS = db.get_option_values("account")
TRADE_TYPES = ["支出", "退款", "收入"]
EXPENSE_CATEGORIES = db.get_option_values("expense_category")
INCOME_CATEGORIES = db.get_option_values("income_category")
SPECIAL_CATEGORIES = db.get_special_categories()
PUBLIC_EXPENSE_CATEGORY = SPECIAL_CATEGORIES["public_expense"]
REIMBURSEMENT_CATEGORY = SPECIAL_CATEGORIES["reimbursement"]
PASS_THROUGH_EXPENSE_CATEGORY = SPECIAL_CATEGORIES["pass_through_expense"]
PASS_THROUGH_INCOME_CATEGORY = SPECIAL_CATEGORIES["pass_through_income"]
EXPENSE_TAGS = db.get_option_values("expense_tag")
INCOME_TAGS = db.get_option_values("income_tag")
INCOME_CATEGORY_TAGS = db.get_income_category_tag_mappings()
EXPENSE_CATEGORY_TAGS = db.get_expense_category_tag_mappings()
STATUS_RULES = db.get_status_rules()
EMPTY_FILTER_OPTION = "空白"


# ══════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════

def _format_money(value: float) -> str:
    """金额格式化，带颜色标记。"""
    if value >= 0:
        return f"¥{value:,.2f}"
    return f"-¥{abs(value):,.2f}"


def _tx_global_search_active(keyword: object) -> bool:
    """全局搜索框有有效关键词时，查询范围固定为整个数据库。"""
    return bool(str(keyword or "").strip())


def _format_amount_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """将表格中的金额字段格式化为两位小数，不改写数据库数据。"""
    formatted = frame.copy()
    for column in ("amount", "金额"):
        if column in formatted.columns:
            formatted[column] = formatted[column].map(
                lambda value: "" if pd.isna(value) else f"{float(value):.2f}"
            )


    return formatted


def _render_local_table(
    frame: pd.DataFrame,
    *,
    table_key: str,
    empty_message: str = "暂无数据。",
    height: int = 360,
) -> None:
    """使用统一的本地表格组件展示页面中的只读数据。"""
    display_frame = frame.copy().where(pd.notna(frame), "")
    for column in display_frame.columns:
        display_frame[column] = display_frame[column].map(
            lambda value: value.isoformat(sep=" ")
            if isinstance(value, (pd.Timestamp, datetime)) else str(value)
        )
    columns = [
        {
            "key": str(column),
            "label": str(column),
            "width": max(95, min(220, len(str(column)) * 22 + 70)),
        }
        for column in display_frame.columns
    ]
    rows = display_frame.to_dict(orient="records")
    version = hash(display_frame.to_json(force_ascii=False, date_format="iso"))
    local_table_viewer(
        rows=rows,
        columns=columns,
        version=version,
        layout_key=f"account_book_{table_key}_layout_v1",
        empty_message=empty_message,
        height=height,
        key=f"{table_key}_{version}",
    )
# ── 流水列表编辑辅助 ──────────────────────────────────────────────────
TX_EDITOR_COLUMNS = ["时间", "账户", "收支", "金额", "分类", "标签", "报销状态", "备注", "对方", "支付方式"]


def _reset_tx_editor() -> None:
    """使流水编辑器在下次渲染时从数据库重新加载。"""
    draft_session_id = st.session_state.get("tx_edit_session_id")
    if draft_session_id:
        st.session_state["tx_draft_cleanup_session_id"] = draft_session_id
    st.session_state["tx_editor_version"] = st.session_state.get("tx_editor_version", 0) + 1
    st.session_state["tx_baseline"] = None
    st.session_state["tx_editor_current"] = None
    st.session_state["tx_dirty"] = False
    st.session_state["tx_editor_seed"] = None
    st.session_state["merged_df"] = None
    st.session_state["tx_selected_ids"] = []
    st.session_state["tx_edit_mode"] = False
    st.session_state["tx_edit_baseline"] = None
    st.session_state["tx_edit_context"] = None
    st.session_state["tx_edit_cancel_requested"] = False
    st.session_state["tx_edit_error"] = None
    st.session_state["tx_edit_deleted_ids"] = []
    st.session_state["tx_edit_loaded_months"] = []
    st.session_state["tx_edit_session_id"] = None
    st.session_state["tx_edit_instance_version"] = 0
    st.session_state["tx_edit_view_mode"] = "month"
    st.session_state["tx_edit_search_rows"] = None
    st.session_state["tx_edit_search_ids"] = []
    st.session_state["tx_single_edit_id"] = None
    st.session_state["tx_single_edit_row"] = None
    st.session_state["tx_edit_version"] = st.session_state.get("tx_edit_version", 0) + 1


def _categories_for_trade_type(trade_type: str, current_category: str = "") -> list[str]:
    """返回指定收支类型的分类，兼容保留历史导入分类。"""
    categories = EXPENSE_CATEGORIES if sr.uses_expense_categories(trade_type) else INCOME_CATEGORIES
    if current_category and current_category not in categories:
        categories = [*categories, current_category]
    return categories

def _tag_options_for_trade_type(trade_type: str) -> list[str]:
    """返回指定收支类型的标签选项。"""
    return sr.tag_options(trade_type, EXPENSE_TAGS, INCOME_TAGS)



def _tag_is_locked(category: str) -> bool:
    """判断业务专属分类是否禁止修改标签。"""
    return category in STATUS_RULES


def _tag_options_for_category(trade_type: str, category: str) -> list[str]:
    """返回分类实际可编辑的标签选项。"""
    return [] if _tag_is_locked(category) else _tag_options_for_trade_type(trade_type)

def _normalise_reimbursement_fields(editor_df: pd.DataFrame, baseline: pd.DataFrame | None) -> pd.DataFrame:
    """同步收支、分类与报销状态间的业务规则。"""
    normalised = editor_df.copy(deep=True)
    baseline_by_id = {}
    if baseline is not None:
        baseline_by_id = {
            _text_value(row["记录ID"]): row for _, row in baseline.iterrows()
        }

    for index, row in normalised.iterrows():
        transaction_id = _text_value(row["记录ID"])
        trade_type = _text_value(row["收支"])
        category = _text_value(row["分类"])
        status = _text_value(row.get("报销状态", ""))
        life_tag = _text_value(row.get("标签", ""))
        original = baseline_by_id.get(transaction_id)
        original_trade_type = _text_value(original["收支"]) if original is not None else trade_type
        if trade_type != original_trade_type and category not in _categories_for_trade_type(trade_type):
            category = ""

        status = sr.normalise_new_status(trade_type, category, status, STATUS_RULES)
        life_tag = sr.normalise_life_tag(trade_type, category, life_tag, EXPENSE_TAGS, INCOME_TAGS, STATUS_RULES)

        normalised.at[index, "分类"] = category
        normalised.at[index, "标签"] = life_tag
        normalised.at[index, "报销状态"] = status
    return normalised


def _empty_tx_column_filters() -> dict:
    """返回未启用任何字段筛选的标准状态。"""
    return {
        "accounts": [],
        "trade_types": [],
        "categories": [],
        "life_tags": [],
        "reimbursement_statuses": [],
        "amount_min": None,
        "amount_max": None,
    }


def _normalise_tx_column_filters(filters: dict | None) -> dict:
    """标准化会话状态中的字段筛选，便于可靠比较与应用。"""
    filters = filters or {}
    return {
        "accounts": sorted(filters.get("accounts", [])),
        "trade_types": sorted(filters.get("trade_types", [])),
        "categories": sorted(filters.get("categories", [])),
        "life_tags": sorted(filters.get("life_tags", [])),
        "reimbursement_statuses": sorted(filters.get("reimbursement_statuses", [])),
        "amount_min": filters.get("amount_min"),
        "amount_max": filters.get("amount_max"),
    }


def _set_tx_column_filters(filters: dict, *, update_draft: bool = True) -> None:
    """写入已应用字段筛选，并在需要时同步筛选表单草稿。"""
    filters = _normalise_tx_column_filters(filters)
    st.session_state["tx_column_filters"] = filters
    if update_draft:
        st.session_state["tx_filter_accounts"] = filters["accounts"]
        st.session_state["tx_filter_trade_types"] = filters["trade_types"]
        st.session_state["tx_filter_categories"] = filters["categories"]
        st.session_state["tx_filter_life_tags"] = filters["life_tags"]
        st.session_state["tx_filter_reimbursement_statuses"] = filters["reimbursement_statuses"]
        st.session_state["tx_filter_amount_min"] = (
            "" if filters["amount_min"] is None else str(filters["amount_min"])
        )
        st.session_state["tx_filter_amount_max"] = (
            "" if filters["amount_max"] is None else str(filters["amount_max"])
        )


def _matches_tx_filter_value(value: object, selected_values: list[str]) -> bool:
    """判断普通字段是否命中筛选，支持“空白”选项。"""
    text = _text_value(value)
    return (
        not selected_values
        or text in selected_values
        or (EMPTY_FILTER_OPTION in selected_values and not text)
    )


def _filter_tx_rows(rows: list[dict], filters: dict) -> list[dict]:
    """在当前月份和关键词结果上应用字段筛选。"""
    filters = _normalise_tx_column_filters(filters)
    result = []
    for row in rows:
        if not _matches_tx_filter_value(row["account"], filters["accounts"]):
            continue
        if not _matches_tx_filter_value(row["trade_type"], filters["trade_types"]):
            continue
        if not _matches_tx_filter_value(row["category"], filters["categories"]):
            continue
        if not _matches_tx_filter_value(row["life_tag"], filters["life_tags"]):
            continue
        if not _matches_tx_filter_value(row["reimbursement_status"], filters["reimbursement_statuses"]):
            continue
        amount = abs(float(row["amount"]))
        if filters["amount_min"] is not None and amount < filters["amount_min"]:
            continue
        if filters["amount_max"] is not None and amount > filters["amount_max"]:
            continue
        result.append(row)
    return result


def _tx_filter_summary(filters: dict) -> str:
    """将当前字段筛选压缩为用户可读摘要。"""
    filters = _normalise_tx_column_filters(filters)
    parts = []
    if filters["accounts"]:
        parts.append("账户：" + "、".join(filters["accounts"]))
    if filters["trade_types"]:
        parts.append("收支：" + "、".join(filters["trade_types"]))
    if filters["categories"]:
        parts.append("分类：" + "、".join(filters["categories"]))
    if filters["life_tags"]:
        parts.append("标签：" + "、".join(filters["life_tags"]))
    if filters["reimbursement_statuses"]:
        parts.append("报销状态：" + "、".join(filters["reimbursement_statuses"]))
    if filters["amount_min"] is not None or filters["amount_max"] is not None:
        lower = f"¥{filters['amount_min']:,.2f}" if filters["amount_min"] is not None else "不限"
        upper = f"¥{filters['amount_max']:,.2f}" if filters["amount_max"] is not None else "不限"
        parts.append(f"金额：{lower} 至 {upper}")
    return "；".join(parts) if parts else "未设置字段筛选"


def _tx_filter_options(
    rows: list[dict],
    filters: dict,
    draft: pd.DataFrame | None = None,
) -> dict[str, list[str]]:
    """为表头筛选弹层生成完整选项，已选值即使当前无记录也继续保留。"""
    if draft is not None:
        values = {
            "accounts": set(draft["账户"].map(_text_value)),
            "trade_types": set(draft["收支"].map(_text_value)),
            "categories": set(draft["分类"].map(_text_value)),
            "life_tags": set(draft["标签"].map(_text_value)),
            "reimbursement_statuses": set(draft["报销状态"].map(_text_value)),
        }
    else:
        values = {
            "accounts": {row["account"] for row in rows},
            "trade_types": {row["trade_type"] for row in rows},
            "categories": {row["category"] for row in rows},
            "life_tags": {row["life_tag"] for row in rows},
            "reimbursement_statuses": {row["reimbursement_status"] for row in rows},
        }
    filters = _normalise_tx_column_filters(filters)
    result = {}
    for key, selected in filters.items():
        if key in {"amount_min", "amount_max"}:
            continue
        result[key] = [
            EMPTY_FILTER_OPTION,
            *sorted({
                _text_value(value) for value in values[key] if _text_value(value)
            } | {value for value in selected if value}),
        ]
    return result


def _rows_to_editor_df(rows: list[dict]) -> pd.DataFrame:
    """将数据库流水转换为可编辑表格，金额统一展示为正数。"""
    editor_rows = []
    for row in rows:
        editor_rows.append({
            "记录ID": row["id"],
            "选择": "",
            "时间": pd.to_datetime(row["trade_time"], errors="coerce"),
            "账户": row["account"] or "",
            "收支": row["trade_type"] or "",
            "金额": abs(float(row["amount"])),
            "分类": row["category"] or "",
            "标签": row.get("life_tag", "") or "",
            "报销状态": row.get("reimbursement_status", "") or "",
            "备注": row["remark"] or "",
            "对方": row["counterparty"] or "",
            "支付方式": row["payment_channel"] or "",
        })
    return pd.DataFrame(editor_rows)


def _text_value(value: object) -> str:
    """将表格文本值规范化，避免 Pandas 的 NaN 被保存为字符串 nan。"""
    return "" if pd.isna(value) else str(value).strip()


def _parse_24_hour_datetime(value: object) -> datetime:
    """校验并解析固定的 24 小时制交易时间。"""
    if pd.isna(value):
        raise ValueError("交易时间须使用 24 小时制：YYYY-MM-DD HH:MM:SS")
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).to_pydatetime().replace(microsecond=0)

    text = _text_value(value)
    try:
        parsed = datetime.strptime(text, DATETIME_24H_FORMAT)
    except ValueError as exc:
        raise ValueError("交易时间须使用 24 小时制：YYYY-MM-DD HH:MM:SS") from exc
    if parsed.strftime(DATETIME_24H_FORMAT) != text:
        raise ValueError("交易时间须使用 24 小时制：YYYY-MM-DD HH:MM:SS")
    return parsed


def _manual_trade_time(entry_date: date, value: object) -> str:
    """将手动记账的可选时间合成为固定 24 小时制交易时间。"""
    text = _text_value(value)
    if not text:
        return datetime.combine(entry_date, datetime.min.time()).strftime(DATETIME_24H_FORMAT)
    for time_format in ("%H:%M:%S", "%H:%M"):
        try:
            parsed_time = datetime.strptime(text, time_format).time()
            return datetime.combine(entry_date, parsed_time).strftime(DATETIME_24H_FORMAT)
        except ValueError:
            continue
    raise ValueError("时间须使用 24 小时制：HH:MM 或 HH:MM:SS")


def _editor_row_to_db(row: pd.Series) -> dict:
    """校验并转换一行编辑器数据为数据库字段。"""
    parsed_time = _parse_24_hour_datetime(row["时间"])

    account = _text_value(row["账户"])
    trade_type = _text_value(row["收支"])
    if not account:
        raise ValueError("账户不能为空")
    if trade_type not in TRADE_TYPES:
        raise ValueError("收支必须为支出、退款或收入")

    try:
        amount = float(row["金额"])
    except (TypeError, ValueError) as exc:
        raise ValueError("金额必须为数字") from exc
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("金额必须大于 0")
    amount = db.round_amount(amount)
    if amount <= 0:
        raise ValueError("金额保留两位小数后必须大于 0")

    category = _text_value(row["分类"])
    life_tag = _text_value(row.get("标签", ""))
    reimbursement_status = _text_value(row.get("报销状态", ""))
    if category == PUBLIC_EXPENSE_CATEGORY and trade_type != "支出":
        raise ValueError("公费垫付只能归入支出")
    if category == REIMBURSEMENT_CATEGORY and trade_type != "收入":
        raise ValueError("垫付报销只能归入收入")
    allowed_statuses = sr.status_options(trade_type, category, STATUS_RULES)
    if not allowed_statuses:
        reimbursement_status = ""
    elif reimbursement_status and reimbursement_status not in allowed_statuses:
        reimbursement_status = sr.default_status(trade_type, category, STATUS_RULES)
    if _tag_is_locked(category):
        life_tag = ""
    else:
        allowed_tags = _tag_options_for_trade_type(trade_type)
        if life_tag not in ("", *allowed_tags):
            raise ValueError(f"标签必须为空或有效的{trade_type}标签")
        life_tag = sr.normalise_life_tag(
            trade_type, category, life_tag, EXPENSE_TAGS, INCOME_TAGS, STATUS_RULES
        )



    return {
        "id": _text_value(row["记录ID"]),
        "trade_time": parsed_time.strftime(DATETIME_24H_FORMAT),
        "account": account,
        "trade_type": trade_type,
        "amount": amount if trade_type in ("收入", "退款") else -amount,
        "category": category,
        "life_tag": life_tag,
        "reimbursement_status": reimbursement_status,
        "remark": _text_value(row["备注"]),
        "counterparty": _text_value(row["对方"]),
        "payment_channel": _text_value(row["支付方式"]),
    }


def _row_signature(row: pd.Series) -> tuple:
    """用于比较编辑前后业务字段；选择框不计入未保存修改。"""
    try:
        values = _editor_row_to_db(row)
        return tuple(values[column] for column in (
            "trade_time", "account", "trade_type", "amount", "category", "life_tag",
            "reimbursement_status", "remark", "counterparty", "payment_channel",
        ))
    except ValueError:
        # 无效输入也应视作未保存修改，以便用户能收到切换提示并修正它。
        parsed_time = pd.to_datetime(row.get("时间"), errors="coerce")
        time_value = "" if pd.isna(parsed_time) else parsed_time.strftime("%Y-%m-%d %H:%M:%S")
        return (
            time_value,
            _text_value(row.get("账户", "")),
            _text_value(row.get("收支", "")),
            _text_value(row.get("金额", "")),
            _text_value(row.get("分类", "")),
            _text_value(row.get("标签", "")),
            _text_value(row.get("报销状态", "")),
            _text_value(row.get("备注", "")),
            _text_value(row.get("对方", "")),
            _text_value(row.get("支付方式", "")),
        )


def _get_changed_editor_rows(editor_df: pd.DataFrame) -> list[pd.Series]:
    """返回相对当前数据库快照发生业务变化的行。"""
    baseline = st.session_state.get("tx_baseline")
    if baseline is None:
        return []

    baseline_by_id = {
        _text_value(row["记录ID"]): row
        for _, row in baseline.iterrows()
    }
    changed = []
    for _, row in editor_df.iterrows():
        original = baseline_by_id.get(_text_value(row["记录ID"]))
        if original is None or _row_signature(row) != _row_signature(original):
            changed.append(row)
    return changed


def _save_editor_changes() -> tuple[bool, str]:
    """校验并保存当前页全部表格改动。"""
    editor_df = st.session_state.get("tx_editor_current")
    if editor_df is None:
        return True, "没有需要保存的修改。"

    changed_rows = _get_changed_editor_rows(editor_df)
    if not changed_rows:
        return True, "没有需要保存的修改。"

    updates = []
    for row_number, row in enumerate(changed_rows, start=1):
        try:
            updates.append(_editor_row_to_db(row))
        except ValueError as exc:
            return False, f"第 {row_number} 条修改无效：{exc}"

    updated = 0
    try:
        for values in updates:
            if db.update_transaction(
                values["id"],
                trade_time=values["trade_time"],
                account=values["account"],
                trade_type=values["trade_type"],
                amount=values["amount"],
                category=values["category"],
                life_tag=values["life_tag"],
                reimbursement_status=values["reimbursement_status"],
                remark=values["remark"],
                counterparty=values["counterparty"],
                payment_channel=values["payment_channel"],
            ):
                updated += 1
    except Exception as exc:
        return False, f"保存失败：{exc}"

    _reset_tx_editor()
    return True, f"已保存 {updated} 条修改。"


def _editor_df_to_component_rows(editor_df: pd.DataFrame) -> list[dict]:
    """将 DataFrame 转为可安全传给本地组件的 JSON 行数据。"""
    component_df = editor_df.copy(deep=True)
    component_df["时间"] = component_df["时间"].map(
        lambda value: "" if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    )
    return component_df.where(pd.notna(component_df), "").to_dict(orient="records")


def _apply_tx_pending_action(action: dict) -> None:
    """执行此前因未保存提示而暂缓的页面或筛选切换。"""
    _reset_tx_editor()
    st.session_state["tx_pending_action"] = None
    if action["kind"] == "page":
        st.session_state["current_page"] = action["page"]
    else:
        context = action["context"]
        st.session_state["tx_month"] = context["month"]
        st.session_state["tx_year"] = context["month"][:4]
        st.session_state["tx_search"] = context["keyword"]
        st.session_state["tx_search_active"] = _tx_global_search_active(context["keyword"])
        _set_tx_column_filters(context.get("column_filters", _empty_tx_column_filters()))
        st.session_state["tx_active_context"] = None


def _continue_tx_editing() -> None:
    st.session_state["tx_pending_action"] = None
    st.session_state["tx_dialog_error"] = None
    _set_tx_column_filters(st.session_state.get("tx_column_filters", _empty_tx_column_filters()))


def _discard_tx_pending_action() -> None:
    action = st.session_state.get("tx_pending_action")
    if action:
        _apply_tx_pending_action(action)


def _save_tx_pending_action() -> None:
    action = st.session_state.get("tx_pending_action")
    if not action:
        return
    ok, message = _save_editor_changes()
    if ok:
        _apply_tx_pending_action(action)
    else:
        st.session_state["tx_dialog_error"] = message


@st.dialog("未保存的修改")
def _render_unsaved_changes_dialog() -> None:
    """确认是否保存或放弃切换前的表格改动。"""
    action = st.session_state.get("tx_pending_action")
    if not action:
        return

    st.warning("当前流水列表存在未保存的修改。")
    st.caption("你可以继续编辑、放弃修改后切换，或保存后再切换。")
    if st.session_state.get("tx_dialog_error"):
        st.error(st.session_state["tx_dialog_error"])
    col1, col2, col3 = st.columns(3)
    with col1:
        st.button("继续编辑", use_container_width=True, on_click=_continue_tx_editing)
    with col2:
        st.button("放弃修改并切换", type="secondary", use_container_width=True,
                  on_click=_discard_tx_pending_action)
    with col3:
        st.button("保存后切换", type="primary", use_container_width=True,
                  on_click=_save_tx_pending_action)


def _request_tx_context_change(requested_context: dict) -> None:
    """安全地请求列表条件切换；脏编辑时转为确认动作。"""
    active_context = st.session_state.get("tx_active_context")
    if active_context is not None:
        active_context = {
            **active_context,
            "search_active": _tx_global_search_active(active_context.get("keyword", "")),
        }
    requested_context["column_filters"] = _normalise_tx_column_filters(
        requested_context.get("column_filters")
    )
    # 搜索范围只由关键词决定，禁止出现“搜索框有内容但仅查询当前月份”的冲突状态。
    requested_context["search_active"] = _tx_global_search_active(
        requested_context.get("keyword", "")
    )
    if not active_context:
        st.session_state["tx_month"] = requested_context["month"]
        st.session_state["tx_year"] = requested_context["month"][:4]
        st.session_state["tx_search"] = requested_context["keyword"]
        st.session_state["tx_search_active"] = requested_context["search_active"]
        _set_tx_column_filters(requested_context["column_filters"])
        return

    if requested_context == active_context:
        _set_tx_column_filters(requested_context["column_filters"])
        if st.session_state.get("tx_edit_mode", False):
            st.session_state["tx_edit_version"] = st.session_state.get("tx_edit_version", 0) + 1
        return

    if st.session_state.get("tx_edit_mode", False):
        st.session_state["tx_month"] = requested_context["month"]
        st.session_state["tx_year"] = requested_context["month"][:4]
        st.session_state["tx_search"] = requested_context["keyword"]
        st.session_state["tx_search_active"] = requested_context["search_active"]
        _set_tx_column_filters(requested_context["column_filters"])
        st.session_state["tx_active_context"] = requested_context
        st.session_state["tx_edit_context"] = requested_context
        st.session_state["tx_edit_view_mode"] = "search" if requested_context["search_active"] else "month"
        st.session_state["tx_edit_search_rows"] = None
        st.session_state["tx_edit_search_ids"] = []
        st.session_state["tx_edit_version"] = st.session_state.get("tx_edit_version", 0) + 1
        return

    if st.session_state.get("tx_dirty", False):
        st.session_state["tx_month"] = active_context["month"]
        st.session_state["tx_year"] = active_context["month"][:4]
        st.session_state["tx_search"] = active_context["keyword"]
        st.session_state["tx_search_active"] = active_context["search_active"]
        _set_tx_column_filters(active_context.get("column_filters", _empty_tx_column_filters()))
        st.session_state["tx_pending_action"] = {
            "kind": "filters", "context": requested_context,
        }
    else:
        st.session_state["tx_month"] = requested_context["month"]
        st.session_state["tx_year"] = requested_context["month"][:4]
        st.session_state["tx_search"] = requested_context["keyword"]
        st.session_state["tx_search_active"] = requested_context["search_active"]
        _set_tx_column_filters(requested_context["column_filters"])
        _reset_tx_editor()
        st.session_state["tx_active_context"] = None


def _request_tx_filter_change() -> None:
    """关键词变化时，拦截可能丢失的未保存编辑。"""
    st.session_state["tx_search_active"] = _tx_global_search_active(st.session_state["tx_search"])
    _request_tx_context_change({
        "month": st.session_state["tx_month"],
        "keyword": st.session_state["tx_search"],
        "search_active": st.session_state["tx_search_active"],
        "column_filters": st.session_state.get("tx_column_filters", _empty_tx_column_filters()),
    })


def _request_tx_month_change(target_month: str) -> None:
    """月份按钮或年份下拉变化时，安全地切换完整 YYYY-MM 筛选值。"""
    if st.session_state.get("tx_edit_mode", False):
        context = {
            "month": target_month,
            "keyword": "",
            "search_active": False,
            "column_filters": _empty_tx_column_filters(),
        }
        st.session_state["tx_filter_error"] = None
        st.session_state["tx_month"] = target_month
        st.session_state["tx_year"] = target_month[:4]
        st.session_state["tx_search"] = ""
        st.session_state["tx_search_active"] = False
        _set_tx_column_filters(context["column_filters"])
        st.session_state["tx_active_context"] = context
        st.session_state["tx_edit_context"] = context
        st.session_state["tx_edit_view_mode"] = "month"
        st.session_state["tx_edit_search_rows"] = None
        st.session_state["tx_edit_search_ids"] = []
        st.session_state["tx_edit_version"] = st.session_state.get("tx_edit_version", 0) + 1
        return
    _request_tx_context_change({
        "month": target_month,
        # 月份视图与全局搜索互斥；清空关键词可避免搜索框显示内容却仅查询当月。
        "keyword": "",
        "search_active": False,
        # 切换月份时，字段筛选自动清空。
        "column_filters": _empty_tx_column_filters(),
    })


def _request_tx_column_filters(filters: dict) -> bool:
    """校验并应用表头筛选，复用未保存修改确认流程。"""
    def parse_amount(value: object, label: str) -> float | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            amount = float(text)
        except ValueError as exc:
            raise ValueError(f"{label}必须是数字。") from exc
        if amount < 0:
            raise ValueError(f"{label}不能小于 0。")
        return amount

    try:
        amount_min = parse_amount(filters.get("amount_min"), "最低金额")
        amount_max = parse_amount(filters.get("amount_max"), "最高金额")
    except ValueError as exc:
        st.session_state["tx_filter_error"] = str(exc)
        return False
    target_filters = _normalise_tx_column_filters({
        "accounts": filters.get("accounts", []),
        "trade_types": filters.get("trade_types", []),
        "categories": filters.get("categories", []),
        "life_tags": filters.get("life_tags", []),
        "reimbursement_statuses": filters.get("reimbursement_statuses", []),
        "amount_min": amount_min,
        "amount_max": amount_max,
    })
    lower, upper = target_filters["amount_min"], target_filters["amount_max"]
    if lower is not None and upper is not None and lower > upper:
        st.session_state["tx_filter_error"] = "最低金额不能大于最高金额。"
        return False
    st.session_state["tx_filter_error"] = None
    current_filters = _normalise_tx_column_filters(
        st.session_state.get("tx_column_filters", _empty_tx_column_filters())
    )
    if target_filters == current_filters:
        return False
    keyword = st.session_state.get("tx_search", "")
    _request_tx_context_change({
        "month": st.session_state["tx_month"],
        "keyword": keyword,
        "search_active": _tx_global_search_active(keyword),
        "column_filters": target_filters,
    })
    return True


def _request_tx_column_filter_apply() -> None:
    """兼容旧会话状态中的筛选表单回调。"""
    _request_tx_column_filters({
        "accounts": st.session_state.get("tx_filter_accounts", []),
        "trade_types": st.session_state.get("tx_filter_trade_types", []),
        "categories": st.session_state.get("tx_filter_categories", []),
        "life_tags": st.session_state.get("tx_filter_life_tags", []),
        "reimbursement_statuses": st.session_state.get("tx_filter_reimbursement_statuses", []),
        "amount_min": st.session_state.get("tx_filter_amount_min"),
        "amount_max": st.session_state.get("tx_filter_amount_max"),
    })


def _request_tx_column_filter_clear() -> None:
    """清除已应用及草稿中的字段筛选。"""
    st.session_state["tx_filter_error"] = None
    keyword = st.session_state.get("tx_search", "")
    _request_tx_context_change({
        "month": st.session_state["tx_month"],
        "keyword": keyword,
        "search_active": _tx_global_search_active(keyword),
        "column_filters": _empty_tx_column_filters(),
    })


def _cancel_tx_filters() -> None:
    """清空当前字段筛选，筛选控件继续常驻显示。"""
    _request_tx_column_filter_clear()


def _request_tx_year_change() -> None:
    """年份变化后默认切换到该年份最新一个有流水的月份。"""
    selected_year = st.session_state["tx_year"]
    available_months = st.session_state.get("tx_available_months", [])
    year_months = [month for month in available_months if month.startswith(f"{selected_year}-")]
    if year_months:
        _request_tx_month_change(max(year_months))


def _request_dashboard_month_change(target_month: str) -> None:
    """仪表盘月份按钮回调。"""
    st.session_state["dashboard_month"] = target_month
    st.session_state["dashboard_year"] = target_month[:4]


def _request_dashboard_year_change() -> None:
    """仪表盘年份变化后默认定位到该年最新有流水的月份。"""
    selected_year = st.session_state["dashboard_year"]
    available_months = st.session_state.get("dashboard_available_months", [])
    year_months = [month for month in available_months if month.startswith(f"{selected_year}-")]
    if year_months:
        _request_dashboard_month_change(max(year_months))


def _request_page_change(page_name: str) -> None:
    """侧边栏导航：离开流水列表前先确认未保存的表格编辑。"""
    if (st.session_state.get("current_page") == "流水列表"
            and st.session_state.get("tx_edit_mode", False)):
        st.session_state["tx_notice"] = "请先保存或取消当前整表修改。"
        return
    if (st.session_state.get("current_page") == "流水列表"
            and page_name != "流水列表"
            and st.session_state.get("tx_dirty", False)):
        st.session_state["tx_pending_action"] = {"kind": "page", "page": page_name}
        return
    if (st.session_state.get("current_page") == "选项管理"
            and page_name != "选项管理"
            and st.session_state.get("option_dirty", False)):
        st.session_state["option_pending_action"] = {"kind": "page", "page": page_name}
        return
    st.session_state["current_page"] = page_name


def _dismiss_single_edit_dialog() -> None:
    """关闭单条修改窗口时清除暂存，避免后续重跑重新打开。"""
    st.session_state["tx_single_edit_id"] = None
    st.session_state["tx_single_edit_row"] = None
    st.session_state["tx_editor_version"] = st.session_state.get("tx_editor_version", 0) + 1


def _refresh_tx_bulk_loaded_months() -> None:
    """将数据库中新出现的流水合并到当前编辑草稿。"""
    for month in st.session_state.get("tx_edit_loaded_months", []):
        rows, _ = db.query_transactions(month, page_size=None)
        if not rows:
            continue
        database_df = _rows_to_editor_df(rows)
        baseline = st.session_state.get("tx_edit_baseline")
        draft = st.session_state.get("merged_df")
        if baseline is None or draft is None:
            return
        baseline_ids = set(baseline["记录ID"].map(_text_value))
        new_baseline_rows = database_df[
            ~database_df["记录ID"].map(_text_value).isin(baseline_ids)
        ]
        if not new_baseline_rows.empty:
            st.session_state["tx_edit_baseline"] = pd.concat(
                [baseline, new_baseline_rows], ignore_index=True
            )
        draft = st.session_state.get("merged_df")
        draft_ids = set(draft["记录ID"].map(_text_value))
        new_draft_rows = database_df[
            ~database_df["记录ID"].map(_text_value).isin(draft_ids)
        ]
        if not new_draft_rows.empty:
            st.session_state["merged_df"] = pd.concat(
                [draft, new_draft_rows], ignore_index=True
            )


def _create_transaction_from_component(row: dict) -> tuple[bool, str]:
    """校验本地弹窗回传的数据并创建一条流水。"""
    editor_row = pd.Series({"记录ID": "", "选择": "", **row})
    try:
        _validate_tx_bulk_category(editor_row, None)
        values = _editor_row_to_db(editor_row)
        inserted = db.create_transaction(
            trade_time=values["trade_time"], account=values["account"],
            trade_type=values["trade_type"], amount=values["amount"],
            category=values["category"], life_tag=values["life_tag"],
            reimbursement_status=values["reimbursement_status"],
            remark=values["remark"], counterparty=values["counterparty"],
            payment_channel=values["payment_channel"],
        )
    except Exception as exc:
        return False, f"保存失败：{exc}"
    return (True, "记录已保存。") if inserted else (False, "保存失败，请重试。")


@st.dialog("修改流水", width="large", on_dismiss=_dismiss_single_edit_dialog)
def _render_single_edit_dialog(row: pd.Series) -> None:
    """渲染单条流水的预填修改表单。"""
    parsed_time = pd.to_datetime(row["时间"], errors="coerce")
    default_time = parsed_time.to_pydatetime() if not pd.isna(parsed_time) else datetime.now()
    original_trade_type = _text_value(row["收支"])
    original_category = _text_value(row["分类"])
    category_options = _categories_for_trade_type(original_trade_type, original_category)
    current_status = _text_value(row.get("报销状态", ""))
    status_options = sr.status_options(original_trade_type, original_category, STATUS_RULES)
    if not status_options:
        status_options = [""]
    elif current_status not in status_options:
        # 兼容历史空状态；未保存时不自动改写已有流水。
        status_options = [current_status, *status_options]

    with st.form("single_transaction_edit_form"):
        row1_col1, row1_col2, row1_col3 = st.columns(3)
        with row1_col1:
            trade_time_text = st.text_input(
                "交易时间（24小时制）",
                value=default_time.strftime(DATETIME_24H_FORMAT),
                help="格式：YYYY-MM-DD HH:MM:SS",
            )
        with row1_col2:
            account_options = list(dict.fromkeys([*ACCOUNTS, _text_value(row["账户"])]))
            account = st.selectbox(
                "账户", account_options,
                index=account_options.index(_text_value(row["账户"])),
            )
        with row1_col3:
            trade_type = st.selectbox("收支类型", TRADE_TYPES,
                                       index=TRADE_TYPES.index(_text_value(row["收支"])))

        row2_col1, row2_col2, row2_col3 = st.columns(3)
        with row2_col1:
            amount = st.number_input("金额", min_value=0.01,
                                     value=max(abs(float(row["金额"])), 0.01),
                                     step=0.01, format="%.2f")
        with row2_col2:
            category = st.selectbox("分类", category_options,
                                    index=category_options.index(original_category))
        with row2_col3:
            current_life_tag = sr.normalise_life_tag(
                original_trade_type, original_category,
                _text_value(row.get("标签", "")),
                EXPENSE_TAGS, INCOME_TAGS, STATUS_RULES,
            )
            tag_options = ["", *_tag_options_for_category(original_trade_type, original_category)]
            life_tag = st.selectbox(
                "标签", tag_options,
                index=tag_options.index(current_life_tag) if current_life_tag in tag_options else 0,
                disabled=_tag_is_locked(original_category),
            )

        row3_col1, row3_col2, row3_col3 = st.columns(3)
        with row3_col1:
            reimbursement_status = st.selectbox(
                "报销状态", status_options,
                index=status_options.index(current_status),
                disabled=status_options == [""],
            )
        with row3_col2:
            counterparty = st.text_input("交易对方", value=_text_value(row["对方"]))
        with row3_col3:
            payment_channel = st.text_input("支付方式", value=_text_value(row["支付方式"]))

        remark = st.text_input("备注", value=_text_value(row["备注"]))

        save_col, cancel_col = st.columns(2)
        with save_col:
            submitted = st.form_submit_button("保存修改", type="primary", use_container_width=True)
        with cancel_col:
            cancelled = st.form_submit_button("取消", use_container_width=True)

    if cancelled:
        st.session_state["tx_single_edit_id"] = None
        st.session_state["tx_single_edit_row"] = None
        st.session_state["tx_editor_version"] = st.session_state.get("tx_editor_version", 0) + 1
        st.rerun(scope="app")
    if submitted:
        try:
            trade_time = _parse_24_hour_datetime(trade_time_text)
        except ValueError as exc:
            st.error(str(exc))
            return
        if trade_type != original_trade_type and category not in _categories_for_trade_type(trade_type):
            category = ""
        if trade_type != original_trade_type or category != original_category:
            reimbursement_status = sr.normalise_new_status(
                trade_type, category, reimbursement_status, STATUS_RULES
            )
        else:
            allowed_statuses = sr.status_options(trade_type, category, STATUS_RULES)
            if not allowed_statuses:
                reimbursement_status = ""
            elif reimbursement_status and reimbursement_status not in allowed_statuses:
                reimbursement_status = sr.default_status(trade_type, category, STATUS_RULES)
        if trade_type != original_trade_type or category != original_category:
            life_tag = sr.default_life_tag(
                trade_type, category, INCOME_CATEGORY_TAGS, EXPENSE_CATEGORY_TAGS, STATUS_RULES
            ) or sr.normalise_life_tag(
                trade_type, category, life_tag, EXPENSE_TAGS, INCOME_TAGS, STATUS_RULES
            )
        else:
            life_tag = sr.normalise_life_tag(trade_type, category, life_tag, EXPENSE_TAGS, INCOME_TAGS, STATUS_RULES)
        values = {
            "id": _text_value(row["记录ID"]),
            "trade_time": trade_time.strftime(DATETIME_24H_FORMAT),
            "account": account,
            "trade_type": trade_type,
            "amount": amount if trade_type in ("收入", "退款") else -amount,
            "category": category.strip(),
            "life_tag": life_tag,
            "reimbursement_status": reimbursement_status,
            "remark": remark.strip(),
            "counterparty": counterparty.strip(),
            "payment_channel": payment_channel.strip(),
        }
        try:
            db.update_transaction(
                values["id"],
                trade_time=values["trade_time"], account=values["account"],
                trade_type=values["trade_type"], amount=values["amount"],
                category=values["category"], life_tag=values["life_tag"],
                reimbursement_status=values["reimbursement_status"],
                remark=values["remark"],
                counterparty=values["counterparty"], payment_channel=values["payment_channel"],
            )
        except Exception as exc:
            st.error(f"保存失败：{exc}")
            return

        _reset_tx_editor()
        st.session_state["tx_notice"] = "流水已修改。"
        st.rerun(scope="app")


def _render_stat_cards(month: str) -> None:
    """渲染本月收支概览卡片。"""
    summary = db.get_month_summary(month)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="stat-card"><div class="label">收入</div><div class="value income">¥{summary["income"]:,.2f}</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="stat-card"><div class="label">支出</div><div class="value expense">¥{summary["expense"]:,.2f}</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        balance = summary["balance"]
        balance_class = "income" if balance >= 0 else "expense"
        st.markdown(
            f'<div class="stat-card"><div class="label">结余</div><div class="value {balance_class}">{_format_money(balance)}</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f'<div class="stat-card"><div class="label">交易笔数</div><div class="value balance">{summary["count"]:,}</div></div>',
            unsafe_allow_html=True,
        )


def _render_reimbursement_kpis(month: str) -> None:
    """展示个人收支、过手资金与报销账户的核心指标。"""
    personal_summary = db.get_month_summary(month)
    pass_through = db.get_pass_through_summary(month)
    reimbursement = db.get_reimbursement_summary()
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("个人支出影响（本月）", f"¥{personal_summary['expense']:,.2f}")
    with c2:
        st.metric("过手转出（本月）", f"¥{pass_through['outgoing']:,.2f}")
    with c3:
        st.metric("过手转入（本月）", f"¥{pass_through['incoming']:,.2f}")
    with c4:
        st.metric("待报销总额", f"¥{reimbursement['pending']:,.2f}")
    with c5:
        st.metric("已收回报销", f"¥{reimbursement['settled']:,.2f}")


def _render_reimbursement_list() -> None:
    """渲染待报销与待转出的两类跟踪清单。"""
    def render_records(records: list[dict], table_key: str, empty_message: str) -> None:
        if not records:
            st.info(empty_message)
            return
        frame = pd.DataFrame(records).rename(columns={
            "trade_time": "时间", "counterparty": "对方", "remark": "备注",
            "amount": "金额", "reimbursement_status": "状态",
        })
        _render_local_table(
            _format_amount_columns(frame), table_key=table_key, height=360
        )

    st.subheader("待报销清单")
    render_records(
        db.get_reimbursement_records(),
        "pending_reimbursement_records",
        "暂无待报销记录。",
    )
    st.subheader("待转出清单")
    render_records(
        db.get_pending_pass_through_income_records(),
        "pending_pass_through_income_records",
        "暂无待转出的过手转入记录。",
    )


def _render_monthly_trend() -> None:
    """月度收支趋势折线图（数据由 SQL 聚合）。"""
    stats = db.get_monthly_stats()
    if not stats:
        st.info("暂无交易数据。")
        return

    df = pd.DataFrame(stats)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=df["month"], y=df["income"], name="收入", mode="lines+markers",
                   line=dict(color="#10b981", width=2), marker=dict(size=6)))
    fig.add_trace(
        go.Scatter(x=df["month"], y=df["expense"], name="支出", mode="lines+markers",
                   line=dict(color="#ef4444", width=2), marker=dict(size=6)))
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        height=350,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None)
    st.subheader("月度收支趋势")
    st.plotly_chart(fig, use_container_width=True)


def _render_yearly_category_table(year: str) -> None:
    """渲染全年各支出分类的月度金额热力表。"""
    stats = db.get_yearly_category_stats(year)
    categories = [category for category in EXPENSE_CATEGORIES
                  if category not in {
                      PUBLIC_EXPENSE_CATEGORY,
                      REIMBURSEMENT_CATEGORY,
                      PASS_THROUGH_EXPENSE_CATEGORY,
                      PASS_THROUGH_INCOME_CATEGORY,
                  }]
    month_columns = list(range(1, 13))

    if stats:
        frame = pd.DataFrame(stats)
        pivot = frame.pivot_table(
            index="category", columns="month", values="total", aggfunc="sum", fill_value=0
        )
    else:
        pivot = pd.DataFrame(index=categories)

    pivot = pivot.reindex(index=categories, columns=month_columns, fill_value=0).fillna(0)
    maximum = float(pivot.to_numpy().max()) if not pivot.empty else 0.0
    colour_map = colormaps["Reds"]
    normalizer = colors.Normalize(vmin=0, vmax=maximum) if maximum > 0 else None
    columns = [
        {"key": "支出类型", "width": 90, "kind": "text"},
        *[
            {"key": f"{month}月", "width": 58, "kind": "money"}
            for month in month_columns
        ],
    ]
    rows = []
    for category in categories:
        row = {"支出类型": category, "__heat_colours": {}}
        for month in month_columns:
            column = f"{month}月"
            amount = float(pivot.at[category, month])
            row[column] = amount
            if amount > 0 and normalizer is not None:
                colour_value = 0.25 + normalizer(amount) * 0.7
                row["__heat_colours"][column] = colors.to_hex(colour_map(colour_value))
        rows.append(row)
    st.subheader(f"{year} 年度分类支出汇总")
    yearly_category_viewer(
        rows=rows,
        columns=columns,
        version=hash((
            year,
            tuple(
                (row["支出类型"], *(row[f"{month}月"] for month in month_columns))
                for row in rows
            ),
        )),
        year=year,
        height=470,
        key=f"yearly_category_viewer_{year}",
    )


def _render_category_pie(month: str) -> None:
    """本月支出分类饼图（数据由 SQL 聚合）。"""
    stats = db.get_monthly_category_stats(month)
    if not stats:
        st.info("本月暂无支出记录。")
        return

    df = pd.DataFrame(stats)
    fig = px.pie(
        df, names="category", values="total", hole=0.45,
        title=f"{month} 支出分类分布",
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=400)
    st.plotly_chart(fig, use_container_width=True)


def _render_tag_pie(month: str, trade_type: str) -> None:
    """渲染本月收入或净支出的标签占比饼图。"""
    if trade_type == "收入":
        stats = db.get_monthly_income_tag_stats(month)
        title = f"{month} 收入标签占比"
        empty_message = "本月暂无收入标签记录。"
    else:
        stats = db.get_monthly_expense_tag_stats(month)
        title = f"{month} 支出标签占比"
        empty_message = "本月暂无支出标签记录。"
    if not stats:
        st.info(empty_message)
        return

    df = pd.DataFrame(stats)
    fig = px.pie(
        df, names="life_tag", values="total", hole=0.45,
        title=title,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=400)
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# 页面：仪表盘
# ══════════════════════════════════════════════════════════════════════════

def page_dashboard() -> None:
    months = db.get_available_months()
    if not months:
        st.info("还没有任何交易记录，先去「导入账单」或「手动记账」添加数据吧。")
        return

    current_month = datetime.now().strftime("%Y-%m")
    if st.session_state.get("dashboard_month") not in months:
        st.session_state["dashboard_month"] = current_month if current_month in months else months[0]
    years = sorted({month[:4] for month in months}, reverse=True)
    if st.session_state.get("dashboard_year") not in years:
        st.session_state["dashboard_year"] = st.session_state["dashboard_month"][:4]
    st.session_state["dashboard_available_months"] = months

    selected_year = st.session_state["dashboard_year"]
    selected_month = st.session_state["dashboard_month"]
    with st.container(key="dashboard_period_toolbar"):
        period_columns = st.columns(
            [1.5] + [0.72] * 12,
            gap="small",
            vertical_alignment="center",
        )
        with period_columns[0]:
            st.selectbox(
                " ", years,
                key="dashboard_year",
                format_func=lambda year: f"{year}年",
                on_change=_request_dashboard_year_change,
                label_visibility="collapsed",
            )
        for month_number, column in enumerate(period_columns[1:], start=1):
            target_month = f"{selected_year}-{month_number:02d}"
            with column:
                st.button(
                    f"{month_number}月",
                    key=f"dashboard_month_button_{selected_year}_{month_number}",
                    type="primary" if target_month == selected_month else "secondary",
                    disabled=target_month not in months,
                    use_container_width=True,
                    on_click=_request_dashboard_month_change,
                    args=(target_month,),
                )

    st.divider()
    _render_reimbursement_kpis(selected_month)

    st.divider()
    _render_stat_cards(selected_month)

    st.divider()
    _render_yearly_category_table(selected_year)

    st.divider()
    _render_monthly_trend()

    col1, col2, col3 = st.columns(3)
    with col1:
        _render_category_pie(selected_month)
    with col2:
        _render_tag_pie(selected_month, "收入")
    with col3:
        _render_tag_pie(selected_month, "支出")

    st.divider()
    _render_reimbursement_list()


# ══════════════════════════════════════════════════════════════════════════
# 页面：流水列表
# ══════════════════════════════════════════════════════════════════════════

def _get_tx_bulk_changes(editor_df: pd.DataFrame, baseline: pd.DataFrame) -> list[pd.Series]:
    """返回整表编辑草稿中相对基线真正发生变化的行。"""
    baseline_by_id = {
        _text_value(row["记录ID"]): row for _, row in baseline.iterrows()
    }
    changed_rows = []
    for _, row in editor_df.iterrows():
        original = baseline_by_id.get(_text_value(row["记录ID"]))
        # 新增或复制的草稿行由 _save_tx_bulk_edits 的 new_rows 分支处理。
        if original is None:
            continue
        if _row_signature(row) != _row_signature(original):
            changed_rows.append(row)
    return changed_rows


def _validate_tx_bulk_category(row: pd.Series, original: pd.Series | None) -> None:
    """校验整表编辑时收支与分类的兼容性，并保留未修改的历史分类。"""
    trade_type = _text_value(row["收支"])
    category = _text_value(row["分类"])
    allowed = EXPENSE_CATEGORIES if sr.uses_expense_categories(trade_type) else INCOME_CATEGORIES
    original_trade_type = _text_value(original["收支"]) if original is not None else ""
    original_category = _text_value(original["分类"]) if original is not None else ""

    if category in EXPENSE_CATEGORIES + INCOME_CATEGORIES and category not in allowed:
        raise ValueError(f"“{category}”不属于{trade_type}分类")
    if trade_type != original_trade_type and category and category not in allowed:
        raise ValueError(f"收支改为{trade_type}后，请重新选择兼容的分类")
    if category == PUBLIC_EXPENSE_CATEGORY and trade_type != "支出":
        raise ValueError("公费垫付只能归入支出")
    if category == REIMBURSEMENT_CATEGORY and trade_type != "收入":
        raise ValueError("垫付报销只能归入收入")
    # 原分类未变时允许保留历史导入分类；其他情况由以上规则校验。
    _ = original_category


def _save_tx_bulk_edits(
    editor_df: pd.DataFrame,
    baseline: pd.DataFrame,
    deleted_ids: list[str],
) -> tuple[bool, str]:
    """校验并一次保存整表编辑模式中的所有有效变更。"""
    baseline_ids = {_text_value(row["记录ID"]) for _, row in baseline.iterrows()}
    changed_rows = [
        row for row in _get_tx_bulk_changes(editor_df, baseline)
        if _text_value(row["记录ID"]) in baseline_ids
    ]
    new_rows = [
        row for _, row in editor_df.iterrows()
        if _text_value(row["记录ID"]) not in baseline_ids
    ]
    deleted_ids = list(dict.fromkeys(
        transaction_id for transaction_id in deleted_ids if transaction_id in baseline_ids
    ))
    if not changed_rows and not new_rows and not deleted_ids:
        return True, "没有需要保存的修改。"

    baseline_by_id = {
        _text_value(row["记录ID"]): row for _, row in baseline.iterrows()
    }
    updates = []
    for row_number, row in enumerate([*changed_rows, *new_rows], start=1):
        try:
            _validate_tx_bulk_category(
                row, baseline_by_id.get(_text_value(row["记录ID"]))
            )
            updates.append(_editor_row_to_db(row))
        except ValueError as exc:
            return False, f"第 {row_number} 条修改无效：{exc}"

    updated = 0
    inserted = 0
    deleted = 0
    try:
        for values in updates[:len(changed_rows)]:
            if db.update_transaction(
                values["id"], trade_time=values["trade_time"],
                account=values["account"], trade_type=values["trade_type"],
                amount=values["amount"], category=values["category"],
                life_tag=values["life_tag"],
                reimbursement_status=values["reimbursement_status"],
                remark=values["remark"], counterparty=values["counterparty"],
                payment_channel=values["payment_channel"],
            ):
                updated += 1
        for values in updates[len(changed_rows):]:
            if db.create_transaction(
                trade_time=values["trade_time"], account=values["account"],
                trade_type=values["trade_type"], amount=values["amount"],
                category=values["category"], life_tag=values["life_tag"],
                reimbursement_status=values["reimbursement_status"],
                remark=values["remark"], counterparty=values["counterparty"],
                payment_channel=values["payment_channel"],
            ):
                inserted += 1
        deleted = db.delete_transactions(deleted_ids)
    except Exception as exc:
        return False, f"保存失败：{exc}"
    message_parts = []
    if updated:
        message_parts.append(f"已保存 {updated} 条修改")
    if inserted:
        message_parts.append(f"已复制 {inserted} 条流水")
    if deleted:
        message_parts.append(f"已删除 {deleted} 条流水")
    return True, "，".join(message_parts) + "。"


def _begin_tx_bulk_edit(database_df: pd.DataFrame, context: dict) -> None:
    """创建整表编辑会话的首个月份快照。"""
    st.session_state["tx_edit_mode"] = True
    st.session_state["tx_edit_baseline"] = database_df.copy(deep=True)
    st.session_state["merged_df"] = database_df.copy(deep=True)
    st.session_state["tx_edit_context"] = context
    st.session_state["tx_selected_ids"] = []
    st.session_state["tx_edit_deleted_ids"] = []
    st.session_state["tx_edit_loaded_months"] = [context["month"]]
    st.session_state["tx_edit_session_id"] = str(uuid.uuid4())
    st.session_state["tx_edit_instance_version"] = 0
    st.session_state["tx_dirty"] = True
    st.session_state["tx_edit_error"] = None
    st.session_state["tx_edit_view_mode"] = "search" if context.get("search_active") else "month"
    st.session_state["tx_edit_search_rows"] = None
    st.session_state["tx_edit_search_ids"] = []
    st.session_state["tx_edit_version"] = st.session_state.get("tx_edit_version", 0) + 1


def _extend_tx_bulk_edit_month(database_df: pd.DataFrame, month: str) -> None:
    """将首次访问月份的原始流水追加到当前编辑会话。"""
    loaded_months = set(st.session_state.get("tx_edit_loaded_months", []))
    if month in loaded_months:
        return

    baseline = st.session_state.get("tx_edit_baseline")
    draft = st.session_state.get("merged_df")
    if baseline is None or draft is None:
        return

    incoming = database_df.copy(deep=True)
    if not incoming.empty:
        baseline_ids = set(baseline["记录ID"].map(_text_value))
        baseline_additions = incoming[~incoming["记录ID"].map(_text_value).isin(baseline_ids)]
        if not baseline_additions.empty:
            baseline = pd.concat([baseline, baseline_additions], ignore_index=True)

        draft_ids = set(draft["记录ID"].map(_text_value))
        draft_additions = incoming[~incoming["记录ID"].map(_text_value).isin(draft_ids)]
        if not draft_additions.empty:
            draft = pd.concat([draft, draft_additions], ignore_index=True)

    loaded_months.add(month)
    st.session_state["tx_edit_baseline"] = baseline.copy(deep=True)
    st.session_state["merged_df"] = draft.copy(deep=True)
    st.session_state["tx_edit_loaded_months"] = sorted(loaded_months)


def _discard_tx_bulk_edit() -> None:
    """放弃整表编辑草稿并恢复只读状态。"""
    _reset_tx_editor()
    st.session_state["tx_notice"] = "已放弃未保存的修改。"


def _draft_keyword_rows(draft: pd.DataFrame, keyword: str) -> pd.DataFrame:
    if draft is None or draft.empty or not keyword:
        return draft.copy(deep=True) if draft is not None else pd.DataFrame()
    mask = draft.apply(
        lambda row: db.matches_keyword(row.get("备注", ""), row.get("分类", ""), row.get("对方", ""), keyword),
        axis=1,
    )
    return draft.loc[mask].copy(deep=True)


def _ensure_tx_bulk_search_scope(keyword: str) -> pd.DataFrame:
    """加载搜索命中的月份，并从累计草稿重新计算可见结果。"""
    if not keyword:
        st.session_state["tx_edit_search_rows"] = None
        st.session_state["tx_edit_search_ids"] = []
        st.session_state["tx_edit_view_mode"] = "month"
        return pd.DataFrame()
    search_rows, _ = db.query_transactions(None, page_size=None, keyword=keyword)
    months = sorted({str(row.get("trade_time", ""))[:7] for row in search_rows if str(row.get("trade_time", ""))[:7]})
    for month in months:
        rows, _ = db.query_transactions(month, page_size=None)
        if rows:
            _extend_tx_bulk_edit_month(_rows_to_editor_df(rows), month)
    draft = st.session_state.get("merged_df")
    result = _draft_keyword_rows(draft, keyword) if draft is not None else pd.DataFrame()
    st.session_state["tx_edit_search_rows"] = result.copy(deep=True)
    st.session_state["tx_edit_search_ids"] = [_text_value(value) for value in result.get("记录ID", [])]
    st.session_state["tx_edit_view_mode"] = "search"
    return result


def _render_tx_bulk_edit_form(
    database_df: pd.DataFrame,
    filter_options: dict[str, list[str]],
    *,
    view_mode: str = "month",
    visible_ids: list[str] | None = None,
) -> None:
    """渲染本地单击编辑器；仅保存/取消操作才会回传 Streamlit。"""
    baseline = st.session_state.get("tx_edit_baseline")
    draft = st.session_state.get("merged_df")
    if baseline is None or draft is None:
        _discard_tx_bulk_edit()
        st.rerun()

    # 会话状态恢复 DataFrame 时，时间列可能被序列化为字符串。
    draft = draft.copy(deep=True)
    draft["时间"] = pd.to_datetime(draft["时间"], errors="coerce")
    st.session_state["merged_df"] = draft.copy(deep=True)

    trade_type_options = sorted(set(TRADE_TYPES) | set(draft["收支"].map(_text_value)))
    account_options = sorted(set(ACCOUNTS) | set(draft["账户"].map(_text_value)))
    version = st.session_state.get("tx_edit_version", 0)

    if st.session_state.get("tx_edit_error"):
        st.error(st.session_state["tx_edit_error"])

    result = transaction_editor(
        rows=_editor_df_to_component_rows(draft),
        version=version,
        accounts=account_options,
        trade_types=trade_type_options,
        expense_categories=EXPENSE_CATEGORIES,
        income_categories=INCOME_CATEGORIES,
        status_rules=STATUS_RULES,
        expense_tags=EXPENSE_TAGS,
        income_tags=INCOME_TAGS,
        income_category_tags=INCOME_CATEGORY_TAGS,
        expense_category_tags=EXPENSE_CATEGORY_TAGS,
        deleted_ids=st.session_state.get("tx_edit_deleted_ids", []),
        draft_ids=[_text_value(value) for value in draft["记录ID"]],
        draft_session_id=st.session_state.get("tx_edit_session_id", ""),
        visible_month=st.session_state.get("tx_month", ""),
        filters=st.session_state.get("tx_column_filters", _empty_tx_column_filters()),
        filter_options=filter_options,
        filter_reset_key=(
            f"{view_mode}:{st.session_state.get('tx_month', '')}:"
            f"{st.session_state.get('tx_search_active', False)}:"
            f"{st.session_state.get('tx_search', '')}"
        ),
        view_mode=view_mode,
        visible_ids=visible_ids or [],
        search_keyword=(
            st.session_state.get("tx_search", "")
            if st.session_state.get("tx_search_active", False) else ""
        ),
        # 编辑工具栏 52px + 表头 38px + 10 行（每行 36px）。
        height=450,
        key=(
            f"tx_bulk_editor_{st.session_state.get('tx_edit_session_id', '')}_"
            f"{st.session_state.get('tx_edit_instance_version', 0)}"
        ),
    )
    if not isinstance(result, dict) or result.get("action") not in {"save", "cancel", "manual_entry"}:
        return

    required_columns = ["记录ID", "选择", *TX_EDITOR_COLUMNS]
    edited_df = pd.DataFrame(result.get("rows", []), columns=required_columns)
    if set(required_columns) - set(edited_df.columns):
        st.session_state["tx_edit_error"] = "编辑器返回的数据不完整，请继续编辑后再次保存。"
        st.session_state["tx_edit_version"] = st.session_state.get("tx_edit_version", 0) + 1
        st.session_state["tx_edit_instance_version"] = st.session_state.get("tx_edit_instance_version", 0) + 1
        st.rerun(scope="fragment")
    edited_df = edited_df[required_columns]
    baseline_ids = set(baseline["记录ID"].map(_text_value))
    deleted_ids = list(dict.fromkeys(
        _text_value(transaction_id)
        for transaction_id in result.get("deleted_ids", [])
        if _text_value(transaction_id) in baseline_ids
    ))
    edited_ids = set(edited_df["记录ID"].map(_text_value))
    removed_ids = edited_ids | set(deleted_ids)
    merged_draft = draft[~draft["记录ID"].map(_text_value).isin(removed_ids)].copy(deep=True)
    merged_draft = pd.concat([merged_draft, edited_df], ignore_index=True)
    st.session_state["merged_df"] = merged_draft.copy(deep=True)
    st.session_state["tx_edit_deleted_ids"] = deleted_ids

    if result["action"] == "manual_entry":
        ok, message = _create_transaction_from_component(result.get("manual_entry", {}))
        if ok:
            _refresh_tx_bulk_loaded_months()
            st.session_state["tx_notice"] = message
        else:
            st.session_state["tx_edit_error"] = message
        st.session_state["tx_edit_instance_version"] = (
            st.session_state.get("tx_edit_instance_version", 0) + 1
        )
        st.rerun(scope="fragment")

    if result["action"] == "save":
        ok, message = _save_tx_bulk_edits(merged_draft, baseline, deleted_ids)
        if ok:
            _reset_tx_editor()
            st.session_state["tx_notice"] = message
        else:
            st.session_state["tx_edit_error"] = message
            st.session_state["tx_edit_version"] = st.session_state.get("tx_edit_version", 0) + 1
            st.session_state["tx_edit_instance_version"] = st.session_state.get("tx_edit_instance_version", 0) + 1
        st.rerun(scope="fragment")

    if result["action"] == "cancel":
        _discard_tx_bulk_edit()
        st.rerun(scope="fragment")


@st.fragment
def _render_transactions_fragment(months: list[str], years: list[str]) -> None:
    """流水列表局部交互区：选择行只会重跑该片段。"""
    # fragment 级重跑不会重新执行 page_transactions 的初始化逻辑，需在片段入口兜底会话键。
    if not months:
        return
    fallback_month = months[0]
    selected_month = st.session_state.get("tx_month")
    if selected_month not in months:
        selected_month = fallback_month
        st.session_state["tx_month"] = selected_month
    selected_year = st.session_state.get("tx_year")
    valid_years = years or sorted({month[:4] for month in months}, reverse=True)
    if selected_year not in valid_years:
        selected_year = selected_month[:4]
        st.session_state["tx_year"] = selected_year
    st.session_state.setdefault("tx_search", "")
    st.session_state.setdefault("tx_search_active", _tx_global_search_active(st.session_state["tx_search"]))
    if "tx_column_filters" not in st.session_state:
        _set_tx_column_filters(_empty_tx_column_filters())
    is_editing = st.session_state.get("tx_edit_mode", False)
    controls_slot = st.empty()
    table_slot = st.empty()
    selected_year = st.session_state["tx_year"]
    selected_month = st.session_state["tx_month"]
    keyword = st.session_state["tx_search"]
    search_active = _tx_global_search_active(keyword)
    st.session_state["tx_search_active"] = search_active
    applied_filters = _normalise_tx_column_filters(st.session_state["tx_column_filters"])
    context = {
        "month": selected_month,
        "keyword": keyword,
        "search_active": search_active,
        "column_filters": applied_filters,
    }
    if st.session_state.get("tx_active_context") != context and not is_editing:
        _reset_tx_editor()
        st.session_state["tx_active_context"] = context

    # 全局搜索框有关键词时固定查询整个数据库；字段筛选仅继续缩小搜索结果。
    query_month = None if search_active else selected_month
    query_keyword = keyword if search_active else ""
    base_rows, total = db.query_transactions(query_month, page_size=None, keyword=query_keyword)
    rows = _filter_tx_rows(base_rows, applied_filters)
    month_scope_rows = base_rows
    if search_active:
        # 关键词搜索继续用于只读结果；整表编辑的基线始终包含所选月份的全部流水。
        month_scope_rows, _ = db.query_transactions(selected_month, page_size=None)
    database_scope_df = _rows_to_editor_df(month_scope_rows) if month_scope_rows else None
    # 表头筛选完全由本地组件处理；操作栏始终以当前月份/搜索的完整结果校验记录。
    database_df = _rows_to_editor_df(base_rows) if base_rows else None
    edit_view_mode = "month"
    edit_visible_ids: list[str] = []
    if is_editing:
        if database_scope_df is not None:
            _extend_tx_bulk_edit_month(database_scope_df, selected_month)
        draft_all = st.session_state.get("merged_df")
        # 编辑期间由浏览器组件直接在完整草稿上筛选，避免用 Python 中的旧基线
        # 覆盖尚未回传的账户、收支、分类、金额等修改。
        database_df = draft_all.copy(deep=True) if draft_all is not None else None
        if search_active:
            _ensure_tx_bulk_search_scope(keyword)
            current_draft = st.session_state.get("merged_df")
            database_df = current_draft.copy(deep=True) if current_draft is not None else None
            edit_view_mode = "search"
            edit_visible_ids = st.session_state.get("tx_edit_search_ids", [])
        else:
            st.session_state["tx_edit_view_mode"] = "month"
    draft_for_options = st.session_state.get("merged_df") if is_editing else None
    filter_options = _tx_filter_options(base_rows, applied_filters, draft_for_options)
    if not is_editing:
        with table_slot.container():
            if search_active:
                st.caption(f"全局搜索结果：共 {total} 条记录")
            else:
                st.caption(f"共 {total} 条记录")
            view_result = transaction_viewer(
                rows=_editor_df_to_component_rows(_rows_to_editor_df(base_rows)) if base_rows else [],
                version=st.session_state.get("tx_editor_version", 0),
                selection_key=f"tx_selection_{st.session_state.get('tx_editor_version', 0)}",
                accounts=ACCOUNTS,
                trade_types=TRADE_TYPES,
                expense_categories=EXPENSE_CATEGORIES,
                income_categories=INCOME_CATEGORIES,
                status_rules=STATUS_RULES,
                expense_tags=EXPENSE_TAGS,
                income_tags=INCOME_TAGS,
                income_category_tags=INCOME_CATEGORY_TAGS,
                expense_category_tags=EXPENSE_CATEGORY_TAGS,
                cleanup_draft_session_id=st.session_state.get("tx_draft_cleanup_session_id", ""),
                filters=applied_filters,
                filter_options=filter_options,
                filter_reset_key=f"view:{selected_month}:{search_active}:{keyword}",
                # 工具栏 52px + 表头 38px + 10 行（每行 36px）。
                height=450,
                key=f"tx_viewer_{st.session_state.get('tx_editor_version', 0)}",
            )
    elif is_editing and database_df is not None:
        with table_slot.container():
            _render_tx_bulk_edit_form(
                database_df,
                filter_options,
                view_mode=edit_view_mode,
                visible_ids=edit_visible_ids,
            )
    else:
        with table_slot.container():
            st.caption(f"显示 0 / {total} 条记录")
            st.info("当前筛选条件下没有记录。")

    with controls_slot.container():
        month_toolbar = st.columns([0.8] + [0.35] * 12 + [3.1], gap=None)
        with month_toolbar[0]:
            st.selectbox("年份", years, key="tx_year", format_func=lambda year: f"{year}年",
                         on_change=_request_tx_year_change, label_visibility="collapsed")
        for month_number, column in enumerate(month_toolbar[1:13], start=1):
            target_month = f"{selected_year}-{month_number:02d}"
            with column:
                st.button(f"{month_number}月", key=f"tx_month_button_{selected_year}_{month_number}",
                          type="primary" if target_month == selected_month else "secondary",
                          disabled=target_month not in months, use_container_width=True,
                          on_click=_request_tx_month_change, args=(target_month,))
        with month_toolbar[13]:
            st.text_input("搜索（备注/分类/对方）", key="tx_search",
                          on_change=_request_tx_filter_change, label_visibility="collapsed",
                          placeholder="全局搜索：AND/且、OR/或")

        if not is_editing and database_df is not None:
            action_result = view_result
            if isinstance(action_result, dict) and action_result.get("action") == "edit":
                _begin_tx_bulk_edit(database_scope_df, context)
                st.rerun(scope="fragment")
            if isinstance(action_result, dict) and action_result.get("action") == "manual_entry":
                ok, message = _create_transaction_from_component(
                    action_result.get("manual_entry", {})
                )
                st.session_state["tx_notice"] = message
                st.session_state["tx_editor_version"] = (
                    st.session_state.get("tx_editor_version", 0) + 1
                )
                st.rerun(scope="fragment")
            if isinstance(action_result, dict) and action_result.get("action") == "single_edit":
                selected_ids = {
                    _text_value(transaction_id)
                    for transaction_id in action_result.get("selected_ids", [])
                }
                matching_rows = database_df[
                    database_df["记录ID"].map(_text_value).isin(selected_ids)
                ]
                if len(selected_ids) == 1 and len(matching_rows) == 1:
                    # 片段中不能可靠地展示对话框；切换到整页重跑后由页面层打开。
                    st.session_state["tx_single_edit_id"] = next(iter(selected_ids))
                    st.session_state["tx_single_edit_row"] = matching_rows.iloc[0].to_dict()
                    st.session_state["tx_editor_version"] = st.session_state.get("tx_editor_version", 0) + 1
                    st.rerun(scope="app")
            if isinstance(action_result, dict) and action_result.get("action") == "copy":
                selected_ids = {
                    _text_value(transaction_id)
                    for transaction_id in action_result.get("selected_ids", [])
                }
                visible_ids = set(database_df["记录ID"].map(_text_value))
                if len(selected_ids) == 1 and selected_ids <= visible_ids:
                    copied = db.copy_transaction(next(iter(selected_ids)))
                    _reset_tx_editor()
                    st.session_state["tx_notice"] = (
                        "已复制 1 条流水。" if copied else "复制失败：原流水不存在。"
                    )
                    st.rerun(scope="fragment")
            if isinstance(action_result, dict) and action_result.get("action") == "delete":
                selected_ids = {
                    _text_value(transaction_id)
                    for transaction_id in action_result.get("selected_ids", [])
                }
                visible_ids = set(database_df["记录ID"].map(_text_value))
                deleted = db.delete_transactions(list(selected_ids & visible_ids))
                _reset_tx_editor()
                st.session_state["tx_notice"] = f"已删除 {deleted} 条记录。"
                st.rerun(scope="fragment")

        if st.session_state.get("tx_notice"):
            st.success(st.session_state.pop("tx_notice"))


def page_transactions() -> None:
    if st.session_state.get("tx_pending_action"):
        _render_unsaved_changes_dialog()

    months = db.get_available_months()
    if not months:
        st.info("还没有任何交易记录。")
        return

    current_month = datetime.now().strftime("%Y-%m")
    if st.session_state.get("tx_month") not in months:
        st.session_state["tx_month"] = current_month if current_month in months else months[0]
    years = sorted({month[:4] for month in months}, reverse=True)
    if st.session_state.get("tx_year") not in years:
        st.session_state["tx_year"] = st.session_state["tx_month"][:4]
    st.session_state["tx_available_months"] = months
    st.session_state.pop("tx_page", None)
    st.session_state.pop("tx_filter_expanded", None)
    if "tx_search" not in st.session_state:
        st.session_state["tx_search"] = ""
    if "tx_search_active" not in st.session_state:
        st.session_state["tx_search_active"] = _tx_global_search_active(st.session_state["tx_search"])
    if "tx_column_filters" not in st.session_state:
        _set_tx_column_filters(_empty_tx_column_filters())
    elif ("tx_filter_accounts" not in st.session_state
          or "tx_filter_life_tags" not in st.session_state
          or "tx_filter_reimbursement_statuses" not in st.session_state
          or not isinstance(st.session_state.get("tx_filter_amount_min"), str)
          or not isinstance(st.session_state.get("tx_filter_amount_max"), str)):
        _set_tx_column_filters(st.session_state["tx_column_filters"])

    _render_transactions_fragment(months, years)
    single_edit_row = st.session_state.get("tx_single_edit_row")
    if single_edit_row:
        _render_single_edit_dialog(pd.Series(single_edit_row))


def page_import() -> None:
    if "excluded_records" not in st.session_state:
        st.session_state["excluded_records"] = []


    st.caption("上传支付宝或微信导出的 CSV 账单，自动去重后存入数据库。")

    col1, col2 = st.columns(2)
    with col1:
        alipay_file = st.file_uploader("支付宝 CSV", type=["csv", "xlsx"], key="import_alipay")
    with col2:
        wechat_file = st.file_uploader("微信 CSV / XLSX", type=["csv", "xlsx"], key="import_wechat")

    if st.button("开始导入", type="primary", use_container_width=True):
        if alipay_file is None and wechat_file is None:
            st.error("请至少上传一个 CSV 文件。")
            return

        total_inserted = 0
        total_skipped = 0

        if alipay_file is not None:
            try:
                inserted, skipped, excluded_rows, preview = p.import_csv_to_db(alipay_file, "支付宝")
                total_inserted += inserted
                total_skipped += skipped
                st.success(f"支付宝：新增 {inserted} 条，跳过 {skipped} 条（重复），剔除 {len(excluded_rows)} 条（自动过滤）")
                with st.expander("预览支付宝导入记录"):
                    _render_local_table(
                        _format_amount_columns(pd.DataFrame(preview)),
                        table_key="alipay_import_preview",
                    )
                if excluded_rows:
                    with st.expander(f"支付宝自动过滤记录 ({len(excluded_rows)} 条)"):
                        _render_local_table(
                            _format_amount_columns(pd.DataFrame(excluded_rows)),
                            table_key="alipay_excluded_preview",
                        )
                        st.caption("以下记录已被自动过滤未导入，如发现误排除请手动补录。")
                if excluded_rows:
                    st.session_state["excluded_records"].extend(excluded_rows)
            except Exception as exc:
                st.error(f"支付宝导入失败：{exc}")

        if wechat_file is not None:
            try:
                inserted, skipped, excluded_rows, preview = p.import_csv_to_db(wechat_file, "微信")
                total_inserted += inserted
                total_skipped += skipped
                st.success(f"微信：新增 {inserted} 条，跳过 {skipped} 条（重复），剔除 {len(excluded_rows)} 条（自动过滤）")
                with st.expander("预览微信导入记录"):
                    _render_local_table(
                        _format_amount_columns(pd.DataFrame(preview)),
                        table_key="wechat_import_preview",
                    )
                if excluded_rows:
                    with st.expander(f"微信自动过滤记录 ({len(excluded_rows)} 条)"):
                        _render_local_table(
                            _format_amount_columns(pd.DataFrame(excluded_rows)),
                            table_key="wechat_excluded_preview",
                        )
                        st.caption("以下记录已被自动过滤未导入，如发现误排除请手动补录。")
                    st.session_state["excluded_records"].extend(excluded_rows)
            except Exception as exc:
                st.error(f"微信导入失败：{exc}")

        if total_inserted > 0:
            st.success(f"🎉 导入完成：共新增 {total_inserted} 条，跳过 {total_skipped} 条重复记录。")
            if st.button("导出 Excel 备份", use_container_width=True):
                months = db.get_available_months()
                if months:
                    all_rows = []
                    for m in months:
                        rows, _ = db.query_transactions(m, page=1, page_size=999999)
                        all_rows.extend(rows)
                    df_all = pd.DataFrame(all_rows)
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        df_all.to_excel(writer, index=False, sheet_name="全部流水")
                    output.seek(0)
                    st.download_button(
                        "下载 Excel", output.getvalue(),
                        file_name="全部流水.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )




    if st.session_state["excluded_records"]:
        st.divider()
        with st.expander(f"📋 历史自动过滤记录 ({len(st.session_state['excluded_records'])} 条)", expanded=True):
            _render_local_table(
                _format_amount_columns(pd.DataFrame(st.session_state["excluded_records"])),
                table_key="excluded_records_history",
            )
            st.caption("以下记录已被自动过滤未导入，如发现误排除请手动补录。")
        if st.button("🗑️ 清除过滤记录", use_container_width=True, type="secondary"):
            st.session_state["excluded_records"] = []
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════
# 页面：手动记账
# ══════════════════════════════════════════════════════════════════════════

def page_manual() -> None:
    if "manual_trade_type" not in st.session_state:
        st.session_state["manual_trade_type"] = "支出"
    type_col, category_col = st.columns(2)
    with type_col:
        trade_type = st.selectbox("收支类型", TRADE_TYPES, key="manual_trade_type")
    category_options = _categories_for_trade_type(trade_type)
    if st.session_state.get("manual_category") not in category_options:
        st.session_state["manual_category"] = category_options[0]
    with category_col:
        category = st.selectbox("分类", category_options, key="manual_category")

    tag_options = _tag_options_for_category(trade_type, category)
    category_changed = st.session_state.get("manual_tag_category") != (trade_type, category)
    automatic_tag = sr.default_life_tag(
        trade_type, category, INCOME_CATEGORY_TAGS, EXPENSE_CATEGORY_TAGS, STATUS_RULES
    )
    if category_changed and automatic_tag:
        st.session_state["manual_life_tag"] = automatic_tag
    elif st.session_state.get("manual_life_tag") not in ("", *tag_options):
        st.session_state["manual_life_tag"] = ""
    st.session_state["manual_tag_category"] = (trade_type, category)
    st.session_state.setdefault("manual_entry_time", "00:00:00")


    with st.form("manual_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            entry_date = st.date_input("日期", value=date.today())
            st.caption("时间（24 小时制）")
            entry_time = segmented_time_input(
                value=st.session_state["manual_entry_time"],
                key="manual_entry_time_input",
            )
            st.session_state["manual_entry_time"] = entry_time
            amount = st.number_input("金额", min_value=0.01, value=0.01, step=0.01, format="%.2f")
        with col2:
            account = st.selectbox("账户", ACCOUNTS)
            life_tag = st.selectbox(
                "标签", ["", *tag_options],
                key="manual_life_tag",
                disabled=_tag_is_locked(category),
            )
            manual_status_options = sr.status_options(trade_type, category, STATUS_RULES)
            reimbursement_status = st.selectbox(
                "报销状态",
                manual_status_options or [""],
                index=(manual_status_options.index(sr.default_status(trade_type, category, STATUS_RULES))
                       if manual_status_options else 0),
                disabled=not manual_status_options,
            )
        remark = st.text_input("备注", placeholder="例如：午餐、地铁通勤...")
        counterparty = st.text_input("交易对方", placeholder="例如：美团、滴滴...")
        payment_channel = st.text_input("支付方式", placeholder="例如：余额宝、零钱通...")

        submitted = st.form_submit_button("保存记录", type="primary", use_container_width=True)
        if submitted:
            try:
                ok = p.import_manual_entry(
                    trade_time=_manual_trade_time(entry_date, entry_time),
                    account=account,
                    trade_type=trade_type,
                    amount=amount,
                    category=category,
                    life_tag=sr.normalise_life_tag(
                        trade_type, category, life_tag, EXPENSE_TAGS, INCOME_TAGS, STATUS_RULES
                    ),
                    reimbursement_status=reimbursement_status,
                    remark=remark,
                    counterparty=counterparty,
                    payment_channel=payment_channel,
                )
                if ok:
                    st.session_state["manual_tag_category"] = None
                    st.session_state["manual_entry_time"] = "00:00:00"
                else:
                    st.success("记录已保存！")
                    st.warning("该记录可能已存在（重复），未重复添加。")
            except Exception as exc:
                st.error(f"保存失败：{exc}")


OPTION_TYPE_LABELS = {
    "account": "账户",
    "expense_category": "支出分类",
    "income_category": "收入分类",
    "expense_tag": "支出标签",
    "income_tag": "收入标签",
}


OPTION_TYPE_ORDER = [
    "account", "expense_category", "income_category", "expense_tag", "income_tag",
]


def _option_draft_id(option_type: str) -> str:
    return f"option:{option_type}"


def _option_version_key(option_type: str) -> str:
    return f"option_manager_version_{option_type}"


def _clear_option_draft(option_type: str) -> None:
    """清理当前选项类型的浏览器草稿，并在下次组件渲染时删除本地缓存。"""
    st.session_state["option_cleanup_draft_id"] = _option_draft_id(option_type)
    st.session_state["option_dirty"] = False
    st.session_state["option_dirty_type"] = None
    st.session_state["option_append_row"] = None
    st.session_state["option_submit_token"] = ""
    version_key = _option_version_key(option_type)
    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1


def _complete_option_pending_action() -> None:
    """在保存或放弃选项草稿后执行此前请求的切换。"""
    action = st.session_state.pop("option_pending_action", None)
    st.session_state.pop("option_save_after_switch", None)
    if not action:
        return
    if action["kind"] == "type":
        st.session_state["option_active_type"] = action["option_type"]
    elif action["kind"] == "page":
        st.session_state["current_page"] = action["page"]


def _request_option_type_change(option_type: str) -> None:
    """切换选项类型前拦截当前浏览器草稿。"""
    if option_type == st.session_state.get("option_active_type", "account"):
        return
    if st.session_state.get("option_dirty", False):
        st.session_state["option_pending_action"] = {"kind": "type", "option_type": option_type}
        return
    st.session_state["option_active_type"] = option_type


def _save_option_rows(
    option_type: str,
    rows: list[dict],
    *,
    mapping_type: str | None = None,
) -> tuple[bool, str]:
    """校验并持久化一类选项的完整浏览器草稿。"""
    edited = pd.DataFrame(rows)
    required_columns = {"原名称", "名称", "删除", "__行ID"}
    if required_columns - set(edited.columns):
        return False, "选项表格返回的数据不完整，请重新编辑后保存。"
    locked_categories = {
        _text_value(row["名称"])
        for _, row in edited.iterrows()
        if _tag_is_locked(_text_value(row["原名称"]))
    }
    try:
        db.save_option_items(
            option_type,
            edited.to_dict(orient="records"),
            mapping_type=mapping_type,
            locked_categories=locked_categories,
        )
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"保存失败：{exc}"
    return True, f"{OPTION_TYPE_LABELS[option_type]}已保存。"


@st.dialog("未保存的选项修改")
def _render_option_unsaved_dialog() -> None:
    """选项管理离开或切换前的统一草稿确认弹窗。"""
    action = st.session_state.get("option_pending_action")
    if not action or st.session_state.get("option_save_after_switch", False):
        return
    st.warning("当前选项修改尚未保存。")
    st.caption("你可以继续编辑、放弃修改后切换，或保存后再切换。")
    current_type = st.session_state.get("option_active_type", "account")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("继续编辑", use_container_width=True, key="option_keep_editing"):
            st.session_state["option_pending_action"] = None
            st.rerun()
    with col2:
        if st.button("放弃修改并切换", use_container_width=True, key="option_discard_switch"):
            _clear_option_draft(current_type)
            _complete_option_pending_action()
            st.rerun()
    with col3:
        if st.button("保存后切换", type="primary", use_container_width=True, key="option_save_switch"):
            st.session_state["option_save_after_switch"] = True
            st.session_state["option_submit_token"] = uuid.uuid4().hex
            st.rerun()


def _render_option_manager(option_type: str, *, mapping_type: str | None = None) -> None:
    """编辑一类可选项；所有修改先保存在浏览器草稿。"""
    label = OPTION_TYPE_LABELS[option_type]
    if st.session_state.pop("option_clear_new_value_for", None) == option_type:
        st.session_state[f"new_option_{option_type}"] = ""
    items = db.get_option_items(option_type)
    mappings = db.get_category_tag_mappings(mapping_type) if mapping_type else {}
    mapping_tags = INCOME_TAGS if mapping_type == "income_category" else EXPENSE_TAGS
    rows = []
    for item in items:
        row = {
            "__行ID": f"db:{item['value']}",
            "原名称": item["value"],
            "名称": item["value"],
            "删除": False,
        }
        if mapping_type:
            row["自动关联标签"] = mappings.get(item["value"], "")
            row["__标签锁定"] = _tag_is_locked(item["value"])
        rows.append(row)

    option_columns = [
        {"key": "顺序", "label": "顺序", "kind": "reorder", "width": 82},
        {"key": "名称", "label": "名称", "kind": "text", "width": 180},
    ]
    if mapping_type:
        option_columns.append(
            {
                "key": "自动关联标签",
                "label": "自动关联标签",
                "kind": "select",
                "options": ["", *mapping_tags],
                "width": 180,
            }
        )
    option_columns.append({"key": "删除", "label": "删除", "kind": "checkbox", "width": 80})
    version_key = _option_version_key(option_type)
    append_row = st.session_state.get("option_append_row")
    if not isinstance(append_row, dict) or append_row.get("__选项类型") != option_type:
        append_row = {}
    cleanup_draft_id = st.session_state.get("option_cleanup_draft_id", "")
    result = option_editor(
        rows=rows,
        columns=option_columns,
        version=st.session_state.get(version_key, 0),
        layout_key=f"account_book_option_manager_{option_type}_v1",
        draft_id=_option_draft_id(option_type),
        append_row=append_row,
        cleanup_draft_id=cleanup_draft_id,
        submit_token=st.session_state.get("option_submit_token", ""),
        height=min(max(180, 76 + len(rows) * 36), 480),
        key=f"option_editor_{option_type}",
    )
    if cleanup_draft_id:
        st.session_state["option_cleanup_draft_id"] = ""

    add_col, action_col = st.columns([3, 1])
    with add_col:
        new_value = st.text_input(f"新增{label}", key=f"new_option_{option_type}")
    with action_col:
        st.write("")
        add_clicked = st.button("新增", key=f"add_option_{option_type}", use_container_width=True)
    if add_clicked:
        value = new_value.strip()
        if not value:
            st.error(f"新增{label}不能为空。")
        else:
            new_row = {
                "__行ID": f"new:{uuid.uuid4().hex}",
                "__选项类型": option_type,
                "原名称": "",
                "名称": value,
                "删除": False,
            }
            if mapping_type:
                new_row["自动关联标签"] = ""
                new_row["__标签锁定"] = False
            st.session_state["option_append_row"] = new_row
            st.session_state["option_dirty"] = True
            st.session_state["option_dirty_type"] = option_type
            st.session_state["option_clear_new_value_for"] = option_type
            st.rerun()

    if isinstance(result, dict) and result.get("action") == "option_dirty":
        st.session_state["option_dirty"] = True
        st.session_state["option_dirty_type"] = option_type
    if isinstance(result, dict) and result.get("action") == "save":
        ok, message = _save_option_rows(option_type, result.get("rows", []), mapping_type=mapping_type)
        if not ok:
            st.session_state["option_error"] = message
        else:
            _clear_option_draft(option_type)
            st.session_state["option_notice"] = message + " 删除的条目仍会保留在历史流水中。"
            st.session_state["option_error"] = None
            _complete_option_pending_action()
            st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
            st.rerun()


def page_option_management() -> None:
    st.caption("可维护账户、分类和标签。重命名会同步既有流水；删除仅移出后续可选项，不会删除账目。")
    if st.session_state.get("option_notice"):
        st.success(st.session_state.pop("option_notice"))
    if "option_active_type" not in st.session_state:
        st.session_state["option_active_type"] = "account"
    button_labels = [
        ("account", "账户"),
        ("expense_category", "支出分类（含退款）"),
        ("income_category", "收入分类"),
        ("expense_tag", "支出标签（含退款）"),
        ("income_tag", "收入标签"),
    ]
    columns = st.columns(len(button_labels))
    for column, (option_type, button_label) in zip(columns, button_labels):
        with column:
            if st.button(
                button_label,
                key=f"option_type_{option_type}",
                type="primary" if st.session_state["option_active_type"] == option_type else "secondary",
                use_container_width=True,
            ):
                _request_option_type_change(option_type)
    active_type = st.session_state["option_active_type"]
    mapping_type = active_type if active_type in {"expense_category", "income_category"} else None
    if st.session_state.get("option_error"):
        st.error(st.session_state["option_error"])
    _render_option_manager(active_type, mapping_type=mapping_type)
    if st.session_state.get("option_pending_action") and not st.session_state.get("option_save_after_switch", False):
        _render_option_unsaved_dialog()


# ══════════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════════

def main() -> None:
    pages = {
        "仪表盘": page_dashboard,
        "流水列表": page_transactions,
        "导入账单": page_import,
        "手动记账": page_manual,
        "选项管理": page_option_management,
    }

    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "仪表盘"

    if "excluded_records" not in st.session_state:
        st.session_state["excluded_records"] = []

    with st.sidebar:
        st.title("个人记账系统")
        st.caption(f"数据库：{db.DB_PATH.name}")
        total_count = db.get_all_transactions_count()
        st.caption(f"总记录数：{total_count:,}")

        st.divider()
        navigation_locked = st.session_state.get("tx_edit_mode", False)
        for page_name in pages:
            if st.button(page_name, use_container_width=True,
                         type="primary" if st.session_state["current_page"] == page_name else "secondary",
                         disabled=navigation_locked):
                _request_page_change(page_name)
                st.rerun()

    pages[st.session_state["current_page"]]()


if __name__ == "__main__":
    main()
