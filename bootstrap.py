# -*- coding: utf-8 -*-
"""首次引导：若 all.txt / go.csv 不存在，用种子文件初始化，确保迁移前历史数据不丢。

- all.txt 不存在 -> 用 seed_legacy_ips.txt（仅存在于本机、四个数据源覆盖不到的 IP）初始化
- go.csv  不存在 -> 用 go_seed.csv（834 条带测速指标的记录）+ seed_legacy_ips.txt 初始化
两种情况都只在首次运行生效；之后脚本不再改动已有文件。
"""
import csv
import ipaddress
import os

BASE = os.path.dirname(os.path.abspath(__file__))
ALL = os.path.join(BASE, "all.txt")
GO = os.path.join(BASE, "go.csv")
SEED_IPS = os.path.join(BASE, "seed_legacy_ips.txt")
GO_SEED = os.path.join(BASE, "go_seed.csv")
HDR = ["IP 地址", "平均延迟", "下载速度(MB/s)", "地区码"]

key = lambda x: int(ipaddress.ip_address(x))


def load_ips(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return {l.strip() for l in fh if l.strip()}


# ---- all.txt ----
if not os.path.exists(ALL):
    ips = load_ips(SEED_IPS)
    with open(ALL, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(ips, key=key)) + "\n")
    print(f"[bootstrap] all.txt 初始化为 {len(ips)} 个历史 IP（来自 seed_legacy_ips.txt）")
else:
    print("[bootstrap] all.txt 已存在，跳过初始化")

# ---- go.csv ----
if not os.path.exists(GO):
    best = {}
    if os.path.exists(GO_SEED):
        with open(GO_SEED, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                ip = (r.get("IP 地址") or "").strip()
                if ip:
                    best[ip] = (r.get("平均延迟", ""), r.get("下载速度(MB/s)", ""), r.get("地区码", ""))
    for ip in load_ips(SEED_IPS):
        best.setdefault(ip, ("", "", ""))
    with open(GO, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HDR)
        for ip in sorted(best, key=key):
            lat, spd, area = best[ip]
            w.writerow([ip, lat, spd, area])
    n_metric = sum(1 for v in best.values() if v[0])
    print(f"[bootstrap] go.csv 初始化为 {len(best)} 行（其中带测速指标 {n_metric} 行）")
else:
    print("[bootstrap] go.csv 已存在，跳过初始化")
