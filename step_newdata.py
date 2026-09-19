# -*- coding: utf-8 -*-
"""Step 0 (conditional): merge speed-test CSVs under 新数据/ into go.csv,
then incrementally push their IPs into all.txt and regenerate all.csv.

- No CSV found under 新数据/  -> print SKIP and exit 0 (pipeline continues).
- Idempotent: de-dupes by IP, so re-running with the same CSVs changes nothing.

Rules (agreed with the user):
  * keep only 4 columns: IP 地址 / 平均延迟 / 下载速度(MB/s) / 地区码
    (drop 已发送 / 已接收 / 丢包率 / 端口)
  * one row per IP; a row WITH numeric 平均延迟 beats one without;
    among numeric rows the lowest 平均延迟 wins; tie -> higher 下载速度;
    still tie -> row that carries a 地区码
  * output sorted by IP ascending, UTF-8 with BOM
"""
import csv
import datetime
import ipaddress
import os
import re
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
NEW_DIR = os.path.join(BASE, "新数据")
GO = os.path.join(BASE, "go.csv")
ALL_TXT = os.path.join(BASE, "all.txt")
ALL_CSV = os.path.join(BASE, "all.csv")
ENRICH = os.path.join(BASE, "enrich_cidrs.py")
NEW_IPS_OUT = os.path.join(BASE, "新增IP_新数据.txt")
# 备份目录：本地项目沿用 .workbuddy/_backup；云端仓库用（已被 gitignore 的）.cache/_backup，
# 避免把备份文件提交进版本库。
BAK = (os.path.join(BASE, ".workbuddy", "_backup")
       if os.path.isdir(os.path.join(BASE, ".workbuddy"))
       else os.path.join(BASE, ".cache", "_backup"))

KEEP = ["IP 地址", "平均延迟", "下载速度(MB/s)", "地区码"]
IP_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


# ---------- helpers ----------
def find_csvs(root):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".csv"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def pick_col(fieldnames, *keywords):
    """Fuzzy-match a column key by keyword (headers vary slightly across exports)."""
    for kw in keywords:
        for k in fieldnames:
            if k and kw in k:
                return k
    return None


def num(v):
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None


def make_cand(lat_str, spd_str, area_str):
    """Comparable row: (has_metric, -latency, speed, has_area) — bigger is better."""
    lat = num(lat_str)
    return (1 if lat is not None else 0,
            -(lat if lat is not None else 0.0),
            num(spd_str) or 0.0,
            1 if area_str else 0)


def out_row(cand, lat_str, spd_str, area_str):
    return (cand, {"平均延迟": lat_str, "下载速度(MB/s)": spd_str, "地区码": area_str})


def better(cand, old_cand):
    return old_cand is None or cand > old_cand


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup(path, tag):
    os.makedirs(BAK, exist_ok=True)
    if os.path.exists(path):
        dst = os.path.join(BAK, f"{tag}.{stamp()}.bak")
        shutil.copy2(path, dst)
        return dst
    return None


# ---------- 1. discover CSVs ----------
if not os.path.isdir(NEW_DIR):
    print(f"SKIP: 目录不存在 {NEW_DIR} —— 跳过新数据合并步骤")
    sys.exit(0)

csv_files = find_csvs(NEW_DIR)
if not csv_files:
    print(f"SKIP: {NEW_DIR} 下没有 CSV 文件 —— 跳过新数据合并步骤")
    sys.exit(0)

print(f"新数据 CSV: {len(csv_files)} 个")


# ---------- 2. parse all CSVs, keep best row per IP ----------
best = {}          # ip -> (cand, row_dict)
rows_read = 0
bad_ip = 0
no_metric = 0
odd_files = 0

for p in csv_files:
    with open(p, "r", encoding="utf-8-sig", newline="") as fh:
        text = fh.read()
    if not text.strip():
        continue
    lines = text.splitlines()
    header = next(csv.reader([lines[0]])) if lines else []
    if header and header[0].strip().startswith("IP"):
        rd = csv.DictReader(lines)
        c_ip = pick_col(rd.fieldnames, "IP")
        c_lat = pick_col(rd.fieldnames, "平均延迟", "延迟")
        c_spd = pick_col(rd.fieldnames, "下载速度", "速度")
        c_area = pick_col(rd.fieldnames, "地区码", "地区")
        if not c_ip:
            odd_files += 1
            continue
        for r in rd:
            ip_s = (r.get(c_ip) or "").strip()
            if not ip_s:
                continue
            if not IP_RE.match(ip_s):
                bad_ip += 1
                continue
            lat_str = (r.get(c_lat) or "").strip() if c_lat else ""
            spd_str = (r.get(c_spd) or "").strip() if c_spd else ""
            area_str = (r.get(c_area) or "").strip() if c_area else ""
            rows_read += 1
            if num(lat_str) is None:
                no_metric += 1
            cand = make_cand(lat_str, spd_str, area_str)
            if better(cand, best[ip_s][0] if ip_s in best else None):
                best[ip_s] = out_row(cand, lat_str, spd_str, area_str)
    else:
        # header-less file: raw "IP:port" lines (defensive fallback)
        odd_files += 1
        for ln in lines:
            ip_s = ln.strip().split(":")[0].strip()
            if not ip_s:
                continue
            if not IP_RE.match(ip_s):
                bad_ip += 1
                continue
            rows_read += 1
            no_metric += 1
            cand = make_cand("", "", "")
            if better(cand, best[ip_s][0] if ip_s in best else None):
                best[ip_s] = out_row(cand, "", "", "")

print(f"读入数据行: {rows_read} | 非法 IP 行: {bad_ip} | 无表头文件: {odd_files} | 无延迟指标行: {no_metric}")
print(f"CSV 内去重后唯一 IP: {len(best)}")


# ---------- 3. merge into existing go.csv ----------
merged = {}
if os.path.exists(GO):
    with open(GO, "r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        c_ip = pick_col(rd.fieldnames or [], "IP") or KEEP[0]
        c_lat = pick_col(rd.fieldnames or [], "平均延迟", "延迟") or KEEP[1]
        c_spd = pick_col(rd.fieldnames or [], "下载速度", "速度") or KEEP[2]
        c_area = pick_col(rd.fieldnames or [], "地区码", "地区") or KEEP[3]
        for r in rd:
            ip_s = (r.get(c_ip) or "").strip()
            if not ip_s or not IP_RE.match(ip_s):
                continue
            lat_str = (r.get(c_lat) or "").strip()
            spd_str = (r.get(c_spd) or "").strip()
            area_str = (r.get(c_area) or "").strip()
            cand = make_cand(lat_str, spd_str, area_str)
            if better(cand, merged[ip_s][0] if ip_s in merged else None):
                merged[ip_s] = out_row(cand, lat_str, spd_str, area_str)

go_before = len(merged)
added = upgraded = 0
for ip, (cand, row) in best.items():
    old = merged.get(ip)
    if old is None:
        added += 1
    elif cand > old[0]:
        upgraded += 1
    if better(cand, old[0] if old else None):
        merged[ip] = (cand, row)

backup(GO, "go.csv")
ordered = sorted(merged.items(), key=lambda kv: int(ipaddress.ip_address(kv[0])))
with open(GO, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(KEEP)
    for ip, (_cand, row) in ordered:
        w.writerow([ip, row["平均延迟"], row["下载速度(MB/s)"], row["地区码"]])

print(f"go.csv: {go_before} -> {len(ordered)} 行（新增 {added}，原有记录被补全/升级 {upgraded}）")


# ---------- 4. incrementally update all.txt ----------
cur = set()
if os.path.exists(ALL_TXT):
    with open(ALL_TXT, "r", encoding="utf-8", errors="ignore") as fh:
        cur = set(l.strip() for l in fh if l.strip())

new_ips = set(best) - cur
if new_ips:
    backup(ALL_TXT, "all.txt")
    union = cur | set(best)
    with open(ALL_TXT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(union, key=lambda x: int(ipaddress.ip_address(x)))) + "\n")
    with open(NEW_IPS_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(new_ips, key=lambda x: int(ipaddress.ip_address(x)))) + "\n")
    print(f"all.txt: {len(cur)} -> {len(union)} 行（来自新数据 CSV 的净新增 {len(new_ips)}）")
    print(f"新增 IP 清单写出: {NEW_IPS_OUT}")
else:
    print(f"all.txt: {len(cur)} 行，无新增（CSV 中的 IP 已全部存在）")


# ---------- 5. regenerate all.csv (reuse the resumable enricher) ----------
if new_ips or not os.path.exists(ALL_CSV):
    if os.path.exists(ENRICH):
        print("--- 调用 enrich_cidrs.py 重生成 all.csv ---", flush=True)
        r = subprocess.run([sys.executable, "-u", ENRICH], cwd=BASE)
        if r.returncode != 0:
            print(f"WARN: enrich_cidrs.py 返回 {r.returncode}，all.csv 可能不完整，可重跑本脚本补齐")
    else:
        print(f"WARN: 未找到 {ENRICH}，跳过 all.csv 重生成")
else:
    print("all.csv 无需重生成（无新 CIDR）")

print("\nSTEP 新数据合并: DONE")
