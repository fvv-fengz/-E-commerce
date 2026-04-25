# -*- coding: utf-8 -*-
"""供 prep_conda_env_for_pack 调用：把 Playwright 浏览器装到当前解释器所在环境内。"""
import os
import subprocess
import sys

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(sys.prefix, "playwright-browsers")
subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
print("PLAYWRIGHT_BROWSERS_PATH =", os.environ["PLAYWRIGHT_BROWSERS_PATH"])
