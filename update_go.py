# -*- coding: utf-8 -*-
"""把指定 IP 列表文件的 IP 并入 go.csv（新增行指标列为空），按 IP 数值升序去重。

用法: update_go.py [源IP列表.txt]      # 默认 新增IP.txt
同一 IP 出现多次时保留【平均延迟最低】的一条（无指标视为无穷大，不会覆盖已有指标）。
"""
import csv
import ipaddress
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
GO = os.path.join(BASE, "go.csv")
SUP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "新增IP.txt")
if not os.path.isabs(SUP):
    SUP = os.path.join(BASE, SUP)
HDR = ["IP 地址", "平均延迟", "下载速度(MB/s)", "地区码"]

best = {}


def add(ip_s, lat="", spd="", area=""):
    ip_s = (ip_s or "").strip()
    if not ip_s:
        return
    try:
        ipa = ipaddress.ip_address(ip_s)
    except ValueError:
        return
    if ipa.version != 4:
        return
    try:
        latv = float(lat)
    except (ValueError, TypeError):
        latv = float("inf")
    k = str(ipa)
    cur = best.get(k)
    if cur is None or latv < cur[0]:
        best[k] = (latv, (lat or "").strip(), (spd or "").strip(), (area or "").strip())


before = 0
if os.path.exists(GO):
    with open(GO, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            add(r.get("IP 地址"), r.get("平均延迟"), r.get("下载速度(MB/s)"), r.get("地区码"))
            before += 1

added = 0
if os.path.exists(SUP):
    with open(SUP, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            try:
                k = str(ipaddress.ip_address(s))
            except ValueError:
                continue
            if k not in best:
                added += 1
            add(s)
else:
    print(f"[WARN] 源文件不存在: {SUP}")

ordered = sorted(best.items(), key=lambda kv: int(ipaddress.ip_address(kv[0])))
with open(GO, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(HDR)
    for ip, (_, lat, spd, area) in ordered:
        w.writerow([ip, lat, spd, area])

print(f"go.csv 原有 {before} 行 -> 新增 {added} -> 共 {len(ordered)} 行")
