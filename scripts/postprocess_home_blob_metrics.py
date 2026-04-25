# -*- coding: utf-8 -*-
"""
将 run_template_trial 导出的 home_metrics_blob 长文，后处理为三项结构化指标：
- home_user_pay_amount（用户支付金额）
- home_deal_order_count（成交订单数）
- home_avg_order_value（客单价，缺失时=金额/单数）

罗盘首页文案常为「主卡一行 + 昨日一行 + 同行…」；数值提取与 fill_compass_metrics_from_blob 一致：
**优先取各指标块内「昨日」行后的数值**（例如用户支付金额主卡 ¥87.77、昨日 ¥891.53 → 取 891.53）。

输入 Excel 需包含列：店铺名、键、标签、数据值。
"""

import argparse
import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from operation_kanban_layout import merge_pipeline

def _parse_cn_number_token(raw: str) -> Optional[float]:
    s = (raw or "").strip()
    if not s:
        return None
    m = re.match(r"^([0-9][0-9,]*(?:\.[0-9]+)?)(万|亿)?$", s)
    if not m:
        return None
    num_s, unit = m.groups()
    try:
        v = float(num_s.replace(",", ""))
    except ValueError:
        return None
    if unit == "万":
        v *= 10000.0
    elif unit == "亿":
        v *= 100000000.0
    return v


def _fmt_decimal(v: float, digits: int = 2) -> str:
    s = f"{float(v):.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _extract_home_blob_metrics(blob_text: str) -> dict:
    """与 fill_compass_metrics_from_blob 同源逻辑：优先「昨日」行。"""
    out = {
        "home_user_pay_amount": "",
        "home_deal_order_count": "",
        "home_avg_order_value": "",
    }
    blob = blob_text or ""
    if not blob.strip():
        return out

    from fill_compass_metrics_from_blob import (
        compute_aov,
        extract_avg_order_from_blob,
        extract_pay_and_orders_from_blob,
    )

    pay_amount, order_count = extract_pay_and_orders_from_blob(blob)
    avg_order = extract_avg_order_from_blob(blob)
    if avg_order is None:
        avg_order = compute_aov(pay_amount, order_count)

    if pay_amount is not None:
        out["home_user_pay_amount"] = _fmt_decimal(float(pay_amount), 2)
    if order_count is not None:
        out["home_deal_order_count"] = _fmt_decimal(float(order_count), 0)
    if avg_order is not None:
        out["home_avg_order_value"] = _fmt_decimal(float(avg_order), 2)
    return out


def _upsert_metric_rows(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    required_cols = ["店铺名", "键", "标签", "数据值"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"缺少必需列: {c}")

    key_to_label = {
        "home_user_pay_amount": "用户支付金额",
        "home_deal_order_count": "成交订单数",
        "home_avg_order_value": "客单价",
    }

    write_count = 0
    blobs = df[df["键"].astype(str) == "home_metrics_blob"]
    if blobs.empty:
        return df, write_count

    for _, row in blobs.iterrows():
        shop = str(row.get("店铺名") or "").strip()
        blob = str(row.get("数据值") or "")
        parsed = _extract_home_blob_metrics(blob)
        for k, label in key_to_label.items():
            v = (parsed.get(k) or "").strip()
            if not v:
                continue
            mask = (df["店铺名"].astype(str) == shop) & (df["键"].astype(str) == k)
            if mask.any():
                df.loc[mask, "标签"] = label
                df.loc[mask, "数据值"] = v
            else:
                df = pd.concat(
                    [
                        df,
                        pd.DataFrame(
                            [{"店铺名": shop, "键": k, "标签": label, "数据值": v}]
                        ),
                    ],
                    ignore_index=True,
                )
            write_count += 1
    return df, write_count


def process_excel_bytes(file_bytes: bytes) -> Tuple[pd.DataFrame, int, pd.DataFrame]:
    """
    供 CLI / Streamlit 调用：
    1）长表内 home_metrics_blob 拆成三项罗盘指标；
    2）再合并为 doc/抖音与拼多多运营看板数据模板.xlsx 同结构的宽表（每店铺一行）。

    返回：(长表, 更新条数, 运营看板宽表)
    """
    df = pd.read_excel(io.BytesIO(file_bytes))
    df_long, n = _upsert_metric_rows(df)
    df_kanban = merge_pipeline(df_long)
    return df_long, n, df_kanban


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """将 DataFrame 写成 .xlsx 字节流（供浏览器下载）。"""
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def default_download_filename() -> str:
    """默认下载文件名：当天日期_抖音店铺指标.xlsx"""
    return f"{date.today().strftime('%Y%m%d')}_抖音店铺指标.xlsx"


def _default_output_path(excel_in: Path) -> Path:
    """未指定 --out 时：与输入同目录，文件名 当天日期 + 抖音店铺指标.xlsx；同名已存在则加时分秒后缀。"""
    today = date.today().strftime("%Y%m%d")
    parent = excel_in.parent
    base = f"{today}_抖音店铺指标.xlsx"
    out = parent / base
    if out.is_file() and out.resolve() != excel_in.resolve():
        out = parent / f"{today}_抖音店铺指标_{datetime.now().strftime('%H%M%S')}.xlsx"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="后处理 home_metrics_blob 为三项结构化指标")
    parser.add_argument("--excel", type=Path, required=True, help="输入 Excel 路径")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出 Excel 路径；不传则自动生成：与输入同目录下的「当天日期_抖音店铺指标.xlsx」",
    )
    args = parser.parse_args()

    excel_in = args.excel
    excel_out = args.out if args.out is not None else _default_output_path(excel_in)
    if not excel_in.is_file():
        raise FileNotFoundError(f"文件不存在: {excel_in}")

    raw = excel_in.read_bytes()
    _long, n, out_kanban = process_excel_bytes(raw)
    out_kanban.to_excel(excel_out, index=False)
    print(
        f"已写入运营看板格式: {excel_out.resolve()}（blob 拆分更新 {n} 条；店铺 {len(out_kanban)} 行）"
    )
    # 供控制台客户交付步骤解析：与输入采集表路径可能不同，须单独一行、无前缀。
    print(f"__FFF2_POSTPROCESS_OUTPUT_EXCEL__{excel_out.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
