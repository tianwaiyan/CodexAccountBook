"""流水整表编辑的本地 Streamlit 组件入口。

组件前端只在用户点击“保存修改”或“取消修改”时回传数据，
因此单元格编辑不会触发 Streamlit 重跑。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


_COMPONENT = components.declare_component(
    "local_transaction_editor",
    path=str(Path(__file__).parent / "components" / "transaction_editor"),
)

def transaction_editor(
    *,
    rows: list[dict[str, Any]],
    version: int,
    accounts: list[str],
    trade_types: list[str],
    expense_categories: list[str],
    income_categories: list[str],
    status_rules: dict[str, dict[str, object]],
    expense_tags: list[str],
    income_tags: list[str],
    income_category_tags: dict[str, str],
    expense_category_tags: dict[str, str],
    deleted_ids: list[str],
    draft_ids: list[str],
    draft_session_id: str,
    filters: dict[str, Any],
    height: int = 600,
    key: str | None = None,
) -> dict[str, Any] | None:
    """渲染浏览器端草稿表格，并仅在保存/取消时返回结果。"""
    return _COMPONENT(
        mode="edit",
        rows=rows,
        version=version,
        accounts=accounts,
        trade_types=trade_types,
        expense_categories=expense_categories,
        income_categories=income_categories,
        status_rules=status_rules,
        expense_tags=expense_tags,
        income_tags=income_tags,
        income_category_tags=income_category_tags,
        expense_category_tags=expense_category_tags,
        deleted_ids=deleted_ids,
        draft_ids=draft_ids,
        draft_session_id=draft_session_id,
        filters=filters,
        height=height,
        default=None,
        key=key,
    )


def transaction_viewer(
    *,
    rows: list[dict[str, Any]],
    version: int,
    selection_key: str,
    cleanup_draft_session_id: str = "",
    height: int = 500,
    key: str | None = None,
) -> dict[str, Any] | None:
    """渲染只读流水表；勾选仅保留在浏览器端，删除时才回传。"""
    return _COMPONENT(
        mode="view",
        rows=rows,
        version=version,
        selection_key=selection_key,
        cleanup_draft_session_id=cleanup_draft_session_id,
        height=height,
        default=None,
        key=key,
    )


def yearly_category_viewer(
    *,
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    version: int,
    year: str,
    height: int = 500,
    key: str | None = None,
) -> None:
    """渲染年度分类支出只读汇总表。"""
    _COMPONENT(
        mode="yearly-summary",
        rows=rows,
        columns=columns,
        version=version,
        year=year,
        summary_first_key=columns[0]["key"] if columns else "",
        height=height,
        default=None,
        key=key,
    )


def local_table_viewer(
    *,
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    version: int,
    layout_key: str,
    empty_message: str,
    height: int = 360,
    key: str | None = None,
) -> None:
    """用统一的本地表格样式展示任意只读数据。"""
    _COMPONENT(
        mode="generic-view",
        rows=rows,
        columns=columns,
        version=version,
        layout_key=layout_key,
        empty_message=empty_message,
        height=height,
        default=None,
        key=key,
    )


def option_editor(
    *,
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    version: int,
    layout_key: str,
    height: int = 360,
    key: str | None = None,
) -> dict[str, Any] | None:
    """用统一的本地表格样式编辑选项，仅保存时回传。"""
    return _COMPONENT(
        mode="option-edit",
        rows=rows,
        columns=columns,
        version=version,
        layout_key=layout_key,
        height=height,
        default=None,
        key=key,
    )


def transaction_actions(
    *,
    version: int,
    selection_key: str,
    cleanup_draft_session_id: str = "",
    key: str | None = None,
) -> dict[str, Any] | None:
    """渲染位于筛选栏下方的本地流水操作按钮。"""
    return _COMPONENT(
        mode="actions",
        rows=[],
        version=version,
        selection_key=selection_key,
        cleanup_draft_session_id=cleanup_draft_session_id,
        height=50,
        default=None,
        key=key,
    )
