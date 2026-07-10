"""个人记账系统 —— Streamlit 前端。

页面：仪表盘 / 流水列表 / 导入账单 / 手动记账。
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import time

import db
import parser as p

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
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)

# ── 常量 ─────────────────────────────────────────────────────────────
CATEGORIES = sorted(set(p.CATEGORY_MAP.values()))
PLATFORMS = ["支付宝", "微信", "手动录入"]
TRADE_TYPES = ["支出", "收入"]


# ══════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════

def _format_money(value: float) -> str:
    """金额格式化，带颜色标记。"""
    if value >= 0:
        return f"¥{value:,.2f}"
    return f"-¥{abs(value):,.2f}"


# ── 流水列表编辑辅助 ──────────────────────────────────────────────────
TX_EDITOR_COLUMNS = ["时间", "来源", "收支", "金额", "分类", "说明", "对方", "支付方式"]


def _reset_tx_editor() -> None:
    """使流水编辑器在下次渲染时从数据库重新加载。"""
    st.session_state["tx_editor_version"] = st.session_state.get("tx_editor_version", 0) + 1
    st.session_state["tx_baseline"] = None
    st.session_state["tx_editor_current"] = None
    st.session_state["tx_dirty"] = False
    st.session_state["tx_editor_seed"] = None


def _rows_to_editor_df(rows: list[dict]) -> pd.DataFrame:
    """将数据库流水转换为可编辑表格，金额统一展示为正数。"""
    editor_rows = []
    for row in rows:
        editor_rows.append({
            "记录ID": row["id"],
            "选择": False,
            "时间": pd.to_datetime(row["trade_time"], errors="coerce"),
            "来源": row["platform"] or "",
            "收支": row["trade_type"] or "",
            "金额": abs(float(row["amount"])),
            "分类": row["category"] or "",
            "说明": row["description"] or "",
            "对方": row["counterparty"] or "",
            "支付方式": row["payment_channel"] or "",
        })
    return pd.DataFrame(editor_rows)


def _text_value(value: object) -> str:
    """将表格文本值规范化，避免 Pandas 的 NaN 被保存为字符串 nan。"""
    return "" if pd.isna(value) else str(value).strip()


def _editor_row_to_db(row: pd.Series) -> dict:
    """校验并转换一行编辑器数据为数据库字段。"""
    parsed_time = pd.to_datetime(row["时间"], errors="coerce")
    if pd.isna(parsed_time):
        raise ValueError("交易时间格式无效")

    platform = _text_value(row["来源"])
    trade_type = _text_value(row["收支"])
    if platform not in PLATFORMS:
        raise ValueError("来源必须为支付宝、微信或手动录入")
    if trade_type not in TRADE_TYPES:
        raise ValueError("收支必须为支出或收入")

    try:
        amount = float(row["金额"])
    except (TypeError, ValueError) as exc:
        raise ValueError("金额必须为数字") from exc
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("金额必须大于 0")

    return {
        "id": _text_value(row["记录ID"]),
        "trade_time": parsed_time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": platform,
        "trade_type": trade_type,
        "amount": amount if trade_type == "收入" else -amount,
        "category": _text_value(row["分类"]),
        "description": _text_value(row["说明"]),
        "counterparty": _text_value(row["对方"]),
        "payment_channel": _text_value(row["支付方式"]),
    }


def _row_signature(row: pd.Series) -> tuple:
    """用于比较编辑前后业务字段；选择框不计入未保存修改。"""
    try:
        values = _editor_row_to_db(row)
        return tuple(values[column] for column in (
            "trade_time", "platform", "trade_type", "amount", "category",
            "description", "counterparty", "payment_channel",
        ))
    except ValueError:
        # 无效输入也应视作未保存修改，以便用户能收到切换提示并修正它。
        return tuple(_text_value(row.get(column, "")) for column in TX_EDITOR_COLUMNS)


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
                platform=values["platform"],
                trade_type=values["trade_type"],
                amount=values["amount"],
                category=values["category"],
                description=values["description"],
                counterparty=values["counterparty"],
                payment_channel=values["payment_channel"],
            ):
                updated += 1
    except Exception as exc:
        return False, f"保存失败：{exc}"

    _reset_tx_editor()
    return True, f"已保存 {updated} 条修改。"


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
        st.session_state["tx_active_context"] = None


def _continue_tx_editing() -> None:
    st.session_state["tx_pending_action"] = None
    st.session_state["tx_dialog_error"] = None


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


def _request_tx_filter_change() -> None:
    """筛选控件变化时，拦截可能丢失的未保存编辑。"""
    active_context = st.session_state.get("tx_active_context")
    if not active_context:
        return

    requested_context = {
        "month": st.session_state["tx_month"],
        "keyword": st.session_state["tx_search"],
    }
    if requested_context == active_context:
        return

    if st.session_state.get("tx_dirty", False):
        st.session_state["tx_month"] = active_context["month"]
        st.session_state["tx_year"] = active_context["month"][:4]
        st.session_state["tx_search"] = active_context["keyword"]
        st.session_state["tx_pending_action"] = {
            "kind": "filters", "context": requested_context,
        }
    else:
        _reset_tx_editor()
        st.session_state["tx_active_context"] = None


def _request_tx_month_change(target_month: str) -> None:
    """月份按钮或年份下拉变化时，安全地切换完整 YYYY-MM 筛选值。"""
    active_context = st.session_state.get("tx_active_context")
    if not active_context:
        st.session_state["tx_month"] = target_month
        st.session_state["tx_year"] = target_month[:4]
        return

    requested_context = {
        "month": target_month,
        "keyword": st.session_state.get("tx_search", ""),
    }
    if requested_context == active_context:
        st.session_state["tx_month"] = target_month
        st.session_state["tx_year"] = target_month[:4]
        return

    if st.session_state.get("tx_dirty", False):
        st.session_state["tx_month"] = active_context["month"]
        st.session_state["tx_year"] = active_context["month"][:4]
        st.session_state["tx_pending_action"] = {
            "kind": "filters", "context": requested_context,
        }
    else:
        st.session_state["tx_month"] = target_month
        st.session_state["tx_year"] = target_month[:4]
        _reset_tx_editor()
        st.session_state["tx_active_context"] = None


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
            and page_name != "流水列表"
            and st.session_state.get("tx_dirty", False)):
        st.session_state["tx_pending_action"] = {"kind": "page", "page": page_name}
        return
    st.session_state["current_page"] = page_name


@st.dialog("修改流水")
def _render_single_edit_dialog(row: pd.Series) -> None:
    """渲染单条流水的预填修改表单。"""
    parsed_time = pd.to_datetime(row["时间"], errors="coerce")
    default_time = parsed_time.to_pydatetime() if not pd.isna(parsed_time) else datetime.now()

    with st.form("single_transaction_edit_form"):
        col1, col2 = st.columns(2)
        with col1:
            trade_time = st.datetime_input("交易时间", value=default_time)
            trade_type = st.selectbox("收支类型", TRADE_TYPES,
                                      index=TRADE_TYPES.index(_text_value(row["收支"])))
            amount = st.number_input("金额", min_value=0.01,
                                     value=max(abs(float(row["金额"])), 0.01),
                                     step=0.01, format="%.2f")
        with col2:
            platform = st.selectbox("来源", PLATFORMS,
                                    index=PLATFORMS.index(_text_value(row["来源"])))
            category = st.text_input("分类", value=_text_value(row["分类"]))
        description = st.text_input("说明", value=_text_value(row["说明"]))
        counterparty = st.text_input("交易对方", value=_text_value(row["对方"]))
        payment_channel = st.text_input("支付方式", value=_text_value(row["支付方式"]))

        save_col, cancel_col = st.columns(2)
        with save_col:
            submitted = st.form_submit_button("保存修改", type="primary", use_container_width=True)
        with cancel_col:
            cancelled = st.form_submit_button("取消", use_container_width=True)

    if cancelled:
        st.session_state["tx_single_edit_id"] = None
        st.rerun()
    if submitted:
        values = {
            "id": _text_value(row["记录ID"]),
            "trade_time": trade_time.strftime("%Y-%m-%d %H:%M:%S"),
            "platform": platform,
            "trade_type": trade_type,
            "amount": amount if trade_type == "收入" else -amount,
            "category": category.strip(),
            "description": description.strip(),
            "counterparty": counterparty.strip(),
            "payment_channel": payment_channel.strip(),
        }
        try:
            db.update_transaction(
                values["id"],
                trade_time=values["trade_time"], platform=values["platform"],
                trade_type=values["trade_type"], amount=values["amount"],
                category=values["category"], description=values["description"],
                counterparty=values["counterparty"], payment_channel=values["payment_channel"],
            )
        except Exception as exc:
            st.error(f"保存失败：{exc}")
            return

        # 将已保存行写回基线；同页其他未保存表格编辑仍然保留。
        editor_df = st.session_state.get("tx_editor_current").copy()
        baseline = st.session_state.get("tx_baseline").copy()
        for frame in (editor_df, baseline):
            index = frame.index[frame["记录ID"] == values["id"]]
            if len(index):
                idx = index[0]
                frame.at[idx, "时间"] = pd.to_datetime(values["trade_time"])
                frame.at[idx, "来源"] = values["platform"]
                frame.at[idx, "收支"] = values["trade_type"]
                frame.at[idx, "金额"] = abs(values["amount"])
                frame.at[idx, "分类"] = values["category"]
                frame.at[idx, "说明"] = values["description"]
                frame.at[idx, "对方"] = values["counterparty"]
                frame.at[idx, "支付方式"] = values["payment_channel"]
        st.session_state["tx_baseline"] = baseline
        st.session_state["tx_editor_seed"] = editor_df
        st.session_state["tx_editor_version"] = st.session_state.get("tx_editor_version", 0) + 1
        st.session_state["tx_single_edit_id"] = None
        st.session_state["tx_dirty"] = bool(_get_changed_editor_rows(editor_df))
        st.session_state["tx_notice"] = "流水已修改。"
        st.rerun()


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


def _render_platform_pie(month: str) -> None:
    """本月支出来源分布（数据由 SQL 聚合）。"""
    stats = db.get_platform_stats(month)
    if not stats:
        st.info("本月暂无支出记录。")
        return

    df = pd.DataFrame(stats)
    fig = px.pie(
        df, names="platform", values="total", hole=0.45,
        title=f"{month} 支出来源",
        color="platform",
        color_discrete_map={"支付宝": "#1677ff", "微信": "#07c160", "手动录入": "#f59e0b"},
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=400)
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# 页面：仪表盘
# ══════════════════════════════════════════════════════════════════════════

def page_dashboard() -> None:
    st.title("📊 仪表盘")

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

    st.selectbox(
        "年份", years,
        key="dashboard_year",
        format_func=lambda year: f"{year}年",
        on_change=_request_dashboard_year_change,
    )

    selected_year = st.session_state["dashboard_year"]
    selected_month = st.session_state["dashboard_month"]
    st.caption("月份")
    for start_month in (1, 7):
        month_columns = st.columns(6)
        for offset, column in enumerate(month_columns):
            month_number = start_month + offset
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
    _render_stat_cards(selected_month)

    st.divider()
    _render_monthly_trend()

    col1, col2 = st.columns(2)
    with col1:
        _render_category_pie(selected_month)
    with col2:
        _render_platform_pie(selected_month)


# ══════════════════════════════════════════════════════════════════════════
# 页面：流水列表
# ══════════════════════════════════════════════════════════════════════════

def page_transactions() -> None:
    st.title("📋 流水列表")

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
    # 清理旧版本分页控件留下的会话状态。
    st.session_state.pop("tx_page", None)
    if "tx_search" not in st.session_state:
        st.session_state["tx_search"] = ""

    col1, col2 = st.columns([1, 2])
    with col1:
        st.selectbox(
            "年份", years,
            key="tx_year",
            format_func=lambda year: f"{year}年",
            on_change=_request_tx_year_change,
        )
    with col2:
        keyword = st.text_input("搜索（说明/分类/对方）", key="tx_search",
                                on_change=_request_tx_filter_change)

    selected_year = st.session_state["tx_year"]
    selected_month = st.session_state["tx_month"]
    st.caption("月份")
    for start_month in (1, 7):
        month_columns = st.columns(6)
        for offset, column in enumerate(month_columns):
            month_number = start_month + offset
            target_month = f"{selected_year}-{month_number:02d}"
            with column:
                st.button(
                    f"{month_number}月",
                    key=f"tx_month_button_{selected_year}_{month_number}",
                    type="primary" if target_month == selected_month else "secondary",
                    disabled=target_month not in months,
                    use_container_width=True,
                    on_click=_request_tx_month_change,
                    args=(target_month,),
                )

    context = {"month": selected_month, "keyword": keyword}
    if st.session_state.get("tx_active_context") != context:
        # 没有脏数据的筛选变化会在回调中重置编辑器；首次进入同样在此建立基线。
        if not st.session_state.get("tx_dirty", False):
            _reset_tx_editor()
        st.session_state["tx_active_context"] = context

    rows, total = db.query_transactions(selected_month, page_size=None, keyword=keyword)

    st.caption(f"共 {total} 条记录")

    if not rows:
        st.info("当前条件下没有记录。")
        return

    database_df = _rows_to_editor_df(rows)
    if st.session_state.get("tx_baseline") is None:
        st.session_state["tx_baseline"] = database_df.copy(deep=True)
    editor_source = st.session_state.pop("tx_editor_seed", None)
    if editor_source is None:
        editor_source = st.session_state["tx_baseline"].copy(deep=True)

    editor_df = st.data_editor(
        editor_source,
        use_container_width=True,
        hide_index=True,
        key=f"tx_editor_{st.session_state.get('tx_editor_version', 0)}",
        disabled=["记录ID"],
        column_config={
            "记录ID": None,
            "选择": st.column_config.CheckboxColumn("选择", default=False),
            "时间": st.column_config.DatetimeColumn("时间", format="YYYY-MM-DD HH:mm:ss"),
            "来源": st.column_config.SelectboxColumn("来源", options=PLATFORMS, required=True),
            "收支": st.column_config.SelectboxColumn("收支", options=TRADE_TYPES, required=True),
            "金额": st.column_config.NumberColumn("金额", min_value=0.01, step=0.01,
                                                     format="¥%.2f", required=True),
            "分类": st.column_config.TextColumn("分类"),
            "说明": st.column_config.TextColumn("说明"),
            "对方": st.column_config.TextColumn("对方"),
            "支付方式": st.column_config.TextColumn("支付方式"),
        },
    )
    st.session_state["tx_editor_current"] = editor_df.copy(deep=True)
    changed_rows = _get_changed_editor_rows(editor_df)
    st.session_state["tx_dirty"] = bool(changed_rows)
    selected_df = editor_df[editor_df["选择"].fillna(False).astype(bool)]
    selected_count = len(selected_df)

    if selected_count:
        st.caption(f"已选中 {selected_count} 行")
    if st.session_state.get("tx_notice"):
        st.success(st.session_state.pop("tx_notice"))

    all_selected = selected_count == len(editor_df)
    select_all_label = "取消全选" if all_selected else "全选"
    if st.button(select_all_label, use_container_width=True, type="secondary"):
        selected_editor_df = editor_df.copy(deep=True)
        selected_editor_df["选择"] = not all_selected
        # 重建编辑器以同步所有复选框，同时保留表格中尚未保存的业务编辑。
        st.session_state["tx_editor_seed"] = selected_editor_df
        st.session_state["tx_editor_version"] = st.session_state.get("tx_editor_version", 0) + 1
        st.rerun()

    edit_col, save_col, undo_col, delete_col = st.columns(4)
    with edit_col:
        edit_selected = st.button("✏️ 修改选中行", type="primary" if selected_count == 1 else "secondary",
                                  use_container_width=True,
                                  disabled=selected_count != 1)
    with save_col:
        save_changes = st.button("💾 保存修改", type="primary", use_container_width=True,
                                 disabled=not changed_rows)
    with undo_col:
        undo_changes = st.button("↩️ 撤销修改", type="primary" if changed_rows else "secondary",
                                 use_container_width=True,
                                 disabled=not changed_rows)
    with delete_col:
        delete_selected = st.button("🗑️ 删除选中行", use_container_width=True,
                                    disabled=selected_count == 0 or bool(changed_rows))

    if edit_selected:
        st.session_state["tx_single_edit_id"] = _text_value(selected_df.iloc[0]["记录ID"])

    if save_changes:
        ok, message = _save_editor_changes()
        if ok:
            st.session_state["tx_notice"] = message
            st.rerun()
        st.error(message)

    if undo_changes:
        _reset_tx_editor()
        st.session_state["tx_notice"] = "已撤销未保存的修改。"
        st.rerun()

    if delete_selected:
        deleted = 0
        for transaction_id in selected_df["记录ID"].tolist():
            if db.delete_transaction(transaction_id):
                deleted += 1
        _reset_tx_editor()
        st.session_state["tx_notice"] = f"已删除 {deleted} 条记录。"
        st.rerun()

    edit_id = st.session_state.get("tx_single_edit_id")
    if edit_id:
        selected_row = editor_df.loc[editor_df["记录ID"] == edit_id]
        if not selected_row.empty:
            _render_single_edit_dialog(selected_row.iloc[0])
        else:
            st.session_state["tx_single_edit_id"] = None


def page_import() -> None:
    st.title("📥 导入账单")
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
                    st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)
                if excluded_rows:
                    with st.expander(f"支付宝自动过滤记录 ({len(excluded_rows)} 条)"):
                        st.dataframe(pd.DataFrame(excluded_rows), use_container_width=True, hide_index=True)
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
                    st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)
                if excluded_rows:
                    with st.expander(f"微信自动过滤记录 ({len(excluded_rows)} 条)"):
                        st.dataframe(pd.DataFrame(excluded_rows), use_container_width=True, hide_index=True)
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
        with st.expander(f"📋 历史自动过滤记录 ({len(st.session_state["excluded_records"])} 条)", expanded=True):
            st.dataframe(pd.DataFrame(st.session_state["excluded_records"]), use_container_width=True, hide_index=True)
            st.caption("以下记录已被自动过滤未导入，如发现误排除请手动补录。")
        if st.button("🗑️ 清除过滤记录", use_container_width=True, type="secondary"):
            st.session_state["excluded_records"] = []
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════
# 页面：手动记账
# ══════════════════════════════════════════════════════════════════════════

def page_manual() -> None:
    st.title("✏️ 手动记账")

    with st.form("manual_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            entry_date = st.date_input("日期", value=date.today())
            trade_type = st.selectbox("收支类型", TRADE_TYPES)
            amount = st.number_input("金额", min_value=0.01, value=0.01, step=0.01, format="%.2f")
        with col2:
            platform = st.selectbox("来源", PLATFORMS)
            category = st.selectbox("分类", CATEGORIES, index=CATEGORIES.index("其他") if "其他" in CATEGORIES else 0)
        description = st.text_input("说明", placeholder="例如：午餐、地铁通勤...")
        counterparty = st.text_input("交易对方", placeholder="例如：美团、滴滴...")
        payment_channel = st.text_input("支付方式", placeholder="例如：余额宝、零钱通...")

        submitted = st.form_submit_button("保存记录", type="primary", use_container_width=True)
        if submitted:
            try:
                ok = p.import_manual_entry(
                    trade_time=entry_date.strftime("%Y-%m-%d 00:00:00"),
                    platform=platform,
                    trade_type=trade_type,
                    amount=amount,
                    category=category,
                    description=description,
                    counterparty=counterparty,
                    payment_channel=payment_channel,
                )
                if ok:
                    st.success("记录已保存！")
                else:
                    st.warning("该记录可能已存在（重复），未重复添加。")
            except Exception as exc:
                st.error(f"保存失败：{exc}")


# ══════════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════════

def main() -> None:
    pages = {
        "仪表盘": page_dashboard,
        "流水列表": page_transactions,
        "导入账单": page_import,
        "手动记账": page_manual,
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
        for page_name in pages:
            if st.button(page_name, use_container_width=True,
                         type="primary" if st.session_state["current_page"] == page_name else "secondary"):
                _request_page_change(page_name)
                st.rerun()

    pages[st.session_state["current_page"]]()


if __name__ == "__main__":
    main()
