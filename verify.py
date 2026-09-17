# -*- coding: utf-8 -*-
"""校验产物一致性。

用法:
  verify.py --only-blank   # 仅检查 all.csv 是否还有空归属；有空 -> 退出码 1
  verify.py                # 全量断言；任一失败 -> 退出码 1

断言:
  1. all.txt 唯一且严格按数值升序
  2. go.csv  唯一且严格按数值升序
  3. 新增IP.txt 中每个 IP 都同时存在于 all.txt / all.csv(IP列表) / go.csv
  4. all.csv 归属列无空白
"""
import csv
import ipaddress
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ALL_TXT = os.path.join(BASE, "all.txt")
ALL_CSV = os.path.join(BASE, "all.csv")
GO_CSV = os.path.join(BASE, "go.csv")
NEW_TXT = os.path.join(BASE, "新增IP.txt")
only_blank = "--only-blank" in sys.argv


def read_ips(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return [l.strip() for l in fh if l.strip()]


def nums(items):
    return [int(ipaddress.ip_address(x)) for x in items]


def count_blank():
    if not os.path.exists(ALL_CSV):
        return -1
    n = 0
    with open(ALL_CSV, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            v = (r.get("CIDR归属厂商") or "").strip()
            l = (r.get("CIDR归属地") or "").strip()
            if not (v or l):
                n += 1
    return n


blank = count_blank()
print(f"[check] all.csv 空归属行数: {blank}")
if only_blank:
    sys.exit(0 if blank == 0 else 1)

fail = False
allips = read_ips(ALL_TXT)
if len(allips) != len(set(allips)):
    print(f"[FAIL] all.txt 有重复: {len(allips)} 行 / {len(set(allips))} 唯一")
    fail = True
else:
    print(f"[OK]   all.txt 唯一: {len(allips)}")
k = nums(allips)
if k != sorted(k):
    print("[FAIL] all.txt 未按数值升序")
    fail = True
else:
    print("[OK]   all.txt 数值升序")

g = []
if os.path.exists(GO_CSV):
    with open(GO_CSV, encoding="utf-8-sig", newline="") as fh:
        g = [(r.get("IP 地址") or "").strip() for r in csv.DictReader(fh)]
    g = [x for x in g if x]
    if len(g) != len(set(g)):
        print(f"[FAIL] go.csv 有重复: {len(g)} / {len(set(g))}")
        fail = True
    else:
        print(f"[OK]   go.csv 唯一: {len(g)}")
    gk = nums(g)
    if gk != sorted(gk):
        print("[FAIL] go.csv 未按数值升序")
        fail = True
    else:
        print("[OK]   go.csv 数值升序")
else:
    print("[WARN] go.csv 不存在")

new = set(read_ips(NEW_TXT))
if new:
    a = set(allips)
    csvips = set()
    if os.path.exists(ALL_CSV):
        with open(ALL_CSV, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                csvips.update((r.get("IP列表") or "").split(";"))
    gset = set(g)
    miss = []
    if not new <= a:
        miss.append("all.txt")
    if not new <= csvips:
        miss.append("all.csv")
    if not new <= gset:
        miss.append("go.csv")
    if miss:
        print(f"[FAIL] 新增IP.txt 未完全进入: {miss}")
        fail = True
    else:
        print(f"[OK]   新增IP.txt {len(new)} 个全部进入 all.txt / all.csv / go.csv")
else:
    print("[OK]   新增IP.txt 为空（本轮无新增）")

if blank != 0:
    print(f"[FAIL] all.csv 仍有 {blank} 行空归属")
    fail = True

print("[RESULT]", "FAIL" if fail else "PASS")
sys.exit(1 if fail else 0)
