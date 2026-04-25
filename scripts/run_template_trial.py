# -*- coding: utf-8 -*-
"""
依据 doc/scrape-template-jinritemai-v1.json 一类「pages + fields + interactions」模板，
连接已登录 Chrome（CDP）做试运行。

支持的操作类型（与你总结的四类对齐）：
  1) extract 文本：fields[].selector + extract.type=text；可选 extract.type=tableColumnAgg（tableSelector + alternateTableSelectors + columnHeaderMatch + aggregate sum|avg；可选 columnIndex 从 0 起指定列号，与 columnHeaderMatch 同时存在时优先 columnIndex）；在页面 table 内对数据行数值求和或算术平均；可选 fields[].alternateFieldSelector（字符串或数组）作为备选选择器链；可选 pages[].networkResponseCapture（urlSubstrings + jsonPathMap）在 goto 后从匹配的 fetch JSON 取值（先于 DOM）：保存完整响应并在全树按 jsonPathMap 叶子键匹配，优先数值/明文数字串，跳过 spider 私用区乱码；可选 --selector-hints-file 按「店铺×页×字段」记忆上次成功选择器并下次优先（--no-selector-hints 关闭）
  2) click：…；key 含 export 时优先 BrowserContext.expect_download（旧版 Playwright 无该方法则仅用 page.expect_download）；getByRoleFallback 可为单对象或数组（依次试 button/link）；仍失败则试首行内文案「下载」点击。历史报表等页若报表仍为「生成中」则无下载按钮：交互步可设 preExportReadyTimeoutMs（默认 45000）+ preExportRefreshMax（>0 时启用）在超时后 page.reload，直至出现下载控件或达到刷新次数上限。另可设 exportFailRetryWaitMs（>0 时单次尝试失败后先等待再 page.reload，重复 exportFailAttemptMax 次直至成功或达上限；用于首行点击下载失败后的重试）。
  3) dateRange：…；dateRangeStrategy=auxoCalendarPick：容器点不到、或已点开但日历面板未出现/选日失败时，若启用首页迂回（见下）则抖店首页 → 再回到资金账单 fund-detail-bill（selector 含 FUND_DETAIL_BILL 时保留同路径 query）后重试，最多多轮；否则容器阶段用 page.reload。启用条件：模板为 doc/scrape-template-jinritemai-v1.json，或页面 `auxoDateRangeRetryViaHome`:true，或交互步 `useHomeRoundtripOnAuxoCalendarMiss`:true。readonlyRangePickYesterday；readonlyRangeMinDisabledMinus2（最小灰死日 G → 点 G-2，可选 minDisabledFallbackToYesterday / postCalendarOpenWaitMs）；target.alternateOpenSelector 打开日历失败时依次再试。千川 promotion-modal-wrap 等见原说明。全局突发弹窗清理见 _try_dismiss_unexpected_overlays。
  4) selectFilter：…同上；可选 postSelectConfirmSelector + alternatePostSelectConfirmSelector（或 postSelectConfirmSelectors）：在点到 value 后**立即**点 Portal 内「确认」（避免与下一步 click 之间存在时序/浮层关闭问题）；可选 postSelectConfirmWaitVisibleMs、postSelectConfirmSkipScroll（默认 true，footer 按钮避免 scroll_into_view 超时）；可选 selectOptionClickTimeoutMs 延长在下拉内点选项的超时（默认 12000）。
  click：可选 skipScrollIntoView / noScrollBeforeClick；分页、菜单项在 portal 内时可跳过 scroll_into_view 避免 4s 超时。
  5) click（含 export 下载）：interactions[].continueOnFail 为 true 时，该步失败（含 preExport 轮询失败、click+download 失败）只记 CSV 行 ok=false，不中断试运行，继续后续 interaction / 下一 page id。
     拼多多售后「下载查询订单」在无符合条件数据时常不触发文件下载：可对含 export 的交互步设 optionalDownload=true，
     若 Playwright 仅表现为「等待 download 事件超时」等，则本步记为成功并附说明，不中断试运行。

说明：各站点日期组件实现差异大，dateRange 采用「点击容器 + 填充分离出的 input」的通用尝试；
失败时结果行会写明错误，便于你针对该页再收窄选择器或改用手动一步。
  页面级可选：postGotoWaitMs（goto 或 skip_same_url 后等待毫秒）；forceReloadOnOpen:true 时即使已同路径仍强制 goto。
  页面级 auxoDateRangeRetryViaHome:true：auxoCalendarPick 选日在面板未出或点选失败时也走「首页→本页」迂回（不限于 jinritemai-v1 文件名）。
  同路径跳过 goto：避免「上一页已 SPA 到目标 URL」后再 reload 导致列表异步未就绪（如历史报表下载）。
  navigateFromCurrent:true：不先 goto 目标 url，先执行带 beforeAccountSwitch 的 interactions（如抖店顶栏进千川等子站），再在目标域切换账号并跑其余步骤。
  千川 accountSwitcher.mode=loginShopList：登录后店铺列表内按当前轮次「千川ID」（globalAccountLoop.accounts 配 千川ID/qianchuanId）或店铺名点击；可选 fallbackToSearchOverlay 回退顶部搜索。
  页面级 preFieldExtractWaitMs：切户/进页后、执行 fields 前额外等待；「仅 fields、无后置 interaction」时还会套用 --post-interaction-wait-ms 再抽数。
  forbiddenHostSubstringsAfterTopBar：顶栏进子站后若 URL 含其中任一串则中断（如 buyin.jinritemai.com 避免进巨量百应）。
  openInNewTab / closePageWhenDone：新标签打开 url，本页流程结束后关闭该标签；失败时 finally 仍会尝试关闭。

运行（项目根目录，连接已用 CDP 打开的 Chrome，默认 http://127.0.0.1:9222）:
  1) 推荐：双击 scripts\\start_chrome_cdp_test.bat 启动专用 Chrome（9222 最稳），在本窗口登录后保持不关。
  2) 再执行：
     python scripts/run_template_trial.py
     完整运行记录写入 log/template_trial_时间戳_run.csv（列含日志时间、自运行起秒、账号、页面…）；采集指标写入 output/<runOutputSubdir>/template_trial_时间戳.xlsx（aggregateExcelFileStem 时可为 …/{stem}_{当天日期}.xlsx）。
     默认每条运行日志后即刷新 CSV、每条抽取成功的指标后即覆盖写入 Excel，便于 Ctrl+C 尽量不丢进度；可加 --no-incremental-checkpoint 改为结束时集中写入。
     runOutputSubdir 支持占位符 {run_ts}/{run_id} 等与本次运行绑定。
     若须在一次命令末尾生成 dailydate 客户交付包（无单独后处理步骤时）：加 --package-dailydate-at-end（仍须本次运行成功结束）。若使用 Streamlit 控制台且启用后处理，请在控制台流程中完成「客户交付」步骤（在后处理之后），勿与本参数同用以免重复。
     模板 aggregateExcelAutoCompassMetrics:true 时，结束后写罗盘千川汇总表（路径见模板 compassMetricsOutputPath，常与 runOutputSubdir 同目录；可用 --no-auto-compass-metrics 关闭）。
     多店 globalAccountLoop 时：采集指标与运行日志仅汇成总表——结束时写 log/template_trial_时间戳_run.csv 与 output/template_trial_时间戳.xlsx（不按店拆文件）。拼多多等模板若配置了 runOutputSubdir + downloadRunSubdirTemplate，默认下载目录为本次 run 输出根下的该子目录（与汇总 Excel 同级，不经 output/downloads）；仍用默认 output/downloads 且未配 runOutputSubdir 时行为照旧。
     默认步骤失败不中断：尽量跑完后续店铺/页面并写入运行日志 CSV 与采集 Excel；需要「遇错即停」时加 --abort-on-fail。
     加长等待用 --interaction-timeout-ms / --download-timeout-ms；导出步若在模板写了 expectDownloadTimeoutMs，则下载等待以该值为准（1–600s），不被全局 --download-timeout-ms 缩短。
     网络间歇性失败（如 net::ERR_FAILED）：可用 --goto-retry-count / --goto-retry-wait-ms 在两次 goto 之间等待并重试；可选 --pre-goto-wait-ms 在每次导航前多等一会。
     python scripts/run_template_trial.py --only-extract
     python scripts/run_template_trial.py --only-date-range --page-ids qianchuan_home_cost_roi
     python scripts/run_template_trial.py --page-ids qianchuan_home_cost_roi --accounts 账号A,账号B
     python scripts/run_template_trial.py --page-ids fxg_mshop_home --accounts 店铺A,店铺B
     拼多多仅跑全店模块D（售后下载），不改模板：--template doc/scrape-template-pdd-拼多多数据提取_1.json --page-ids pdd_login_switch,pdd_aftersale_export
     拼多多全店仅测模块D+E：--page-ids pdd_login_switch,pdd_aftersale_export,pdd_cashier_bills_reconcile
     python scripts/run_template_trial.py --global-accounts 店A,店B
     断点续跑（仅多店 globalAccountLoop）：--checkpoint log/trial.ckpt 每完成一整页即写入；
     中断后再跑：加 --resume 跳过已完成（店铺×页面）。与 --page-ids 同用时仅对过滤后的页记断点。
     python scripts/run_template_trial.py --only-account-switch
     仅千川（已手动打开千川首页并选好店铺）：python scripts/run_template_trial.py --qianchuan-standalone
  备选：沿用日常 User Data 时用 scripts\\start_chrome_cdp_with_profile.bat（部分公司策略下 9222 不会监听）。
  可选 --launch-chrome：无调试端口时自动起独立目录 Chrome（一般不用）。

影响运行速度的主要因素（排查性能时对照）：
  - 店铺数 × 每店 pageIds 数量：整体近似线性放大。
  - 网络与页面加载：单页 goto 超时、goto 重试、目标站响应、是否 skip_same_url。
  - 模板等待参数：postGotoWaitMs、postInteractionWaitMs、postFieldExtractWaitMs、preExport 轮询与 reload。
  - 交互与下载：dateRange/selectFilter/点击导出、expect_download、历史报表「生成中」轮询。
  - 字段抽取：命令行 --field-locator-timeout-ms；模板 pages[].fieldLocatorTimeoutMs 可覆盖本页单字段等待上限（毫秒，500～120000）。千川等指标渲染慢时可调大。
  - 浏览器侧：CDP 延迟、弹窗蒙层重试、多标签、千川重试 qianchuanRetryExtra。
  逐步耗时：加 --timing-log（可省略路径）写入 log/template_trial_时间戳_timing.csv。
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import date, timedelta
from datetime import datetime as dt
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import pandas as pd

try:
    import openpyxl  # noqa: F401  # 启动时预热，避免结束时首次 import 恰遇 Ctrl+C 卡在 openpyxl 内部
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_TIMING_LOG_AUTO = "__AUTO_TIMING__"

# 增量写入采集 Excel：run() 内 trial_checkpoint_bind 后，每条指标 _append_data_row 即落盘
_TRIAL_CKPT_PATH: Optional[Path] = None
_TRIAL_CKPT_TPL: Optional[dict] = None
_TRIAL_CKPT_ARGS: Optional[Any] = None
# run() 在确定 run_ts 后记一次 perf_counter，供运行日志 CSV「自运行起秒」
_TRIAL_RUN_LOG_T0_PERF: Optional[float] = None
# 运行日志逐步耗时：每次写 _result_row 时记录与上一条日志的间隔（毫秒）
_TRIAL_RUN_LOG_LAST_PERF: Optional[float] = None
# --run-root：将模板 runOutputSubdir、罗盘相对路径、默认 output/ 前缀的罗盘文件等统一到该根目录（与控制台「本次运行文件夹」对齐）
_RUN_ROOT_OVERRIDE: Optional[Path] = None


def _expand_template_output_placeholders(
    s: str,
    *,
    run_ts: str,
    yday: str,
    run_day: str,
) -> str:
    """
    模板产出路径占位符（runOutputSubdir、compassMetricsOutputPath 等）：
      {run_ts} / {run_id} 本次运行时间戳 YYYYMMDD_HHMMSS（唯一识别码）；
      {yday} 统计用昨天 YYYY-MM-DD；{yday_compact} 昨天无横线 YYYYMMDD；
      {run_day}/{run_date} 运行日当天 YYYYMMDD。
    """
    yc = (yday or "").replace("-", "").strip()[:8]
    ts = run_ts or ""
    return (
        str(s or "")
        .replace("{run_ts}", ts)
        .replace("{run_id}", ts)
        .replace("{yday}", yday or "")
        .replace("{yday_compact}", yc)
        .replace("{run_day}", run_day or "")
        .replace("{run_date}", run_day or "")
    )


def _trial_output_root(
    tpl: Optional[dict],
    *,
    run_ts: str = "",
    yday: str = "",
    run_day: str = "",
) -> Path:
    """
    模板根 runOutputSubdir：默认产出放到 output/<subdir>/；subdir 支持占位符（含 {run_ts}/{run_id}），
    可用斜杠分多层目录。未配置时为项目 output/。
    """
    global _RUN_ROOT_OVERRIDE
    if _RUN_ROOT_OVERRIDE is not None:
        try:
            _RUN_ROOT_OVERRIDE.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return _RUN_ROOT_OVERRIDE
    base = PROJECT_ROOT / "output"
    if not isinstance(tpl, dict):
        return base
    sub = str(tpl.get("runOutputSubdir") or "").strip()
    if not sub:
        return base
    exp = _expand_template_output_placeholders(sub, run_ts=run_ts, yday=yday, run_day=run_day)
    raw_parts = re.split(r"/+", exp.replace("\\", "/").strip("/"))
    parts: List[str] = []
    for p in raw_parts:
        seg = _sanitize_filename_prefix(p.strip())
        if seg:
            parts.append(seg)
    if not parts:
        return base
    root = base
    for seg in parts:
        root = root / seg
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return root


def _resolve_compass_metrics_out_path(
    tpl: Optional[dict],
    *,
    run_ts: str = "",
    yday: str = "",
    run_day: str = "",
) -> Path:
    """compassMetricsOutputPath：支持占位符；相对 runOutputSubdir；或以 output/ 开头的项目相对路径。"""
    global _RUN_ROOT_OVERRIDE
    rel = str((tpl or {}).get("compassMetricsOutputPath") or "").strip() if isinstance(tpl, dict) else ""
    if not rel:
        # 未配置时仍按 run_ts 区分文件，避免每日覆盖同一 xlsx
        if run_ts:
            rel = f"店铺罗盘千川指标表_{run_ts}.xlsx"
        else:
            if _RUN_ROOT_OVERRIDE is not None:
                return _RUN_ROOT_OVERRIDE / "店铺罗盘千川指标表.xlsx"
            return PROJECT_ROOT / "output" / "店铺罗盘千川指标表.xlsx"
    rs = _expand_template_output_placeholders(
        rel.replace("\\", "/"), run_ts=run_ts, yday=yday, run_day=run_day
    )
    p = Path(rs)
    if p.is_absolute():
        return p
    rs_norm = str(rs).replace("\\", "/")
    if rs_norm.startswith("output/"):
        if _RUN_ROOT_OVERRIDE is not None:
            tail = rs_norm[len("output/") :].lstrip("/")
            return _RUN_ROOT_OVERRIDE / tail if tail else _RUN_ROOT_OVERRIDE / "compass_metrics.xlsx"
        return PROJECT_ROOT / rs
    return (
        _trial_output_root(
            tpl if isinstance(tpl, dict) else None,
            run_ts=run_ts,
            yday=yday,
            run_day=run_day,
        )
        / rs
    )


def _load_account_credential_map(tpl: dict) -> dict:
    """
    从模板读取店铺账号映射：
    - 若配置了 accountCredentialCsv（非空），优先读 CSV，列名：店铺类型, 主账号, 密码
    - 否则若配置了 accountCredentialsFile + accountCredentialProfile，读 JSON（结构同 doc/pdd-accounts.json → profiles.<profile>）
    """
    cache = tpl.get("_account_credential_map")
    if isinstance(cache, dict):
        return cache
    p_raw = str(tpl.get("accountCredentialCsv") or "").strip()
    if p_raw:
        p = Path(p_raw)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        out: dict = {}
        try:
            with p.open("r", encoding="utf-8-sig", newline="") as f:
                rd = csv.DictReader(f)
                for r in rd:
                    if not isinstance(r, dict):
                        continue
                    n = str(r.get("店铺类型") or "").strip()
                    if not n:
                        continue
                    out[n] = {
                        "username": str(r.get("主账号") or "").strip(),
                        "password": str(r.get("密码") or "").strip(),
                    }
        except Exception:
            out = {}
        tpl["_account_credential_map"] = out
        return out

    cred_file = str(tpl.get("accountCredentialsFile") or "").strip()
    profile = str(tpl.get("accountCredentialProfile") or "").strip()
    out_json: dict = {}
    if cred_file and profile:
        try:
            p_cfg = Path(cred_file)
            if not p_cfg.is_absolute():
                p_cfg = (PROJECT_ROOT / p_cfg).resolve()
            if p_cfg.is_file():
                with p_cfg.open("r", encoding="utf-8") as f:
                    cfg_obj = json.load(f)
                rows = []
                if isinstance(cfg_obj, dict):
                    prof = cfg_obj.get("profiles")
                    if isinstance(prof, dict):
                        block = prof.get(profile)
                        if isinstance(block, list):
                            rows = block
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    n = str(item.get("name") or "").strip()
                    if not n:
                        continue
                    out_json[n] = {
                        "username": str(
                            item.get("username") or item.get("主账号") or ""
                        ).strip(),
                        "password": str(item.get("password") or item.get("密码") or "").strip(),
                    }
        except Exception:
            out_json = {}
    tpl["_account_credential_map"] = out_json
    return out_json


def _resolve_input_value(step: dict, acct: str, tpl: dict) -> Tuple[str, str]:
    """
    input 交互值来源：
    - step.value：直接写死
    - step.valueFrom=account_username|account_password：按当前店铺名从账号 CSV 取值
    """
    val = str(step.get("value") or "")
    if val:
        return val, "value"
    src = str(step.get("valueFrom") or "").strip().lower()
    if src not in {"account_username", "account_password"}:
        return "", "未配置 value/valueFrom"
    m = _load_account_credential_map(tpl if isinstance(tpl, dict) else {})
    rec = m.get(str(acct or "").strip())
    if not isinstance(rec, dict):
        return "", f"账号映射缺失：{acct}"
    if src == "account_username":
        v = str(rec.get("username") or "").strip()
        return v, "account_username"
    v = str(rec.get("password") or "").strip()
    return v, "account_password"


def _timing_records_init(args: Any, path: Optional[Path]) -> None:
    if path is not None:
        setattr(args, "_timing_records", [])
        setattr(args, "_timing_log_path", path)
    else:
        setattr(args, "_timing_records", None)
        setattr(args, "_timing_log_path", None)


def _timing_append_ms(
    args: Any,
    *,
    account: str,
    page_id: str,
    phase: str,
    step: str,
    detail: str,
    t_start: float,
) -> None:
    recs = getattr(args, "_timing_records", None)
    if recs is None:
        return
    dt_ms = (time.perf_counter() - t_start) * 1000.0
    recs.append(
        {
            "账号": (account or "")[:200],
            "页面": (page_id or "")[:120],
            "阶段": phase[:80],
            "步骤": step[:120],
            "说明": (detail or "")[:500],
            "耗时_ms": round(dt_ms, 2),
        }
    )


@contextmanager
def _timing_span(
    args: Any,
    *,
    account: str,
    page_id: str,
    phase: str,
    step: str,
    detail: str = "",
):
    recs = getattr(args, "_timing_records", None)
    if recs is None:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        _timing_append_ms(
            args,
            account=account,
            page_id=page_id,
            phase=phase,
            step=step,
            detail=detail,
            t_start=t0,
        )


def _write_timing_log_csv(path: Path, records: list, batch_id: str) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["批次", "账号", "页面", "阶段", "步骤", "说明", "耗时_ms"]
    rows_out = [{**r, "批次": batch_id} for r in records]
    pd.DataFrame(rows_out, columns=cols).to_csv(path, index=False, encoding="utf-8-sig")


def _maybe_write_timing_log(args: Any, run_ts: str) -> None:
    tp = getattr(args, "_timing_log_path", None)
    recs = getattr(args, "_timing_records", None)
    if tp is None or not recs:
        return
    _write_timing_log_csv(tp, recs, run_ts)
    print(f"已写入步骤耗时（CSV）: {tp.resolve()}（共 {len(recs)} 条）")


def _load_selector_hints(path: Path) -> dict:
    """上次 fields 抽取成功的选择器记忆（JSON 对象）；文件不存在或损坏则返回空 dict。"""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_selector_hints(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _field_selector_hint_key(
    template_hint_stem: str, pid: str, fkey: str, acct: str
) -> str:
    """记忆键：模板名::pageId::fieldKey::店铺名（无店铺时末段为 _）。"""
    part = (acct or "").strip() or "_"
    return f"{template_hint_stem}::{pid}::{fkey}::{part}"


def _field_selector_hint_lookup(
    selector_hints: dict, template_hint_stem: str, pid: str, fkey: str, acct: str
) -> Optional[str]:
    """按当前店铺查上次成功选择器；若无则回退旧格式「无店铺段」键（兼容升级前 JSON）。"""
    k = _field_selector_hint_key(template_hint_stem, pid, fkey, acct)
    v = selector_hints.get(k)
    if v is not None and str(v).strip():
        return str(v).strip()
    legacy = f"{template_hint_stem}::{pid}::{fkey}"
    if legacy != k:
        v2 = selector_hints.get(legacy)
        if v2 is not None and str(v2).strip():
            return str(v2).strip()
    return None


class TrialAbort(Exception):
    """交互/字段失败且启用中断时抛出，由 run() 捕获后写运行日志 CSV 与采集 Excel 并以非零码退出。"""


def _visible_cap_ms(args: Any) -> int:
    """0 表示不限制（仅用模板/步骤自身毫秒数）。"""
    try:
        c = int(getattr(args, "interaction_timeout_ms", 15000) or 0)
    except (TypeError, ValueError):
        c = 15000
    return max(0, c)


def _download_cap_ms(args: Any) -> int:
    raw = getattr(args, "download_timeout_ms", None)
    if raw is None:
        return _visible_cap_ms(args)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _visible_cap_ms(args)


def _cap_visible_ms(step_val: Any, default_ms: int, cap_ms: int) -> int:
    try:
        v = int(step_val)
    except (TypeError, ValueError):
        v = int(default_ms)
    v = max(1000, min(v, 600000))
    if cap_ms > 0:
        v = min(v, cap_ms)
    return v


def _cap_download_ms(step_val: Any, default_ms: int, cap_ms: int) -> int:
    try:
        v = int(step_val)
    except (TypeError, ValueError):
        v = int(default_ms)
    v = max(1000, min(v, 600000))
    if cap_ms > 0:
        v = min(v, cap_ms)
    return v


def _resolve_export_download_timeout_ms(step: Any, default_ms: int, cap_ms: int) -> int:
    """
    导出步骤：模板若显式写了 expectDownloadTimeoutMs，按该值（夹在 1000–600000）等待，
    不被 CLI 的 --download-timeout-ms 全局上限缩短；未写或无效时行为同 _cap_download_ms。
    """
    if not isinstance(step, dict):
        return _cap_download_ms(None, default_ms, cap_ms)
    raw = step.get("expectDownloadTimeoutMs")
    if raw is not None and str(raw).strip() != "":
        try:
            v = int(raw)
            return max(1000, min(v, 600000))
        except (TypeError, ValueError):
            pass
    return _cap_download_ms(step.get("expectDownloadTimeoutMs"), default_ms, cap_ms)


def _is_optional_export_no_file_err(err: str) -> bool:
    """
    optionalDownload：拼多多「下载查询订单」等在无符合条件数据时常不触发浏览器下载，
    Playwright expect_download 表现为超时等。据此与「点不到按钮」「网络断开」等区分（仅启发式）。
    """
    if not err or not str(err).strip():
        return False
    e = str(err).lower().replace("\n", " ")
    if "waiting for event" in e and "download" in e:
        return True
    if "expect_download" in e and ("timeout" in e or "timed out" in e):
        return True
    if "download" in e and ("timeout" in e or "timed out" in e):
        return True
    return False


def _is_pdd_aftersale_download_query_menuitem_wait_timeout(err: str) -> bool:
    """
    仅用于拼多多售后模块 D（pdd_aftersale_export）最后一步「下载查询订单」：
    下拉 menuitem 未在超时内变为可见时的典型 Playwright 报错。
    其它页面/其它错误不得命中（避免误触发整页刷新重跑）。
    """
    if not err or not str(err).strip():
        return False
    e = str(err)
    if "下载查询订单" not in e:
        return False
    el = e.lower()
    if "wait_for" not in el:
        return False
    if "timeout" not in el and "exceeded" not in el:
        return False
    if "menuitem" not in el:
        return False
    return True


def _abort_on_step_fail(args: Any, pid: str, acct: str, step_key: str, action: str, detail: str) -> None:
    if getattr(args, "no_abort_on_fail", True):
        return
    cap = _visible_cap_ms(args)
    dcap = _download_cap_ms(args)
    print("\n========== [试运行中断] ==========", file=sys.stderr)
    print(f"  页面 id: {pid}", file=sys.stderr)
    print(f"  账号: {acct or '(无)'}", file=sys.stderr)
    print(f"  步骤 key: {step_key}", file=sys.stderr)
    print(f"  动作: {action}", file=sys.stderr)
    print(f"  原因: {detail}", file=sys.stderr)
    if cap > 0 or dcap > 0:
        print(
            f"  等待上限: 可见/点击 {cap or '未限制'} ms，下载 {dcap or '未限制'} ms（可用 --interaction-timeout-ms / --download-timeout-ms 调整）",
            file=sys.stderr,
        )
    print("  默认已尽量跑完；若曾加 --abort-on-fail 可去掉以恢复遇错不中断。", file=sys.stderr)
    print("==================================\n", file=sys.stderr)
    raise TrialAbort()


def _page_soft_fail_enabled(page_cfg: Optional[dict]) -> bool:
    """模板 pages[].softFailPage：本页任一步失败时不中断试运行，指标写入占位符。"""
    return isinstance(page_cfg, dict) and bool(page_cfg.get("softFailPage"))


def _soft_fail_placeholder(page_cfg: Optional[dict]) -> str:
    if not isinstance(page_cfg, dict):
        return "none"
    s = str(page_cfg.get("softFailPlaceholder") or "none").strip()
    return s if s else "none"


def _soft_fail_fill_remaining_fields(
    *,
    data_rows: Optional[list],
    rows: list,
    fields: Any,
    acct: str,
    pid: str,
    placeholder: str,
    reason: str,
    already_have: set,
) -> None:
    """为尚未成功的 text 字段补写占位符（Excel）；并写 CSV 行 ok=true。"""
    if data_rows is None or not isinstance(fields, list):
        return
    for f in fields:
        if not isinstance(f, dict):
            continue
        ext = f.get("extract") or {}
        etype = str((ext.get("type") if isinstance(ext, dict) else "") or "text")
        if etype != "text":
            continue
        fkey = str(f.get("key") or f.get("label") or "")
        if not fkey or fkey in already_have:
            continue
        label = str(f.get("label") or f.get("key") or "")
        _append_data_row(data_rows, account=acct, field_key=fkey, label=label, value=placeholder)
        rows.append(
            _result_row(
                page_id=pid,
                account=acct,
                phase="field",
                key=label or fkey,
                action="extract:text",
                detail=f"{placeholder}（softFailPage：{reason}）",
                ok=True,
            )
        )


def _nav_fail_try_soft_fill(
    pg_inner: dict,
    pid: str,
    acct: str,
    flds: Any,
    data_rows: Optional[list],
    rows: list,
    reason: str,
) -> None:
    """goto/切户等失败、无法进入 interactions 时，若 softFailPage 则仍补写占位符。"""
    if not _page_soft_fail_enabled(pg_inner if isinstance(pg_inner, dict) else None):
        return
    ph = _soft_fail_placeholder(pg_inner if isinstance(pg_inner, dict) else None)
    _soft_fail_fill_remaining_fields(
        data_rows=data_rows,
        rows=rows,
        fields=flds,
        acct=acct,
        pid=pid,
        placeholder=ph,
        reason=reason,
        already_have=set(),
    )


def _fill_qianchuan_skipped_no_id(
    pg_inner: dict,
    pid: str,
    acct: str,
    flds: Any,
    data_rows: Optional[list],
    rows: list,
) -> None:
    """globalAccountLoop 已启用千川ID策略但本店未配千川ID：不写千川页指标，Excel 数据值填字符串 None。"""
    if data_rows is None or not isinstance(flds, list):
        return
    reason = "未配置千川ID，跳过千川页"
    for f in flds:
        if not isinstance(f, dict):
            continue
        ext = f.get("extract") or {}
        etype = str((ext.get("type") if isinstance(ext, dict) else "") or "text")
        if etype != "text":
            continue
        fkey = str(f.get("key") or f.get("label") or "")
        if not fkey:
            continue
        label = str(f.get("label") or f.get("key") or "")
        _append_data_row(data_rows, account=acct, field_key=fkey, label=label, value="None")
        rows.append(
            _result_row(
                page_id=pid,
                account=acct,
                phase="field",
                key=label or fkey,
                action="extract:text",
                detail=f"None（{reason}）",
                ok=True,
            )
        )


def _qianchuan_retry_eligible(gal: dict, qc_ov: Any) -> bool:
    """仅当模板启用千川 ID 映射且本店有非空千川 ID 时允许千川页自动重试。"""
    if not isinstance(gal, dict):
        return False
    qcb = gal.get("qianchuanByAccount")
    if not isinstance(qcb, dict):
        return False
    return isinstance(qc_ov, str) and bool(qc_ov.strip())


def _qianchuan_extract_all_real(
    data_rows: Optional[list], account: str, pg_inner: dict
) -> bool:
    """千川页 fields（extract:text）是否均已写入非占位、非跳过类数据值。"""
    if data_rows is None:
        return False
    flds = pg_inner.get("fields") if isinstance(pg_inner, dict) else None
    if not isinstance(flds, list):
        return False
    keys: list = []
    for f in flds:
        if not isinstance(f, dict):
            continue
        ext = f.get("extract") or {}
        etype = str((ext.get("type") if isinstance(ext, dict) else "") or "text")
        if etype != "text":
            continue
        k = str(f.get("key") or "").strip()
        if k:
            keys.append(k)
    if not keys:
        return True
    ph = (_soft_fail_placeholder(pg_inner) or "none").strip().lower()
    ac = (account or "").strip()
    got = {k: False for k in keys}
    for r in data_rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("店铺名") or "").strip() != ac:
            continue
        rk = str(r.get("键") or "").strip()
        if rk not in got:
            continue
        v = r.get("数据值")
        vs = "" if v is None else str(v).strip()
        if not vs:
            continue
        if vs.lower() == ph:
            continue
        if vs == "None":
            continue
        got[rk] = True
    return all(got.values())


def _qianchuan_first_metric_is_empty_dash(text: Optional[str]) -> bool:
    """
    千川成本卡首项（如整体消耗）无数据时页面常显示为「--」类双横线，而非数字。
    命中则三指标统一记 0，不再继续抽取后续字段。
    """
    s = (text or "").strip()
    if len(s) < 2:
        return False
    t = re.sub(r"\s+", "", s)
    if len(t) != 2:
        return False
    # ASCII 与常见全角/长横线等「横线类」字符
    dash_chars = set("-‐‑‒–—―−﹣－‾")
    return all((c in dash_chars) for c in t)


def _qianchuan_fill_zeros_no_data(
    fields: Any,
    *,
    acct: str,
    pid: str,
    data_rows: Optional[list],
    rows: list,
) -> None:
    """千川首项为 -- 时，为所有 extract:text 字段写入 0。"""
    if data_rows is None or not isinstance(fields, list):
        return
    reason = "千川首项为「--」类无数据占位，三指标填 0"
    for f in fields:
        if not isinstance(f, dict):
            continue
        ext = f.get("extract") or {}
        etype = str((ext.get("type") if isinstance(ext, dict) else "") or "text")
        if etype != "text":
            continue
        fkey = str(f.get("key") or f.get("label") or "").strip()
        label = str(f.get("label") or f.get("key") or "").strip()
        if not fkey:
            continue
        _append_data_row(
            data_rows, account=acct, field_key=fkey, label=label or fkey, value="0"
        )
        rows.append(
            _result_row(
                page_id=pid,
                account=acct,
                phase="field",
                key=label or fkey,
                action="extract:text",
                detail=f"0  ← {reason}",
                ok=True,
            )
        )


def _run_qianchuan_page_with_retries(
    page: Any,
    args: Any,
    tpl: dict,
    pid: str,
    acct: str,
    pg_inner: dict,
    rows: list,
    download_dir: Path,
    network_json_dir: Path,
    yday: str,
    data_rows: Optional[list],
    download_filename_prefix: str,
    qc_ov: str,
    *,
    selector_hints: Optional[dict] = None,
    template_hint_stem: str = "",
    hints_dirty: Optional[list] = None,
) -> bool:
    """
    千川页：最多「首次 + qianchuanRetryExtra」次尝试（见 pages[].qianchuanRetryExtra，缺省用模块 _QIANCHUAN_RETRY_EXTRA），间隔 _QIANCHUAN_RETRY_WAIT_MS。
    失败且仍有重试次数时回滚本次产生的 rows / data_rows 尾部再试；用尽仍失败返回 False。
    """
    extra = _qianchuan_retry_extra_for_page(pg_inner)
    total = 1 + extra
    wait_ms = max(0, min(int(_QIANCHUAN_RETRY_WAIT_MS), 600000))
    for attempt in range(total):
        row_start = len(rows)
        data_start = len(data_rows) if data_rows is not None else 0
        play_ok = False
        try:
            play_ok = _template_page_goto_switch_play(
                page,
                args,
                tpl,
                pid,
                acct,
                pg_inner,
                rows,
                download_dir,
                network_json_dir,
                yday,
                data_rows=data_rows,
                download_filename_prefix=download_filename_prefix,
                qianchuan_switch_override=qc_ov,
                selector_hints=selector_hints,
                template_hint_stem=template_hint_stem,
                hints_dirty=hints_dirty,
            )
        except TrialAbort:
            play_ok = False
        data_ok = play_ok and _qianchuan_extract_all_real(data_rows, acct, pg_inner)
        if data_ok:
            if attempt > 0:
                rows.append(
                    _result_row(
                        page_id=pid,
                        phase="pipeline",
                        key="qianchuan_retry",
                        action="retry_success",
                        detail=f"第 {attempt + 1}/{total} 次尝试后千川指标已齐",
                        ok=True,
                        account=acct,
                    )
                )
            return True
        will_retry = attempt < total - 1
        if will_retry:
            del rows[row_start:]
            if data_rows is not None:
                del data_rows[data_start:]
            rows.append(
                _result_row(
                    page_id=pid,
                    phase="pipeline",
                    key="qianchuan_retry",
                    action="retry_wait",
                    detail=f"千川页未成功或指标不齐，{wait_ms}ms 后进行第 {attempt + 2}/{total} 次尝试",
                    ok=False,
                    account=acct,
                )
            )
            try:
                page.wait_for_timeout(wait_ms)
            except Exception:
                pass
        else:
            rows.append(
                _result_row(
                    page_id=pid,
                    phase="pipeline",
                    key="qianchuan_retry",
                    action="retry_exhausted",
                    detail=f"千川页已尝试 {total} 次仍失败或指标未齐",
                    ok=False,
                    account=acct,
                )
            )
            return False
    return False


def _cdp_port(cdp: str) -> int:
    raw = (cdp or "").strip()
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    u = urlparse(raw)
    if u.port is not None:
        return int(u.port)
    return 9222


def _yesterday_str() -> str:
    d = date.today() - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _yesterday_date() -> date:
    return date.today() - timedelta(days=1)


def _resolve_runtime_url(raw_url: str) -> str:
    """
    运行时 URL 占位符替换：
    - {{yday}} 或 {yday} -> 昨天（YYYY-MM-DD）
    - %7Byday%7D：若在 _merge_qianchuan_aavid_into_url 之后才替换，dr 里的花括号已被 urlencode，
      需兜底替换（否则会原样进地址栏，千川报「时间解析失败」）。
    """
    u = str(raw_url or "").strip()
    if not u:
        return ""
    yday = _yesterday_str()
    u = u.replace("{{yday}}", yday)
    u = u.replace("{yday}", yday)
    u = u.replace("%7Byday%7D", yday)
    u = u.replace("%7byday%7d", yday)
    return u


def _render_download_name_template(
    tmpl: str,
    *,
    account: str,
    yday: str,
    task_name: str,
    suggested: str,
) -> str:
    t = str(tmpl or "").strip()
    if not t:
        return ""
    ext = Path(suggested).suffix or ".xlsx"
    base = Path(suggested).stem or "download"
    out = (
        t.replace("{account}", _sanitize_filename_prefix(account or ""))
        .replace("{yday}", yday or "")
        .replace("{date}", yday or "")
        .replace("{task_name}", _sanitize_filename_prefix(task_name or ""))
        .replace("{suggested_name}", _sanitize_filename_prefix(base))
        .replace("{ext}", ext)
    )
    if "{ext}" not in t and not out.lower().endswith(ext.lower()):
        out = out + ext
    return out


def _parse_title_date(s: str) -> Optional[date]:
    if not s:
        return None
    s = s.strip()[:10]
    if len(s) == 10 and s[4:5] == "-" and s[7:8] == "-":
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    return None


def _load_template(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("模板顶层应为对象")
    return raw


def _sanitize_filename_prefix(name: str, *, max_len: int = 80) -> str:
    """当前轮次店铺名等，用作保存文件名的前缀（去掉 Windows 非法字符）。"""
    s = (name or "").strip()
    if not s:
        return ""
    s = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]', "_", s)
    s = s.strip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s or "account"


def _result_row(
    *,
    page_id: str,
    phase: str,
    key: str,
    action: str,
    detail: str,
    ok: bool,
    account: str = "",
) -> dict:
    wall = dt.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed_s = ""
    step_ms = ""
    global _TRIAL_RUN_LOG_T0_PERF
    global _TRIAL_RUN_LOG_LAST_PERF
    try:
        now_perf = time.perf_counter()
        if _TRIAL_RUN_LOG_T0_PERF is not None:
            elapsed_s = f"{now_perf - _TRIAL_RUN_LOG_T0_PERF:.3f}"
        if _TRIAL_RUN_LOG_LAST_PERF is not None:
            step_ms = f"{(now_perf - _TRIAL_RUN_LOG_LAST_PERF) * 1000.0:.2f}"
        _TRIAL_RUN_LOG_LAST_PERF = now_perf
    except Exception:
        pass
    return {
        "日志时间": wall,
        "自运行起秒": elapsed_s,
        "步骤耗时_ms": step_ms,
        "账号": account or "",
        "页面": page_id,
        "阶段": phase,
        "键/标签": key,
        "动作": action,
        "结果": detail,
        "是否成功": "是" if ok else "否",
    }


def trial_checkpoint_bind(excel_out: Path, tpl: Optional[dict], args: Any) -> None:
    """与本次 run 的采集 Excel 绑定，供 _append_data_row 增量落盘。"""
    global _TRIAL_CKPT_PATH, _TRIAL_CKPT_TPL, _TRIAL_CKPT_ARGS
    _TRIAL_CKPT_PATH = excel_out
    _TRIAL_CKPT_TPL = tpl if isinstance(tpl, dict) else None
    _TRIAL_CKPT_ARGS = args


def trial_checkpoint_clear() -> None:
    global _TRIAL_CKPT_PATH, _TRIAL_CKPT_TPL, _TRIAL_CKPT_ARGS, _TRIAL_RUN_LOG_T0_PERF
    global _TRIAL_RUN_LOG_LAST_PERF
    _TRIAL_CKPT_PATH = None
    _TRIAL_CKPT_TPL = None
    _TRIAL_CKPT_ARGS = None
    _TRIAL_RUN_LOG_T0_PERF = None
    _TRIAL_RUN_LOG_LAST_PERF = None


def _trial_checkpoint_maybe_write(data_rows: list) -> None:
    """每条指标写入 data_rows 后调用；依赖先 trial_checkpoint_bind。"""
    global _TRIAL_CKPT_PATH, _TRIAL_CKPT_TPL, _TRIAL_CKPT_ARGS
    if _TRIAL_CKPT_PATH is None:
        return
    if _TRIAL_CKPT_ARGS is not None and getattr(_TRIAL_CKPT_ARGS, "no_incremental_checkpoint", False):
        return
    try:
        _write_data_excel(_TRIAL_CKPT_PATH, data_rows, _TRIAL_CKPT_TPL)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        print(f"[注意] 增量保存采集表失败（将继续运行，结束时再写）: {e}", file=sys.stderr)


def _append_data_row(
    data_rows: Optional[list],
    *,
    account: str,
    field_key: str,
    label: str,
    value: str,
) -> None:
    """仅成功抽取的指标写入 Excel（与完整运行日志分离）；键、标签来自模板 fields[].key / label。"""
    if data_rows is None:
        return
    data_rows.append(
        {
            "店铺名": account or "",
            "键": (field_key or "").strip(),
            "标签": (label or "").strip(),
            "数据值": value,
        }
    )
    _trial_checkpoint_maybe_write(data_rows)


def _write_run_log_csv(path: Path, rows: list) -> None:
    """完整试运行过程（goto/切店/交互/字段成败）写入 CSV，非 Excel。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["日志时间", "自运行起秒", "步骤耗时_ms", "账号", "页面", "阶段", "键/标签", "动作", "结果", "是否成功"]
    if not rows:
        pd.DataFrame(columns=cols).to_csv(path, index=False, encoding="utf-8-sig")
        return
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


class _RunLogCsvFlushList(list):
    """每条运行日志追加后立即写 template_trial_*_run.csv，降低中断丢日志概率。"""

    def __init__(self, path: Path):
        super().__init__()
        self._run_log_path = path

    def append(self, item):  # type: ignore[override]
        super().append(item)
        try:
            _write_run_log_csv(self._run_log_path, self)
        except KeyboardInterrupt:
            raise
        except BaseException:
            pass


def _atomic_df_to_excel(path: Path, df: "pd.DataFrame") -> Path:
    """
    先写临时文件再 os.replace 覆盖目标。
    若目标被占用（WinError 5），写入同目录「原名_已写入_时间戳.xlsx」并返回该路径。
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
            print(
                f"[注意] 采集表原路径无法写入，已保存到: {alt.resolve()}",
                file=sys.stderr,
            )
            return alt
        except Exception:
            raise

    try:
        os.replace(tmp, path)
        return path
    except (OSError, PermissionError):
        try:
            os.replace(tmp, alt)
            print(
                f"[注意] 原文件被占用（请关闭 WPS/Excel），完整结果已写入: {alt.resolve()}",
                file=sys.stderr,
            )
            return alt
        except Exception:
            try:
                df.to_excel(alt, index=False, engine="openpyxl")
            finally:
                _cleanup_t()
            print(
                f"[注意] 原文件被占用，完整结果已写入: {alt.resolve()}",
                file=sys.stderr,
            )
            return alt


def _build_wide_data_df(data_rows: list, metric_cfg: list) -> "pd.DataFrame":
    """
    将长表（店铺名/键/标签/数据值）转为宽表（一店一行）。
    metric_cfg: [{"key":"...", "label":"列名"}]，按给定顺序输出列。
    """
    cols = ["店铺名", "键", "标签", "数据值"]
    if not data_rows:
        head = ["店铺名"] + [str((x or {}).get("label") or (x or {}).get("key") or "").strip() for x in metric_cfg]
        head = [x for x in head if x]
        return pd.DataFrame(columns=head if head else ["店铺名"])
    df = pd.DataFrame(data_rows).reindex(columns=cols)
    df["_ord"] = range(len(df))
    # 同店同键取最后一次有效值
    df = df.sort_values("_ord").drop_duplicates(subset=["店铺名", "键"], keep="last")
    shop_order = [str(x) for x in df["店铺名"].tolist() if str(x or "").strip()]
    shop_order = list(dict.fromkeys(shop_order))
    out = pd.DataFrame({"店铺名": shop_order})
    work = df[["店铺名", "键", "数据值"]].copy()
    key_to_col: dict = {}
    for mc in metric_cfg:
        if not isinstance(mc, dict):
            continue
        k = str(mc.get("key") or "").strip()
        if not k:
            continue
        cn = str(mc.get("label") or mc.get("column") or k).strip()
        key_to_col[k] = cn or k
    if not key_to_col:
        # 未配置指标顺序时，按当前出现顺序展开所有 key
        key_order = list(dict.fromkeys([str(x) for x in work["键"].tolist() if str(x).strip()]))
        key_to_col = {k: k for k in key_order}
    for k, cn in key_to_col.items():
        sub = work[work["键"] == k][["店铺名", "数据值"]].rename(columns={"数据值": cn})
        out = out.merge(sub, on="店铺名", how="left")
    return out


def _write_data_excel(path: Path, data_rows: list, tpl: Optional[dict] = None) -> None:
    """写采集结果：默认长表；模板 aggregateExcelLayout=wideByShop 时写宽表。"""
    cols = ["店铺名", "键", "标签", "数据值"]
    layout = str((tpl or {}).get("aggregateExcelLayout") or "").strip().lower()
    if layout == "widebyshop":
        metric_cfg = (tpl or {}).get("aggregateExcelMetricColumns") or []
        if not isinstance(metric_cfg, list):
            metric_cfg = []
        df_out = _build_wide_data_df(data_rows, metric_cfg)
        _atomic_df_to_excel(path, df_out)
        return
    if not data_rows:
        _atomic_df_to_excel(path, pd.DataFrame(columns=cols))
        return
    df = pd.DataFrame(data_rows)
    df = df.reindex(columns=cols)
    _atomic_df_to_excel(path, df)


def _maybe_write_compass_metrics_from_trial_rows(
    tpl: Optional[dict],
    data_rows: list,
    args: Any,
    *,
    run_ts: str = "",
    yday: str = "",
    run_day: str = "",
) -> None:
    """
    模板根 aggregateExcelAutoCompassMetrics 为 true 时：用 fill_compass_metrics_from_blob 同源逻辑，
    将内存中长表直接解析为「店铺/罗盘三项/千川三项」宽表并写入 compassMetricsOutputPath（支持 {run_ts} 等占位符）。
    """
    if not data_rows:
        return
    if getattr(args, "no_auto_compass_metrics", False):
        return
    if not isinstance(tpl, dict):
        return
    raw = tpl.get("aggregateExcelAutoCompassMetrics")
    if raw is not True:
        rs = str(raw or "").strip().lower()
        if rs not in ("1", "yes", "true"):
            return
    out = _resolve_compass_metrics_out_path(
        tpl, run_ts=run_ts, yday=yday, run_day=run_day
    )
    merge_tpl = bool(tpl.get("compassMergeTemplateShops"))
    try:
        from fill_compass_metrics_from_blob import write_compass_metrics_from_data_rows

        filled, written = write_compass_metrics_from_data_rows(
            data_rows, out, merge_template_shops=merge_tpl
        )
        print(
            f"[罗盘千川汇总] 已写入 {written.resolve()}（{len(filled)} 店；列：店铺、罗盘支付金额、罗盘成交订单数、客单价、千川消耗、千川净成交订单数、净成交roi）"
        )
    except Exception as e:
        print(
            f"[罗盘千川汇总] 自动生成失败，可手动: python scripts/fill_compass_metrics_from_blob.py --input <template_trial.xlsx>。原因: {e}",
            file=sys.stderr,
        )


def _maybe_package_dailydate_cli_flag(
    tpl: Optional[dict],
    tpl_path: Path,
    excel_out: Path,
    download_dir: Path,
    *,
    run_ts: str,
    yday: str,
    run_day: str,
    args: Any,
    interrupted: bool,
    aborted: bool,
) -> None:
    """命令行 --package-dailydate-at-end：试运行成功后写入 dailydate/（见 package_dailydate_deliverable.py）。"""
    if interrupted or aborted:
        return
    if not getattr(args, "package_dailydate_at_end", False):
        return
    if not isinstance(tpl, dict):
        return
    root_raw = str(getattr(args, "package_dailydate_root", "") or "").strip() or "dailydate"
    dr = Path(root_raw)
    if not dr.is_absolute():
        dr = PROJECT_ROOT / dr
    folder_pat = str(getattr(args, "package_dailydate_folder_pattern", "") or "").strip()
    if not folder_pat:
        folder_pat = "{run_day}_{run_output_subdir}_{run_ts}"
    zip_pat = str(getattr(args, "package_dailydate_zip_pattern", "") or "").strip()
    if not zip_pat:
        zip_pat = "网页导出等附件_{run_ts}"
    auto_compass = not getattr(args, "package_dailydate_no_compass", False)

    try:
        from package_dailydate_deliverable import package_client_deliverable
    except Exception as e:
        print(f"[客户交付] 无法加载 package_dailydate_deliverable: {e}", file=sys.stderr)
        return

    try:
        _out, logs = package_client_deliverable(
            excel_out,
            download_dir,
            dailydate_root=dr,
            run_ts=run_ts,
            run_day=run_day,
            yday=yday,
            tpl=tpl,
            template_path=tpl_path,
            task_name=str(getattr(args, "package_task_name", "") or "").strip(),
            task_slug=str(getattr(args, "package_task_slug", "") or "").strip(),
            folder_name_pattern=folder_pat,
            zip_basename_pattern=zip_pat,
            auto_compass_copy=bool(auto_compass),
            readme=not getattr(args, "package_dailydate_no_readme", False),
        )
        for line in logs:
            print(f"[客户交付] {line}")
    except Exception as e:
        print(f"[客户交付] 打包失败（不影响采集结果文件）: {e}", file=sys.stderr)


def _read_existing_excel_metrics(path: Path) -> list:
    """断点续跑：读入已有采集 Excel，与新抽取行合并后再写回（列须含 店铺名、键、标签、数据值）。"""
    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception:
        return []
    if df is None or df.empty:
        return []
    cols = ["店铺名", "键", "标签", "数据值"]
    if not all(c in df.columns for c in cols):
        return []
    out: list = []
    for _, row in df.iterrows():
        v = row.get("数据值")
        if pd.isna(v):
            v_str = ""
        else:
            v_str = str(v).strip() if not isinstance(v, str) else v.strip()
        out.append(
            {
                "店铺名": str(row.get("店铺名") or "").strip(),
                "键": str(row.get("键") or "").strip(),
                "标签": str(row.get("标签") or "").strip(),
                "数据值": v_str,
            }
        )
    return out


def _checkpoint_pair(account: str, page_id: str) -> Tuple[str, str]:
    return ((account or "").strip(), (page_id or "").strip())


def _checkpoint_read_raw(path: Path) -> Tuple[Optional[str], Optional[str], set]:
    """
    读取断点。返回 (lastCompletedAccount 或 None, 模板路径或 None, 旧版 v1 的 (店铺,pageId) 集合)。
    """
    if not path.is_file():
        return None, None, set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None, set()
    if not isinstance(raw, dict):
        return None, None, set()
    st = raw.get("template")
    tpl_s = str(st).strip() if st else None
    g = raw.get("globalAccountLoop")
    last_ca: Optional[str] = None
    done_v1: set = set()
    if isinstance(g, dict):
        lc = g.get("lastCompletedAccount") or g.get("last_completed_account")
        if lc and str(lc).strip():
            last_ca = str(lc).strip()
        comp = g.get("completed")
        if isinstance(comp, list):
            for it in comp:
                if not isinstance(it, dict):
                    continue
                a = str(it.get("account") or "").strip()
                p = str(it.get("pageId") or it.get("page_id") or "").strip()
                if a and p:
                    done_v1.add((a, p))
    return last_ca, tpl_s, done_v1


def _checkpoint_infer_last_full_from_v1(
    done_pairs: set,
    accounts: list,
    page_ids: list,
    page_id_allow: Optional[set],
) -> Optional[str]:
    """旧版按页记录时：按 accounts 顺序找「该店 pageIds 全部出现在 done 中」的最后一家。"""
    pids = [p for p in page_ids if page_id_allow is None or p in page_id_allow]
    if not pids or not done_pairs:
        return None
    last_full: Optional[str] = None
    for acct in accounts:
        a = (acct or "").strip()
        if not a:
            continue
        if not all((a, p) in done_pairs for p in pids):
            break
        last_full = a
    return last_full


def _checkpoint_resume_start_index(
    path: Optional[Path],
    resume: bool,
    accounts: list,
    page_ids: list,
    page_id_allow: Optional[set],
) -> Tuple[int, Optional[str]]:
    """
    续跑时从「下一家」店铺下标开始：lastCompletedAccount 为上一轮整店成功的最后一家。
    返回 (start_index, 用于提示的 last_completed 或 None)。
    """
    if not resume or path is None or not path.is_file():
        return 0, None
    last_stored, _, v1_done = _checkpoint_read_raw(path)
    last_ca = last_stored
    if not last_ca and v1_done:
        last_ca = _checkpoint_infer_last_full_from_v1(v1_done, accounts, page_ids, page_id_allow)
    if not last_ca:
        return 0, None
    target = last_ca.strip()
    for i, a in enumerate(accounts):
        if (a or "").strip() == target:
            return i + 1, last_ca
    print(
        f"[断点续跑] 警告: 断点中的店铺名「{target}」不在当前轮次店铺列表中，将从第一家重跑。",
        file=sys.stderr,
    )
    return 0, last_ca


def _checkpoint_write_last_completed_account(path: Path, template_path: Path, account: str) -> None:
    """记录「整店所有 pageIds 已成功跑完」的最后一家（version 2，仅 lastCompletedAccount）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "template": str(template_path.resolve()),
        "globalAccountLoop": {
            "lastCompletedAccount": (account or "").strip(),
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


_CLI_ACCOUNT_PAGE_IDS = frozenset(
    {
        "qianchuan_home_cost_roi",
        "fxg_mshop_home",
        "fxg_aftersale_fund_detail_bill",
        "fxg_bill_history_report",
        "fxg_aftersale_order_list_export",
    }
)

# globalAccountLoop 下千川页：None=未配置千川ID（不写 goto/不切户，Excel 填 None）；str=按该串切户；UNSET=兼容旧模板（仍用店铺名）
_QC_SWITCH_OVERRIDE_UNSET = object()
# 已配置千川 ID 的店：千川页 goto/抽数失败时可重试；默认 0（不重试）。模板 pages[].qianchuanRetryExtra 可覆盖（0～10）
_QIANCHUAN_RETRY_EXTRA = 0
_QIANCHUAN_RETRY_WAIT_MS = 2000


def _qianchuan_retry_extra_for_page(pg_inner: Optional[dict]) -> int:
    """读取 pages[].qianchuanRetryExtra；缺省用模块默认 _QIANCHUAN_RETRY_EXTRA。"""
    raw = (pg_inner or {}).get("qianchuanRetryExtra")
    if raw is None:
        try:
            return max(0, min(10, int(_QIANCHUAN_RETRY_EXTRA)))
        except (TypeError, ValueError):
            return 0
    try:
        return max(0, min(10, int(raw)))
    except (TypeError, ValueError):
        return 0


def _raw_account_qianchuan_id(acc_obj: dict) -> str:
    if not isinstance(acc_obj, dict):
        return ""
    for k in ("千川ID", "qianchuanId", "qianchuan_id"):
        v = acc_obj.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _template_accounts_any_qianchuan_id(ra: Any) -> bool:
    if not isinstance(ra, list):
        return False
    for x in ra:
        if isinstance(x, dict) and _raw_account_qianchuan_id(x):
            return True
    return False


def _build_qianchuan_by_account_map(
    raw_accounts: Any, account_names: list
) -> Tuple[Optional[dict], bool]:
    """
    若模板中至少一条 account 配置了非空千川ID，则启用「按 ID」策略：未配千川ID的店在千川页跳过并写 Excel 为 None。
    否则返回 (None, False)，千川仍按店铺名切换（旧行为）。
    """
    if not isinstance(raw_accounts, list) or not account_names:
        return None, False
    if not _template_accounts_any_qianchuan_id(raw_accounts):
        return None, False
    name_to_obj: dict = {}
    for x in raw_accounts:
        if isinstance(x, dict):
            n = str(x.get("name") or x.get("shopName") or "").strip()
            if n:
                name_to_obj[n] = x
    out: dict = {}
    for name in account_names:
        nm = (name or "").strip()
        obj = name_to_obj.get(nm)
        q = _raw_account_qianchuan_id(obj) if isinstance(obj, dict) else ""
        out[nm] = q if q else None
    return out, True


def _accounts_for_page(pg: dict, args: Any) -> list:
    """模板 pages[].runAccounts；--accounts 仅作用于支持多账号的 page id（见 _CLI_ACCOUNT_PAGE_IDS）。"""
    pid = str(pg.get("id") or "")
    cli = (getattr(args, "accounts", "") or "").strip()
    ra = pg.get("runAccounts")
    tpl_list = (
        [str(x).strip() for x in ra if str(x).strip()]
        if isinstance(ra, list)
        else []
    )
    if cli and pid in _CLI_ACCOUNT_PAGE_IDS:
        return [x.strip() for x in cli.split(",") if x.strip()]
    return tpl_list


def _cdp_pick_work_page(context: Any, *, prefer: str = "fxg") -> Any:
    """
    CDP 连接后选用要操作的标签页。
    prefer=fxg：优先抖店 PC 后台域名（默认）。
    prefer=qianchuan：优先巨量千川域名（--qianchuan-standalone 时使用，便于你已手动打开千川）。
    """
    pages = list(context.pages)
    if not pages:
        return context.new_page()
    if prefer == "qianchuan":
        for p in reversed(pages):
            try:
                u = (p.url or "").lower()
                if "qianchuan.jinritemai.com" in u:
                    try:
                        p.bring_to_front()
                    except Exception:
                        pass
                    return p
            except Exception:
                continue
    for p in reversed(pages):
        try:
            u = (p.url or "").lower()
            if "fxg.jinritemai.com" in u or "jinritemai.com/ffa/" in u:
                try:
                    p.bring_to_front()
                except Exception:
                    pass
                return p
        except Exception:
            continue
    p = pages[-1]
    try:
        p.bring_to_front()
    except Exception:
        pass
    return p


def _urls_same_path(a: str, b: str) -> bool:
    """是否视为同一文档路径（忽略 query/hash）；用于避免 SPA 已跳转后再次 goto 整页重载。"""
    pa, pb = urlparse((a or "").strip()), urlparse((b or "").strip())
    return (pa.scheme, pa.netloc, pa.path.rstrip("/")) == (pb.scheme, pb.netloc, pb.path.rstrip("/"))


def _url_query_param_first(url: str, key: str) -> str:
    """取 URL query 中某键的首个值（大小写敏感键名）。"""
    try:
        for k, v in parse_qsl(urlparse((url or "").strip()).query, keep_blank_values=True):
            if k == key:
                return v or ""
    except Exception:
        pass
    return ""


def _merge_qianchuan_aavid_into_url(url: str, aavid: str) -> str:
    """
    在千川域名 URL 上写入/覆盖 query 参数 aavid（巨量常用账户直达参数）。
    不附带 utm/btm 等追踪参数；其它 query 键保留。
    aavid 置于 query 首位（与浏览器里常见可用链接形如 ?aavid=…&dr=… 一致，避免个别前端对参数顺序敏感）。
    """
    aavid = (aavid or "").strip()
    u = (url or "").strip()
    if not aavid or not u:
        return u
    if "qianchuan.jinritemai.com" not in u.lower():
        return u
    parts = urlparse(u)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "aavid"]
    pairs.insert(0, ("aavid", aavid))
    new_q = urlencode(pairs)
    return urlunparse(
        (parts.scheme, parts.netloc, parts.path, parts.params, new_q, parts.fragment)
    )


def _qianchuan_same_url_skip_goto_ok(cur: str, target: str) -> bool:
    """
    与 _urls_same_path 联用：千川同为 /uni-prom、/home 等 path 时，
    - 若 target 含 aavid 且与当前页不一致，不可 skip；
    - 若 target 含 dr（日期范围）且与当前页不一致，不可 skip（否则 SPA 仍停留在旧统计日）。
    """
    cl = (cur or "").lower()
    tl = (target or "").lower()
    if "qianchuan.jinritemai.com" not in cl or "qianchuan.jinritemai.com" not in tl:
        return True
    dr_t = _url_query_param_first(target, "dr")
    if dr_t:
        dr_c = _url_query_param_first(cur, "dr")
        if unquote(dr_c).strip() != unquote(dr_t).strip():
            return False
    av_t = _url_query_param_first(target, "aavid")
    if not av_t:
        return True
    av_c = _url_query_param_first(cur, "aavid")
    return av_c == av_t


def _off_fxg_topbar_context(page_url: str) -> bool:
    """当前 URL 已离开抖店主壳（千川等子站），顶栏无抖店 leftBar 时需先回 preSwitchUrl。"""
    pl = (page_url or "").lower()
    if "compass.jinritemai.com" in pl or "qianchuan.jinritemai.com" in pl:
        return True
    return False


def _page_goto(
    page: Any,
    target: str,
    *,
    page_id: str,
    acct: str,
    args: Any,
    rows: list,
) -> bool:
    u = _resolve_runtime_url(target)
    if not u:
        return True
    try:
        to = int(getattr(args, "goto_timeout_ms", 90000) or 90000)
    except (TypeError, ValueError):
        to = 90000
    to = max(1000, min(to, 600000))
    try:
        pre = int(getattr(args, "pre_goto_wait_ms", 0) or 0)
    except (TypeError, ValueError):
        pre = 0
    pre = max(0, min(pre, 120000))
    try:
        retries = int(getattr(args, "goto_retry_count", 0) or 0)
    except (TypeError, ValueError):
        retries = 0
    retries = max(0, min(retries, 10))
    try:
        gap = int(getattr(args, "goto_retry_wait_ms", 3000) or 0)
    except (TypeError, ValueError):
        gap = 3000
    gap = max(0, min(gap, 120000))

    if pre > 0:
        try:
            page.wait_for_timeout(pre)
        except Exception:
            pass

    last_err: Optional[Exception] = None
    attempts = 1 + retries
    for attempt in range(attempts):
        try:
            page.goto(u, wait_until="domcontentloaded", timeout=to)
            rows.append(
                _result_row(
                    page_id=page_id,
                    phase="nav",
                    key="goto",
                    action="open_url",
                    detail=u,
                    ok=True,
                    account=acct,
                )
            )
            return True
        except Exception as e:
            last_err = e
            if attempt < attempts - 1 and gap > 0:
                try:
                    page.wait_for_timeout(gap)
                except Exception:
                    pass

    err_s = str(last_err) if last_err else "unknown"
    if retries > 0:
        detail = f"打开失败（已重试 {retries} 次，间隔 {gap}ms）: {err_s}"
    else:
        detail = f"打开失败: {err_s}"
    rows.append(
        _result_row(
            page_id=page_id,
            phase="nav",
            key="goto",
            action="open_url",
            detail=detail,
            ok=False,
            account=acct,
        )
    )
    return False


def _page_goto_maybe(
    page: Any,
    target: str,
    *,
    page_id: str,
    acct: str,
    args: Any,
    rows: list,
    pg: Optional[dict] = None,
) -> bool:
    """
    若当前页已与 target 同路径且未设 forceReloadOnOpen，则跳过 goto（避免列表被重载后异步未就绪）。
    单测模板常是「直接打开该页」；全量中上一页可能已 SPA 跳到同一 URL，再 goto 会误伤。
    """
    raw = (target or "").strip()
    if not raw:
        return True
    # 必须与 _page_goto 内解析后的 URL 对齐后再判断 skip，否则 `{yday}` 未替换时仍会误判；
    # 千川还须比较 dr（见 _qianchuan_same_url_skip_goto_ok）。
    resolved_for_skip = _resolve_runtime_url(raw)
    force = bool((pg or {}).get("forceReloadOnOpen"))
    cur = ""
    try:
        cur = str(getattr(page, "url", "") or "")
    except Exception:
        pass
    if (
        not force
        and _urls_same_path(cur, resolved_for_skip)
        and _qianchuan_same_url_skip_goto_ok(cur, resolved_for_skip)
    ):
        rows.append(
            _result_row(
                page_id=page_id,
                phase="nav",
                key="goto",
                action="skip_same_url",
                detail=resolved_for_skip,
                ok=True,
                account=acct,
            )
        )
        return True
    return _page_goto(page, raw, page_id=page_id, acct=acct, args=args, rows=rows)


def _apply_post_goto_wait(page: Any, pg: dict) -> None:
    try:
        w = int((pg or {}).get("postGotoWaitMs") or 0)
    except (TypeError, ValueError):
        w = 0
    if w <= 0:
        return
    try:
        page.wait_for_timeout(min(max(0, w), 120000))
    except Exception:
        pass


def _apply_pre_field_extract_wait(page: Any, pg: dict) -> None:
    """切户/进页后、仅抽 fields 且无后置 interaction 时，给异步渲染额外时间。"""
    try:
        w = int((pg or {}).get("preFieldExtractWaitMs") or 0)
    except (TypeError, ValueError):
        w = 0
    if w <= 0:
        return
    try:
        page.wait_for_timeout(min(max(0, w), 120000))
    except Exception:
        pass


def _guard_topbar_nav_destination(
    page: Any, pg: dict, pid: str, acct: str, args: Any, rows: list
) -> None:
    """
    navigateFromCurrent 顶栏点击后：若当前 URL 命中 forbiddenHostSubstringsAfterTopBar 则中断。
    用于避免误点巨量百应 Buyin（buyin.jinritemai.com）等非目标站。
    """
    raw = pg.get("forbiddenHostSubstringsAfterTopBar")
    if not isinstance(raw, list) or not raw:
        return
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    for item in raw:
        s = str(item or "").strip().lower()
        if s and s in url:
            det = (
                f"顶栏跳转后落在禁止域（匹配「{s}」），勿进入巨量百应等；"
                f"请调整该页 beforeAccountSwitch 的 Tab 序号或选择器"
            )
            rows.append(
                _result_row(
                    page_id=pid,
                    account=acct,
                    phase="nav",
                    key="topbar_nav_guard",
                    action="forbiddenHost",
                    detail=det,
                    ok=False,
                )
            )
            _abort_on_step_fail(
                args, pid, acct, "topbar_nav_guard", "forbiddenHost", det
            )


def _fxg_account_switcher_sel_list(spec: Any) -> list:
    if isinstance(spec, str) and spec.strip():
        return [spec.strip()]
    if isinstance(spec, list):
        return [str(x).strip() for x in spec if str(x).strip()]
    return []


def _fxg_try_click_first_visible(page: Any, selector: str, wait_ms: int) -> bool:
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=wait_ms)
        loc.click(timeout=min(wait_ms, 12000))
        return True
    except Exception:
        pass
    try:
        loc.wait_for(state="attached", timeout=min(wait_ms, 8000))
        loc.click(timeout=12000, force=True)
        return True
    except Exception:
        return False


def _fxg_try_hover_first(page: Any, selector: str, wait_ms: int) -> bool:
    """悬停以展开账号下拉（popover 常为 hover 触发，非 click）。"""
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=wait_ms)
        loc.hover(timeout=min(wait_ms, 12000))
        return True
    except Exception:
        pass
    try:
        loc.wait_for(state="attached", timeout=min(wait_ms, 8000))
        loc.hover(timeout=12000, force=True)
        return True
    except Exception:
        return False


def _fxg_click_shop_in_select_modal(
    page: Any, shop_name: str, list_specs: list, modal_hint: str
) -> Tuple[bool, str]:
    """
    「请选择店铺」弹层内：优先在列表/弹窗中找 div[class*='index_introName'] 且文案精确等于店名，
    再点击其外层 index_intro__ 卡片（与页面结构一致）；失败则退回 get_by_text。
    """
    name = (shop_name or "").strip()
    if not name:
        return False, "店铺名为空"
    exact_pat = re.compile("^" + re.escape(name) + "$")
    intro_sel = "div[class*='index_introName']"
    last_err: Optional[Exception] = None

    def _click_cell(cell: Any) -> None:
        cell.wait_for(state="visible", timeout=15000)
        cell.scroll_into_view_if_needed(timeout=5000)
        row = cell.locator("xpath=ancestor::div[contains(@class,'index_intro__')][1]")
        if row.count() > 0:
            row.first.click(timeout=10000)
        else:
            cell.click(timeout=10000)

    for list_sel in list_specs:
        try:
            root = page.locator(list_sel).first
            root.wait_for(state="visible", timeout=12000)
            tgt = root.locator(intro_sel).filter(has_text=exact_pat)
            if tgt.count() == 0:
                raise RuntimeError("列表内无 index_introName 精确匹配")
            _click_cell(tgt.first)
            return True, ""
        except Exception as e:
            last_err = e
            continue

    try:
        dlg = page.locator("[role='dialog']").filter(has_text=modal_hint).first
        dlg.wait_for(state="visible", timeout=12000)
        tgt = dlg.locator(intro_sel).filter(has_text=exact_pat)
        if tgt.count() > 0:
            _click_cell(tgt.first)
            return True, ""
    except Exception as e:
        last_err = e

    for list_sel in list_specs:
        try:
            root = page.locator(list_sel).first
            root.wait_for(state="visible", timeout=8000)
            row = root.get_by_text(name, exact=True)
            row.first.wait_for(state="visible", timeout=15000)
            row.first.scroll_into_view_if_needed(timeout=5000)
            row.first.click(timeout=10000)
            return True, ""
        except Exception as e:
            last_err = e
            continue

    try:
        dlg = page.locator("[role='dialog']").filter(has_text=modal_hint)
        if dlg.count() > 0:
            tgt = dlg.first.get_by_text(name, exact=True)
            tgt.first.wait_for(state="visible", timeout=15000)
            tgt.first.scroll_into_view_if_needed(timeout=5000)
            tgt.first.click(timeout=10000)
            return True, ""
    except Exception as e:
        last_err = e

    try:
        tgt = page.get_by_text(name, exact=True)
        tgt.first.wait_for(state="visible", timeout=15000)
        tgt.first.scroll_into_view_if_needed(timeout=5000)
        tgt.first.click(timeout=10000)
        return True, ""
    except Exception as e:
        last_err = e

    return False, f"点击店铺「{name}」失败: {last_err}"


def _switch_fxg_shop_modal(
    page: Any, shop_name: str, page_cfg: Optional[dict] = None
) -> Tuple[bool, str]:
    """
    抖店 PC：切店弹窗多为两步——① 在 headerMenuHoverSelector 上悬停展开账号下拉，再点 openSwitchModalSelector；
    若无 hover 配置则退回点击 headerMenuTriggerSelector；再试 menuOpenSelectors。
    最后在「请选择店铺」弹层内用 index_introName 匹配店名点击。切换成功后约等待 5 秒。
    """
    cfg = (page_cfg or {}).get("accountSwitcher") if isinstance(page_cfg, dict) else None
    if not isinstance(cfg, dict):
        cfg = {}
    switch_text = str(cfg.get("switchMenuText") or "切换组织/店铺").strip()
    modal_hint = str(cfg.get("modalTitleContains") or "请选择店铺").strip()
    menu_open = cfg.get("menuOpenSelectors")
    if not isinstance(menu_open, list) or not menu_open:
        menu_open = [
            "[class*='header'] [class*='avatar']",
            "header img",
            "[class*='user-info']",
            "[class*='header-user']",
        ]
    else:
        menu_open = [str(x).strip() for x in menu_open if str(x or "").strip()]
    # 抖店顶栏专用回退（插到前面优先试）
    _fxg_menu_extra = [
        "#fxg-pc-header div[class*='nav-menu_rightBar']",
        "#fxg-pc-header [class*='index_wrapper']",
        "#fxg-pc-header img",
        "#fxg-pc-header [class*='avatar']",
    ]
    for s in reversed(_fxg_menu_extra):
        if s not in menu_open:
            menu_open.insert(0, s)

    name = (shop_name or "").strip()
    if not name:
        return False, "店铺名为空"

    list_specs = _fxg_account_switcher_sel_list(cfg.get("shopListContainerSelector"))
    if not list_specs:
        list_specs = [
            "div.auxo-modal-wrap.auxo-modal-centered div[class*='index_roleList']",
        ]

    open_spec = cfg.get("openSwitchModalSelector")
    if isinstance(open_spec, str) and open_spec.strip():
        open_chain = [open_spec.strip()]
    elif isinstance(open_spec, list):
        open_chain = [str(x).strip() for x in open_spec if str(x).strip()]
    else:
        open_chain = []

    hover_list = _fxg_account_switcher_sel_list(cfg.get("headerMenuHoverSelector"))
    trigger_list = _fxg_account_switcher_sel_list(cfg.get("headerMenuTriggerSelector"))
    used_css = bool(open_chain)

    if used_css:
        try:
            page.locator("#fxg-pc-header").first.wait_for(state="visible", timeout=45000)
        except Exception as e:
            cur = ""
            try:
                cur = page.url or ""
            except Exception:
                pass
            return False, (
                f"当前页未出现抖店顶栏 #fxg-pc-header（45s）：{e}；page.url={cur!r}。"
                "请确认已登录抖店 PC 后台；若多标签请把抖店页置于优先或关闭干扰标签。"
                "脚本会优先选用已打开 fxg.jinritemai.com 的标签。"
            )

        max_open_modal_refreshes = 1
        last_open_err: Optional[Exception] = None
        for refresh_i in range(max_open_modal_refreshes + 1):
            menu_ok = False
            if hover_list:
                for hs in hover_list:
                    if _fxg_try_hover_first(page, hs, 8000):
                        page.wait_for_timeout(1000)
                        menu_ok = True
                        break
            if not menu_ok and trigger_list:
                for ts in trigger_list:
                    if _fxg_try_click_first_visible(page, ts, 8000):
                        page.wait_for_timeout(800)
                        menu_ok = True
                        break
            if not menu_ok and not hover_list and not trigger_list:
                menu_ok = True

            if not menu_ok:
                for osel in menu_open:
                    osel = str(osel or "").strip()
                    if not osel:
                        continue
                    if _fxg_try_click_first_visible(page, osel, 5000):
                        page.wait_for_timeout(700)
                        menu_ok = True
                        break

            if not menu_ok:
                cur = ""
                try:
                    cur = page.url or ""
                except Exception:
                    pass
                return False, (
                    "打开右上角账号下拉失败（headerMenuHoverSelector / headerMenuTriggerSelector / menuOpenSelectors 均未成功）。"
                    f"当前 url={cur!r}。抖店常为「先悬停账号区再点菜单项」，请配置 headerMenuHoverSelector（index_wrapper 下那一层 div）。"
                )

            last_open_err = None
            for osel in open_chain:
                try:
                    loc = page.locator(osel).first
                    loc.wait_for(state="visible", timeout=20000)
                    loc.click(timeout=12000)
                    page.wait_for_timeout(500)
                    last_open_err = None
                    break
                except Exception as e:
                    last_open_err = e
                    continue

            if last_open_err is None:
                break
            if refresh_i < max_open_modal_refreshes:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(1200)
                except Exception as re:
                    return False, (
                        f"打开切店弹窗失败（openSwitchModalSelector）已刷新重试，但页面刷新失败: {re}"
                    )
                continue
            return False, f"打开切店弹窗失败（openSwitchModalSelector）: {last_open_err}"

        try:
            page.get_by_text(modal_hint, exact=False).first.wait_for(state="visible", timeout=25000)
        except Exception:
            pass

        ok_shop, shop_err = _fxg_click_shop_in_select_modal(page, name, list_specs, modal_hint)
        if not ok_shop:
            return False, shop_err

        try:
            page.wait_for_timeout(5000)
        except Exception:
            pass
        return True, f"已切换店铺: {name}（CSS 流程）"

    try:
        link = page.get_by_text(switch_text, exact=True)
        if link.count() == 0 or not link.first.is_visible():
            for osel in menu_open:
                osel = str(osel or "").strip()
                if not osel:
                    continue
                try:
                    page.locator(osel).first.click(timeout=5000)
                    page.wait_for_timeout(500)
                except Exception:
                    continue
                link = page.get_by_text(switch_text, exact=True)
                if link.count() > 0:
                    try:
                        link.first.wait_for(state="visible", timeout=6000)
                        break
                    except Exception:
                        continue
        link.first.wait_for(state="visible", timeout=20000)
        link.first.click(timeout=8000)
        page.wait_for_timeout(600)
    except Exception as e:
        return False, f"打开「{switch_text}」失败: {e}"

    try:
        page.get_by_text(modal_hint, exact=False).first.wait_for(state="visible", timeout=20000)
    except Exception:
        pass

    ok_shop, shop_err = _fxg_click_shop_in_select_modal(page, name, list_specs, modal_hint)
    if not ok_shop:
        return False, shop_err + "（若列表过长需在页内滚动后再试，或缩短名称匹配）"

    try:
        page.wait_for_timeout(5000)
    except Exception:
        pass
    return True, f"已切换店铺: {name}"


def _dispatch_account_switch(
    page: Any,
    acct: str,
    pg: dict,
    pid: str,
    *,
    qianchuan_switch_key: Any = _QC_SWITCH_OVERRIDE_UNSET,
) -> Tuple[bool, str]:
    sw = pg.get("accountSwitcher") if isinstance(pg.get("accountSwitcher"), dict) else {}
    mode = str(sw.get("mode") or "").strip()
    if mode == "noop":
        return (
            True,
            "globalAccountLoop：锚点无需 UI 切店（如拼多多：店铺轮次由 pageIds 内登录与业务页完成）",
        )
    if mode == "fxgShopModal":
        return _switch_fxg_shop_modal(page, acct, pg)
    qc_key = acct
    if qianchuan_switch_key is not _QC_SWITCH_OVERRIDE_UNSET:
        qc_key = str(qianchuan_switch_key or "").strip() or acct
    if mode == "loginShopList":
        return _switch_qianchuan_login_shop_list(page, qc_key, pg)
    if mode == "searchOverlay" or pid == "qianchuan_home_cost_roi":
        return _switch_qianchuan_account(page, qc_key, pg)
    return (
        False,
        f"页面 {pid} 需配置 accountSwitcher：千川用 searchOverlay 或 loginShopList；"
        f"抖店首页/先切店再进业务页用 mode=fxgShopModal，并可配 preSwitchUrl",
    )


def _switch_qianchuan_login_shop_list(
    page: Any, account_name: str, page_cfg: Optional[dict] = None
) -> Tuple[bool, str]:
    """
    千川登录后「选择店铺」列表：在 account-list-container 内按「千川ID」或店铺名点击对应行（与 globalAccountLoop 轮次一致）。
    配置：shopListContainerSelector 或 shopListContainerSelectors（依次尝试）、可选 shopListScrollSelector 滚到底再找文案。
    若列表未出现且 fallbackToSearchOverlay 为 true，回退为顶部搜索切换。
    """
    cfg = (page_cfg or {}).get("accountSwitcher") if isinstance(page_cfg, dict) else None
    if not isinstance(cfg, dict):
        cfg = {}
    name = (account_name or "").strip()
    if not name:
        return False, "账号名为空"
    sels: list = []
    primary = str(cfg.get("shopListContainerSelector") or "").strip()
    if primary:
        sels.append(primary)
    extra = cfg.get("shopListContainerSelectors")
    if isinstance(extra, list):
        for x in extra:
            xs = str(x or "").strip()
            if xs and xs not in sels:
                sels.append(xs)
    if not sels:
        return False, "loginShopList 需配置 shopListContainerSelector（或 shopListContainerSelectors）"
    try:
        to = int(cfg.get("shopListWaitTimeoutMs") or 30000)
    except (TypeError, ValueError):
        to = 30000
    to = max(3000, min(to, 120000))
    root = None
    last_vis_err: Optional[Exception] = None
    for ls in sels:
        loc = page.locator(ls).first
        try:
            loc.wait_for(state="visible", timeout=min(to, 20000))
            root = loc
            break
        except Exception as e:
            last_vis_err = e
            continue
    if root is None:
        if cfg.get("fallbackToSearchOverlay"):
            return _switch_qianchuan_account(page, account_name, page_cfg)
        return False, f"店铺列表容器未出现: {last_vis_err}"

    scroll_sel = str(cfg.get("shopListScrollSelector") or "").strip()
    if scroll_sel:
        try:
            sc = page.locator(scroll_sel).first
            if sc.count() > 0:
                sc.evaluate("el => { el.scrollTop = el.scrollHeight; }")
                page.wait_for_timeout(500)
        except Exception:
            pass

    try:
        cand = None
        if name.isdigit() and len(name) >= 10:
            t_id = root.get_by_text(name, exact=False)
            if t_id.count() > 0:
                cand = t_id
            else:
                t_id2 = root.locator("div").filter(has_text=re.compile(r"ID:\s*" + re.escape(name)))
                if t_id2.count() > 0:
                    cand = t_id2
        if cand is None or cand.count() == 0:
            t_exact = root.get_by_text(name, exact=True)
            cand = t_exact if t_exact.count() > 0 else root.get_by_text(name, exact=False)
        if cand.count() == 0:
            if cfg.get("fallbackToSearchOverlay"):
                return _switch_qianchuan_account(page, account_name, page_cfg)
            return False, f"列表中未找到「{name}」（千川ID 或店铺名；可检查配置是否与列表展示一致）"
        cand.first.scroll_into_view_if_needed(timeout=8000)
        cand.first.click(timeout=10000)
    except Exception as e:
        if cfg.get("fallbackToSearchOverlay"):
            return _switch_qianchuan_account(page, account_name, page_cfg)
        return False, f"点击店铺「{name}」失败: {e}"

    try:
        acw = int(cfg.get("afterClickWaitMs") or 5000)
    except (TypeError, ValueError):
        acw = 5000
    try:
        page.wait_for_timeout(min(max(0, acw), 60000))
    except Exception:
        pass
    return True, f"已在登录列表选择店铺进入千川: {name}"


def _switch_qianchuan_account(
    page: Any, account_name: str, page_cfg: Optional[dict] = None
) -> Tuple[bool, str]:
    """
    千川顶部账户切换：打开面板 → 搜索框输入名称 → 点击列表中对应行。
    可选 pages[].accountSwitcher：searchPlaceholder、openSelectors（数组，依次尝试点击打开面板）。
    """
    cfg = (page_cfg or {}).get("accountSwitcher") if isinstance(page_cfg, dict) else None
    if not isinstance(cfg, dict):
        cfg = {}
    ph = str(cfg.get("searchPlaceholder") or "请输入账户名称或完整ID").strip()
    open_sels = cfg.get("openSelectors")
    if not isinstance(open_sels, list) or not open_sels:
        open_sels = [
            "#app header span:has-text('ID:')",
            "header [class*='account']",
            "[class*='account-switch']",
            "header >> text=/ID:\\s*\\d+/",
        ]

    name = (account_name or "").strip()
    if not name:
        return False, "账号名为空"

    try:
        inp = page.get_by_placeholder(ph)
        if inp.count() == 0 or not inp.first.is_visible():
            opened = False
            for osel in open_sels:
                osel = str(osel or "").strip()
                if not osel:
                    continue
                try:
                    page.locator(osel).first.click(timeout=5000)
                    page.wait_for_timeout(500)
                    inp = page.get_by_placeholder(ph)
                    inp.first.wait_for(state="visible", timeout=12000)
                    opened = True
                    break
                except Exception:
                    continue
            if not opened:
                return (
                    False,
                    "未打开账户切换面板；请在模板该页 accountSwitcher.openSelectors 中补充可点击入口",
                )
        inp.first.click(timeout=3000)
        inp.first.fill("", timeout=3000)
        inp.first.fill(name, timeout=5000)
        page.wait_for_timeout(700)
    except Exception as e:
        return False, f"搜索账户失败: {e}"

    try:
        if name.isdigit() and len(name) >= 10:
            cand = page.locator("div").filter(has_text=re.compile(r"ID:\s*" + re.escape(name)))
            if cand.count() > 0:
                cand.first.click(timeout=8000)
            else:
                page.get_by_text(name, exact=False).first.click(timeout=8000)
        else:
            cand = page.locator("div").filter(has_text=name).filter(has_text=re.compile(r"ID:\s*\d+"))
            if cand.count() > 0:
                cand.first.click(timeout=8000)
            else:
                page.get_by_text(name, exact=True).first.click(timeout=8000)
    except Exception as e:
        return False, f"点击账户「{name}」失败: {e}"

    try:
        page.wait_for_timeout(2000)
    except Exception:
        pass
    return True, f"已切换到: {name}"


def _field_selector_candidates(primary: str) -> list:
    """若模板含 .metric-card-selected，未点选卡片时可能无该类名，追加去掉后的备选。"""
    p = (primary or "").strip()
    if not p:
        return []
    out = [p]
    if ".metric-card-selected" in p:
        alt = re.sub(r"\s*\.metric-card-selected\b", "", p).strip()
        if alt and alt not in out:
            out.append(alt)
    return out


def _field_merge_alternate_selectors(
    primary_cands: list, field_dict: Optional[dict]
) -> list:
    """fields[].alternateFieldSelector：字符串或数组，依次追加为备选（与主 selector 同样走 metric-card 去选中等规则）。"""
    out = list(primary_cands)
    if not isinstance(field_dict, dict):
        return out
    alt = field_dict.get("alternateFieldSelector")
    parts: list = []
    if isinstance(alt, str) and alt.strip():
        parts.append(alt.strip())
    elif isinstance(alt, list):
        for x in alt:
            sx = str(x or "").strip()
            if sx:
                parts.append(sx)
    for p in parts:
        for c in _field_selector_candidates(p):
            if c not in out:
                out.append(c)
    return out


def _looks_like_pdd_spider_obfuscated(s: str) -> bool:
    """
    拼多多数据中心等指标使用 __spider_font：innerText 常为私用区 Unicode，Excel 里像「.」或空白。
    若整段无 ASCII 数字且含私用区或仅为无意义标点，视为需走 DOM 兜底。
    """
    s = (s or "").strip()
    if not s:
        return True
    if re.search(r"[0-9]", s):
        return False
    if s in ".。…·":
        return True
    for ch in s:
        o = ord(ch)
        if 0xE000 <= o <= 0xF8FF:
            return True
    return False


def _pdd_sycm_try_plain_number_from_card(page: Any, selector: str, timeout_ms: int) -> str:
    """
    在卡片容器内查找 data-* / title / 非 __spider_font 子节点中的可读数字（无法解密字体时尽量对齐业务展示）。
    """
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="attached", timeout=timeout_ms)
    except Exception:
        return ""
    try:
        out = loc.evaluate(
            """(el) => {
              const card = el.closest('[class*="card_cardItem"]')
                || el.closest('[class*="card_item"]')
                || el.parentElement;
              const root = card || el;
              const tryText = (t) => {
                if (!t) return '';
                const s = String(t).trim().replace(/,/g, '');
                if (/^[-+]?(?:\\d+)(?:\\.\\d+)?$/.test(s)) return String(t).trim();
                const m = String(t).match(/([-+]?(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?)/);
                return m ? m[1].replace(/,/g, '') : '';
              };
              for (const attr of ['data-value','data-val','data-amount','data-count','data-tip','data-title','title','aria-label']) {
                let cur = el;
                for (let i = 0; i < 10 && cur; i++, cur = cur.parentElement) {
                  const v = cur.getAttribute && cur.getAttribute(attr);
                  const got = tryText(v);
                  if (got) return got;
                }
              }
              const nodes = root.querySelectorAll('span, p, div, li');
              for (const n of nodes) {
                const cls = (n.className && String(n.className)) || '';
                if (cls.includes('__spider_font')) continue;
                const got = tryText(n.textContent || '');
                if (got) return got;
              }
              const html = root.innerHTML || '';
              const dm = html.match(/data-value="([^"]+)"/);
              if (dm) {
                const g = tryText(dm[1]);
                if (g) return g;
              }
              return '';
            }"""
        )
        return (str(out or "")).strip()
    except Exception:
        return ""


def _extract_field_text(
    page: Any,
    primary_sel: str,
    timeout_ms: int,
    field_dict: Optional[dict] = None,
    *,
    selector_hint: Optional[str] = None,
) -> Tuple[str, str]:
    """返回 (text, used_selector_or_error)；成功时第二段为实际命中的选择器字符串。可选 field_dict 含 alternateFieldSelector。
    selector_hint：上次跑通的选择器（与 --selector-hints-file 配合，按店铺），插入候选链最前并重排去重。"""
    inner_to = max(3000, min(25000, timeout_ms // 2))
    last_err = ""
    cands = _field_merge_alternate_selectors(
        _field_selector_candidates(primary_sel), field_dict
    )
    if selector_hint and str(selector_hint).strip():
        h = str(selector_hint).strip()
        cands = [h] + [c for c in cands if c != h]
    for cand in cands:
        loc = page.locator(cand).first
        try:
            loc.wait_for(state="attached", timeout=timeout_ms)
            text = (loc.inner_text(timeout=inner_to) or "").strip()
            if text and not _looks_like_pdd_spider_obfuscated(text):
                return text, cand
            plain = _pdd_sycm_try_plain_number_from_card(page, cand, timeout_ms)
            if plain:
                return plain, f"{cand} (+pddPlain)"
            if text:
                last_err = (
                    f"拼多多 spider 字体私用区文本且卡片内无 data/title 等可读数字: {cand[:120]}"
                )
                continue
            last_err = f"已附着但文本为空: {cand[:120]}"
        except Exception as e:
            last_err = str(e)
        loc2 = page.locator(cand).first
        try:
            loc2.wait_for(state="visible", timeout=timeout_ms)
            text = (loc2.inner_text(timeout=inner_to) or "").strip()
            if text and not _looks_like_pdd_spider_obfuscated(text):
                return text, f"{cand} (visible)"
            plain = _pdd_sycm_try_plain_number_from_card(page, cand, timeout_ms)
            if plain:
                return plain, f"{cand} (visible,+pddPlain)"
            if text:
                last_err = (
                    f"拼多多 spider 字体私用区文本且卡片内无 data/title 等可读数字: {cand[:120]}"
                )
                continue
            last_err = f"已附着但文本为空: {cand[:120]}"
        except Exception as e:
            last_err = str(e)
    return "", last_err or "无可用选择器"


def _parse_network_response_capture_config(pg_inner: dict) -> Optional[dict]:
    """
    pages[].networkResponseCapture：urlSubstrings / urlIncludes + jsonPathMap（field.key -> JSON 键或 a.b 路径）。
    未配置或无效时返回 None。
    """
    if not isinstance(pg_inner, dict):
        return None
    raw = pg_inner.get("networkResponseCapture")
    if not isinstance(raw, dict):
        return None
    subs_raw = raw.get("urlSubstrings") or raw.get("urlIncludes")
    if isinstance(subs_raw, str):
        subs_raw = [subs_raw]
    if not isinstance(subs_raw, list):
        return None
    subs = [str(x).strip() for x in subs_raw if str(x).strip()]
    if not subs:
        return None
    jmap = raw.get("jsonPathMap") or raw.get("fieldKeyToJsonKey")
    if not isinstance(jmap, dict) or not jmap:
        return None
    return {"subs": subs, "map": jmap}


def _network_json_pick(payload: dict, path_spec: str) -> Any:
    """path_spec 为单层键名或点分路径。"""
    ps = str(path_spec or "").strip()
    if not ps or not isinstance(payload, dict):
        return None
    if "." not in ps:
        return payload.get(ps)
    cur: Any = payload
    for part in ps.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _network_json_values_for_key(obj: Any, key: str) -> list:
    """深度遍历 dict/list，收集所有名为 key 的字段值（顺序：深度优先）。"""
    out: list = []
    k = str(key or "").strip()
    if not k:
        return out

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            if k in n:
                out.append(n[k])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for it in n:
                walk(it)

    walk(obj)
    return out


def _network_resolve_path_to_list(obj: Any, list_path: str) -> Optional[list]:
    """
    从响应根对象解析出列表，如 result.dayList 或单段 dayList（会在根下与 result 子对象上各试一次）。
    """
    lp = (list_path or "").strip()
    if not lp or not isinstance(obj, dict):
        return None
    parts = lp.split(".")

    def _dig(root: Any) -> Optional[list]:
        if not isinstance(root, dict):
            return None
        cur: Any = root
        for p in parts:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur if isinstance(cur, list) else None

    hit = _dig(obj)
    if hit is not None:
        return hit
    res = obj.get("result")
    if isinstance(res, dict):
        hit = _dig(res)
        if hit is not None:
            return hit
    return None


def _network_leaf_values_from_dated_list(
    items: list,
    leaf: str,
    yday: str,
    date_field: str,
) -> list:
    """在对象列表中筛出 date_field 与 yday（YYYY-MM-DD）一致的行，取 leaf。"""
    out: list = []
    td = (yday or "").strip()[:10]
    df = (date_field or "").strip()
    k = str(leaf or "").strip()
    if not items or not td or len(td) < 8 or not df or not k:
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        ds = str(it.get(df) or "").strip()[:10]
        if ds == td and k in it:
            out.append(it[k])
    return out


def _network_json_leaf_in_date_matched_dicts(
    obj: Any,
    leaf: str,
    target_date: str,
    date_field: str,
) -> list:
    """
    遍历 JSON，在「含 date_field 且日期与 target_date（YYYY-MM-DD 前 10 位）一致」的对象上取 leaf 字段。
    用于 queryMallTradeList 等多日列表，只取「昨天」一行而非任意一日的 payOrdrAmt。
    """
    k_leaf = str(leaf or "").strip()
    k_date = str(date_field or "").strip()
    td = (target_date or "").strip()[:10]
    if not k_leaf or not k_date or len(td) < 8:
        return []
    out: list = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            dv = n.get(k_date)
            if dv is not None:
                ds = str(dv).strip()[:10]
                if ds == td and k_leaf in n:
                    out.append(n[k_leaf])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for it in n:
                walk(it)

    walk(obj)
    return out


def _network_find_dated_row_anywhere(
    obj: Any, yday: str, date_field: str
) -> Optional[dict]:
    """
    深度遍历 JSON，在任意 list[dict] 中查找第一条 date_field 与 yday（YYYY-MM-DD）一致的行。
    用于 dayList 路径不固定或 listPath 未配置时的按日取数。
    """
    td = (yday or "").strip()[:10]
    df = (date_field or "").strip()
    if len(td) < 8 or not df:
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
                    dv = it.get(df)
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


def _network_plain_pick_scalar(values: list) -> Optional[str]:
    """从同一键的多处取值中优先选：数值类型 > 含 ASCII 数字且非 spider 私用区乱码的字符串。若仅乱码则返回 None。"""
    if not values:
        return None
    nums: list = []
    strs: list = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            nums.append(str(v))
            continue
        if isinstance(v, float):
            nums.append(str(v))
            continue
        s = str(v).strip()
        if not s:
            continue
        if not _looks_like_pdd_spider_obfuscated(s) and re.search(r"[0-9]", s):
            strs.append(s)
    if nums:
        return nums[0]
    if strs:
        return strs[0]
    return None


def _try_field_from_network_capture(
    page_cfg: Optional[dict], store: Optional[dict], fkey: str, yday: str = ""
) -> Tuple[str, str]:
    """若模板配置了 networkResponseCapture 且已拦截到 JSON，按 jsonPathMap 取值。返回 (text, detail)。
    可选 matchYesterday + dateField + listPath（如 dayList）：优先在 result.<listPath> 数组里按 stateDate=yday 取 payOrdrAmt 等；
    listPath 未命中时再全树按日期匹配。无可用明文则走 DOM + pddPlain。"""
    if not isinstance(page_cfg, dict) or not isinstance(store, dict):
        return "", ""
    nrs = page_cfg.get("networkResponseCapture")
    if not isinstance(nrs, dict):
        return "", ""
    raw_root = store.get("raw")
    pl = store.get("payload")
    base: Any = raw_root if raw_root is not None else pl
    if base is None:
        return "", ""
    jmap = nrs.get("jsonPathMap") or {}
    jspec = jmap.get(fkey)
    if jspec is None:
        jspec = jmap.get(str(fkey).strip())
    if not jspec:
        return "", ""
    jspec_s = str(jspec).strip()
    leaf = jspec_s.split(".")[-1]

    date_field = str(nrs.get("dateField") or nrs.get("matchDateField") or "").strip()
    match_yesterday = bool(nrs.get("matchYesterday"))
    list_path_raw = nrs.get("listPath")
    list_paths: list = []
    if isinstance(list_path_raw, list):
        list_paths = [str(x).strip() for x in list_path_raw if str(x or "").strip()]
    elif isinstance(list_path_raw, str) and list_path_raw.strip():
        list_paths = [list_path_raw.strip()]

    candidates: list = []
    if match_yesterday and date_field and (yday or "").strip() and leaf:
        if list_paths:
            for root in (base, pl):
                if root is None or not isinstance(root, dict):
                    continue
                for lp in list_paths:
                    arr = _network_resolve_path_to_list(root, lp)
                    if not arr:
                        continue
                    got = _network_leaf_values_from_dated_list(
                        arr, leaf, (yday or "").strip(), date_field
                    )
                    if got:
                        candidates.extend(got)
                        break
                if candidates:
                    break
        if not candidates:
            for root in (base, pl):
                if root is None:
                    continue
                if not isinstance(root, (dict, list)):
                    continue
                candidates.extend(
                    _network_json_leaf_in_date_matched_dicts(
                        root, leaf, (yday or "").strip(), date_field
                    )
                )
        if not candidates:
            for root in (base, pl):
                if root is None:
                    continue
                row = _network_find_dated_row_anywhere(
                    root, (yday or "").strip(), date_field
                )
                if isinstance(row, dict) and leaf in row:
                    candidates.append(row.get(leaf))
        picked = _network_plain_pick_scalar(candidates)
        if picked:
            subs = nrs.get("urlSubstrings") or nrs.get("urlIncludes") or []
            if isinstance(subs, str):
                subs = [subs]
            detail = f"network:{subs}#{jspec_s}#date={date_field}:{(yday or '').strip()[:10]}"
            return picked, detail
        return "", ""

    if isinstance(base, dict):
        v_dot = _network_json_pick(base, jspec_s)
        if v_dot is not None:
            candidates.append(v_dot)
    if isinstance(pl, dict) and pl is not base:
        v2 = _network_json_pick(pl, jspec_s)
        if v2 is not None:
            candidates.append(v2)

    if leaf and isinstance(base, (dict, list)):
        candidates.extend(_network_json_values_for_key(base, leaf))

    picked = _network_plain_pick_scalar(candidates)
    if not picked:
        return "", ""
    subs = nrs.get("urlSubstrings") or nrs.get("urlIncludes") or []
    if isinstance(subs, str):
        subs = [subs]
    detail = f"network:{subs}#{jspec_s}"
    return picked, detail


def _network_response_capture_attach(
    page: Any, pg_inner: dict
) -> Tuple[dict, Any]:
    """
    在 page.goto 之前挂上 response 监听，将 URL 含 urlSubstrings 的 JSON 存入 store['raw']（完整 body）
    与 store['payload']（unwrap 一层 result/data/body 后的 dict）；后者覆盖前者。
    字段取值时优先在 raw 全树按 jsonPathMap 叶子键深度匹配明文/数值。
    返回 (store, cleanup)；cleanup 须在 finally 中调用。
    """
    cinfo = _parse_network_response_capture_config(pg_inner)
    if not cinfo:
        return {}, None
    store: dict = {}
    subs = cinfo["subs"]
    nrs_top = pg_inner.get("networkResponseCapture") if isinstance(pg_inner, dict) else None
    match_after_key = (
        str((nrs_top or {}).get("matchAfterInteractionKey") or "").strip()
        if isinstance(nrs_top, dict)
        else ""
    )
    if match_after_key:
        store["_phase"] = "ignore"

    def on_response(response: Any) -> None:
        try:
            url = getattr(response, "url", None) or ""
            if not any(s in url for s in subs):
                return
            if match_after_key:
                ph = store.get("_phase")
                if ph == "ignore":
                    return
                if ph == "done":
                    return
                if ph != "armed":
                    return
            data = response.json()
            store["raw"] = data
            root: Any = data
            if isinstance(root, dict):
                for k in ("result", "data", "body"):
                    v = root.get(k)
                    if isinstance(v, dict):
                        root = v
                        break
            if isinstance(root, dict):
                store["payload"] = root
            if match_after_key:
                store["_phase"] = "done"
        except Exception:
            return

    page.on("response", on_response)

    def cleanup() -> None:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    return store, cleanup


def _network_capture_arm_if_step_matches(
    page_cfg: Optional[dict],
    store: Optional[dict],
    resolved_step_key: str,
) -> None:
    """
    pages[].networkResponseCapture.matchAfterInteractionKey：与 resolved_step_key 相等时，
    清空已拦截的 raw/payload，并将 _phase 置为 armed，使后续仅采纳「本条交互之后」的第一条匹配响应。
    goto 阶段若已设 matchAfterInteractionKey，attach 时 _phase=ignore，不会写入初始请求。
    """
    if not isinstance(page_cfg, dict) or not isinstance(store, dict):
        return
    nrs = page_cfg.get("networkResponseCapture")
    if not isinstance(nrs, dict):
        return
    want = str(nrs.get("matchAfterInteractionKey") or "").strip()
    if not want:
        return
    sk = str(resolved_step_key or "").strip()
    if sk != want:
        return
    store.pop("raw", None)
    store.pop("payload", None)
    store["_phase"] = "armed"


def _maybe_save_network_capture_response(
    page_cfg: Optional[dict],
    store: Optional[dict],
    json_save_root: Path,
    yday: str,
    page_id: str,
    account: str,
) -> None:
    """
    pages[].networkResponseCapture.saveRawResponseRelativePath（或 saveResponseJsonPath）：
    将拦截到的完整 JSON（store['raw']）写入 json_save_root 下相对路径；占位 {yday}{pageId}{account}{run_date}。
    """
    if not isinstance(page_cfg, dict) or not isinstance(store, dict):
        return
    nrs = page_cfg.get("networkResponseCapture")
    if not isinstance(nrs, dict):
        return
    rel = str(nrs.get("saveRawResponseRelativePath") or nrs.get("saveResponseJsonPath") or "").strip()
    if not rel:
        return
    raw = store.get("raw")
    if raw is None:
        return
    try:
        yd = (yday or "").strip()[:10]
        safe_acct = _sanitize_filename_prefix(account) or "account"
        safe_pid = _sanitize_filename_prefix(page_id) or "page"
        path_s = (
            rel.replace("{yday}", yd)
            .replace("{pageId}", safe_pid)
            .replace("{account}", safe_acct)
            .replace("{run_date}", yd)
        )
        out = Path(path_s)
        if not out.is_absolute():
            out = json_save_root / path_s
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fp:
            json.dump(raw, fp, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _timed_extract_field_text(
    page: Any,
    primary_sel: str,
    timeout_ms: int,
    field_dict: Optional[dict],
    *,
    args: Any,
    account: str,
    page_id: str,
    field_key: str,
    selector_hint: Optional[str] = None,
) -> Tuple[str, str]:
    """与 _extract_field_text 相同，额外写入 --timing-log 中单字段耗时。"""
    t0 = time.perf_counter()
    try:
        return _extract_field_text(
            page, primary_sel, timeout_ms, field_dict, selector_hint=selector_hint
        )
    finally:
        _timing_append_ms(
            args,
            account=account,
            page_id=page_id,
            phase="field",
            step="extract_field_text",
            detail=(field_key or "")[:200],
            t_start=t0,
        )


def _table_column_agg_selectors(field_dict: dict) -> list:
    """extract.tableColumnAgg：主 selector + alternateTableSelectors。"""
    ext = field_dict.get("extract") if isinstance(field_dict, dict) else None
    if not isinstance(ext, dict):
        ext = {}
    out: list = []
    ts = str(ext.get("tableSelector") or "").strip()
    if ts:
        out.append(ts)
    alts = ext.get("alternateTableSelectors") or ext.get("alternateTableSelector")
    if isinstance(alts, str) and alts.strip():
        out.append(alts.strip())
    elif isinstance(alts, list):
        out.extend([str(x).strip() for x in alts if str(x or "").strip()])
    ps = str(field_dict.get("selector") or "").strip()
    if ps and ps not in out:
        out.insert(0, ps)
    seen = set()
    dedup: list = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        dedup.append(x)
    return dedup


def _extract_table_column_agg(
    page: Any,
    timeout_ms: int,
    field_dict: dict,
) -> Tuple[str, str]:
    """
    extract.type=tableColumnAgg：在 table 内按表头文案匹配列，对 tbody 行该列数字求和或算术平均。
    extract.columnHeaderMatch + extract.aggregate(sum|avg)。
    """
    ext = field_dict.get("extract") if isinstance(field_dict, dict) else None
    if not isinstance(ext, dict):
        return "", "extract 须为对象"
    sels = _table_column_agg_selectors(field_dict)
    if not sels:
        return "", "缺少 tableSelector / selector"
    header_needle = str(ext.get("columnHeaderMatch") or ext.get("columnHeader") or "").strip()
    col_idx_override: Optional[int] = None
    raw_ci = ext.get("columnIndex")
    if raw_ci is not None and str(raw_ci).strip() != "":
        try:
            col_idx_override = int(raw_ci)
        except (TypeError, ValueError):
            col_idx_override = None
    if col_idx_override is None and not header_needle:
        return "", "缺少 columnHeaderMatch，或设置 columnIndex（从 0 起）"
    agg = str(ext.get("aggregate") or "sum").strip().lower()
    if agg in ("average",):
        agg = "avg"
    if agg not in ("sum", "avg"):
        return "", f"aggregate 仅支持 sum/avg，当前: {agg}"
    integer_only = bool(ext.get("integerOnly"))
    paginate_all = bool(ext.get("paginateAllPages"))
    raw_mp = ext.get("maxPages")
    try:
        max_pages = int(raw_mp) if raw_mp is not None else 30
    except (TypeError, ValueError):
        max_pages = 30
    max_pages = max(1, min(max_pages, 200))
    try:
        next_wait_ms = int(ext.get("postNextPageWaitMs") or 900)
    except (TypeError, ValueError):
        next_wait_ms = 900
    next_wait_ms = max(100, min(next_wait_ms, 10000))
    next_sels: list = []
    nps = ext.get("nextPageSelector")
    if isinstance(nps, str) and nps.strip():
        next_sels.append(nps.strip())
    aps = ext.get("alternateNextPageSelectors")
    if isinstance(aps, str) and aps.strip():
        next_sels.append(aps.strip())
    elif isinstance(aps, list):
        next_sels.extend([str(x).strip() for x in aps if str(x or "").strip()])
    if not next_sels:
        next_sels = [
            "button:has-text('下一页')",
            "a:has-text('下一页')",
            "li:has-text('下一页')",
            "[aria-label='下一页']",
        ]

    last_vis_err = ""
    for sel in sels:
        try:
            page.locator(sel).first.wait_for(
                state="visible", timeout=min(max(500, timeout_ms), 60000)
            )
            last_vis_err = ""
            break
        except Exception as e:
            last_vis_err = str(e)
            continue
    else:
        return "", f"表格未可见（已试 {len(sels)} 个选择器）: {last_vis_err[:200]}"

    def _read_one_page() -> Any:
        return page.evaluate(
            """([selectors, headerNeedle, colIdxOverride]) => {
              const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
              const needle = norm(headerNeedle || "");
              const matchCol = (cells) => {
                for (let i = 0; i < cells.length; i++) {
                  const h = norm(cells[i]);
                  if (h === needle || h.includes(needle) || needle.includes(h)) return i;
                }
                return -1;
              };
              const findHeaderRow = (table) => {
                const theadTr = table.querySelector("thead tr");
                if (theadTr) return theadTr;
                for (const tr of table.querySelectorAll("tr")) {
                  if (tr.querySelector("th")) return tr;
                }
                for (const tr of table.querySelectorAll("tr")) {
                  const fc = norm(tr.querySelector("th,td")?.textContent || "");
                  if (fc === "省份" || fc.includes("省份")) return tr;
                }
                const headerHints = [
                  "成交金额",
                  "成交订单",
                  "成交买家",
                  "订单单价",
                  "客单价",
                  "操作",
                ];
                for (const tr of table.querySelectorAll("tr")) {
                  const rowText = norm(tr.textContent || "");
                  const cells = [...tr.querySelectorAll("th,td")];
                  if (cells.length < 3) continue;
                  const hit = headerHints.some((k) => rowText.includes(k));
                  if (hit) return tr;
                }
                return null;
              };
              let table = null;
              let used = "";
              for (const s of selectors) {
                const root = document.querySelector(s);
                if (!root) continue;
                const t = root.tagName === "TABLE" ? root : root.querySelector("table");
                if (t) {
                  table = t;
                  used = s;
                  break;
                }
              }
              if (!table) {
                return { ok: false, err: "选择器下无 table 元素" };
              }
              let colIdx = -1;
              let headerCells = [];
              let headerRow = null;
              if (typeof colIdxOverride === "number" && colIdxOverride >= 0) {
                colIdx = colIdxOverride;
              } else {
                headerRow = findHeaderRow(table);
                if (!headerRow) {
                  return {
                    ok: false,
                    err: "未找到表头行（无 thead/th、首格非「省份」、文案不含成交金额等）。可设 extract.columnIndex",
                  };
                }
                headerCells = [...headerRow.querySelectorAll("th,td")].map((c) =>
                  norm(c.textContent)
                );
                colIdx = matchCol(headerCells);
                if (colIdx < 0) {
                  return {
                    ok: false,
                    err: "列头未匹配「" + needle + "」，当前表头: " + headerCells.join(" | "),
                  };
                }
              }
              const allTr = [...table.querySelectorAll("tr")];
              let rows = [];
              if (headerRow) {
                const hi = allTr.indexOf(headerRow);
                rows = hi >= 0 ? allTr.slice(hi + 1) : [];
              }
              if (!rows.length) {
                const tb = table.querySelectorAll("tbody tr");
                rows = tb && tb.length ? [...tb] : [...allTr];
              }
              if (headerRow) {
                rows = rows.filter((tr) => tr !== headerRow);
              }
              if (
                typeof colIdxOverride === "number" &&
                colIdxOverride >= 0 &&
                rows.length
              ) {
                const fr = rows[0];
                const fc = norm(fr.querySelector("th,td")?.textContent || "");
                const rt = norm(fr.textContent || "");
                if (
                  fc === "省份" ||
                  (rt.includes("成交") && rt.includes("订单") && rt.includes("元"))
                ) {
                  rows = rows.slice(1);
                }
              }
              const nums = [];
              for (const tr of rows) {
                const cells = tr.querySelectorAll("td");
                if (cells.length <= colIdx) continue;
                const t = norm(cells[colIdx].textContent);
                const m = t.replace(/,/g, "").match(/-?[0-9]+(?:\\.[0-9]+)?/);
                if (m) nums.push(parseFloat(m[0]));
              }
              if (!nums.length) {
                return { ok: false, err: "该列无有效数字（数据行=" + rows.length + "）" };
              }
              const sig = rows
                .map((tr) => norm(tr.textContent || ""))
                .filter((x) => x)
                .join("||")
                .slice(0, 1200);
              return {
                ok: true,
                nums: nums,
                n: nums.length,
                colIdx: colIdx,
                used: used,
                headers: headerCells.length ? headerCells.join(" | ") : "(columnIndex)",
                rowSig: sig,
              };
            }""",
            [sels, header_needle, col_idx_override],
        )

    all_nums: list = []
    seen_sig: set = set()
    used_desc = ""
    col_desc = ""
    pages_used = 0
    for i in range(max_pages):
        try:
            result = _read_one_page()
        except Exception as e:
            return "", f"evaluate 失败: {e}"
        if not isinstance(result, dict):
            return "", "脚本返回异常"
        if not result.get("ok"):
            return "", str(result.get("err") or "未知错误")
        nums = result.get("nums") or []
        row_sig = str(result.get("rowSig") or "")
        if row_sig and row_sig in seen_sig:
            break
        if row_sig:
            seen_sig.add(row_sig)
        for n in nums:
            try:
                all_nums.append(float(n))
            except Exception:
                continue
        pages_used = i + 1
        used_desc = str(result.get("used") or "")[:120]
        col_desc = str(result.get("colIdx"))
        if not paginate_all:
            break
        ok_click, _detail_click = _click_selector_chain(
            page,
            next_sels,
            wait_visible_ms=min(max(2000, timeout_ms), 12000),
            skip_scroll_into_view=True,
        )
        if not ok_click:
            break
        if next_wait_ms > 0:
            try:
                page.wait_for_timeout(next_wait_ms)
            except Exception:
                pass
    if not all_nums:
        return "", "多页聚合后未得到有效数字"
    if integer_only:
        bad = [x for x in all_nums if abs(x - round(x)) > 1e-9]
        if bad:
            return "", f"integerOnly=true 但检测到非整数值: {bad[:3]}"
    if agg == "sum":
        val_num = sum(all_nums)
    else:
        val_num = sum(all_nums) / len(all_nums)
    # 输出规范：默认两位小数；integerOnly 为 true 时按整数输出。
    if integer_only:
        val = str(int(round(val_num)))
    else:
        val = f"{val_num:.2f}"
    detail = f"tableColumnAgg:{used_desc}#col{col_desc} n={len(all_nums)} p={pages_used} {agg}"
    return val, detail


def _timed_extract_table_column_agg(
    page: Any,
    timeout_ms: int,
    field_dict: dict,
    *,
    args: Any,
    account: str,
    page_id: str,
    field_key: str,
) -> Tuple[str, str]:
    t0 = time.perf_counter()
    try:
        return _extract_table_column_agg(page, timeout_ms, field_dict)
    finally:
        _timing_append_ms(
            args,
            account=account,
            page_id=page_id,
            phase="field",
            step="extract_table_column_agg",
            detail=(field_key or "")[:200],
            t_start=t0,
        )


def _extract_table_total_by_header(
    page: Any,
    timeout_ms: int,
    field_dict: dict,
) -> Tuple[str, str]:
    """
    extract.type=tableTotalByHeader：
    在表格中按列头匹配 columnHeaderMatch，再在汇总行读取该列值。
    汇总行默认按 totalRowMatch 等文案匹配；设 totalRowStrategy=firstBodyRow 时直接取 tbody 首行（表体第一行即合计/总和）。
    """
    ext = field_dict.get("extract") if isinstance(field_dict, dict) else None
    if not isinstance(ext, dict):
        return "", "extract 须为对象"
    sels = _table_column_agg_selectors(field_dict)
    if not sels:
        return "", "缺少 tableSelector / selector"
    header_needle = str(ext.get("columnHeaderMatch") or ext.get("columnHeader") or "").strip()
    if not header_needle:
        return "", "缺少 columnHeaderMatch"
    header_needles: list = [header_needle]
    h_alt = ext.get("columnHeaderMatchAlternates")
    if isinstance(h_alt, list):
        for x in h_alt:
            s = str(x or "").strip()
            if s and s not in header_needles:
                header_needles.append(s)
    row_strategy = str(ext.get("totalRowStrategy") or "matchText").strip().lower()
    tr_primary = str(ext.get("totalRowMatch") or "总和").strip()
    total_needles: list = [tr_primary] if tr_primary else ["总和"]
    alt_raw = ext.get("totalRowMatchAlternates")
    if isinstance(alt_raw, list):
        for a in alt_raw:
            s = str(a or "").strip()
            if s and s not in total_needles:
                total_needles.append(s)
    first_number_only = bool(ext.get("firstNumberOnly"))

    last_vis_err = ""
    for sel in sels:
        try:
            page.locator(sel).first.wait_for(
                state="visible", timeout=min(max(500, timeout_ms), 60000)
            )
            last_vis_err = ""
            break
        except Exception as e:
            last_vis_err = str(e)
            continue
    else:
        return "", f"表格未可见（已试 {len(sels)} 个选择器）: {last_vis_err[:200]}"

    try:
        result = page.evaluate(
            """([selectors, headerNeedles, totalNeedles, firstNumberOnly, totalRowStrategy]) => {
              const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
              const headerNeedleList = (Array.isArray(headerNeedles) && headerNeedles.length)
                ? headerNeedles.map((x) => norm(x)).filter(Boolean)
                : [];
              const totalNeedleList = (Array.isArray(totalNeedles) && totalNeedles.length)
                ? totalNeedles.map((x) => norm(x)).filter(Boolean)
                : [norm("总和")];
              const strat = norm(totalRowStrategy || "matchText").toLowerCase();
              const firstNum = (s) => {
                const m = String(s || "").replace(/,/g, "").match(/-?[0-9]+(?:\\.[0-9]+)?/);
                return m ? m[0] : "";
              };
              const pickTable = () => {
                const candidates = [];
                for (const s of selectors) {
                  const root = document.querySelector(s);
                  if (!root) continue;
                  const t = root.tagName === "TABLE" ? root : root.querySelector("table");
                  if (t) candidates.push({ table: t, used: s });
                }
                if (!candidates.length) return { table: null, used: "" };
                if (strat === "firstbodyrow" || strat === "first") {
                  const withBody = candidates.find((c) => c.table.querySelector("tbody tr"));
                  if (withBody) return withBody;
                }
                return candidates[0];
              };
              const picked = pickTable();
              const table = picked.table;
              const used = picked.used;
              if (!table) return { ok: false, err: "选择器下无 table 元素" };
              const headRow =
                table.querySelector("thead tr") ||
                [...table.querySelectorAll("tr")].find((tr) => tr.querySelector("th"));
              if (!headRow) return { ok: false, err: "未找到表头行" };
              const headers = [...headRow.querySelectorAll("th,td")].map((x) => norm(x.textContent));
              let colIdx = -1;
              let matchedHeader = "";
              for (const needle of headerNeedleList) {
                if (!needle) continue;
                for (let i = 0; i < headers.length; i++) {
                  const h = headers[i];
                  if (h === needle || h.includes(needle)) {
                    colIdx = i;
                    matchedHeader = needle;
                    break;
                  }
                }
                if (colIdx >= 0) break;
              }
              if (colIdx < 0) {
                return {
                  ok: false,
                  err:
                    "列头未匹配（已试: " +
                    headerNeedleList.join("、") +
                    "），当前表头: " +
                    headers.join(" | "),
                };
              }
              let row = null;
              let matchedTotal = "";
              if (strat === "firstbodyrow" || strat === "first") {
                const tb = table.querySelector("tbody");
                if (tb) {
                  row = tb.querySelector("tr");
                }
                if (!row) {
                  const trs = [...table.querySelectorAll("tr")];
                  const hi = headRow ? trs.indexOf(headRow) : -1;
                  row = hi >= 0 ? trs[hi + 1] : trs[1] || null;
                }
                matchedTotal = "firstBodyRow";
              } else {
                const allRows = [...table.querySelectorAll("tbody tr, tr")];
                for (const tn of totalNeedleList) {
                  if (!tn) continue;
                  row = allRows.find((tr) => norm(tr.textContent).includes(tn));
                  if (row) {
                    matchedTotal = tn;
                    break;
                  }
                }
                if (!row) {
                  return { ok: false, err: "未找到汇总行（已试: " + totalNeedleList.join("、") + "）" };
                }
              }
              if (!row) {
                return { ok: false, err: "未找到表体首行（firstBodyRow）" };
              }
              const tds = row.querySelectorAll("td,th");
              if (tds.length <= colIdx) return { ok: false, err: "汇总行列数不足，colIdx=" + colIdx };
              let val = norm(tds[colIdx].textContent);
              if (firstNumberOnly) {
                const n = firstNum(val);
                if (n) val = n;
              }
              return {
                ok: true,
                value: val,
                colIdx,
                used,
                totalRow: matchedTotal,
                header: matchedHeader,
              };
            }""",
            [sels, header_needles, total_needles, first_number_only, row_strategy],
        )
    except Exception as e:
        return "", f"evaluate 失败: {e}"

    if not isinstance(result, dict):
        return "", "脚本返回异常"
    if not result.get("ok"):
        return "", str(result.get("err") or "未知错误")
    val = str(result.get("value") or "").strip()
    if not val:
        return "", "汇总行目标列值为空"
    tr_m = str(result.get("totalRow") or "").strip()
    hd_m = str(result.get("header") or "").strip()
    suf = f" row={tr_m}" if tr_m else ""
    huf = f" hdr={hd_m}" if hd_m else ""
    return val, f"tableTotalByHeader:{result.get('used','')[:120]}#col{result.get('colIdx')}{suf}{huf}"


def _parse_num_text(s: Any) -> Optional[float]:
    if s is None:
        return None
    t = str(s).strip().replace(",", "")
    if not t:
        return None
    m = re.search(r"-?[0-9]+(?:\.[0-9]+)?", t)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _first_number_text(s: Any) -> str:
    """提取文本中的第一个数字串（含可选小数），未命中则返回空串。"""
    if s is None:
        return ""
    t = str(s).strip().replace(",", "")
    if not t:
        return ""
    m = re.search(r"-?[0-9]+(?:\.[0-9]+)?", t)
    return m.group(0) if m else ""


def _extract_computed_divide(field_dict: dict, value_ctx: dict) -> Tuple[str, str]:
    """
    extract.type=computedDivide
    通过已有字段值做除法：numeratorKey / denominatorKey，结果保留两位小数。
    """
    ext = field_dict.get("extract") if isinstance(field_dict, dict) else None
    if not isinstance(ext, dict):
        return "", "extract 须为对象"
    nkey = str(ext.get("numeratorKey") or "").strip()
    dkey = str(ext.get("denominatorKey") or "").strip()
    if not nkey or not dkey:
        return "", "缺少 numeratorKey/denominatorKey"
    nval = _parse_num_text(value_ctx.get(nkey))
    dval = _parse_num_text(value_ctx.get(dkey))
    if nval is None or dval is None:
        return "", f"依赖字段缺失或非数值: {nkey}/{dkey}"
    if abs(dval) < 1e-12:
        return "", f"分母为 0: {dkey}"
    return f"{(nval / dval):.2f}", f"computedDivide:{nkey}/{dkey}"


def _step_match_index(step: dict) -> Optional[int]:
    """interactions[].matchIndex：同一 selector 命中多个节点时取第几个（0=第一个，自上而下 DOM 顺序）。
    注意：若 selector 写成「所有行的下载按钮」而首行尚无按钮，第 0 个匹配可能已是第二行——导出类应把选择器限定在首行容器（如 li[1]、li:nth-child(1)）内。"""
    if not isinstance(step, dict):
        return None
    raw = step.get("matchIndex")
    if raw is None:
        return None
    try:
        i = int(raw)
    except (TypeError, ValueError):
        return None
    return max(0, i)


def _locator_nth_match(page: Any, selector: str, match_idx: Optional[int]) -> Any:
    loc = page.locator(selector)
    if match_idx is None:
        return loc.first
    return loc.nth(match_idx)


def _collect_click_selectors(step: dict, tgt: dict) -> list:
    """主 selector + alternateClickSelector（字符串或数组），去重保序。"""
    out: list = []
    if isinstance(tgt, dict):
        s = str(tgt.get("selector") or "").strip()
        if s:
            out.append(s)
    if not isinstance(step, dict):
        return out
    alt = step.get("alternateClickSelector")
    if isinstance(alt, str) and alt.strip():
        sx = alt.strip()
        if sx not in out:
            out.append(sx)
    elif isinstance(alt, list):
        for x in alt:
            sx = str(x or "").strip()
            if sx and sx not in out:
                out.append(sx)
    return out


def _export_control_any_visible(
    page: Any,
    selectors: list,
    match_idx: Optional[int],
    per_selector_timeout_ms: int,
) -> bool:
    """任一条 selector 对应节点在短时内可见则 True（用于轮询「下载」是否已就绪）。"""
    to = max(200, min(int(per_selector_timeout_ms or 800), 8000))
    for sel in selectors:
        sx = (sel or "").strip()
        if not sx:
            continue
        try:
            loc = _locator_nth_match(page, sx, match_idx)
            loc.wait_for(state="visible", timeout=to)
            return True
        except Exception:
            continue
    return False


def _wait_export_ready_with_refreshes(
    page: Any,
    selectors: list,
    match_idx: Optional[int],
    *,
    ready_timeout_ms: int,
    max_refreshes: int,
    reload_wait_ms: int,
    poll_interval_ms: int,
    step_key: str = "",
) -> Tuple[bool, str]:
    """
    在 ready_timeout_ms 内轮询 selector，直至任一条可见；超时则 reload，重复最多 max_refreshes 次刷新。
    用于历史报表「生成中」时暂无「下载」按钮的场景。
    """
    rtm = max(3000, min(int(ready_timeout_ms or 45000), 180000))
    rm = max(0, min(int(max_refreshes or 0), 30))
    rw = max(0, min(int(reload_wait_ms or 1000), 120000))
    poll = max(500, min(int(poll_interval_ms or 1500), 30000))
    refreshes_done = 0
    sk = (step_key or "").strip() or "export"
    while True:
        deadline = time.monotonic() + rtm / 1000.0
        while time.monotonic() < deadline:
            if _export_control_any_visible(page, selectors, match_idx, 900):
                if refreshes_done > 0:
                    print(
                        f"[{sk}] 刷新后已出现下载控件（本轮共刷新 {refreshes_done} 次）",
                        file=sys.stderr,
                    )
                return True, ""
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                page.wait_for_timeout(min(poll, max(100, int(remaining * 1000))))
            except Exception:
                pass
        if refreshes_done >= rm:
            return (
                False,
                f"{rtm}ms 内未出现下载控件，已刷新 {refreshes_done} 次仍不可见",
            )
        refreshes_done += 1
        print(
            f"[{sk}] {rtm}ms 内未发现下载控件，刷新页面 ({refreshes_done}/{rm})…",
            file=sys.stderr,
        )
        try:
            page.reload(wait_until="domcontentloaded", timeout=90000)
        except Exception as e:
            return False, f"刷新历史报表页失败: {e}"
        if rw > 0:
            try:
                page.wait_for_timeout(min(rw, 600000))
            except Exception:
                pass


def _collect_open_export_tab_selectors(step: dict) -> list:
    """openExportTabTarget + alternateOpenExportTabSelector，用于点击后新开标签页的「导出」等。"""
    out: list = []
    if not isinstance(step, dict):
        return out
    tgt = step.get("openExportTabTarget") or {}
    if isinstance(tgt, dict):
        s = str(tgt.get("selector") or "").strip()
        if s:
            out.append(s)
    alt = step.get("alternateOpenExportTabSelector")
    if isinstance(alt, str) and alt.strip():
        sx = alt.strip()
        if sx not in out:
            out.append(sx)
    elif isinstance(alt, list):
        for x in alt:
            sx = str(x or "").strip()
            if sx and sx not in out:
                out.append(sx)
    return out


def _click_opens_new_tab_for_export(
    page: Any,
    open_selectors: list,
    mi: Optional[int],
    vw: int,
    *,
    expect_timeout_ms: int = 60000,
) -> Tuple[Any, str]:
    """
    点击会新开标签页的按钮；返回 (新 Page, "") 或 (None, 错误信息)。
    优先 BrowserContext.expect_page；否则轮询 context.pages 数量变化。
    """
    ctx = getattr(page, "context", None)
    if ctx is None:
        return None, "当前 page 无 context"
    last_err = ""
    exp_page = getattr(ctx, "expect_page", None)
    to = max(5000, min(int(expect_timeout_ms or 60000), 300000))
    for sel in open_selectors:
        sx = (sel or "").strip()
        if not sx:
            continue
        try:
            loc = _locator_nth_match(page, sx, mi)
            np: Any = None
            if exp_page is not None and callable(exp_page):
                with exp_page(timeout=to) as pi:
                    sc_to = max(4000, min(max(vw, 5000), 22500))
                    try:
                        loc.scroll_into_view_if_needed(timeout=sc_to)
                    except Exception:
                        pass
                    try:
                        page.wait_for_timeout(60)
                    except Exception:
                        pass
                    try:
                        loc.click(timeout=7500)
                    except Exception:
                        loc.click(timeout=7500, force=True)
                np = pi.value
            else:
                n0 = len(ctx.pages)
                sc_to = max(4000, min(max(vw, 5000), 22500))
                try:
                    loc.scroll_into_view_if_needed(timeout=sc_to)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(60)
                except Exception:
                    pass
                try:
                    loc.click(timeout=7500)
                except Exception:
                    loc.click(timeout=7500, force=True)
                deadline = time.monotonic() + to / 1000.0
                while time.monotonic() < deadline:
                    if len(ctx.pages) > n0:
                        np = ctx.pages[-1]
                        break
                    try:
                        page.wait_for_timeout(200)
                    except Exception:
                        break
                if np is None:
                    last_err = f"未检测到新标签页（{sx}）"
                    continue
            if np is not None:
                try:
                    np.wait_for_load_state("domcontentloaded", timeout=90000)
                except Exception:
                    pass
                return np, ""
        except Exception as e:
            last_err = str(e)
            continue
    return None, last_err or "打开导出页（新标签）失败"


def _try_export_download_once(
    page: Any,
    step: dict,
    selectors: list,
    mi: Optional[int],
    vw: int,
    edl: int,
    download_dir: Path,
    dl_prefix: str,
    step_key: str,
    *,
    account: str = "",
    yday: str = "",
    task_name: str = "",
) -> Tuple[bool, str, str, str]:
    """
    单次导出尝试：pre_export（若 preExportRefreshMax>0）+ 选择器链 + getByRole 兜底。
    若 exportClickOpensNewTab：先在当前页点「导出」打开新标签，再在新页执行下载选择器链。
    返回 (ok, saved_path, detail, last_err)。
    """
    last_err = ""
    ok = False
    saved_path = ""
    detail = ""
    new_tab: Any = None
    st = step if isinstance(step, dict) else {}
    opens_new = bool(st.get("exportClickOpensNewTab"))

    try:
        pre_max = int(st.get("preExportRefreshMax") or 0)
    except (TypeError, ValueError):
        pre_max = 0
    use_for_pre = selectors
    if opens_new:
        pm = st.get("preExportReadySelectorsOnMain")
        if isinstance(pm, list) and any(str(x or "").strip() for x in pm):
            use_for_pre = [str(x).strip() for x in pm if str(x or "").strip()]
        else:
            use_for_pre = []

    if pre_max > 0 and use_for_pre:
        try:
            pr_to = int(st.get("preExportReadyTimeoutMs") or 45000)
        except (TypeError, ValueError):
            pr_to = 45000
        try:
            pr_rw = int(st.get("preExportReloadWaitMs") or 1000)
        except (TypeError, ValueError):
            pr_rw = 1000
        try:
            pr_poll = int(st.get("preExportPollIntervalMs") or 1500)
        except (TypeError, ValueError):
            pr_poll = 1500
        ok_pre, err_pre = _wait_export_ready_with_refreshes(
            page,
            use_for_pre,
            mi,
            ready_timeout_ms=pr_to,
            max_refreshes=pre_max,
            reload_wait_ms=pr_rw,
            poll_interval_ms=pr_poll,
            step_key=step_key,
        )
        if not ok_pre:
            return False, "", "", (err_pre or "pre_export 未就绪")

    work_page = page
    try:
        if opens_new:
            open_sels = _collect_open_export_tab_selectors(st)
            if not open_sels:
                return False, "", "", (
                    "exportClickOpensNewTab 为 true 但未配置 openExportTabTarget 或 alternateOpenExportTabSelector"
                )
            try:
                expect_new_ms = int(st.get("openExportTabTimeoutMs") or 60000)
            except (TypeError, ValueError):
                expect_new_ms = 60000
            new_tab, err_nt = _click_opens_new_tab_for_export(
                page,
                open_sels,
                mi,
                vw,
                expect_timeout_ms=expect_new_ms,
            )
            if err_nt or not new_tab:
                return False, "", "", (err_nt or "未能打开新标签页")
            work_page = new_tab
            try:
                pwait = int(st.get("postOpenExportTabWaitMs") or 0)
            except (TypeError, ValueError):
                pwait = 0
            if pwait > 0:
                try:
                    work_page.wait_for_timeout(min(pwait, 120000))
                except Exception:
                    pass

        for try_sel in selectors:
            loc = _locator_nth_match(work_page, try_sel, mi)
            ok, saved_path, err = _export_click_and_save(
                work_page,
                loc,
                vw,
                edl,
                download_dir,
                dl_prefix,
                filename_template=str(st.get("downloadFileNameTemplate") or "").strip(),
                account=account,
                yday=yday,
                task_name=task_name,
            )
            if ok:
                detail = try_sel
                break
            last_err = err
        if not ok:
            ok_fb, path_fb, err_fb = _export_download_get_by_role_fallback(
                work_page,
                st,
                vw,
                edl,
                download_dir,
                mi,
                dl_prefix,
                account=account,
                yday=yday,
                task_name=task_name,
            )
            if ok_fb:
                ok = True
                saved_path = path_fb
                detail = f"getByRoleFallback:{step_key}"
            elif err_fb:
                last_err = (last_err + "; " if last_err else "") + err_fb
        return ok, saved_path, detail, last_err
    finally:
        if new_tab is not None and bool(st.get("closeExportNewTabWhenDone")):
            try:
                new_tab.close()
            except Exception:
                pass
            try:
                page.bring_to_front()
            except Exception:
                pass


def _click_selector_chain(
    page: Any,
    selectors: list,
    wait_visible_ms: int = 10000,
    match_idx: Optional[int] = None,
    *,
    skip_scroll_into_view: bool = False,
) -> tuple:
    """依次尝试；先等到可见再滚入视口后点击（避免 DOM 未就绪时 scroll_into_view 先超时）。
    分页 / portal 下拉可模板设 skipScrollIntoView 跳过滚动。"""
    last_err = ""
    wv = max(1000, min(int(wait_visible_ms or 10000), 600000))
    for sel in selectors:
        sx = (sel or "").strip()
        if not sx:
            continue
        try:
            loc = _locator_nth_match(page, sx, match_idx)
            loc.wait_for(state="visible", timeout=wv)
            if not skip_scroll_into_view:
                # 滚入与「可见等待」对齐，避免 wv=1100 时 sc 仍卡 4000ms 却等不到节点
                sc_to = max(6000, min(max(wv, 5000), 25000))
                try:
                    loc.scroll_into_view_if_needed(timeout=sc_to)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(80)
                except Exception:
                    pass
            try:
                loc.click(timeout=8500)
            except Exception:
                loc.click(timeout=8500, force=True)
            return True, sx
        except Exception as e:
            last_err = str(e)
    return False, last_err or "无可用选择器"


def _click_with_fallback(
    page: Any, primary: str, alternate: Optional[str], wait_visible_ms: int = 10000
) -> tuple:
    selectors = [s for s in (primary, alternate) if (s or "").strip()]
    return _click_selector_chain(page, selectors, wait_visible_ms)


def _expect_download_context_mgr(page: Any, edl: int) -> Any:
    """
    返回 expect_download 的上下文管理器。部分旧版 Playwright 的 BrowserContext 无 expect_download，
    仅 Page 有，此时回退到 page.expect_download（跨页下载可能漏接，优于直接报错）。
    """
    ctx = getattr(page, "context", None)
    exp = getattr(ctx, "expect_download", None) if ctx is not None else None
    if exp is not None and callable(exp):
        return exp(timeout=edl)
    return page.expect_download(timeout=edl)


def _export_click_and_save(
    page: Any,
    loc: Any,
    vw: int,
    edl: int,
    download_dir: Path,
    filename_prefix: str = "",
    *,
    filename_template: str = "",
    account: str = "",
    yday: str = "",
    task_name: str = "",
) -> tuple:
    """对定位器点击后 expect_download 并保存。优先 BrowserContext（若存在 expect_download）。"""
    try:
        loc.wait_for(state="visible", timeout=vw)
        sc_to = max(6000, min(max(vw, 8000), 25000))
        try:
            loc.scroll_into_view_if_needed(timeout=sc_to)
        except Exception:
            pass
        try:
            page.wait_for_timeout(80)
        except Exception:
            pass
        dl_cm = _expect_download_context_mgr(page, edl)
        with dl_cm as dl_info:
            try:
                loc.click(timeout=7500)
            except Exception:
                loc.click(timeout=7500, force=True)
        download = dl_info.value
        suggested = download.suggested_filename or f"download_{dt.now().strftime('%Y%m%d_%H%M%S')}"
        templated = _render_download_name_template(
            filename_template,
            account=account,
            yday=yday,
            task_name=task_name,
            suggested=suggested,
        )
        safe = re.sub(r'[<>:"/\\\\|?*]', "_", templated or suggested)
        pref = _sanitize_filename_prefix(filename_prefix)
        if pref and not safe.startswith(pref + "_"):
            safe = f"{pref}_{safe}"
        target = download_dir / safe
        download.save_as(str(target))
        return True, str(target), ""
    except Exception as e:
        return False, "", str(e)


def _export_download_one_role_fb(
    page: Any,
    fb: dict,
    vw: int,
    edl: int,
    download_dir: Path,
    match_idx: Optional[int],
    filename_prefix: str = "",
    *,
    filename_template: str = "",
    account: str = "",
    yday: str = "",
    task_name: str = "",
) -> tuple:
    """单条 getByRoleFallback 字典：点 button/link 等并 expect_download。"""
    role = str(fb.get("role") or "button").strip() or "button"
    nm = str(fb.get("name") or "").strip()
    if not nm:
        return False, "", ""
    scope_one = str(fb.get("scopeSelector") or "").strip()
    row_scope = str(fb.get("rowScope") or "").strip() or "#root li"
    row_filter = str(fb.get("rowFilterHasText") or "").strip()
    try:
        ri = int(fb.get("rowIndex") if fb.get("rowIndex") is not None else 0)
    except (TypeError, ValueError):
        ri = 0
    try:
        if scope_one:
            chain = page.locator(scope_one).first.get_by_role(role, name=nm)
        elif row_filter:
            chain = page.locator(row_scope).filter(has_text=row_filter).first.get_by_role(role, name=nm)
        else:
            chain = page.locator(row_scope).nth(ri).get_by_role(role, name=nm)
        loc = chain.first if match_idx is None else chain.nth(match_idx)
        return _export_click_and_save(
            page,
            loc,
            vw,
            edl,
            download_dir,
            filename_prefix,
            filename_template=filename_template,
            account=account,
            yday=yday,
            task_name=task_name,
        )
    except Exception as e:
        return False, "", str(e)


def _export_download_text_in_row(
    page: Any,
    label: str,
    row_scope: str,
    row_index: int,
    vw: int,
    edl: int,
    download_dir: Path,
    filename_prefix: str = "",
    *,
    filename_template: str = "",
    account: str = "",
    yday: str = "",
    task_name: str = "",
) -> tuple:
    """首行内精确文案「下载」等（常见于 a 或 span 包裹，无稳定 role）。"""
    try:
        row = page.locator(row_scope).nth(row_index)
        loc = row.get_by_text(label, exact=True).first
        return _export_click_and_save(
            page,
            loc,
            vw,
            edl,
            download_dir,
            filename_prefix,
            filename_template=filename_template,
            account=account,
            yday=yday,
            task_name=task_name,
        )
    except Exception as e:
        return False, "", str(e)


def _export_download_get_by_role_fallback(
    page: Any,
    step: dict,
    vw: int,
    edl: int,
    download_dir: Path,
    match_idx: Optional[int] = None,
    filename_prefix: str = "",
    *,
    account: str = "",
    yday: str = "",
    task_name: str = "",
) -> tuple:
    """
    getByRoleFallback：单对象或数组；依次尝试 role=button、link 等。
    仍失败则试首行内 get_by_text（页面「下载」多为可点击链接）。
    """
    fb = step.get("getByRoleFallback")
    items: list = []
    if isinstance(fb, dict):
        items = [fb]
    elif isinstance(fb, list):
        items = [x for x in fb if isinstance(x, dict)]
    filename_template = str(step.get("downloadFileNameTemplate") or "").strip()
    last_err = ""
    for it in items:
        ok, path, err = _export_download_one_role_fb(
            page,
            it,
            vw,
            edl,
            download_dir,
            match_idx,
            filename_prefix,
            filename_template=filename_template,
            account=account,
            yday=yday,
            task_name=task_name,
        )
        if ok:
            return True, path, ""
        if err:
            last_err = err
    # 文案点击兜底：与模板首行 rowIndex=0 对齐
    if items:
        first = items[0]
        nm = str(first.get("name") or "下载").strip() or "下载"
        row_scope = str(first.get("rowScope") or "").strip() or "#root li"
        try:
            ri = int(first.get("rowIndex") if first.get("rowIndex") is not None else 0)
        except (TypeError, ValueError):
            ri = 0
        ok2, path2, err2 = _export_download_text_in_row(
            page,
            nm,
            row_scope,
            ri,
            vw,
            edl,
            download_dir,
            filename_prefix,
            filename_template=filename_template,
            account=account,
            yday=yday,
            task_name=task_name,
        )
        if ok2:
            return True, path2, ""
        if err2:
            last_err = (last_err + "; " if last_err else "") + err2
    return False, "", last_err


def _fill_one_input(el: Any, day: str) -> bool:
    try:
        el.fill(day, timeout=4000, force=True)
        return True
    except Exception:
        try:
            el.evaluate(
                """(node, v) => {
                    node.removeAttribute('readonly');
                    node.removeAttribute('disabled');
                    node.value = v;
                    node.dispatchEvent(new Event('input', { bubbles: true }));
                    node.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                day,
            )
            return True
        except Exception:
            return False


def _date_range_container_candidates(primary: str) -> list:
    """千川成本卡：新版为 ovui-custom-input / ovui-range-picker；旧版为 oc-picker；nth-child 易失效。"""
    p = (primary or "").strip()
    fallbacks = [
        ".oc-card.cost-container.mb-16 div.ovui-custom-input--readonly",
        ".oc-card.cost-container.mb-16 .ovui-custom-input",
        ".oc-card.cost-container.mb-16 .ovui-range-picker__calendar-icon",
        ".oc-card.cost-container.mb-16 .ovui-range-picker__input input.ovui-input",
        ".oc-card.cost-container.mb-16 .header__right .oc-picker",
        ".oc-card.cost-container.mb-16 .header__right div.oc-picker",
        ".oc-card.cost-container.mb-16 div.header__right div[class*='Picker']",
        ".oc-card.cost-container.mb-16 div.header__right div[class*='picker']",
        ".oc-card.cost-container.mb-16 .header__right > div:nth-child(2) > div",
        ".oc-card.cost-container.mb-16 .header__right > div:nth-child(1) > div",
        ".oc-card.cost-container.mb-16 .header__right > div:nth-child(3) > div",
        "div.oc-layout__main-content .oc-card.cost-container.mb-16 .header__right > div:nth-child(2) > div > div > div > div",
    ]
    out = []
    seen = set()
    for s in [p] + fallbacks if p else fallbacks:
        s = (s or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _try_readonly_range_portal_footer_confirm(page: Any) -> bool:
    """
    只读范围日期弹层：点完起止日后点 footer 确认。
    拼多多等 portal 常见结构：body 下某层 div 内 footer/button。
    """
    xpaths = (
        "/html/body/div[3]/div/div/div/div/div/footer/button",
    )
    for xp in xpaths:
        try:
            loc = page.locator("xpath=" + xp).first
            if loc.count() > 0 and loc.is_visible(timeout=1200):
                loc.click(timeout=3000)
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    return False


def _confirm_date_panel(page: Any) -> None:
    for label in ("确定", "应用", "OK", "查询"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass
        try:
            b = page.locator(f"button:has-text('{label}')").first
            if b.is_visible(timeout=800):
                b.click(timeout=3000)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


def _locator_visible_short(page: Any, selector: str, timeout_ms: int = 400) -> bool:
    """短超时探测可见性，用于关键弹层判断；失败视为不可见。"""
    try:
        loc = page.locator(selector).first
        return loc.count() > 0 and loc.is_visible(timeout=timeout_ms)
    except Exception:
        return False


def _critical_interaction_layer_visible(page: Any) -> bool:
    """
    若当前存在明显属于「正在操作的业务流程」的弹层，则跳过全局突发弹窗清理，
    避免 ESC/误点关掉切店、选日期、确认生成等必需界面。
    """
    try:
        if page.get_by_text("请选择店铺", exact=False).first.is_visible(timeout=400):
            if _locator_visible_short(page, "div[class*='index_roleList']", 350):
                return True
    except Exception:
        pass
    try:
        if _locator_visible_short(page, "div.auxo-modal-wrap div[class*='index_roleList']", 450):
            return True
    except Exception:
        pass
    # 千川 OVUI 日期浮层已展开
    if _locator_visible_short(page, "div.ovui-range-picker__popper--show", 350):
        return True
    # 抖店 auxo 日期/下拉面板
    if _locator_visible_short(page, ".auxo-picker-panel-container", 350):
        return True
    try:
        dd = page.locator(".auxo-picker-dropdown").first
        if dd.count() > 0 and dd.is_visible(timeout=350):
            return True
    except Exception:
        pass
    return False


def _try_dismiss_express_interception_reminder_modal(page: Any) -> None:
    """
    抖店售后等页可能出现的「快递拦截开通提醒」营销弹窗（auxo-modal-centered），
    挡在筛选/导出前。优先点标题区关闭（.auxo-modal-close-x），失败再点「取消」。
    不依赖 body > div:nth-child(n) 等易变路径。
    """
    if _critical_interaction_layer_visible(page):
        return
    try:
        wrap = page.locator("div.auxo-modal-wrap.auxo-modal-centered").filter(
            has_text=re.compile(r"快递拦截")
        )
        if wrap.count() == 0:
            return
        box = wrap.first
        if not box.is_visible(timeout=700):
            return
        for sel in (
            ".auxo-modal-header .auxo-modal-close",
            "button.auxo-modal-close",
            "button:has(.auxo-modal-close-x)",
            "span.auxo-modal-close-x",
            ".auxo-modal-close-x",
        ):
            try:
                cand = box.locator(sel)
                if cand.count() == 0:
                    continue
                el = cand.first
                if not el.is_visible(timeout=500):
                    continue
                el.click(timeout=3000)
                page.wait_for_timeout(400)
                return
            except Exception:
                continue
        try:
            box.get_by_role("button", name="取消").first.click(timeout=3000)
            page.wait_for_timeout(400)
        except Exception:
            pass
    except Exception:
        pass


def _try_dismiss_extra_nuisance_overlays(page: Any) -> None:
    """
    在「非关键业务弹层」前提下，尝试关闭少量常见干扰层（仅点明确关闭/知道了，不发全局 ESC）。
    保守：命中失败静默忽略；若与业务弹层冲突请改选择器或依赖 critical 检测。
    """
    if _critical_interaction_layer_visible(page):
        return
    # (容器需大致可见，再点其内关闭类节点，避免点到页面主按钮)
    rules: list = [
        (
            "[class*='index_mask'][class*='mask']",
            (
                "[class*='close']",
                "[class*='Close']",
                "text=我知道了",
                "text=不再提示",
            ),
        ),
        (
            "[class*='guide'][class*='mask'], [class*='guide-mask'], [class*='novice-mask']",
            (
                "button:has-text('跳过')",
                "button:has-text('我知道了')",
                "[class*='close']",
            ),
        ),
        # 千川等：底部操作条内 div.close（如「官方投放顾问」类弹窗）
        (
            "div.actions.bottom.center, .actions.bottom.center",
            (
                "div.close",
                ".close",
                "> div.close",
                "[class*='close']",
            ),
        ),
    ]
    for root_sel, close_sels in rules:
        try:
            root = page.locator(root_sel).first
            if root.count() == 0 or not root.is_visible(timeout=350):
                continue
        except Exception:
            continue
        for cs in close_sels:
            if _critical_interaction_layer_visible(page):
                return
            try:
                btn = root.locator(cs).first
                if btn.count() == 0 or not btn.is_visible(timeout=400):
                    continue
                btn.click(timeout=2500)
                page.wait_for_timeout(350)
                break
            except Exception:
                continue


def _try_dismiss_qianchuan_close_class_overlays(page: Any) -> None:
    """
    千川页额外兜底：当广告/顾问弹窗未被既有规则命中时，
    在常见弹层容器内扫描 close/关闭/X 类关闭控件并尝试点击。
    仅在 qianchuan.jinritemai.com 生效，避免跨站误伤。
    """
    if _critical_interaction_layer_visible(page):
        return
    try:
        cur_u = str(getattr(page, "url", "") or "").lower()
    except Exception:
        cur_u = ""
    if "qianchuan.jinritemai.com" not in cur_u:
        return

    root_selectors = (
        "[class*='modal']",
        "[class*='dialog']",
        "[class*='overlay']",
        "[class*='mask']",
        "[class*='popup']",
        "div.actions.bottom.center",
    )
    close_selectors = (
        "[class*='close']",
        "[aria-label*='close']",
        "[aria-label*='Close']",
        "button:has-text('关闭')",
        "a:has-text('关闭')",
        "text=我知道了",
        "text=知道了",
        "text=暂不",
        "text=跳过",
        "text=×",
        "text=X",
    )

    for root_sel in root_selectors:
        if _critical_interaction_layer_visible(page):
            return
        try:
            root = page.locator(root_sel).first
            if root.count() == 0 or not root.is_visible(timeout=350):
                continue
        except Exception:
            continue

        for cs in close_selectors:
            if _critical_interaction_layer_visible(page):
                return
            try:
                btn = root.locator(cs).first
                if btn.count() == 0 or not btn.is_visible(timeout=450):
                    continue
                txt = ""
                try:
                    txt = (btn.inner_text(timeout=300) or "").strip().lower()
                except Exception:
                    txt = ""
                cls = ""
                try:
                    cls = (btn.get_attribute("class") or "").strip().lower()
                except Exception:
                    cls = ""
                aria = ""
                try:
                    aria = (btn.get_attribute("aria-label") or "").strip().lower()
                except Exception:
                    aria = ""
                # 保守过滤：仅在文案/类名/aria 明确带关闭语义时点击
                if not any(k in (txt + " " + cls + " " + aria) for k in ("close", "关闭", "知道", "暂不", "跳过", "x", "×")):
                    continue
                btn.click(timeout=2500, force=True)
                page.wait_for_timeout(300)
                break
            except Exception:
                continue


def _try_dismiss_unexpected_overlays(page: Any) -> None:
    """
    全局突发弹窗清理入口：先判断是否存在业务必需弹层；再关抖店快递拦截营销弹窗；
    再关千川推广类蒙层；最后尝试少量安全干扰层。
    """
    if _critical_interaction_layer_visible(page):
        return
    _try_dismiss_express_interception_reminder_modal(page)
    if _critical_interaction_layer_visible(page):
        return
    _try_dismiss_blocking_overlays(page)
    if _critical_interaction_layer_visible(page):
        return
    _try_dismiss_qianchuan_close_class_overlays(page)
    if _critical_interaction_layer_visible(page):
        return
    _try_dismiss_extra_nuisance_overlays(page)


def _try_dismiss_blocking_overlays(page: Any) -> None:
    """
    千川等页：promotion-modal-wrap / promotion-modal-marsk 遮挡会导致控件在 DOM 内但非 visible。
    - dateRange 点日期前会调用；抽 fields 前也会调用（见 pages[].dismissBlockingOverlaysBeforeFields，默认 true）。
    - 策略：最多 3 轮；每轮 Escape → 点关闭类按钮 → 对蒙层 force 点击兜底；静默失败不抛。
    """
    if _critical_interaction_layer_visible(page):
        return

    def _overlay_visible() -> bool:
        for root in (".promotion-modal-wrap", "[class*='promotion-modal-wrap']"):
            try:
                w = page.locator(root).first
                if w.count() > 0 and w.is_visible(timeout=350):
                    return True
            except Exception:
                continue
        try:
            mk = page.locator(".promotion-modal-marsk, [class*='promotion-modal-marsk']").first
            return mk.count() > 0 and mk.is_visible(timeout=350)
        except Exception:
            return False

    for _ in range(3):
        if not _overlay_visible():
            return
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
        except Exception:
            pass
        if not _overlay_visible():
            return

        for sel in (
            ".promotion-modal-wrap button",
            "[class*='promotion-modal-wrap'] button",
            ".promotion-modal-wrap [class*='close']",
            ".promotion-modal-wrap [class*='Close']",
            ".promotion-modal-wrap a[class*='close']",
            ".promotion-modal-wrap >> text=关闭",
            ".promotion-modal-wrap >> text=我知道了",
            ".promotion-modal-wrap >> text=不再提示",
            ".promotion-modal-wrap >> text=暂不",
        ):
            if not _overlay_visible():
                return
            try:
                loc = page.locator(sel).first
                if loc.count() == 0:
                    continue
                if not loc.is_visible(timeout=500):
                    continue
                loc.click(timeout=3500)
                page.wait_for_timeout(450)
                break
            except Exception:
                continue

        if _overlay_visible():
            for msel in (
                ".promotion-modal-marsk",
                "[class*='promotion-modal-marsk']",
            ):
                try:
                    mk = page.locator(msel).first
                    if mk.count() == 0:
                        continue
                    if not mk.is_visible(timeout=400):
                        continue
                    mk.click(timeout=2500, force=True)
                    page.wait_for_timeout(400)
                    break
                except Exception:
                    continue


def _try_dismiss_promotion_modal(page: Any) -> None:
    """兼容旧名：现为全局突发弹窗清理（含推广蒙层 + 安全干扰层）。"""
    _try_dismiss_unexpected_overlays(page)


def _locator_click_with_scroll(
    loc: Any, *, timeout_ms: int = 8000, force: bool = False
) -> None:
    """尽量滚入视口再点；千川等页浮层内节点常被判定为「不可点」时需 force。"""
    try:
        loc.scroll_into_view_if_needed(timeout=min(5000, timeout_ms))
    except Exception:
        pass
    loc.click(timeout=timeout_ms, force=force)


def _ovui_popper_visible(page: Any) -> Any:
    """取当前可见的 OVUI 日期浮层：优先 last（新打开的），避免命中已隐藏的旧 popper 节点。"""
    loc = page.locator("div.ovui-range-picker__popper--show")
    try:
        n = loc.count()
    except Exception:
        n = 0
    if n <= 0:
        return loc.first
    return loc.nth(n - 1) if n > 1 else loc.first


def _date_range_shortcut_click_builtin_ovui(page: Any, sh_to: int) -> tuple:
    """
    千川 OVUI：不依赖 body 长链里的 --up/--down（方向 class 常变或短暂缺失），
    在可见 popper 内用「昨天」文案或 shortcuts 区第 2 项兜底。
    """
    last_err: Optional[Exception] = None
    pop = _ovui_popper_visible(page)
    try:
        pop.wait_for(state="visible", timeout=min(sh_to, 25000))
    except Exception as e:
        return False, str(e)
    sc = pop.locator(".ovui-range-picker__shortcuts")
    try:
        if sc.count() == 0:
            sc = pop.locator("[class*='range-picker__shortcuts']")
    except Exception:
        sc = pop.locator(".ovui-range-picker__shortcuts")

    candidates: list = []
    try:
        candidates.append(sc.get_by_text("昨天", exact=True))
    except Exception:
        pass
    try:
        candidates.append(pop.get_by_text("昨天", exact=True))
    except Exception:
        pass
    for c in candidates:
        try:
            if c.count() == 0:
                continue
            el = c.first
            el.wait_for(state="visible", timeout=min(8000, sh_to))
            try:
                _locator_click_with_scroll(el, timeout_ms=8000, force=False)
            except Exception as e1:
                try:
                    _locator_click_with_scroll(el, timeout_ms=8000, force=True)
                except Exception as e2:
                    last_err = e2 or e1
                    continue
            return True, "shortcutClick: 已点快捷「昨天」（OVUI 文案兜底）"
        except Exception as e:
            last_err = e
            continue

    for sel in (
        ".ovui-range-picker__shortcuts > div > div:nth-child(2)",
        "div.ovui-range-picker__shortcuts > div > div:nth-child(2)",
    ):
        try:
            items = pop.locator(sel)
            if items.count() == 0:
                continue
            el = items.first
            el.wait_for(state="visible", timeout=min(8000, sh_to))
            try:
                _locator_click_with_scroll(el, timeout_ms=8000, force=False)
            except Exception:
                _locator_click_with_scroll(el, timeout_ms=8000, force=True)
            return True, f"shortcutClick: 已点快捷区第 2 项（OVUI 结构兜底 {sel}）"
        except Exception as e:
            last_err = e
            continue
    return False, last_err


def _date_range_shortcut_click(
    page: Any,
    open_selector: str,
    shortcut_selector: str,
    container_timeout_ms: int,
    alternate_shortcut_selectors: Optional[list] = None,
) -> tuple:
    """先点打开日期面板，再点 popper 内快捷项（如「昨天」对应 nth-child）。支持多个备选（up/down 等）。"""
    o = (open_selector or "").strip()
    shortcuts: list = []
    primary = (shortcut_selector or "").strip()
    if primary:
        shortcuts.append(primary)
    if isinstance(alternate_shortcut_selectors, list):
        for a in alternate_shortcut_selectors:
            ax = str(a or "").strip()
            if ax and ax not in shortcuts:
                shortcuts.append(ax)
    if not o:
        return False, "shortcutClick 需要 target.selector（打开面板）"
    if not shortcuts:
        return False, "shortcutClick 需要 shortcutSelector 或 alternateShortcutSelector"
    budget = max(15000, int(container_timeout_ms))
    try:
        op = page.locator(o).first
        op.wait_for(state="visible", timeout=budget)
        op.click(timeout=10000)
    except Exception as e:
        return False, f"点击日期入口失败: {e}"
    try:
        page.wait_for_timeout(1200)
    except Exception:
        pass
    try:
        _ovui_popper_visible(page).wait_for(state="visible", timeout=20000)
    except Exception:
        pass
    sh_to = max(20000, min(45000, int(container_timeout_ms)))
    last_err: Optional[Exception] = None
    for s in shortcuts:
        try:
            sh = page.locator(s).first
            sh.wait_for(state="visible", timeout=sh_to)
            try:
                _locator_click_with_scroll(sh, timeout_ms=8000, force=False)
            except Exception:
                _locator_click_with_scroll(sh, timeout_ms=8000, force=True)
            try:
                page.wait_for_timeout(400)
            except Exception:
                pass
            return True, f"shortcutClick: 已打开面板并点击快捷项（{s[:100]}）"
        except Exception as e:
            last_err = e
            continue

    ok_b, detail_b = _date_range_shortcut_click_builtin_ovui(page, sh_to)
    if ok_b:
        try:
            page.wait_for_timeout(400)
        except Exception:
            pass
        return True, str(detail_b)
    return False, f"点击快捷项失败: {detail_b or last_err}"


def _auxo_try_click_day_cell(panel: Any, d: date) -> bool:
    """在单个 auxo 月历面板内点击「指定日」：优先 td[title=YYYY-MM-DD]，再按可见格文案精确匹配日号。"""
    title = d.strftime("%Y-%m-%d")
    for p in (
        f"td.auxo-picker-cell-in-view[title='{title}']",
        f"td[title='{title}']",
    ):
        try:
            loc = panel.locator(p)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=8000)
                return True
        except Exception:
            continue
    want = str(d.day)
    try:
        cells = panel.locator("td.auxo-picker-cell-in-view")
        n = min(cells.count(), 42)
        for i in range(n):
            c = cells.nth(i)
            try:
                cls = c.get_attribute("class") or ""
                if "disabled" in cls:
                    continue
                tattr = (c.get_attribute("title") or "").strip()
                if tattr and _parse_title_date(tattr) == d:
                    c.click(timeout=8000)
                    return True
                inner = c.locator("div").first
                txt = (
                    inner.inner_text(timeout=800).strip().split("\n")[0].strip()
                    if inner.count() > 0
                    else c.inner_text(timeout=800).strip().split("\n")[0].strip()
                )
                if txt == want:
                    c.click(timeout=8000)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _auxo_click_prev_month(panel: Any) -> bool:
    for s in (
        ".auxo-picker-header-prev-btn",
        "button.auxo-picker-header-prev-btn",
        ".auxo-picker-prev-icon",
        ".auxo-picker-header .auxo-picker-prev-icon",
    ):
        try:
            b = panel.locator(s).first
            if b.count() > 0 and b.is_visible():
                b.click(timeout=4000)
                return True
        except Exception:
            continue
    return False


def _auxo_click_next_month(panel: Any) -> bool:
    for s in (
        ".auxo-picker-header-next-btn",
        "button.auxo-picker-header-next-btn",
        ".auxo-picker-next-icon",
        ".auxo-picker-header .auxo-picker-next-icon",
    ):
        try:
            b = panel.locator(s).first
            if b.count() > 0 and b.is_visible():
                b.click(timeout=4000)
                return True
        except Exception:
            continue
    return False


def _auxo_first_listed_day_in_panel(panel: Any) -> Optional[date]:
    try:
        cells = panel.locator("td.auxo-picker-cell-in-view[title]")
        if cells.count() == 0:
            cells = panel.locator("td[title]")
        if cells.count() == 0:
            return None
        for i in range(min(cells.count(), 42)):
            t = cells.nth(i).get_attribute("title")
            pd = _parse_title_date(t or "")
            if pd:
                return pd
    except Exception:
        pass
    return None


# 资金明细日期：历史模板里的超长链（与 doc 旧版一致），作降级候选
_AUXO_FUND_DETAIL_LEGACY_LONG_SELECTOR = (
    "#rc-tabs-0-panel-FUND_DETAIL_BILL > div > div.auxo-pro-table.custom-style-gray.auxo-pro-table-combined "
    "> div.auxo-pro-table-search.auxo-pro-table-search-query-filter > form > div > div > div:nth-child(1) "
    "> div > div > div > div > div > div > div > span > div.auxo-picker.auxo-picker-range"
)


def _auxo_fund_detail_calendar_container_chain(primary: str) -> list[str]:
    """
    资金明细等页：模板里常用超长 nth-child 链定位 auxo-picker-range，店铺/版本差异易失效。
    在保留主选择器的前提下追加较短链，便于 wait_for/点击命中。
    """
    p = (primary or "").strip()
    if not p:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def add(s: str) -> None:
        t = (s or "").strip()
        if not t or t in seen:
            return
        seen.add(t)
        out.append(t)

    add(p)
    u = p.upper()
    if "AUXO-PICKER-RANGE" not in u:
        return out
    if "FUND_DETAIL_BILL" in u or "FUND_DETAIL" in u:
        add(_AUXO_FUND_DETAIL_LEGACY_LONG_SELECTOR)
        # 比「全路径 nth」稳：先锁面板 + form，再用 class；避免依赖 div[2]/div[1] 等易变层级
        add("#rc-tabs-0-panel-FUND_DETAIL_BILL form .auxo-picker.auxo-picker-range")
        add("[id*='panel-FUND_DETAIL_BILL'] form .auxo-picker.auxo-picker-range")
        add("#rc-tabs-0-panel-FUND_DETAIL_BILL div.auxo-picker.auxo-picker-range")
        add("[id*='panel-FUND_DETAIL_BILL'] div.auxo-picker.auxo-picker-range")
        add("[id*='panel-FUND_DETAIL'] div.auxo-picker.auxo-picker-range")
        add(
            "xpath=//*[@id='rc-tabs-0-panel-FUND_DETAIL_BILL']"
            "//*[contains(@class,'auxo-picker-range')]"
        )
        add(
            "xpath=//*[contains(@id,'panel-FUND_DETAIL_BILL')]"
            "//*[contains(@class,'auxo-picker-range')]"
        )
        add("div.auxo-pro-table-search-query-filter div.auxo-picker.auxo-picker-range")
        add("div.auxo-pro-table-search div.auxo-picker.auxo-picker-range")
        add("form div.auxo-picker.auxo-picker-range")
    return out


def _auxo_try_open_range_container_once(
    page: Any,
    container_sel: str,
    *,
    budget: int,
) -> Tuple[bool, str, Optional[str]]:
    """
    按 _auxo_fund_detail_calendar_container_chain 依次尝试点开 auxo 范围日期。
    返回 (是否成功, 实际点中的选择器, 失败说明)。
    """
    cs = (container_sel or "").strip()
    if not cs:
        return False, "", "缺少 container_sel"
    sel_chain = _auxo_fund_detail_calendar_container_chain(cs)
    last_detail: Optional[str] = None
    opened_cs = cs
    _auxo_prep_page_before_range_pick(page, cs)
    per_sel_budget = max(12000, min(int(budget), 20000))
    for try_sel in sel_chain:
        try:
            c = page.locator(try_sel).first
            c.wait_for(state="attached", timeout=per_sel_budget)
            try:
                c.scroll_into_view_if_needed(timeout=min(8000, per_sel_budget))
            except Exception:
                pass
            try:
                page.wait_for_timeout(350)
            except Exception:
                pass
            c.wait_for(state="visible", timeout=per_sel_budget)
            c.click(timeout=10000)
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass
            opened_cs = try_sel
            return True, opened_cs, None
        except Exception as e:
            last_detail = str(e)
            continue
    return False, cs, last_detail or "日期容器选择器均未命中"


def _auxo_prep_page_before_range_pick(page: Any, container_sel: str) -> None:
    """资金明细 Tab 内：先等面板挂上 DOM 并滚入视口，再去找深层日期框，减少「节点未渲染完就超时」。"""
    if "FUND_DETAIL_BILL" not in (container_sel or "").upper():
        return
    stubs = (
        "#rc-tabs-0-panel-FUND_DETAIL_BILL",
        "[id*='panel-FUND_DETAIL_BILL']",
        "[id*='panel-FUND_DETAIL']",
    )
    for st in stubs:
        try:
            loc = page.locator(st).first
            loc.wait_for(state="attached", timeout=15000)
            loc.scroll_into_view_if_needed(timeout=8000)
            try:
                page.wait_for_timeout(600)
            except Exception:
                pass
            return
        except Exception:
            continue


def _auxo_ensure_click_day_in_panel(page: Any, panel: Any, d: date) -> bool:
    """翻月到含目标日的月份，再点击该日格子。"""
    for _ in range(28):
        if _auxo_try_click_day_cell(panel, d):
            return True
        cur = _auxo_first_listed_day_in_panel(panel)
        if cur:
            if (d.year, d.month) < (cur.year, cur.month):
                if not _auxo_click_prev_month(panel):
                    return False
            elif (d.year, d.month) > (cur.year, cur.month):
                if not _auxo_click_next_month(panel):
                    return False
            else:
                if not _auxo_click_prev_month(panel):
                    _auxo_click_next_month(panel)
        else:
            if not _auxo_click_prev_month(panel):
                return False
        try:
            page.wait_for_timeout(280)
        except Exception:
            pass
    return False


# 仅 doc/scrape-template-jinritemai-v1.json：auxoCalendarPick 日期容器点不到时经首页再回到当前页
_AUXO_CALENDAR_PICK_RETRY_HUB_URL = "https://fxg.jinritemai.com/ffa/mshop/homepage/index"
# 资金账单 / 资金流水明细（选交易时间）页：异常恢复时优先回到该 SPA 路径
_FXG_FUND_DETAIL_BILL_URL = "https://fxg.jinritemai.com/ffa/fxg-bill/fund-detail-bill"


def _auxo_calendar_pick_is_jinritemai_v1_template(template_abs: str) -> bool:
    t = (template_abs or "").replace("\\", "/").strip().lower()
    return t.endswith("/doc/scrape-template-jinritemai-v1.json") or t.endswith(
        "doc/scrape-template-jinritemai-v1.json"
    )


def _auxo_calendar_pick_fund_detail_return_url(current_url: str) -> str:
    """
    选日期步骤若锚在 FUND_DETAIL_BILL：迂回后应回到 fund-detail-bill。
    若当前 URL 已是该路径（可带 query），则保留；否则用固定入口 URL。
    """
    c = (current_url or "").strip()
    if "fund-detail-bill" in c.lower():
        return c
    return _FXG_FUND_DETAIL_BILL_URL


def _auxo_calendar_pick_retry_via_home(
    page: Any, *, container_sel: str = ""
) -> Optional[str]:
    """
    抖店首页 → 再回到资金明细/流水页（或原 URL）。
    当 target.selector 含 FUND_DETAIL_BILL 时，第二跳优先 fund-detail-bill 固定地址（见模板该页 url）。
    失败返回错误文案；成功返回 None。
    非上述场景且无法取得 URL 或已在首页：退回 page.reload。
    """
    hub = _AUXO_CALENDAR_PICK_RETRY_HUB_URL.strip()
    fund_panel = "FUND_DETAIL_BILL" in (container_sel or "").upper()
    cur = ""
    try:
        cur = (page.url or "").strip()
    except Exception:
        cur = ""
    ret = cur
    if fund_panel:
        ret = _auxo_calendar_pick_fund_detail_return_url(cur)
    try:
        on_hub = bool(cur) and cur.rstrip("/").lower() == hub.rstrip("/").lower()
        if not ret or on_hub:
            if fund_panel:
                page.goto(hub, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(1200)
                page.goto(_FXG_FUND_DETAIL_BILL_URL, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(2200)
                return None
            page.reload(wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2200)
            return None
        page.goto(hub, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(1200)
        page.goto(ret, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2200)
        return None
    except Exception as e:
        return str(e)


def _apply_auxo_panel_calendar_pick(
    page: Any,
    container_sel: str,
    target: date,
    container_timeout_ms: int,
    panel_sel: str,
    *,
    use_home_roundtrip: bool = False,
) -> tuple:
    """
    打开 auxo 范围日期 → 在挂出的 panel 里按「昨天」的年月点到对应 td（依赖 title 或格内日号），
    起止各点一次（同一张历或左右双 panel）。
    日期容器多次点不到时：若 use_home_roundtrip 为真则经抖店首页再回到目标页
    （selector 含 FUND_DETAIL_BILL 时第二跳为 fund-detail-bill）；否则 page.reload。
    若已点开容器但日历面板未出现、找不到面板或点选日期失败：在 use_home_roundtrip 为真时
    同样经首页 → 资金账单页再重新点开容器并重试（最多 3 轮）。
    """
    budget = max(15000, int(container_timeout_ms))
    cs = (container_sel or "").strip()
    ps = (panel_sel or "").strip() or "div.auxo-picker-panel-container"
    if not cs:
        return False, "auxoCalendarPick 需要 target.selector（点开范围选择器）"

    max_container_refreshes = 2
    last_container_err_detail = ""
    picked = False
    opened_cs = cs
    for refresh_i in range(max_container_refreshes + 1):
        ok_open, opened_cs, err_d = _auxo_try_open_range_container_once(page, cs, budget=budget)
        if ok_open:
            picked = True
            break
        last_container_err_detail = err_d or ""
        if refresh_i < max_container_refreshes:
            if use_home_roundtrip:
                err_nav = _auxo_calendar_pick_retry_via_home(page, container_sel=cs)
                if err_nav:
                    return False, (
                        f"auxoCalendarPick: 找不到日期容器已尝试经首页迂回重试，但失败: {err_nav}"
                    )
            else:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(2200)
                except Exception as re:
                    return False, f"auxoCalendarPick: 找不到日期容器已刷新重试，但刷新失败: {re}"
            continue
        return False, f"auxoCalendarPick: 点击日期容器失败: {last_container_err_detail}"

    if not picked:
        return False, f"auxoCalendarPick: 点击日期容器失败: {last_container_err_detail}"

    max_panel_roundtrips = 3
    last_soft_err = ""
    picked_days_ok = False
    for full_i in range(max_panel_roundtrips):
        if full_i > 0:
            if not use_home_roundtrip:
                return False, f"auxoCalendarPick: {last_soft_err}"
            err_nav = _auxo_calendar_pick_retry_via_home(page, container_sel=cs)
            if err_nav:
                return False, (
                    f"auxoCalendarPick: 选日失败且经首页迂回仍异常: {err_nav}；前因: {last_soft_err}"
                )
            ok_re, opened_cs, err_re = _auxo_try_open_range_container_once(page, cs, budget=budget)
            if not ok_re:
                return False, f"auxoCalendarPick: 经首页迂回后仍无法点开日期容器: {err_re}"

        try:
            page.locator(
                "div.auxo-picker-dropdown, div.sp-picker-range-body, div.auxo-picker-panel-container"
            ).first.wait_for(state="visible", timeout=min(budget, 25000))
        except Exception as e:
            last_soft_err = f"未等到日历下拉/面板: {e}"
            if full_i < max_panel_roundtrips - 1 and use_home_roundtrip:
                continue
            return False, f"auxoCalendarPick: {last_soft_err}"

        try:
            panels = page.locator(ps)
            n = panels.count()
            if n <= 0 and ps != "div.auxo-picker-dropdown div.auxo-picker-panel-container":
                panels = page.locator("div.auxo-picker-dropdown div.auxo-picker-panel-container")
                n = panels.count()
            if n <= 0:
                panels = page.locator("div.auxo-picker-panel-container")
                n = panels.count()
            if n <= 0:
                last_soft_err = f"未找到面板 {ps!r}"
                if full_i < max_panel_roundtrips - 1 and use_home_roundtrip:
                    continue
                return False, f"auxoCalendarPick: {last_soft_err}"

            ok_block = False
            if n >= 2:
                if _auxo_ensure_click_day_in_panel(page, panels.nth(0), target):
                    page.wait_for_timeout(450)
                    if _auxo_ensure_click_day_in_panel(page, panels.nth(1), target):
                        ok_block = True
                    else:
                        last_soft_err = "结束日在右侧面板点击失败"
                else:
                    last_soft_err = "起始日在左侧面板点击失败"
            else:
                if _auxo_ensure_click_day_in_panel(page, panels.first, target):
                    page.wait_for_timeout(450)
                    if _auxo_ensure_click_day_in_panel(page, panels.first, target):
                        ok_block = True
                    else:
                        try:
                            c2 = page.locator(opened_cs).first
                            c2.click(timeout=8000)
                            page.wait_for_timeout(450)
                            page.locator(
                                "div.auxo-picker-dropdown, div.sp-picker-range-body, div.auxo-picker-panel-container"
                            ).first.wait_for(state="visible", timeout=15000)
                            panels = page.locator(ps)
                        except Exception:
                            pass
                        if _auxo_ensure_click_day_in_panel(page, panels.first, target):
                            ok_block = True
                        else:
                            last_soft_err = "结束日（同面板需再开一次范围框）点击失败"
                else:
                    last_soft_err = "起始日点击失败"

            if ok_block:
                picked_days_ok = True
                break
            if full_i < max_panel_roundtrips - 1 and use_home_roundtrip:
                continue
            return False, f"auxoCalendarPick: {last_soft_err}"
        except Exception as e:
            last_soft_err = f"点选日期异常: {e}"
            if full_i < max_panel_roundtrips - 1 and use_home_roundtrip:
                continue
            return False, f"auxoCalendarPick: {last_soft_err}"

    if not picked_days_ok:
        return False, f"auxoCalendarPick: 选日重试耗尽: {last_soft_err or 'unknown'}"

    try:
        page.wait_for_timeout(300)
        _confirm_date_panel(page)
        page.wait_for_timeout(200)
    except Exception:
        pass
    return True, f"auxoCalendarPick: 已点选起止均为 {target.strftime('%Y-%m-%d')}"


def _apply_dual_input_date_range(
    page: Any,
    start_input_sel: str,
    end_input_sel: str,
    day: str,
    container_sel: str,
    container_timeout_ms: int,
) -> tuple:
    """
    账单等页：范围选择器拆成两个可见 input，起止都填同一「昨天」日期（YYYY-MM-DD）。
    可选先点 container_sel 聚焦范围框；结束框若带 auxo-picker-input-active 仅在聚焦后匹配，
    失败则在同一 auxo-picker-range 内取第二个 .auxo-picker-input input。
    """
    budget = max(15000, int(container_timeout_ms))
    cs = (container_sel or "").strip()
    s1 = (start_input_sel or "").strip()
    s2 = (end_input_sel or "").strip()
    if not s1 or not s2:
        return False, "dualInputFill 需在 target 中配置 startInputSelector 与 endInputSelector"

    if cs:
        try:
            c = page.locator(cs).first
            c.wait_for(state="visible", timeout=budget)
            c.click(timeout=10000)
            page.wait_for_timeout(400)
        except Exception as e:
            return False, f"dualInputFill: 点击日期容器失败: {e}"

    try:
        el1 = page.locator(s1).first
        el1.wait_for(state="visible", timeout=budget)
        el1.click(timeout=8000)
        page.wait_for_timeout(150)
        if not _fill_one_input(el1, day):
            return False, f"dualInputFill: 写入起始日期失败: {day}"
    except Exception as e:
        return False, f"dualInputFill: 起始 input 不可用: {e}"

    filled_end = False
    try:
        page.keyboard.press("Tab")
        page.wait_for_timeout(350)
        el2 = page.locator(s2).first
        el2.wait_for(state="visible", timeout=8000)
        el2.click(timeout=8000)
        page.wait_for_timeout(150)
        filled_end = _fill_one_input(el2, day)
    except Exception:
        filled_end = False

    if not filled_end:
        try:
            rng = page.locator(s1).locator(
                "xpath=ancestor::div[contains(@class,'auxo-picker-range')][1]"
            )
            if rng.count() > 0:
                el_alt = rng.locator("div.auxo-picker-input input").nth(1)
                if el_alt.count() == 0:
                    el_alt = rng.locator("input").nth(1)
                if el_alt.count() > 0:
                    el_alt.click(timeout=8000)
                    page.wait_for_timeout(150)
                    filled_end = _fill_one_input(el_alt, day)
        except Exception:
            filled_end = False

    if not filled_end:
        return False, "dualInputFill: 写入结束日期失败（可检查 endInputSelector 或 range 内第二个 input）"

    try:
        page.keyboard.press("Enter")
        page.wait_for_timeout(350)
        _confirm_date_panel(page)
        page.wait_for_timeout(200)
    except Exception:
        pass
    return True, f"dualInputFill: 起止均为 {day}"


def _readonly_range_yesterday_day_xpaths(dd: str, pick_first: bool) -> List[str]:
    """
    起止都是「昨天」同一日号 dd；双月历时第一次点第一个匹配格（多为开始侧），第二次点最后一个匹配格（多为结束侧）。
    单月只有一个 dd 格时 [1] 与 [last()] 为同一节点，相当于同格点两下。
    """
    idx = "[1]" if pick_first else "[last()]"
    return [
        f"xpath=(//*[contains(@class,'calendar') or contains(@class,'Calendar') or contains(@class,'picker') or contains(@class,'Picker')]//*[normalize-space(text())='{dd}' and not(contains(@class,'disabled'))]){idx}",
        f"xpath=(//td[not(contains(@class,'disabled'))]//*[normalize-space(text())='{dd}']){idx}",
        f"xpath=(//*[normalize-space(text())='{dd}' and not(contains(@class,'disabled'))]){idx}",
    ]


def _merge_open_selectors(primary: str, alternate: Optional[list]) -> list:
    """主 selector + target.alternateOpenSelector，去重保序。"""
    out: list = []
    seen = set()
    for s in [primary] + list(alternate or []):
        sx = (s or "").strip()
        if not sx or sx in seen:
            continue
        seen.add(sx)
        out.append(sx)
    return out


def _min_disabled_date_from_picker(page: Any, panel_root_selector: str = "") -> Optional[date]:
    """
    在当前可见的日期浮层内，解析「灰死/disabled」格子的 title 日期，返回最小的那一天（完整 YYYY-MM-DD）。
    """
    pr = (panel_root_selector or "").strip()
    min_s = page.evaluate(
        """(panelSel) => {
            function vis(el) {
                if (!el) return false;
                const st = window.getComputedStyle(el);
                return st && st.display !== "none" && st.visibility !== "hidden" && el.offsetParent !== null;
            }
            let roots = [];
            if (panelSel) {
                try {
                    const n = document.querySelector(panelSel);
                    if (n && vis(n)) roots = [n];
                } catch (e) {}
            }
            if (!roots.length) {
                document.querySelectorAll(
                    'div[class*="picker-dropdown"], div[class*="PickerDropdown"], div[class*="ant-picker-dropdown"], div[class*="Ppicker"]'
                ).forEach((n) => {
                    if (vis(n)) roots.push(n);
                });
            }
            let minS = null;
            for (const root of roots) {
                const tds = root.querySelectorAll("td");
                for (const td of tds) {
                    const cls = td.className || "";
                    const dis =
                        td.getAttribute("aria-disabled") === "true" ||
                        /cell-disabled|picker-cell-disabled|PickerCellDisabled|disabled/i.test(cls);
                    if (!dis) continue;
                    let t = td.getAttribute("title") || "";
                    if (!t) {
                        const inner = td.querySelector("[title]");
                        if (inner) t = inner.getAttribute("title") || "";
                    }
                    const m = t.match(/(\\d{4}-\\d{2}-\\d{2})/);
                    if (!m) continue;
                    const s = m[1];
                    if (!minS || s < minS) minS = s;
                }
            }
            return minS;
        }""",
        pr,
    )
    if not min_s or not isinstance(min_s, str):
        return None
    try:
        return date.fromisoformat(min_s[:10])
    except ValueError:
        return None


def _click_calendar_cell_for_date(page: Any, target: date, pick_first: bool) -> Tuple[bool, str]:
    """优先用 td[title=YYYY-MM-DD] 点 in-view 非 disabled 格，失败则回退按日号 XPath。"""
    iso = target.isoformat()
    dd = str(int(target.day))
    cands = [
        f"td.ant-picker-cell-in-view[title='{iso}']",
        f"td[title='{iso}']",
        f"xpath=//td[contains(@class,'in-view') and not(contains(@class,'disabled'))][@title='{iso}']",
    ]
    last_err = ""
    for sel in cands:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.wait_for(state="visible", timeout=5000)
            loc.click(timeout=5000)
            page.wait_for_timeout(220)
            return True, sel
        except Exception as e:
            last_err = str(e)
            continue
    for ps in _readonly_range_yesterday_day_xpaths(dd, pick_first=pick_first):
        try:
            loc = page.locator(ps).first
            loc.wait_for(state="visible", timeout=6000)
            loc.click(timeout=5000)
            page.wait_for_timeout(220)
            return True, ps
        except Exception as e:
            last_err = str(e)
            continue
    return False, last_err or "无可用定位"


def _apply_readonly_range_min_disabled_minus2(
    page: Any,
    container_sel: str,
    day: str,
    container_timeout_ms: int,
    alternate_open_selectors: Optional[list],
    calendar_panel_selector: str = "",
    *,
    fallback_to_yesterday: bool = True,
    post_calendar_open_wait_ms: int = 500,
) -> tuple:
    """
    打开日历 -> 在浮层内找最小「灰死」日期 G -> 目标日 = G - 2 天 -> 连点两次该日 -> 确认。
    解析失败且 fallback_to_yesterday 时回退为 readonlyRangePickYesterday。
    """
    openers = _merge_open_selectors(container_sel, alternate_open_selectors)
    if not openers:
        return False, "readonlyRangeMinDisabledMinus2 需配置 target.selector"

    budget = max(10000, int(container_timeout_ms or 12000))
    cs = ""
    last_open_err = ""
    for cand in openers:
        try:
            c = page.locator(cand).first
            c.wait_for(state="visible", timeout=budget)
            c.click(timeout=9000)
            page.wait_for_timeout(260)
            cs = cand
            break
        except Exception as e:
            last_open_err = str(e)
            continue
    if not cs:
        return False, f"readonlyRangeMinDisabledMinus2: 打开日期面板失败（已试 {len(openers)} 个）: {last_open_err}"

    try:
        page.wait_for_timeout(max(0, min(int(post_calendar_open_wait_ms or 500), 10000)))
    except Exception:
        pass

    min_g = _min_disabled_date_from_picker(page, calendar_panel_selector)
    if min_g is None:
        if fallback_to_yesterday:
            return _apply_readonly_range_pick_yesterday(
                page, container_sel, day, container_timeout_ms, alternate_open_selectors
            )
        return False, "readonlyRangeMinDisabledMinus2: 未解析到任何 disabled 日期（无 title YYYY-MM-DD）"

    try:
        target_d = min_g - timedelta(days=2)
    except Exception as e:
        return False, f"readonlyRangeMinDisabledMinus2: 日期计算失败: {e}"

    for i in range(2):
        ok, detail = _click_calendar_cell_for_date(page, target_d, pick_first=(i == 0))
        if not ok:
            if fallback_to_yesterday:
                return _apply_readonly_range_pick_yesterday(
                    page, container_sel, day, container_timeout_ms, alternate_open_selectors
                )
            return False, f"readonlyRangeMinDisabledMinus2: 第{i+1}次点目标日 {target_d} 失败: {detail}"
        page.wait_for_timeout(520 if i == 0 else 280)
        if i == 0:
            try:
                page.locator("button:has-text('确认'), span:has-text('确认')").first.wait_for(
                    state="visible", timeout=800
                )
            except Exception:
                try:
                    page.locator(cs).first.click(timeout=5000)
                    page.wait_for_timeout(280)
                except Exception:
                    pass
            page.wait_for_timeout(900)

    page.wait_for_timeout(1000)
    try:
        if not _try_readonly_range_portal_footer_confirm(page):
            _confirm_date_panel(page)
        page.wait_for_timeout(180)
    except Exception:
        pass
    return (
        True,
        f"readonlyRangeMinDisabledMinus2: min灰={min_g.isoformat()} -> 目标={target_d.isoformat()}（起止同日）",
    )


def _apply_readonly_range_pick_yesterday(
    page: Any,
    container_sel: str,
    day: str,
    container_timeout_ms: int,
    alternate_open_selectors: Optional[list] = None,
) -> tuple:
    """
    只读范围控件：先点击打开日历（主 selector，失败则试 alternateOpenSelector）->
    第一下点「昨天」日号、第二下再点「昨天」日号 -> 点确认。
    """
    openers = _merge_open_selectors(container_sel, alternate_open_selectors)
    if not openers:
        return False, "readonlyRangePickYesterday 需配置 target.selector"
    try:
        d = date.fromisoformat((day or "").strip()[:10])
    except ValueError:
        d = _yesterday_date()
    dd = str(int(d.day))
    budget = max(10000, int(container_timeout_ms or 12000))
    cs = ""
    last_open_err = ""
    for cand in openers:
        try:
            c = page.locator(cand).first
            c.wait_for(state="visible", timeout=budget)
            c.click(timeout=9000)
            page.wait_for_timeout(260)
            cs = cand
            last_open_err = ""
            break
        except Exception as e:
            last_open_err = str(e)
            continue
    if not cs:
        return False, f"readonlyRangePickYesterday: 打开日期面板失败（已试 {len(openers)} 个）: {last_open_err}"

    for i in range(2):
        pickers = _readonly_range_yesterday_day_xpaths(dd, pick_first=(i == 0))
        ok = False
        last_err = ""
        for ps in pickers:
            try:
                loc = page.locator(ps).first
                loc.wait_for(state="visible", timeout=6000)
                loc.click(timeout=5000)
                # 第一次点日后多留一点时间，避免起止面板未切换完就第二次点击导致日期未更新
                page.wait_for_timeout(520 if i == 0 else 280)
                ok = True
                break
            except Exception as e:
                last_err = str(e)
                continue
        if not ok:
            return False, f"readonlyRangePickYesterday: 第{i+1}次点昨日失败: {last_err}"
        if i == 0:
            # 首点后若面板收起，第二次前尝试重新打开
            try:
                page.locator("button:has-text('确认'), span:has-text('确认'), text=确认").first.wait_for(
                    state="visible", timeout=800
                )
            except Exception:
                try:
                    c2 = page.locator(cs).first
                    c2.click(timeout=5000)
                    page.wait_for_timeout(280)
                except Exception:
                    pass
            # 两次点「同一日」之间再给一截间隔，便于范围选择器完成起止切换
            page.wait_for_timeout(900)

    # 两次点日后再停 1s，等 footer/确定 渲染稳定再点确认
    page.wait_for_timeout(1000)

    try:
        if not _try_readonly_range_portal_footer_confirm(page):
            _confirm_date_panel(page)
        page.wait_for_timeout(180)
    except Exception:
        pass
    return True, f"readonlyRangePickYesterday: 起止均为 {d.strftime('%Y-%m-%d')}"


def _apply_previous_day_range(
    page: Any,
    selector: str,
    day: str,
    *,
    container_timeout_ms: int = 60000,
    shortcut_selector: str = "",
    alternate_shortcut_selectors: Optional[list] = None,
    date_range_strategy: str = "",
    start_input_selector: str = "",
    end_input_selector: str = "",
    calendar_panel_selector: str = "",
    alternate_open_selectors: Optional[list] = None,
    fallback_min_disabled_to_yesterday: bool = True,
    post_calendar_open_wait_ms: int = 500,
    trial_template_abs: str = "",
    auxo_home_roundtrip: bool = False,
) -> tuple:
    """
    默认：点击容器后在 input 写入「昨天」。
    若 dateRangeStrategy=shortcutClick（或配置了 shortcutSelector 且未强制 fill）：只两次点击，不写 input。
    若 dateRangeStrategy=dualInputFill：使用 startInputSelector / endInputSelector 分别写入（可选先点 selector 容器）。
    若 dateRangeStrategy=auxoCalendarPick：在 auxo 月历面板内翻到目标年月并点击「昨天」对应格（起止各一次）；容器/面板异常时的首页迂回见 _apply_auxo_panel_calendar_pick；auxo_home_roundtrip 为真或 trial_template_abs 为 jinritemai-v1 等时启用。
    若 dateRangeStrategy=readonlyRangePickYesterday：只读范围控件按日号点两次昨天并确认；可选 target.alternateOpenSelector（字符串或数组）打开日历失败时依次再试。
    若 dateRangeStrategy=readonlyRangeMinDisabledMinus2：解析浮层内最小灰死日 G，目标日=G-2 天，连点两次后确认；可选 calendarPanelSelector；可选 minDisabledFallbackToYesterday（默认 true）解析失败则回退 readonlyRangePickYesterday；可选 postCalendarOpenWaitMs。
    """
    ss = (shortcut_selector or "").strip()
    strat = (date_range_strategy or "").strip().lower()
    si = (start_input_selector or "").strip()
    ei = (end_input_selector or "").strip()
    cps = (calendar_panel_selector or "").strip()

    alt_ss = [str(x).strip() for x in (alternate_shortcut_selectors or []) if str(x or "").strip()]
    _try_dismiss_promotion_modal(page)
    if strat != "fill" and (strat == "shortcutclick" or ss or alt_ss):
        primary = ss
        rest = list(alt_ss)
        if not primary and rest:
            primary = rest.pop(0)
        if not primary:
            return False, "shortcutClick 策略需配置 shortcutSelector 或 alternateShortcutSelector"
        return _date_range_shortcut_click(
            page,
            selector,
            primary,
            container_timeout_ms,
            alternate_shortcut_selectors=rest,
        )

    if strat == "auxocalendarpick":
        try:
            target_d = date.fromisoformat(day.strip()[:10])
        except ValueError:
            target_d = _yesterday_date()
        return _apply_auxo_panel_calendar_pick(
            page,
            selector,
            target_d,
            container_timeout_ms,
            cps,
            use_home_roundtrip=bool(auxo_home_roundtrip)
            or _auxo_calendar_pick_is_jinritemai_v1_template(trial_template_abs),
        )

    if strat == "readonlyrangepickyesterday":
        return _apply_readonly_range_pick_yesterday(
            page, selector, day, container_timeout_ms, alternate_open_selectors
        )

    if strat in ("readonlyrangemindisabledminus2", "readonlyrangemingrayminus2"):
        return _apply_readonly_range_min_disabled_minus2(
            page,
            selector,
            day,
            container_timeout_ms,
            alternate_open_selectors,
            calendar_panel_selector=cps,
            fallback_to_yesterday=fallback_min_disabled_to_yesterday,
            post_calendar_open_wait_ms=post_calendar_open_wait_ms,
        )

    if strat == "dualinputfill" or (si and ei):
        return _apply_dual_input_date_range(
            page, si, ei, day, selector, container_timeout_ms
        )

    candidates = _date_range_container_candidates(selector)
    if not candidates:
        return False, "dateRange 未配置 target.selector"

    first_budget = max(15000, int(container_timeout_ms))
    retry_budget = max(12000, min(25000, int(container_timeout_ms) // 2 + 5000))
    last_err = ""
    root = None
    used_sel = ""

    for i, cand in enumerate(candidates):
        budget = first_budget if i == 0 else retry_budget
        try:
            loc = page.locator(cand).first
            loc.wait_for(state="visible", timeout=budget)
            loc.click(timeout=10000)
            root = loc
            used_sel = cand
            break
        except Exception as e:
            last_err = str(e)

    if root is None:
        return False, f"点击日期容器失败（已试 {len(candidates)} 个选择器）: {last_err}"

    try:
        page.wait_for_timeout(1200)
    except Exception:
        pass

    last = ""
    filled = 0

    # A) 容器内直接有的 input（少数页面）
    try:
        for i in range(min(root.locator("input").count(), 6)):
            el = root.locator("input").nth(i)
            if el.is_visible():
                if _fill_one_input(el, day):
                    filled += 1
        if filled >= 1:
            page.keyboard.press("Tab")
            page.wait_for_timeout(200)
            if filled == 1:
                try:
                    page.keyboard.type(day, delay=30)
                except Exception:
                    pass
            _confirm_date_panel(page)
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            return True, f"已在日期容器内写入 {filled} 处: {day}"
    except Exception as e:
        last = str(e)

    # B) 弹层挂在 body（千川 ovui + oc/auxo/ant）
    panel_input_selectors = [
        "div[class*='ovui-picker'] input",
        "div[class*='ovui-date'] input",
        "div[class*='OvuiPicker'] input",
        "div.oc-picker-dropdown input",
        "div[class*='picker-dropdown'] input",
        "div[class*='PickerDropdown'] input",
        "div.auxo-picker-dropdown input",
        "div.ant-picker-dropdown input",
        ".auxo-picker-input input",
        "div.auxo-picker-range input",
        ".oc-picker input",
        "[class*='oc-picker'] input",
    ]
    for csel in panel_input_selectors:
        try:
            loc = page.locator(csel)
            n = loc.count()
            if n <= 0:
                continue
            sub = 0
            for i in range(min(n, 6)):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                if _fill_one_input(el, day):
                    sub += 1
            if sub >= 1:
                page.keyboard.press("Tab")
                page.wait_for_timeout(200)
                _confirm_date_panel(page)
                page.keyboard.press("Enter")
                page.wait_for_timeout(300)
                return True, f"弹层 {csel} 写入 {sub} 个 input: {day}"
        except Exception as e:
            last = str(e)

    # C) 成本卡片区域内所有可见 input（兜底，避免 class 大改）
    try:
        card = page.locator(".oc-card.cost-container.mb-16").first
        if card.count() > 0:
            loc = card.locator("input")
            sub = 0
            for i in range(min(loc.count(), 8)):
                el = loc.nth(i)
                if el.is_visible():
                    if _fill_one_input(el, day):
                        sub += 1
            if sub >= 1:
                _confirm_date_panel(page)
                page.keyboard.press("Enter")
                page.wait_for_timeout(300)
                return True, f"成本卡片内兜底写入 {sub} 个 input: {day}"
    except Exception as e:
        last = str(e)

    return False, last or "未找到可写入的日期 input；请在 DevTools 确认弹层内 input 的 class 或改用接口抓数"


def _select_filter_selectors(step: dict, tgt: dict) -> list:
    out: list = []
    if isinstance(tgt, dict):
        s = str(tgt.get("selector") or "").strip()
        if s:
            out.append(s)
    alt = step.get("alternateSelectFilterSelector")
    if isinstance(alt, str) and alt.strip():
        out.append(alt.strip())
    elif isinstance(alt, list):
        for x in alt:
            sx = str(x or "").strip()
            if sx and sx not in out:
                out.append(sx)
    return out


def _select_filter_confirm_selectors_from_step(step: dict) -> list:
    """postSelectConfirmSelector + alternate + postSelectConfirmSelectors 列表，去重保序。"""
    out: list = []
    if not isinstance(step, dict):
        return out
    pri = str(step.get("postSelectConfirmSelector") or "").strip()
    if pri:
        out.append(pri)
    alt = step.get("alternatePostSelectConfirmSelector")
    if isinstance(alt, str) and alt.strip():
        sx = alt.strip()
        if sx not in out:
            out.append(sx)
    elif isinstance(alt, list):
        for x in alt:
            sx = str(x or "").strip()
            if sx and sx not in out:
                out.append(sx)
    raw_list = step.get("postSelectConfirmSelectors")
    if isinstance(raw_list, list):
        for x in raw_list:
            sx = str(x or "").strip()
            if sx and sx not in out:
                out.append(sx)
    return out


def _try_click_filter_portal_confirm(page: Any) -> bool:
    """筛选项 Portal 底部「确认」：选择器链失败时的兜底（beast 主按钮 / footer / role）。"""
    try:
        loc = page.locator(
            "div[class*='dropdown'] footer button[data-testid='beast-core-button']"
        ).filter(has_text=re.compile(r"确认"))
        for i in range(min(loc.count(), 6)):
            try:
                el = loc.nth(i)
                if el.is_visible(timeout=900):
                    el.click(timeout=5000)
                    page.wait_for_timeout(200)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    try:
        loc = page.locator("footer button[type='button']").filter(has_text=re.compile(r"^\s*确认\s*$"))
        fn = loc.count()
        for i in range(min(fn, 6)):
            try:
                el = loc.nth(fn - 1 - i)
                if el.is_visible(timeout=700):
                    el.click(timeout=5000)
                    page.wait_for_timeout(200)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    try:
        btn = page.get_by_role("button", name=re.compile(r"^\s*确认\s*$"))
        n = btn.count()
        for k in range(min(n, 12)):
            try:
                el = btn.nth(n - 1 - k)
                if el.is_visible(timeout=500):
                    el.click(timeout=5000)
                    page.wait_for_timeout(200)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _scroll_click_loc(page: Any, loc: Any, click_timeout_ms: int = 10000) -> None:
    """页面下方/被 sticky 遮挡时：先滚入视口，再点；失败则 force 点击。"""
    loc.scroll_into_view_if_needed(timeout=8000)
    page.wait_for_timeout(150)
    try:
        loc.click(timeout=click_timeout_ms)
    except Exception:
        loc.click(timeout=click_timeout_ms, force=True)


def _click_first_visible_role(page: Any, role: str, name: str, click_timeout_ms: int = 8000) -> bool:
    """同一文案可能有多处节点；优先点当前可见的（下拉层通常在视口内或需滚动）。"""
    loc = page.get_by_role(role, name=name)
    n = loc.count()
    for i in range(n):
        el = loc.nth(i)
        try:
            if el.is_visible():
                _scroll_click_loc(page, el, click_timeout_ms)
                return True
        except Exception:
            continue
    if n > 0:
        try:
            _scroll_click_loc(page, loc.last, click_timeout_ms)
            return True
        except Exception:
            pass
    return False


def _select_filter_labels_to_try(step: dict) -> list:
    """主 value + alternateSelectValues；抖店时间项常见「昨天」「昨日」二选一，脚本会都试。"""
    seen: list = []

    def add(s: str) -> None:
        t = (s or "").strip()
        if t and t not in seen:
            seen.append(t)

    add(str(step.get("value") or ""))
    alt = step.get("alternateSelectValues")
    if isinstance(alt, list):
        for x in alt:
            add(str(x or ""))
    elif isinstance(alt, str):
        add(alt)
    if any(x in ("昨天", "昨日") for x in seen):
        add("昨日")
        add("昨天")
    return seen


def _try_pick_select_label(page: Any, label: str, click_timeout_ms: int = 8000) -> bool:
    """Auxo/rc-select 选项常在 portal 的 listbox 内，且可见项文案可能是「昨日」而非「昨天」。"""
    # 1) 先只在「当前可见」的 listbox 里找（避免点到页面上其它同名文本）
    try:
        lbs = page.locator('[role="listbox"]')
        for i in range(lbs.count()):
            lb = lbs.nth(i)
            try:
                if not lb.is_visible():
                    continue
            except Exception:
                continue
            for role in ("option", "menuitem"):
                try:
                    opt = lb.get_by_role(role, name=label)
                    for j in range(opt.count()):
                        el = opt.nth(j)
                        if el.is_visible():
                            _scroll_click_loc(page, el, click_timeout_ms)
                            return True
                except Exception:
                    pass
            try:
                gt = lb.get_by_text(label, exact=True)
                for j in range(gt.count()):
                    el = gt.nth(j)
                    if el.is_visible():
                        _scroll_click_loc(page, el, click_timeout_ms)
                        return True
            except Exception:
                pass
    except Exception:
        pass

    # 1b) Ant Design rc-select：浮层根节点 id 常为 rc_select_N_list，option 可能在 listbox 子树或 .auxo-select-item 内
    try:
        pops = page.locator('[id$="_list"]')
        for i in range(pops.count()):
            root = pops.nth(i)
            try:
                if not root.is_visible():
                    continue
            except Exception:
                continue
            try:
                inner_lb = root.locator('[role="listbox"]').first
                if inner_lb.count() > 0:
                    try:
                        gt = inner_lb.get_by_text(label, exact=True)
                        for j in range(gt.count()):
                            el = gt.nth(j)
                            if el.is_visible():
                                _scroll_click_loc(page, el, click_timeout_ms)
                                return True
                    except Exception:
                        pass
                    for role in ("option", "menuitem"):
                        try:
                            opt = inner_lb.get_by_role(role, name=label)
                            for j in range(opt.count()):
                                el = opt.nth(j)
                                if el.is_visible():
                                    _scroll_click_loc(page, el, click_timeout_ms)
                                    return True
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                for cls in (
                    ".auxo-select-item-option-content",
                    ".auxo-select-item",
                    "[role='option']",
                ):
                    hit = root.locator(cls).filter(has_text=re.compile("^" + re.escape(label) + "$"))
                    for j in range(hit.count()):
                        el = hit.nth(j)
                        if el.is_visible():
                            _scroll_click_loc(page, el, click_timeout_ms)
                            return True
            except Exception:
                pass
            try:
                hit = root.get_by_text(label, exact=True)
                for j in range(hit.count()):
                    el = hit.nth(j)
                    if el.is_visible():
                        _scroll_click_loc(page, el, click_timeout_ms)
                        return True
            except Exception:
                pass
    except Exception:
        pass

    # 2) [role=option] 整节点文案精确匹配（部分实现不设 accessible name）
    try:
        pat = re.compile("^" + re.escape(label) + "$")
        opts = page.locator('[role="option"]').filter(has_text=pat)
        for i in range(opts.count()):
            el = opts.nth(i)
            if el.is_visible():
                _scroll_click_loc(page, el, click_timeout_ms)
                return True
    except Exception:
        pass

    for role in ("option", "menuitem"):
        if _click_first_visible_role(page, role, label, click_timeout_ms):
            return True

    try:
        gt = page.get_by_text(label, exact=True)
        for i in range(gt.count()):
            el = gt.nth(i)
            if el.is_visible():
                _scroll_click_loc(page, el, click_timeout_ms)
                return True
        if gt.count() > 0:
            _scroll_click_loc(page, gt.last, click_timeout_ms)
            return True
    except Exception:
        pass

    try:
        tl = page.locator(f"text={label}")
        for i in range(tl.count()):
            el = tl.nth(i)
            if el.is_visible():
                _scroll_click_loc(page, el, click_timeout_ms)
                return True
        if tl.count() > 0:
            _scroll_click_loc(page, tl.last, click_timeout_ms)
            return True
    except Exception:
        pass

    return False


# selectFilter：筛选项容器「等到可见」默认上限（单条 selector）；alternate 较多时避免每条误配都卡 20s
_SELECT_FILTER_VISIBLE_DEFAULT_MS = 3000


def _select_filter_value(
    page: Any,
    selectors: list,
    labels: list,
    container_visible_timeout_ms: int = _SELECT_FILTER_VISIBLE_DEFAULT_MS,
    *,
    confirm_selectors: Optional[list] = None,
    confirm_wait_visible_ms: int = 8000,
    confirm_skip_scroll: bool = True,
    option_click_timeout_ms: int = 12000,
) -> tuple:
    if not selectors:
        return False, "selectFilter 未配置 target.selector"
    labels = [str(x).strip() for x in (labels or []) if str(x).strip()]
    if not labels:
        return False, "selectFilter 未配置 value"
    last_err = ""
    summary = "、".join(labels)
    default_cap = _SELECT_FILTER_VISIBLE_DEFAULT_MS
    vw_box = max(1000, min(int(container_visible_timeout_ms or default_cap), 600000))
    cw = max(2000, min(int(confirm_wait_visible_ms or 8000), 120000))
    for container_sel in selectors:
        try:
            loc = page.locator(container_sel)
            # 当前 DOM 下 0 个匹配时不再阻塞 wait_for（否则每条 alternate 可能各等满 vw_box）
            try:
                if loc.count() == 0:
                    last_err = f"无匹配节点(跳过): {container_sel[:48]}…"
                    continue
            except Exception:
                pass
            box = loc.first
            box.wait_for(state="visible", timeout=vw_box)
            _scroll_click_loc(page, box, 12000)
            page.wait_for_timeout(550)
        except Exception as e:
            last_err = f"点击筛选项容器失败({container_sel[:48]}…): {e}"
            continue

        pick_to = max(4000, min(int(option_click_timeout_ms or 12000), 60000))
        for lab in labels:
            if _try_pick_select_label(page, lab, pick_to):
                if confirm_selectors:
                    page.wait_for_timeout(450)
                    ok_c, det_c = _click_selector_chain(
                        page,
                        confirm_selectors,
                        cw,
                        skip_scroll_into_view=confirm_skip_scroll,
                    )
                    if ok_c:
                        return True, f"已选择「{lab}」并已点确认（候选: {summary}）"
                    if _try_click_filter_portal_confirm(page):
                        return True, f"已选择「{lab}」并已点确认(兜底)（候选: {summary}）"
                    return False, f"已选中「{lab}」但点确认失败: {det_c}"
                return True, f"已选择「{lab}」（候选: {summary}）"

        last_err = f"下拉已打开但未命中选项，已尝试文案: {summary}"
        continue
    return False, last_err or f"未找到选项（{summary}）"


def _needs_post_goto_account_switch(pg: dict, pid: str) -> bool:
    """globalAccountLoop 内：抖店已用首页切店时，千川等需落地后再切一次。
    pages[].skipPostGotoAccountSwitch 为 true 时（如 aavid 直达后不再点账户列表）跳过。"""
    if bool((pg or {}).get("skipPostGotoAccountSwitch")):
        return False
    sw = pg.get("accountSwitcher") if isinstance(pg.get("accountSwitcher"), dict) else {}
    mode = str(sw.get("mode") or "").strip()
    if mode == "fxgShopModal":
        return False
    if mode in ("searchOverlay", "loginShopList"):
        return True
    return pid == "qianchuan_home_cost_roi"


def _parse_global_account_loop(tpl: dict, args: Any) -> Optional[dict]:
    """
    模板根 globalAccountLoop：每家店铺一轮——先 preSwitchUrl，再 anchor 上 accountSwitcher 切店（或 noop），
    然后按 pageIds 顺序做 interactions+fields。
    accounts 为空时可设 accountsFromCredentialCsv=true，从 accountCredentialCsv 按文件行顺序加载全部店铺名。
    """
    raw = tpl.get("globalAccountLoop")
    if not isinstance(raw, dict):
        return None
    cli = (getattr(args, "global_accounts", "") or "").strip()
    accs: Optional[list] = None
    ra = raw.get("accounts")
    ra_effective: list = ra if isinstance(ra, list) else []
    cfg_file = str(raw.get("accountsConfigFile") or "").strip()
    cfg_profile = str(raw.get("accountsProfile") or "").strip()
    if not ra_effective and cfg_file:
        try:
            p_cfg = Path(cfg_file)
            if not p_cfg.is_absolute():
                p_cfg = (PROJECT_ROOT / p_cfg).resolve()
            if p_cfg.is_file():
                with p_cfg.open("r", encoding="utf-8") as f:
                    cfg_obj = json.load(f)
                if isinstance(cfg_obj, dict):
                    if cfg_profile and isinstance(cfg_obj.get("profiles"), dict):
                        prof = cfg_obj.get("profiles") or {}
                        one = prof.get(cfg_profile)
                        if isinstance(one, list):
                            ra_effective = one
                    elif isinstance(cfg_obj.get("accounts"), list):
                        ra_effective = cfg_obj.get("accounts") or []
                elif isinstance(cfg_obj, list):
                    ra_effective = cfg_obj
        except Exception:
            ra_effective = []
    if cli:
        accs = [x.strip() for x in cli.split(",") if x.strip()]
    if accs is None:
        if isinstance(ra_effective, list):
            accs = []
            for x in ra_effective:
                if isinstance(x, dict):
                    n = str(x.get("name") or x.get("shopName") or "").strip()
                    if n:
                        accs.append(n)
                elif isinstance(x, str) and x.strip():
                    accs.append(x.strip())
    if not accs and bool(raw.get("accountsFromCredentialCsv")):
        m = _load_account_credential_map(tpl if isinstance(tpl, dict) else {})
        if isinstance(m, dict) and m:
            accs = [str(k).strip() for k in m.keys() if str(k).strip()]
    if not accs:
        return None
    pids = raw.get("pageIds")
    if not isinstance(pids, list):
        return None
    pids = [str(x).strip() for x in pids if str(x).strip()]
    if not pids:
        return None
    pre = str(raw.get("preSwitchUrl") or "").strip()
    if not pre:
        return None
    sw = raw.get("accountSwitcher")
    if not isinstance(sw, dict):
        sw = {}
    anchor = str(raw.get("anchorPageId") or "fxg_mshop_home").strip()
    qc_map, _qc_policy = _build_qianchuan_by_account_map(ra_effective if isinstance(ra_effective, list) else [], accs)
    out = {
        "accounts": accs,
        "pageIds": pids,
        "preSwitchUrl": pre,
        "accountSwitcher": sw,
        "anchorPageId": anchor,
    }
    if qc_map is not None:
        out["qianchuanByAccount"] = qc_map
    return out


def _task_part_page_ids(part: str) -> Optional[set]:
    """
    将任务分块标识（A/B/C/D）映射为 page ids，便于逐块调试。

    A: 抖店首页与切店后首页指标
    B: 资金账单 + 历史报表下载
    C: 售后单筛选与导出
    D: 千川成本卡
    """
    p = (part or "").strip().upper()
    mapping = {
        "A": {"fxg_mshop_home"},
        "B": {"fxg_aftersale_fund_detail_bill", "fxg_bill_history_report"},
        "C": {"fxg_aftersale_order_list_export"},
        "D": {"qianchuan_home_cost_roi"},
    }
    return mapping.get(p)


def _task_parts_page_ids(parts_raw: str) -> Optional[Tuple[set, list]]:
    """支持 --task-part 多选（逗号分隔），返回合并后的 page ids 与分块列表。"""
    raw = str(parts_raw or "").strip()
    if not raw:
        return None
    parts = [x.strip().upper() for x in raw.split(",") if x.strip()]
    if not parts:
        return None
    seen = set()
    norm_parts: list = []
    merged: set = set()
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        one = _task_part_page_ids(p)
        if one is None:
            return None
        norm_parts.append(p)
        merged.update(one)
    return merged, norm_parts


# 控制台多选恰好为「登录/切换 + 资金账单生成 + 历史报表下载」三模块（无罗盘/售后/千川等）时，多店之间插入冷却。
_FUNDBILL_ONLY_SHOP_COOLDOWN_PAGE_IDS = frozenset(
    {
        "fxg_login_switch",
        "fxg_aftersale_fund_detail_bill",
        "fxg_bill_history_report",
    }
)


def _page_ids_need_fundbill_only_shop_cooldown(page_id_allow: Optional[set]) -> bool:
    if page_id_allow is None:
        return False
    return frozenset(page_id_allow) == _FUNDBILL_ONLY_SHOP_COOLDOWN_PAGE_IDS


def _page_id_to_task_part(page_id: str) -> str:
    """将页面 id 归类为 A/B/C/D 环节，便于运行结束后汇总提醒缺失项。"""
    pid = str(page_id or "").strip()
    if pid in {"globalAccountLoop", "fxg_mshop_home"}:
        return "A"
    if pid in {"fxg_aftersale_fund_detail_bill", "fxg_bill_history_report"}:
        return "B"
    if pid in {"fxg_aftersale_order_list_export"}:
        return "C"
    if pid in {"qianchuan_home_cost_roi"}:
        return "D"
    return "其他"


def _print_missing_step_summary(rows: list) -> None:
    """
    从运行日志行中汇总失败步骤，按「店铺 + 环节」输出提醒，便于后续补齐。
    仅打印，不改 CSV/Excel 内容。
    """
    if not isinstance(rows, list) or not rows:
        return
    failed: list = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("是否成功") or "").strip() != "否":
            continue
        acct = str(r.get("账号") or "").strip() or "（未标注店铺）"
        pid = str(r.get("页面") or "").strip() or "（未知页面）"
        part = _page_id_to_task_part(pid)
        step_key = str(r.get("键/标签") or "").strip() or "（未命名步骤）"
        action = str(r.get("动作") or "").strip() or "（未知动作）"
        detail = str(r.get("结果") or "").strip() or "（无详细信息）"
        failed.append((acct, part, pid, step_key, action, detail))

    if not failed:
        return

    # 去重：同店同环节同步骤同原因只报一次，避免刷屏
    uniq = []
    seen = set()
    for item in failed:
        k = "||".join(item)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(item)
    uniq.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    print("\n========== 缺失环节提醒（请后续补齐）==========", file=sys.stderr)
    for acct, part, pid, step_key, action, detail in uniq:
        print(
            f"- {acct} 环节{part} 缺失：页面={pid}，步骤={step_key}，动作={action}",
            file=sys.stderr,
        )
        print(f"  详细信息：{detail}", file=sys.stderr)
    print("============================================\n", file=sys.stderr)


def _parse_fxg_switch_test_only(tpl: dict, args: Any) -> Optional[dict]:
    """
    仅测抖店切店：读 globalAccountLoop 的 preSwitchUrl、accountSwitcher、accounts；
    不要求配置 pageIds（与完整流水线解耦）。
    """
    raw = tpl.get("globalAccountLoop")
    if not isinstance(raw, dict):
        return None
    cli = (getattr(args, "global_accounts", "") or "").strip()
    accs: Optional[list] = None
    if cli:
        accs = [x.strip() for x in cli.split(",") if x.strip()]
    if accs is None:
        ra = raw.get("accounts")
        if isinstance(ra, list):
            accs = []
            for x in ra:
                if isinstance(x, dict):
                    n = str(x.get("name") or x.get("shopName") or "").strip()
                    if n:
                        accs.append(n)
                elif isinstance(x, str) and x.strip():
                    accs.append(x.strip())
    if not accs:
        return None
    pre = str(raw.get("preSwitchUrl") or "").strip()
    if not pre:
        return None
    sw = raw.get("accountSwitcher")
    if not isinstance(sw, dict):
        sw = {}
    anchor = str(raw.get("anchorPageId") or "fxg_mshop_home").strip()
    return {
        "accounts": accs,
        "preSwitchUrl": pre,
        "accountSwitcher": sw,
        "anchorPageId": anchor,
    }


def _split_interactions_for_navigate_from_current(
    interactions: Any, navigate_from_current: bool
) -> Tuple[list, list]:
    """navigateFromCurrent 页：带 beforeAccountSwitch 的步骤在顶栏跳转前执行，其余在目标域切换账号后执行。"""
    if not navigate_from_current or not isinstance(interactions, list):
        return [], [x for x in interactions if isinstance(x, dict)] if isinstance(interactions, list) else []
    before: list = []
    after: list = []
    for x in interactions:
        if not isinstance(x, dict):
            continue
        if x.get("beforeAccountSwitch"):
            before.append(x)
        else:
            after.append(x)
    return before, after


def _play_interactions_and_fields(
    page: Any,
    args: Any,
    tpl: dict,
    pid: str,
    acct: str,
    interactions: Any,
    fields: Any,
    rows: list,
    download_dir: Path,
    network_json_dir: Path,
    yday: str,
    *,
    suppress_tail_post_interaction_wait: bool = False,
    data_rows: Optional[list] = None,
    field_extract_budget_ms: Optional[int] = None,
    page_cfg: Optional[dict] = None,
    download_filename_prefix: str = "",
    selector_hints: Optional[dict] = None,
    template_hint_stem: str = "",
    hints_dirty: Optional[list] = None,
    network_capture_store: Optional[dict] = None,
) -> None:
    _try_dismiss_unexpected_overlays(page)
    dl_prefix = _sanitize_filename_prefix(download_filename_prefix or acct)
    ran_any_interaction = False
    vis_cap = _visible_cap_ms(args)
    dl_cap = _download_cap_ms(args)
    soft = _page_soft_fail_enabled(page_cfg)
    ph = _soft_fail_placeholder(page_cfg)
    if not args.only_extract and isinstance(interactions, list):
        ordered = sorted(
            [x for x in interactions if isinstance(x, dict)],
            key=lambda x: int(x.get("order") or 0),
        )
        _pdd_mod_max_pass = 2 if pid == "pdd_aftersale_export" else 1
        _pdd_mod_pass_i = 0
        _pdd_mod_need_another_pass = False
        while _pdd_mod_pass_i < _pdd_mod_max_pass:
            _pdd_mod_pass_i += 1
            _pdd_mod_need_another_pass = False
            for step in ordered:
                _try_dismiss_unexpected_overlays(page)
                stype = str(step.get("type") or "")
                key = str(step.get("key") or "")
                if not key:
                    bf = step.get("bindsFields")
                    if isinstance(bf, list) and bf:
                        key = ",".join(str(x) for x in bf)
                    else:
                        key = stype or "step"

                if getattr(args, "only_date_range", False) and stype != "dateRange":
                    continue

                ran_any_interaction = True

                if stype == "click":
                    tgt = step.get("target") or {}
                    tgt_d = tgt if isinstance(tgt, dict) else {}
                    sel = str(tgt_d.get("selector") or "")
                    alt = str(step.get("alternateClickSelector") or "").strip() or None
                    step_key = str(step.get("key") or key)
                    wants_download = "export" in step_key.lower()
                    click_sels = _collect_click_selectors(
                        step if isinstance(step, dict) else {}, tgt_d
                    )

                    if wants_download:
                        selectors = click_sels if click_sels else [s for s in (sel, alt) if (s or "").strip()]
                        ok = False
                        detail = ""
                        saved_path = ""
                        last_err = ""
                        mi = _step_match_index(step if isinstance(step, dict) else {})
                        vw = max(
                            3000,
                            _cap_visible_ms(step.get("waitVisibleTimeoutMs"), 10000, vis_cap),
                        )
                        edl = _resolve_export_download_timeout_ms(
                            step if isinstance(step, dict) else {}, 60000, dl_cap
                        )
                        try:
                            ef_retry_wait = int(step.get("exportFailRetryWaitMs") or 0)
                        except (TypeError, ValueError):
                            ef_retry_wait = 0
                        try:
                            ef_attempt_max = int(step.get("exportFailAttemptMax") or 0)
                        except (TypeError, ValueError):
                            ef_attempt_max = 0
                        if ef_retry_wait > 0:
                            if ef_attempt_max < 1:
                                ef_attempt_max = 30
                        else:
                            ef_attempt_max = 1
                        ef_attempt_max = max(1, min(ef_attempt_max, 200))
                        try:
                            pr_rw_after_fail = int(step.get("preExportReloadWaitMs") or 1000)
                        except (TypeError, ValueError):
                            pr_rw_after_fail = 1000

                        st = step if isinstance(step, dict) else {}
                        for attempt_i in range(ef_attempt_max):
                            ok, saved_path, detail, last_err = _try_export_download_once(
                                page,
                                st,
                                selectors,
                                mi,
                                vw,
                                edl,
                                download_dir,
                                dl_prefix,
                                step_key,
                                account=acct,
                                yday=yday,
                                task_name=str((tpl or {}).get("name") or ""),
                            )
                            if ok:
                                if attempt_i > 0:
                                    print(
                                        f"[{step_key}] 第 {attempt_i + 1} 次尝试后导出成功",
                                        file=sys.stderr,
                                    )
                                break
                            if attempt_i >= ef_attempt_max - 1:
                                break
                            if ef_retry_wait <= 0:
                                break
                            print(
                                f"[{step_key}] 导出未成功，{ef_retry_wait}ms 后刷新再试 ({attempt_i + 1}/{ef_attempt_max})…",
                                file=sys.stderr,
                            )
                            try:
                                page.wait_for_timeout(min(ef_retry_wait, 600000))
                            except Exception:
                                pass
                            try:
                                page.reload(wait_until="domcontentloaded", timeout=90000)
                            except Exception as e:
                                last_err = (last_err + "; " if last_err else "") + f"刷新失败: {e}"
                                continue
                            if pr_rw_after_fail > 0:
                                try:
                                    page.wait_for_timeout(min(pr_rw_after_fail, 600000))
                                except Exception:
                                    pass

                        eff_ok = ok
                        eff_detail = saved_path if ok else (last_err or "")
                        if (
                            not ok
                            and isinstance(step, dict)
                            and bool(step.get("optionalDownload"))
                            and _is_optional_export_no_file_err(last_err or "")
                        ):
                            eff_ok = True
                            eff_detail = (
                                "无符合条件数据未触发下载（已跳过本步） "
                                + ((last_err or "")[:450]).strip()
                            ).strip()

                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="interaction",
                                key=step_key,
                                action="click+download",
                                detail=eff_detail,
                                ok=eff_ok,
                            )
                        )
                        if not eff_ok:
                            if (
                                pid == "pdd_aftersale_export"
                                and _pdd_mod_pass_i == 1
                                and step_key == "export_pdd_aftersale_query_orders"
                                and _is_pdd_aftersale_download_query_menuitem_wait_timeout(
                                    last_err or ""
                                )
                            ):
                                rows.append(
                                    _result_row(
                                        page_id=pid,
                                        account=acct,
                                        phase="interaction",
                                        key=step_key,
                                        action="pdd_module_reload_retry",
                                        detail=(
                                            "拼多多售后：「下载查询订单」menuitem 未在超时内可见；"
                                            "整页刷新后从本页第一步重试一次"
                                        ),
                                        ok=True,
                                    )
                                )
                                try:
                                    page.reload(
                                        wait_until="domcontentloaded", timeout=90000
                                    )
                                except Exception as re:
                                    rows.append(
                                        _result_row(
                                            page_id=pid,
                                            account=acct,
                                            phase="interaction",
                                            key=step_key,
                                            action="pdd_module_reload_retry",
                                            detail=f"整页刷新失败: {re}",
                                            ok=False,
                                        )
                                    )
                                    if isinstance(step, dict) and bool(
                                        step.get("continueOnFail")
                                    ):
                                        continue
                                    _abort_on_step_fail(
                                        args,
                                        pid,
                                        acct,
                                        step_key,
                                        "click+download",
                                        str(re),
                                    )
                                pgw = 2800
                                if isinstance(page_cfg, dict):
                                    try:
                                        pgw = int(page_cfg.get("postGotoWaitMs") or 2800)
                                    except (TypeError, ValueError):
                                        pgw = 2800
                                pgw = max(0, min(int(pgw), 120000))
                                if pgw > 0:
                                    try:
                                        page.wait_for_timeout(pgw)
                                    except Exception:
                                        pass
                                _pdd_mod_need_another_pass = True
                                break
                            if soft:
                                _soft_fail_fill_remaining_fields(
                                    data_rows=data_rows,
                                    rows=rows,
                                    fields=fields,
                                    acct=acct,
                                    pid=pid,
                                    placeholder=ph,
                                    reason=f"click+download 失败: {last_err or '导出点击/下载失败'}",
                                    already_have=set(),
                                )
                                return
                            if isinstance(step, dict) and bool(step.get("continueOnFail")):
                                continue
                            _abort_on_step_fail(
                                args,
                                pid,
                                acct,
                                step_key,
                                "click+download",
                                last_err or "导出点击/下载失败",
                            )
                        ok = eff_ok
                    else:
                        cwv = _cap_visible_ms(step.get("waitVisibleTimeoutMs"), 10000, vis_cap)
                        skip_sv = bool(
                            (step.get("skipScrollIntoView") if isinstance(step, dict) else None)
                            or (step.get("noScrollBeforeClick") if isinstance(step, dict) else None)
                        )
                        ok, detail = _click_selector_chain(
                            page,
                            click_sels if click_sels else [s for s in (sel, alt) if (s or "").strip()],
                            cwv,
                            _step_match_index(step if isinstance(step, dict) else {}),
                            skip_scroll_into_view=skip_sv,
                        )
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="interaction",
                                key=step_key,
                                action="click",
                                detail=detail if ok else detail,
                                ok=ok,
                            )
                        )
                        if not ok:
                            if soft:
                                _soft_fail_fill_remaining_fields(
                                    data_rows=data_rows,
                                    rows=rows,
                                    fields=fields,
                                    acct=acct,
                                    pid=pid,
                                    placeholder=ph,
                                    reason=f"click 失败: {detail}",
                                    already_have=set(),
                                )
                                return
                            if isinstance(step, dict) and bool(step.get("continueOnFail")):
                                continue
                            _abort_on_step_fail(
                                args,
                                pid,
                                acct,
                                step_key,
                                "click",
                                str(detail),
                            )
                    if ok:
                        _network_capture_arm_if_step_matches(
                            page_cfg, network_capture_store, step_key
                        )
                    try:
                        pcw = int(step.get("postClickWaitMs") or 0)
                    except (TypeError, ValueError):
                        pcw = 0
                    if ok and pcw > 0:
                        try:
                            page.wait_for_timeout(min(pcw, 600000))
                        except Exception:
                            pass

                elif stype == "input":
                    step_key = str(step.get("key") or key)
                    tgt = step.get("target") or {}
                    tgt_d = tgt if isinstance(tgt, dict) else {}
                    sel_main = str(tgt_d.get("selector") or "").strip()
                    alts = step.get("alternateInputSelector")
                    selectors = [sel_main] if sel_main else []
                    if isinstance(alts, str) and alts.strip():
                        selectors.append(alts.strip())
                    elif isinstance(alts, list):
                        selectors.extend([str(x).strip() for x in alts if str(x or "").strip()])
                    # 去重保序
                    dedup = []
                    seen = set()
                    for s in selectors:
                        if s in seen:
                            continue
                        seen.add(s)
                        dedup.append(s)
                    selectors = dedup
                    if not selectors:
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="interaction",
                                key=step_key,
                                action="input",
                                detail="缺少 input selector",
                                ok=False,
                            )
                        )
                        if isinstance(step, dict) and bool(step.get("continueOnFail")):
                            continue
                        _abort_on_step_fail(args, pid, acct, step_key, "input", "缺少 input selector")

                    try:
                        ivw = _cap_visible_ms(step.get("waitVisibleTimeoutMs"), 10000, vis_cap)
                    except Exception:
                        ivw = 10000
                    clear_first = bool(step.get("clearFirst", True))
                    press_enter = bool(step.get("pressEnterAfterInput", False))
                    val, src_detail = _resolve_input_value(step if isinstance(step, dict) else {}, acct, tpl if isinstance(tpl, dict) else {})
                    if not val:
                        msg = f"input 值为空（来源: {src_detail}）"
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="interaction",
                                key=step_key,
                                action="input",
                                detail=msg,
                                ok=False,
                            )
                        )
                        if isinstance(step, dict) and bool(step.get("continueOnFail")):
                            continue
                        _abort_on_step_fail(args, pid, acct, step_key, "input", msg)
                    ok = False
                    detail = ""
                    for s in selectors:
                        try:
                            loc = page.locator(s).first
                            loc.wait_for(state="visible", timeout=ivw)
                            if clear_first:
                                try:
                                    loc.fill("", timeout=3000)
                                except Exception:
                                    pass
                            loc.fill(val, timeout=8000)
                            if press_enter:
                                try:
                                    loc.press("Enter", timeout=3000)
                                except Exception:
                                    pass
                            ok = True
                            detail = f"{s} <- {src_detail}"
                            break
                        except Exception as e:
                            detail = str(e)
                            continue
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="interaction",
                            key=step_key,
                            action="input",
                            detail=detail,
                            ok=ok,
                        )
                    )
                    if not ok:
                        if isinstance(step, dict) and bool(step.get("continueOnFail")):
                            continue
                        _abort_on_step_fail(args, pid, acct, step_key, "input", detail)
                    if ok:
                        _network_capture_arm_if_step_matches(
                            page_cfg, network_capture_store, step_key
                        )
                    try:
                        piw = int(step.get("postInputWaitMs") or 0)
                    except (TypeError, ValueError):
                        piw = 0
                    if ok and piw > 0:
                        try:
                            page.wait_for_timeout(min(piw, 600000))
                        except Exception:
                            pass

                elif stype == "scroll":
                    step_key = str(step.get("key") or key)
                    tgt = step.get("target") or {}
                    tgt_d = tgt if isinstance(tgt, dict) else {}
                    sel = str(tgt_d.get("selector") or "").strip()
                    scroll_mode = str(
                        step.get("scrollMode") or step.get("scrollTo") or "end"
                    ).strip().lower()
                    sw_raw = step.get("scrollWindow")
                    scroll_window = True if sw_raw is None else bool(sw_raw)
                    if isinstance(sw_raw, str):
                        scroll_window = sw_raw.strip().lower() in ("1", "true", "yes", "on")
                    ok = True
                    detail_parts = []
                    vw_scroll = _cap_visible_ms(
                        step.get("waitVisibleTimeoutMs"), 7500, vis_cap
                    )
                    try:
                        if scroll_window:
                            page.evaluate(
                                """() => {
                                  const h = Math.max(
                                    document.body ? document.body.scrollHeight : 0,
                                    document.documentElement
                                      ? document.documentElement.scrollHeight
                                      : 0
                                  );
                                  window.scrollTo(0, h);
                                }"""
                            )
                            detail_parts.append("window:end")
                        if sel:
                            loc = page.locator(sel).first
                            loc.wait_for(state="attached", timeout=vw_scroll)
                            if scroll_mode in ("end", "max", "bottom"):
                                loc.evaluate("el => { el.scrollTop = el.scrollHeight; }")
                            else:
                                loc.evaluate("el => { el.scrollTop = 0; }")
                            detail_parts.append(sel[:160])
                        elif not scroll_window:
                            ok = False
                            detail_parts.append("缺少 scrollWindow 与 target.selector")
                    except Exception as e:
                        ok = False
                        detail_parts.append(str(e))
                    detail = "; ".join(detail_parts) if detail_parts else "scroll"
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="interaction",
                            key=step_key,
                            action="scroll",
                            detail=detail if ok else detail,
                            ok=ok,
                        )
                    )
                    if not ok:
                        if soft:
                            _soft_fail_fill_remaining_fields(
                                data_rows=data_rows,
                                rows=rows,
                                fields=fields,
                                acct=acct,
                                pid=pid,
                                placeholder=ph,
                                reason=f"scroll 失败: {detail}",
                                already_have=set(),
                            )
                            return
                        _abort_on_step_fail(args, pid, acct, step_key, "scroll", str(detail))
                    if ok:
                        _network_capture_arm_if_step_matches(
                            page_cfg, network_capture_store, step_key
                        )
                    try:
                        psw = int(step.get("postScrollWaitMs") or 0)
                    except (TypeError, ValueError):
                        psw = 0
                    if ok and psw > 0:
                        try:
                            page.wait_for_timeout(min(psw, 600000))
                        except Exception:
                            pass

                elif stype == "dateRange":
                    tgt = step.get("target") or {}
                    sel = str((tgt.get("selector") if isinstance(tgt, dict) else "") or "")
                    alt_open_list: list = []
                    if isinstance(tgt, dict):
                        ao = tgt.get("alternateOpenSelector")
                        if isinstance(ao, str) and ao.strip():
                            alt_open_list = [ao.strip()]
                        elif isinstance(ao, list):
                            alt_open_list = [str(x).strip() for x in ao if str(x or "").strip()]
                    start_in = str(tgt.get("startInputSelector") or "").strip()
                    end_in = str(tgt.get("endInputSelector") or "").strip()
                    cal_panel = str(tgt.get("calendarPanelSelector") or "").strip()
                    policy = str(step.get("datePolicy") or tpl.get("datePolicyDefault") or "")
                    day = yday if policy == "previousCalendarDay" else yday
                    dr_base = int(getattr(args, "date_range_container_timeout_ms", 60000))
                    dr_to = _cap_visible_ms(dr_base, dr_base, vis_cap)
                    strat = str(step.get("dateRangeStrategy") or "").strip()
                    shortcut_sel = str(step.get("shortcutSelector") or "").strip()
                    alt_raw = step.get("alternateShortcutSelector")
                    alt_list: list = []
                    if isinstance(alt_raw, str) and alt_raw.strip():
                        alt_list = [alt_raw.strip()]
                    elif isinstance(alt_raw, list):
                        alt_list = [str(x).strip() for x in alt_raw if str(x or "").strip()]
                    st_d = step if isinstance(step, dict) else {}
                    fb_md = True
                    if st_d.get("minDisabledFallbackToYesterday") is not None:
                        fb_md = bool(st_d.get("minDisabledFallbackToYesterday"))
                    try:
                        pcm = int(st_d.get("postCalendarOpenWaitMs") or 500)
                    except (TypeError, ValueError):
                        pcm = 500
                    pcm = max(0, min(pcm, 30000))
                    _pgc = page_cfg if isinstance(page_cfg, dict) else {}
                    _auxo_hr = bool(_pgc.get("auxoDateRangeRetryViaHome")) or bool(
                        st_d.get("useHomeRoundtripOnAuxoCalendarMiss")
                    )
                    ok, detail = _apply_previous_day_range(
                        page,
                        sel,
                        day,
                        container_timeout_ms=dr_to,
                        shortcut_selector=shortcut_sel,
                        alternate_shortcut_selectors=alt_list,
                        date_range_strategy=strat,
                        start_input_selector=start_in,
                        end_input_selector=end_in,
                        calendar_panel_selector=cal_panel,
                        alternate_open_selectors=alt_open_list or None,
                        fallback_min_disabled_to_yesterday=fb_md,
                        post_calendar_open_wait_ms=pcm,
                        trial_template_abs=str(
                            getattr(args, "_trial_template_abs", "") or ""
                        ),
                        auxo_home_roundtrip=_auxo_hr,
                    )
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="interaction",
                            key=key,
                            action="dateRange",
                            detail=detail if ok else detail,
                            ok=ok,
                        )
                    )
                    if not ok:
                        if soft:
                            _soft_fail_fill_remaining_fields(
                                data_rows=data_rows,
                                rows=rows,
                                fields=fields,
                                acct=acct,
                                pid=pid,
                                placeholder=ph,
                                reason=f"dateRange 失败: {detail}",
                                already_have=set(),
                            )
                            return
                        if isinstance(step, dict) and bool(step.get("continueOnFail")):
                            continue
                        _abort_on_step_fail(args, pid, acct, key, "dateRange", str(detail))
                    if ok:
                        _network_capture_arm_if_step_matches(
                            page_cfg, network_capture_store, key
                        )
                    if ok and int(getattr(args, "post_date_range_wait_ms", 0) or 0) > 0:
                        page.wait_for_timeout(int(args.post_date_range_wait_ms))

                elif stype == "selectFilter":
                    tgt = step.get("target") or {}
                    labels = _select_filter_labels_to_try(step if isinstance(step, dict) else {})
                    sels = _select_filter_selectors(step, tgt if isinstance(tgt, dict) else {})
                    box_vw = _cap_visible_ms(
                        step.get("waitVisibleTimeoutMs"), _SELECT_FILTER_VISIBLE_DEFAULT_MS, vis_cap
                    )
                    st_d = step if isinstance(step, dict) else {}
                    confirm_sels = _select_filter_confirm_selectors_from_step(st_d)
                    conf_vw = _cap_visible_ms(
                        st_d.get("postSelectConfirmWaitVisibleMs"), 8000, vis_cap
                    )
                    conf_skip = st_d.get("postSelectConfirmSkipScroll")
                    if conf_skip is None:
                        conf_skip = True
                    try:
                        pick_to = int(st_d.get("selectOptionClickTimeoutMs") or 12000)
                    except (TypeError, ValueError):
                        pick_to = 12000
                    ok, detail = _select_filter_value(
                        page,
                        sels,
                        labels,
                        box_vw,
                        confirm_selectors=confirm_sels or None,
                        confirm_wait_visible_ms=conf_vw,
                        confirm_skip_scroll=bool(conf_skip),
                        option_click_timeout_ms=pick_to,
                    )
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="interaction",
                            key=key,
                            action="selectFilter",
                            detail=detail,
                            ok=ok,
                        )
                    )
                    if not ok:
                        if soft:
                            _soft_fail_fill_remaining_fields(
                                data_rows=data_rows,
                                rows=rows,
                                fields=fields,
                                acct=acct,
                                pid=pid,
                                placeholder=ph,
                                reason=f"selectFilter 失败: {detail}",
                                already_have=set(),
                            )
                            return
                        _abort_on_step_fail(args, pid, acct, key, "selectFilter", str(detail))
                    if ok:
                        _network_capture_arm_if_step_matches(
                            page_cfg, network_capture_store, key
                        )

                else:
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="interaction",
                            key=key,
                            action=stype or "unknown",
                            detail="未识别的 interaction.type",
                            ok=False,
                        )
                    )
                    if soft:
                        _soft_fail_fill_remaining_fields(
                            data_rows=data_rows,
                            rows=rows,
                            fields=fields,
                            acct=acct,
                            pid=pid,
                            placeholder=ph,
                            reason=f"未识别的 interaction.type: {stype or 'unknown'}",
                            already_have=set(),
                        )
                        return
                    _abort_on_step_fail(
                        args,
                        pid,
                        acct,
                        key,
                        stype or "unknown",
                        "未识别的 interaction.type",
                    )
            if not _pdd_mod_need_another_pass:
                break

    if (
        ran_any_interaction
        and getattr(args, "post_interaction_wait_ms", 0) > 0
        and not suppress_tail_post_interaction_wait
    ):
        try:
            page.wait_for_timeout(int(args.post_interaction_wait_ms))
        except Exception as e:
            if "Target page, context or browser has been closed" not in str(e):
                raise

    has_field_work = isinstance(fields, list) and any(isinstance(f, dict) for f in fields)
    if (
        has_field_work
        and not ran_any_interaction
        and int(getattr(args, "post_interaction_wait_ms", 0) or 0) > 0
        and not suppress_tail_post_interaction_wait
        and not getattr(args, "only_date_range", False)
    ):
        try:
            page.wait_for_timeout(int(args.post_interaction_wait_ms))
        except Exception as e:
            if "Target page, context or browser has been closed" not in str(e):
                raise

    if isinstance(fields, list) and not getattr(args, "only_date_range", False):
        try:
            ft_base = int(getattr(args, "field_locator_timeout_ms", 30000))
        except (TypeError, ValueError):
            ft_base = 30000
        if isinstance(page_cfg, dict):
            raw_oft = page_cfg.get("fieldLocatorTimeoutMs")
            if raw_oft is not None:
                try:
                    po = max(500, min(120000, int(raw_oft)))
                    ft_base = min(ft_base, po)
                except (TypeError, ValueError):
                    pass
        field_vis_cap = _cap_visible_ms(ft_base, ft_base, vis_cap)
        pgx = page_cfg if isinstance(page_cfg, dict) else {}
        dismiss = pgx.get("dismissBlockingOverlaysBeforeFields")
        if dismiss is None:
            dismiss = True
        field_extract_deadline_mono: Optional[float] = None
        if field_extract_budget_ms is not None:
            try:
                bms = int(field_extract_budget_ms)
            except (TypeError, ValueError):
                bms = 0
            bms = max(1000, min(120000, bms))
            field_extract_deadline_mono = time.monotonic() + bms / 1000.0
        field_done: set = set()
        value_ctx: dict = {}
        # 千川首字段探针成功后复用结果，避免主循环再抽一遍「整体消耗」
        qianchuan_probe_first_fkey: Optional[str] = None

        # 千川：模板中第一个 extract:text 字段若为「--」类无数据占位，不再继续抽后续字段，三指标统一填 0
        if pid == "qianchuan_home_cost_roi" and data_rows is not None:
            q_txt_fields: list = []
            for x in fields:
                if not isinstance(x, dict):
                    continue
                ex = x.get("extract") or {}
                et = str((ex.get("type") if isinstance(ex, dict) else "") or "text")
                if et == "text":
                    q_txt_fields.append(x)
            if q_txt_fields:
                f0 = q_txt_fields[0]
                fk0_probe = str(f0.get("key") or "").strip()
                if field_extract_deadline_mono is not None:
                    remain0 = field_extract_deadline_mono - time.monotonic()
                    if remain0 <= 0:
                        per_cap0 = 500
                    else:
                        per_cap0 = min(
                            field_vis_cap, int(max(500, remain0 * 1000))
                        )
                else:
                    per_cap0 = field_vis_cap
                hint0: Optional[str] = None
                if selector_hints is not None and template_hint_stem:
                    hint0 = _field_selector_hint_lookup(
                        selector_hints,
                        template_hint_stem,
                        pid,
                        fk0_probe,
                        acct,
                    )
                sel0 = str(f0.get("selector") or "")
                t_first, det_first = _timed_extract_field_text(
                    page,
                    sel0,
                    per_cap0,
                    f0,
                    args=args,
                    account=acct,
                    page_id=pid,
                    field_key=str(f0.get("key") or ""),
                    selector_hint=hint0,
                )
                if _qianchuan_first_metric_is_empty_dash(t_first):
                    _qianchuan_fill_zeros_no_data(
                        fields,
                        acct=acct,
                        pid=pid,
                        data_rows=data_rows,
                        rows=rows,
                    )
                    return
                ext0 = f0.get("extract") or {}
                fn0 = bool((ext0.get("firstNumberOnly") if isinstance(ext0, dict) else False))
                t_use = t_first
                if fn0:
                    picked0 = _first_number_text(t_first)
                    if picked0:
                        t_use = picked0
                if t_use and fk0_probe:
                    label0 = str(f0.get("label") or fk0_probe or "")
                    if (
                        selector_hints is not None
                        and template_hint_stem
                        and hints_dirty is not None
                    ):
                        hint_key0 = _field_selector_hint_key(
                            template_hint_stem, pid, fk0_probe, acct
                        )
                        if hint_key0:
                            norm0 = det_first.replace(" (visible)", "").strip()
                            if selector_hints.get(hint_key0) != norm0:
                                selector_hints[hint_key0] = norm0
                                hints_dirty[0] = True
                    _append_data_row(
                        data_rows,
                        account=acct,
                        field_key=fk0_probe,
                        label=label0,
                        value=t_use,
                    )
                    value_ctx[fk0_probe] = t_use
                    field_done.add(fk0_probe)
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="field",
                            key=label0 or fk0_probe,
                            action="extract:text",
                            detail=f"{t_use}  ← {det_first}",
                            ok=True,
                        )
                    )
                    qianchuan_probe_first_fkey = fk0_probe

        for f in fields:
            if dismiss:
                _try_dismiss_unexpected_overlays(page)
            if not isinstance(f, dict):
                continue
            label = str(f.get("label") or f.get("key") or "")
            fkey = str(f.get("key") or label)
            sel = str(f.get("selector") or "")
            ext = f.get("extract") or {}
            etype = str((ext.get("type") if isinstance(ext, dict) else "") or "text")
            skip_if_empty = bool((ext.get("skipIfEmpty") if isinstance(ext, dict) else False))
            first_number_only = bool((ext.get("firstNumberOnly") if isinstance(ext, dict) else False))
            if (
                pid == "qianchuan_home_cost_roi"
                and etype == "text"
                and qianchuan_probe_first_fkey
                and fkey == qianchuan_probe_first_fkey
            ):
                continue
            if etype not in ("text", "tableColumnAgg", "computedDivide", "tableTotalByHeader"):
                if soft:
                    _append_data_row(
                        data_rows, account=acct, field_key=fkey, label=label, value=ph
                    )
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="field",
                            key=label or fkey,
                            action=f"extract:{etype}",
                            detail=f"{ph}（softFailPage：不支持的 extract 类型 {etype}）",
                            ok=True,
                        )
                    )
                    field_done.add(fkey)
                    continue
                rows.append(
                    _result_row(
                        page_id=pid,
                        account=acct,
                        phase="field",
                        key=fkey,
                        action=f"extract:{etype}",
                        detail="试运行脚本支持 extract.type=text / tableColumnAgg / computedDivide / tableTotalByHeader",
                        ok=False,
                    )
                )
                _abort_on_step_fail(
                    args,
                    pid,
                    acct,
                    fkey,
                    "extract",
                    f"不支持的 extract 类型: {etype}",
                )
                continue
            if etype == "tableTotalByHeader":
                if field_extract_deadline_mono is not None:
                    remain_s = field_extract_deadline_mono - time.monotonic()
                    if remain_s <= 0:
                        if soft:
                            _soft_fail_fill_remaining_fields(
                                data_rows=data_rows,
                                rows=rows,
                                fields=fields,
                                acct=acct,
                                pid=pid,
                                placeholder=ph,
                                reason="已超过字段抽取总时限（field_extract_budget_ms）",
                                already_have=field_done,
                            )
                            break
                        _abort_on_step_fail(
                            args,
                            pid,
                            acct,
                            label or fkey,
                            "extract:tableTotalByHeader",
                            "已超过字段抽取总时限（field_extract_budget_ms）",
                        )
                        continue
                    per_cap_tt = min(field_vis_cap, int(max(500, remain_s * 1000)))
                else:
                    per_cap_tt = field_vis_cap
                t_tt, det_tt = _extract_table_total_by_header(page, per_cap_tt, f)
                if t_tt:
                    _append_data_row(
                        data_rows, account=acct, field_key=fkey, label=label, value=t_tt
                    )
                    value_ctx[fkey] = t_tt
                    field_done.add(fkey)
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="field",
                            key=label or fkey,
                            action="extract:tableTotalByHeader",
                            detail=f"{t_tt}  ← {det_tt}",
                            ok=True,
                        )
                    )
                else:
                    if soft:
                        _append_data_row(
                            data_rows, account=acct, field_key=fkey, label=label, value=ph
                        )
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="field",
                                key=label or fkey,
                                action="extract:tableTotalByHeader",
                                detail=f"{ph}（softFailPage：{det_tt}）",
                                ok=True,
                            )
                        )
                        field_done.add(fkey)
                    else:
                        if skip_if_empty:
                            rows.append(
                                _result_row(
                                    page_id=pid,
                                    account=acct,
                                    phase="field",
                                    key=label or fkey,
                                    action="extract:tableTotalByHeader",
                                    detail=f"skipIfEmpty=true，空值已跳过：{det_tt}",
                                    ok=True,
                                )
                            )
                            field_done.add(fkey)
                            continue
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="field",
                                key=label or fkey,
                                action="extract:tableTotalByHeader",
                                detail=det_tt,
                                ok=False,
                            )
                        )
                        _abort_on_step_fail(
                            args,
                            pid,
                            acct,
                            label or fkey,
                            "extract:tableTotalByHeader",
                            str(det_tt),
                        )
                continue
            if etype == "tableColumnAgg":
                if field_extract_deadline_mono is not None:
                    remain_s = field_extract_deadline_mono - time.monotonic()
                    if remain_s <= 0:
                        if soft:
                            _soft_fail_fill_remaining_fields(
                                data_rows=data_rows,
                                rows=rows,
                                fields=fields,
                                acct=acct,
                                pid=pid,
                                placeholder=ph,
                                reason="已超过字段抽取总时限（field_extract_budget_ms）",
                                already_have=field_done,
                            )
                            break
                        _abort_on_step_fail(
                            args,
                            pid,
                            acct,
                            label or fkey,
                            "extract:tableColumnAgg",
                            "已超过字段抽取总时限（field_extract_budget_ms）",
                        )
                        continue
                    per_cap_tc = min(
                        field_vis_cap, int(max(500, remain_s * 1000))
                    )
                else:
                    per_cap_tc = field_vis_cap
                t_agg, det_agg = _timed_extract_table_column_agg(
                    page,
                    per_cap_tc,
                    f,
                    args=args,
                    account=acct,
                    page_id=pid,
                    field_key=fkey,
                )
                if t_agg:
                    _append_data_row(
                        data_rows, account=acct, field_key=fkey, label=label, value=t_agg
                    )
                    value_ctx[fkey] = t_agg
                    field_done.add(fkey)
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="field",
                            key=label or fkey,
                            action="extract:tableColumnAgg",
                            detail=f"{t_agg}  ← {det_agg}",
                            ok=True,
                        )
                    )
                else:
                    if soft:
                        _append_data_row(
                            data_rows, account=acct, field_key=fkey, label=label, value=ph
                        )
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="field",
                                key=label or fkey,
                                action="extract:tableColumnAgg",
                                detail=f"{ph}（softFailPage：{det_agg}）",
                                ok=True,
                            )
                        )
                        field_done.add(fkey)
                    else:
                        if skip_if_empty:
                            rows.append(
                                _result_row(
                                    page_id=pid,
                                    account=acct,
                                    phase="field",
                                    key=label or fkey,
                                    action="extract:tableColumnAgg",
                                    detail=f"skipIfEmpty=true，空值已跳过：{det_agg}",
                                    ok=True,
                                )
                            )
                            field_done.add(fkey)
                            continue
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="field",
                                key=label or fkey,
                                action="extract:tableColumnAgg",
                                detail=det_agg,
                                ok=False,
                            )
                        )
                        _abort_on_step_fail(
                            args,
                            pid,
                            acct,
                            label or fkey,
                            "extract:tableColumnAgg",
                            str(det_agg),
                        )
                continue
            if etype == "computedDivide":
                t_calc, det_calc = _extract_computed_divide(f, value_ctx)
                if t_calc:
                    _append_data_row(
                        data_rows, account=acct, field_key=fkey, label=label, value=t_calc
                    )
                    value_ctx[fkey] = t_calc
                    field_done.add(fkey)
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="field",
                            key=label or fkey,
                            action="extract:computedDivide",
                            detail=f"{t_calc}  ← {det_calc}",
                            ok=True,
                        )
                    )
                else:
                    if soft:
                        _append_data_row(
                            data_rows, account=acct, field_key=fkey, label=label, value=ph
                        )
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="field",
                                key=label or fkey,
                                action="extract:computedDivide",
                                detail=f"{ph}（softFailPage：{det_calc}）",
                                ok=True,
                            )
                        )
                        field_done.add(fkey)
                    else:
                        if skip_if_empty:
                            rows.append(
                                _result_row(
                                    page_id=pid,
                                    account=acct,
                                    phase="field",
                                    key=label or fkey,
                                    action="extract:computedDivide",
                                    detail=f"skipIfEmpty=true，空值已跳过：{det_calc}",
                                    ok=True,
                                )
                            )
                            field_done.add(fkey)
                            continue
                        rows.append(
                            _result_row(
                                page_id=pid,
                                account=acct,
                                phase="field",
                                key=label or fkey,
                                action="extract:computedDivide",
                                detail=det_calc,
                                ok=False,
                            )
                        )
                        _abort_on_step_fail(
                            args,
                            pid,
                            acct,
                            label or fkey,
                            "extract:computedDivide",
                            str(det_calc),
                        )
                continue
            alt_raw = f.get("alternateFieldSelector") if isinstance(f, dict) else None
            has_alt = False
            if isinstance(alt_raw, str) and alt_raw.strip():
                has_alt = True
            elif isinstance(alt_raw, list) and any(str(x or "").strip() for x in alt_raw):
                has_alt = True
            net_text, net_detail = _try_field_from_network_capture(
                page_cfg if isinstance(page_cfg, dict) else None,
                network_capture_store,
                fkey,
                yday,
            )
            if net_text:
                if first_number_only:
                    picked = _first_number_text(net_text)
                    if picked:
                        net_text = picked
                _append_data_row(
                    data_rows, account=acct, field_key=fkey, label=label, value=net_text
                )
                value_ctx[fkey] = net_text
                field_done.add(fkey)
                rows.append(
                    _result_row(
                        page_id=pid,
                        account=acct,
                        phase="field",
                        key=label or fkey,
                        action="extract:text",
                        detail=f"{net_text}  ← {net_detail}",
                        ok=True,
                    )
                )
                continue
            nrs_fb = page_cfg.get("networkResponseCapture") if isinstance(page_cfg, dict) else None
            if (
                isinstance(nrs_fb, dict)
                and nrs_fb.get("domFallback") is False
                and _parse_network_response_capture_config(page_cfg if isinstance(page_cfg, dict) else {})
            ):
                rows.append(
                    _result_row(
                        page_id=pid,
                        account=acct,
                        phase="field",
                        key=label or fkey,
                        action="extract:text",
                        detail="networkResponseCapture 未从 JSON 取到对应日期明文（domFallback=false，不使用 DOM）",
                        ok=False,
                    )
                )
                _abort_on_step_fail(
                    args,
                    pid,
                    acct,
                    label or fkey,
                    "extract:text",
                    "仅使用 queryMallTradeList 等拦截 JSON，未匹配到 stateDate=昨日 或可读数值",
                )
                continue
            if not (sel or has_alt):
                if soft:
                    _append_data_row(
                        data_rows, account=acct, field_key=fkey, label=label, value=ph
                    )
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="field",
                            key=label or fkey,
                            action="extract:text",
                            detail=f"{ph}（softFailPage：缺少 selector）",
                            ok=True,
                        )
                    )
                    field_done.add(fkey)
                    continue
                rows.append(
                    _result_row(
                        page_id=pid,
                        account=acct,
                        phase="field",
                        key=fkey,
                        action="extract:text",
                        detail="缺少 selector（且无 alternateFieldSelector）",
                        ok=False,
                    )
                )
                _abort_on_step_fail(
                    args, pid, acct, fkey, "extract:text", "缺少 selector（且无 alternateFieldSelector）"
                )
                continue
            if field_extract_deadline_mono is not None:
                remain_s = field_extract_deadline_mono - time.monotonic()
                if remain_s <= 0:
                    if soft:
                        _soft_fail_fill_remaining_fields(
                            data_rows=data_rows,
                            rows=rows,
                            fields=fields,
                            acct=acct,
                            pid=pid,
                            placeholder=ph,
                            reason="已超过字段抽取总时限（field_extract_budget_ms）",
                            already_have=field_done,
                        )
                        break
                    _abort_on_step_fail(
                        args,
                        pid,
                        acct,
                        label or fkey,
                        "extract:text",
                        "已超过字段抽取总时限（field_extract_budget_ms）",
                    )
                per_cap = min(field_vis_cap, int(max(500, remain_s * 1000)))
            else:
                per_cap = field_vis_cap
            hint_sel = None
            hint_key = ""
            if (
                selector_hints is not None
                and template_hint_stem
                and isinstance(f, dict)
            ):
                hint_key = _field_selector_hint_key(
                    template_hint_stem, pid, fkey, acct
                )
                hint_sel = _field_selector_hint_lookup(
                    selector_hints, template_hint_stem, pid, fkey, acct
                )
            text, detail_or_err = _timed_extract_field_text(
                page,
                sel,
                per_cap,
                f,
                args=args,
                account=acct,
                page_id=pid,
                field_key=fkey,
                selector_hint=hint_sel,
            )
            if text:
                if first_number_only:
                    picked = _first_number_text(text)
                    if picked:
                        text = picked
                if (
                    selector_hints is not None
                    and hint_key
                    and hints_dirty is not None
                ):
                    norm = detail_or_err.replace(" (visible)", "").strip()
                    if selector_hints.get(hint_key) != norm:
                        selector_hints[hint_key] = norm
                        hints_dirty[0] = True
                _append_data_row(data_rows, account=acct, field_key=fkey, label=label, value=text)
                value_ctx[fkey] = text
                field_done.add(fkey)
                rows.append(
                    _result_row(
                        page_id=pid,
                        account=acct,
                        phase="field",
                        key=label or fkey,
                        action="extract:text",
                        detail=f"{text}  ← {detail_or_err}",
                        ok=True,
                    )
                )
            else:
                if soft:
                    _append_data_row(
                        data_rows, account=acct, field_key=fkey, label=label, value=ph
                    )
                    rows.append(
                        _result_row(
                            page_id=pid,
                            account=acct,
                            phase="field",
                            key=label or fkey,
                            action="extract:text",
                            detail=f"{ph}（softFailPage：{detail_or_err}）",
                            ok=True,
                        )
                    )
                    field_done.add(fkey)
                    continue
                rows.append(
                    _result_row(
                        page_id=pid,
                        account=acct,
                        phase="field",
                        key=label or fkey,
                        action="extract:text",
                        detail=detail_or_err,
                        ok=False,
                    )
                )
                _abort_on_step_fail(args, pid, acct, label or fkey, "extract:text", str(detail_or_err))

    _maybe_save_network_capture_response(
        page_cfg if isinstance(page_cfg, dict) else None,
        network_capture_store if isinstance(network_capture_store, dict) else None,
        network_json_dir,
        yday,
        pid,
        acct,
    )


def _template_page_goto_switch_play(
    page: Any,
    args: Any,
    tpl: dict,
    pid: str,
    acct: str,
    pg_inner: dict,
    rows: list,
    download_dir: Path,
    network_json_dir: Path,
    yday: str,
    data_rows: Optional[list] = None,
    download_filename_prefix: str = "",
    *,
    qianchuan_switch_override: Any = _QC_SWITCH_OVERRIDE_UNSET,
    selector_hints: Optional[dict] = None,
    template_hint_stem: str = "",
    hints_dirty: Optional[list] = None,
) -> bool:
    """
    单页流水线：可选 navigateFromCurrent（抖店顶栏进子站）→ 必要时目标站切换账号 → interactions + fields。
    openInNewTab：在新标签页打开 url，抽数后 closePageWhenDone 关闭该标签，主标签不变。
    返回 False 表示本页应跳过（与原先 continue 语义一致）。
    qianchuan_switch_override：仅 globalAccountLoop 且模板启用千川ID 策略时传入；为 None 表示本店无千川ID（不切户、不写 goto，指标写 None）；为 str 时千川切户用该串；缺省则千川仍用店铺名（旧行为）。
    """
    _try_dismiss_unexpected_overlays(page)
    main_u = _resolve_runtime_url(str(pg_inner.get("url") or "").strip())
    if (
        pid == "qianchuan_home_cost_roi"
        and qianchuan_switch_override is not _QC_SWITCH_OVERRIDE_UNSET
        and qianchuan_switch_override is not None
        and bool(pg_inner.get("appendAavidToQianchuanUrl"))
    ):
        qid = str(qianchuan_switch_override).strip()
        if qid:
            main_u = _merge_qianchuan_aavid_into_url(main_u, qid)
    open_new = bool(pg_inner.get("openInNewTab"))
    inte_full = pg_inner.get("interactions") or []
    flds = pg_inner.get("fields") or []
    if open_new:
        nvc = False
        inte_before: list = []
        inte_after = inte_full
    else:
        nvc = bool(pg_inner.get("navigateFromCurrent"))
        inte_before, inte_after = _split_interactions_for_navigate_from_current(inte_full, nvc)
    if pid == "qianchuan_home_cost_roi" and qianchuan_switch_override is not _QC_SWITCH_OVERRIDE_UNSET:
        if qianchuan_switch_override is None:
            rows.append(
                _result_row(
                    page_id=pid,
                    phase="account",
                    key="skip_qianchuan",
                    action="no_qianchuan_id",
                    detail="本店未配置千川ID，跳过千川页导航与切户，指标写入 None",
                    ok=True,
                    account=acct,
                )
            )
            _fill_qianchuan_skipped_no_id(pg_inner, pid, acct, flds, data_rows, rows)
            return True
    if not main_u and not nvc:
        _nav_fail_try_soft_fill(
            pg_inner, pid, acct, flds, data_rows, rows, "页面缺少 url 且非 navigateFromCurrent，无法进入"
        )
        return False

    active_page = page
    opened_new_tab = False
    if open_new:
        try:
            ctx = getattr(page, "context", None)
            if ctx is None:
                rows.append(
                    _result_row(
                        page_id=pid,
                        phase="nav",
                        key="openInNewTab",
                        action="new_tab",
                        detail="当前 page 无 context，无法新开标签",
                        ok=False,
                        account=acct,
                    )
                )
                _nav_fail_try_soft_fill(
                    pg_inner, pid, acct, flds, data_rows, rows, "当前 page 无 context，无法新开标签"
                )
                return False
            active_page = ctx.new_page()
            opened_new_tab = True
            rows.append(
                _result_row(
                    page_id=pid,
                    phase="nav",
                    key="openInNewTab",
                    action="new_tab",
                    detail=main_u,
                    ok=True,
                    account=acct,
                )
            )
        except Exception as e:
            rows.append(
                _result_row(
                    page_id=pid,
                    phase="nav",
                    key="openInNewTab",
                    action="new_tab",
                    detail=f"新开标签失败: {e}",
                    ok=False,
                    account=acct,
                )
            )
            _nav_fail_try_soft_fill(pg_inner, pid, acct, flds, data_rows, rows, f"新开标签失败: {e}")
            return False

    net_cap_store: dict = {}
    net_cap_cleanup: Any = None
    try:
        net_cap_store, net_cap_cleanup = _network_response_capture_attach(
            active_page, pg_inner if isinstance(pg_inner, dict) else {}
        )
        if not nvc:
            if main_u and not _page_goto_maybe(
                active_page,
                main_u,
                page_id=pid,
                acct=acct,
                args=args,
                rows=rows,
                pg=pg_inner,
            ):
                _nav_fail_try_soft_fill(
                    pg_inner, pid, acct, flds, data_rows, rows, "page_goto 失败（本页 url）"
                )
                return False
        else:
            if inte_before:
                pre_sw = str(pg_inner.get("preSwitchUrl") or "").strip()
                if _off_fxg_topbar_context(getattr(page, "url", "") or "") and pre_sw:
                    rows.append(
                        _result_row(
                            page_id=pid,
                            phase="nav",
                            key="goto",
                            action="navigateFromCurrent_reenter_fxg",
                            detail=f"上一页在子站，先回抖店承接页再点顶栏: {pre_sw}",
                            ok=True,
                            account=acct,
                        )
                    )
                    if not _page_goto_maybe(
                        page,
                        pre_sw,
                        page_id=pid,
                        acct=acct,
                        args=args,
                        rows=rows,
                        pg=pg_inner,
                    ):
                        _nav_fail_try_soft_fill(
                            pg_inner,
                            pid,
                            acct,
                            flds,
                            data_rows,
                            rows,
                            "page_goto 失败（preSwitchUrl 回抖店承接页）",
                        )
                        return False
                rows.append(
                    _result_row(
                        page_id=pid,
                        phase="nav",
                        key="goto",
                        action="navigateFromCurrent",
                        detail="跳过初始 goto，先执行顶栏进入目标站",
                        ok=True,
                        account=acct,
                    )
                )
                _play_interactions_and_fields(
                    page,
                    args,
                    tpl,
                    pid,
                    acct,
                    inte_before,
                    [],
                    rows,
                    download_dir,
                    network_json_dir,
                    yday,
                    suppress_tail_post_interaction_wait=True,
                    data_rows=data_rows,
                    page_cfg=pg_inner,
                    download_filename_prefix=download_filename_prefix,
                    selector_hints=selector_hints,
                    template_hint_stem=template_hint_stem,
                    hints_dirty=hints_dirty,
                    network_capture_store=net_cap_store,
                )
                _guard_topbar_nav_destination(page, pg_inner, pid, acct, args, rows)
            elif main_u:
                if not _page_goto_maybe(
                    page,
                    main_u,
                    page_id=pid,
                    acct=acct,
                    args=args,
                    rows=rows,
                    pg=pg_inner,
                ):
                    _nav_fail_try_soft_fill(
                        pg_inner,
                        pid,
                        acct,
                        flds,
                        data_rows,
                        rows,
                        "page_goto 失败（navigateFromCurrent 目标 url）",
                    )
                    return False
            else:
                rows.append(
                    _result_row(
                        page_id=pid,
                        phase="nav",
                        key="goto",
                        action="navigateFromCurrent",
                        detail="缺少 url 且无 beforeAccountSwitch 步骤，无法进入目标站",
                        ok=False,
                        account=acct,
                    )
                )
                _nav_fail_try_soft_fill(
                    pg_inner,
                    pid,
                    acct,
                    flds,
                    data_rows,
                    rows,
                    "缺少 url 且无 beforeAccountSwitch 步骤，无法进入目标站",
                )
                return False
        if _needs_post_goto_account_switch(pg_inner, pid):
            sw_kw: dict = {}
            if pid == "qianchuan_home_cost_roi" and qianchuan_switch_override is not _QC_SWITCH_OVERRIDE_UNSET:
                sw_kw["qianchuan_switch_key"] = str(qianchuan_switch_override or "").strip()
            ok2, det2 = _dispatch_account_switch(active_page, acct, pg_inner, pid, **sw_kw)
            rows.append(
                _result_row(
                    page_id=pid,
                    phase="account",
                    key="switch_after_goto",
                    action="switchAccount",
                    detail=det2,
                    ok=ok2,
                    account=acct,
                )
            )
            if not ok2:
                _nav_fail_try_soft_fill(
                    pg_inner, pid, acct, flds, data_rows, rows, f"switch_after_goto 失败: {det2}"
                )
                return False
        _apply_post_goto_wait(active_page, pg_inner)
        if isinstance(flds, list) and any(isinstance(f, dict) for f in flds):
            _apply_pre_field_extract_wait(active_page, pg_inner)

        inte_for_play = inte_after if nvc else inte_full
        try:
            _play_interactions_and_fields(
                active_page,
                args,
                tpl,
                pid,
                acct,
                inte_for_play,
                flds,
                rows,
                download_dir,
                network_json_dir,
                yday,
                data_rows=data_rows,
                field_extract_budget_ms=None,
                page_cfg=pg_inner,
                download_filename_prefix=download_filename_prefix,
                selector_hints=selector_hints,
                template_hint_stem=template_hint_stem,
                hints_dirty=hints_dirty,
                network_capture_store=net_cap_store,
            )
        except TrialAbort:
            raise
        return True
    finally:
        if net_cap_cleanup is not None:
            try:
                net_cap_cleanup()
            except Exception:
                pass
        if opened_new_tab and bool(pg_inner.get("closePageWhenDone", True)):
            try:
                active_page.close()
            except Exception:
                pass
            # 关新标签后把主 page 置前并短暂等待，避免多店轮次时主标签已开始 goto 下一店而用户仍盯着已关的新标签造成「顺序错乱」观感
            try:
                page.bring_to_front()
            except Exception:
                pass
            try:
                page.wait_for_timeout(400)
            except Exception:
                pass


def run(args: argparse.Namespace) -> int:
    global _RUN_ROOT_OVERRIDE
    _RUN_ROOT_OVERRIDE = None
    trial_checkpoint_clear()
    tpl_path: Path = args.template
    if not tpl_path.is_file():
        print(f"找不到模板: {tpl_path}", file=sys.stderr)
        return 1

    try:
        tpl = _load_template(tpl_path)
    except Exception as e:
        print(f"模板解析失败: {e}", file=sys.stderr)
        return 1

    setattr(args, "_trial_template_abs", str(tpl_path.resolve()))

    pages_cfg = tpl.get("pages")
    if not isinstance(pages_cfg, list):
        print("模板缺少 pages 数组", file=sys.stderr)
        return 1

    if bool(getattr(args, "resume", False)) and not getattr(args, "checkpoint", None):
        print("--resume 须同时指定 --checkpoint 断点 JSON 文件路径", file=sys.stderr)
        return 1

    pid_to_pg_registry = {
        str(p.get("id")): p
        for p in pages_cfg
        if isinstance(p, dict) and str(p.get("id") or "")
    }

    if bool(getattr(args, "only_extract", False)) and bool(getattr(args, "only_date_range", False)):
        print("不能同时使用 --only-extract 与 --only-date-range", file=sys.stderr)
        return 1
    if getattr(args, "only_account_switch", False) and (
        args.only_extract or getattr(args, "only_date_range", False)
    ):
        print("--only-account-switch 不能与 --only-extract / --only-date-range 同时使用", file=sys.stderr)
        return 1

    page_id_filter_raw = (getattr(args, "page_ids", None) or "").strip()
    task_part_raw = (getattr(args, "task_part", None) or "").strip()
    page_id_allow: Optional[set] = None
    if task_part_raw and page_id_filter_raw:
        print("--task-part 不能与 --page-ids 同时使用", file=sys.stderr)
        return 1
    if task_part_raw and getattr(args, "qianchuan_standalone", False):
        print("--task-part 不能与 --qianchuan-standalone 同时使用", file=sys.stderr)
        return 1
    if task_part_raw:
        parsed = _task_parts_page_ids(task_part_raw)
        if parsed is None:
            print("--task-part 仅支持 A/B/C/D，支持逗号多选（如 A,D）", file=sys.stderr)
            return 1
        part_pages, norm_parts = parsed
        page_id_allow = part_pages
        print(
            f"[任务分块] 当前分块 {','.join(norm_parts)}，仅运行: {', '.join(sorted(page_id_allow))}",
            file=sys.stderr,
        )
    if page_id_filter_raw:
        page_id_allow = {x.strip() for x in page_id_filter_raw.split(",") if x.strip()}

    if getattr(args, "qianchuan_standalone", False):
        if getattr(args, "only_account_switch", False):
            print("--qianchuan-standalone 不能与 --only-account-switch 同时使用", file=sys.stderr)
            return 1
        page_id_allow = {"qianchuan_home_cost_roi"}
        if "qianchuan_home_cost_roi" not in pid_to_pg_registry:
            print("模板中缺少 pages[].id: qianchuan_home_cost_roi", file=sys.stderr)
            return 1

    run_ts = dt.now().strftime("%Y%m%d_%H%M%S")
    global _TRIAL_RUN_LOG_T0_PERF, _TRIAL_RUN_LOG_LAST_PERF
    _TRIAL_RUN_LOG_T0_PERF = time.perf_counter()
    _TRIAL_RUN_LOG_LAST_PERF = _TRIAL_RUN_LOG_T0_PERF
    yday = _yesterday_str()
    run_day = dt.now().strftime("%Y%m%d")
    _stem = str((tpl or {}).get("aggregateExcelFileStem") or "").strip()

    _rr_arg = getattr(args, "run_root", None)
    if _rr_arg is not None and str(_rr_arg).strip():
        rp = Path(_rr_arg)
        if not rp.is_absolute():
            rp = PROJECT_ROOT / rp
        try:
            rp.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        _RUN_ROOT_OVERRIDE = rp.resolve()

    download_dir = Path(args.download_dir)
    _default_downloads = PROJECT_ROOT / "output" / "downloads"
    dr_root = str((tpl or {}).get("downloadRoot") or "").strip()
    if dr_root and download_dir.resolve() == _default_downloads.resolve():
        drp = Path(dr_root)
        download_dir = drp if drp.is_absolute() else (PROJECT_ROOT / drp)
    elif (
        download_dir.resolve() == _default_downloads.resolve()
        and str((tpl or {}).get("runOutputSubdir") or "").strip()
    ):
        # 与 excel 同级：runOutputRoot/{downloadRunSubdirTemplate}/，不再插入 downloads/ 以免路径过深
        download_dir = _trial_output_root(
            tpl if isinstance(tpl, dict) else None,
            run_ts=run_ts,
            yday=yday,
            run_day=run_day,
        )
    dl_sub_tmpl = str((tpl or {}).get("downloadRunSubdirTemplate") or "").strip()
    if dl_sub_tmpl:
        sub = (
            dl_sub_tmpl.replace("{task_name}", _sanitize_filename_prefix(str((tpl or {}).get("name") or "")))
            .replace("{run_date}", yday)
            .replace("{yday}", yday)
            .replace("{run_ts}", run_ts)
        )
        sub = _sanitize_filename_prefix(sub) or f"run_{run_ts}"
        download_dir = download_dir / sub
    download_dir.mkdir(parents=True, exist_ok=True)

    _nj_arg = getattr(args, "network_json_dir", None)
    if _nj_arg is not None and str(_nj_arg).strip():
        network_json_dir = Path(_nj_arg)
        if not network_json_dir.is_absolute():
            network_json_dir = PROJECT_ROOT / network_json_dir
        network_json_dir.mkdir(parents=True, exist_ok=True)
    else:
        network_json_dir = download_dir

    _xo = getattr(args, "excel_out", None)
    if _xo is not None and str(_xo).strip():
        excel_out = Path(_xo)
        if not excel_out.is_absolute():
            excel_out = PROJECT_ROOT / excel_out
    elif _stem:
        if dr_root:
            excel_out = download_dir / f"{_sanitize_filename_prefix(_stem)}_{run_day}.xlsx"
        else:
            excel_out = (
                _trial_output_root(
                    tpl if isinstance(tpl, dict) else None,
                    run_ts=run_ts,
                    yday=yday,
                    run_day=run_day,
                )
                / f"{_sanitize_filename_prefix(_stem)}_{run_day}.xlsx"
            )
    else:
        excel_out = (
            _trial_output_root(
                tpl if isinstance(tpl, dict) else None,
                run_ts=run_ts,
                yday=yday,
                run_day=run_day,
            )
            / f"template_trial_{run_ts}.xlsx"
        )
    excel_out.parent.mkdir(parents=True, exist_ok=True)
    trial_checkpoint_bind(excel_out, tpl if isinstance(tpl, dict) else None, args)
    log_dir: Path = args.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    run_log_csv = log_dir / f"template_trial_{run_ts}_run.csv"

    tl_raw = getattr(args, "timing_log", None)
    if tl_raw is None:
        timing_path: Optional[Path] = None
    elif tl_raw == _TIMING_LOG_AUTO:
        timing_path = log_dir / f"template_trial_{run_ts}_timing.csv"
    else:
        timing_path = Path(tl_raw)
    _timing_records_init(args, timing_path)

    if _RUN_ROOT_OVERRIDE is not None and not getattr(args, "no_selector_hints", False):
        try:
            _def_hints = (PROJECT_ROOT / "log" / "field_selector_hints.json").resolve()
            _cur_hints = Path(args.selector_hints_file).resolve()
            if _cur_hints == _def_hints:
                args.selector_hints_file = _RUN_ROOT_OVERRIDE / "runtime" / "field_selector_hints.json"
        except OSError:
            pass

    rows = (
        _RunLogCsvFlushList(run_log_csv)
        if not getattr(args, "no_incremental_checkpoint", False)
        else []
    )  # type: list
    data_rows: list = []  # 仅 extract:text 成功，写入 Excel
    if (
        bool(getattr(args, "resume", False))
        and getattr(args, "excel_out", None) is not None
        and Path(args.excel_out).is_file()
    ):
        data_rows = _read_existing_excel_metrics(Path(args.excel_out))
        if data_rows:
            print(
                f"[断点续跑] 已读入已有 Excel（{len(data_rows)} 条指标），将写入: {Path(args.excel_out).resolve()}",
                file=sys.stderr,
            )
            _trial_checkpoint_maybe_write(data_rows)
    hints_dirty = [False]
    template_hint_stem = tpl_path.stem
    selector_hints_path: Optional[Path] = None
    selector_hints: Optional[dict] = None
    if not getattr(args, "no_selector_hints", False):
        selector_hints_path = Path(getattr(args, "selector_hints_file"))
        selector_hints = _load_selector_hints(selector_hints_path)

    port = _cdp_port(args.cdp)
    env_port = os.environ.get("PICKER_DEBUG_PORT", "").strip()
    if env_port.isdigit():
        port = int(env_port)
        cdp_raw = args.cdp.strip()
        if not cdp_raw.startswith(("http://", "https://")):
            cdp_raw = "http://" + cdp_raw
        host = urlparse(cdp_raw).hostname or "127.0.0.1"
        args.cdp = f"http://{host}:{port}"

    if args.launch_chrome:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from picker_tool.chrome_launcher import ensure_chrome_remote_debugging

        ok_launch, err_launch = ensure_chrome_remote_debugging(
            port=port,
            wait_seconds=float(args.chrome_wait),
        )
        if not ok_launch:
            print(err_launch, file=sys.stderr)
            return 1
        print(
            "已自动启动带调试端口的 Chrome（独立目录 chrome-pw-debug）。"
            "若要用已登录的常用浏览器，请勿使用 --launch-chrome，请按脚本说明用远程调试方式自行启动 Chrome。"
        )

    from playwright.sync_api import sync_playwright

    aborted = False
    interrupted = False
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(args.cdp)
        except Exception as e:
            print(
                f"无法连接 CDP {args.cdp}: {e}\n\n"
                "请先启动带远程调试的 Chrome 并保持不关。推荐双击项目内：\n"
                "  scripts\\start_chrome_cdp_test.bat\n"
                "再运行本脚本。端口不一致时用：--cdp http://127.0.0.1:端口号\n"
                "备选：scripts\\start_chrome_cdp_with_profile.bat（若公司策略限制可能无 9222）。\n"
                "可加 --launch-chrome 自动起独立目录 Chrome（需重新登录）。\n",
                file=sys.stderr,
            )
            return 1

        try:
            if not browser.contexts:
                print("已连接但未发现浏览器上下文", file=sys.stderr)
                return 1

            context = browser.contexts[0]
            pick = "qianchuan" if getattr(args, "qianchuan_standalone", False) else "fxg"
            page = _cdp_pick_work_page(context, prefer=pick)
            if getattr(args, "qianchuan_standalone", False):
                print(
                    "【千川单独模式】已跳过抖店 globalAccountLoop；不主动导航千川首页（避免整页重载）。"
                    "请在本浏览器中先打开并停留在巨量千川（建议首页），登录并选好店铺后再运行。"
                )
                try:
                    u0 = (page.url or "").lower()
                    if "qianchuan.jinritemai.com" not in u0:
                        print(
                            "错误: 当前选中的标签页不是巨量千川域名，请切换到 qianchuan.jinritemai.com 后再运行。",
                            file=sys.stderr,
                        )
                        return 1
                except Exception:
                    print("错误: 无法读取当前页 URL。", file=sys.stderr)
                    return 1

            if getattr(args, "only_account_switch", False):
                st = _parse_fxg_switch_test_only(tpl, args)
                if not st:
                    print(
                        "分块测试「仅切店」需要：模板 globalAccountLoop 里配置 preSwitchUrl、"
                        "accountSwitcher（fxgShopModal），以及 accounts 或命令行 --global-accounts。",
                        file=sys.stderr,
                    )
                    return 1
                synth_id = st["anchorPageId"]
                synth_pg = {"id": synth_id, "accountSwitcher": st["accountSwitcher"]}
                for acct in st["accounts"]:
                    with _timing_span(
                        args,
                        account=acct,
                        page_id="fxg_switch_test",
                        phase="global_loop",
                        step="goto_preSwitchUrl",
                        detail=str(st.get("preSwitchUrl") or ""),
                    ):
                        if not _page_goto(
                            page,
                            st["preSwitchUrl"],
                            page_id="fxg_switch_test",
                            acct=acct,
                            args=args,
                            rows=rows,
                        ):
                            continue
                    try:
                        page.wait_for_timeout(2500)
                    except Exception:
                        pass
                    with _timing_span(
                        args,
                        account=acct,
                        page_id="fxg_switch_test",
                        phase="global_loop",
                        step="switch_account",
                        detail=str(synth_id),
                    ):
                        ok_sw, det_sw = _dispatch_account_switch(page, acct, synth_pg, synth_id)
                    rows.append(
                        _result_row(
                            page_id="fxg_switch_test",
                            phase="account",
                            key="switch",
                            action="switchAccount",
                            detail=det_sw,
                            ok=ok_sw,
                            account=acct,
                        )
                    )
                _maybe_write_timing_log(args, run_ts)
                try:
                    _write_run_log_csv(run_log_csv, rows)
                    _write_data_excel(excel_out, data_rows, tpl if isinstance(tpl, dict) else None)
                except KeyboardInterrupt:
                    print("\n已收到 Ctrl+C（收尾写入），尝试保存 CSV 兜底…", file=sys.stderr)
                    try:
                        _write_run_log_csv(run_log_csv, rows)
                    except BaseException:
                        pass
                    try:
                        fb = excel_out.with_suffix(".csv")
                        cols = ["店铺名", "键", "标签", "数据值"]
                        df_fb = (
                            pd.DataFrame(data_rows).reindex(columns=cols)
                            if data_rows
                            else pd.DataFrame(columns=cols)
                        )
                        df_fb.to_csv(fb, index=False, encoding="utf-8-sig")
                        print(f"[兜底] 采集指标已写入 CSV: {fb.resolve()}", file=sys.stderr)
                    except BaseException as e2:
                        print(f"[兜底] CSV 写入仍失败: {e2}", file=sys.stderr)
                    raise
                _maybe_write_compass_metrics_from_trial_rows(
                    tpl if isinstance(tpl, dict) else None,
                    data_rows,
                    args,
                    run_ts=run_ts,
                    yday=yday,
                    run_day=run_day,
                )
                print(f"已写入运行日志（CSV）: {run_log_csv}（共 {len(rows)} 行）")
                print(f"已写入采集数据（Excel）: {excel_out}（共 {len(data_rows)} 条指标）")
                if len(rows) > 0:
                    print("\n========== 仅切换店铺（分块测试）==========")
                    df = pd.DataFrame(rows)
                    with pd.option_context(
                        "display.max_columns", None, "display.width", 240, "display.max_colwidth", 120
                    ):
                        print(df.to_string(index=False))
                    print("==========================================\n")
                trial_checkpoint_clear()
                return 0

            global_consumed: set = set()
            gal = _parse_global_account_loop(tpl, args)
            if (
                gal
                and not getattr(args, "qianchuan_standalone", False)
                and not args.only_extract
                and not getattr(args, "only_date_range", False)
            ):
                chk_path: Optional[Path] = (
                    Path(getattr(args, "checkpoint"))
                    if getattr(args, "checkpoint", None)
                    else None
                )
                chk_resume = bool(getattr(args, "resume", False))
                resume_start_idx = 0
                resume_last_hint: Optional[str] = None
                if chk_path and chk_resume:
                    resume_start_idx, resume_last_hint = _checkpoint_resume_start_index(
                        chk_path,
                        True,
                        gal["accounts"],
                        gal["pageIds"],
                        page_id_allow,
                    )
                    _, chk_tpl, _ = _checkpoint_read_raw(chk_path)
                    cur_tpl = str(tpl_path.resolve())
                    if chk_tpl and chk_tpl != cur_tpl:
                        print(
                            f"[断点续跑] 警告: 断点内模板路径与当前不一致。\n"
                            f"  断点: {chk_tpl}\n"
                            f"  当前: {cur_tpl}",
                            file=sys.stderr,
                        )
                    if resume_start_idx > 0:
                        prev_n = gal["accounts"][resume_start_idx - 1]
                        nxt_n = gal["accounts"][resume_start_idx]
                        print(
                            f"[断点续跑] 上次整店完成的最后一家: {prev_n}；本次从「{nxt_n}」继续。",
                            file=sys.stderr,
                        )
                    elif resume_last_hint:
                        print(
                            "[断点续跑] 无「整店完成」记录或需从第一家开始。",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            "[断点续跑] 断点为空或无法推断，从第一家开始。",
                            file=sys.stderr,
                        )
                elif chk_path and not chk_resume:
                    print(
                        f"[断点] 已启用 --checkpoint {chk_path}，每整店成功完成后更新 lastCompletedAccount（不加 --resume 时不跳过店铺）。",
                        file=sys.stderr,
                    )

                pid_to_pg = pid_to_pg_registry
                synth_id = gal["anchorPageId"]
                synth_pg = {"id": synth_id, "accountSwitcher": gal["accountSwitcher"]}
                accounts_run = gal["accounts"][resume_start_idx:]
                gal_planned_pids = [
                    p
                    for p in gal["pageIds"]
                    if page_id_allow is None or p in page_id_allow
                ]
                n_accounts_run = len(accounts_run)
                for acct_i, acct in enumerate(accounts_run):
                    acct_fn = _sanitize_filename_prefix(acct)
                    with _timing_span(
                        args,
                        account=acct,
                        page_id="globalAccountLoop",
                        phase="global_loop",
                        step="goto_preSwitchUrl",
                        detail=str(gal.get("preSwitchUrl") or ""),
                    ):
                        if not _page_goto(
                            page,
                            gal["preSwitchUrl"],
                            page_id="globalAccountLoop",
                            acct=acct,
                            args=args,
                            rows=rows,
                        ):
                            continue
                    with _timing_span(
                        args,
                        account=acct,
                        page_id="globalAccountLoop",
                        phase="global_loop",
                        step="switch_account",
                        detail=str(synth_id),
                    ):
                        ok_sw, det_sw = _dispatch_account_switch(page, acct, synth_pg, synth_id)
                    rows.append(
                        _result_row(
                            page_id="globalAccountLoop",
                            phase="account",
                            key="switch",
                            action="switchAccount",
                            detail=det_sw,
                            ok=ok_sw,
                            account=acct,
                        )
                    )
                    if not ok_sw:
                        continue
                    account_pages_all_ok = True
                    for pid in gal["pageIds"]:
                        if page_id_allow is not None and pid not in page_id_allow:
                            continue
                        pg_inner = pid_to_pg.get(pid)
                        if not isinstance(pg_inner, dict):
                            rows.append(
                                _result_row(
                                    page_id=pid,
                                    phase="pipeline",
                                    key="pageIds",
                                    action="missing",
                                    detail=f"globalAccountLoop.pageIds 中不存在 {pid}",
                                    ok=False,
                                    account=acct,
                                )
                            )
                            account_pages_all_ok = False
                            continue
                        qc_ov: Any = _QC_SWITCH_OVERRIDE_UNSET
                        if pid == "qianchuan_home_cost_roi":
                            qcb = gal.get("qianchuanByAccount")
                            if isinstance(qcb, dict):
                                qc_ov = qcb.get(acct)

                        if pid == "qianchuan_home_cost_roi" and _qianchuan_retry_eligible(
                            gal, qc_ov
                        ):
                            with _timing_span(
                                args,
                                account=acct,
                                page_id=pid,
                                phase="page",
                                step="qianchuan_with_retries",
                                detail=str(qc_ov).strip()[:120],
                            ):
                                qc_ok = _run_qianchuan_page_with_retries(
                                    page,
                                    args,
                                    tpl,
                                    pid,
                                    acct,
                                    pg_inner,
                                    rows,
                                    download_dir,
                                    network_json_dir,
                                    yday,
                                    data_rows,
                                    acct_fn,
                                    str(qc_ov).strip(),
                                    selector_hints=selector_hints,
                                    template_hint_stem=template_hint_stem,
                                    hints_dirty=hints_dirty,
                                )
                            if not qc_ok:
                                account_pages_all_ok = False
                        else:
                            with _timing_span(
                                args,
                                account=acct,
                                page_id=pid,
                                phase="page",
                                step="template_page_pipeline",
                                detail="",
                            ):
                                tpl_ok = _template_page_goto_switch_play(
                                    page,
                                    args,
                                    tpl,
                                    pid,
                                    acct,
                                    pg_inner,
                                    rows,
                                    download_dir,
                                    network_json_dir,
                                    yday,
                                    data_rows,
                                    download_filename_prefix=acct_fn,
                                    qianchuan_switch_override=qc_ov,
                                    selector_hints=selector_hints,
                                    template_hint_stem=template_hint_stem,
                                    hints_dirty=hints_dirty,
                                )
                            if not tpl_ok:
                                account_pages_all_ok = False
                                continue
                    if account_pages_all_ok and chk_path and gal_planned_pids:
                        _checkpoint_write_last_completed_account(chk_path, tpl_path, acct)
                    if (
                        _page_ids_need_fundbill_only_shop_cooldown(page_id_allow)
                        and acct_i < n_accounts_run - 1
                    ):
                        print(
                            "[冷却] 当前为「登录/切换 + 资金账单生成 + 历史下载」三模块专选："
                            "本店流程已结束，50 秒后进入下一家店铺。",
                            file=sys.stderr,
                        )
                        time.sleep(50)
                global_consumed = set(gal["pageIds"])

            for pg in pages_cfg:
                if not isinstance(pg, dict):
                    continue
                pid = str(pg.get("id") or "unknown")
                if pid in global_consumed:
                    continue
                if global_consumed and bool(pg.get("skipStandaloneIfNotInGlobalPageIds")):
                    continue
                if page_id_allow is not None and pid not in page_id_allow:
                    continue
                url = str(pg.get("url") or "").strip()
                interactions = pg.get("interactions") or []
                fields = pg.get("fields") or []

                acct_list = _accounts_for_page(pg, args)
                if not acct_list:
                    acct_list = [""]

                for acct in acct_list:
                    pre_u = str(pg.get("preSwitchUrl") or "").strip()
                    main_u = url
                    nvc = bool(pg.get("navigateFromCurrent"))

                    if bool(pg.get("openInNewTab")):
                        with _timing_span(
                            args,
                            account=acct,
                            page_id=pid,
                            phase="page",
                            step="template_page_pipeline",
                            detail="openInNewTab",
                        ):
                            ok_nt = _template_page_goto_switch_play(
                                page,
                                args,
                                tpl,
                                pid,
                                acct,
                                pg,
                                rows,
                                download_dir,
                                network_json_dir,
                                yday,
                                data_rows,
                                download_filename_prefix=_sanitize_filename_prefix(acct),
                                selector_hints=selector_hints,
                                template_hint_stem=template_hint_stem,
                                hints_dirty=hints_dirty,
                            )
                        if not ok_nt:
                            continue
                        continue

                    if nvc:
                        if pre_u:
                            if not _page_goto_maybe(
                                page, pre_u, page_id=pid, acct=acct, args=args, rows=rows, pg=pg
                            ):
                                continue
                        if acct:
                            fxg_pg = pid_to_pg_registry.get("fxg_mshop_home")
                            if isinstance(fxg_pg, dict):
                                ok_f, det_f = _dispatch_account_switch(
                                    page, acct, fxg_pg, "fxg_mshop_home"
                                )
                                rows.append(
                                    _result_row(
                                        page_id=pid,
                                        phase="account",
                                        key="switch_before_navigateFromCurrent",
                                        action="switchAccount",
                                        detail=det_f,
                                        ok=ok_f,
                                        account=acct,
                                    )
                                )
                                if not ok_f:
                                    continue
                        with _timing_span(
                            args,
                            account=acct,
                            page_id=pid,
                            phase="page",
                            step="template_page_pipeline",
                            detail="navigateFromCurrent",
                        ):
                            ok_nvc = _template_page_goto_switch_play(
                                page,
                                args,
                                tpl,
                                pid,
                                acct,
                                pg,
                                rows,
                                download_dir,
                                network_json_dir,
                                yday,
                                data_rows,
                                download_filename_prefix=_sanitize_filename_prefix(acct),
                                selector_hints=selector_hints,
                                template_hint_stem=template_hint_stem,
                                hints_dirty=hints_dirty,
                            )
                        if not ok_nvc:
                            continue
                        continue

                    if acct and pre_u:
                        if not _page_goto_maybe(
                            page, pre_u, page_id=pid, acct=acct, args=args, rows=rows, pg=pg
                        ):
                            continue
                    elif main_u:
                        skip_qc_goto = bool(
                            getattr(args, "qianchuan_standalone", False)
                            and pid == "qianchuan_home_cost_roi"
                        )
                        if not skip_qc_goto:
                            if not _page_goto_maybe(
                                page, main_u, page_id=pid, acct=acct, args=args, rows=rows, pg=pg
                            ):
                                continue
                        else:
                            rows.append(
                                _result_row(
                                    page_id=pid,
                                    phase="nav",
                                    key="skip_initial_goto",
                                    action="use_current_tab",
                                    detail="千川单独模式：不执行 goto，沿用当前标签页 URL",
                                    ok=True,
                                    account=acct,
                                )
                            )

                    skip_sw = bool((pg or {}).get("skipAccountSwitch"))
                    if acct and not skip_sw:
                        ok_sw, det_sw = _dispatch_account_switch(page, acct, pg, pid)
                        rows.append(
                            _result_row(
                                page_id=pid,
                                phase="account",
                                key="switch",
                                action="switchAccount",
                                detail=det_sw,
                                ok=ok_sw,
                                account=acct,
                            )
                        )
                        if not ok_sw:
                            continue
                    elif acct and skip_sw:
                        rows.append(
                            _result_row(
                                page_id=pid,
                                phase="account",
                                key="switch",
                                action="skipAccountSwitch",
                                detail="页面配置 skipAccountSwitch=true，跳过 accountSwitcher",
                                ok=True,
                                account=acct,
                            )
                        )

                    if acct and pre_u and main_u and pre_u != main_u:
                        if not _page_goto_maybe(
                            page, main_u, page_id=pid, acct=acct, args=args, rows=rows, pg=pg
                        ):
                            continue

                    _apply_post_goto_wait(page, pg if isinstance(pg, dict) else {})
                    if isinstance(fields, list) and any(isinstance(f, dict) for f in fields):
                        _apply_pre_field_extract_wait(page, pg if isinstance(pg, dict) else {})
                    with _timing_span(
                        args,
                        account=acct,
                        page_id=pid,
                        phase="page",
                        step="interactions_and_fields",
                        detail="standalone_page",
                    ):
                        _play_interactions_and_fields(
                            page,
                            args,
                            tpl,
                            pid,
                            acct,
                            interactions,
                            fields,
                            rows,
                            download_dir,
                            network_json_dir,
                            yday,
                            data_rows=data_rows,
                            page_cfg=pg if isinstance(pg, dict) else None,
                            download_filename_prefix=_sanitize_filename_prefix(acct),
                            selector_hints=selector_hints,
                            template_hint_stem=template_hint_stem,
                            hints_dirty=hints_dirty,
                        )

        except TrialAbort:
            aborted = True
        except KeyboardInterrupt:
            interrupted = True
            print("\n已收到 Ctrl+C，正在断开 CDP 并写入日志…", file=sys.stderr)
        finally:
            try:
                browser.close()
            except BaseException:
                pass

    if (
        not getattr(args, "no_selector_hints", False)
        and selector_hints_path is not None
        and hints_dirty[0]
        and selector_hints is not None
    ):
        try:
            _save_selector_hints(selector_hints_path, selector_hints)
            print(f"已更新 field 选择器记忆: {selector_hints_path.resolve()}")
        except OSError as e:
            print(f"写入选择器记忆失败: {e}", file=sys.stderr)

    _maybe_write_timing_log(args, run_ts)
    try:
        _write_run_log_csv(run_log_csv, rows)
        _write_data_excel(excel_out, data_rows, tpl if isinstance(tpl, dict) else None)
    except KeyboardInterrupt:
        print("\n已收到 Ctrl+C（收尾写入），尝试保存 CSV 兜底…", file=sys.stderr)
        try:
            _write_run_log_csv(run_log_csv, rows)
        except BaseException:
            pass
        try:
            fb = excel_out.with_suffix(".csv")
            cols = ["店铺名", "键", "标签", "数据值"]
            df_fb = pd.DataFrame(data_rows).reindex(columns=cols) if data_rows else pd.DataFrame(columns=cols)
            df_fb.to_csv(fb, index=False, encoding="utf-8-sig")
            print(f"[兜底] 采集指标已写入 CSV: {fb.resolve()}", file=sys.stderr)
        except BaseException as e2:
            print(f"[兜底] CSV 写入仍失败: {e2}", file=sys.stderr)
        raise
    _maybe_write_compass_metrics_from_trial_rows(
        tpl if isinstance(tpl, dict) else None,
        data_rows,
        args,
        run_ts=run_ts,
        yday=yday,
        run_day=run_day,
    )
    print(f"已写入运行日志（CSV）: {run_log_csv}（共 {len(rows)} 行）")
    print(f"已写入采集数据（Excel）: {excel_out}（共 {len(data_rows)} 条指标）")
    print(f"下载目录（若有）: {download_dir}")
    if not interrupted and not aborted:
        _maybe_package_dailydate_cli_flag(
            tpl if isinstance(tpl, dict) else None,
            tpl_path,
            excel_out,
            download_dir,
            run_ts=run_ts,
            yday=yday,
            run_day=run_day,
            args=args,
            interrupted=interrupted,
            aborted=aborted,
        )
    _print_missing_step_summary(rows)
    if interrupted:
        print("用户中断（Ctrl+C），退出码 130。", file=sys.stderr)
    elif aborted:
        print("本次已因步骤失败中断，退出码 1（详见上方 stderr 块）。", file=sys.stderr)
    if getattr(args, "only_date_range", False) and len(rows) > 0:
        print("\n========== 仅 dateRange 步骤：运行日志 ==========")
        df = pd.DataFrame(rows)
        with pd.option_context("display.max_columns", None, "display.width", 240, "display.max_colwidth", 100):
            print(df.to_string(index=False))
        print("================================================\n")
    exit_code = 130 if interrupted else (1 if aborted else 0)
    trial_checkpoint_clear()
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="按模板 JSON 试运行：提取/点击下载/日期/下拉")
    parser.add_argument(
        "--template",
        type=Path,
        default=PROJECT_ROOT / "doc" / "scrape-template-jinritemai-v1.json",
        help="模板路径（含 pages、fields、interactions）",
    )
    parser.add_argument(
        "--cdp",
        "--cdp-url",
        dest="cdp",
        default="http://127.0.0.1:9222",
        help="Chrome CDP 地址（需与调试端口一致；--cdp-url 为同义写法）",
    )
    parser.add_argument(
        "--launch-chrome",
        action="store_true",
        help="可选：本机无调试端口时自动启动独立配置的 Chrome（需重新登录；日常请用已登录的调试 Chrome，不要加此参数）",
    )
    parser.add_argument(
        "--chrome-wait",
        type=float,
        default=15.0,
        help="自动启动 Chrome 后等待调试端口就绪的最长时间（秒）",
    )
    parser.add_argument("--goto-timeout-ms", type=int, default=90000, help="单页 goto 超时")
    parser.add_argument(
        "--pre-goto-wait-ms",
        type=int,
        default=0,
        help="每次 page.goto 之前额外等待（毫秒），缓解瞬时拥塞；0 表示不等待；上限 120000",
    )
    parser.add_argument(
        "--goto-retry-count",
        type=int,
        default=2,
        help="page.goto 失败后重试次数（不含首次），用于 net::ERR_FAILED 等；默认 2 即最多共 3 次；0 表示不重试",
    )
    parser.add_argument(
        "--goto-retry-wait-ms",
        type=int,
        default=1500,
        help="goto 失败后、再次尝试前的等待（毫秒）；默认 1500；上限 120000",
    )
    parser.add_argument(
        "--field-locator-timeout-ms",
        type=int,
        default=30000,
        help="fields 提取时等待元素出现/取文本的超时（毫秒）；默认 30000，千川等 SPA 偏慢可再加大",
    )
    parser.add_argument(
        "--post-interaction-wait-ms",
        type=int,
        default=2500,
        help="每页完成 interactions 后、读取 fields 前的等待（毫秒），便于接口返回后渲染数值",
    )
    parser.add_argument(
        "--post-date-range-wait-ms",
        type=int,
        default=5000,
        help="每次 dateRange 成功应用后额外等待（毫秒）；选日期会触发拉数，指标 .value 往往比「不选日期」晚出现",
    )
    parser.add_argument(
        "--date-range-container-timeout-ms",
        type=int,
        default=60000,
        help="dateRange 点击「日期容器」时首个选择器的可见超时（毫秒）；失败会自动换短备选选择器重试",
    )
    parser.add_argument(
        "--interaction-timeout-ms",
        type=int,
        default=30000,
        help="交互步骤等待元素可见/可点、selectFilter 容器、field 提取等的上限（毫秒）；0=不按此上限截断。默认 30000。",
    )
    parser.add_argument(
        "--download-timeout-ms",
        type=int,
        default=None,
        help="export 点击后 expect_download 超时上限（毫秒）；默认与 --interaction-timeout-ms 相同；0=不按上限截断",
    )
    parser.add_argument(
        "--abort-on-fail",
        dest="no_abort_on_fail",
        action="store_false",
        help="任一步失败即 stderr 详情并退出码 1（旧默认行为）",
    )
    parser.add_argument(
        "--no-abort-on-fail",
        dest="no_abort_on_fail",
        action="store_true",
        help="失败不中断（与默认一致，可省略）",
    )
    parser.set_defaults(no_abort_on_fail=True)
    parser.add_argument(
        "--excel-out",
        type=Path,
        default=None,
        help="采集数据 Excel（仅字段抽取成功：店铺名、键、标签、数据值）；默认 output/template_trial_时间戳.xlsx；"
        "若模板 runOutputSubdir 非空则默认 output/<subdir>/template_trial_时间戳.xlsx；"
        "若模板根含 aggregateExcelFileStem 则默认 output[/subdir]/{stem}_{运行当天YYYYMMDD}.xlsx；"
        "若模板含 downloadRoot 且未指定本参数，则与本次 run 的下载子目录（含 downloadRunSubdirTemplate）同级。"
        "与 --resume 同用且该路径已存在时，会先读入已有行再追加本次新指标后写回。",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=PROJECT_ROOT / "log",
        help="完整运行过程 CSV 日志目录；默认项目根目录下 log/",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "downloads",
        help="导出按钮触发下载时的保存目录",
    )
    parser.add_argument(
        "--network-json-dir",
        type=Path,
        default=None,
        help="networkResponseCapture 保存完整 JSON 的根目录；默认与本次解析后的浏览器下载目录相同。",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=None,
        metavar="DIR",
        help="统一模板产出根目录：runOutputSubdir、罗盘汇总相对路径、模板中以 output/ 开头的罗盘路径等均归此目录；"
        "显式传入的 --excel-out / --download-dir / --log-dir 仍以各自为准。",
    )
    parser.add_argument(
        "--only-extract",
        action="store_true",
        help="仅执行 fields 文本提取，跳过所有 interactions（先验证选择器是否仍能命中）",
    )
    parser.add_argument(
        "--only-date-range",
        action="store_true",
        help="仅执行 interactions 中的 dateRange（选时间），不读 fields；便于单独验证日期步骤",
    )
    parser.add_argument(
        "--only-account-switch",
        action="store_true",
        help="分块测试：只验证抖店首页切店（globalAccountLoop 的 preSwitchUrl + accountSwitcher + accounts），不跑 pageIds、不抽数",
    )
    parser.add_argument(
        "--page-ids",
        default="",
        metavar="ID,ID",
        help=(
            "只处理这些 page id（逗号分隔）；执行顺序仍按模板 globalAccountLoop.pageIds 原顺序，仅跳过未列入的 id。"
            "拼多多全店铺仅模块D：pdd_login_switch,pdd_aftersale_export；"
            "仅模块D+E（售后+对账）：pdd_login_switch,pdd_aftersale_export,pdd_cashier_bills_reconcile（须含登录页）。"
            "其他示例：qianchuan_home_cost_roi。默认处理模板中全部页。"
        ),
    )
    parser.add_argument(
        "--task-part",
        default="",
        metavar="A|B|C|D 或 A,D",
        help=(
            "按固定分块调试（等价 pageIds 过滤）："
            "A=fxg_mshop_home；"
            "B=fxg_aftersale_fund_detail_bill+fxg_bill_history_report；"
            "C=fxg_aftersale_order_list_export；"
            "D=qianchuan_home_cost_roi。"
            "支持逗号多选，如 --task-part A,D。"
            "不能与 --page-ids / --qianchuan-standalone 同时使用"
        ),
    )
    parser.add_argument(
        "--qianchuan-standalone",
        action="store_true",
        help="仅跑千川成本卡（qianchuan_home_cost_roi）：跳过抖店 globalAccountLoop；优先千川标签且不 goto 首页；请先手动打开并登录巨量千川",
    )
    parser.add_argument(
        "--accounts",
        default="",
        metavar="名称,名称",
        help="多账号页按顺序切换：逗号分隔名称，覆盖模板 runAccounts；支持千川/抖店首页/售后等业务页（见模板 page id）",
    )
    parser.add_argument(
        "--global-accounts",
        default="",
        metavar="名称,名称",
        help="覆盖模板 globalAccountLoop.accounts：每家店一轮——首页切店后按 pageIds 顺序跑采集/下载，再下一家",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        metavar="PATH",
        help="断点 JSON 路径：globalAccountLoop 下每成功完成一整页即写入（店铺名×page id）；中断后可配合 --resume 跳过已完成项",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="与 --checkpoint 合用：从断点文件读取已完成的（店铺×页面）并跳过；须与上次同一模板/店名列表意图一致",
    )
    parser.add_argument(
        "--selector-hints-file",
        type=Path,
        default=PROJECT_ROOT / "log" / "field_selector_hints.json",
        help="fields 抽取：按店铺记录「模板名::pageId::fieldKey::店铺名」，下次同店优先尝试",
    )
    parser.add_argument(
        "--no-selector-hints",
        action="store_true",
        help="不读、不写 field 选择器记忆（忽略 --selector-hints-file）",
    )
    parser.add_argument(
        "--no-auto-compass-metrics",
        action="store_true",
        help="跳过模板 aggregateExcelAutoCompassMetrics 触发的罗盘千川汇总表自动生成（仍写 template_trial*.xlsx）",
    )
    parser.add_argument(
        "--no-incremental-checkpoint",
        action="store_true",
        dest="no_incremental_checkpoint",
        help="关闭增量落盘：不在每条指标/每条运行日志后写 Excel/CSV（默认开启以降低中断丢失进度）",
    )
    parser.add_argument(
        "--package-dailydate-at-end",
        action="store_true",
        dest="package_dailydate_at_end",
        help="本次试运行成功结束后：复制采集表到 dailydate/、下载目录打 zip（与 Streamlit「客户交付」二选一，避免重复）",
    )
    parser.add_argument(
        "--package-dailydate-root",
        default="dailydate",
        help="配合 --package-dailydate-at-end：交付根目录（相对项目根或绝对路径），默认 dailydate",
    )
    parser.add_argument(
        "--package-dailydate-folder-pattern",
        default="{run_day}_{run_output_subdir}_{run_ts}",
        help="配合 --package-dailydate-at-end：交付文件夹名占位符模板",
    )
    parser.add_argument(
        "--package-dailydate-zip-pattern",
        default="网页导出等附件_{run_ts}",
        help="配合 --package-dailydate-at-end：附件 zip 主文件名模板（可不含 .zip）",
    )
    parser.add_argument(
        "--package-task-name",
        default="",
        help="配合 --package-dailydate-at-end：写入 README 的任务展示名",
    )
    parser.add_argument(
        "--package-task-slug",
        default="",
        help="配合 --package-dailydate-at-end：任务短标识（占位符 task_slug；默认可留空）",
    )
    parser.add_argument(
        "--package-dailydate-no-compass",
        action="store_true",
        help="配合 --package-dailydate-at-end：不尝试复制罗盘千川汇总表",
    )
    parser.add_argument(
        "--package-dailydate-no-readme",
        action="store_true",
        help="配合 --package-dailydate-at-end：不写 README_交付说明.txt",
    )
    parser.add_argument(
        "--timing-log",
        nargs="?",
        const=_TIMING_LOG_AUTO,
        default=None,
        metavar="PATH",
        help=(
            "写入逐步耗时 CSV（列：批次、账号、页面、阶段、步骤、说明、耗时_ms）；"
            "仅写 --timing-log 不传路径时默认为 log/template_trial_时间戳_timing.csv"
        ),
    )
    ns = parser.parse_args()
    raise SystemExit(run(ns))


if __name__ == "__main__":
    main()
