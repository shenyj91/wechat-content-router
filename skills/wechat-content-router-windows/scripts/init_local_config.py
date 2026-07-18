#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Create a local config for wechat-content-router.")
    parser.add_argument("--mode", choices=["obsidian", "local"], default="obsidian", help="Where imported files should be saved")
    parser.add_argument("--vault-root", help="Absolute path to your Obsidian vault root")
    parser.add_argument("--local-root", help="Absolute path to a normal local folder for direct download")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("config.json")),
        help="Where to write the config file",
    )
    args = parser.parse_args()

    vault_root = str(Path(args.vault_root).expanduser().resolve()) if args.vault_root else ""
    local_root = str(Path(args.local_root).expanduser().resolve()) if args.local_root else ""
    if args.mode == "obsidian" and not vault_root:
        raise SystemExit("--mode obsidian 时必须提供 --vault-root")
    if args.mode == "local" and not local_root:
        raise SystemExit("--mode local 时必须提供 --local-root")
    output_path = Path(args.output).expanduser().resolve()
    state_root = vault_root or local_root

    config = {
        "vault_root": vault_root,
        "state_file": str(Path(state_root) / ".wechat-content-router-state.json"),
        "storage": {
            "mode": args.mode,
            "local_root": local_root,
        },
        "settings": {
            "openAfterCreate": False,
            "downloadImages": True,
            "runOcr": True,
            "keepImagesInNote": True,
            "deleteImagesAfterOcr": False,
            "appendImagesAfterText": True,
            "includeFrontmatter": True,
            "includeImportedAt": True,
        },
        "routes": {
            "xhs": {
                "enabled": True,
                "import_root": "微信导入/小红书",
                "asset_root": "微信导入/小红书/assets",
                "save_pdf": args.mode == "local",
                "prefer_pdf_preview": args.mode == "local",
                "pdf_source": "browser_render",
            },
            "mp": {
                "enabled": True,
                "import_root": "微信导入/公众号",
                "save_pdf": args.mode == "local",
                "prefer_pdf_preview": args.mode == "local",
                "pdf_source": "browser_render",
            },
            "feishu": {
                "enabled": True,
                "import_root": "微信导入/飞书",
                "save_pdf": args.mode == "local",
                "prefer_pdf_preview": args.mode == "local",
                "pdf_source": "browser_render",
            },
        },
        "wechat": {
            "enabled": False,
            "session_db": "",
            "message_dir": "",
            "chat_username": "filehelper",
            "message_table": "",
            "decrypt_workdir": "",
            "decrypt_python": "",
            "decrypt_script": "",
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
