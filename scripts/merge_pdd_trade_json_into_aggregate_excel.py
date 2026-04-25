"""
将 queryMallTradeList 落盘 JSON 中的「昨日」行（stateDate=yday）的成交金额/订单数/支付转化率
合并写入试运行汇总 Excel（店铺名、键、标签、数据值）。

优先：result.dayList 或全树中第一条 stateDate 与 --yday 一致的行。
可选：若 dayList 为空且仅有 todayRtList（stateDate 全为 null），可用 --today-rt-hour 取指定小时行（如 01 对应示例 JSON 第 34–35 行附近）。

用法示例：
  python scripts/merge_pdd_trade_json_into_aggregate_excel.py ^
    --json output/crawl/拼多多数据提取_1_2026-04-16/network_capture/queryMallTradeList_2026-04-16_pdd_trade_data_operation.json ^
    --excel output/crawl/拼多多数据提取_1_2026-04-16/拼多多数值提取_20260417.xlsx ^
    --yday 2026-04-15 ^
    --today-rt-hour 01
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd

METRICS = (
    ("pdd_trade_amount", "成交金额", "payOrdrAmt"),
    ("pdd_trade_order_count", "成交订单数", "payOrdrCnt"),
    ("pdd_trade_pay_uv_rto", "支付转化率", "payUvRto"),
)


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_row_by_state_date(obj: Any, yday: str, date_field: str = "stateDate") -> Optional[dict]:
    td = (yday or "").strip()[:10]
    if len(td) < 8:
        return None
    hit: list = []

    def walk(n: Any) -> None:
        if hit:
            return
        if isinstance(n, list):
            for it in n:
                if hit:
                    return
                if isinstance(it, dict):
                    dv = it.get(date_field)
                    if dv is not None:
                        ds = str(dv).strip()[:10]
                        if ds == td:
                            hit.append(it)
                            return
                walk(it)
        elif isinstance(n, dict):
            for v in n.values():
                walk(v)

    walk(obj)
    return hit[0] if hit else None


def _find_today_rt_hour(obj: Any, hr: str) -> Optional[dict]:
    """在 result.todayRtList 中取 hr 字段等于指定两位字符串的行。"""
    h = str(hr or "").strip().zfill(2)[:2]
    root = obj
    if isinstance(root, dict) and "result" in root and isinstance(root["result"], dict):
        root = root["result"]
    tl = None
    if isinstance(root, dict):
        tl = root.get("todayRtList")
    if not isinstance(tl, list):
        return None
    for it in tl:
        if not isinstance(it, dict):
            continue
        if str(it.get("hr") or "").strip().zfill(2)[:2] == h:
            return it
    return None


def _save_excel_with_fallback(path: Path, df: pd.DataFrame) -> Path:
    """
    先写临时 xlsx，再 os.replace 覆盖目标。
    若目标被 WPS/Excel 占用（WinError 5），则写入同目录「原名_已写入_时间戳.xlsx」，保证数据不丢。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.stem + ".tmp" + path.suffix)
    ts = time.strftime("%Y%m%d_%H%M%S")
    alt = path.parent / (path.stem + "_已写入_" + ts + path.suffix)

    def _cleanup_t() -> None:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass

    try:
        df.to_excel(tmp, index=False, engine="openpyxl")
    except Exception:
        _cleanup_t()
        try:
            df.to_excel(alt, index=False, engine="openpyxl")
            return alt
        except Exception:
            raise

    try:
        os.replace(tmp, path)
        return path
    except (OSError, PermissionError):
        try:
            os.replace(tmp, alt)
            return alt
        except Exception:
            try:
                df.to_excel(alt, index=False, engine="openpyxl")
            finally:
                _cleanup_t()
            return alt


def _fmt_val(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return str(v) if v == v else ""
    if isinstance(v, int):
        return str(v)
    return str(v).strip()


def run(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="合并 queryMallTradeList JSON 指标到拼多多数值提取 xlsx")
    p.add_argument("--json", required=True, type=Path, help="queryMallTradeList 落盘 JSON 路径")
    p.add_argument("--excel", required=True, type=Path, help="汇总 xlsx 路径")
    p.add_argument(
        "--yday",
        required=True,
        help="统计「昨日」日期 YYYY-MM-DD（与采集模板 yday 一致，用于匹配 stateDate）",
    )
    p.add_argument(
        "--today-rt-hour",
        default="",
        help="无 stateDate 命中时，从 todayRtList 取该小时行（两位，如 01）",
    )
    p.add_argument(
        "--shops",
        default="",
        help="逗号分隔店铺名；省略则写入 Excel 中全部不重复店铺名（同一套数值复制到各店，请自行核对是否适用）",
    )
    p.add_argument(
        "--no-replace-keys",
        action="store_true",
        help="不在写入前删除本脚本涉及的键（默认会先删掉各店下 pdd_trade_* 旧行再追加，避免重复）",
    )
    args = p.parse_args(argv)

    jpath = args.json
    if not jpath.is_file():
        print(f"找不到 JSON: {jpath}", file=sys.stderr)
        return 1
    xlsx = args.excel

    data = _load_json(jpath)
    row = _find_row_by_state_date(data, args.yday)
    mode = "stateDate"
    if row is None and str(args.today_rt_hour or "").strip():
        row = _find_today_rt_hour(data, args.today_rt_hour)
        mode = f"todayRtList hr={str(args.today_rt_hour).strip().zfill(2)[:2]}"
    if not isinstance(row, dict):
        print(
            "未找到可用数据行：请确认 JSON 内有 stateDate 与 --yday 一致的 dayList 行，"
            "或传入 --today-rt-hour 使用分时 todayRtList。",
            file=sys.stderr,
        )
        return 1

    keys = [m[2] for m in METRICS]
    missing = [k for k in keys if k not in row]
    if missing:
        print(f"警告：行内缺少字段 {missing}，仍将写出空字符串", file=sys.stderr)

    cols = ["店铺名", "键", "标签", "数据值"]
    if xlsx.is_file():
        df = pd.read_excel(xlsx, engine="openpyxl")
    else:
        df = pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df.reindex(columns=cols)

    if str(args.shops or "").strip():
        shops = [s.strip() for s in str(args.shops).split(",") if s.strip()]
    else:
        shops = list(dict.fromkeys(df["店铺名"].dropna().astype(str).tolist()))
    if not shops:
        print(
            "无店铺名：请在已有数据的 xlsx 上运行，或用 --shops 店A,店B 指定（新文件须指定店铺）。",
            file=sys.stderr,
        )
        return 1

    new_rows: list = []
    metric_keys = [m[0] for m in METRICS]
    if not args.no_replace_keys:
        shop_set = set(shops)
        df = df[
            ~(
                (df["店铺名"].astype(str).isin(shop_set))
                & (df["键"].isin(metric_keys))
            )
        ]
    for shop in shops:
        for fkey, label, jk in METRICS:
            new_rows.append(
                {
                    "店铺名": shop,
                    "键": fkey,
                    "标签": label,
                    "数据值": _fmt_val(row.get(jk)),
                }
            )

    add = pd.DataFrame(new_rows)
    merged = pd.concat([df, add], ignore_index=True)
    written = _save_excel_with_fallback(xlsx, merged)
    if written.resolve() != xlsx.resolve():
        print(
            f"提示：原文件「{xlsx.name}」正被占用，完整结果已写入：\n  {written.resolve()}\n"
            f"关闭 WPS/Excel 后可将该文件改名为「{xlsx.name}」覆盖原文件，或复制内容。",
            file=sys.stderr,
        )
    print(
        f"已写入 {len(shops)} 店 × {len(METRICS)} 项（来源: {mode}）→ {written.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
