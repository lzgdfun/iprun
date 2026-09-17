# -*- coding: utf-8 -*-
"""all.txt = 旧 all.txt ∪ 新增IP.txt，按 IP 数值升序去重落盘。

备份由 git 承担（每次运行都会提交），故此处不再另存 .bak。
"""
import ipaddress
import os

BASE = os.path.dirname(os.path.abspath(__file__))
ALL = os.path.join(BASE, "all.txt")
NEW = os.path.join(BASE, "新增IP.txt")
key = lambda x: int(ipaddress.ip_address(x))


def load(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return {l.strip() for l in fh if l.strip()}


cur = load(ALL)
new = load(NEW)
union = cur | new
ordered = sorted(union, key=key)
with open(ALL, "w", encoding="utf-8") as fh:
    fh.write("\n".join(ordered) + "\n")

nets = {str(ipaddress.ip_network(f"{ip}/24", strict=False)) for ip in union}
old_nets = {str(ipaddress.ip_network(f"{ip}/24", strict=False)) for ip in cur}
print(f"all.txt: {len(cur)} -> {len(union)}  (新增 {len(new)}，其中净新增 {len(new - cur)})")
print(f"/24 CIDR: {len(old_nets)} -> {len(nets)}  (新增 {len(nets - old_nets)} 个待查询)")
