"""
仅测试抖店「历史报表 → 首条下载」一步，不跑账单生成与账单页等待。

依赖：已用 CDP 启动 Chrome 并登录抖店（scripts\\start_chrome_cdp_test.bat）。

示例：
  python scripts/run_bill_history_download_test.py
  python scripts/run_bill_history_download_test.py --accounts 某店铺
  python scripts/run_bill_history_download_test.py --download-timeout-ms 180000 --no-abort-on-fail

其余参数原样传给 run_template_trial.py。未指定时默认附加 --post-interaction-wait-ms 0，减少页末空等。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TRIAL = ROOT / "scripts" / "run_template_trial.py"
_TEMPLATE = ROOT / "doc" / "scrape-template-fxg-bill-history-download-test.json"
_PAGE_ID = "fxg_bill_history_report"


def main() -> int:
    if not _TRIAL.is_file():
        print(f"未找到: {_TRIAL}", file=sys.stderr)
        return 1
    if not _TEMPLATE.is_file():
        print(f"未找到测试模板: {_TEMPLATE}", file=sys.stderr)
        return 1
    extra = sys.argv[1:]
    cmd = [
        sys.executable,
        str(_TRIAL),
        "--template",
        str(_TEMPLATE),
        "--page-ids",
        _PAGE_ID,
    ]
    if not any(a == "--post-interaction-wait-ms" for a in extra):
        cmd.extend(["--post-interaction-wait-ms", "0"])
    cmd.extend(extra)
    return int(subprocess.call(cmd, cwd=str(ROOT)))


if __name__ == "__main__":
    raise SystemExit(main())
