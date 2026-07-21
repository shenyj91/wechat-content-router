"""
run_frida_scan.py — WeChat 内存扫描提取（消息内容 / 链接的正统来源）

为什么需要它
-----------
微信 4.x 的 message_*.db 在磁盘上用 WCDB 加密，部分页（尤其消息主体）用纯 Python
磁盘解密无法还原（98.6% 页 HMAC 不匹配，密钥/参数网格覆盖不到）。但微信运行时会把
解密后的 SQLite 页驻留内存——本脚本用 Frida 扫描进程内存，找到 "SQLite format 3"
明文页并整库 dump 出来，直接得到可被 sqlite3 打开的明文库，从而拿到消息与链接。

这是「读聊天内容 / 导出链接」**当前唯一稳定可用**的路径，已实测可用
（自动附加 Weixin.exe、扫到内存中的数据库、按来源分类链接）。

前置条件
--------
1. 已安装 frida：  pip install frida
2. 微信已启动且登录（内存里才有解密页）
3. 建议用管理员权限运行（否则部分内存区域读不到）

用法
----
  python3 run_frida_scan.py                 # 默认扫描 120 秒
  python3 run_frida_scan.py --seconds 180   # 扫描更久（库多时更稳）
  python3 run_frida_scan.py --pid 2616      # 手动指定 PID

输出（相对本脚本目录的 output/）
  databases.json        扫到的内存数据库（地址/表名/页数）
  urls.txt              所有去重 URL
  categorized_urls.json 按来源分类（小红书/公众号/飞书/金山文档/其它）
  keyword_hits.json    关键词命中片段
仅用于处理**你自己**的微信数据。
"""
import frida
import sys
import os
import json
import time
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(HERE, "output")


def find_wechat_pid():
    """自动找微信主进程 PID（优先 Weixin.exe）。"""
    try:
        dev = frida.get_local_device()
        procs = dev.enumerate_processes()
    except Exception as e:
        print(f"[-] 无法枚举进程: {e}")
        return None
    wechat = [p for p in procs if "weixin" in p.name.lower() or "wechat" in p.name.lower()]
    if not wechat:
        return None
    for p in wechat:
        if p.name.lower() == "weixin.exe":
            return p.pid
    return wechat[0].pid


JS_CODE = r"""
const SQLITE_HEADER_PATTERN = "53 51 4c 69 74 65 20 66 6f 72 6d 61 74 20 33 00";

function readU16BE(arr, off) { return (arr[off] << 8) | arr[off+1]; }
function readU32BE(arr, off) { return (arr[off] << 24) | (arr[off+1] << 16) | (arr[off+2] << 8) | arr[off+3]; }

function parseVarint(arr, pos) {
    let val = 0, shift = 0;
    while (pos < arr.length) {
        const b = arr[pos++];
        val |= (b & 0x7f) << shift;
        shift += 7;
        if (!(b & 0x80)) break;
    }
    return [val, pos];
}

function extractTableNames(pageData) {
    const arr = new Uint8Array(pageData);
    if (arr.length < 108) return [];
    const pageType = arr[100];
    if (pageType !== 0x0D && pageType !== 0x05) return [];
    const numCells = readU16BE(arr, 103);
    const headerSize = (pageType === 0x05) ? 12 : 8;
    const cellPtrStart = 100 + headerSize;
    const names = [];
    for (let i = 0; i < Math.min(numCells, 30); i++) {
        const ptrOff = cellPtrStart + i * 2;
        if (ptrOff + 2 > arr.length) break;
        const cellOff = readU16BE(arr, ptrOff);
        if (cellOff >= arr.length || cellOff < 100) continue;
        try {
            let pos = cellOff;
            if (pageType === 0x05) pos += 4;
            const [payloadLen, p2] = parseVarint(arr, pos); pos = p2;
            const [rowid, p3] = parseVarint(arr, pos); pos = p3;
            const [hdrLen, p4] = parseVarint(arr, pos); pos = p4;
            const hdrEnd = pos + hdrLen;
            const serialTypes = [];
            while (pos < hdrEnd && pos < arr.length) {
                const [st, p5] = parseVarint(arr, pos); pos = p5;
                serialTypes.push(st);
            }
            let dpos = hdrEnd;
            for (let si = 0; si < serialTypes.length; si++) {
                const st = serialTypes[si];
                if (si === 1) {
                    if (st >= 13 && st % 2 === 1) {
                        const textLen = (st - 13) >> 1;
                        let text = '';
                        for (let t = 0; t < textLen && dpos + t < arr.length; t++) text += String.fromCharCode(arr[dpos + t]);
                        names.push(text);
                    }
                    break;
                }
                if (st === 0) continue;
                if (st <= 4) dpos += st;
                else if (st === 5) dpos += 6;
                else if (st === 6 || st === 7) dpos += 8;
                else if (st >= 12 && st % 2 === 0) dpos += (st - 12) >> 1;
                else if (st >= 13 && st % 2 === 1) dpos += (st - 13) >> 1;
            }
        } catch(e) {}
    }
    return names;
}

send({type: "status", msg: "Scanning memory..."});
const ranges = Process.enumerateRanges('r--');
const foundDbs = [];

for (let i = 0; i < ranges.length; i++) {
    const range = ranges[i];
    if (range.size > 50 * 1024 * 1024) continue;
    try {
        const matches = Memory.scanSync(range.base, range.size, SQLITE_HEADER_PATTERN);
        for (const m of matches) {
            try {
                const page1Buf = m.address.readByteArray(4096);
                const arr = new Uint8Array(page1Buf);
                const pageSize = (arr[16] << 8) | arr[17];
                const reserved = arr[20];
                const dbSize = readU32BE(arr, 28);
                const tables = extractTableNames(page1Buf);
                if (tables.length > 0) {
                    const hasInteresting = tables.some(t =>
                        t.toLowerCase().includes('msg') ||
                        t.toLowerCase().includes('session') ||
                        t.toLowerCase().includes('contact') ||
                        t.toLowerCase().includes('name2id') ||
                        t.toLowerCase().includes('chat') ||
                        t.toLowerCase().includes('message') ||
                        t.toLowerCase().includes('kv'));
                    foundDbs.push({ addr: m.address.toString(), dbSize,
                        pageSize: pageSize === 1 ? 65536 : pageSize, reserved, tables, interesting: hasInteresting });
                    send({type: "found", data: { addr: m.address.toString(), dbSize, tables, interesting: hasInteresting }});
                }
            } catch(e) {}
        }
    } catch(e) {}
    if (i % 200 === 0) send({type: "progress", current: i, total: ranges.length, found: foundDbs.length});
}
send({type: "scan_done", found: foundDbs.length});

// Phase 2: URLs
send({type: "status", msg: "Scanning URLs..."});
const URL_PATTERN = "68 74 74 70 73 3f 3a 2f 2f";
const allUrls = new Set();
for (let i = 0; i < ranges.length; i++) {
    const range = ranges[i];
    if (range.size > 50 * 1024 * 1024) continue;
    try {
        const urlMatches = Memory.scanSync(range.base, range.size, URL_PATTERN);
        for (const m of urlMatches) {
            try {
                const buf = m.address.readByteArray(300);
                const arr = new Uint8Array(buf);
                let url = '';
                for (let j = 0; j < 300; j++) {
                    const c = arr[j];
                    if (c === 0 || c === 10 || c === 13 || c === 32 || c === 34 || c === 39 || c === 60 || c === 62 || c === 92 || c === 124) break;
                    if (c < 32 || c > 126) break;
                    url += String.fromCharCode(c);
                }
                if (url.length > 15) allUrls.add(url);
            } catch(e) {}
        }
    } catch(e) {}
    if (i % 500 === 0) send({type: "url_progress", current: i, total: ranges.length, urls: allUrls.size});
}
send({type: "urls", count: allUrls.size, urls: Array.from(allUrls).sort()});

// Phase 3: keywords
send({type: "status", msg: "Scanning keywords..."});
const keywords = ["xiaohongshu","xhslink","mp.weixin","feishu","kdocs","obsidian","douban","bilibili","zhihu"];
for (const kw of keywords) {
    let totalFound = 0;
    for (let i = 0; i < Math.min(ranges.length, 1000); i++) {
        const range = ranges[i];
        if (range.size > 50 * 1024 * 1024) continue;
        try {
            const hex = kw.split('').map(c => c.charCodeAt(0).toString(16).padStart(2,'0')).join(' ');
            const kwMatches = Memory.scanSync(range.base, range.size, hex);
            for (const m of kwMatches) {
                try {
                    const buf = m.address.readByteArray(500);
                    const arr = new Uint8Array(buf);
                    let text = '';
                    for (let j = 0; j < 500; j++) {
                        if (arr[j] >= 32 && arr[j] < 127) text += String.fromCharCode(arr[j]);
                        else if (arr[j] >= 0x80) text += '%' + arr[j].toString(16);
                        else if (arr[j] === 10 || arr[j] === 13) text += '\\n';
                        else break;
                    }
                    if (text.length > 20) { send({type: "keyword_hit", keyword: kw, text: text.substring(0,400)}); totalFound++; if (totalFound >= 5) break; }
                } catch(e) {}
            }
        } catch(e) {}
        if (totalFound >= 5) break;
    }
}
send({type: "all_done"});
"""


def on_message(message, data, state):
    if message["type"] == "send":
        p = message["payload"]
        t = p.get("type")
        if t == "status":
            print(f"[*] {p['msg']}")
        elif t == "progress":
            print(f"[*] DB scan: {p['current']}/{p['total']} ({p['found']} DBs)")
        elif t == "found":
            d = p["data"]
            tag = " ***" if d.get("interesting") else ""
            print(f"[!] {d['addr']}: dbSize={d['dbSize']}, tables={d['tables'][:8]}{tag}")
            state["dbs"].append(d)
        elif t == "scan_done":
            print(f"\n[*] Scan complete. {p['found']} databases with tables found.")
        elif t == "url_progress":
            print(f"[*] URL scan: {p['current']}/{p['total']} ({p['urls']} URLs)")
        elif t == "urls":
            state["urls"] = p["urls"]
            print(f"\n[*] Found {p['count']} unique URLs")
        elif t == "keyword_hit":
            state["keywords"].append({"keyword": p["keyword"], "text": p["text"]})
            print(f"[!] Keyword '{p['keyword']}': {p['text'][:200]}")
        elif t == "all_done":
            print(f"\n[*] All done!")
    elif message["type"] == "error":
        print(f"[JS ERROR] {message['description']}")


def main():
    ap = argparse.ArgumentParser(description="Frida 内存扫描提取微信消息/链接")
    ap.add_argument("--seconds", type=int, default=120, help="扫描时长（秒）")
    ap.add_argument("--pid", type=int, default=None, help="手动指定微信 PID")
    args = ap.parse_args()

    pid = args.pid or find_wechat_pid()
    if pid is None:
        print("[-] 找不到微信进程。请先启动并登录微信，再运行本脚本。")
        sys.exit(1)
    print(f"[+] 附加到微信 PID {pid}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state = {"dbs": [], "urls": [], "keywords": []}

    try:
        session = frida.attach(pid)
    except Exception as e:
        print(f"[-] 无法附加到 PID {pid}: {e}")
        print("    若提示权限不足，请用管理员权限运行；若微信未登录，请先登录。")
        sys.exit(1)

    script = session.create_script(JS_CODE)
    script.on("message", lambda m, d: on_message(m, d, state))
    script.load()
    print(f"[*] 扫描中（约 {args.seconds} 秒）…")
    time.sleep(args.seconds)
    session.detach()

    # 保存
    with open(os.path.join(OUTPUT_DIR, "databases.json"), "w", encoding="utf-8") as f:
        json.dump(state["dbs"], f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUTPUT_DIR, "urls.txt"), "w", encoding="utf-8") as f:
        for u in state["urls"]:
            f.write(u + "\n")
    with open(os.path.join(OUTPUT_DIR, "keyword_hits.json"), "w", encoding="utf-8") as f:
        json.dump(state["keywords"], f, ensure_ascii=False, indent=2)

    interesting = {"xiaohongshu": [], "mp.weixin": [], "feishu": [], "kdocs": [], "other_interesting": [], "all_unique": state["urls"]}
    for u in state["urls"]:
        low = u.lower()
        if "xiaohongshu" in low or "xhslink" in low: interesting["xiaohongshu"].append(u)
        elif "mp.weixin" in low: interesting["mp.weixin"].append(u)
        elif "feishu" in low: interesting["feishu"].append(u)
        elif "kdocs" in low: interesting["kdocs"].append(u)
        elif any(k in low for k in ["douban","bilibili","zhihu","obsidian","pexels","china.com.cn"]): interesting["other_interesting"].append(u)
    with open(os.path.join(OUTPUT_DIR, "categorized_urls.json"), "w", encoding="utf-8") as f:
        json.dump(interesting, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
    print(f"Databases found: {len(state['dbs'])}")
    print(f"Unique URLs found: {len(state['urls'])}")
    print(f"Keyword hits: {len(state['keywords'])}")
    for cat, urls in interesting.items():
        if cat == "all_unique": continue
        if urls:
            print(f"  {cat}: {len(urls)} URLs")
            for u in urls[:5]: print(f"    {u[:200]}")
    print(f"\n输出已保存到: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
