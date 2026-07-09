from __future__ import annotations

from io import BytesIO
from typing import BinaryIO

import pandas as pd
import plotly.express as px
import streamlit as st


STANDARD_COLUMNS = [
    "时间",
    "分类",
    "交易对方",
    "商品说明",
    "收支类型",
    "金额",
    "支付渠道",
    "来源",
]

ALIPAY_COLUMN_MAP = {
    "交易时间": "时间",
    "交易分类": "分类",
    "交易对方": "交易对方",
    "商品说明": "商品说明",
    "收/支": "收支类型",
    "金额": "金额",
    "收/付款方式": "支付渠道",
}

WECHAT_COLUMN_MAP = {
    "交易时间": "时间",
    "交易类型": "分类",
    "交易对方": "交易对方",
    "商品": "商品说明",
    "收/支": "收支类型",
    "金额(元)": "金额",
    "支付方式": "支付渠道",
}


def _reset_file(file: BinaryIO) -> None:
    """Move uploaded files back to the beginning before each read."""
    if hasattr(file, "seek"):
        file.seek(0)


def _read_csv(file: BinaryIO, *, encoding: str, skiprows: int, source_name: str) -> pd.DataFrame:
    _reset_file(file)
    try:
        return pd.read_csv(file, encoding=encoding, skiprows=skiprows, dtype=str)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source_name} 文件编码读取失败，请确认上传的是官方导出的 CSV 文件。") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"{source_name} 文件格式解析失败，请确认文件没有被手动改坏。") from exc


def _normalize_columns(df: pd.DataFrame, column_map: dict[str, str], source_name: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    missing_columns = [column for column in column_map if column not in df.columns]
    if missing_columns:
        missing = "、".join(missing_columns)
        raise ValueError(f"{source_name} 文件缺少必要列：{missing}")

    df = df[list(column_map.keys())].rename(columns=column_map)
    for column in df.columns:
        if df[column].dtype == "object":
            df[column] = df[column].astype(str).str.strip()

    return df


def parse_alipay(file: BinaryIO) -> pd.DataFrame:
    """Parse an Alipay CSV export into the unified transaction schema."""
    df = _read_csv(file, encoding="gb18030", skiprows=24, source_name="支付宝")
    df = _normalize_columns(df, ALIPAY_COLUMN_MAP, "支付宝")
    df["来源"] = "支付宝"
    return df[STANDARD_COLUMNS]


def parse_wechat(file: BinaryIO) -> pd.DataFrame:
    """Parse a WeChat Pay CSV export into the unified transaction schema."""
    df = _read_csv(file, encoding="utf-8", skiprows=16, source_name="微信")
    df = _normalize_columns(df, WECHAT_COLUMN_MAP, "微信")
    df["来源"] = "微信"
    return df[STANDARD_COLUMNS]


def _clean_amount_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    amount_text = (
        df["金额"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.replace("¥", "", regex=False)
        .str.replace("￥", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("元", "", regex=False)
        .str.replace(r"\s+", "", regex=True)
    )

    df["金额"] = pd.to_numeric(amount_text, errors="coerce")
    invalid_mask = df["金额"].isna() & amount_text.ne("")
    if invalid_mask.any():
        preview = "、".join(amount_text[invalid_mask].head(3).tolist())
        raise ValueError(f"金额列存在无法转换为数字的内容，请检查原始账单。示例：{preview}")

    return df


def merge_transactions(alipay_df: pd.DataFrame, wechat_df: pd.DataFrame) -> pd.DataFrame:
    merged = pd.concat([alipay_df, wechat_df], ignore_index=True)
    merged = _clean_amount_column(merged)

    merged["时间"] = pd.to_datetime(merged["时间"], errors="coerce")
    invalid_time_count = int(merged["时间"].isna().sum())
    if invalid_time_count:
        raise ValueError(f"有 {invalid_time_count} 条记录的时间无法识别，请检查原始 CSV 的交易时间列。")

    merged = merged.sort_values("时间", ascending=False).reset_index(drop=True)
    return merged[STANDARD_COLUMNS]


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl", datetime_format="yyyy-mm-dd hh:mm:ss") as writer:
        df.to_excel(writer, index=False, sheet_name="合并账单")
    output.seek(0)
    return output.getvalue()


def render_income_expense_chart(df: pd.DataFrame) -> None:
    summary = (
        df.dropna(subset=["金额"])
        .groupby("收支类型", as_index=False)["金额"]
        .sum()
        .sort_values("金额", ascending=False)
    )

    if summary.empty:
        st.info("暂无可用于收支统计的金额数据。")
        return

    st.subheader("收支金额汇总")
    st.bar_chart(summary, x="收支类型", y="金额")


def render_source_donut_chart(df: pd.DataFrame) -> None:
    expense_df = df[df["收支类型"].astype(str).str.contains("支出", na=False)]
    summary = (
        expense_df.dropna(subset=["金额"])
        .groupby("来源", as_index=False)["金额"]
        .sum()
        .sort_values("金额", ascending=False)
    )

    st.subheader("支出来源分布")
    if summary.empty:
        st.info("暂无支出记录，无法生成来源分布图。")
        return

    fig = px.pie(
        summary,
        names="来源",
        values="金额",
        hole=0.45,
        color="来源",
        color_discrete_map={"支付宝": "#1677ff", "微信": "#07c160"},
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(showlegend=True, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="账单合并分析器", page_icon="💳", layout="wide")

    st.title("账单合并分析器")
    st.caption("上传支付宝和微信导出的 CSV 账单，在本机完成清洗、合并、分析和 Excel 导出。")

    col1, col2 = st.columns(2)
    with col1:
        alipay_file = st.file_uploader("上传支付宝 CSV 文件", type=["csv"], key="alipay")
    with col2:
        wechat_file = st.file_uploader("上传微信 CSV 文件", type=["csv"], key="wechat")

    if st.button("合并并分析", type="primary", use_container_width=True):
        if alipay_file is None or wechat_file is None:
            st.error("请同时上传支付宝和微信 CSV 文件。")
            return

        try:
            alipay_df = parse_alipay(alipay_file)
            wechat_df = parse_wechat(wechat_file)
            merged_df = merge_transactions(alipay_df, wechat_df)
        except Exception as exc:
            st.error(f"处理失败：{exc}")
            return

        st.success(f"合并成功，共得到 {len(merged_df):,} 条交易记录。")

        st.subheader("合并结果预览")
        st.dataframe(merged_df.head(10), use_container_width=True, hide_index=True)

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            render_income_expense_chart(merged_df)
        with chart_col2:
            render_source_donut_chart(merged_df)

        excel_bytes = dataframe_to_excel_bytes(merged_df)
        st.download_button(
            label="下载合并后的 Excel 文件",
            data=excel_bytes,
            file_name="合并账单.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
