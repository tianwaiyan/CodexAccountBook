"""解析层：智能识别表头，兼容不同版本的支付宝/微信 CSV 和 XLSX 导出文件。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

import pandas as pd

import db

# ── 字段映射 ─────────────────────────────────────────────────────────
STANDARD_COLUMNS = [
    "trade_time",
    "platform",
    "trade_type",
    "amount",
    "category",
    "description",
    "counterparty",
    "payment_channel",
]

# 支付宝与微信都能识别的关键列名，用于智能定位表头行
ALIPAY_KEY_COLUMNS = {"交易时间", "交易分类", "金额", "收/支", "收/付款方式"}
WECHAT_KEY_COLUMNS = {"交易时间", "交易类型", "金额(元)", "收/支", "支付方式"}

ALIPAY_COLUMN_MAP = {
    "交易时间": "trade_time",
    "交易分类": "category_raw",
    "交易对方": "counterparty",
    "商品说明": "description",
    "收/支": "trade_type",
    "金额": "amount_raw",
    "收/付款方式": "payment_channel",
}

WECHAT_COLUMN_MAP = {
    "交易时间": "trade_time",
    "交易类型": "category_raw",
    "交易对方": "counterparty",
    "商品": "description",
    "收/支": "trade_type",
    "金额(元)": "amount_raw",
    "支付方式": "payment_channel",
}

# ── 分类归一化映射表 ────────────────────────────────────────────────
CATEGORY_MAP: dict[str, str] = {
    "餐饮美食": "餐饮", "饮食": "餐饮", "餐饮": "餐饮",
    "日用百货": "购物", "服饰美容": "购物", "电商购物": "购物", "商户消费": "购物", "商户支付": "购物",
    "交通出行": "交通", "交通": "交通",
    "生活服务": "生活", "生活缴费": "生活",
    "文化休闲": "娱乐", "休闲娱乐": "娱乐",
    "通讯": "通讯", "通讯物流": "通讯",
    "住房物业": "居住", "住房": "居住",
    "医疗健康": "医疗", "医疗": "医疗",
    "教育培训": "教育", "教育": "教育",
    "投资理财": "理财", "金融服务": "理财",
    "转账充值": "转账", "转账": "转账", "信用借贷": "转账",
    "退款": "退款",
    "红包": "红包", "微信红包": "红包", "微信红包往来": "红包",
    "微信通讯": "通讯", "微信转账": "转账",
    "其他": "其他",
    "扫二维码付款": "其他", "扫二维码付钱": "其他",
}


def normalize_category(raw_category: str) -> str:
    if not raw_category:
        return "其他"
    return CATEGORY_MAP.get(raw_category.strip(), raw_category.strip())


def generate_import_hash(row: dict) -> str:
    content = f"{row.get('trade_time','')}|{row.get('amount',0)}|{row.get('counterparty','')}|{row.get('description','')}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ── 文件类型检测 ────────────────────────────────────────────────────
def _file_extension(file: BinaryIO) -> str:
    if hasattr(file, "name"):
        return Path(file.name).suffix.lower()
    return ".csv"


def _is_xlsx(file: BinaryIO) -> bool:
    return _file_extension(file) in (".xlsx", ".xls")


# ── 智能表头定位 ────────────────────────────────────────────────────
def _find_header_row_csv(file: BinaryIO, encoding: str, key_columns: set[str], source_name: str, max_scan: int = 50) -> int:
    """扫描 CSV 前 max_scan 行，找到包含关键列名的行号。

    返回该行号（0-based），如果找不到则抛出异常。
    """
    _reset_file(file)
    try:
        raw = pd.read_csv(file, encoding=encoding, header=None, dtype=str, nrows=max_scan)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source_name} 文件编码读取失败，请确认上传的是官方导出的 CSV 文件。") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"{source_name} 文件格式解析失败，请确认文件没有被手动改坏。") from exc

    for row_idx in range(len(raw)):
        row_values = {str(v).strip() for v in raw.iloc[row_idx] if pd.notna(v)}
        # 至少匹配 3 个关键列就算找到表头
        if len(row_values & key_columns) >= 3:
            return row_idx

    raise ValueError(
        f"{source_name} 未能自动识别表头行（前 {max_scan} 行中未找到关键列名）。"
        f"关键列：{'/'.join(key_columns)}"
    )


def _find_header_row_xlsx(file: BinaryIO, key_columns: set[str], source_name: str, max_scan: int = 50) -> int:
    """扫描 Excel 前 max_scan 行，找到包含关键列名的行号。"""
    _reset_file(file)
    try:
        raw = pd.read_excel(file, header=None, dtype=str, nrows=max_scan)
    except Exception as exc:
        raise ValueError(f"{source_name} 文件格式解析失败，请确认上传的是官方导出的 Excel 文件。") from exc

    for row_idx in range(len(raw)):
        row_values = {str(v).strip() for v in raw.iloc[row_idx] if pd.notna(v)}
        if len(row_values & key_columns) >= 3:
            return row_idx

    raise ValueError(
        f"{source_name} 未能自动识别表头行（前 {max_scan} 行中未找到关键列名）。"
        f"关键列：{'/'.join(key_columns)}"
    )


# ── 通用读取 ────────────────────────────────────────────────────────
def _reset_file(file: BinaryIO) -> None:
    if hasattr(file, "seek"):
        file.seek(0)


def _read_csv_with_header(file: BinaryIO, encoding: str, skiprows: int, source_name: str) -> pd.DataFrame:
    """跳过元数据行后读取 CSV，表头在第一行。"""
    _reset_file(file)
    try:
        return pd.read_csv(file, encoding=encoding, skiprows=skiprows, dtype=str)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source_name} 文件编码读取失败，请确认上传的是官方导出的 CSV 文件。") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"{source_name} 文件格式解析失败，请确认文件没有被手动改坏。") from exc


def _read_excel_with_header(file: BinaryIO, skiprows: int, source_name: str) -> pd.DataFrame:
    """跳过元数据行后读取 Excel，表头紧接其后。"""
    _reset_file(file)
    try:
        return pd.read_excel(file, skiprows=skiprows, dtype=str)
    except Exception as exc:
        raise ValueError(f"{source_name} 文件格式解析失败，请确认上传的是官方导出的 Excel 文件。") from exc


def _normalize_columns(df: pd.DataFrame, column_map: dict[str, str], source_name: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.replace('\ufeff', '')

    missing_columns = [column for column in column_map if column not in df.columns]
    if missing_columns:
        missing = "、".join(missing_columns)
        if missing_columns:
            found = "、".join(df.columns) if len(df.columns) > 0 else "(no columns)"
            raise ValueError(
                f"{source_name} 文件缺少必要列：{missing}\n"
                f"已识别的列（共{len(df.columns)}列）：{found}\n"
                f"请确认上传的是支付宝/微信官方导出的原始文件。"
             )
    df = df[list(column_map.keys())].rename(columns=column_map)
    for column in df.columns:
        if df[column].dtype == "object":
            df[column] = df[column].astype(str).str.strip()

    return df


# ── 解析入口 ────────────────────────────────────────────────────────
def parse_alipay(file: BinaryIO) -> pd.DataFrame:
    """智能解析支付宝导出文件（支持 CSV 和 XLSX）。"""
    if _is_xlsx(file):
        header_row = _find_header_row_xlsx(file, ALIPAY_KEY_COLUMNS, "支付宝")
        df = _read_excel_with_header(file, skiprows=header_row, source_name="支付宝")
    else:
        header_row = _find_header_row_csv(file, "gb18030", ALIPAY_KEY_COLUMNS, "支付宝")
        df = _read_csv_with_header(file, "gb18030", skiprows=header_row, source_name="支付宝")

    df = _normalize_columns(df, ALIPAY_COLUMN_MAP, "支付宝")
    df["platform"] = "支付宝"
    return df


def parse_wechat(file: BinaryIO) -> pd.DataFrame:
    """智能解析微信导出文件（支持 CSV 和 XLSX）。"""
    if _is_xlsx(file):
        header_row = _find_header_row_xlsx(file, WECHAT_KEY_COLUMNS, "微信")
        df = _read_excel_with_header(file, skiprows=header_row, source_name="微信")
    else:
        header_row = _find_header_row_csv(file, "utf-8", WECHAT_KEY_COLUMNS, "微信")
        df = _read_csv_with_header(file, "utf-8", skiprows=header_row, source_name="微信")

    df = _normalize_columns(df, WECHAT_COLUMN_MAP, "微信")
    df["platform"] = "微信"
    return df


# ── 金额清洗 ─────────────────────────────────────────────────────────
def _clean_amount_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    amount_text = (
        df["amount_raw"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.replace("¥", "", regex=False)
        .str.replace("￥", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("元", "", regex=False)
        .str.replace(r"\s+", "", regex=True)
    )

    df["amount"] = pd.to_numeric(amount_text, errors="coerce")
    invalid_mask = df["amount"].isna() & amount_text.ne("")
    if invalid_mask.any():
        preview = "、".join(amount_text[invalid_mask].head(3).tolist())
        raise ValueError(f"金额列存在无法转换为数字的内容。示例：{preview}")

    return df


def _normalize_trade_type(raw_type: str) -> str:
    raw_type = str(raw_type).strip() if raw_type else ""
    if "支出" in raw_type or raw_type == "支":
        return "支出"
    if "收入" in raw_type or raw_type == "收":
        return "收入"
    if "不计收支" in raw_type or raw_type in ("/", "平", "不计"):
        return "不计收支"
    return "支出"


# ── 导入流程 ─────────────────────────────────────────────────────────

# Alipay auto-exclude: 余额宝 earnings, 花呗 auto-repay, bank scheduled transfer
ALIPAY_EXCLUDE_RULES = [
    lambda r: ("余额宝" in str(r.get("description", "")) and "收益" in str(r.get("description", ""))),
    lambda r: ("余额宝" in str(r.get("category_raw", "")) and "收益" in str(r.get("category_raw", ""))),
    lambda r: ("花呗" in str(r.get("counterparty", "")) and "还款" in str(r.get("description", ""))),
    lambda r: ("花呗" in str(r.get("description", "")) and "还款" in str(r.get("description", ""))),
    lambda r: ("定时转入" in str(r.get("description", ""))),
]

def _exclude_alipay_rows(rows):
    kept = []
    excluded_rows = []
    for row in rows:
        if any(rule(row) for rule in ALIPAY_EXCLUDE_RULES):
            excluded_rows.append(row)
        else:
            kept.append(row)
    return kept, excluded_rows


def _df_to_rows(df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for _, series in df.iterrows():
        trade_time_raw = series.get("trade_time", "")
        try:
            trade_time = pd.to_datetime(trade_time_raw).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            trade_time = str(trade_time_raw)

        amount_abs = float(series.get("amount", 0) or 0)
        raw_trade_type = str(series.get("trade_type", ""))
        trade_type = _normalize_trade_type(raw_trade_type)

        if trade_type == "收入":
            amount = abs(amount_abs)
        elif trade_type == "支出":
            amount = -abs(amount_abs)
        else:
            amount = amount_abs

        raw_category = str(series.get("category_raw", ""))
        category = normalize_category(raw_category)

        row = {
            "trade_time": trade_time,
            "platform": str(series.get("platform", "")),
            "trade_type": trade_type,
            "amount": amount,
            "category": category,
            "description": str(series.get("description", "")),
            "counterparty": str(series.get("counterparty", "")),
            "payment_channel": str(series.get("payment_channel", "")),
            "import_hash": "",
        }
        row["import_hash"] = generate_import_hash(row)
        rows.append(row)

    return rows


def import_csv_to_db(file: BinaryIO, platform: str) -> tuple[int, int, list[dict]]:
    # Read uploaded file bytes into BytesIO for robust handling with Streamlit
    import io
    file_bytes = file.read()
    buf = io.BytesIO(file_bytes)

    if platform == "支付宝":
        df = parse_alipay(buf)
    elif platform == "微信":
        df = parse_wechat(buf)
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    df = _clean_amount_column(df)
    rows = _df_to_rows(df)
    excluded_rows = []
    if platform == "支付宝":
        rows, excluded_rows = _exclude_alipay_rows(rows)
    inserted, skipped = db.insert_transactions(rows)
    preview = rows[:5]
    return inserted, skipped, excluded_rows, preview
def import_manual_entry(
    trade_time: str,
    platform: str,
    trade_type: str,
    amount: float,
    category: str,
    description: str = "",
    counterparty: str = "",
    payment_channel: str = "",
) -> bool:
    if trade_type == "支出":
        amount = -abs(amount)
    else:
        amount = abs(amount)

    row = {
        "trade_time": trade_time,
        "platform": platform,
        "trade_type": trade_type,
        "amount": amount,
        "category": category,
        "description": description,
        "counterparty": counterparty,
        "payment_channel": payment_channel,
        "import_hash": "",
    }
    row["import_hash"] = generate_import_hash(row)
    inserted, _ = db.insert_transactions([row])
    return inserted > 0
