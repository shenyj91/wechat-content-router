"""
Full memory scan: databases + URLs + keywords + categorized URLs.
自动找 Weixin.exe PID。等价于 run_frida_scan.py 的参考实现（输出到 output/）。
前置：pip install frida；微信已启动并登录；建议管理员权限。
仅用于处理你自己的微信数据。
"""
import frida, sys, json, time, os, argparse

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
const SQLITE_HEADER_PATTERN = "53 51 4c 69 74 65 20 66 6f 72 6d 61 74 20 33 00";
function readU16BE(arr, off) { return (arr[off] << 8) | arr[off+1]; }
function readU32BE(arr, off) { return (arr[off] << 24) | (arr[off+1] << 16) | (arr[off+2] << 8) | arr[off+3]; }
function parseVarint(arr, pos) { let val=0,shift=0; while(pos<arr.length){const b=arr[pos++];val|=(b&0x7f)<<shift;shift+=7;if(!(b&0x80))break;} return [val,pos]; }
function extractTableNames(pageData) {
    const arr = new Uint8Array(pageData);
    if (arr.length < 108) return [];
    const pageType = arr[100];
    if (pageType !== 0x0D && pageType !== 0x05) return [];
    const numCells = readU16BE(arr, 103);
    const headerSize = (pageType === 0x05) ? 12 : 8;
    const cellPtrStart = 100 + headerSize;
    const names = [];
    for (let i = 0; i < Math.min(numCells, 50); i++) {
        const ptrOff = cellPtrStart + i*2;
        if (ptrOff+2 > arr.length) break;
        const cellOff = readU16BE(arr, ptrOff);
        if (cellOff >= arr.length || cellOff < 100) continue;
        try {
            let pos = cellOff;
            if (pageType === 0x05) pos += 4;
            const [pl,p2]=parseVarint(arr,pos);pos=p2;
            const [ri,p3]=parseVarint(arr,pos);pos=p3;
            const [hl,p4]=parseVarint(arr,pos);pos=p4;
            const hdrEnd = pos+hl;
            const sts=[];
            while(pos<hdrEnd && pos<arr.length){const [st,p5]=parseVarint(arr,pos);pos=p5;sts.push(st);}
            let dpos=hdrEnd;
            for(let si=0;si<sts.length;si++){
                const st=sts[si];
                if(st===0)continue;
                if(st<=4)dpos+=st;
                else if(st===5)dpos+=6;
                else if(st===6||st===7)dpos+=8;
                else if(st>=12&&st%2===0)dpos+=(st-12)>>1;
                else if(st>=13&&st%2===1){const tl=(st-13)>>1;let tx='';for(let t=0;t<tl&&dpos+t<arr.length;t++)tx+=String.fromCharCode(arr[dpos+t]);names.push(tx);dpos+=tl;break;}
            }
        } catch(e){}
    }
    return names;
}
send({type:"status",msg:"Scanning for databases..."});
const ranges = Process.enumerateRanges('r--');
const databases = [];
for (let i=0;i<ranges.length;i++){
    const range=ranges[i];
    if(range.size>50*1024*1024)continue;
    try{
        const matches=Memory.scanSync(range.base,range.size,SQLITE_HEADER_PATTERN);
        for(const m of matches){
            try{
                const page1Buf=m.address.readByteArray(4096);
                const arr=new Uint8Array(page1Buf);
                const pageSize=(arr[16]<<8)|arr[17];
                const dbSize=readU32BE(arr,28);
                const tables=extractTableNames(page1Buf);
                if(tables.length>0) databases.push({addr:m.address.toString(),dbSize,tables});
            }catch(e){}
        }
    }catch(e){}
    if(i%500===0)send({type:"progress",current:i,total:ranges.length,found:databases.length});
}
send({type:"dbs_found",count:databases.length,databases});
send({type:"status",msg:"Scanning for URLs and messages..."});
const URL_PATTERN="68 74 74 70 73 3f 3a 2f 2f";
const allUrls=new Set();
for(let i=0;i<ranges.length;i++){
    const range=ranges[i];
    if(range.size>50*1024*1024)continue;
    try{
        const urlMatches=Memory.scanSync(range.base,range.size,URL_PATTERN);
        for(const m of urlMatches){
            try{
                const buf=m.address.readByteArray(300);
                const arr=new Uint8Array(buf);
                let url='';
                for(let j=0;j<300;j++){const c=arr[j];if(c===0||c===10||c===13||c===32||c===34||c===39||c===60||c===62||c===92||c===124)break;if(c<32||c>126)break;url+=String.fromCharCode(c);}
                if(url.length>15)allUrls.add(url);
            }catch(e){}
        }
    }catch(e){}
    if(i%500===0)send({type:"url_progress",current:i,total:ranges.length,urls:allUrls.size});
}
send({type:"urls",count:allUrls.size,urls:Array.from(allUrls).sort()});
const keywords=["xiaohongshu","xhslink","mp.weixin","feishu","kdocs","obsidian","douban","bilibili","zhihu"];
for(const kw of keywords){
    let total=0;
    for(let i=0;i<Math.min(ranges.length,1000);i++){
        const range=ranges[i];
        if(range.size>50*1024*1024)continue;
        try{
            const hex=kw.split('').map(c=>c.charCodeAt(0).toString(16).padStart(2,'0')).join(' ');
            const kwMatches=Memory.scanSync(range.base,range.size,hex);
            for(const m of kwMatches){
                try{
                    const buf=m.address.readByteArray(500);
                    const arr=new Uint8Array(buf);
                    let text='';
                    for(let j=0;j<500;j++){if(arr[j]>=32&&arr[j]<127)text+=String.fromCharCode(arr[j]);else if(arr[j]>=0x80)text+='%'+arr[j].toString(16);else if(arr[j]===10||arr[j]===13)text+='\\n';else break;}
                    if(text.length>20){send({type:"keyword_hit",keyword:kw,text:text.substring(0,400)});total++;if(total>=5)break;}
                }catch(e){}
            }
        }catch(e){}
        if(total>=5)break;
    }
}
send({type:"all_done"});
"""


def on_message(message, data, store):
    if message["type"] == "send":
        p = message["payload"]
        t = p.get("type")
        if t == "status":
            print(f"[*] {p['msg']}")
        elif t == "progress":
            print(f"[*] DB scan: {p['current']}/{p['total']} ({p['found']} DBs)")
        elif t == "dbs_found":
            store["dbs"].extend(p["databases"])
            print(f"\n[*] Found {p['count']} databases:")
            for db in p["databases"]:
                print(f"  {db['addr']}: dbSize={db['dbSize']}, tables={db['tables'][:8]}")
        elif t == "url_progress":
            print(f"[*] URL scan: {p['current']}/{p['total']} ({p['urls']} URLs)")
        elif t == "urls":
            store["urls"].extend(p["urls"])
            print(f"\n[*] Found {p['count']} unique URLs")
        elif t == "keyword_hit":
            store["keywords"].append({"keyword": p["keyword"], "text": p["text"]})
            print(f"[!] Keyword '{p['keyword']}': {p['text'][:200]}")
        elif t == "all_done":
            print(f"\n[*] All done!")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--pid", type=int, default=None)
    args = ap.parse_args()
    pid = args.pid or find_wechat_pid()
    if pid is None:
        print("[-] 找不到微信进程，请先启动并登录微信。"); sys.exit(1)
    os.makedirs(OUT, exist_ok=True)
    store = {"dbs": [], "urls": [], "keywords": []}
    print(f"[+] 附加到微信 PID {pid}")
    session = frida.attach(pid)
    script = session.create_script(JS_CODE)
    script.on("message", lambda m, d: on_message(m, d, store))
    script.load()
    time.sleep(args.seconds)
    with open(os.path.join(OUT, "databases.json"), "w", encoding="utf-8") as f:
        json.dump(store["dbs"], f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "urls.txt"), "w", encoding="utf-8") as f:
        for u in sorted(store["urls"]):
            f.write(u + "\n")
    with open(os.path.join(OUT, "keyword_hits.json"), "w", encoding="utf-8") as f:
        json.dump(store["keywords"], f, ensure_ascii=False, indent=2)
    interesting = {"xiaohongshu": [], "mp.weixin": [], "feishu": [], "kdocs": [], "other_interesting": [], "all_unique": sorted(store["urls"])}
    for u in store["urls"]:
        low = u.lower()
        if "xiaohongshu" in low or "xhslink" in low: interesting["xiaohongshu"].append(u)
        elif "mp.weixin" in low: interesting["mp.weixin"].append(u)
        elif "feishu" in low: interesting["feishu"].append(u)
        elif "kdocs" in low: interesting["kdocs"].append(u)
        elif any(k in low for k in ["douban","bilibili","zhihu","obsidian","pexels","china.com.cn"]): interesting["other_interesting"].append(u)
    with open(os.path.join(OUT, "categorized_urls.json"), "w", encoding="utf-8") as f:
        json.dump(interesting, f, ensure_ascii=False, indent=2)
    print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
    print(f"Databases found: {len(store['dbs'])}")
    print(f"Unique URLs found: {len(store['urls'])}")
    print(f"Keyword hits: {len(store['keywords'])}")
    for cat, urls in interesting.items():
        if cat == "all_unique": continue
        if urls:
            print(f"  {cat}: {len(urls)} URLs")
            for u in urls[:5]: print(f"    {u[:200]}")
    print(f"\n输出已保存到: {OUT}")


if __name__ == "__main__":
    main()
