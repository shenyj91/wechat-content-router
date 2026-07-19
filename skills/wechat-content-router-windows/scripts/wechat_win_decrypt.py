#!/usr/bin/env python3
"""
Windows微信4.x解密模块
通过Node.js桥接脚本调用WxLens的解密能力
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BRIDGE_SCRIPT = SCRIPT_DIR / "wechat_bridge.mjs"

XHS_RE = re.compile(r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s<>\"]+")
MP_RE = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s<>\"]+")
FEISHU_RE = re.compile(r"https?://(?:[\w-]+\.)?feishu\.cn/(?:wiki|docx)/[^\s<>\"]+")


def _run_bridge(command: str, *args: str, timeout: int = 60) -> dict:
    """调用Node.js桥接脚本"""
    node_cmd = os.environ.get("NODEJS_PATH") or "node"
    cmd = [node_cmd, str(BRIDGE_SCRIPT), command, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SCRIPT_DIR),
    )

    stdout = result.stdout.strip()
    json_lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not json_lines:
        raise RuntimeError(
            f"Bridge返回无效输出:\nstdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )

    data = json.loads(json_lines[-1])
    if not data.get("success"):
        raise RuntimeError(f"Bridge错误: {data.get('error', '未知错误')}")
    return data


def list_all_accounts() -> list[dict]:
    """
    列出所有微信4.x账号目录
    返回: [{account_dir, wxid, mtime}]
    """
    data = _run_bridge("find_account_dir", timeout=10)
    all_accounts = data.get("allAccounts", [])
    if not all_accounts:
        all_accounts = [data["accountDir"]]

    accounts = []
    for acc_dir in all_accounts:
        p = Path(acc_dir)
        wxid = p.name
        # 去掉wxid后面的随机后缀 _xxxx
        wxid_clean = re.sub(r"_[a-zA-Z0-9]{4}$", "", wxid)
        try:
            mtime = p.stat().st_mtime
        except Exception:
            mtime = 0
        accounts.append({
            "account_dir": str(p),
            "wxid": wxid_clean,
            "raw_name": wxid,
            "mtime": mtime,
        })

    # 按修改时间倒序（最近使用的在前）
    accounts.sort(key=lambda a: a["mtime"], reverse=True)
    return accounts


def extract_wechat_key(timeout: int = 30) -> str:
    """从微信进程提取密钥（需要管理员权限）"""
    print("正在从微信进程提取密钥（需要管理员权限）...")
    data = _run_bridge("extract_key", timeout=timeout + 10)
    key = data.get("key", "")
    if not key or len(key) != 64:
        raise RuntimeError(f"提取到的密钥格式不对: {key}")
    print(f"密钥提取成功: {key[:8]}...")
    return key


def find_account_dir() -> tuple[str, list[str]]:
    """自动找微信4.x账号目录（兼容旧代码）"""
    data = _run_bridge("find_account_dir", timeout=10)
    return data["accountDir"], data.get("allAccounts", [])


def get_sessions(account_dir: str, hex_key: str) -> list[dict]:
    """获取所有会话列表"""
    data = _run_bridge("get_sessions", account_dir, hex_key, timeout=30)
    return data.get("sessions", [])


def get_messages(
    account_dir: str,
    hex_key: str,
    session_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """获取某会话的消息"""
    data = _run_bridge(
        "get_messages",
        account_dir,
        hex_key,
        session_id,
        str(limit),
        str(offset),
        timeout=30,
    )
    return data.get("messages", [])


def get_recent_links(
    account_dir: str,
    hex_key: str,
    session_id: str = "filehelper",
    limit: int = 50,
) -> list[dict]:
    """从指定会话提取最近消息里的链接"""
    messages = get_messages(account_dir, hex_key, session_id, limit)
    results = []

    for msg in messages:
        content = msg.get("content") or msg.get("message") or ""
        if not content:
            continue
        for link_type, pattern in (("xhs", XHS_RE), ("mp", MP_RE), ("feishu", FEISHU_RE)):
            match = pattern.search(content)
            if match:
                results.append({
                    "type": link_type,
                    "url": match.group(0).replace("&amp;", "&"),
                    "raw_text": content,
                    "create_time": msg.get("createTime") or msg.get("create_time") or 0,
                    "local_id": msg.get("localId") or msg.get("local_id") or 0,
                })
                break

    return results


def decrypt_and_get_links(
    session_id: str = "filehelper",
    limit: int = 50,
    key: str | None = None,
    account_dir: str | None = None,
) -> dict:
    """一键完成：账号目录 → 提取密钥 → 读取链接"""
    if not account_dir:
        raise RuntimeError(
            "未指定account_dir。请先运行 use_router.py 完成账号选择配置。"
        )

    if not key:
        key = extract_wechat_key()

    print(f"正在读取会话 [{session_id}] 的最近消息...")
    links = get_recent_links(account_dir, key, session_id, limit)
    print(f"找到 {len(links)} 条链接")

    return {
        "account_dir": account_dir,
        "key": key,
        "session_id": session_id,
        "links": links,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-accounts", action="store_true", help="列出所有账号")
    parser.add_argument("--session", default="filehelper")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--key")
    parser.add_argument("--account-dir")
    args = parser.parse_args()

    try:
        if args.list_accounts:
            accounts = list_all_accounts()
            print(json.dumps(accounts, ensure_ascii=False, indent=2))
            return

        result = decrypt_and_get_links(
            session_id=args.session,
            limit=args.limit,
            key=args.key,
            account_dir=args.account_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
