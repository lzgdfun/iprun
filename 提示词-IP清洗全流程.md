# 提示词：IP 清单清洗全流程（全量重建 + 增量更新）

> **用法**：整段直接粘贴给任意 AI 智能体即可。它会先自动判断该走「全量重建」还是「增量更新」，然后完成采集、去重、CIDR 归属补全，产出 `all.txt` / `all.csv` / `go.csv` 三个文件。
> **本提示词自包含**：不依赖上游脚本存在，附录 A 提供了可直接抄写的参考实现代码。

---

## 一、角色与目标

你是数据清洗助手。请从指定的多个数据源采集 IPv4 地址，合并去重，按 **/24 CIDR** 归并并补全每个网段的**归属厂商**与**归属地**，最终维护三个文件：

| 文件 | 内容 |
|---|---|
| `all.txt` | 全部唯一 IPv4 主表（每行一个 IP，按数值升序） |
| `all.csv` | 按 /24 归并的归属统计表（按 IP 数量降序） |
| `go.csv` | 测速 IP 表（`IP 地址,平均延迟,下载速度(MB/s),地区码`，按 IP 数值升序） |

**两种运行模式**（先判断，再执行）：
- **全量重建**：目录下没有任何历史数据时，从所有数据源从零构建三个文件。
- **增量更新**：目录下已存在历史数据时，只把**新增 IP** 并入，不覆盖、不丢旧数据。

**核心要求**：增量、幂等、可重复执行。重复跑结果一致，不产生副作用。

---

## 二、工作目录与产物

- 工作目录：当前项目目录（例如 `D:\tools\workbuddy\数据清洗`）。
- 全部读写在本机完成并落盘，命令行工具在**工作目录内**执行。
- 产物文件：`all.txt`、`all.csv`、`go.csv`；中间文件：`本轮数据源.txt`（本轮所有源去重后合集）、`新增IP.txt`（相对上次的净新增）。
- 缓存目录：`.workbuddy/_src_cache/`（外链原始快照）、`.workbuddy/_enrich_cache.json`（CIDR 归属增量缓存）、`.workbuddy/_backup/`（主表备份）。
- 优先使用受管 Python（例：`C:\Users\38231\.workbuddy\binaries\python\versions\3.13.12\python.exe`），**仅用标准库**，无需安装依赖。若该路径不存在，用本机任意 Python 3.8+。

---

## 三、数据源

| # | 来源 | 类型 | 解析方式 |
|---|---|---|---|
| 1 | 工作目录下的 `dns.txt` | 域名列表（每行一个域名） | 本地 DNS 解析其 **A 记录**，只取 IPv4（过滤 IPv6） |
| 2 | `https://zip.cm.edu.kg/all.txt` | 文本，格式 `IP:443#CC` | 每行提取**第一个合法 IPv4** |
| 3 | `https://raw.githubusercontent.com/yuanxiawan/cfipv4db/refs/heads/main/high_score_ips.txt` | 文本，格式 `IP # 区域码` | 每行提取**第一个合法 IPv4** |
| 4 | `https://github.com/xgonce/Cloudflare_IP/blob/main/result.csv` | GitHub 网页链接 | **必须改用 raw 地址**：`https://raw.githubusercontent.com/xgonce/Cloudflare_IP/main/result.csv`（失败回退 `/master/`），取每行第一个 IPv4 |

**附加（可选）**：若工作目录下还存在其它 IP 文本文件（每行一个 IPv4，如 `p1.txt`、`新增数据.txt` 等），**全量重建时**应一并纳入；**增量更新时**默认不纳入（避免把历史文件重复算作新增），除非用户明确要求。

> 关键坑：源 4 给的是 GitHub **blob 网页**地址，必须转成 `raw.githubusercontent.com` 才能拿到纯文本；直接抓网页会拿到 HTML。

---

## 四、模式判断（先做这一步）

统计工作目录下 `all.txt`、`all.csv`、`go.csv` 的存在情况：

- **三者都存在** → 走**增量更新**。
- **缺任意一个** → 走**全量重建**：
  - 若 `all.txt` 不存在，先创建一个空文件（这样四源 IP 全部视为新增，即等价于全量构建）；
  - 若 `go.csv` 不存在，先写入表头 `IP 地址,平均延迟,下载速度(MB/s),地区码`；
  - `all.csv` 由流程自动生成，无需预建。
- 两种模式**后续命令流程完全一致**，无需写两套分支逻辑。

---

## 五、处理流程

### 步骤 1：采集 + 解析 + 求新增
1. **解析 `dns.txt`**：逐行读域名 → 查询 A 记录（用 `socket.gethostbyname_ex`，只保留 IPv4）。
   - 并发解析（建议 24 线程）加速；单域名超时 6 秒，失败重试 1 次。
   - **记录解析失败的域名**并在汇报中列出（常见原因是域名无 A 记录/不存在，而非网络问题，不要静默丢弃）。
2. **抓取 3 个外链源**：带 `User-Agent`，超时 60 秒；抓到的原始内容缓存到 `.workbuddy/_src_cache/`。某源失败时重试并回退备用 URL，**不要中断整体任务**。
3. **解析为 IP 集合**：每行用正则 `(?:\d{1,3}\.){3}\d{1,3}` 提取候选，取**第一个能通过 `ipaddress.ip_address()` 校验的 IPv4**（这样可同时兼容 `IP:port#CC`、`IP # region`、CSV 首列等格式）。
4. **合并去重**：所有源取并集 → 写出 `本轮数据源.txt`（按 IP 数值升序，UTF-8）。
5. **求新增**：`新增IP.txt = 本轮数据源 − 现有 all.txt`，按 IP 数值升序写出。
   - 若 `新增IP.txt` 为空 → 无更新，直接跳到步骤 6 的校验与汇报（幂等）。

### 步骤 2：更新 `all.txt`
`新 all.txt = 旧 all.txt ∪ 新增IP.txt`，按 **IP 数值升序**（不是字符串序）去重落盘。
- **覆盖前先把旧 `all.txt` 备份**到 `.workbuddy/_backup/all.txt.bak`。
- 编码 UTF-8，每行一个 IP，行尾换行。

### 步骤 3：更新 `all.csv`
读取整份 `all.txt` → 按 **/24 CIDR** 归并 → 补全每个 CIDR 的归属 → 按数量降序写出（详见第六、七节）。
- 归属查询走**可恢复增量缓存**：已解析过的 CIDR 直接复用，只查询新出现的 CIDR。
- 缓存必须**增量落盘**（每批写一次），支持断点续跑。

### 步骤 4：更新 `go.csv`
把 `新增IP.txt` 的 IP 追加进 `go.csv`，新增行指标列（平均延迟/下载速度/地区码）留空；按 IP 数值升序、去重落盘，编码 UTF-8 with BOM。
- 去重规则：同一 IP 出现多次时，保留**平均延迟最低**的那条（无指标则视为无穷大，不会覆盖已有指标）。

---

## 六、CIDR 归属补全细节

- 数据源：`http://ip-api.com/batch?lang=zh-CN&fields=status,query,country,regionName,city,isp,org,as`
- 每个 CIDR 取其**首个成员 IP** 作为代表，每批 **100 个**，批间 sleep 4 秒。
- **CIDR归属厂商** = `org`，为空回退 `isp`，再空回退 `as`。
- **CIDR归属地** = `country` + `regionName` + `city`（空格连接，跳过空值，中文）。
- **地区标签规范化**：香港 → 中国香港；台湾 → 中国台湾；澳门 / 澳門 → 中国澳门。

### 必须处理的稳定性坑（否则会严重拖慢甚至卡死）
1. ip-api 免费批量接口约有 **20% 请求随机挂起**（不是限流，是随机无响应）。
   → 必须用 **10 秒快速超时 + 轻量重试（≤3 次）**，禁止「长退避 × 多次重试」——曾出现 9000+ 个 CIDR 用长退避策略跑 30 分钟仍未完成。
2. **缓存加载时要跳过「空归属」记录**：若上一轮把失败的 CIDR 以空值写入 `all.csv`，下次加载会被误判为「已解析」而永远补不上。
3. 允许**分多轮执行**：失败的批次在下次运行时自动重试，直至 `all.csv` 归属**零空白**。

---

## 七、输出格式规范

### `all.txt`
每行一个 IPv4，**按数值升序**，UTF-8（无 BOM），末尾换行。

### `all.csv`
- 列顺序**固定**：`序号,CIDR归属厂商,CIDR归属地,CIDR,IP数量,IP列表`
- 排序：按 `IP数量` **降序**；数量相同时按 CIDR 网络地址**升序**。
- `CIDR` 用网络地址形式（如 `172.65.90.0/24`，主机位归零）。
- `IP列表` = 该 CIDR 下所有成员 IP，用分号 `;` 分隔。
- 编码：**UTF-8 with BOM**（`utf-8-sig`），便于 Excel 直接打开不乱码。

示例：
```
序号,CIDR归属厂商,CIDR归属地,CIDR,IP数量,IP列表
1,"Cloudflare, Inc.",加拿大 安大略 多伦多,172.65.90.0/24,36,172.65.90.2;172.65.90.4;...
```

### `go.csv`
- 列顺序**固定**：`IP 地址,平均延迟,下载速度(MB/s),地区码`
- 按 IP **数值升序**，编码 **UTF-8 with BOM**。

---

## 八、校验断言（必须执行并记录结果）

1. `all.txt` 行数 = 唯一 IP 数，且**严格按数值升序**。
2. `go.csv` 行数 = 唯一 IP 数，且**严格按数值升序**。
3. `新增IP.txt` 中的**每一个 IP** 都同时存在于：`all.txt`、`all.csv` 的 `IP列表` 列、`go.csv`。
4. `all.csv` 的归属列**无空白**（`空归属 = 0`）。
5. `all.txt` 与 `all.csv` 基于**同一份去重 IP 集合**，保持自洽（可用 `all.csv` 中 IP 数量之和与 `all.txt` 行数是否相等的近似校验：数量之和应等于 `all.txt` 行数）。

---

## 九、汇报要求

完成后输出：
- 各源分别解析出的**唯一 IPv4 数**；`dns.txt` 解析**成功/失败域名数**（列出失败域名）。
- 各源**去重合计**、与旧 `all.txt` 的**重叠数**、**净新增数**、**合并后总数**。
- 三个文件（`all.txt` / `all.csv` / `go.csv`）**变化的行数**（前 → 后）。
- **新出现的 CIDR 数**与本次**实际向 API 新查询的 CIDR 数**。
- **Top 10 CIDR**（按 IP 数量降序，含厂商/归属地）。
- 数据来源与局限说明（见第十节）。

---

## 十、约束与局限说明

- **归属为第三方 IP 库的大致结果**，可能存在偏差；如需权威数据，可改用 RIR 的 RDAP 备案信息核对。
- 对 **anycast / CDN**（如 Cloudflare）IP，**归属地是最新接入点机房城市**，而非公司注册地，同一厂商会分散在多个国家——须在汇报中提示。
- `go.csv` 的新增行没有测速指标（外链源只提供 IP 列表），指标列为空**属预期**。
- 覆盖任何已有文件前，确保数据可从 `all.txt` / `新增IP.txt` 重建；主表覆盖前必须备份。
- 若用户明确要求"以某个粒度归并"（非 /24），按要求调整，并在汇报中注明。

---

## 十一、可变参数（按需在需求中补充说明）

- **CIDR 掩码**：默认 `/24`；可改 `/16`、`/20`，或按真实分配块做 IP 聚合（supernetting）。
- **查询语言**：默认中文；改为英文归属地用 `lang=en`。
- **是否保留 `IP列表` 列**：默认保留；只要 CIDR + 数量时可去掉。
- **数据源增减**：某源长期失效时删除或替换；`dns.txt` 域名清单可随时更新。
- **输出位置**：默认工作目录根；可指定子目录。

---

## 十二、附录 A：参考实现（可直接抄写为 4 个脚本）

> 以下为经过实测的完整实现。写入工作目录后按顺序执行即可。若目标智能体具备文件写入能力，直接照抄；否则按逻辑自行实现。

### 通用配置（各脚本共用）
```python
BASE = r"D:\tools\workbuddy\数据清洗"   # ← 改成你的工作目录
```

### `fetch_round2.py` —— 采集 + 解析 + 求新增
```python
# -*- coding: utf-8 -*-
import concurrent.futures as cf, ipaddress, os, re, socket, urllib.request

BASE = r"D:\tools\workbuddy\数据清洗"
CACHE = os.path.join(BASE, ".workbuddy", "_src_cache")
os.makedirs(CACHE, exist_ok=True)
PAT = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
HDR = {"User-Agent": "Mozilla/5.0"}
socket.setdefaulttimeout(6)

def resolve(domain):
    got = set()
    try:
        _h, _a, addrs = socket.gethostbyname_ex(domain)
        for a in addrs:
            try:
                ip = ipaddress.ip_address(a)
                if ip.version == 4: got.add(str(ip))
            except ValueError: pass
    except Exception: pass
    return domain, got

# 1) DNS
with open(os.path.join(BASE, "dns.txt"), encoding="utf-8", errors="ignore") as fh:
    domains = sorted({l.strip() for l in fh if l.strip()})
dns_ips, failed = set(), []
with cf.ThreadPoolExecutor(max_workers=24) as ex:
    for dom, got in ex.map(resolve, domains):
        (dns_ips.update(got) if got else failed.append(dom))
print(f"dns.txt domains={len(domains)} resolved_ips={len(dns_ips)} failed={len(failed)}")
if failed: print("  failed:", failed)

# 2) 外链
SOURCES = {
    "src1_all.txt": ["https://zip.cm.edu.kg/all.txt"],
    "src2_high_score.txt": ["https://raw.githubusercontent.com/yuanxiawan/cfipv4db/refs/heads/main/high_score_ips.txt"],
    "src3_result.csv": ["https://raw.githubusercontent.com/xgonce/Cloudflare_IP/main/result.csv",
                        "https://raw.githubusercontent.com/xgonce/Cloudflare_IP/master/result.csv"],
}
def parse_first_ipv4(text):
    ips = set()
    for line in text.splitlines():
        for m in PAT.findall(line):
            try: ip = ipaddress.ip_address(m)
            except ValueError: continue
            if ip.version == 4: ips.add(str(ip)); break
    return ips

src_ips = {}
for name, urls in SOURCES.items():
    raw = None
    for url in urls:
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=60).read().decode("utf-8", "ignore")
            print(f"{name}: OK <- {url}"); break
        except Exception as e: print(f"{name}: failed {url} -> {e}")
    if raw is None: continue
    open(os.path.join(CACHE, name), "w", encoding="utf-8").write(raw)
    src_ips[name] = parse_first_ipv4(raw)
    print(f"   lines={len(raw.splitlines())} uniqueIPv4={len(src_ips[name])}")

# 3) 合并 + 求新增
union = set(dns_ips)
for s in src_ips.values(): union |= s
key = lambda x: int(ipaddress.ip_address(x))
open(os.path.join(BASE, "本轮数据源.txt"), "w", encoding="utf-8").write("\n".join(sorted(union, key=key)) + "\n")

cur = set()
p_all = os.path.join(BASE, "all.txt")
if os.path.exists(p_all):
    with open(p_all, encoding="utf-8", errors="ignore") as fh:
        cur = {l.strip() for l in fh if l.strip()}
new = union - cur
open(os.path.join(BASE, "新增IP.txt"), "w", encoding="utf-8").write("\n".join(sorted(new, key=key)) + "\n")

print(f"\n=== dns={len(dns_ips)} 四源合计={len(union)} 旧all.txt={len(cur)} 重叠={len(union&cur)} 净新增={len(new)} 合并后={len(cur|union)}")
```

### `apply_round2.py` —— 并集更新 all.txt
```python
# -*- coding: utf-8 -*-
import ipaddress, os, shutil
BASE = r"D:\tools\workbuddy\数据清洗"
ALL, NEW = os.path.join(BASE, "all.txt"), os.path.join(BASE, "新增IP.txt")
BK = os.path.join(BASE, ".workbuddy", "_backup"); os.makedirs(BK, exist_ok=True)

def load(p):
    if not os.path.exists(p): return set()
    with open(p, encoding="utf-8", errors="ignore") as fh:
        return {l.strip() for l in fh if l.strip()}

cur, new = load(ALL), load(NEW)
if os.path.exists(ALL): shutil.copy2(ALL, os.path.join(BK, "all.txt.bak"))
union = cur | new
ordered = sorted(union, key=lambda x: int(ipaddress.ip_address(x)))
open(ALL, "w", encoding="utf-8").write("\n".join(ordered) + "\n")
nets = {str(ipaddress.ip_network(f"{ip}/24", strict=False)) for ip in union}
old  = {str(ipaddress.ip_network(f"{ip}/24", strict=False)) for ip in cur}
print(f"all.txt: {len(cur)} -> {len(union)}  | /24: {len(old)} -> {len(nets)} (新增 {len(nets-old)})")
```

### `enrich_cidrs.py` —— 重生成 all.csv（增量归属补全，可断点续跑）
```python
# -*- coding: utf-8 -*-
import csv, ipaddress, json, os, time, urllib.request
BASE = r"D:\tools\workbuddy\数据清洗"
ALL_TXT, ALL_CSV = os.path.join(BASE, "all.txt"), os.path.join(BASE, "all.csv")
CACHE = os.path.join(BASE, ".workbuddy", "_enrich_cache.json")
API = "http://ip-api.com/batch?lang=zh-CN&fields=status,query,country,regionName,city,isp,org,as"
FIX = {"香港": "中国香港", "台湾": "中国台湾", "澳门": "中国澳门", "澳門": "中国澳门"}
BATCH, SLEEP, TIMEOUT = 100, 4, 10
os.makedirs(os.path.dirname(CACHE), exist_ok=True)
ven = lambda it: it.get("org") or it.get("isp") or it.get("as") or ""
def loc(it):
    s = " ".join(p for p in (it.get("country",""), it.get("regionName",""), it.get("city","")) if p)
    t = s.split(" ")
    if t and t[0] in FIX: t[0] = FIX[t[0]]; s = " ".join(t)
    return s
_ok = lambda v: bool(v) and (v[0] or v[1])

cache = {}
if os.path.exists(CACHE):
    cache.update({k: v for k, v in json.load(open(CACHE, encoding="utf-8")).items() if _ok(v)})
if os.path.exists(ALL_CSV):                              # 复用旧 all.csv，但跳过空归属
    for r in csv.DictReader(open(ALL_CSV, encoding="utf-8-sig", newline="")):
        c = (r.get("CIDR") or "").strip(); v = [r.get("CIDR归属厂商",""), r.get("CIDR归属地","")]
        if c and c not in cache and _ok(v): cache[c] = v
print(f"cache={len(cache)}")

ips = {l.strip() for l in open(ALL_TXT, encoding="utf-8") if l.strip()}
groups = {}
for ip in ips: groups.setdefault(str(ipaddress.ip_network(f"{ip}/24", strict=False)), []).append(ip)
ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), int(ipaddress.ip_network(kv[0]).network_address)))
print(f"IPs={len(ips)} CIDRs={len(ordered)}")

todo = [m[0] for net, m in ordered if net not in cache]
print(f"to query: {len(todo)}")
def query(chunk, tries=3):
    for a in range(tries):
        try:
            req = urllib.request.Request(API, data=json.dumps(chunk).encode(), headers={"Content-Type":"application/json"})
            d = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))
            if isinstance(d, dict): raise RuntimeError(d.get("message","fail"))
            return d
        except Exception:
            if a == tries - 1: return None
            time.sleep(3)

ok = bad = 0
for i in range(0, len(todo), BATCH):
    chunk = todo[i:i+BATCH]; data = query(chunk)
    if data is None: bad += len(chunk)
    else:
        for it in data:
            q = it.get("query")
            if q:
                cache[str(ipaddress.ip_network(f"{q}/24", strict=False))] = [ven(it), loc(it)] if it.get("status") == "success" else ["", ""]
        ok += len(chunk)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)   # 每批落盘
    print(f"batch {i//BATCH+1}/{(len(todo)+BATCH-1)//BATCH} ok={ok} bad={bad}")

with open(ALL_CSV, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh); w.writerow(["序号","CIDR归属厂商","CIDR归属地","CIDR","IP数量","IP列表"])
    for idx, (net, mem) in enumerate(ordered, 1):
        v, l = cache.get(net, ["", ""]); w.writerow([idx, v, l, net, len(mem), ";".join(mem)])
print(f"DONE CIDR={len(ordered)} resolved={sum(1 for n,_ in ordered if n in cache)} bad={bad}")
```

### `update_go.py` —— 更新 go.csv
```python
# -*- coding: utf-8 -*-
"""用法: update_go.py [源IP列表.txt]  (默认 补充数据.txt)"""
import csv, ipaddress, os, sys
BASE = r"D:\tools\workbuddy\数据清洗"
GO = os.path.join(BASE, "go.csv")
SUP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "补充数据.txt")
HDR = ["IP 地址", "平均延迟", "下载速度(MB/s)", "地区码"]

best = {}
def add(ip_s, lat="", spd="", area=""):
    ip_s = (ip_s or "").strip()
    if not ip_s: return
    try: ipa = ipaddress.ip_address(ip_s)
    except ValueError: return
    if ipa.version != 4: return
    try: latv = float(lat)
    except (ValueError, TypeError): latv = float("inf")
    k = str(ipa); cur = best.get(k)
    if cur is None or latv < cur[0]: best[k] = (latv, (lat or "").strip(), (spd or "").strip(), (area or "").strip())

before = added = 0
if os.path.exists(GO):
    for r in csv.DictReader(open(GO, encoding="utf-8-sig", newline="")):
        add(r.get("IP 地址"), r.get("平均延迟"), r.get("下载速度(MB/s)"), r.get("地区码")); before += 1
if os.path.exists(SUP):
    for line in open(SUP, encoding="utf-8"):
        s = line.strip()
        if s:
            if str(ipaddress.ip_address(s)) not in best: added += 1
            add(s)
ordered = sorted(best.items(), key=lambda kv: int(ipaddress.ip_address(kv[0])))
with open(GO, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh); w.writerow(HDR)
    for ip, (_, lat, spd, area) in ordered: w.writerow([ip, lat, spd, area])
print(f"go.csv 原 {before} 行 -> 新增 {added} -> 共 {len(ordered)} 行")
```

### 执行顺序
```bash
python -u fetch_round2.py            # ① 采集解析 + 求新增
python -u apply_round2.py            # ② 并集更新 all.txt
python -u enrich_cidrs.py            # ③ 重生成 all.csv（可多轮重跑直到 0 空白）
python -u update_go.py 新增IP.txt    # ④ 更新 go.csv
```

---

## 十三、附录 B：一句话版（适合定时任务/自动化）

> 采集 `dns.txt` 的域名 A 记录，并抓取 zip.cm.edu.kg/all.txt、cfipv4db 的 high_score_ips.txt、xgonce/Cloudflare_IP 的 result.csv（改用 raw 地址）三个外链源，去重后与工作目录 `all.txt` 比较：若三个主文件已存在则只并入新增 IP（增量），否则从零构建（全量）。最终维护 `all.txt`（唯一 IP 升序）、`all.csv`（按 /24 归并，含 CIDR 归属厂商/归属地，按 IP 数量降序，UTF-8 with BOM）、`go.csv`（IP 升序）三个文件。完成后校验升序、唯一、新增 IP 已进入三个文件、归属零空白，并汇报净新增数、Top 10 CIDR 与各源解析失败情况。
