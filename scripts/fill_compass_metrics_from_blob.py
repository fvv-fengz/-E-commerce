# -*- coding: utf-8 -*-
"""
从「抖店首页」整段 inner_text 样式的单元格中批量提取：
  - 用户支付金额、成交订单数、客单价
首页布局多为「主卡一行 + 昨日一行 + 同行…」：上述三项 **优先取该指标块内「昨日」行后的数值**（无主卡/昨日结构时回退为原正则，取主卡首值）。
客单价解析不到时仍可用 支付金额/成交订单数 推算，写入 output/店铺罗盘千川指标表.xlsx。

支持两种源表：
  1) blob：每行一店，一列为长文本（与首页复制/采集一致）
  2) trial：列含 店铺名、标签、数据值（与 template_trial 汇总类似），自动按标签透视再清洗

用法（项目根目录）:
  python scripts/fill_compass_metrics_from_blob.py
  （省略 --input 时自动选项目 output/ 下最新的 template_trial*.xlsx / template_trial_merged*.xlsx）
  python scripts/fill_compass_metrics_from_blob.py --input output/某表.xlsx
  python scripts/fill_compass_metrics_from_blob.py --input raw.xlsx --shop-col 店铺 --blob-col 首页文本
  python scripts/fill_compass_metrics_from_blob.py --input output/template_trial_merged_20260415.xlsx --mode merged
  默认只把「本次输入里出现过的店铺」写入 --out；若需与模板全量店名合并（旧行为）加 --merge-template-shops。

  run_template_trial：若模板根 aggregateExcelAutoCompassMetrics 为 true（如 doc/scrape-template-jinritemai-v1.json），
  试运行结束时会用内存长表调用 build_compass_metrics_from_trial_long_rows / write_compass_metrics_from_data_rows，
  与手动跑本脚本 merged 模式结果一致；加 --no-auto-compass-metrics 可关闭自动生成。
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "output" / "店铺罗盘千川指标表.xlsx"
DEFAULT_TEMPLATE = PROJECT_ROOT / "doc" / "scrape-template-jinritemai-v1.json"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _default_input_template_trial() -> Optional[Path]:
    """
    未指定 --input 时：取 output/ 下最新的抖店试运行采集表（按修改时间）。
    匹配 template_trial*.xlsx、template_trial_merged*.xlsx（不含临时锁文件 ~$）。
    """
    if not OUTPUT_DIR.is_dir():
        return None
    hits: List[Path] = []
    for pat in ("template_trial_merged*.xlsx", "template_trial*.xlsx"):
        for p in OUTPUT_DIR.glob(pat):
            if p.is_file() and not p.name.startswith("~$"):
                hits.append(p)
    if not hits:
        return None
    hits.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return hits[0]


def _resolve_input_path(raw: Optional[object]) -> Optional[Path]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    p = Path(s)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p

OUT_COLS = [
    "店铺",
    "罗盘支付金额",
    "罗盘成交订单数",
    "客单价",
    "千川消耗",
    "千川净成交订单数",
    "净成交roi",
]

# 抖店首页指标块边界：用于截取「某标签」到下一标签之间的文本，再在块内取「昨日」行后的数值
_HOME_METRIC_LABELS = (
    "成交金额",
    "用户支付金额",
    "结算金额",
    "客单价",
    "成交订单数",
    "商品曝光人数",
    "商品点击人数",
    "成交人数",
    "退款金额（退款时间）",
    "退款金额（支付时间）",
    "退款率（支付时间）",
    "成交退款金额（退款时间）",
    "退款订单数（退款时间）",
    "退款订单数（支付时间）",
    "商品曝光-点击转化率（人数）",
    "商品点击-成交转化率（人数）",
)


def _norm_shop(s: str) -> str:
    return (s or "").strip()


def _parse_money_cell(s: str) -> Optional[float]:
    """从可能含 ¥、逗号、汉字的单元格里取第一个金额数字。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    t = str(s).strip().replace(",", "")
    m = re.search(r"¥\s*([\d]+\.?[\d]*)", t)
    if not m:
        m = re.search(r"([\d]+\.?[\d]*)\s*元", t)
    if not m:
        m = re.search(r"^([\d]+\.?[\d]*)$", t)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_int_cell(s: str) -> Optional[int]:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    t = str(s).strip().replace(",", "")
    m = re.search(r"(\d+)", t)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _parse_cn_number_token(s: str) -> Optional[float]:
    """纯数字或带 万/亿 的中文数量（与 postprocess_home_blob_metrics 一致）。"""
    raw = (s or "").strip()
    if not raw:
        return None
    m = re.match(r"^([0-9][0-9,]*(?:\.[0-9]+)?)(万|亿)?$", raw)
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


def _parse_float_loose(s: str) -> Optional[float]:
    """纯数字、或文案中的第一个小数/整数。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    t = str(s).strip().replace(",", "").replace("，", "")
    if not t:
        return None
    try:
        if re.match(r"^-?[\d.]+\s*$", t):
            return float(t)
    except ValueError:
        pass
    m = re.search(r"-?[\d]+\.?[\d]*", t)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            pass
    return None


def _block_after_label(text: str, label: str) -> Optional[str]:
    """从 text 中 label 首次出现之后，截到下一个首页指标名之前（不含下一指标）。"""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    i = t.find(label)
    if i < 0:
        return None
    rest = t[i + len(label) :]
    end = len(rest)
    for m in _HOME_METRIC_LABELS:
        if m == label:
            continue
        j = rest.find("\n" + m)
        if j >= 0:
            end = min(end, j)
    return rest[:end]


def _first_nonempty_line_after(block: str, keyword: str) -> Optional[str]:
    """block 内 keyword 之后第一个非空行（keyword 为「昨日」时即取昨日对应那一行的下一行展示值）。"""
    if keyword not in block:
        return None
    sub = block[block.find(keyword) + len(keyword) :].strip()
    for line in sub.split("\n"):
        s = line.strip()
        if s:
            return s
    return None


def _parse_money_line(line: str) -> Optional[float]:
    v = _parse_money_cell(line)
    if v is not None:
        return float(v)
    return _parse_float_loose(line)


def _parse_by_kind(raw: object, kind: str) -> Optional[float]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw)
    if kind == "money":
        v = _parse_money_cell(s)
        if v is not None:
            return float(v)
        return _parse_float_loose(s)
    if kind == "avg_order":
        v = _parse_avg_order_value(raw)
        if v is not None:
            return float(v)
        v = _parse_money_cell(s)
        if v is not None:
            return float(v)
        return _parse_float_loose(s)
    if kind == "deal_orders":
        v = _parse_deal_order_count(raw)
        return v
    if kind == "int":
        v = _parse_int_cell(s)
        if v is not None:
            return float(v)
        return _parse_float_loose(s)
    if kind == "float":
        v = _parse_float_loose(s)
        return v
    return _parse_float_loose(s)


# template fields[].key -> (指标表列名, 解析类型)
_MERGED_KEY_MAP = {
    "home_user_pay_amount": ("罗盘支付金额", "money"),
    "home_deal_order_count": ("罗盘成交订单数", "deal_orders"),
    "home_avg_order_value": ("客单价", "avg_order"),
    "stat_cost_for_roi2": ("千川消耗", "float"),
    "total_order_settle_count_for_roi2_1h": ("千川净成交订单数", "float"),
    "total_prepay_and_pay_settle_roi2_1h": ("净成交roi", "float"),
}

def extract_pay_and_orders_from_blob(text: str) -> Tuple[Optional[float], Optional[int]]:
    """
    从首页大段文本中提取「用户支付金额」「成交订单数」。
    若块内存在「昨日」行，则优先取昨日行后的数值（与罗盘主卡「当日」区分）。
    """
    if not text or not isinstance(text, str):
        return None, None
    t = text.replace("\r\n", "\n")

    pay = None
    b_pay = _block_after_label(t, "用户支付金额")
    if b_pay and "昨日" in b_pay:
        line = _first_nonempty_line_after(b_pay, "昨日")
        if line:
            pay = _parse_money_line(line)

    if pay is None:
        for pat in (
            r"用户支付金额\s*\n\s*¥\s*([\d,]+\.?\d*)",
            r"用户支付金额[^\d¥]*¥\s*([\d,]+\.?\d*)",
        ):
            m = re.search(pat, t)
            if m:
                try:
                    pay = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass

    orders = None
    b_ord = _block_after_label(t, "成交订单数")
    if b_ord and "昨日" in b_ord:
        line = _first_nonempty_line_after(b_ord, "昨日")
        if line:
            v = _parse_cn_number_token(line.replace(",", ""))
            if v is not None:
                orders = int(v) if float(v).is_integer() else int(round(v))

    if orders is None:
        m = re.search(r"成交订单数\s*(\d+)", t)
        if m:
            try:
                orders = int(m.group(1))
            except ValueError:
                pass

    return pay, orders


def _parse_avg_order_value(raw: object) -> Optional[float]:
    """
    爬取块常见格式：优先「客单价」块内「昨日」行后的 ¥；否则主卡首行 ¥。
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).replace("\r\n", "\n").strip()
    if not s:
        return None
    b = _block_after_label(s, "客单价")
    if b and "昨日" in b:
        line = _first_nonempty_line_after(b, "昨日")
        if line:
            v = _parse_money_line(line)
            if v is not None:
                return v
    compact = s.replace(",", "").replace(" ", "").replace("\u3000", "")
    if re.match(r"^\d+\.?\d*$", compact):
        try:
            return float(compact)
        except ValueError:
            pass
    for pat in (
        r"客单价\s*\n\s*¥\s*([\d,]+\.?\d*)",
        r"客单价[^\d\n¥￥]*[¥￥]\s*([\d,]+\.?\d*)",
    ):
        m = re.search(pat, s)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def extract_avg_order_from_blob(text: str) -> Optional[float]:
    if not text or not isinstance(text, str):
        return None
    return _parse_avg_order_value(text.replace("\r\n", "\n"))


def _parse_deal_order_count(raw: object) -> Optional[float]:
    """
    「成交订单数」：优先块内「昨日」行后的数量；否则首行整数（主卡）。
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).replace("\r\n", "\n").strip()
    if not s:
        return None
    b = _block_after_label(s, "成交订单数")
    if b and "昨日" in b:
        line = _first_nonempty_line_after(b, "昨日")
        if line:
            v = _parse_cn_number_token(line.replace(",", ""))
            if v is not None:
                return float(v)
    compact = s.replace(",", "").replace(" ", "").replace("\u3000", "")
    if re.match(r"^\d{1,12}$", compact):
        try:
            return float(int(compact))
        except ValueError:
            pass
    m = re.search(r"成交订单数\s*(\d+)", s)
    if m:
        try:
            return float(int(m.group(1)))
        except ValueError:
            pass
    return None


def compute_aov(pay: Optional[float], orders: Optional[int]) -> Optional[float]:
    if pay is None or orders is None or orders <= 0:
        return None
    return round(pay / orders, 4)


def _parse_luopan_user_pay_raw(raw: object) -> Optional[float]:
    """
    「用户支付金额」单元格：常见为多行
      用户支付金额 / ¥主卡 / 昨日 / ¥昨日值
    须优先取「昨日」后一行（与 extract_pay_and_orders_from_blob 一致），不能取首个 ¥（主卡）。
    已为纯数字的单元格直接返回。
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    s = str(raw).strip()
    if not s:
        return None
    p, _ = extract_pay_and_orders_from_blob(s)
    if p is not None:
        return float(p)
    return _parse_money_cell(s)


def _load_template_shops() -> list:
    raw = json.loads(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    gal = raw.get("globalAccountLoop") or {}
    accs = gal.get("accounts") or []
    names = []
    for x in accs:
        if isinstance(x, dict):
            n = _norm_shop(str(x.get("name") or x.get("shopName") or ""))
            if n:
                names.append(n)
        elif isinstance(x, str) and x.strip():
            names.append(x.strip())
    return names


def _detect_blob_column(df: pd.DataFrame, name: Optional[str]) -> str:
    if name and name in df.columns:
        return name
    candidates = ("首页文本", "数据值", "inner_text", "blob", "首页", "raw", "文本")
    for c in candidates:
        if c in df.columns:
            return c
    # 取「平均非空最长」列（排除店名列）
    best, best_len = None, 0
    for c in df.columns:
        ser = df[c].dropna().astype(str)
        if ser.empty:
            continue
        avg = ser.str.len().mean()
        if avg > best_len and avg > 80:
            best_len = avg
            best = c
    if best:
        return str(best)
    raise SystemExit(
        "无法自动识别长文本列，请用 --blob-col 指定（当前列: %s）" % list(df.columns)
    )


def _detect_shop_column(df: pd.DataFrame, name: Optional[str]) -> str:
    if name and name in df.columns:
        return name
    for c in ("店铺名", "店铺", "账号", "店名", "name"):
        if c in df.columns:
            return c
    return str(df.columns[0])


def process_blob_sheet(df: pd.DataFrame, shop_col: str, blob_col: str) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        shop = _norm_shop(str(r.get(shop_col) or ""))
        if not shop:
            continue
        blob = r.get(blob_col)
        if pd.isna(blob):
            blob = ""
        pay, orders = extract_pay_and_orders_from_blob(str(blob))
        aov = extract_avg_order_from_blob(str(blob))
        if aov is None:
            aov = compute_aov(pay, orders)
        rows.append(
            {
                "店铺": shop,
                "罗盘支付金额": pay,
                "罗盘成交订单数": orders,
                "客单价": aov,
            }
        )
    return pd.DataFrame(rows)


def process_trial_style(df: pd.DataFrame) -> pd.DataFrame:
    """店铺名 + 标签 + 数据值：取 用户支付金额、成交订单数，必要时从数据值再解析。"""
    need = {"店铺名", "标签", "数据值"}.issubset(set(df.columns))
    alt = {"店铺", "标签", "数据值"}.issubset(set(df.columns))
    if not need and not alt:
        raise SystemExit("trial 模式需要列: 店铺名/店铺、标签、数据值")
    sc = "店铺名" if "店铺名" in df.columns else "店铺"
    sub = df[[sc, "标签", "数据值"]].copy()
    sub = sub.dropna(subset=[sc])
    sub["标签"] = sub["标签"].astype(str).str.strip()
    rows_out = []
    for shop, g in sub.groupby(sc):
        shop = _norm_shop(str(shop))
        m = {str(r["标签"]): r["数据值"] for _, r in g.iterrows()}
        pay = None
        orders = None
        aov = None
        # 抖店 v1：单字段 home_metrics_blob → 标签「经营概况整块文本」，直接按昨日解析三项
        blob_whole = None
        for bk in ("经营概况整块文本",):
            if bk in m and pd.notna(m.get(bk)):
                blob_whole = str(m[bk])
                break
        if blob_whole and blob_whole.strip():
            pay, orders = extract_pay_and_orders_from_blob(blob_whole)
            aov = extract_avg_order_from_blob(blob_whole)
            if orders is not None:
                orders = int(orders)
            if aov is None:
                aov = compute_aov(pay, orders)
            rows_out.append(
                {
                    "店铺": shop,
                    "罗盘支付金额": pay,
                    "罗盘成交订单数": orders,
                    "客单价": aov,
                }
            )
            continue

        if "用户支付金额" in m:
            pay = _parse_luopan_user_pay_raw(m["用户支付金额"])
        if "成交订单数" in m:
            orders = _parse_deal_order_count(m["成交订单数"])
            if orders is not None:
                orders = int(orders)
        if pay is None and "用户支付金额" in m:
            pay, _ = extract_pay_and_orders_from_blob(str(m["用户支付金额"]))
        if orders is None and "成交订单数" in m:
            _, orders = extract_pay_and_orders_from_blob(str(m["成交订单数"]))
        if pay is None or orders is None:
            blob = "\n".join(f"{k}\n{v}" for k, v in m.items() if pd.notna(v))
            p2, o2 = extract_pay_and_orders_from_blob(blob)
            if pay is None:
                pay = p2
            if orders is None:
                orders = o2
        aov = None
        if "客单价" in m:
            aov = _parse_avg_order_value(m["客单价"])
        if aov is None:
            blob_all = "\n".join(f"{k}\n{v}" for k, v in m.items() if pd.notna(v))
            aov = extract_avg_order_from_blob(blob_all)
        if aov is None:
            aov = compute_aov(pay, orders)
        rows_out.append(
            {
                "店铺": shop,
                "罗盘支付金额": pay,
                "罗盘成交订单数": orders,
                "客单价": aov,
            }
        )
    return pd.DataFrame(rows_out)


def _is_home_metrics_blob_row(field_key: str, lab: str) -> bool:
    """抖店简约模板：整页 inner_text 一条（键 home_metrics_blob / 标签 经营概况整块文本）。"""
    fk = (field_key or "").strip()
    lb = (lab or "").strip()
    if fk == "home_metrics_blob":
        return True
    if lb == "经营概况整块文本":
        return True
    if "经营概况" in lb and "文本" in lb:
        return True
    return False


def _merged_resolve_label(lab: str) -> Tuple[Optional[str], Optional[str]]:
    """标签 -> (指标表列, 解析类型)；与 scrape-template 中 fields[].label 对齐。"""
    if not lab:
        return None, None
    lab = lab.strip()
    if lab == "用户支付金额":
        return "罗盘支付金额", "money"
    if lab == "成交订单数":
        return "罗盘成交订单数", "deal_orders"
    if lab == "客单价":
        return "客单价", "avg_order"
    if "stat_cost_for_roi2" in lab:
        return "千川消耗", "float"
    if "total_order_settle_count_for_roi2_1h" in lab:
        return "千川净成交订单数", "float"
    if "total_prepay_and_pay_settle_roi2_1h" in lab:
        return "净成交roi", "float"
    return None, None


def process_merged_trial(df: pd.DataFrame) -> pd.DataFrame:
    """
    template_trial / template_trial_merged 长表：列含 店铺名、键、标签、数据值。
    按 fields[].key 映射到指标表；键未识别时用 标签 兜底。
    home_metrics_blob / 经营概况整块文本：整段文案内按「用户支付金额/成交订单数/客单价」块取「昨日」行后数值。
    """
    if "店铺名" not in df.columns or "数据值" not in df.columns:
        raise SystemExit("merged 模式需要列: 店铺名、数据值（及 键）")
    if "键" not in df.columns:
        df = df.copy()
        df["键"] = ""
    rows_out = []
    for shop, g in df.groupby(df["店铺名"].map(lambda x: _norm_shop(str(x)))):
        if not shop:
            continue
        out = {c: None for c in OUT_COLS}
        out["店铺"] = shop
        luopan_from_blob = False
        for _, r in g.iterrows():
            fk = str(r.get("键") or "").strip()
            lab = str(r.get("标签") or "").strip()
            val = r.get("数据值")
            if _is_home_metrics_blob_row(fk, lab):
                blob = str(val if pd.notna(val) else "")
                if blob.strip():
                    pay_b, orders_b = extract_pay_and_orders_from_blob(blob)
                    aov_b = extract_avg_order_from_blob(blob)
                    if pay_b is not None:
                        out["罗盘支付金额"] = float(pay_b)
                    if orders_b is not None:
                        out["罗盘成交订单数"] = int(orders_b)
                    if aov_b is not None:
                        out["客单价"] = float(aov_b)
                    luopan_from_blob = True
                continue

            col, kind = None, None
            if fk in _MERGED_KEY_MAP:
                col, kind = _MERGED_KEY_MAP[fk]
            else:
                col, kind = _merged_resolve_label(lab)
            if col and kind:
                if luopan_from_blob and col in (
                    "罗盘支付金额",
                    "罗盘成交订单数",
                    "客单价",
                ):
                    continue
                if col == "罗盘支付金额":
                    v = _parse_luopan_user_pay_raw(val)
                else:
                    v = _parse_by_kind(val, kind)
                if v is not None:
                    out[col] = v
        pay = out.get("罗盘支付金额")
        orders = out.get("罗盘成交订单数")
        if (
            out.get("客单价") is None
            and pay is not None
            and orders is not None
            and float(orders) > 0
        ):
            out["客单价"] = round(float(pay) / float(orders), 4)
        rows_out.append({k: out[k] for k in OUT_COLS})
    return pd.DataFrame(rows_out)


def merge_into_workbook(
    filled: pd.DataFrame,
    out_path: Path,
    template_shops: list,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.is_file():
        base = pd.read_excel(out_path, engine="openpyxl")
    else:
        base = pd.DataFrame({"店铺": template_shops})
        for c in OUT_COLS[1:]:
            base[c] = None

    for c in OUT_COLS:
        if c not in base.columns:
            base[c] = None
    base = base.reindex(columns=OUT_COLS)

    key_to_row: dict = {}
    for i, v in enumerate(base["店铺"].tolist()):
        k = _norm_shop(str(v))
        if k and k not in key_to_row:
            key_to_row[k] = i

    for _, fr in filled.iterrows():
        k = _norm_shop(str(fr.get("店铺") or ""))
        if not k:
            continue
        upd = {
            "罗盘支付金额": fr.get("罗盘支付金额"),
            "罗盘成交订单数": fr.get("罗盘成交订单数"),
            "客单价": fr.get("客单价"),
            "千川消耗": fr.get("千川消耗"),
            "千川净成交订单数": fr.get("千川净成交订单数"),
            "净成交roi": fr.get("净成交roi"),
        }
        if k in key_to_row:
            bi = key_to_row[k]
            for col, val in upd.items():
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    base.at[bi, col] = val
        else:
            new = {c: None for c in OUT_COLS}
            new["店铺"] = fr["店铺"]
            for col, val in upd.items():
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    new[col] = val
            base = pd.concat([base, pd.DataFrame([new])], ignore_index=True)
            key_to_row[k] = len(base) - 1

    base.to_excel(out_path, index=False, engine="openpyxl")


def write_only_input_shops(filled: pd.DataFrame, out_path: Path) -> None:
    """仅写出本次解析到的店铺行（不铺模板全量店名）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = filled.reindex(columns=OUT_COLS)
    for c in OUT_COLS:
        if c not in out.columns:
            out[c] = None
    out = out[OUT_COLS]
    out.to_excel(out_path, index=False, engine="openpyxl")


def build_compass_metrics_from_trial_long_rows(data_rows: List[Any]) -> pd.DataFrame:
    """
    与 run_template_trial 写入 Excel 前的采集长表等价（列：店铺名、键、标签、数据值），
    经 process_merged_trial 解析 home_metrics_blob 文案「昨日」三项并合并千川键，得到 OUT_COLS 宽表。
    """
    if not data_rows:
        return pd.DataFrame(columns=OUT_COLS)
    cols = ["店铺名", "键", "标签", "数据值"]
    df = pd.DataFrame(data_rows)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df.reindex(columns=cols)
    return process_merged_trial(df)


def write_compass_metrics_from_data_rows(
    data_rows: List[Any],
    out_path: Path,
    *,
    merge_template_shops: bool = False,
) -> Tuple[pd.DataFrame, Path]:
    """
    供 run_template_trial 在写完 template_trial*.xlsx 后调用：直接写店铺罗盘千川指标表（默认列见 OUT_COLS）。
    """
    filled = build_compass_metrics_from_trial_long_rows(data_rows)
    outp = Path(out_path)
    if not outp.is_absolute():
        outp = PROJECT_ROOT / outp
    if merge_template_shops:
        merge_into_workbook(filled, outp, _load_template_shops())
    else:
        write_only_input_shops(filled, outp)
    return filled, outp


def main() -> int:
    ap = argparse.ArgumentParser(description="从首页长文本提取罗盘三项并写入指标表")
    ap.add_argument(
        "--input",
        "-i",
        type=Path,
        default=None,
        help="源 Excel（.xlsx）；省略则自动使用 output/ 下最新的 template_trial*.xlsx 或 template_trial_merged*.xlsx",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="输出路径，默认 output/店铺罗盘千川指标表.xlsx",
    )
    ap.add_argument("--sheet", type=str, default=0, help="工作表名或下标，默认 0")
    ap.add_argument("--shop-col", type=str, default=None, help="店名列名，默认自动识别")
    ap.add_argument("--blob-col", type=str, default=None, help="长文本列名，默认自动识别")
    ap.add_argument(
        "--mode",
        choices=("auto", "blob", "trial", "merged"),
        default="auto",
        help="auto：有 键+数据值+店铺名 则 merged；否则有 标签+数据值 则 trial；否则 blob",
    )
    ap.add_argument(
        "--merge-template-shops",
        action="store_true",
        help="写入时与 doc/scrape-template-jinritemai-v1.json 中的店铺列表合并（旧行为）；默认仅输出本次输入里出现的店铺",
    )
    ns = ap.parse_args()
    inp = _resolve_input_path(ns.input)
    if inp is None:
        auto = _default_input_template_trial()
        if auto is None:
            print(
                "请指定 --input，或先将抖店采集结果保存为 output/template_trial*.xlsx",
                file=sys.stderr,
            )
            return 1
        inp = auto
        print(f"[自动输入] {inp.resolve()}", file=sys.stderr)
    elif not inp.is_file():
        print(f"找不到文件: {inp}", file=sys.stderr)
        return 1

    df = pd.read_excel(inp, sheet_name=ns.sheet, engine="openpyxl")
    mode = ns.mode
    if mode == "auto":
        sc = "店铺名" if "店铺名" in df.columns else ("店铺" if "店铺" in df.columns else None)
        if (
            sc
            and "数据值" in df.columns
            and "键" in df.columns
        ):
            mode = "merged"
        elif {"标签", "数据值"}.issubset(df.columns) and sc:
            mode = "trial"
        else:
            mode = "blob"

    if mode == "merged":
        filled = process_merged_trial(df)
    elif mode == "trial":
        filled = process_trial_style(df)
    else:
        shop_c = _detect_shop_column(df, ns.shop_col)
        blob_c = _detect_blob_column(df, ns.blob_col)
        print(f"使用列: 店铺=[{shop_c}] 文本=[{blob_c}]", file=sys.stderr)
        filled = process_blob_sheet(df, shop_c, blob_c)

    if ns.merge_template_shops:
        merge_into_workbook(filled, ns.out, _load_template_shops())
    else:
        write_only_input_shops(filled, ns.out)
    print(f"已更新: {ns.out.resolve()}（写入 {len(filled)} 条解析结果）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
