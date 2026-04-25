# -*- coding: utf-8 -*-
"""
从已连接 CDP 的 Chrome 中，抓取千川「账户选择器」里无限滚动区域文本，写入 .txt。

前置：已用 scripts/start_chrome_cdp_test.bat 等启动调试 Chrome，并已打开巨量千川且账户列表区域可见
（若只在首页未展开列表，请先点开顶部账户/店铺选择，使 .account-selector 内滚动区出现）。

用法（项目根目录）:
  python dev-plugins/scrape_qianchuan_account_scroll.py
  python dev-plugins/scrape_qianchuan_account_scroll.py --out output/my_accounts.txt
  python dev-plugins/scrape_qianchuan_account_scroll.py --cdp http://127.0.0.1:9222
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SELECTOR = (
    "body > div.container > div.right > div.account-selector > "
    "div.byted-infinite-scroll.account-infinite.fix-scroll"
)

# 备选：哈希或层级微调时尝试
ALTERNATE_SELECTORS = [
    "div.account-selector div.byted-infinite-scroll.account-infinite.fix-scroll",
    "div.byted-infinite-scroll.account-infinite.fix-scroll",
]


def _pick_qianchuan_page(context: Any) -> Any:
    pages = list(context.pages)
    if not pages:
        return None
    for p in reversed(pages):
        try:
            if "qianchuan.jinritemai.com" in (p.url or "").lower():
                return p
        except Exception:
            continue
    return pages[-1]


def _first_visible_selector(
    page: Any, selectors: list, wait_ms: int
) -> Tuple[Optional[Any], Optional[str]]:
    last_err = ""
    for sel in selectors:
        s = (sel or "").strip()
        if not s:
            continue
        try:
            loc = page.locator(s).first
            loc.wait_for(state="visible", timeout=max(1000, min(wait_ms, 120000)))
            return loc, s
        except Exception as e:
            last_err = str(e)
            continue
    if last_err:
        print(f"[提示] 等待可见失败: {last_err}", file=sys.stderr)
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取千川 account-selector 内滚动区文本到 txt")
    parser.add_argument(
        "--cdp",
        default="http://127.0.0.1:9222",
        help="Chrome CDP 地址（默认 127.0.0.1:9222）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出 txt 路径；默认 output/qianchuan_account_scroll_时间戳.txt",
    )
    parser.add_argument(
        "--selector",
        default=DEFAULT_SELECTOR,
        help="主选择器（与页面结构一致时用最稳）",
    )
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=30000,
        help="等待节点可见超时（毫秒）",
    )
    args = parser.parse_args()

    out: Path = args.out or (
        PROJECT_ROOT / "output" / f"qianchuan_account_scroll_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    )
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    chain = [args.selector.strip()] + [s for s in ALTERNATE_SELECTORS if s != args.selector.strip()]

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(args.cdp.strip())
        except Exception as e:
            print(f"无法连接 CDP {args.cdp}: {e}", file=sys.stderr)
            return 1
        if not browser.contexts:
            print("浏览器无可用上下文", file=sys.stderr)
            return 1
        ctx = browser.contexts[0]
        page = _pick_qianchuan_page(ctx)
        if page is None:
            print("没有可操作的标签页", file=sys.stderr)
            return 1
        try:
            page.bring_to_front()
        except Exception:
            pass

        loc, used = _first_visible_selector(page, chain, args.wait_ms)
        if loc is None:
            print(f"未匹配到选择器。当前页 URL: {page.url}", file=sys.stderr)
            print("请确认已打开千川，并已展开账户/店铺列表。", file=sys.stderr)
            return 1

        try:
            text = loc.inner_text(timeout=15000)
        except Exception as e:
            print(f"读取 inner_text 失败: {e}", file=sys.stderr)
            return 1

        # 尝试拆一层直接子节点（结构因页面而异，仅供参考）
        row_snippets: list[str] = []
        try:
            kids = loc.locator(":scope > div").all()
            for i, k in enumerate(kids[:200]):
                try:
                    if k.is_visible(timeout=500):
                        t = k.inner_text(timeout=2000).strip()
                        if t:
                            row_snippets.append(f"[子块 {i + 1}]\n{t}")
                except Exception:
                    continue
        except Exception:
            pass

        lines: list[str] = [
            f"抓取时间: {datetime.now().isoformat(timespec='seconds')}",
            f"页面 URL: {page.url or ''}",
            f"使用选择器: {used}",
            "",
            "========== inner_text（整块） ==========",
            text.strip() if text else "(空)",
            "",
        ]
        if row_snippets:
            lines.append("========== 子块拆分（尽力而为，结构变则不准） ==========")
            lines.extend(row_snippets)
            lines.append("")

        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"已写入: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
