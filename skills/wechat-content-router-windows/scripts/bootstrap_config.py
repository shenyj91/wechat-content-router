#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path

from init_local_config import interactive_config, print_config_summary


CONFIG_PATH = Path(__file__).with_name("config.json")


def main():
    config = interactive_config()
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n配置已写入：{CONFIG_PATH}")
    print_config_summary(config)


if __name__ == "__main__":
    main()
