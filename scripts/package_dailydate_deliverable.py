# -*- coding: utf-8 -*-
"""
将抖店一次试运行的产出整理到项目根 dailydate/ 下，便于直接发给客户：
  - 主数据 Excel：由调用方传入路径（控制台在后处理后会传「加工后的看板表」；纯命令行未后处理时即采集表）；复制到交付文件夹（不改动原路径文件）
  - 浏览器下载目录中的其它导出文件：打成 zip（默认不包含与采集表同一路径的那份）

交付文件夹命名默认包含：运行日、模板输出子目录（任务标识）、运行时间戳。
"""

import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _sanitize_filename_prefix(name: str, *, max_len: int = 80) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    s = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]', "_", s)
    s = s.strip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s or "account"


def _expand_pkg_placeholders(
    s: str,
    *,
    run_ts: str,
    yday: str,
    run_day: str,
    task_name: str,
    task_slug: str,
    run_output_subdir: str,
) -> str:
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
        .replace("{task_name}", task_name or "")
        .replace("{task_slug}", task_slug or "")
        .replace("{run_output_subdir}", run_output_subdir or "")
    )


def _trial_output_root_from_tpl(
    tpl: Optional[dict],
    *,
    run_ts: str = "",
    yday: str = "",
    run_day: str = "",
) -> Path:
    """与 run_template_trial._trial_output_root 一致（占位符展开 + 多级子目录）。"""
    base = PROJECT_ROOT / "output"
    if not isinstance(tpl, dict):
        return base
    sub = str(tpl.get("runOutputSubdir") or "").strip()
    if not sub:
        return base
    ros_exp = _expand_pkg_placeholders(
        sub,
        run_ts=run_ts,
        yday=yday,
        run_day=run_day,
        task_name="",
        task_slug="",
        run_output_subdir="",
    )
    raw_parts = re.split(r"/+", ros_exp.replace("\\", "/").strip("/"))
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


def resolve_compass_metrics_path(
    tpl: dict,
    *,
    run_ts: str,
    yday: str,
    run_day: str,
) -> Path:
    """与 run_template_trial._resolve_compass_metrics_out_path 一致。"""
    rel = str(tpl.get("compassMetricsOutputPath") or "").strip()
    if not rel:
        if run_ts:
            rel = f"店铺罗盘千川指标表_{run_ts}.xlsx"
        else:
            return PROJECT_ROOT / "output" / "店铺罗盘千川指标表.xlsx"
    ros_plain = str(tpl.get("runOutputSubdir") or "").strip()
    ros_disp = (
        _sanitize_filename_prefix(
            _expand_pkg_placeholders(
                ros_plain,
                run_ts=run_ts,
                yday=yday,
                run_day=run_day,
                task_name="",
                task_slug="",
                run_output_subdir="",
            ).replace("/", "_").replace("\\", "_")
        )
        if ros_plain
        else ""
    )
    rs = _expand_pkg_placeholders(
        rel.replace("\\", "/"),
        run_ts=run_ts,
        yday=yday,
        run_day=run_day,
        task_name="",
        task_slug="",
        run_output_subdir=ros_disp or ros_plain,
    )
    p = Path(rs)
    if p.is_absolute():
        return p
    if rs.startswith("output/"):
        return PROJECT_ROOT / rs
    return _trial_output_root_from_tpl(tpl, run_ts=run_ts, yday=yday, run_day=run_day) / rs


def _compass_auto_enabled(tpl: dict) -> bool:
    raw = tpl.get("aggregateExcelAutoCompassMetrics")
    if raw is True:
        return True
    rs = str(raw or "").strip().lower()
    return rs in ("1", "yes", "true")


def _collect_zip_files(
    download_dir: Path,
    *,
    exclude_resolved: Optional[Path],
) -> List[Tuple[Path, str]]:
    """返回 (绝对路径, zip 内相对路径) 列表。"""
    if not download_dir.is_dir():
        return []
    out: List[Tuple[Path, str]] = []
    dl_root = download_dir.resolve()
    exclude = exclude_resolved.resolve() if exclude_resolved else None
    for root, _dirs, files in os.walk(download_dir):
        rpath = Path(root)
        for fn in files:
            ap = (rpath / fn).resolve()
            if exclude is not None and ap == exclude:
                continue
            arc = str(ap.relative_to(dl_root)).replace("\\", "/")
            out.append((ap, arc))
    return sorted(out, key=lambda x: x[1])


def package_client_deliverable(
    scraped_excel: Path,
    download_dir: Path,
    *,
    dailydate_root: Path,
    run_ts: str,
    run_day: str,
    yday: str,
    tpl: Optional[dict] = None,
    template_path: Optional[Path] = None,
    task_name: str = "",
    task_slug: str = "",
    folder_name_pattern: str = "{run_day}_{run_output_subdir}_{run_ts}",
    zip_basename_pattern: str = "网页导出等附件_{run_ts}",
    auto_compass_copy: bool = False,
    readme: bool = True,
) -> Tuple[Path, List[str]]:
    """
    创建 dailydate/<folder>/ ，复制采集表；可选复制罗盘汇总表；将 download_dir 打成 zip。
    返回 (交付文件夹路径, 日志行)。
    """
    logs: List[str] = []
    scraped_excel = scraped_excel.resolve()
    download_dir = download_dir.resolve()
    dailydate_root = dailydate_root.resolve()
    dailydate_root.mkdir(parents=True, exist_ok=True)

    if tpl is None and template_path is not None and template_path.is_file():
        tpl = json.loads(template_path.read_text(encoding="utf-8"))
    if not isinstance(tpl, dict):
        tpl = {}

    ros_plain = str(tpl.get("runOutputSubdir") or "").strip()
    run_output_subdir = (
        _sanitize_filename_prefix(
            _expand_pkg_placeholders(
                ros_plain,
                run_ts=run_ts,
                yday=yday,
                run_day=run_day,
                task_name="",
                task_slug="",
                run_output_subdir="",
            ).replace("/", "_").replace("\\", "_")
        )
        if ros_plain
        else ""
    )
    if not run_output_subdir:
        run_output_subdir = _sanitize_filename_prefix(task_slug) or "task"
    tn = task_name.strip() or str(tpl.get("name") or "").strip() or "任务"
    slug = _sanitize_filename_prefix(task_slug) or run_output_subdir

    folder_name = _expand_pkg_placeholders(
        folder_name_pattern,
        run_ts=run_ts,
        yday=yday,
        run_day=run_day,
        task_name=_sanitize_filename_prefix(tn, max_len=40),
        task_slug=slug,
        run_output_subdir=run_output_subdir,
    )
    folder_name = _sanitize_filename_prefix(folder_name, max_len=160) or f"run_{run_ts}"
    out_dir = dailydate_root / folder_name
    if out_dir.exists():
        # 同一时间戳重跑：在目录名后加短后缀避免覆盖
        out_dir = dailydate_root / f"{folder_name}_dup"
        n = 2
        while out_dir.exists():
            out_dir = dailydate_root / f"{folder_name}_dup{n}"
            n += 1
    out_dir.mkdir(parents=True, exist_ok=True)

    if not scraped_excel.is_file():
        raise FileNotFoundError(f"采集表不存在: {scraped_excel}")

    dest_xlsx = out_dir / scraped_excel.name
    shutil.copy2(scraped_excel, dest_xlsx)
    logs.append(f"已复制采集表: {dest_xlsx.name}")

    extra_copies: List[str] = []
    if auto_compass_copy and _compass_auto_enabled(tpl):
        cpath = resolve_compass_metrics_path(tpl, run_ts=run_ts, yday=yday, run_day=run_day)
        if cpath.is_file():
            dest_c = out_dir / cpath.name
            shutil.copy2(cpath, dest_c)
            extra_copies.append(dest_c.name)
            logs.append(f"已复制罗盘千川汇总表: {dest_c.name}")
        else:
            logs.append(f"[提示] 未找到罗盘汇总文件（跳过）: {cpath}")

    zip_base = _expand_pkg_placeholders(
        zip_basename_pattern,
        run_ts=run_ts,
        yday=yday,
        run_day=run_day,
        task_name=_sanitize_filename_prefix(tn, max_len=40),
        task_slug=slug,
        run_output_subdir=run_output_subdir,
    )
    zip_base = _sanitize_filename_prefix(zip_base, max_len=120) or f"attachments_{run_ts}"
    if not zip_base.lower().endswith(".zip"):
        zip_base = zip_base + ".zip"
    zip_path = out_dir / zip_base

    exclude_zip_source: Optional[Path] = None
    try:
        scraped_res = scraped_excel.resolve()
        dl_res = download_dir.resolve()
        scraped_res.relative_to(dl_res)
        exclude_zip_source = scraped_excel
    except ValueError:
        pass

    pairs = _collect_zip_files(download_dir, exclude_resolved=exclude_zip_source)
    if pairs:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for ap, arc in pairs:
                zf.write(ap, arcname=arc)
        logs.append(f"已打包网页导出等附件: {zip_path.name}（{len(pairs)} 个文件）")
    else:
        logs.append("下载目录为空或无附加文件，未生成附件 zip。")

    if readme:
        lines = [
            "客户交付包说明",
            "",
            f"运行日期（本地）: {run_day}",
            f"运行时间戳: {run_ts}",
            f"统计昨日（业务参考）: {yday}",
            f"任务名称: {tn}",
            f"模板输出子目录标识: {run_output_subdir}",
            "",
            f"- 主数据表（控制台会在后处理后再打包时，放入已加工后的 Excel；纯试运行无后处理时即为采集表）: {scraped_excel.name}",
        ]
        if extra_copies:
            lines.append(f"- 罗盘千川汇总表（若已生成）: {', '.join(extra_copies)}")
        if pairs:
            lines.append(f"- 网页导出等浏览器下载文件: {zip_path.name}")
        else:
            lines.append("- 网页导出等浏览器下载文件: （本轮无附件或未写入下载目录）")
        lines.append("")
        lines.append("请将采集表直接交付；压缩包内为各页导出的原始下载文件。")
        readme_path = out_dir / "README_交付说明.txt"
        readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logs.append(f"已写入说明: {readme_path.name}")

    logs.insert(0, f"客户交付目录: {out_dir.resolve()}")
    return out_dir, logs


def _parse_bool(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y", "on")


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="整理抖店试运行产出到 dailydate/ 客户交付目录")
    p.add_argument("--scraped-excel", required=True, type=Path, help="采集汇总 Excel（template_trial 等）")
    p.add_argument("--download-dir", required=True, type=Path, help="浏览器下载目录（run_template_trial 的 download-dir）")
    p.add_argument(
        "--dailydate-root",
        type=Path,
        default=PROJECT_ROOT / "dailydate",
        help="交付根目录，默认项目根下 dailydate/",
    )
    p.add_argument("--run-ts", required=True, help="本次运行时间戳 YYYYMMDD_HHMMSS")
    p.add_argument("--run-day", default="", help="运行日 YYYYMMDD，默认可由脚本填今天")
    p.add_argument("--yday", default="", help="统计昨日 YYYY-MM-DD，默认可由脚本推算中国时区昨天")
    p.add_argument("--template", type=Path, default=None, help="模板 JSON，用于 run_output_subdir / 罗盘路径解析")
    p.add_argument("--task-name", default="", help="任务展示名（写入 README）")
    p.add_argument("--task-slug", default="", help="任务短标识（文件夹占位符 task_slug）")
    p.add_argument(
        "--folder-name-pattern",
        default="{run_day}_{run_output_subdir}_{run_ts}",
        help="交付文件夹名占位符模板",
    )
    p.add_argument("--zip-basename-pattern", default="网页导出等附件_{run_ts}", help="附件 zip 主文件名（可不含 .zip）")
    p.add_argument(
        "--auto-compass-if-template",
        action="store_true",
        help="若模板 aggregateExcelAutoCompassMetrics 开启且能解析到罗盘文件则一并复制",
    )
    p.add_argument("--no-readme", action="store_true", help="不写 README_交付说明.txt")
    ns = p.parse_args(list(argv) if argv is not None else None)

    run_ts = str(ns.run_ts).strip()
    run_day = str(ns.run_day).strip()
    yday = str(ns.yday).strip()
    if not run_day:
        from datetime import datetime

        run_day = datetime.now().strftime("%Y%m%d")
    if not yday:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            from run_template_trial import _yesterday_str  # type: ignore

            yday = _yesterday_str()
        except Exception:
            from datetime import date, timedelta

            yday = (date.today() - timedelta(days=1)).isoformat()

    tpl_obj: Optional[dict] = None
    if ns.template is not None and Path(ns.template).is_file():
        tpl_obj = json.loads(Path(ns.template).read_text(encoding="utf-8"))

    try:
        out_dir, logs = package_client_deliverable(
            Path(ns.scraped_excel),
            Path(ns.download_dir),
            dailydate_root=Path(ns.dailydate_root),
            run_ts=run_ts,
            run_day=run_day,
            yday=yday,
            tpl=tpl_obj,
            template_path=Path(ns.template) if ns.template else None,
            task_name=str(ns.task_name or ""),
            task_slug=str(ns.task_slug or ""),
            folder_name_pattern=str(ns.folder_name_pattern or ""),
            zip_basename_pattern=str(ns.zip_basename_pattern or ""),
            auto_compass_copy=bool(ns.auto_compass_if_template),
            readme=not ns.no_readme,
        )
    except Exception as e:
        print(f"[客户交付打包] 失败: {e}", file=sys.stderr)
        return 1
    for line in logs:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
