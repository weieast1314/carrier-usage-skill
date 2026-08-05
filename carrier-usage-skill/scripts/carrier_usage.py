#!/usr/bin/env python3
"""从源码仓库运行运营商查询 CLI。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from carrier_usage.cli import main  # noqa: I001 - 先修正脚本目录导致的包遮蔽


if __name__ == "__main__":
    raise SystemExit(main())
