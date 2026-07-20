#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
XHS_URL_RE = re.compile(r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s<>\"]+")
MP_URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s<>\"]+")
FEISHU_URL_RE = re.compile(r"https?://(?:[\w-]+\.)?feishu\.cn/(?:wiki|docx)/[^\s<>\"]+")


def ensure_python_deps():
    """首次运行若缺少 Python 依赖，自动 pip 安装，保证干净克隆也能直接跑。"""
    required = ["requests", "lxml", "browser_cookie3", "zstandard"]
    missing = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return
    req_path = SCRIPT_DIR / "requirements.txt"
    if not req_path.exists():
        raise RuntimeError(f"缺少依赖 {missing}，且未找到 requirements.txt（{req_path}）")
    print(f"[bootstrap] 缺少 Python 依赖 {missing}，正在安装…", file=sys.stderr)
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_path)], check=True)


def load_importer(module_name: str, script_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ensure_config():
    if CONFIG_PATH.exists():
        return
    print("还没有配置文件，先启动本地辅助配置。")
    subprocess.run([sys.executable, str(SCRIPT_DIR / "bootstrap_config.py")], check=True)


def load_config():
    ensure_config()
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def detect_type_and_url(raw_text: str) -> tuple[str, str]:
    for route_type, pattern in (("xhs", XHS_URL_RE), ("mp", MP_URL_RE), ("feishu", FEISHU_URL_RE)):
        match = pattern.search(raw_text or "")
        if match:
            return route_type, match.group(0).replace("&amp;", "&")
    return "", ""


def import_manual(raw_text: str):
    ensure_python_deps()
    route_type, url = detect_type_and_url(raw_text)
    if not route_type:
        raise RuntimeError("没识别出支持的链接类型，目前支持：小红书 / 公众号 / 飞书。")
    if route_type == "xhs":
        importer = load_importer("router_xhs", SCRIPT_DIR / "import_xhs_note.py")
        return {"type": route_type, "result": importer.import_note(raw_text)}
    if route_type == "mp":
        importer = load_importer("router_mp", SCRIPT_DIR / "import_wechat_mp_article.py")
        return {"type": route_type, "result": importer.import_article(url)}
    importer = load_importer("router_feishu", SCRIPT_DIR / "import_feishu_page.py")
    return {"type": route_type, "result": importer.import_page(url)}


def run_wechat_once():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "run_wechat_router_pipeline.py")],
        capture_output=True,
        text=True,
    )
    raw_output = (result.stdout or "").strip()
    if raw_output:
        try:
            payload = json.loads(raw_output)
            if isinstance(payload, dict) and payload.get("status") == "decrypt_failed":
                error_text = str(payload.get("error") or "")
                if "SecurityStatus:2" in error_text or "wcdb_init" in error_text:
                    raise RuntimeError("微信自动扫描不可用：WCDB 安全保护拦住了当前环境，先用手动粘贴链接模式。")
                raise RuntimeError(error_text or "微信扫描失败")
            return payload
        except json.JSONDecodeError:
            pass
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = raw_output
        if "SecurityStatus:2" in stderr or "SecurityStatus:2" in stdout or "wcdb_init" in stderr or "wcdb_init" in stdout:
            raise RuntimeError("微信自动扫描不可用：WCDB 安全保护拦住了当前环境，先用手动粘贴链接模式。")
        raise RuntimeError(stderr or stdout or "微信扫描失败")
    return json.loads(result.stdout)


def print_summary(config: dict):
    storage = config.get("storage") or {}
    workflow = config.get("workflow") or {}
    wechat = config.get("wechat") or {}
    target = storage.get("local_root") if storage.get("mode") == "local" else config.get("vault_root")
    account_text = wechat.get("selected_account_label") or wechat.get("selected_account_wxid") or "未绑定"
    print("\n当前配置")
    print(f"- 保存模式：{storage.get('mode')}")
    print(f"- 目标路径：{target}")
    print(f"- 默认使用方式：{workflow.get('default_action', 'manual_link')}")
    print(f"- 微信自动扫描：{'开启' if wechat.get('enabled') else '关闭'}")
    print(f"- 当前绑定微信：{account_text}")


def maybe_auto_run(config: dict) -> bool:
    workflow = config.get("workflow") or {}
    wechat = config.get("wechat") or {}
    if workflow.get("default_action") != "wechat_monitor":
        return False
    if not wechat.get("enabled"):
        return False

    print("\n已选择“自动扫描微信”模式，启动后先自动跑一次。")
    try:
        print(json.dumps(run_wechat_once(), ensure_ascii=False, indent=2))
    except Exception as error:
        print(f"自动扫描失败：{error}")
    return True


def maybe_launch_wechat(config: dict) -> None:
    wechat = config.get("wechat") or {}
    if not wechat.get("enabled"):
        return
    try:
        decrypt_module = load_importer("wechat_win_decrypt", SCRIPT_DIR / "wechat_win_decrypt.py")
        result = decrypt_module.ensure_wechat_running()
        if result.get("launched"):
            print("已自动拉起微信。")
    except Exception as error:
        print(f"微信自动拉起失败：{error}")


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--auto-run", action="store_true", help="启动后若微信自动扫描已启用，则先自动跑一次")
    args = parser.parse_args()

    config = load_config()
    ensure_python_deps()
    print_summary(config)
    maybe_launch_wechat(config)
    if args.auto_run and maybe_auto_run(config):
        return
    maybe_auto_run(config)

    while True:
        print("\n请选择要做什么：")
        print("1. 手动粘贴一条链接/分享文案进行导入")
        print("2. 运行一次微信自动扫描")
        print("3. 按当前配置持续扫描微信")
        print("4. 重新配置")
        print("5. 修改监控会话（当前：" + (config.get("wechat") or {}).get("chat_username", "filehelper") + "）")
        print("0. 退出")
        choice = input("请输入序号：").strip()

        if choice == "0":
            return
        if choice == "5":
            new_session = select_session(config)
            if new_session:
                config["wechat"]["chat_username"] = new_session
                CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"已保存，后续扫描将使用会话：{new_session}")
            continue
        if choice == "4":
            subprocess.run([sys.executable, str(SCRIPT_DIR / "bootstrap_config.py")], check=True)
            config = load_config()
            print_summary(config)
            continue
        if choice == "1":
            raw_text = input("\n请粘贴小红书分享文案 / 公众号链接 / 飞书链接：\n").strip()
            if not raw_text:
                print("你还没粘内容。")
                continue
            result = import_manual(raw_text)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            continue
        if choice == "2":
            print(json.dumps(run_wechat_once(), ensure_ascii=False, indent=2))
            continue
        if choice == "3":
            wechat = config.get("wechat") or {}
            if not wechat.get("enabled"):
                print("当前还没启用微信自动扫描，请先重新配置。")
                continue
            workflow = config.get("workflow") or {}
            mode = workflow.get("monitor_mode") or "manual"
            interval_seconds = int(workflow.get("interval_seconds") or 900)
            if mode == "manual":
                print("当前配置是“只跑一次”，现在执行一次。")
                print(json.dumps(run_wechat_once(), ensure_ascii=False, indent=2))
                continue
            if mode == "realtime":
                interval_seconds = 15
            print(f"开始持续扫描。轮询间隔：{interval_seconds} 秒。按 Ctrl+C 停止。")
            try:
                while True:
                    print(json.dumps(run_wechat_once(), ensure_ascii=False, indent=2))
                    time.sleep(interval_seconds)
            except KeyboardInterrupt:
                print("\n已停止持续扫描。")
            continue
        print("输入不对，请重新选。")

def select_session(config: dict):
    wechat = config.get("wechat") or {}
    account_dir = wechat.get("account_dir")
    if not account_dir:
        print("未配置微信账号目录，请先重新配置。")
        return None
    decrypt_module = load_importer("wechat_win_decrypt", SCRIPT_DIR / "wechat_win_decrypt.py")
    cached_key = wechat.get("_cached_key")
    if not cached_key:
        print("需要先提取密钥（微信必须登录，以管理员身份运行）...")
        try:
            cached_key = decrypt_module.extract_wechat_key()
            config["wechat"]["_cached_key"] = cached_key
            CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"密钥提取失败：{e}")
            return None
    print("正在获取会话列表...")
    try:
        sessions = decrypt_module.list_sessions_with_info(account_dir, cached_key)
    except Exception as e:
        print(f"获取会话列表失败：{e}")
        return None
    if not sessions:
        print("没有找到任何会话。")
        return None
    print(f"\n找到 {len(sessions)} 个会话（显示前30个）：")
    display = sessions[:30]
    for i, s in enumerate(display, 1):
        tag = "[群]" if s["is_group"] else "[联系人]"
        print(f"{i:3}. {tag} {s['display_name']} ({s['session_id']})")
    print()
    while True:
        raw = input("请输入序号（或直接输入会话ID，如 filehelper）：").strip()
        if not raw:
            continue
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(display):
                chosen = display[idx]["session_id"]
                print(f"已选择：{display[idx]['display_name']} ({chosen})")
                return chosen
            print("序号超出范围。")
        else:
            print(f"已选择：{raw}")
            return raw


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
