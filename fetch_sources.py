# -*- coding: utf-8 -*-
"""采集 + 解析 + 求新增。

数据源：
  1. dns.txt            —— 每行一个域名，解析 DNS A 记录（仅 IPv4）
  2. zip.cm.edu.kg/all.txt
  3. cfipv4db/high_score_ips.txt
  4. xgonce/Cloudflare_IP/result.csv（必须用 raw 地址）

输出：
  本轮数据源.txt —— 四源合并去重后全部 IP（数值升序）
  新增IP.txt     —— 相对现有 all.txt 的净新增（数值升序）

安全性：任一【外链源】抓取失败 -> 退出码 1，中止本轮，避免用不完整数据污染主表。
（DNS 解析失败的域名不视为致命错误，只记录并在汇报中列出。）
"""
import concurrent.futures as cf
import ipaddress
import os
import re
import socket
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache", "src")
os.makedirs(CACHE, exist_ok=True)
PAT = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
HDR = {"User-Agent": "Mozilla/5.0"}
socket.setdefaulttimeout(6)

key = lambda x: int(ipaddress.ip_address(x))


# ---------- 1. DNS ----------
def resolve(domain):
    got = set()
    try:
        _h, _a, addrs = socket.gethostbyname_ex(domain)
        for a in addrs:
            try:
                ip = ipaddress.ip_address(a)
                if ip.version == 4:
                    got.add(str(ip))
            except ValueError:
                pass
    except Exception:
        pass
    return domain, got


dns_path = os.path.join(BASE, "dns.txt")
domains = []
if os.path.exists(dns_path):
    with open(dns_path, encoding="utf-8", errors="ignore") as fh:
        domains = sorted({l.strip() for l in fh if l.strip()})
print(f"dns.txt domains: {len(domains)}", flush=True)

dns_ips, failed = set(), []
if domains:
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        for dom, got in ex.map(resolve, domains):
            if got:
                dns_ips |= got
            else:
                failed.append(dom)
print(f"DNS resolved IPv4: {len(dns_ips)}  | unresolved domains: {len(failed)}", flush=True)
if failed:
    print("unresolved:", failed, flush=True)


# ---------- 2. 外链源 ----------
SOURCES = {
    "src1_all.txt": ["https://zip.cm.edu.kg/all.txt"],
    "src2_high_score.txt": [
        "https://raw.githubusercontent.com/yuanxiawan/cfipv4db/refs/heads/main/high_score_ips.txt"
    ],
    "src3_result.csv": [
        "https://raw.githubusercontent.com/xgonce/Cloudflare_IP/main/result.csv",
        "https://raw.githubusercontent.com/xgonce/Cloudflare_IP/master/result.csv",
    ],
}


def parse_first_ipv4(text):
    ips = set()
    for line in text.splitlines():
        for m in PAT.findall(line):
            try:
                ip = ipaddress.ip_address(m)
            except ValueError:
                continue
            if ip.version == 4:
                ips.add(str(ip))
                break
    return ips


src_ips = {}
fetch_failed = []
for name, urls in SOURCES.items():
    raw = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers=HDR)
            raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
            print(f"{name}: OK <- {url}", flush=True)
            break
        except Exception as e:
            print(f"{name}: failed {url} -> {e}", flush=True)
    if raw is None:
        fetch_failed.append(name)
        continue
    with open(os.path.join(CACHE, name), "w", encoding="utf-8") as fh:
        fh.write(raw)
    src_ips[name] = parse_first_ipv4(raw)
    print(f"   lines={len(raw.splitlines())} uniqueIPv4={len(src_ips[name])}", flush=True)

if fetch_failed:
    print(f"\n[ABORT] 外链源抓取失败: {fetch_failed}；本轮中止，主表保持原样。", flush=True)
    sys.exit(1)


# ---------- 3. 合并 + 求新增 ----------
union = set(dns_ips)
for s in src_ips.values():
    union |= s

with open(os.path.join(BASE, "本轮数据源.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(sorted(union, key=key)) + "\n")

cur = set()
p_all = os.path.join(BASE, "all.txt")
if os.path.exists(p_all):
    with open(p_all, encoding="utf-8", errors="ignore") as fh:
        cur = {l.strip() for l in fh if l.strip()}

new = union - cur
with open(os.path.join(BASE, "新增IP.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(sorted(new, key=key)) + "\n")

print("\n===== SUMMARY =====", flush=True)
print(f"dns 解析:      {len(dns_ips)} (失败域名 {len(failed)})", flush=True)
for name, s in src_ips.items():
    print(f"{name}: {len(s)}", flush=True)
print(f"四源去重合计:  {len(union)}", flush=True)
print(f"现有 all.txt:  {len(cur)}", flush=True)
print(f"重叠:          {len(union & cur)}", flush=True)
print(f"--> 净新增:    {len(new)}", flush=True)
print(f"合并后总计:    {len(cur | union)}", flush=True)
