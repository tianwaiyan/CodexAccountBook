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
    reimbursement_statuses: list[str],
    life_tags: list[str],
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
        reimbursement_statuses=reimbursement_statuses,
        life_tags=life_tags,
        height=height,
        default=None,
        key=key,
    )


def transaction_viewer(
    *,
    rows: list[dict[str, Any]],
    version: int,
    selection_key: str,
    height: int = 500,
    key: str | None = None,
) -> dict[str, Any] | None:
    """渲染只读流水表；勾选仅保留在浏览器端，删除时才回传。"""
    return _COMPONENT(
        mode="view",
        rows=rows,
        version=version,
        selection_key=selection_key,
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


def transaction_actions(
    *,
    version: int,
    selection_key: str,
    key: str | None = None,
) -> dict[str, Any] | None:
    """渲染位于筛选栏下方的本地流水操作按钮。"""
    return _COMPONENT(
        mode="actions",
        rows=[],
        version=version,
        selection_key=selection_key,
        height=50,
        default=None,
        key=key,
    )
