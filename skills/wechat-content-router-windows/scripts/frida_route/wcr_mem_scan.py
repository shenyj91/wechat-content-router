"""
Scan WeChat process memory for decrypted SQLite page-1 headers (DB-only scan).
自动找 Weixin.exe PID。仅列出内存中解密后的数据库（地址/页大小/reserved/模块），
不提取内容——用于快速确认「微信是否把某库解密在内存里」。
前置：pip install frida；微信已启动并登录。
"""
import frida, sys, json, time, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")


def find_wechat_pid():
    try:
        dev = frida.get_local_device()
        procs = dev.enumerate_processes()
    except Exception:
        return None
    w = [p for p in procs if "weixin" in p.name.lower() or "wechat" in p.name.lower()]
    if not w:
        return None
    for p in w:
        if p.name.lower() == "weixin.exe":
            return p.pid
    return w[0].pid


JS_CODE = r"""
const SQLITE_HEADER = "SQLite format 3\x00";
const HEADER_BYTES = [];
for (let i = 0; i < SQLITE_HEADER.length; i++) HEADER_BYTES.push(SQLITE_HEADER.charCodeAt(i));
const ranges = Process.enumerateRanges('r--');
const results = [];
send({type: "status", msg: "Scanning " + ranges.length + " readable memory ranges..."});
for (let i = 0; i < ranges.length; i++) {
    const range = ranges[i];
    if (range.size > 50 * 1024 * 1024) { send({type:"status", msg:"Skipping large range: " + range.base}); continue; }
    try {
        const matches = Memory.scanSync(range.base, range.size, "53 51 4c 69 74 65 20 66 6f 72 6d 61 74 20 33 00");
        for (const m of matches) {
            const header = m.address.readByteArray(100);
            const arr = new Uint8Array(header);
            let pageSize = (arr[16] << 8) | arr[17];
            if (pageSize === 1) pageSize = 65536;
            const reserved = arr[20];
            let moduleInfo = "";
            try { const mod = Process.findModuleByAddress(m.address); if (mod) moduleInfo = mod.name + "+" + m.address.sub(mod.base); } catch(e) {}
            results.push({ addr: m.address.toString(), pageSize, reserved, module: moduleInfo });
            send({type: "found", data: { addr: m.address.toString(), pageSize, reserved, module: moduleInfo }});
        }
    } catch(e) {}
    if (i % 100 === 0) send({type: "progress", current: i, total: ranges.length});
}
send({type: "done", count: results.length});
"""


def on_message(message, data, store):
    if message["type"] == "send":
        p = message["payload"]
        if p["type"] == "status":
            print(f"[*] {p['msg']}")
        elif p["type"] == "progress":
            print(f"[*] Progress: {p['current']}/{p['total']}")
        elif p["type"] == "found":
            d = p["data"]
            print(f"\n[!] FOUND SQLite header at {d['addr']}")
            print(f"    Page size: {d['pageSize']}  Reserved: {d['reserved']}  Module: {d['module']}")
            store.append(d)
        elif p["type"] == "done":
            print(f"\n[*] Done! Found {p['count']} matches.")


def main():
    pid = find_wechat_pid()
    if pid is None:
        print("[-] 找不到微信进程，请先启动并登录微信。"); sys.exit(1)
    os.makedirs(OUT, exist_ok=True)
    store = []
    print(f"[+] 附加到微信 PID {pid}")
    session = frida.attach(pid)
    script = session.create_script(JS_CODE)
    script.on("message", lambda m, d: on_message(m, d, store))
    script.load()
    time.sleep(30)
    session.detach()
    with open(os.path.join(OUT, "mem_scan.json"), "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    print(f"[*] 结果已保存到 {os.path.join(OUT, 'mem_scan.json')}")


if __name__ == "__main__":
    main()
