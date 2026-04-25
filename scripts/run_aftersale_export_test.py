"""
仅测试抖店售后列表一条线：侧栏进列表 → 展开筛选 → 退款成功 → 时间「昨日」→ 查询 → 导出。

依赖：已用 CDP 启动 Chrome 并登录抖店（可与主流程共用 scripts\\start_chrome_cdp_test.bat）。

示例：
  python scripts/run_aftersale_export_test.py
  python scripts/run_aftersale_export_test.py --accounts 店甲,店乙,店丙
  python scripts/run_aftersale_export_test.py --cdp http://127.0.0.1:9222

多店与主模板 global 循环：请改用主模板
  python scripts/run_template_trial.py --template doc/scrape-template-jinritemai-v1.json --global-accounts 店甲,店乙 --page-ids fxg_aftersale_order_list_export

其余参数原样传给 run_template_trial.py（--help 可看全部选项）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TRIAL = ROOT / "scripts" / "run_template_trial.py"
_TEMPLATE = ROOT / "doc" / "scrape-template-fxg-aftersale-export-test.json"
_PAGE_ID = "fxg_aftersale_order_list_export"


def main() -> int:
    if not _TRIAL.is_file():
        print(f"未找到: {_TRIAL}", file=sys.stderr)
        return 1
    if not _TEMPLATE.is_file():
        print(f"未找到测试模板: {_TEMPLATE}", file=sys.stderr)
        return 1
    cmd = [
        sys.executable,
        str(_TRIAL),
        "--template",
        str(_TEMPLATE),
        "--page-ids",
        _PAGE_ID,
    ]
    cmd.extend(sys.argv[1:])
    return int(subprocess.call(cmd, cwd=str(ROOT)))


if __name__ == "__main__":
    raise SystemExit(main())
