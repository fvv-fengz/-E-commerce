# -*- coding: utf-8 -*-
"""
拼多多下载结果的后处理脚本，分三部分（第一、二部分已实现）。

第一部分：从指定目录识别「原始售后单」Excel，按条件筛选后按店汇总退款金额，并合并明细与全店合计；
同时把每个店铺「筛选后的明细」各输出为一个独立 xlsx（与汇总表同目录下子文件夹「<汇总文件名>_筛选明细」）。

第二部分：从压缩包（或同目录下的对账 xlsx）读取「资金账单」明细表；按店、按「业务描述」合并汇总收入/支出/笔数（同描述叠加）；
按店汇总中收入合计为明细「收入金额」列求和，并统计总支出等；不另建「收入透视」工作表。每店一张表（店铺名称+业务描述+收入+支出，同描述一行）写入「…_按店交易明细」。

用法示例（项目根目录）：
  python scripts/process_pdd_data.py part1
  默认读取相对路径：output/downloads/拼多多数据提取_1_<中国时区昨天，YYYY-MM-DD>（与 run_template_trial 下载子目录一致）。

  也可显式指定目录：
  python scripts/process_pdd_data.py part1 --input-dir "output/downloads/拼多多数据提取_1_2026-04-16"

  python scripts/process_pdd_data.py part2
  默认识别 *对账*raw*.zip（或 *对账*raw*.xlsx），解压 zip 内首个 xlsx 后解析。

  一次跑完 part1 + part2（同一输入目录、同一参考日，默认各写各的 dailydate 文件）：
  python scripts/process_pdd_data.py all

默认输出：项目根目录下 dailydate/，文件名 pdd_part1_售后退款_<统计昨日>.xlsx、
pdd_part2_资金账单_<统计昨日>.xlsx（另含同目录「…_按店交易明细」每店四列含店铺名称、同业务描述合并为一行）；
可用各子命令的 --output 或 all 的 --out-part1 / --out-part2 覆盖。

参考日默认取「中国时区当天」；统计用「昨天」= 参考日 − 1 天。
可选：手动指定 --reference-date 2026-04-17，则「昨天」= 2026-04-16。
"""

import argparse
import inspect
import io
import re
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


def _pd_read_csv_compat(bio: Any, **kwargs: Any) -> pd.DataFrame:
    """兼容不同 pandas 版本的坏行处理参数。"""
    sig = inspect.signature(pd.read_csv)
    if "on_bad_lines" in sig.parameters:
        return pd.read_csv(bio, on_bad_lines="skip", **kwargs)
    if "error_bad_lines" in sig.parameters:
        return pd.read_csv(bio, error_bad_lines=False, warn_bad_lines=False, **kwargs)
    return pd.read_csv(bio, **kwargs)


# 项目根目录（process_pdd_data.py 位于 scripts/ 下）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 各 part 处理结果默认写入项目根下 dailydate/（不存在则自动创建）
DAILYDATE_OUT_DIR = PROJECT_ROOT / "dailydate"

# ---------- 第一部分：列名与筛选常量（与导出列一致） ----------

COL_SHOP = "店铺名称"
COL_TYPE = "售后类型"
COL_STATUS = "售后状态"
COL_HANDLE = "处理状态"
COL_APPLY_TIME = "售后申请时间"
COL_LOGISTICS = "发货物流状态"
COL_INTERCEPT = "包裹拦截状态"
COL_REFUND = "退款金额"

FILTER_TYPE = "退款"
FILTER_STATUS = "退款成功"
FILTER_HANDLE = "待处理"
FILTER_LOGISTICS = "已签收"

RAW_FILE_GLOB = "*售后单*raw*.xlsx"

# ---------- 第二部分：资金账单（对账 zip / xlsx）----------

RECON_ZIP_GLOB = "*对账*raw*.zip"
RECON_XLSX_GLOB = "*对账*raw*.xlsx"

# 拼多多「店铺账务明细」导出标准表头（与站点 CSV 一致，全角括号）
PDD_CASHIER_MERCHANT_ORDER = "商户订单号"
PDD_CASHIER_PRODUCT_ORDER = "商品订单号"
PDD_CASHIER_OCCUR_TIME = "发生时间"
PDD_CASHIER_INCOME = "收入金额（+元）"
PDD_CASHIER_EXPENSE = "支出金额（-元）"
PDD_CASHIER_ACCT_TYPE = "账务类型"
PDD_CASHIER_REMARK = "备注"
PDD_CASHIER_BIZ_DESC = "业务描述"


def _find_reconcile_archives(input_dir: Path, recursive: bool) -> List[Path]:
    """按文件名匹配对账下载（zip 优先列出；同目录可有 xlsx 兜底）。"""
    if not input_dir.is_dir():
        raise FileNotFoundError(f"目录不存在: {input_dir}")

    def ok_zip(p: Path) -> bool:
        n = p.name.lower()
        if p.name.startswith("~$"):
            return False
        return p.suffix.lower() == ".zip" and "对账" in p.name and "raw" in n

    def ok_xlsx(p: Path) -> bool:
        n = p.name.lower()
        if p.name.startswith("~$"):
            return False
        return p.suffix.lower() == ".xlsx" and "对账" in p.name and "raw" in n

    zips: List[Path] = []
    xlsx: List[Path] = []
    if recursive:
        for p in input_dir.rglob("*"):
            if ok_zip(p):
                zips.append(p)
            elif ok_xlsx(p):
                xlsx.append(p)
    else:
        for p in input_dir.glob("*.zip"):
            if ok_zip(p):
                zips.append(p)
        for p in input_dir.glob("*.xlsx"):
            if ok_xlsx(p):
                xlsx.append(p)
    zips = sorted(set(zips))
    xlsx = sorted(set(xlsx))
    # 每个店铺通常各一份；zip 与同名 stem 的 xlsx 只取 zip，避免重复
    stems = {p.stem for p in zips}
    xlsx_only = [p for p in xlsx if p.stem not in stems]
    return zips + xlsx_only


def _shop_label_from_reconcile_filename(path: Path) -> str:
    """{account}_对账_{yday}_raw.zip / .xlsx → account。"""
    stem = path.stem
    if "_对账_" in stem:
        return stem.split("_对账_")[0]
    return stem


def _first_tabular_from_zip(zip_path: Path) -> Tuple[str, bytes, str]:
    """
    从对账 zip 中取首个表格文件。拼多多可能下发 .xlsx / .xls / .csv。
    返回 (包内路径, 原始字节, 类型)，类型为 \"xlsx\" | \"xls\" | \"csv\"。
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        all_names = [
            n
            for n in zf.namelist()
            if not n.endswith("/")
            and not n.startswith("__MACOSX/")
            and not Path(n).name.startswith("~$")
        ]
        # 拼多多对账常见为 zip 内单文件 .csv；其次 .xlsx / .xls
        for ext, kind in (".xlsx", "xlsx"), (".csv", "csv"), (".xls", "xls"):
            hit = sorted(n for n in all_names if n.lower().endswith(ext))
            if hit:
                name = hit[0]
                return name, zf.read(name), kind
        sample = ", ".join(all_names[:25]) if all_names else "(空压缩包)"
        raise ValueError(
            f"压缩包内无 .xlsx/.csv/.xls。包内条目(节选): {sample}"
        )


def _scan_header_row(
    buf: bytes, max_rows: int = 45, *, engine: str = "openpyxl"
) -> int:
    """在表头区域查找含「商户/商品订单」的行作为列名行。"""
    head = pd.read_excel(
        io.BytesIO(buf), header=None, nrows=max_rows, engine=engine
    )
    for i in range(len(head)):
        parts = head.iloc[i].astype(str).fillna("")
        joined = " ".join(parts.tolist())
        if "商户订单" in joined or "商品订单" in joined:
            return i
    return 4


def _pick_col(df: pd.DataFrame, must: List[str]) -> Optional[str]:
    for c in df.columns:
        cs = str(c).replace("\n", "").strip()
        if all(k in cs for k in must):
            return c
    return None


def _normalize_header_cell(c: Any) -> str:
    return str(c).replace("\ufeff", "").replace("\n", "").strip()


def _match_column_exact(df: pd.DataFrame, *exact_labels: str) -> Optional[Any]:
    """列名与标准表头完全一致（去 BOM/换行/首尾空白）时返回该列。"""
    want = {str(x).strip() for x in exact_labels if x}
    for col in df.columns:
        if _normalize_header_cell(col) in want:
            return col
    return None


def _pick_income_col(df: pd.DataFrame) -> Optional[str]:
    c = _match_column_exact(df, PDD_CASHIER_INCOME)
    if c is not None:
        return c
    c = _pick_col(df, ["收入"])
    if c:
        return c
    for col in df.columns:
        cs = _normalize_header_cell(col)
        if "收入" in cs and "支出" not in cs:
            return col
    return None


def _pick_expense_col(df: pd.DataFrame) -> Optional[str]:
    c = _match_column_exact(df, PDD_CASHIER_EXPENSE)
    if c is not None:
        return c
    c = _pick_col(df, ["支出"])
    if c:
        return c
    for col in df.columns:
        cs = _normalize_header_cell(col)
        if "支出" in cs:
            return col
    return None


def _pick_biz_desc_col(df: pd.DataFrame) -> Optional[str]:
    """业务描述列；标准名「业务描述」，否则列名含「业务描述」。"""
    c = _match_column_exact(df, PDD_CASHIER_BIZ_DESC)
    if c is not None:
        return c
    for col in df.columns:
        cs = _normalize_header_cell(col)
        if "业务描述" in cs:
            return col
    return None


def _parse_expenditure_cell(val: Any) -> float:
    """单元格可能为「-0.03 技术服务费」或纯数字，取首个数值。"""
    if pd.isna(val):
        return 0.0
    s = str(val).strip().replace(",", "").replace("，", "")
    if not s or s in {"-", "—"}:
        return 0.0
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except ValueError:
        return 0.0


def _is_body_row_order_col(val: Any) -> bool:
    """剔除表尾说明行（#合计、导出时间等）。"""
    if pd.isna(val):
        return False
    s = str(val).strip()
    if not s:
        return False
    if s.startswith("#"):
        return False
    if "导出时间" in s and "：" in s:
        return False
    if re.match(r"^#?支出合计", s) or re.match(r"^#?收入合计", s) or re.match(r"^#?总计", s):
        return False
    return True


def _is_footer_marker_order_col(val: Any) -> bool:
    """是否为账务导出尾部说明行（按订单号列文本判断）。"""
    if pd.isna(val):
        return False
    s = str(val).strip()
    if not s:
        return False
    if s.startswith("#"):
        return True
    if "导出时间" in s and "：" in s:
        return True
    if re.match(r"^#?支出合计", s) or re.match(r"^#?收入合计", s) or re.match(r"^#?总计", s):
        return True
    return False


def _has_visible_value(val: Any) -> bool:
    """单元格是否可视为有效内容。"""
    if pd.isna(val):
        return False
    return bool(str(val).strip())


def _decode_csv_bytes_for_scan(buf: bytes) -> str:
    """用于定位表头行。拼多多 Windows 导出多为 GBK，优先于 UTF-8。"""
    for enc in ("gbk", "gb18030", "utf-8-sig", "utf-8"):
        try:
            return buf.decode(enc)
        except UnicodeDecodeError:
            continue
    return buf.decode("utf-8", errors="replace")


def _should_try_utf8_csv(buf: bytes) -> bool:
    """
    仅当带 BOM 或整段可被 strict UTF-8 解码时，再尝试 utf-8 / utf-8-sig。
    拼多多 GBK 导出若强行走 UTF-8 会得到 UnicodeDecodeError，且易成为「最后错误」误导排查。
    """
    if buf.startswith(b"\xef\xbb\xbf"):
        return True
    try:
        buf.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _scan_header_row_csv(buf: bytes, max_rows: int = 45) -> int:
    """
    返回「列名所在行」的 0-based 行号（从文件第一行算起，**含空行**）。
    拼多多「店铺账务明细」CSV 典型结构（示例）：
      第1行 标题「拼多多店铺账务明细查询」
      第2行 空行
      第3行 起始/终止时间
      第4行 ----------交易记录明细列表---------
      第5行 列名：商户订单号或商品订单号,发生时间,收入金额（+元）,支出金额（-元）,账务类型,备注,业务描述
      第6行起 明细；文末 #支出合计 / #收入合计 / #总计 / #导出时间（非表格行，读入后剔除）
    故 skiprows=4、header=0 对应「第5行为表头」。勿用 header=4 配 skip_blank_lines（会错位）。
    """
    text = _decode_csv_bytes_for_scan(buf)
    lines = text.splitlines()
    if len(lines) > 4:
        row5 = lines[4]
        if "商户订单" in row5 or "商品订单" in row5 or (
            "收入" in row5 and "支出" in row5 and "发生时间" in row5
        ):
            return 4
    for i, line in enumerate(lines[:max_rows]):
        if "商户订单" in line or "商品订单" in line:
            return i
    return 4


def _csv_header_skiprows_candidates(buf: bytes, max_scan: int = 80) -> List[int]:
    """
    扫描文本，找出「像表头」的行号：含「商户订单」或「商品订单」且含逗号/Tab（排除 # 开头）。
    无命中时退回 [4]；版本差异导致少空行时表头可能不在第 5 行，需多候选。
    """
    text = _decode_csv_bytes_for_scan(buf)
    lines = text.splitlines()
    cand: List[int] = []
    for i, line in enumerate(lines[:max_scan]):
        s = line.strip()
        if s.startswith("#"):
            continue
        if "商户订单" not in line and "商品订单" not in line:
            continue
        if "," in line or "\t" in line:
            cand.append(i)
    if not cand:
        cand = [4]
    out: List[int] = []
    for x in cand + [4, 3, 5, 2, 6]:
        if x >= 0 and x not in out:
            out.append(x)
    return out[:15]


def _pick_merchant_order_col(df: pd.DataFrame) -> Optional[str]:
    """订单号列：优先「商户订单号」「商品订单号」，否则列名含「商户订单」或「商品订单」。"""
    c = _match_column_exact(df, PDD_CASHIER_MERCHANT_ORDER, PDD_CASHIER_PRODUCT_ORDER)
    if c is not None:
        return c
    for col in df.columns:
        cs = _normalize_header_cell(col)
        if "商户订单" in cs or "商品订单" in cs:
            return col
    return None


def _read_cashier_detail_from_csv_bytes(raw: bytes) -> pd.DataFrame:
    """
    读取拼多多等对账 CSV：自动尝试编码与分隔符（逗号 / Tab / 分号 / pandas 推断）。
    拼多多导出的 .csv 在中文 Windows 下多为 GBK；若先按 UTF-8 读会报 UnicodeDecodeError。
    表尾「#支出合计」「#导出时间」等为非表格行，读入后由 _is_body_row_order_col 剔除。
    注意：无交易明细时表尾行往往只在首列有内容、其余列为 NaN；若在读入后立刻 dropna(axis=1, how='all')，
    会把合法表头列全部删掉只剩一列，导致无法识别订单号列（误判为解析失败）。
    """
    hdr_list = _csv_header_skiprows_candidates(raw)
    # GBK 优先；仅 BOM/真 UTF-8 文件再尝试 utf-8 系列，避免 GBK 文件末尾误报 UTF-8 解码失败
    encodings: Tuple[str, ...] = ("gbk", "gb18030", "cp936")
    if _should_try_utf8_csv(raw):
        encodings = encodings + ("utf-8-sig", "utf-8")
    # 拼多多账务 CSV 多为英文逗号；最后再尝试 pandas 推断分隔符（部分环境 infer 会失败）
    seps: List[Optional[str]] = [",", "\t", ";", None]
    last_err: Optional[BaseException] = None
    last_cols: List[Any] = []

    for hdr in hdr_list:
        for enc in encodings:
            for sep in seps:
                try:
                    kw: Dict[str, Any] = dict(
                        skiprows=hdr,
                        header=0,
                        encoding=enc,
                        engine="python",
                    )
                    if sep is not None:
                        kw["sep"] = sep
                    else:
                        kw["sep"] = None
                    df = _pd_read_csv_compat(io.BytesIO(raw), **kw)
                    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
                    if df.shape[1] < 2:
                        continue
                    last_cols = list(df.columns)
                    order_c = _pick_merchant_order_col(df)
                    if order_c:
                        return df.copy()
                    last_err = ValueError(
                        f"skiprows={hdr} enc={enc} 已读出多列但未匹配订单号列（商户/商品订单），列名={last_cols[:20]!r}"
                    )
                except Exception as e:
                    last_err = e
                    continue

    for hdr in hdr_list:
        for sep in (",", "\t", ";", None):
            try:
                kw: Dict[str, Any] = dict(
                    skiprows=hdr,
                    header=0,
                    encoding="latin-1",
                    engine="python",
                )
                if sep is not None:
                    kw["sep"] = sep
                else:
                    kw["sep"] = None
                df = _pd_read_csv_compat(io.BytesIO(raw), **kw)
                df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
                last_cols = list(df.columns)
                order_c = _pick_merchant_order_col(df)
                if order_c:
                    return df.copy()
            except Exception as e:
                last_err = e

    hint = ""
    if last_err is not None and type(last_err).__name__ == "UnicodeDecodeError":
        hint = (
            "（若内容为中文而报错 UTF-8，多为文件实为 GBK；请确认已使用当前脚本「仅对真 UTF-8 尝试 utf-8」逻辑。）"
        )
    col_hint = f" 最近一次解析到的列名(节选): {last_cols[:25]!r}" if last_cols else ""
    raise ValueError(
        "无法解析对账 CSV：未能在任一 skiprows/编码/分隔符组合下识别订单号列（「商户订单号」或「商品订单号」）。"
        " 若站点少空行或增删说明行，表头可能不在第 5 行，脚本已自动多行扫描；仍失败请检查导出是否为标准账务明细。"
        f"{hint}{col_hint} 技术详情: {last_err!r}"
    )


def _read_cashier_detail_df(path: Path) -> pd.DataFrame:
    """从本地 xlsx/xls 读取资金明细（单表）。"""
    raw = path.read_bytes()
    suf = path.suffix.lower()
    if suf == ".csv":
        return _read_cashier_detail_from_csv_bytes(raw)
    engine = "openpyxl" if suf == ".xlsx" else "xlrd"
    return _read_cashier_detail_from_bytes(raw, engine=engine)


def _read_cashier_detail_from_bytes(
    raw: bytes, *, engine: str = "openpyxl"
) -> pd.DataFrame:
    hdr = _scan_header_row(raw, engine=engine)
    df = pd.read_excel(io.BytesIO(raw), header=hdr, engine=engine)
    df = df.dropna(axis=1, how="all")
    order_c = _pick_merchant_order_col(df)
    if not order_c:
        raise ValueError("未找到订单号列（需「商户订单号」或「商品订单号」，或列名含商户/商品订单）")
    return df.copy()


def _load_reconcile_frame(archive: Path) -> pd.DataFrame:
    if archive.suffix.lower() == ".zip":
        inner, buf, kind = _first_tabular_from_zip(archive)
        try:
            if kind == "csv":
                return _read_cashier_detail_from_csv_bytes(buf)
            eng = "openpyxl" if kind == "xlsx" else "xlrd"
            return _read_cashier_detail_from_bytes(buf, engine=eng)
        except Exception as e:
            raise ValueError(f"{archive.name} 内 {inner}: {e}") from e
    return _read_cashier_detail_df(archive)


def run_part2(
    input_dir: Path,
    output_path: Optional[Path],
    reference_date: Optional[str],
    recursive: bool,
) -> Path:
    """
    对每个店铺的对账 zip/xlsx：按「业务描述」合并汇总收入/支出/笔数（同店同描述叠加）；
    按店汇总中「收入(按商户订单号透视合计)」为对账明细「收入金额」列逐行求和；不再单独输出「收入透视」工作表。
    为每店输出一张表：店铺名称、业务描述、收入、支出（共四列），
    且与「业务描述汇总」sheet 中该店口径一致（相同业务描述合并为一行），写入「汇总文件名_按店交易明细」目录。
    """
    ref = _resolve_reference_date(input_dir, reference_date)
    yday = _yesterday_from_ref(ref)

    files = _find_reconcile_archives(input_dir, recursive=recursive)
    if not files:
        raise FileNotFoundError(
            f"未在目录中找到 {RECON_ZIP_GLOB} 或 {RECON_XLSX_GLOB}: {input_dir}"
        )

    out = output_path
    if out is None:
        out = DAILYDATE_OUT_DIR / f"pdd_part2_资金账单_{yday.isoformat()}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    per_shop_dir = out.parent / f"{out.stem}_按店交易明细"

    summary_rows: List[Dict[str, Any]] = []
    biz_pivot_parts: List[pd.DataFrame] = []
    detail_parts: List[pd.DataFrame] = []

    for fp in files:
        shop = _shop_label_from_reconcile_filename(fp)
        try:
            body = _load_reconcile_frame(fp)
        except Exception as e:
            raise RuntimeError(f"读取失败 {fp.name}: {e}") from e

        order_c = _pick_merchant_order_col(body)
        inc_c = _pick_income_col(body)
        exp_c = _pick_expense_col(body)
        bd_c = _pick_biz_desc_col(body)
        if not order_c or not inc_c or not exp_c or not bd_c:
            miss = [
                x
                for x, v in [
                    ("商户订单号", order_c),
                    ("收入", inc_c),
                    ("支出", exp_c),
                    ("业务描述", bd_c),
                ]
                if not v
            ]
            raise ValueError(f"{fp.name} 缺少列: {miss}，实际列={list(body.columns)}")

        # 保留「商品订单号为空」的有效账务记录；仅剔除导出尾部说明行与整行空白。
        probe = body[[order_c, bd_c, inc_c, exp_c]].copy()
        mask_footer = probe[order_c].map(_is_footer_marker_order_col)
        mask_any_visible = probe.apply(
            lambda r: any(_has_visible_value(v) for v in r),
            axis=1,
        )
        body = body.loc[(~mask_footer) & mask_any_visible].copy()

        exp_series = body[exp_c].map(_parse_expenditure_cell)
        total_expense = round(float(exp_series.sum()), 2)

        inc_series = body[inc_c].map(_parse_money)
        # 「收入(按商户订单号透视合计)」：按业务要求为明细行「收入金额」列直接求和（不按订单号先去重合并）
        income_after_pivot = round(float(inc_series.sum()), 2)
        n_orders = int(body.groupby(order_c, dropna=False).ngroups)

        summary_rows.append(
            {
                "店铺标识": shop,
                "源文件": fp.name,
                "参考日期": str(ref),
                "统计昨日": str(yday),
                "商户订单号条数_本店": n_orders,
                "明细行数": int(len(body)),
                "收入(按商户订单号透视合计)": income_after_pivot,
                "总支出金额": total_expense,
            }
        )

        tb = body[[order_c, bd_c, inc_c, exp_c]].copy()
        tb["_inc_num"] = tb[inc_c].map(_parse_money)
        tb["_exp_num"] = tb[exp_c].map(_parse_expenditure_cell)
        tb[bd_c] = tb[bd_c].apply(lambda x: "" if pd.isna(x) else str(x).strip())
        tb.loc[tb[bd_c] == "", bd_c] = "（空）"
        biz_grp = (
            tb.groupby(bd_c, dropna=False)
            .agg(
                收入合计=("_inc_num", "sum"),
                支出合计=("_exp_num", "sum"),
                笔数=(order_c, "count"),
            )
            .reset_index()
            .rename(columns={bd_c: "业务描述"})
        )
        biz_grp["收入合计"] = biz_grp["收入合计"].map(lambda x: round(float(x), 2))
        biz_grp["支出合计"] = biz_grp["支出合计"].map(lambda x: round(float(x), 2))
        biz_grp["笔数"] = biz_grp["笔数"].astype(int)
        biz_grp.insert(0, "店铺标识", shop)
        biz_pivot_parts.append(biz_grp)

        if len(body) > 0:
            slim = biz_grp[["店铺标识", "业务描述", "收入合计", "支出合计"]].copy()
            slim = slim.rename(
                columns={
                    "店铺标识": "店铺名称",
                    "收入合计": "收入",
                    "支出合计": "支出",
                }
            )
            slim = slim.sort_values("业务描述", kind="mergesort").reset_index(drop=True)
            per_shop_dir.mkdir(parents=True, exist_ok=True)
            safe = _safe_filename_segment(shop)
            dest = per_shop_dir / f"{safe}_对账交易_{yday.isoformat()}.xlsx"
            n_dup = 1
            while dest.exists():
                dest = (
                    per_shop_dir / f"{safe}_对账交易_{yday.isoformat()}_{n_dup}.xlsx"
                )
                n_dup += 1
            slim.to_excel(dest, index=False, engine="openpyxl")

        d = body.copy()
        d.insert(0, "店铺标识", shop)
        d.insert(1, "源文件", fp.name)
        detail_parts.append(d)

    summary_df = pd.DataFrame(summary_rows)
    total_orders = int(summary_df["商户订单号条数_本店"].sum())
    total_rows = int(summary_df["明细行数"].sum())
    sum_income_pivot = round(float(summary_df["收入(按商户订单号透视合计)"].sum()), 2)
    sum_expense = round(float(summary_df["总支出金额"].sum()), 2)

    summary_df = pd.concat(
        [
            summary_df,
            pd.DataFrame(
                [
                    {
                        "店铺标识": "【全部店铺合计】",
                        "源文件": "",
                        "参考日期": str(ref),
                        "统计昨日": str(yday),
                        "商户订单号条数_本店": total_orders,
                        "明细行数": total_rows,
                        "收入(按商户订单号透视合计)": sum_income_pivot,
                        "总支出金额": sum_expense,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    biz_pivot_df = (
        pd.concat(biz_pivot_parts, ignore_index=True)
        if biz_pivot_parts
        else pd.DataFrame()
    )
    detail_df = (
        pd.concat(detail_parts, ignore_index=True) if detail_parts else pd.DataFrame()
    )

    meta = pd.DataFrame(
        [
            {"项": "参考日期(ref，默认=中国时区当天)", "值": str(ref)},
            {"项": "统计「昨天」", "值": str(yday)},
            {
                "项": "业务描述汇总",
                "值": "相同「业务描述」合并：汇总收入、支出、明细笔数（按店铺）",
            },
            {
                "项": "收入(按商户订单号透视合计)",
                "值": "对账明细「收入金额」列逐行解析后求和（与是否同订单号无关）；列名沿用；仅体现在「按店汇总」",
            },
            {"项": "总支出", "值": "对「支出金额」列逐行取首个数值后求和（含负数）"},
            {"项": "源目录", "值": str(input_dir.resolve())},
            {"项": "结果输出目录", "值": str(out.parent.resolve())},
            {"项": "结果文件", "值": str(out.resolve())},
            {
                "项": "各店交易明细（店铺名称/业务描述/收入/支出四列，同店同描述合并为一行）",
                "值": str(per_shop_dir.resolve())
                if per_shop_dir.is_dir()
                else "(无交易行，未创建)",
            },
        ]
    )

    with pd.ExcelWriter(out, engine="openpyxl") as w:
        summary_df.to_excel(w, sheet_name="按店汇总", index=False)
        if len(biz_pivot_df):
            biz_pivot_df.to_excel(w, sheet_name="业务描述汇总", index=False)
        else:
            pd.DataFrame({"说明": ["无数据"]}).to_excel(w, sheet_name="业务描述汇总", index=False)
        if len(detail_df):
            detail_df.to_excel(w, sheet_name="原始明细", index=False)
        else:
            pd.DataFrame({"说明": ["无数据"]}).to_excel(w, sheet_name="原始明细", index=False)
        meta.to_excel(w, sheet_name="说明", index=False)

    extra_shop = ""
    if per_shop_dir.is_dir():
        extra_shop = f"\n  各店四列汇总（店铺名称+业务描述+收入+支出，同描述合并）目录: {per_shop_dir}"
    print(
        f"已写入: {out}\n"
        f"  参考日期={ref}  统计昨日={yday}\n"
        f"  店铺数={len(files)}  全店收入金额合计={sum_income_pivot}  全店总支出={sum_expense}"
        f"{extra_shop}"
    )
    return out


def cmd_part2(args):
    raw_out = (getattr(args, "output", None) or "").strip()
    outp = None
    if raw_out:
        po = Path(raw_out)
        outp = po if po.is_absolute() else PROJECT_ROOT / po
    inp = _resolve_part1_input_dir(getattr(args, "input_dir", None))
    print(f"[part2] 输入目录: {inp}")
    run_part2(
        inp,
        outp,
        getattr(args, "reference_date", None),
        bool(getattr(args, "recursive", False)),
    )


def cmd_all(args):
    """依次执行 part1、part2，共用 input-dir / reference-date / recursive。"""
    o1 = (getattr(args, "out_part1", None) or "").strip()
    o2 = (getattr(args, "out_part2", None) or "").strip()
    common = {
        "input_dir": getattr(args, "input_dir", None),
        "reference_date": getattr(args, "reference_date", None),
        "recursive": bool(getattr(args, "recursive", False)),
    }
    print("========== part1（售后退款）==========", file=sys.stderr)
    cmd_part1(
        SimpleNamespace(
            output=o1,
            **common,
        )
    )
    print("========== part2（资金账单）==========", file=sys.stderr)
    cmd_part2(
        SimpleNamespace(
            output=o2,
            **common,
        )
    )


def _today_china() -> date:
    """
    中国（东八区）的「今天」日历日。
    优先用 Asia/Shanghai；不可用时用 UTC+8 近似（与北京时间一致，无夏令时）。
    """
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=8)).date()


def _yesterday_china() -> date:
    """中国时区的「昨天」（用于默认下载子目录名中的日期段）。"""
    return _today_china() - timedelta(days=1)


def _default_part1_input_dir() -> Path:
    """
    与模板 downloadRunSubdirTemplate 一致：拼多多数据提取_1_{run_date}，
    run_date 在试运行里为「昨天」——此处用中国时区昨天的 YYYY-MM-DD。
    """
    yd = _yesterday_china().isoformat()
    return PROJECT_ROOT / "output" / "downloads" / f"拼多多数据提取_1_{yd}"


def _resolve_part1_input_dir(raw: Optional[str]) -> Path:
    """未传或空串时用默认目录；相对路径相对项目根解析。"""
    if raw is None or not str(raw).strip():
        return _default_part1_input_dir()
    path = Path(str(raw).strip())
    if not path.is_absolute():
        return PROJECT_ROOT / path
    return path


def _resolve_reference_date(_input_dir: Path, explicit: Optional[str]) -> date:
    if explicit:
        return datetime.strptime(explicit.strip(), "%Y-%m-%d").date()
    return _today_china()


def _yesterday_from_ref(ref: date) -> date:
    return ref - timedelta(days=1)


def _is_empty_intercept(val: Any) -> bool:
    """包裹拦截状态「空值」：NaN 或仅空白。"""
    if pd.isna(val):
        return True
    s = str(val).strip()
    return s == ""


def _intercept_ok_for_part1(val: Any) -> bool:
    """part1：包裹拦截状态为空，或文案中含「未拦截」即通过。"""
    if _is_empty_intercept(val):
        return True
    s = str(val).strip()
    return "未拦截" in s


def _parse_money(val: Any) -> float:
    if pd.isna(val):
        return 0.0
    s = str(val).strip().replace(",", "").replace("，", "")
    for prefix in ("\u00a5", "\uffe5", "¥"):
        if s.startswith(prefix):
            s = s[len(prefix) :].strip()
            break
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_raw_aftersale_files(input_dir: Path, recursive: bool) -> List[Path]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"目录不存在: {input_dir}")

    def _is_raw_aftersale(p: Path) -> bool:
        n = p.name.lower()
        if p.name.startswith("~$"):
            return False
        return p.suffix.lower() == ".xlsx" and "售后单" in p.name and "raw" in n

    if recursive:
        files = sorted(p for p in input_dir.rglob("*.xlsx") if _is_raw_aftersale(p))
    else:
        files = sorted(p for p in input_dir.glob("*.xlsx") if _is_raw_aftersale(p))
    return files


def _safe_filename_segment(name: str, max_len: int = 80) -> str:
    """Windows 文件名安全片段。"""
    s = (name or "").strip()
    s = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", s)
    s = s.strip(" .") or "店铺"
    return s[:max_len]


def _shop_label_from_path(df: pd.DataFrame, path: Path) -> str:
    if COL_SHOP in df.columns and len(df) > 0:
        v = df[COL_SHOP].iloc[0]
        if pd.notna(v) and str(v).strip():
            return str(v).strip()
    stem = path.stem
    if "_售后单" in stem:
        return stem.split("_售后单")[0]
    return stem


def _strip_colnames(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = pd.Index(str(c).strip() if c is not None and pd.notna(c) else "" for c in out.columns)
    return out


def _part1_required_columns() -> List[str]:
    return [
        COL_TYPE,
        COL_STATUS,
        COL_HANDLE,
        COL_APPLY_TIME,
        COL_LOGISTICS,
        COL_INTERCEPT,
        COL_REFUND,
    ]


def _aftersale_cols_ok(df: pd.DataFrame) -> bool:
    return all(c in df.columns for c in _part1_required_columns())


def _read_aftersale_raw_excel(fp: Path) -> pd.DataFrame:
    """
    读「下载查询订单」导出 xlsx。拼多多部分版本会在第 1 行插入整表提示语，
    真实表头在第 2 行，需 header=1；否则 read_excel 会把整列读成 Unnamed:* 并报缺列。
    """
    df0 = pd.read_excel(fp, engine="openpyxl")
    df0 = _strip_colnames(df0)
    if _aftersale_cols_ok(df0):
        return df0
    df1 = pd.read_excel(fp, engine="openpyxl", header=1)
    df1 = _strip_colnames(df1)
    if _aftersale_cols_ok(df1):
        return df1
    need = [c for c in _part1_required_columns() if c not in df1.columns]
    raise ValueError(
        f"{fp.name}: 缺少列 {need}；已尝试首行表头(header=0)与第二行表头(header=1)。"
    )


def _filter_aftersale(
    df: pd.DataFrame,
    target_day: date,
) -> pd.DataFrame:
    need = _part1_required_columns()
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"缺少列: {missing}")

    t = pd.to_datetime(df[COL_APPLY_TIME], errors="coerce")
    day_ok = t.dt.date == target_day

    m = (
        (df[COL_TYPE].astype(str).str.strip() == FILTER_TYPE)
        & (df[COL_STATUS].astype(str).str.strip() == FILTER_STATUS)
        & (df[COL_HANDLE].astype(str).str.strip() == FILTER_HANDLE)
        & (df[COL_LOGISTICS].astype(str).str.strip() == FILTER_LOGISTICS)
        & (df[COL_INTERCEPT].map(_intercept_ok_for_part1))
        & day_ok
    )
    return df.loc[m].copy()


def run_part1(
    input_dir: Path,
    output_path: Optional[Path],
    reference_date: Optional[str],
    recursive: bool,
) -> Path:
    ref = _resolve_reference_date(input_dir, reference_date)
    yday = _yesterday_from_ref(ref)

    files = _find_raw_aftersale_files(input_dir, recursive=recursive)
    if not files:
        raise FileNotFoundError(
            f"未在目录中找到匹配 {RAW_FILE_GLOB} 的文件: {input_dir}"
        )

    out = output_path
    if out is None:
        out = DAILYDATE_OUT_DIR / f"pdd_part1_售后退款_{yday.isoformat()}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    per_shop_dir = out.parent / f"{out.stem}_筛选明细"

    summary_rows = []  # type: List[Dict[str, Any]]
    detail_parts = []  # type: List[pd.DataFrame]

    for fp in files:
        df = _read_aftersale_raw_excel(fp)
        sub = _filter_aftersale(df, yday)
        shop = _shop_label_from_path(df, fp)
        sub_sum = sub[COL_REFUND].map(_parse_money).sum() if len(sub) else 0.0

        summary_rows.append(
            {
                "店铺标识": shop,
                "命中行数": int(len(sub)),
                "退款金额合计": round(float(sub_sum), 2),
            }
        )

        if len(sub):
            sub = sub.copy()
            sub.insert(0, "店铺标识_汇总", shop)
            sub.insert(1, "源文件", fp.name)
            detail_parts.append(sub)
            per_shop_dir.mkdir(parents=True, exist_ok=True)
            safe = _safe_filename_segment(shop)
            dest = per_shop_dir / f"{safe}_售后单筛选_{yday.isoformat()}.xlsx"
            n_dup = 1
            while dest.exists():
                dest = per_shop_dir / f"{safe}_售后单筛选_{yday.isoformat()}_{n_dup}.xlsx"
                n_dup += 1
            sub.to_excel(dest, index=False, engine="openpyxl")

    total_hits = int(sum(int(r["命中行数"]) for r in summary_rows))
    total_amt = round(float(sum(float(r["退款金额合计"]) for r in summary_rows)), 2)
    # 按店汇总：不列出命中 0 行的店铺（合计仍含全部源文件的加总）
    summary_visible = [r for r in summary_rows if int(r["命中行数"]) > 0]
    cols = ["店铺标识", "命中行数", "退款金额合计"]
    if summary_visible:
        summary_df = pd.DataFrame(summary_visible)
    else:
        summary_df = pd.DataFrame(columns=cols)
    summary_df = pd.concat(
        [
            summary_df,
            pd.DataFrame(
                [
                    {
                        "店铺标识": "【全部店铺合计】",
                        "命中行数": total_hits,
                        "退款金额合计": total_amt,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    if detail_parts:
        detail_df = pd.concat(detail_parts, ignore_index=True)
    else:
        detail_df = pd.DataFrame()

    meta = pd.DataFrame(
        [
            {"项": "参考日期(ref，默认=中国时区当天)", "值": str(ref)},
            {"项": "统计「昨天」(售后申请日期=ref−1天)", "值": str(yday)},
            {
                "项": "筛选条件",
                "值": (
                    f"{COL_TYPE}={FILTER_TYPE}; {COL_STATUS}={FILTER_STATUS}; "
                    f"{COL_HANDLE}={FILTER_HANDLE}; {COL_APPLY_TIME} 日期={yday}; "
                    f"{COL_LOGISTICS}={FILTER_LOGISTICS}; {COL_INTERCEPT} 为空或含「未拦截」"
                ),
            },
            {"项": "源目录", "值": str(input_dir.resolve())},
            {"项": "结果输出目录", "值": str(out.parent.resolve())},
            {"项": "结果文件", "值": str(out.resolve())},
            {
                "项": "各店筛选明细目录（每店一个 xlsx）",
                "值": str(per_shop_dir.resolve())
                if per_shop_dir.is_dir()
                else "(无命中行，未创建)",
            },
            {
                "项": "按店汇总",
                "值": "仅列出命中行数>0 的店铺；命中为 0 的不占行（底部合计仍为全部源文件加总）",
            },
        ]
    )

    with pd.ExcelWriter(out, engine="openpyxl") as w:
        summary_df.to_excel(w, sheet_name="按店汇总", index=False)
        if len(detail_df):
            detail_df.to_excel(w, sheet_name="明细", index=False)
        else:
            pd.DataFrame({"说明": ["无命中行"]}).to_excel(w, sheet_name="明细", index=False)
        meta.to_excel(w, sheet_name="说明", index=False)

    extra_dir = ""
    if per_shop_dir.is_dir():
        extra_dir = f"\n  各店筛选明细目录: {per_shop_dir}"
    n_listed = max(0, len(summary_df) - 1)
    print(
        f"已写入: {out}\n"
        f"  参考日期={ref}  统计昨日(售后申请日)={yday}\n"
        f"  源文件数={len(files)}  汇总表列出店铺数={n_listed}  "
        f"命中合计行数={total_hits}  退款金额总计={total_amt}"
        f"{extra_dir}"
    )
    return out


def cmd_part1(args):
    raw_out = (getattr(args, "output", None) or "").strip()
    outp = None
    if raw_out:
        po = Path(raw_out)
        outp = po if po.is_absolute() else PROJECT_ROOT / po
    inp = _resolve_part1_input_dir(getattr(args, "input_dir", None))
    print(f"[part1] 输入目录: {inp}")
    run_part1(
        inp,
        outp,
        getattr(args, "reference_date", None),
        bool(getattr(args, "recursive", False)),
    )


def cmd_part3(_args):
    print("第三部分：尚未实现（占位）。可在本脚本中补充其它汇总。", file=sys.stderr)
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="拼多多下载数据后处理（多部分）")
    sub = parser.add_subparsers(dest="part")

    p1 = sub.add_parser("part1", help="第一部分：原始售后单筛选与退款汇总")
    p1.add_argument(
        "--input-dir",
        default="",
        metavar="DIR",
        help=(
            "含「*售后单*raw*.xlsx」的目录（相对路径相对项目根）。"
            "省略则默认 output/downloads/拼多多数据提取_1_<中国时区昨天，YYYY-MM-DD>"
        ),
    )
    p1.add_argument(
        "--output",
        default="",
        help=(
            "汇总 xlsx 路径（相对路径相对项目根）；默认 dailydate/pdd_part1_售后退款_<统计昨日>.xlsx。"
            "各店筛选明细另存为同目录下「<文件名不含扩展名>_筛选明细/*.xlsx」"
        ),
    )
    p1.add_argument(
        "--reference-date",
        default="",
        help="参考日期 YYYY-MM-DD（统计「昨天」= 该日 −1）；不设时默认中国时区(Asia/Shanghai)当天",
    )
    p1.add_argument(
        "--recursive",
        action="store_true",
        help="递归子目录查找售后单文件",
    )
    p1.set_defaults(func=cmd_part1)

    p2 = sub.add_parser("part2", help="第二部分：对账 zip 资金账单，按店汇总收入金额与支出等")
    p2.add_argument(
        "--input-dir",
        default="",
        metavar="DIR",
        help=(
            "含「*对账*raw*.zip」或「*对账*raw*.xlsx」的目录（相对路径相对项目根）。"
            "省略则默认 output/downloads/拼多多数据提取_1_<中国时区昨天，YYYY-MM-DD>"
        ),
    )
    p2.add_argument(
        "--output",
        default="",
        help=(
            "汇总 xlsx 路径（相对项目根）；默认 dailydate/pdd_part2_资金账单_<统计昨日>.xlsx；"
            "每店四列（店铺名称/业务描述/收入/支出，同店同描述合并为一行）另存「<文件名不含扩展名>_按店交易明细/*.xlsx」"
        ),
    )
    p2.add_argument(
        "--reference-date",
        default="",
        help="参考日期 YYYY-MM-DD（统计「昨天」= 该日 −1）；不设时默认中国时区(Asia/Shanghai)当天",
    )
    p2.add_argument(
        "--recursive",
        action="store_true",
        help="递归子目录查找对账压缩包",
    )
    p2.set_defaults(func=cmd_part2)

    p_all = sub.add_parser(
        "all",
        help="依次运行 part1 与 part2（同一 --input-dir / --reference-date；默认各输出到 dailydate）",
    )
    p_all.add_argument(
        "--input-dir",
        default="",
        metavar="DIR",
        help=(
            "下载目录（相对路径相对项目根）。"
            "省略则默认 output/downloads/拼多多数据提取_1_<中国时区昨天，YYYY-MM-DD>"
        ),
    )
    p_all.add_argument(
        "--out-part1",
        default="",
        metavar="XLSX",
        help="part1 输出路径（相对项目根）；省略则 dailydate/pdd_part1_售后退款_<统计昨日>.xlsx",
    )
    p_all.add_argument(
        "--out-part2",
        default="",
        metavar="XLSX",
        help=(
            "part2 汇总 xlsx（相对项目根）；省略则 dailydate/pdd_part2_资金账单_<统计昨日>.xlsx；"
            "每店四列汇总（含店铺名称，同业务描述合并）见同目录 _按店交易明细"
        ),
    )
    p_all.add_argument(
        "--reference-date",
        default="",
        help="参考日期 YYYY-MM-DD（统计「昨天」= 该日 −1）；不设时默认中国时区(Asia/Shanghai)当天",
    )
    p_all.add_argument(
        "--recursive",
        action="store_true",
        help="part1 / part2 均递归子目录查找源文件",
    )
    p_all.set_defaults(func=cmd_all)

    p3 = sub.add_parser("part3", help="第三部分（占位）")
    p3.set_defaults(func=cmd_part3)

    ns = parser.parse_args()
    if not getattr(ns, "part", None):
        parser.print_help()
        sys.exit(2)
    if ns.part == "part1":
        ns.reference_date = (ns.reference_date or "").strip() or None
        out = (getattr(ns, "output", None) or "").strip()
        ns.output = out or None
        ns.input_dir = (getattr(ns, "input_dir", None) or "").strip() or None
    elif ns.part == "part2":
        ns.reference_date = (ns.reference_date or "").strip() or None
        out = (getattr(ns, "output", None) or "").strip()
        ns.output = out or None
        ns.input_dir = (getattr(ns, "input_dir", None) or "").strip() or None
    elif ns.part == "all":
        ns.reference_date = (ns.reference_date or "").strip() or None
        ns.input_dir = (getattr(ns, "input_dir", None) or "").strip() or None
        ns.out_part1 = (getattr(ns, "out_part1", None) or "").strip() or None
        ns.out_part2 = (getattr(ns, "out_part2", None) or "").strip() or None
    ns.func(ns)


if __name__ == "__main__":
    main()
