# -*- coding: utf-8 -*-
"""按 /24 归并 all.txt，补全每个 CIDR 的归属厂商/归属地，写出 all.csv。

要点：
- 归属缓存直接复用已有 all.csv（跳过空归属），只查询新出现的 CIDR；跨运行免重复查询。
- .enrich_cache.json 为运行内断点续跑缓存（每批落盘，不入库）。
- ip-api 免费接口约 20% 请求会随机挂起：采用 10 秒快速超时 + 轻量重试(<=3 次)，
  绝不用长退避重试（否则会空转数十分钟）。失败的批次留待下一次运行重试。
"""
import csv
import ipaddress
import json
import os
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ALL_TXT = os.path.join(BASE, "all.txt")
ALL_CSV = os.path.join(BASE, "all.csv")
CACHE_JSON = os.path.join(BASE, ".enrich_cache.json")
API = "http://ip-api.com/batch?lang=zh-CN&fields=status,query,country,regionName,city,isp,org,as"
FIX = {"香港": "中国香港", "台湾": "中国台湾", "澳门": "中国澳门", "澳門": "中国澳门"}
BATCH, SLEEP, TIMEOUT = 100, 4, 10

ven = lambda it: it.get("org") or it.get("isp") or it.get("as") or ""


def loc(it):
    s = " ".join(p for p in (it.get("country", ""), it.get("regionName", ""), it.get("city", "")) if p)
    t = s.split(" ")
    if t and t[0] in FIX:
        t[0] = FIX[t[0]]
        s = " ".join(t)
    return s


_ok = lambda v: bool(v) and (v[0] or v[1])

# ---- 缓存：JSON 断点 + 已有 all.csv（空归属视为未解析）----
cache = {}
if os.path.exists(CACHE_JSON):
    try:
        with open(CACHE_JSON, encoding="utf-8") as fh:
            cache.update({k: v for k, v in json.load(fh).items() if _ok(v)})
    except Exception:
        pass
if os.path.exists(ALL_CSV):
    with open(ALL_CSV, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            c = (r.get("CIDR") or "").strip()
            v = [r.get("CIDR归属厂商", ""), r.get("CIDR归属地", "")]
            if c and c not in cache and _ok(v):
                cache[c] = v
print(f"cache loaded: {len(cache)}", flush=True)

# ---- 分组 ----
ips = {l.strip() for l in open(ALL_TXT, encoding="utf-8") if l.strip()}
groups = {}
for ip in ips:
    groups.setdefault(str(ipaddress.ip_network(f"{ip}/24", strict=False)), []).append(ip)
ordered = sorted(
    groups.items(),
    key=lambda kv: (-len(kv[1]), int(ipaddress.ip_network(kv[0]).network_address)),
)
print(f"union IPs: {len(ips)}, /24 CIDRs: {len(ordered)}", flush=True)

todo = [mem[0] for net, mem in ordered if net not in cache]
print(f"to query: {len(todo)}", flush=True)


def query(chunk, tries=3):
    for a in range(tries):
        try:
            req = urllib.request.Request(
                API, data=json.dumps(chunk).encode(), headers={"Content-Type": "application/json"}
            )
            d = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))
            if isinstance(d, dict):
                raise RuntimeError(d.get("message", "fail"))
            return d
        except Exception:
            if a == tries - 1:
                return None
            time.sleep(3)
    return None


def write_cache():
    with open(CACHE_JSON, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)


ok = bad = 0
nb = (len(todo) + BATCH - 1) // BATCH
t0 = time.time()
for i in range(0, len(todo), BATCH):
    chunk = todo[i:i + BATCH]
    data = query(chunk)
    if data is None:
        bad += len(chunk)
    else:
        for it in data:
            q = it.get("query")
            if not q:
                continue
            k = str(ipaddress.ip_network(f"{q}/24", strict=False))
            cache[k] = [ven(it), loc(it)] if it.get("status") == "success" else ["", ""]
        ok += len(chunk)
    write_cache()
    print(f"batch {i // BATCH + 1}/{nb} ok={ok} bad={bad} elapsed={int(time.time() - t0)}s", flush=True)
    time.sleep(SLEEP)

# ---- 写 all.csv ----
with open(ALL_CSV, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["序号", "CIDR归属厂商", "CIDR归属地", "CIDR", "IP数量", "IP列表"])
    for idx, (net, mem) in enumerate(ordered, start=1):
        v, l = cache.get(net, ["", ""])
        w.writerow([str(idx), v, l, net, str(len(mem)), ";".join(mem)])

resolved = sum(1 for net, _ in ordered if net in cache)
print(f"\nDONE. CIDR={len(ordered)} resolved={resolved} bad={bad} elapsed={int(time.time() - t0)}s", flush=True)
