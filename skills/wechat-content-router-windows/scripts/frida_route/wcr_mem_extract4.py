"""
Single-pass memory scan: find SQLite headers, extract full databases (base64 chunks).
自动找 Weixin.exe PID。把内存里解密后的数据库整库 dump 为明文 .db（base64 分块传输），
输出到 output/memdb/。与 wcr_mem_extract5.py 类似，仅传输方式不同（base64）。
前置：pip install frida；微信已启动并登录；建议管理员权限。
"""
import frida, sys, json, time, struct, sqlite3, os, base64, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
MEMDB_DIR = os.path.join(HERE, "output", "memdb")


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
    const arr=new Uint8Array(pageData);
    if(arr.length<108)return[];
    const pageType=arr[100];
    if(pageType!==0x0D&&pageType!==0x05)return[];
    const numCells=readU16BE(arr,103);
    const headerSize=(pageType===0x05)?12:8;
    const cellPtrStart=100+headerSize;
    const names=[];
    for(let i=0;i<Math.min(numCells,30);i++){
        const ptrOff=cellPtrStart+i*2;
        if(ptrOff+2>arr.length)break;
        const cellOff=readU16BE(arr,ptrOff);
        if(cellOff>=arr.length||cellOff<100)continue;
        try{
            let pos=cellOff;
            if(pageType===0x05)pos+=4;
            const [pl,p2]=parseVarint(arr,pos);pos=p2;
            const [ri,p3]=parseVarint(arr,pos);pos=p3;
            const [hl,p4]=parseVarint(arr,pos);pos=p4;
            const hdrEnd=pos+hl;
            const sts=[];
            while(pos<hdrEnd&&pos<arr.length){const [st,p5]=parseVarint(arr,pos);pos=p5;sts.push(st);}
            let dpos=hdrEnd;
            for(let si=0;si<sts.length;si++){
                const st=sts[si];
                if(si===1){if(st>=13&&st%2===1){const tl=(st-13)>>1;let tx='';for(let t=0;t<tl&&dpos+t<arr.length;t++)tx+=String.fromCharCode(arr[dpos+t]);names.push(tx);}break;}
                if(st===0)continue;
                if(st<=4)dpos+=st;
                else if(st===5)dpos+=6;
                else if(st===6||st===7)dpos+=8;
                else if(st>=12&&st%2===0)dpos+=(st-12)>>1;
                else if(st>=13&&st%2===1)dpos+=(st-13)>>1;
            }
        }catch(e){}
    }
    return names;
}
function addrToB64(addr, numBytes){const buf=addr.readByteArray(numBytes);const arr=new Uint8Array(buf);let b='';for(let i=0;i<arr.length;i++)b+=String.fromCharCode(arr[i]);return btoa(b);}
send({type:"status",msg:"Scanning memory..."});
const ranges=Process.enumerateRanges('r--');
const found=[];
for(let i=0;i<ranges.length;i++){
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
                if(tables.length>0){
                    found.push({addr:m.address.toString(),dbSize,tables});
                    send({type:"found",data:{addr:m.address.toString(),dbSize,tables}});
                    const totalBytes=Math.max(dbSize,1)*(pageSize===1?65536:pageSize);
                    const readBytes=Math.min(totalBytes,10*1024*1024);
                    try{
                        const b64=addrToB64(m.address,readBytes);
                        const chunkSize=500000;
                        const numChunks=Math.ceil(b64.length/chunkSize);
                        send({type:"db_start",addr:m.address.toString(),tables,totalBytes:readBytes,numChunks});
                        for(let c=0;c<numChunks;c++){
                            const chunk=b64.substring(c*chunkSize,(c+1)*chunkSize);
                            send({type:"db_chunk",addr:m.address.toString(),idx:c,chunk});
                        }
                        send({type:"db_end",addr:m.address.toString()});
                    }catch(e){send({type:"db_fail",addr:m.address.toString(),error:e.toString()});}
                }
            }catch(e){}
        }
    }catch(e){}
    if(i%200===0)send({type:"progress",current:i,total:ranges.length,found:found.length});
}
send({type:"done",found:found.length});
"""


def on_message(message, data, store):
    if message["type"] == "send":
        p = message["payload"]
        t = p.get("type")
        if t == "status":
            print(f"[*] {p['msg']}")
        elif t == "progress":
            print(f"[*] Progress: {p['current']}/{p['total']} ({p['found']} found)")
        elif t == "found":
            d = p["data"]
            print(f"\n[!] Found DB at {d['addr']}: dbSize={d['dbSize']}, tables={d['tables'][:10]}")
            store["dbs"].append(d)
        elif t == "db_start":
            store["chunks"][p["addr"]] = {"tables": p["tables"], "chunks": [""] * p["numChunks"]}
            print(f"  >> Extracting {p['totalBytes']} bytes ({p['numChunks']} chunks)...")
        elif t == "db_chunk":
            if p["addr"] in store["chunks"]:
                store["chunks"][p["addr"]]["chunks"][p["idx"]] = p["chunk"]
        elif t == "db_end":
            print(f"  >> Extraction complete for {p['addr']}")
        elif t == "db_fail":
            print(f"  >> Extraction FAILED: {p['error']}")
        elif t == "done":
            print(f"\n[*] Done! Found {p['found']} databases with tables.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--pid", type=int, default=None)
    args = ap.parse_args()
    pid = args.pid or find_wechat_pid()
    if pid is None:
        print("[-] 找不到微信进程，请先启动并登录微信。"); sys.exit(1)
    os.makedirs(MEMDB_DIR, exist_ok=True)
    store = {"dbs": [], "chunks": {}}
    print(f"[+] 附加到微信 PID {pid}")
    session = frida.attach(pid)
    script = session.create_script(JS_CODE)
    script.on("message", lambda m, d: on_message(m, d, store))
    script.load()
    time.sleep(args.seconds)
    for addr, info in store["chunks"].items():
        if not all(info["chunks"]):
            print(f"[{addr}] 缺块，跳过"); continue
        try:
            db_bytes = base64.b64decode("".join(info["chunks"]))
        except Exception:
            print(f"[{addr}] base64 解码失败"); continue
        out_path = os.path.join(MEMDB_DIR, f"mem_{addr.replace('0x','')}.db")
        with open(out_path, "wb") as f:
            f.write(db_bytes)
        print(f"\n[{addr}] Saved {len(db_bytes)} bytes -> {out_path}")
        try:
            con = sqlite3.connect(out_path)
            tbls = [t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            print(f"  Tables: {tbls}")
            for t in tbls[:3]:
                try:
                    n = con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
                    print(f"    {t}: {n} rows")
                except Exception as e:
                    print(f"    {t}: 读失败 {e}")
            con.close()
            print(f"  *** SUCCESS ***")
        except Exception as e:
            print(f"  sqlite3 error: {e}")
    session.detach()
    print(f"\n[*] 明文库已保存到 {MEMDB_DIR}")


if __name__ == "__main__":
    main()
