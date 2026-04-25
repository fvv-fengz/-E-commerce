# -*- coding: utf-8 -*-
"""
从 doc/scrape-template-jinritemai-v1.json 的 globalAccountLoop.accounts 读取店名，
生成「店铺 + 罗盘三项 + 千川三项」列的 Excel 空表（指标列留白，供手工填或对照采集结果）。

用法（项目根目录）:
  python scripts/generate_store_metrics_workbook.py
  python scripts/generate_store_metrics_workbook.py --out output/店铺罗盘千川指标表.xlsx
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = PROJECT_ROOT / "doc" / "scrape-template-jinritemai-v1.json"
DEFAULT_OUT = PROJECT_ROOT / "output" / "store_metrics_template.xlsx"

COLS = [
    "店铺",
    "罗盘支付金额",
    "罗盘成交订单数",
    "客单价",
    "千川消耗",
    "千川净成交订单数",
    "净成交roi",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成店铺×指标列 Excel 空表")
    ap.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help="模板 JSON 路径",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="输出 .xlsx 路径",
    )
    ns = ap.parse_args()
    tpl_path = ns.template
    if not tpl_path.is_file():
        print(f"找不到模板: {tpl_path}", file=sys.stderr)
        return 1
    raw = json.loads(tpl_path.read_text(encoding="utf-8"))
    gal = raw.get("globalAccountLoop") or {}
    accs = gal.get("accounts") or []
    names: list = []
    for x in accs:
        if isinstance(x, dict):
            n = str(x.get("name") or x.get("shopName") or "").strip()
            if n:
                names.append(n)
        elif isinstance(x, str) and x.strip():
            names.append(x.strip())
    if not names:
        print("模板中 globalAccountLoop.accounts 无店名", file=sys.stderr)
        return 1
    df = pd.DataFrame({COLS[0]: names})
    for c in COLS[1:]:
        df[c] = ""
    df = df[COLS]
    out_path = ns.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False, engine="openpyxl")
    print(f"已写入: {out_path.resolve()}（共 {len(names)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
