# -*- coding: utf-8 -*-
"""
本地采集控制台（Streamlit）
- 选择内置配置
- 选择模块（中文流程名 + page id）、账号包配置、实时日志
- 实时展示 run_template_trial 与后处理日志
"""

import json
import os
import shlex
import subprocess
import sys
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import threading
import traceback
import difflib
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 优先 doc：便于把控制台用的 JSON 与 doc 下 scrape 模板一起版本管理；不存在则回退 app
_BUILTIN_CONFIG_PATHS = (
    PROJECT_ROOT / "doc" / "config_registry" / "builtin_configs.json",
    PROJECT_ROOT / "app" / "config_registry" / "builtin_configs.json",
)
_CLIENTS_REGISTRY_PATHS = (
    PROJECT_ROOT / "doc" / "config_registry" / "clients.json",
    PROJECT_ROOT / "app" / "config_registry" / "clients.json",
)
ACCOUNT_CONFIG_DIR = PROJECT_ROOT / "app" / "account_configs"
PDD_ACCOUNT_PACK_DIR = PROJECT_ROOT / "doc" / "pdd-account-packs"
DOUYIN_ACCOUNT_PACK_DIR = PROJECT_ROOT / "doc" / "douyin-account-packs"
DEFAULT_PORT = 8502
# 本机已用 --remote-debugging-port=9222 启动 Chrome 时，与 run_template_trial 的 --cdp 一致
DEFAULT_CDP = "http://127.0.0.1:9222"


def _cdp_normalize_base(cdp: str) -> str:
    u = (cdp or "").strip().rstrip("/")
    if not u:
        u = DEFAULT_CDP
    if not u.startswith("http"):
        u = "http://" + u
    return u


def _cdp_loopback_port(cdp: str) -> Tuple[int, bool]:
    """Returns (port, host_is_loopback_ok_for_autolaunch)."""
    try:
        p = urllib.parse.urlsplit(_cdp_normalize_base(cdp))
        host = (p.hostname or "127.0.0.1").lower()
        loop_ok = host in ("127.0.0.1", "localhost", "::1")
        port = p.port if p.port is not None else 9222
        return int(port), loop_ok
    except Exception:
        return 9222, True


def _cdp_ping(cdp: str, timeout_sec: float = 2.0) -> bool:
    base = _cdp_normalize_base(cdp)
    url = base.rstrip("/") + "/json/version"
    try:
        resp = urllib.request.urlopen(url, timeout=timeout_sec)
        try:
            code = getattr(resp, "status", None) or resp.getcode()
            return code == 200
        finally:
            resp.close()
    except Exception:
        return False


def ensure_cdp_chrome(cdp: str) -> Tuple[bool, Optional[str]]:
    """若指定 CDP 不可访问：在 Windows 上尝试启动 Launch-ChromeCdp.ps1；返回 (是否可用, 提示文案)。"""
    base = _cdp_normalize_base(cdp)
    if _cdp_ping(base):
        return True, None

    port, loop_ok = _cdp_loopback_port(base)
    if sys.platform != "win32":
        return False, f"无法连接 CDP `{base}`，且当前平台不会自动拉起 Chrome。"
    if not loop_ok:
        return (
            False,
            f"无法连接 CDP `{base}`（仅支持对本机 127.0.0.1 / localhost 自动启动 Chrome）。",
        )

    ps = PROJECT_ROOT / "scripts" / "Launch-ChromeCdp.ps1"
    if not ps.is_file():
        return False, f"找不到 {ps.name}，无法自动启动 Chrome。"

    try:
        run_env = dict(os.environ)
        run_env.update(_child_process_env())
        run_kw: Dict[str, object] = {
            "cwd": str(PROJECT_ROOT),
            "capture_output": True,
            "text": True,
            "timeout": 120,
            "env": run_env,
        }
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            run_kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[assignment]
        cp = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps),
                "-Mode",
                "Test",
                "-Port",
                str(port),
            ],
            **run_kw,
        )
        if cp.returncode != 0:
            tail = ((cp.stderr or "") + "\n" + (cp.stdout or "")).strip()[-800:]
            return False, f"启动 Chrome CDP 失败（exit {cp.returncode}）：{tail}"
    except subprocess.TimeoutExpired:
        return False, "启动 Chrome CDP 超时。"
    except Exception as e:
        return False, f"启动 Chrome CDP 异常：{e}"

    time.sleep(3.0)
    for _ in range(10):
        if _cdp_ping(base, timeout_sec=2.0):
            return (
                True,
                f"已自动启动 CDP Chrome（端口 {port}）。请在新窗口中登录店铺后再继续采集。",
            )
        time.sleep(1.0)

    return (
        False,
        f"已尝试启动 Chrome，但 `{base}/json/version` 仍不可访问；请关闭其它 Chrome 实例后重试，或手动运行 scripts/Launch-ChromeCdp.ps1。",
    )


def _normalize_child_cmd(cmd: List[str]) -> List[str]:
    """离线 conda_env 解压部署时，系统 PATH 里可能没有 python；子进程改用当前解释器。"""
    if not cmd:
        return cmd
    out = list(cmd)
    head = str(out[0]).strip().lower()
    if head in ("python", "python3"):
        out[0] = sys.executable
    return out


def _child_process_env() -> Dict[str, str]:
    """供 Popen 使用的环境：在 Windows 上强制子进程 Python 向管道输出 UTF-8。

    否则控制台默认 ANSI（如 GBK）与 Streamlit 按 UTF-8 解码 stdout 不一致，日志会乱码。
    """
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _inject_compact_ops_theme() -> None:
    """窄幅居中、收紧留白与日志字号；不改变控件 key 与业务逻辑。"""
    st.markdown(
        """
<style>
    .main .block-container {
        padding-top: 0.55rem !important;
        padding-bottom: 0.85rem !important;
        max-width: 48rem !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }
    .ops-hero {
        margin-bottom: 0.55rem;
        padding-bottom: 0.45rem;
        border-bottom: 1px solid #e5e7eb;
    }
    .ops-hero-title {
        font-size: 1.28rem;
        font-weight: 650;
        letter-spacing: -0.03em;
        color: #0f172a;
        line-height: 1.2;
        margin: 0;
    }
    .ops-hero-sub {
        font-size: 0.76rem;
        color: #64748b;
        margin: 0.28rem 0 0 0;
        line-height: 1.35;
    }
    .ops-h {
        font-size: 0.65rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: #64748b;
        margin: 0.65rem 0 0.25rem 0;
        padding: 0;
    }
    .ops-hint {
        font-size: 0.72rem;
        color: #64748b;
        line-height: 1.45;
        margin: 0.2rem 0 0.35rem 0;
        padding: 0.35rem 0.5rem;
        background: #f8fafc;
        border-radius: 6px;
        border: 1px solid #f1f5f9;
    }
    .ops-foot {
        font-size: 0.7rem;
        color: #94a3b8;
        margin-top: 0.85rem;
    }
    [data-testid="stCodeBlock"] {
        max-height: min(38vh, 280px) !important;
        overflow-y: auto !important;
    }
    [data-testid="stCodeBlock"] code,
    [data-testid="stCodeBlock"] pre {
        font-size: 0.72rem !important;
        line-height: 1.38 !important;
    }
    div[data-testid="stExpander"] summary {
        font-size: 0.8rem !important;
    }
</style>
""",
        unsafe_allow_html=True,
    )


def _ops_section(title: str) -> None:
    st.markdown(f'<p class="ops-h">{title}</p>', unsafe_allow_html=True)


# 预约运行：可排队多个触发时刻；每笔须在「当前时间 + N 小时」之内（便于周末前预排下周）
SCHEDULE_MAX_HOURS = 24 * 14


def _sch_queues() -> Dict[str, Any]:
    raw = st.session_state.setdefault("sch_queues", {})
    if not isinstance(raw, dict):
        raw = {}
        st.session_state["sch_queues"] = raw
    return raw


def _sch_queue_for(cfg_id: str) -> List[datetime]:
    qm = _sch_queues()
    raw = qm.get(cfg_id)
    if not isinstance(raw, list):
        raw = []
    cleaned: List[datetime] = []
    for x in raw:
        if isinstance(x, datetime):
            cleaned.append(x.replace(microsecond=0))
    cleaned.sort()
    qm[str(cfg_id)] = cleaned
    return cleaned


def _sch_enqueue(cfg_id: str, fire_at: datetime) -> Tuple[bool, str]:
    now = datetime.now()
    horizon = now + timedelta(hours=SCHEDULE_MAX_HOURS)
    at = fire_at.replace(microsecond=0)
    if at <= now:
        return False, "请选择晚于当前时间的日期时刻。"
    if at > horizon:
        return False, f"单笔预约须在 {SCHEDULE_MAX_HOURS // 24} 天内，不晚于 {horizon:%Y-%m-%d %H:%M}。"
    lst = _sch_queue_for(cfg_id)
    if any(x == at for x in lst):
        return False, "该时刻已在队列中。"
    lst.append(at)
    lst.sort()
    return True, f"已加入：**{at:%Y-%m-%d %H:%M}**"


def _sch_remove_fire_at(cfg_id: str, fire_at: datetime) -> None:
    lst = _sch_queue_for(cfg_id)
    qm = _sch_queues()
    kept = [x for x in lst if x != fire_at.replace(microsecond=0)]
    if kept:
        qm[str(cfg_id)] = kept
    else:
        qm.pop(str(cfg_id), None)


def _sch_clear_queue(cfg_id: str) -> None:
    qm = _sch_queues()
    qm.pop(str(cfg_id), None)


def _sch_migrate_legacy_schedule(cfg_id: str) -> None:
    """旧版单条 schedule_cfg → 并入队列（展开预约区时执行一次）。"""
    legacy = st.session_state.get("schedule_cfg")
    if not isinstance(legacy, dict) or legacy.get("_sch_legacy_consumed"):
        return
    if not legacy.get("enabled") or legacy.get("mode") != "delay_once":
        st.session_state["schedule_cfg"] = {"enabled": False, "mode": "off", "_sch_legacy_consumed": True}
        return
    fa = legacy.get("fire_at")
    if isinstance(fa, datetime):
        _sch_enqueue(cfg_id, fa)
    st.session_state["schedule_cfg"] = {"enabled": False, "mode": "off", "_sch_legacy_consumed": True}


def _first_existing_path(paths: Tuple[Path, ...]) -> Optional[Path]:
    for p in paths:
        if p.is_file():
            return p
    return None


def _load_builtin_configs() -> List[dict]:
    p = _first_existing_path(_BUILTIN_CONFIG_PATHS)
    if not p:
        return []
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _load_clients() -> List[dict]:
    """客户登记：优先 doc/config_registry/clients.json，否则 app/config_registry/clients.json。"""
    p = _first_existing_path(_CLIENTS_REGISTRY_PATHS)
    if not p:
        return [{"id": "", "name": "未指定客户", "slug": "", "note": ""}]
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            out = [x for x in raw if isinstance(x, dict)]
            # 按 id 去重，避免下拉出现重复「未指定客户」等
            seen: set = set()
            dedup: List[dict] = []
            for x in out:
                kid = str(x.get("id", "")).strip()
                if kid in seen:
                    continue
                seen.add(kid)
                dedup.append(x)
            out = dedup
            return out if out else [{"id": "", "name": "未指定客户", "slug": "", "note": ""}]
    except Exception:
        pass
    return [{"id": "", "name": "未指定客户", "slug": "", "note": ""}]


def _builtin_dataset_options(
    cfg: dict,
    builtin: List[Tuple[str, str]],
    default_field: str,
) -> Tuple[List[str], List[str], int]:
    task_bound = str(cfg.get(default_field) or "").strip().replace("\\", "/")
    labels: List[str] = []
    vals: List[str] = []
    default_idx = 0
    for rel, title in builtin:
        rel_n = str(rel or "").strip().replace("\\", "/")
        if not rel_n or not (PROJECT_ROOT / rel_n).is_file():
            continue
        mark = "【本任务默认】 " if task_bound == rel_n else ""
        labels.append(f"{mark}{title}")
        vals.append(rel_n)
        if task_bound == rel_n:
            default_idx = len(vals) - 1
    return labels, vals, default_idx


def _normalize_presets(cfg: dict) -> List[dict]:
    raw = cfg.get("presets")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _load_json_template(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _discover_template_files() -> List[str]:
    files = sorted(PROJECT_ROOT.glob("doc/scrape-template-*.json"))
    return [str(p.relative_to(PROJECT_ROOT)).replace("\\", "/") for p in files]


def _resolve_template_rel(cfg: dict, template_options: List[str]) -> Tuple[str, Optional[str]]:
    configured = str(cfg.get("template") or "").strip().replace("\\", "/")
    if configured and configured in template_options:
        return configured, None
    if not template_options:
        return configured, None

    wanted_name = Path(configured).name if configured else ""
    candidate_name_to_rel = {Path(x).name: x for x in template_options}
    fallback = ""
    if wanted_name:
        m = difflib.get_close_matches(wanted_name, list(candidate_name_to_rel.keys()), n=1, cutoff=0.45)
        if m:
            fallback = candidate_name_to_rel[m[0]]
    if not fallback:
        low = configured.lower()
        if "jinritemai" in low:
            for x in template_options:
                if "jinritemai" in x.lower():
                    fallback = x
                    break
        elif "pdd" in low:
            for x in template_options:
                if "pdd" in x.lower():
                    fallback = x
                    break
    if not fallback:
        fallback = template_options[0]
    note = (
        f"配置中的模板不存在：`{configured}`，已自动切换为项目现有模板：`{fallback}`。"
        if configured
        else f"未配置模板，已默认使用：`{fallback}`。"
    )
    return fallback, note


# 控制台展示用短中文（模板 pages 里有的 id 仍可被 description 补充，见 _label_for_page_id）
_PAGE_ID_CN_FALLBACK: Dict[str, str] = {
    # 抖店生态常见 page id
    "fxg_login_switch": "登录 / 切换店铺（入口页）",
    "fxg_mshop_home": "罗盘 · 店铺经营概况",
    "fxg_aftersale_fund_detail_bill": "资金账单全流程 · ① 生成报表",
    "fxg_bill_history_report": "资金账单全流程 · ② 历史报表下载",
    "fxg_aftersale_order_list_export": "售后工作台 · 订单导出",
    "qianchuan_home_cost_roi": "巨量千川 · 推广成本 / ROI",
    # 拼多多（全店模板常见）
    "pdd_login_switch": "拼多多 · 登录 / 切店",
    "pdd_trade_data_operation": "拼多多 · 交易/经营数据",
    "pdd_promotion_overview": "拼多多 · 推广概况",
    "pdd_aftersale_export": "拼多多 · 售后单导出",
    "pdd_cashier_bills_reconcile": "拼多多 · 资金账单对账",
}


def _desc_to_short_label(desc: str, max_len: int = 40) -> str:
    s = (desc or "").strip().replace("\n", " ")
    if not s:
        return ""
    for sep in ("。", "；", ";"):
        if sep in s[:120]:
            chunk = s.split(sep)[0].strip()
            if len(chunk) >= 6:
                return (chunk[:max_len] + "…") if len(chunk) > max_len else chunk
    return (s[:max_len] + "…") if len(s) > max_len else s


def _label_for_page_id(page_id: str, tpl: dict) -> str:
    pid = str(page_id or "").strip()
    if not pid:
        return ""
    if pid in _PAGE_ID_CN_FALLBACK:
        return _PAGE_ID_CN_FALLBACK[pid]
    pages = tpl.get("pages") if isinstance(tpl.get("pages"), list) else []
    for pg in pages:
        if not isinstance(pg, dict):
            continue
        if str(pg.get("id") or "").strip() != pid:
            continue
        desc = str(pg.get("description") or "").strip()
        if desc:
            return _desc_to_short_label(desc)
        break
    return pid


def _format_module_choice(page_id: str, tpl: dict) -> str:
    pid = str(page_id or "").strip()
    return f"{_label_for_page_id(pid, tpl)} （{pid}）"


def _preset_short_label(preset: Optional[dict]) -> str:
    """预设下拉短文案；模块明细仅用下方多选标签展示。"""
    if preset is None:
        return "自选（仅用下方模块标签）"
    return str(preset.get("label") or preset.get("id") or "?")


def _effective_module_page_ids(cfg: dict, tpl: dict) -> List[str]:
    """
    与本次任务模板 globalAccountLoop.pageIds 对齐（顺序一致）；builtin 中多出的 page id（如独立登录页）
    排在末尾，避免控制台可选模块与真实轮次顺序脱节。
    """
    gal = tpl.get("globalAccountLoop") if isinstance(tpl.get("globalAccountLoop"), dict) else {}
    raw = gal.get("pageIds")
    cfg_mod = [str(x).strip() for x in (cfg.get("module_page_ids") or []) if str(x).strip()]
    if isinstance(raw, list) and raw:
        gal_ids = [str(x).strip() for x in raw if str(x).strip()]
        seen = set(gal_ids)
        extra = [x for x in cfg_mod if x not in seen]
        return gal_ids + extra
    return cfg_mod


def _cfg_with_template_modules(cfg: dict, tpl: dict) -> dict:
    mods = _effective_module_page_ids(cfg, tpl)
    out = dict(cfg)
    if not mods:
        return out
    out["module_page_ids"] = mods
    od = cfg.get("default_page_ids") or cfg.get("module_page_ids") or []
    od_set = {str(x).strip() for x in od if str(x).strip()}
    out["default_page_ids"] = [x for x in mods if x in od_set] or list(mods)
    return out


def _resolve_preset_page_ids(cfg: dict, preset: Optional[dict]) -> Tuple[List[str], List[str]]:
    """
    解析预设的运行模块。
    返回 (page_ids, warnings)；warnings 为空表示无告警。
    """
    modules = [str(x).strip() for x in (cfg.get("module_page_ids") or []) if str(x).strip()]
    default_mods = cfg.get("default_page_ids")
    if isinstance(default_mods, list) and default_mods:
        defaults = [str(x).strip() for x in default_mods if str(x).strip()]
    else:
        defaults = list(modules)
    warns: List[str] = []
    if not preset:
        return list(defaults), warns
    scope = str(preset.get("run_scope") or "default").strip().lower()
    if scope == "all":
        return list(modules), warns
    if scope == "default":
        return list(defaults), warns
    raw_ids = preset.get("page_ids")
    if not isinstance(raw_ids, list):
        return list(defaults), warns
    ids = [str(x).strip() for x in raw_ids if str(x).strip()]
    known = set(modules)
    ok = [x for x in ids if x in known]
    unk = [x for x in ids if x not in known]
    if unk:
        warns.append(f"预设中含未在本任务中出现的 page id（已忽略）：{', '.join(unk)}")
    return (ok if ok else list(defaults)), warns


def _flatten_dynamic_for_subst(values: Dict[str, object]) -> Dict[str, str]:
    return {
        k: (",".join(str(x) for x in v) if isinstance(v, list) else str(v))
        for k, v in values.items()
    }


def _merge_substitution_vals(
    dynamic_values: Dict[str, object],
    *,
    task_display_name: str,
    task_slug: str,
    client_id: str,
    client_name: str,
) -> Dict[str, str]:
    """后处理 / 交付命令占位符替换用。"""
    out = _flatten_dynamic_for_subst(dynamic_values)
    out["task_display_name"] = task_display_name
    out["task_slug"] = task_slug
    out["client_id"] = client_id
    out["client_name"] = client_name
    return out


def _load_account_profiles() -> List[dict]:
    out: List[dict] = []
    if not ACCOUNT_CONFIG_DIR.is_dir():
        return out
    for p in sorted(ACCOUNT_CONFIG_DIR.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if not isinstance(obj, dict):
                continue
            obj["_file"] = str(p)
            out.append(obj)
        except Exception:
            continue
    return out


def _save_account_profile_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _read_text_fallback(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _save_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _pack_label_from_json(path: Path, fallback: str) -> str:
    """账号包展示名：优先读取 JSON 顶层 label，否则回退到文件名。"""
    try:
        obj = json.loads(_read_text_fallback(path))
        if isinstance(obj, dict):
            lb = str(obj.get("label") or "").strip()
            if lb:
                return lb
    except Exception:
        pass
    return fallback


def _safe_name_part(s: str) -> str:
    bad = '<>:"/\\|?*'
    t = (s or "").strip()
    for ch in bad:
        t = t.replace(ch, "_")
    return t[:80]


def _patch_template_account_csv(template_path: Path, account_csv: str) -> Path:
    """可选：把 accountCredentialCsv 覆盖到临时模板，避免改原文件。"""
    with open(template_path, "r", encoding="utf-8") as f:
        tpl = json.load(f)
    tpl["accountCredentialCsv"] = account_csv
    td = Path(tempfile.mkdtemp(prefix="streamlit_tpl_"))
    out = td / template_path.name
    with open(out, "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=2)
    return out


def _template_is_jinritemai(cfg: dict) -> bool:
    t = str(cfg.get("template") or "").replace("\\", "/").lower()
    return "jinritemai" in t


def _template_is_pdd(cfg: dict) -> bool:
    t = str(cfg.get("template") or "").replace("\\", "/").lower()
    return "scrape-template-pdd" in t or "/pdd-" in t


def _normalize_account_pack_root(obj: Any) -> dict:
    """拼多多/抖音共用账号包 JSON：顶层 label + profiles.<key> → 账号数组。"""
    if not isinstance(obj, dict):
        return {"label": "", "profiles": {}}
    out = dict(obj)
    out.setdefault("label", "")
    prof = out.get("profiles")
    if not isinstance(prof, dict):
        out["profiles"] = {}
    else:
        out["profiles"] = dict(prof)
    return out


def _pdd_rows_to_df(rows: Any) -> pd.DataFrame:
    if not isinstance(rows, list):
        rows = []
    rec: List[Dict[str, str]] = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        rec.append(
            {
                "店铺名": str(x.get("name") or ""),
                "登录账号": str(x.get("username") or ""),
                "密码": str(x.get("password") or ""),
            }
        )
    cols = ["店铺名", "登录账号", "密码"]
    return pd.DataFrame(rec, columns=cols)


def _df_to_pdd_rows(df: pd.DataFrame) -> List[dict]:
    rows_out: List[dict] = []
    if df is None or getattr(df, "empty", False):
        return rows_out
    for _, r in df.iterrows():
        name = str(r.get("店铺名") or "").strip()
        user = str(r.get("登录账号") or "").strip()
        pwd = str(r.get("密码") or "").strip()
        if not name and not user and not pwd:
            continue
        rows_out.append({"name": name, "username": user, "password": pwd})
    return rows_out


def _douyin_rows_to_df(rows: Any) -> pd.DataFrame:
    if not isinstance(rows, list):
        rows = []
    rec: List[Dict[str, str]] = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        qcid = x.get("千川ID")
        if qcid is None or qcid == "":
            qcid = x.get("qianchuanId")
        rec.append(
            {
                "店铺名": str(x.get("name") or ""),
                "shopId": str(x.get("shopId") or ""),
                "千川ID": "" if qcid is None else str(qcid),
            }
        )
    cols = ["店铺名", "shopId", "千川ID"]
    return pd.DataFrame(rec, columns=cols)


def _cell_plain_str(val: Any) -> str:
    """表格单元格可能是 float（如 shopId），保存为不带小数点的字符串。"""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except Exception:
        pass
    if isinstance(val, float):
        if abs(val - round(val)) < 1e-9:
            return str(int(round(val)))
        return str(val).strip()
    return str(val).strip()


def _df_to_douyin_rows(df: pd.DataFrame) -> List[dict]:
    rows_out: List[dict] = []
    if df is None or getattr(df, "empty", False):
        return rows_out
    for _, r in df.iterrows():
        name = _cell_plain_str(r.get("店铺名"))
        sid = _cell_plain_str(r.get("shopId"))
        qcid = _cell_plain_str(r.get("千川ID"))
        if not name and not sid:
            continue
        obj: Dict[str, Any] = {"name": name, "shopId": sid}
        if qcid:
            obj["千川ID"] = qcid
        rows_out.append(obj)
    return rows_out


def _pdd_password_column_config() -> Any:
    """新版 Streamlit 支持 PasswordColumn；旧版无该属性时退回 TextColumn。"""
    PC = getattr(st.column_config, "PasswordColumn", None)
    if PC is not None and callable(PC):
        return PC("密码", help="不会在页面上明文显示；保存仍为 JSON")
    return st.column_config.TextColumn(
        "密码",
        help="当前 Streamlit 版本较旧，以文本列编辑密码；请勿截屏外传，建议升级 streamlit（如 ≥1.33）。",
    )


def _pdd_credential_csv_entries() -> List[Tuple[str, str]]:
    """拼多多账号包：优先读取 doc/pdd-account-packs/*.json，兼容旧路径。"""
    out: List[Tuple[str, str]] = []
    seen: set = set()
    if PDD_ACCOUNT_PACK_DIR.is_dir():
        for p in sorted(PDD_ACCOUNT_PACK_DIR.glob("*.json")):
            rel = str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
            seen.add(rel)
            label = _pack_label_from_json(p, p.stem)
            out.append((rel, f"账号包 · {label}"))
    legacy_rel = "doc/pdd-accounts.json"
    if legacy_rel not in seen and (PROJECT_ROOT / legacy_rel).is_file():
        out.append((legacy_rel, "主档店铺账号（旧路径）"))
    return out


def _pdd_credential_csv_select(cfg: dict) -> Tuple[List[str], List[str], int]:
    return _builtin_dataset_options(cfg, _pdd_credential_csv_entries(), "pdd_credential_csv")


def _douyin_account_pack_entries() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    if DOUYIN_ACCOUNT_PACK_DIR.is_dir():
        for p in sorted(DOUYIN_ACCOUNT_PACK_DIR.glob("*.json")):
            rel = str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
            label = _pack_label_from_json(p, p.stem)
            out.append((rel, f"账号包 · {label}"))
    return out


def _jinritemai_customer_pack_select(cfg: dict) -> Tuple[List[str], List[str], int]:
    """抖店：必选其一（相对路径写入模板覆盖），默认由 builtin 绑定。"""
    return _builtin_dataset_options(cfg, _douyin_account_pack_entries(), "jinritemai_account_pack")


def _patch_template_global_accounts(
    template_path: Path,
    accounts_config_file: str,
    accounts_profile: str = "default",
) -> Path:
    """可选：覆盖 globalAccountLoop.accountsConfigFile / accountsProfile（抖店账号包 JSON）。"""
    with open(template_path, "r", encoding="utf-8") as f:
        tpl = json.load(f)
    gal = tpl.get("globalAccountLoop")
    if not isinstance(gal, dict):
        gal = {}
        tpl["globalAccountLoop"] = gal
    gal["accountsConfigFile"] = accounts_config_file.strip().replace("\\", "/")
    gal["accountsProfile"] = (accounts_profile or "default").strip() or "default"
    td = Path(tempfile.mkdtemp(prefix="streamlit_tpl_"))
    out = td / template_path.name
    with open(out, "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=2)
    return out


def _patch_template_pdd_account_pack(
    template_path: Path,
    account_pack_file: str,
) -> Path:
    """可选：覆盖拼多多账号包 JSON 路径（accountCredentialsFile）。"""
    with open(template_path, "r", encoding="utf-8") as f:
        tpl = json.load(f)
    tpl["accountCredentialsFile"] = account_pack_file.strip().replace("\\", "/")
    td = Path(tempfile.mkdtemp(prefix="streamlit_tpl_"))
    out = td / template_path.name
    with open(out, "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=2)
    return out


def _build_trial_command(
    *,
    template: Path,
    cdp: str,
    page_ids: List[str],
    download_dir: str,
    excel_out: str,
    log_dir: str,
    network_json_dir: str,
    run_root: str,
    abort_on_fail: bool,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    cmd = [
        sys.executable,
        "scripts/run_template_trial.py",
        "--template",
        str(template),
        "--cdp",
        cdp.strip(),
        "--download-dir",
        download_dir.strip(),
    ]
    if page_ids:
        cmd.extend(["--page-ids", ",".join(page_ids)])
    if excel_out.strip():
        cmd.extend(["--excel-out", excel_out.strip()])
    if (log_dir or "").strip():
        cmd.extend(["--log-dir", log_dir.strip()])
    if (network_json_dir or "").strip():
        cmd.extend(["--network-json-dir", network_json_dir.strip()])
    if (run_root or "").strip():
        cmd.extend(["--run-root", run_root.strip()])
    cmd.append("--abort-on-fail" if abort_on_fail else "--no-abort-on-fail")
    if extra_args:
        cmd.extend([str(x) for x in extra_args if str(x).strip()])
    return cmd


def _init_pipeline_holder() -> dict:
    return {
        "status": "running",
        "phase": "",
        "lines": [],
        "current_proc": None,
        "cancel_requested": False,
        "_lock": threading.Lock(),
    }


def _run_subprocess_stream_to_holder(
    holder: dict,
    cmd: List[str],
    cwd: Path,
    phase_title: str,
) -> int:
    lines: List[str] = holder.setdefault("lines", [])
    lock: Optional[threading.Lock] = holder.get("_lock")
    holder["phase"] = phase_title
    proc = subprocess.Popen(
        _normalize_child_cmd(cmd),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=_child_process_env(),
    )
    holder["current_proc"] = proc
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if holder.get("cancel_requested"):
                proc.terminate()
                break
            s = line.rstrip("\n")
            row = f"【{phase_title}】 {s}"
            if lock:
                with lock:
                    lines.append(row)
            else:
                lines.append(row)
        code = proc.wait()
        return int(code) if code is not None else -1
    finally:
        holder["current_proc"] = None


def _run_blocking_command_ui(cmd: List[str], cwd: Path, log_placeholder: object) -> int:
    """在页面内阻塞执行子进程，并把 stdout/stderr 流式写入「运行窗口」。"""
    cmd_n = _normalize_child_cmd(cmd)
    lines: List[str] = ["$ " + " ".join(shlex.quote(x) for x in cmd_n), ""]
    proc = subprocess.Popen(
        cmd_n,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=_child_process_env(),
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))
        log_placeholder.code("\n".join(lines[-500:]) or "(无输出)")
    code = proc.wait()
    return int(code) if code is not None else -1


def _apply_pdd_postprocess_subcommand(cmd: List[str], sub: str) -> List[str]:
    """将 process_pdd_data.py 后的子命令（all/part1/part2）替换为所选值。"""
    out = list(cmd)
    sub = (sub or "all").strip()
    for i, p in enumerate(out):
        ps = str(p).replace("\\", "/")
        if ps.endswith("scripts/process_pdd_data.py") or ps.endswith("process_pdd_data.py"):
            if i + 1 < len(out):
                out[i + 1] = sub
            break
    return out


def _override_cli_arg_after_flag(cmd: List[str], flag: str, new_value: str) -> List[str]:
    """将命令行中某 flag 后的第一个参数替换为 new_value（如 --input-dir、--excel）。"""
    out = list(cmd)
    fs = (flag or "").strip()
    nv = (new_value or "").strip()
    if not fs:
        return out
    for i, x in enumerate(out):
        if str(x).strip() == fs and i + 1 < len(out):
            out[i + 1] = nv
            break
    return out


def _compile_pipeline_job(
    *,
    template_path: Path,
    cfg: dict,
    jinritemai_pack_rel: Optional[str],
    pdd_account_pack_rel: Optional[str],
    account_csv: str,
    selected_profile: Optional[dict],
    selected_shop_names: Optional[List[str]],
    cdp: str,
    selected_modules: List[str],
    download_dir: str,
    excel_out: str,
    log_dir: str,
    network_json_dir: str,
    run_root: str,
    trial_extra_args: List[str],
    post_extra_args: List[str],
    subst_vals: Dict[str, str],
    abort_on_fail: bool,
) -> Tuple[Optional[str], dict]:
    warnings: List[str] = []
    try:
        tpl_to_use = Path(template_path)
        if jinritemai_pack_rel:
            tpl_to_use = _patch_template_global_accounts(tpl_to_use, jinritemai_pack_rel, "default")
            warnings.append(f"已覆盖抖店账号包：{jinritemai_pack_rel} → {tpl_to_use}")
        if pdd_account_pack_rel:
            tpl_to_use = _patch_template_pdd_account_pack(tpl_to_use, pdd_account_pack_rel)
            warnings.append(f"已覆盖拼多多账号包：{pdd_account_pack_rel} → {tpl_to_use}")
        if account_csv.strip():
            tpl_to_use = _patch_template_account_csv(Path(tpl_to_use), account_csv.strip())
            warnings.append(f"已使用临时模板覆盖 accountCredentialCsv：{tpl_to_use}")

        cmd_trial = _build_trial_command(
            template=tpl_to_use,
            cdp=cdp,
            page_ids=selected_modules,
            download_dir=download_dir,
            excel_out=excel_out,
            log_dir=log_dir,
            network_json_dir=network_json_dir,
            run_root=run_root,
            abort_on_fail=abort_on_fail,
            extra_args=trial_extra_args,
        )
        picked_names = [
            str(x).strip()
            for x in (selected_shop_names or [])
            if str(x).strip()
        ]
        if picked_names:
            cmd_trial.extend(["--global-accounts", ",".join(picked_names)])
            warnings.append(f"已按界面选择注入店铺：{len(picked_names)} 家")
        if (not _template_is_pdd(cfg)) and selected_profile and isinstance(selected_profile.get("accounts"), list):
            names = [
                str(x.get("name") or "").strip()
                for x in selected_profile.get("accounts")
                if isinstance(x, dict)
            ]
            names = [x for x in names if x]
            if names:
                cmd_trial.extend(["--global-accounts", ",".join(names)])
                warnings.append(f"已从用户配置文件注入店铺账号：{len(names)} 家")

        job = {
            "cmd_trial": cmd_trial,
            "cfg": cfg,
            "excel_out": excel_out,
            "download_dir": download_dir,
            "log_dir": log_dir,
            "network_json_dir": network_json_dir,
            "run_root": run_root,
            "subst_vals": subst_vals,
            "post_extra_args": post_extra_args,
            "tpl_resolved_path": str(Path(tpl_to_use).resolve()),
            "warnings": warnings,
        }
        return None, job
    except Exception as e:
        return str(e), {}


def _pipeline_worker(holder: dict, job: dict) -> None:
    lines = holder.setdefault("lines", [])
    lock: Optional[threading.Lock] = holder.get("_lock")

    def append_row(msg: str) -> None:
        if lock:
            with lock:
                lines.append(msg)
        else:
            lines.append(msg)

    try:
        holder["status"] = "running"
        holder["cancel_requested"] = False
        for w in job.get("warnings") or []:
            append_row(f"【提示】 {w}")

        append_row("【提示】 " + " ".join(shlex.quote(x) for x in job["cmd_trial"]))
        code1 = _run_subprocess_stream_to_holder(holder, job["cmd_trial"], PROJECT_ROOT, "采集运行")
        cancel_requested = bool(holder.get("cancel_requested"))
        interrupted_codes = {130, -1073741510, 3221225786}
        interrupted = cancel_requested or int(code1) in interrupted_codes
        if code1 != 0 and not interrupted:
            holder["status"] = "error"
            holder["error_detail"] = f"采集失败（退出码 {code1}）。"
            return
        if interrupted:
            append_row("【系统】采集已中断，开始尝试对已产出数据执行后处理。")

        cfg = job["cfg"]
        cmd_pp = _render_postprocess_command(
            cfg,
            excel_out=job["excel_out"],
            download_dir=job["download_dir"],
            dynamic_values=job["subst_vals"],
            extra_args=job["post_extra_args"],
        )
        excel_for_deliverable = job["excel_out"]
        if cmd_pp:
            append_row("【提示】 " + " ".join(shlex.quote(x) for x in cmd_pp))
            code2 = _run_subprocess_stream_to_holder(holder, cmd_pp, PROJECT_ROOT, "后处理")
            if holder.get("cancel_requested"):
                holder["status"] = "cancelled"
                append_row("【系统】用户已请求停止。")
                return
            if code2 != 0:
                holder["status"] = "error"
                holder["error_detail"] = f"后处理失败（退出码 {code2}）。"
                return
            excel_for_deliverable = _excel_for_client_deliverable(
                job["excel_out"],
                cmd_pp,
                holder.get("lines") if isinstance(holder.get("lines"), list) else None,
            )

        run_ts_cd = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_day_cd = datetime.now().strftime("%Y%m%d")
        yday_cd = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        cmd_cd = _render_client_deliverable_command(
            cfg,
            excel_out=excel_for_deliverable,
            download_dir=job["download_dir"],
            template_path=job["tpl_resolved_path"],
            run_ts=run_ts_cd,
            run_day=run_day_cd,
            yday=yday_cd,
            dynamic_values=job["subst_vals"],
            extra_args=None,
        )
        if cmd_cd:
            append_row("【提示】 " + " ".join(shlex.quote(x) for x in cmd_cd))
            code3 = _run_subprocess_stream_to_holder(holder, cmd_cd, PROJECT_ROOT, "客户交付整理（dailydate）")
            if holder.get("cancel_requested"):
                holder["status"] = "cancelled"
                append_row("【系统】用户已请求停止。")
                return
            if code3 != 0:
                holder["status"] = "error"
                holder["error_detail"] = f"客户交付整理失败（退出码 {code3}）。"
                return

        if interrupted:
            holder["status"] = "cancelled"
            append_row("【系统】任务已中断；已尝试完成可执行的后处理。")
        else:
            holder["status"] = "done"
        holder["result"] = {
            "download_dir": job["download_dir"],
            "excel_out": excel_for_deliverable,
            "trial_excel_out": job["excel_out"],
            "log_dir": job.get("log_dir") or "",
            "network_json_dir": job.get("network_json_dir") or "",
            "run_root": str(Path(job["download_dir"]).resolve().parent)
            if job.get("download_dir")
            else "",
        }
    except Exception as e:
        holder["status"] = "error"
        holder["exception"] = str(e)
        append_row(traceback.format_exc())


def _pipeline_holder_busy() -> bool:
    h = st.session_state.get("pipeline_holder")
    return isinstance(h, dict) and h.get("status") == "running"


_POSTPROCESS_OUT_MARKER = "__FFF2_POSTPROCESS_OUTPUT_EXCEL__"


def _excel_for_client_deliverable(
    trial_excel: str,
    cmd_pp: Optional[List[str]],
    log_lines: Optional[List[str]],
) -> str:
    """
    客户交付 dailydate 应打包「交付用主表」：若后处理另存为新文件，须用该路径而非试运行原始 excel_out。
    优先读子进程输出的 __FFF2_POSTPROCESS_OUTPUT_EXCEL__=绝对路径；否则解析 postprocess 命令行中的 --out。
    """
    base = (trial_excel or "").strip()
    if log_lines:
        for row in reversed(log_lines):
            if _POSTPROCESS_OUT_MARKER not in row:
                continue
            i = row.find(_POSTPROCESS_OUT_MARKER)
            if i < 0:
                continue
            tail = row[i + len(_POSTPROCESS_OUT_MARKER) :].strip()
            if not tail:
                continue
            p = Path(tail.strip().strip('"'))
            try:
                if p.is_file():
                    return str(p.resolve())
            except OSError:
                continue
    if cmd_pp:
        parts = [str(x) for x in cmd_pp]
        for j, a in enumerate(parts):
            if a.strip() == "--out" and j + 1 < len(parts):
                p = Path(parts[j + 1].strip().strip('"'))
                try:
                    if p.is_file():
                        return str(p.resolve())
                except OSError:
                    break
    return base


def _render_postprocess_command(
    cfg: dict,
    excel_out: str,
    download_dir: str,
    dynamic_values: Optional[Dict[str, str]] = None,
    extra_args: Optional[List[str]] = None,
) -> Optional[List[str]]:
    pp = cfg.get("postprocess") or {}
    if not isinstance(pp, dict) or not pp.get("enabled"):
        return None
    raw = pp.get("command")
    if not isinstance(raw, list) or not raw:
        return None
    vals: Dict[str, str] = {
        "excel_out": excel_out.strip(),
        "download_dir": download_dir.strip(),
        "project_root": str(PROJECT_ROOT),
        "task_display_name": str(cfg.get("name") or ""),
        "task_slug": str(cfg.get("id") or ""),
        "client_id": "",
        "client_name": "",
        "config_name": str(cfg.get("name") or ""),
        "config_id": str(cfg.get("id") or ""),
    }
    if dynamic_values:
        for k, v in dynamic_values.items():
            vals[k] = str(v)
            vals[f"param.{k}"] = str(v)
    out: List[str] = []
    for part in raw:
        s = str(part)
        for k, v in vals.items():
            s = s.replace("{" + k + "}", v)
        out.append(s)
    if extra_args:
        out.extend([str(x) for x in extra_args if str(x).strip()])
    return out


def _render_client_deliverable_command(
    cfg: dict,
    excel_out: str,
    download_dir: str,
    template_path: str,
    *,
    run_ts: str,
    run_day: str,
    yday: str,
    dynamic_values: Optional[Dict[str, str]] = None,
    extra_args: Optional[List[str]] = None,
) -> Optional[List[str]]:
    cd = cfg.get("client_deliverable") or {}
    if not isinstance(cd, dict) or not cd.get("enabled"):
        return None
    raw = cd.get("command")
    if not isinstance(raw, list) or not raw:
        return None
    vals: Dict[str, str] = {
        "excel_out": excel_out.strip(),
        "download_dir": download_dir.strip(),
        "project_root": str(PROJECT_ROOT),
        "run_ts": run_ts,
        "run_day": run_day,
        "yday": yday,
        "template_path": template_path.strip(),
        "task_display_name": str(cfg.get("name") or ""),
        "task_slug": str(cfg.get("id") or ""),
        "client_id": "",
        "client_name": "",
        "config_name": str(cfg.get("name") or ""),
        "config_id": str(cfg.get("id") or ""),
    }
    if dynamic_values:
        for k, v in dynamic_values.items():
            vals[k] = str(v)
            vals[f"param.{k}"] = str(v)
    out: List[str] = []
    for part in raw:
        s = str(part)
        for k, v in vals.items():
            s = s.replace("{" + k + "}", v)
        out.append(s)
    if extra_args:
        out.extend([str(x) for x in extra_args if str(x).strip()])
    return out


def _resolve_dynamic_params_cli(
    cfg: dict,
    default_overrides: Optional[Dict[str, object]] = None,
) -> Tuple[Dict[str, object], List[str], List[str]]:
    """
    根据 builtin 配置里的 dynamic_params 默认值（及预设 dynamic_params_override）生成 CLI 片段，
    不在页面上展示表单（避免与固定配置重复维护）。
    """
    defs = cfg.get("dynamic_params") or []
    if not isinstance(defs, list) or not defs:
        return {}, [], []
    values: Dict[str, object] = {}
    trial_args: List[str] = []
    post_args: List[str] = []
    dov = default_overrides if isinstance(default_overrides, dict) else None

    for i, p in enumerate(defs):
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        if not pid:
            continue
        ptype = str(p.get("type") or "text").strip().lower()
        default = p.get("default")
        if dov is not None and pid in dov:
            default = dov[pid]

        if ptype == "number":
            val = int(default) if isinstance(default, (int, float)) else 0
        elif ptype == "bool":
            val = bool(default)
        elif ptype == "select":
            val = str(default or "")
        elif ptype == "multiselect":
            val = list(default) if isinstance(default, list) else []
        else:
            val = str(default or "")
        values[pid] = val

        cli = p.get("cli") or {}
        if not isinstance(cli, dict):
            continue
        flag = str(cli.get("flag") or "").strip()
        if not flag:
            continue
        target = str(cli.get("target") or "trial").strip().lower()
        mode = str(cli.get("mode") or "").strip().lower()
        sink = post_args if target == "postprocess" else trial_args

        if ptype == "bool":
            if mode == "store_true":
                if bool(val):
                    sink.append(flag)
            elif mode == "store_false":
                if not bool(val):
                    sink.append(flag)
            else:
                sink.extend([flag, "true" if bool(val) else "false"])
        elif ptype == "multiselect":
            if isinstance(val, list) and val:
                sink.extend([flag, ",".join(str(x) for x in val)])
        else:
            sval = str(val).strip()
            if sval:
                sink.extend([flag, sval])
    return values, trial_args, post_args


st.set_page_config(page_title="采集控制台", layout="wide", initial_sidebar_state="collapsed")
_inject_compact_ops_theme()
st.markdown(
    '<div class="ops-hero"><p class="ops-hero-title">采集控制台</p>'
    '<p class="ops-hero-sub">选择配置与模块后一键运行；输出按批次写入项目 <code>output/</code> 目录。</p></div>',
    unsafe_allow_html=True,
)

builtin = _load_builtin_configs()
if not builtin:
    st.error("未找到内置配置文件 app/config_registry/builtin_configs.json")
    st.stop()

all_cfg = builtin
_ops_section("任务与模板")
idx = st.selectbox(
    "运行配置",
    list(range(len(all_cfg))),
    format_func=lambda i: all_cfg[i]["name"],
    key="ops_run_cfg_idx",
)
_orphan = st.session_state.pop("_sch_orphan_note", None)
if _orphan:
    st.warning(_orphan)
cfg = dict(all_cfg[idx])
profiles = _load_account_profiles()

template_options = _discover_template_files()
if not template_options:
    st.error("未在 `doc/` 下发现 `scrape-template-*.json` 模板文件。")
    st.stop()
resolved_template_rel, template_sync_note = _resolve_template_rel(cfg, template_options)
cfg["template"] = resolved_template_rel if resolved_template_rel else cfg.get("template", "")
template_path = PROJECT_ROOT / cfg["template"]

tpl_json = _load_json_template(template_path)
cfg_run = _cfg_with_template_modules(cfg, tpl_json)

cfg_id = str(cfg.get("id") or "cfg")

clients_registry = _load_clients()
_presets_list = _normalize_presets(cfg)

mod_key = f"mods_{cfg_id}"
preset_pick_key = f"preset_pick_{cfg_id}"
last_preset_idx_key = f"_last_preset_idx_{cfg_id}"

modules = cfg_run.get("module_page_ids") or []
default_modules = cfg_run.get("default_page_ids") or modules

if mod_key not in st.session_state:
    st.session_state[mod_key] = list(default_modules)

preset_labels = [_preset_short_label(None)]
preset_objs: List[Optional[dict]] = [None]
for pr in _presets_list:
    preset_labels.append(_preset_short_label(pr))
    preset_objs.append(pr)

pst_idx = st.selectbox(
    "快捷预设",
    range(len(preset_labels)),
    format_func=lambda i: preset_labels[i],
    key=preset_pick_key,
)
active_preset = preset_objs[pst_idx]

if last_preset_idx_key not in st.session_state:
    st.session_state[last_preset_idx_key] = pst_idx
elif st.session_state[last_preset_idx_key] != pst_idx:
    st.session_state[last_preset_idx_key] = pst_idx
    resolved, preset_warns = _resolve_preset_page_ids(cfg_run, active_preset)
    for w in preset_warns:
        st.warning(w)
    st.session_state[mod_key] = list(resolved)

if active_preset and str(active_preset.get("help") or "").strip():
    st.caption(str(active_preset.get("help")))

_ops_section("运行模块")
jinritemai_pack_rel: Optional[str] = None

selected_modules = st.multiselect(
    "模块（多选）",
    options=modules,
    format_func=lambda x: _format_module_choice(str(x), tpl_json),
    key=mod_key,
)

selected_profile = None
selected_shop_names: List[str] = []
jinritemai_pack_rel = str(cfg.get("jinritemai_account_pack") or "").strip() or None
pdd_account_pack_rel: Optional[str] = None
account_csv = str(cfg.get("pdd_credential_csv") or "").strip()
selected_client = next(
    (c for c in clients_registry if str(c.get("id") or "").strip() == ""),
    clients_registry[0],
)

_ops_section("账号")
if _template_is_pdd(cfg):
    pdd_labels, pdd_vals, pdd_default_idx = _pdd_credential_csv_select(cfg)
    if not pdd_vals:
        st.error("未找到拼多多账号包。请将 JSON 放到 `doc/pdd-account-packs/`。")
        st.stop()
    pdd_idx_key = f"pdd_pack_idx_{cfg_id}"
    if pdd_idx_key not in st.session_state or int(st.session_state[pdd_idx_key]) >= len(pdd_vals):
        st.session_state[pdd_idx_key] = pdd_default_idx
    pdd_idx = st.selectbox(
        "拼多多账号包",
        options=list(range(len(pdd_vals))),
        format_func=lambda i: pdd_labels[i],
        key=pdd_idx_key,
    )
    pdd_account_pack_rel = str(pdd_vals[int(pdd_idx)]).strip()
    pdd_path = PROJECT_ROOT / pdd_account_pack_rel
    if pdd_path.is_file():
        _pdd_ns = f"pdd_pack_editor_{cfg_id}_{pdd_path.name}"
        _pdd_obj: Optional[Any] = None
        try:
            _pdd_obj = json.loads(_read_text_fallback(pdd_path))
        except json.JSONDecodeError as e:
            _pdd_obj = None
            st.error(f"账号包 JSON 语法错误（第 {getattr(e, 'lineno', '?')} 行附近）：{e}")
            _pdd_raw_fallback = st.text_area(
                "手动修正 JSON 后保存",
                value=_read_text_fallback(pdd_path),
                height=180,
                key=f"{_pdd_ns}_raw_fallback",
            )
            if st.button("保存拼多多账号包（原始 JSON）", key=f"{_pdd_ns}_save_raw"):
                try:
                    _parsed = json.loads(_pdd_raw_fallback)
                    if not isinstance(_parsed, dict):
                        raise ValueError("根节点必须是 JSON 对象 { ... }")
                    _save_account_profile_json(pdd_path, _normalize_account_pack_root(_parsed))
                    st.success(f"已保存：{pdd_account_pack_rel}")
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))
        except Exception as e:
            _pdd_obj = None
            st.error(f"读取账号包失败：{e}")
        if _pdd_obj is not None and not isinstance(_pdd_obj, dict):
            st.error("账号包根节点须为 JSON 对象 `{ ... }`。")
            _pdd_obj = None
        if _pdd_obj is not None:
            pack_obj = _normalize_account_pack_root(_pdd_obj)
            if not pack_obj["profiles"]:
                pack_obj["profiles"]["pdd_default"] = []

            _pdd_label_in = st.text_input(
                "账号包名称（下拉列表展示）",
                value=str(pack_obj.get("label") or ""),
                key=f"{_pdd_ns}_label",
                help="对应 JSON 顶层 label，简短即可。",
            )
            _pk_list = sorted(pack_obj["profiles"].keys())
            _pk_idx = (
                _pk_list.index("pdd_default") if "pdd_default" in _pk_list else min(0, len(_pk_list) - 1)
            )
            sel_pk = st.selectbox(
                "账号分组 profile",
                options=_pk_list if _pk_list else ["pdd_default"],
                index=max(0, min(_pk_idx, len(_pk_list) - 1)) if _pk_list else 0,
                key=f"{_pdd_ns}_profile",
                help="须与模板「accountCredentialProfile」一致（常用 pdd_default）。",
            )
            if sel_pk not in pack_obj["profiles"]:
                pack_obj["profiles"][sel_pk] = []

            _df_pdd = _pdd_rows_to_df(pack_obj["profiles"].get(sel_pk))
            edited_pdd_df = st.data_editor(
                _df_pdd,
                num_rows="dynamic",
                hide_index=True,
                height=min(340, max(140, 56 + len(_df_pdd.index) * 34)),
                key=f"{_pdd_ns}_grid_{sel_pk}",
                column_config={
                    "店铺名": st.column_config.TextColumn("店铺名", width="medium"),
                    "登录账号": st.column_config.TextColumn("登录账号（手机等）", width="medium"),
                    "密码": _pdd_password_column_config(),
                },
            )
            st.caption("可增加/删除行；店铺名与登录账号至少填一项时再保存。")
            _pdd_name_opts = [
                str(x.get("name") or "").strip()
                for x in (pack_obj["profiles"].get(sel_pk) or [])
                if isinstance(x, dict) and str(x.get("name") or "").strip()
            ]
            if _pdd_name_opts:
                _pdd_name_opts = list(dict.fromkeys(_pdd_name_opts))
                selected_shop_names = st.multiselect(
                    "运行店铺（可多选，默认全选）",
                    options=_pdd_name_opts,
                    default=_pdd_name_opts,
                    key=f"{_pdd_ns}_run_shops_{sel_pk}",
                    help="仅运行勾选的店铺；不勾选则回退为账号包全部店铺。",
                )
            if st.button("保存拼多多账号包", type="primary", key=f"{_pdd_ns}_save"):
                try:
                    pack_obj["label"] = str(_pdd_label_in or "").strip()
                    pack_obj["profiles"][sel_pk] = _df_to_pdd_rows(edited_pdd_df)
                    _save_account_profile_json(pdd_path, pack_obj)
                    st.success(f"已保存：{pdd_account_pack_rel}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    else:
        st.warning(f"账号包文件不存在：`{pdd_account_pack_rel}`")
elif _template_is_jinritemai(cfg):
    dy_labels, dy_vals, dy_default_idx = _jinritemai_customer_pack_select(cfg)
    if not dy_vals:
        st.error("未找到抖音账号包。请将 JSON 放到 `doc/douyin-account-packs/`。")
        st.stop()
    dy_idx_key = f"douyin_pack_idx_{cfg_id}"
    if dy_idx_key not in st.session_state or int(st.session_state[dy_idx_key]) >= len(dy_vals):
        st.session_state[dy_idx_key] = dy_default_idx
    dy_idx = st.selectbox(
        "抖音账号包",
        options=list(range(len(dy_vals))),
        format_func=lambda i: dy_labels[i],
        key=dy_idx_key,
    )
    jinritemai_pack_rel = str(dy_vals[int(dy_idx)]).strip()
    cfg["jinritemai_account_pack"] = jinritemai_pack_rel
    dy_path = PROJECT_ROOT / jinritemai_pack_rel
    if dy_path.is_file():
        _dy_ns = f"douyin_pack_editor_{cfg_id}_{dy_path.name}"
        _dy_obj: Optional[Any] = None
        try:
            _dy_obj = json.loads(_read_text_fallback(dy_path))
        except json.JSONDecodeError as e:
            _dy_obj = None
            st.error(f"账号包 JSON 语法错误：{e}")
            _dy_raw_fb = st.text_area(
                "手动修正 JSON 后保存",
                value=_read_text_fallback(dy_path),
                height=180,
                key=f"{_dy_ns}_raw_fallback",
            )
            if st.button("保存抖音账号包（原始 JSON）", key=f"{_dy_ns}_save_raw"):
                try:
                    _p2 = json.loads(_dy_raw_fb)
                    if not isinstance(_p2, dict):
                        raise ValueError("根节点必须是 JSON 对象 { ... }")
                    _save_account_profile_json(dy_path, _normalize_account_pack_root(_p2))
                    st.success(f"已保存：{jinritemai_pack_rel}")
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))
        except Exception as e:
            _dy_obj = None
            st.error(f"读取账号包失败：{e}")
        if _dy_obj is not None and not isinstance(_dy_obj, dict):
            st.error("账号包根节点须为 JSON 对象 `{ ... }`。")
            _dy_obj = None
        if _dy_obj is not None:
            pack_dy = _normalize_account_pack_root(_dy_obj)
            if not pack_dy["profiles"]:
                pack_dy["profiles"]["default"] = []
            _dy_label_in = st.text_input(
                "账号包名称（下拉展示）",
                value=str(pack_dy.get("label") or ""),
                key=f"{_dy_ns}_label",
                help="JSON 顶层 label。",
            )
            _dk_list = sorted(pack_dy["profiles"].keys())
            _dki = _dk_list.index("default") if "default" in _dk_list else 0
            sel_dk = st.selectbox(
                "账号分组 profile",
                options=_dk_list if _dk_list else ["default"],
                index=max(0, min(_dki, len(_dk_list) - 1)) if _dk_list else 0,
                key=f"{_dy_ns}_profile",
                help="须与模板 globalAccountLoop.accountsProfile 等一致（常用 default）。",
            )
            if sel_dk not in pack_dy["profiles"]:
                pack_dy["profiles"][sel_dk] = []
            _df_dy = _douyin_rows_to_df(pack_dy["profiles"].get(sel_dk))
            edited_dy_df = st.data_editor(
                _df_dy,
                num_rows="dynamic",
                hide_index=True,
                height=min(340, max(140, 56 + len(_df_dy.index) * 34)),
                key=f"{_dy_ns}_grid_{sel_dk}",
                column_config={
                    "店铺名": st.column_config.TextColumn("店铺名", width="medium"),
                    "shopId": st.column_config.TextColumn("店铺 ID（shopId）", width="small"),
                    "千川ID": st.column_config.TextColumn("千川 ID（可空）", width="medium"),
                },
            )
            st.caption("千川 ID 没有可留空；可增加/删除行。")
            _dy_name_opts = [
                str(x.get("name") or "").strip()
                for x in (pack_dy["profiles"].get(sel_dk) or [])
                if isinstance(x, dict) and str(x.get("name") or "").strip()
            ]
            if _dy_name_opts:
                _dy_name_opts = list(dict.fromkeys(_dy_name_opts))
                selected_shop_names = st.multiselect(
                    "运行店铺（可多选，默认全选）",
                    options=_dy_name_opts,
                    default=_dy_name_opts,
                    key=f"{_dy_ns}_run_shops_{sel_dk}",
                    help="仅运行勾选的店铺；不勾选则回退为账号包全部店铺。",
                )
            if st.button("保存抖音账号包", type="primary", key=f"{_dy_ns}_save"):
                try:
                    pack_dy["label"] = str(_dy_label_in or "").strip()
                    pack_dy["profiles"][sel_dk] = _df_to_douyin_rows(edited_dy_df)
                    _save_account_profile_json(dy_path, pack_dy)
                    st.success(f"已保存：{jinritemai_pack_rel}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    else:
        st.warning(f"账号包文件不存在：`{jinritemai_pack_rel}`")
else:
    st.caption("当前模板无需账号包选择。")

cdp = DEFAULT_CDP
_cdp_banner = st.session_state.pop(f"_cdp_autostart_note_{cfg_id}", None)
if _cdp_banner:
    st.info(_cdp_banner)

preset_dyn_overrides: Dict[str, object] = {}
if active_preset:
    ov = active_preset.get("dynamic_params_override")
    if isinstance(ov, dict):
        preset_dyn_overrides = dict(ov)

dynamic_values, trial_extra_args, post_extra_args = _resolve_dynamic_params_cli(
    cfg,
    default_overrides=preset_dyn_overrides if preset_dyn_overrides else None,
)

# 抖店类配置：builtin 可为试运行注入 --package-dailydate-at-end；控制台若启用「客户交付」则去掉该参数（须在后处理之后再打 dailydate，且避免与 package_dailydate_deliverable 重复）。
_base_trial: List[str] = []
_bt = cfg.get("default_trial_args")
if isinstance(_bt, list):
    _base_trial = [str(x).strip() for x in _bt if str(x).strip()]
if isinstance((cfg.get("client_deliverable") or {}), dict) and (cfg.get("client_deliverable") or {}).get(
    "enabled"
):
    _base_trial = [x for x in _base_trial if x != "--package-dailydate-at-end"]
trial_extra_args = _base_trial + list(trial_extra_args)

if active_preset:
    trial_extra_args = list(trial_extra_args)
    post_extra_args = list(post_extra_args)
    et = active_preset.get("extra_trial_args")
    if isinstance(et, list):
        trial_extra_args.extend([str(x) for x in et if str(x).strip()])
    ep = active_preset.get("extra_post_args")
    if isinstance(ep, list):
        post_extra_args.extend([str(x) for x in ep if str(x).strip()])

cid = str(selected_client.get("id") or "").strip()
cname = str(selected_client.get("name") or "").strip()

task_display_name = str(cfg.get("name") or "")
if cname and cname not in ("未指定客户",):
    task_display_name = f"{cfg.get('name')} · {cname}"

task_slug = str(cfg.get("id") or "")
cslug = _safe_name_part(str(selected_client.get("slug") or ""))
if cslug:
    task_slug = f"{cfg.get('id')}_{cslug}"
elif cid:
    task_slug = f"{cfg.get('id')}_{cid}"

subst_vals = _merge_substitution_vals(
    dynamic_values,
    task_display_name=task_display_name,
    task_slug=task_slug,
    client_id=cid,
    client_name=cname,
)

run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
suffix = ""
_run_uid = secrets.token_hex(4)
_task_folder_label = _safe_name_part(task_display_name) or _safe_name_part(
    str(cfg.get("name") or cfg.get("id") or "task")
)
_run_folder_name = f"{_task_folder_label}_{run_tag}_{_run_uid}"
run_root = PROJECT_ROOT / "output" / _run_folder_name
default_download_dir = str(run_root / "downloads")
default_excel_out = str(run_root / "excel" / f"{cfg['id']}_{run_tag}{suffix}.xlsx")
default_log_dir = str(run_root / "runtime")
default_network_json_dir = str(run_root / "runtime" / "capture")
download_dir = default_download_dir
excel_out = default_excel_out
log_dir = default_log_dir
network_json_dir = default_network_json_dir

st.markdown(
    "<div class=\"ops-hint\"><strong>本批输出目录</strong> "
    f"<code>{_run_folder_name}</code> · "
    "<code>excel/</code> 汇总 · <code>downloads/</code> 下载 · "
    "<code>runtime/</code> 日志 · <code>runtime/capture/</code> 拦截 JSON · "
    "<code>--run-root</code> 同步罗盘等模板产物</div>",
    unsafe_allow_html=True,
)


def _schedule_tick(all_cfg: List[dict]) -> None:
    """队列中已到点的最早一项触发一轮完整流程（必要时自动切换「运行配置」）。"""
    if _pipeline_holder_busy():
        return
    now = datetime.now()
    queues = st.session_state.get("sch_queues")
    if not isinstance(queues, dict):
        return
    best_cid: Optional[str] = None
    best_t: Optional[datetime] = None
    for cid, lst in list(queues.items()):
        if not isinstance(lst, list) or not lst:
            continue
        t0 = lst[0]
        if not isinstance(t0, datetime):
            continue
        if t0 > now:
            continue
        if best_t is None or t0 < best_t:
            best_t = t0
            best_cid = str(cid)
    if not best_cid or best_t is None:
        return
    lst = queues.get(best_cid)
    if not isinstance(lst, list) or not lst or lst[0] != best_t:
        return
    lst.pop(0)
    if not lst:
        queues.pop(str(best_cid), None)
    st.session_state["sch_queues"] = queues
    idx_force = None
    for i, c in enumerate(all_cfg):
        if str(c.get("id") or "") == best_cid:
            idx_force = i
            break
    if idx_force is None:
        st.session_state["_sch_orphan_note"] = f"已跳过未知配置 id={best_cid} 的到期预约（可能已从 builtin 删除）。"
        return
    st.session_state["ops_run_cfg_idx"] = idx_force
    st.session_state["pending_pipeline_start"] = True
    st.rerun()


def _draw_pipeline_monitor() -> None:
    holder = st.session_state.get("pipeline_holder")
    if not holder:
        return
    st.markdown('<p class="ops-h">流水线</p>', unsafe_allow_html=True)
    status = holder.get("status")
    phase = holder.get("phase") or ""
    st.caption(f"{status} · {phase}")
    lock = holder.get("_lock")
    if lock:
        with lock:
            snap = list(holder.get("lines", []))
    else:
        snap = list(holder.get("lines", []))
    st.code("\n".join(snap[-400:]) or "(尚无输出)")
    if status == "running":
        if st.button("停止", type="secondary", key=f"pipeline_stop_{cfg_id}"):
            holder["cancel_requested"] = True
            proc = holder.get("current_proc")
            if proc is not None and proc.poll() is None:
                proc.terminate()
            st.rerun()
    elif status == "done":
        st.success("完成")
        r = holder.get("result") or {}
        _bits: List[str] = []
        if r.get("run_root"):
            _bits.append(f"根 `{r['run_root']}`")
        if r.get("download_dir"):
            _bits.append(f"下载 `{r['download_dir']}`")
        if r.get("excel_out"):
            _bits.append(f"交付主表 `{r['excel_out']}`")
        te = r.get("trial_excel_out") or ""
        if te and str(te).strip() != str(r.get("excel_out") or "").strip():
            _bits.append(f"试运行采集表 `{te}`")
        if r.get("log_dir"):
            _bits.append(f"日志 `{r['log_dir']}`（capture/ 为网络 JSON）")
        if _bits:
            st.caption(" · ".join(_bits))
        hint = (cfg.get("postprocess") or {}).get("result_hint")
        if hint:
            st.caption(f"后处理：{hint}")
        cd_hint = (cfg.get("client_deliverable") or {}).get("result_hint")
        if cd_hint and isinstance(cfg.get("client_deliverable"), dict) and cfg["client_deliverable"].get(
            "enabled"
        ):
            st.caption(f"客户交付：{cd_hint}")
        with st.expander("完整日志"):
            st.code("\n".join(snap) or "(无输出)")
    elif status == "cancelled":
        st.warning("已停止")
        with st.expander("已输出日志"):
            st.code("\n".join(snap) or "(无输出)")
    elif status == "error":
        st.error(holder.get("error_detail") or holder.get("exception") or "运行出错")
        with st.expander("日志与堆栈"):
            st.code("\n".join(snap) or "(无输出)")
    if status in ("done", "error", "cancelled"):
        if st.button("关闭记录", key=f"pipeline_clear_{cfg_id}"):
            st.session_state.pipeline_holder = None
            st.rerun()


with st.expander("预约", expanded=False):
    _sch_migrate_legacy_schedule(cfg_id)
    st.caption(
        "按**日期+时间**（本地时间）将多个时刻加入队列，到点自动执行一轮完整流程（与「开始运行」相同）。"
        f" 每笔须在 **{SCHEDULE_MAX_HOURS // 24} 天内**；多任务时按「最早到点」依次执行并自动切换运行配置。"
        " 预约保存在本会话内，**刷新或关闭浏览器会清空**；周末前预排请保持本页打开或改用系统计划任务脚本。"
    )
    _sn = datetime.now()
    _sh = _sn + timedelta(hours=SCHEDULE_MAX_HOURS)
    _def_at = min(_sn + timedelta(hours=1), _sh - timedelta(seconds=1))
    if _def_at <= _sn:
        _def_at = _sn + timedelta(minutes=5)

    c_date, c_time = st.columns(2)
    with c_date:
        _ap_d = st.date_input(
            "下一笔预约日期",
            value=_def_at.date(),
            min_value=_sn.date(),
            max_value=_sh.date(),
            key=f"sch_appt_date_{cfg_id}",
        )
    with c_time:
        _ap_tm = st.time_input(
            "下一笔预约时刻",
            value=_def_at.replace(second=0, microsecond=0).time(),
            key=f"sch_appt_time_{cfg_id}",
        )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("加入队列", key=f"sch_enqueue_{cfg_id}"):
            fire_at = datetime.combine(_ap_d, _ap_tm)
            ok, msg = _sch_enqueue(cfg_id, fire_at)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
    with c2:
        if st.button("清空本任务队列", key=f"sch_clr_{cfg_id}"):
            _sch_clear_queue(cfg_id)
            st.success("已清空本任务的全部预约时刻。")

    _ql = _sch_queue_for(cfg_id)
    if _ql:
        st.markdown("**本任务待执行（按时间先后）**")
        for _t in _ql:
            _rk = f"sch_rm_{cfg_id}_{_t.strftime('%Y%m%d%H%M%S')}"
            u1, u2 = st.columns([4, 1])
            with u1:
                st.text(f"· {_t:%Y-%m-%d %H:%M}")
            with u2:
                if st.button("移除", key=_rk):
                    _sch_remove_fire_at(cfg_id, _t)
                    st.rerun()
    else:
        st.caption("当前任务队列为空。")

    _allq = st.session_state.get("sch_queues") or {}
    if isinstance(_allq, dict) and _allq:
        _lines: List[str] = []
        for _cid, _lst in sorted(_allq.items(), key=lambda kv: str(kv[0])):
            if not isinstance(_lst, list) or not _lst:
                continue
            _nm = next((str(c.get("name") or _cid) for c in all_cfg if str(c.get("id") or "") == _cid), _cid)
            _lines.append(f"- **{_nm}**：{len(_lst)} 笔，最近 {_lst[0]:%m-%d %H:%M}")
        if _lines:
            st.markdown("**全局队列概览**（所有任务）  \n" + "  \n".join(_lines))

_frag = getattr(st, "fragment", None)
if _frag:
    _frag(run_every=timedelta(seconds=1))(_draw_pipeline_monitor)()
    _frag(run_every=timedelta(seconds=15))(lambda: _schedule_tick(all_cfg))()
else:
    _draw_pipeline_monitor()
    _schedule_tick(all_cfg)

pending_start = bool(st.session_state.pop("pending_pipeline_start", False))
busy = _pipeline_holder_busy()
clicked = st.button("开始运行", type="primary", use_container_width=True, disabled=busy)

if pending_start or clicked:
    if busy:
        st.warning("已有采集任务在运行，请等待结束或点击「停止运行」。")
    else:
        try:
            _cdp_ok, _cdp_note = ensure_cdp_chrome((cdp or "").strip() or DEFAULT_CDP)
            if not _cdp_ok:
                st.error(_cdp_note or "CDP 不可用")
            else:
                if _cdp_note:
                    st.session_state[f"_cdp_autostart_note_{cfg_id}"] = _cdp_note
            if not _cdp_ok:
                raise RuntimeError("cdp_unavailable")

            err, job = _compile_pipeline_job(
                template_path=template_path,
                cfg=cfg,
                jinritemai_pack_rel=jinritemai_pack_rel,
                pdd_account_pack_rel=pdd_account_pack_rel,
                account_csv=account_csv,
                selected_profile=selected_profile,
                selected_shop_names=selected_shop_names,
                cdp=(cdp or "").strip() or DEFAULT_CDP,
                selected_modules=selected_modules,
                download_dir=download_dir,
                excel_out=excel_out,
                log_dir=log_dir,
                network_json_dir=network_json_dir,
                run_root=str(run_root),
                trial_extra_args=trial_extra_args,
                post_extra_args=post_extra_args,
                subst_vals=subst_vals,
                abort_on_fail=False,
            )
            if err:
                st.error(f"无法启动：{err}")
            elif job:
                holder = _init_pipeline_holder()
                st.session_state.pipeline_holder = holder
                threading.Thread(target=_pipeline_worker, args=(holder, job), daemon=True).start()
                st.rerun()
        except RuntimeError as e:
            if str(e) != "cdp_unavailable":
                st.error(f"启动异常：{e}")
                st.code(traceback.format_exc())
        except Exception as e:
            st.error(f"启动异常：{e}")
            st.code(traceback.format_exc())

st.divider()
_ops_section("后处理（单独运行）")
st.caption("命令来自当前配置的 `postprocess`；路径可改成本机已有批次。")

_post_cmd = _render_postprocess_command(
    cfg,
    excel_out=excel_out,
    download_dir=download_dir,
    dynamic_values=subst_vals,
    extra_args=post_extra_args,
)
_kind_label = (
    "拼多多（下载目录 → process_pdd_data）"
    if _template_is_pdd(cfg)
    else "抖店（汇总 Excel → postprocess_home_blob_metrics）"
    if _template_is_jinritemai(cfg)
    else "其它模板"
)

if _post_cmd:
    st.caption(f"类型：{_kind_label}")

    _manual_post = list(_post_cmd)
    if _template_is_pdd(cfg):
        pp_input_dir = st.text_input(
            "拼多多 · 输入目录",
            value=download_dir,
            key=f"pp_input_dir_{cfg_id}",
            help="填写或粘贴含拼多多下载结果的文件夹路径；可与上方采集输出不同，指向已有批次。",
        )
        _manual_post = _override_cli_arg_after_flag(_manual_post, "--input-dir", pp_input_dir)
        _dd_chk = Path(pp_input_dir.strip())
        _dd_ok = _dd_chk.is_dir()
        st.caption(
            f"路径检查：`{_dd_chk}` — {'目录已存在，可运行' if _dd_ok else '⚠ 目录不存在，请修改路径或先完成采集'}"
        )
    if _template_is_jinritemai(cfg):
        pp_excel_in = st.text_input(
            "抖店 · 汇总 Excel",
            value=excel_out,
            key=f"pp_excel_in_{cfg_id}",
            help="填写 run_template_trial 写出的长表 Excel；可指向历史文件。",
        )
        _manual_post = _override_cli_arg_after_flag(_manual_post, "--excel", pp_excel_in)
        _xl_chk = Path(pp_excel_in.strip())
        _xl_ok = _xl_chk.is_file()
        st.caption(
            f"路径检查：`{_xl_chk}` — {'文件已存在，可运行' if _xl_ok else '⚠ 文件不存在，请修改路径或先完成采集'}"
        )

    if _template_is_pdd(cfg):
        _pdd_sub = st.selectbox(
            "拼多多 · 处理范围",
            ["all", "part1", "part2"],
            index=0,
            key=f"manual_pdd_sub_{cfg_id}",
            help="part1：售后退款汇总；part2：资金账单；all：两部分都跑（与流水线默认一致）。",
        )
        _manual_post = _apply_pdd_postprocess_subcommand(_manual_post, _pdd_sub)

    st.code(" ".join(shlex.quote(x) for x in _manual_post))
    _pp_hint = (cfg.get("postprocess") or {}).get("result_hint")
    if _pp_hint:
        st.caption(str(_pp_hint))

    _pp_log_region = st.empty()
    if st.button("运行后处理", type="secondary", use_container_width=True, key=f"manual_run_postprocess_{cfg_id}"):
        with st.spinner("正在运行数据处理脚本…"):
            _code_m = _run_blocking_command_ui(_manual_post, PROJECT_ROOT, _pp_log_region)
        if _code_m == 0:
            st.success("数据处理脚本执行完成。")
        else:
            st.error(f"数据处理脚本失败（退出码 {_code_m}）。")
else:
    st.info(
        "当前运行配置未启用 **`postprocess`**（`enabled: false`），或无可解析的数据处理命令。"
        " 如需后处理，请在 `builtin_configs.json` 中为该任务配置 `postprocess`。"
    )

st.markdown(
    f'<p class="ops-foot">本地端口建议 {DEFAULT_PORT}</p>',
    unsafe_allow_html=True,
)
