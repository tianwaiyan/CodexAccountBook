"""个人记账系统 —— Streamlit 前端。

页面：仪表盘 / 流水列表 / 导入账单 / 手动记账。
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

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
PAGE_SIZE = 50
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
    selected_month = st.selectbox(
        "选择月份", months,
        index=months.index(current_month) if current_month in months else 0,
        key="dashboard_month",
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

    months = db.get_available_months()
    if not months:
        st.info("还没有任何交易记录。")
        return

    current_month = datetime.now().strftime("%Y-%m")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        selected_month = st.selectbox(
            "月份", months,
            index=months.index(current_month) if current_month in months else 0,
            key="tx_month",
        )
    with col2:
        page = st.number_input("页码", min_value=1, value=1, key="tx_page")
    with col3:
        keyword = st.text_input("搜索（说明/分类/对方）", key="tx_search")

    rows, total = db.query_transactions(selected_month, page=page, page_size=PAGE_SIZE, keyword=keyword)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    st.caption(f"共 {total} 条记录，第 {page}/{total_pages} 页")

    if not rows:
        st.info("当前条件下没有记录。")
        return

    df = pd.DataFrame(rows)
    df_display = df.rename(columns={
        "trade_time": "时间",
        "platform": "来源",
        "trade_type": "收支",
        "amount": "金额",
        "category": "分类",
        "description": "说明",
        "counterparty": "对方",
        "payment_channel": "支付方式",
    })
    df_display["金额"] = df_display["金额"].apply(lambda x: f"¥{x:,.2f}")
    df_display = df_display[["时间", "来源", "收支", "金额", "分类", "说明", "对方", "支付方式"]]

    # 删除计数器 — 用于重置表格选择状态
    if "tx_del_counter" not in st.session_state:
        st.session_state["tx_del_counter"] = 0

    # 带行选择的数据表格（动态 key，删除后重建）
    selection_event = st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        height=600,
        selection_mode="multi-row",
        on_select="rerun",
        key=f"tx_table_{st.session_state.tx_del_counter}",
    )

    # 获取选中的行索引
    selected_rows = getattr(getattr(selection_event, "selection", None), "rows", [])

    # 选中提示
    if selected_rows:
        st.caption(f"已选中 {len(selected_rows)} 行")

    # 删除按钮 — 始终可见，无勾选时禁用
    if st.button("🗑️ 删除选中行", type="primary", disabled=len(selected_rows) == 0):
        deleted = 0
        for idx in sorted(selected_rows, reverse=True):
            if idx < len(rows):
                if db.delete_transaction(rows[idx]["id"]):
                    deleted += 1
        if deleted > 0:
            st.session_state["tx_del_counter"] += 1
            st.rerun()


def page_import() -> None:
    st.title("📥 导入账单")

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
                inserted, skipped, preview = p.import_csv_to_db(alipay_file, "支付宝")
                total_inserted += inserted
                total_skipped += skipped
                st.success(f"支付宝：新增 {inserted} 条，跳过 {skipped} 条（重复）")
                with st.expander("预览支付宝导入记录"):
                    st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"支付宝导入失败：{exc}")

        if wechat_file is not None:
            try:
                inserted, skipped, preview = p.import_csv_to_db(wechat_file, "微信")
                total_inserted += inserted
                total_skipped += skipped
                st.success(f"微信：新增 {inserted} 条，跳过 {skipped} 条（重复）")
                with st.expander("预览微信导入记录"):
                    st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)
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

    with st.sidebar:
        st.title("个人记账系统")
        st.caption(f"数据库：{db.DB_PATH.name}")
        total_count = db.get_all_transactions_count()
        st.caption(f"总记录数：{total_count:,}")

        st.divider()
        for page_name in pages:
            if st.button(page_name, use_container_width=True,
                         type="primary" if st.session_state["current_page"] == page_name else "secondary"):
                st.session_state["current_page"] = page_name
                st.rerun()

    pages[st.session_state["current_page"]]()


if __name__ == "__main__":
    main()
