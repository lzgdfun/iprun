# cf-ip-pipeline

Cloudflare IP 清单的**全自动清洗流水线**。云端定时运行，无需本机开机。

## 定时调度

- **北京时间每周五 00:00**（等价于 UTC 每周四 16:00，工作流里配置为 `cron: '0 16 * * 4'`）
- 也可在 **Actions 页面手动触发**（workflow_dispatch），用于首次验证或临时补跑
- GitHub 的 cron 在高峰期可能有几分钟延迟，属正常现象

## 它做什么

每次运行按顺序执行：

| 步骤 | 脚本 | 作用 |
|---|---|---|
| 0 | `step_newdata.py` | **条件执行**：若仓库里存在 `新数据/` 文件夹且有测速 CSV，则合并进 `go.csv`（去重、择优）并把其 IP 增量并入 `all.txt` / `all.csv`；**没有 CSV 时自动 SKIP**，不是错误 |
| 1 | `bootstrap.py` | 首次运行时用种子文件初始化 `all.txt` / `go.csv`，保证迁移前历史数据不丢 |
| 2 | `fetch_sources.py` | 采集 4 个数据源 → 合并去重 → 与 `all.txt` 对比算出**净新增** |
| 3 | `apply_update.py` | `all.txt` = 旧 ∪ 新增，按 IP 数值升序去重 |
| 4 | `enrich_cidrs.py` | 按 /24 归并并补全每个网段的**归属厂商 / 归属地** → 生成 `all.csv` |
| 5 | `update_go.py` | 把新增 IP 并入 `go.csv`（新增行指标列为空；不会清掉第 0 步填好的指标） |
| 6 | `verify.py` | 校验升序、唯一、新增 IP 三文件全覆盖、归属零空白 |

> 步骤 0 的说明：把测速结果 CSV 放进仓库的 `新数据/` 目录（可含子目录）并提交，下次运行就会自动并入。CSV 表头应为
> `IP 地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s),地区码,端口`；流程只保留后 4 列中的
> `IP 地址 / 平均延迟 / 下载速度(MB/s) / 地区码`，丢弃 `已发送 / 已接收 / 丢包率 / 端口`。
> 同一 IP 出现多次时保留**平均延迟最低**的记录（无延迟指标的记录优先级最低），原有无指标的记录会被**自动补全**。
> 该步骤按 IP 去重，**幂等**——重复放入同一批 CSV 不会改变结果。

## 数据源（4 个）

1. `dns.txt` —— 本项目维护的域名列表，解析其 DNS A 记录
2. <https://zip.cm.edu.kg/all.txt>
3. <https://raw.githubusercontent.com/yuanxiawan/cfipv4db/refs/heads/main/high_score_ips.txt>
4. <https://raw.githubusercontent.com/xgonce/Cloudflare_IP/main/result.csv>（raw 地址；失败回退 `/master/`）

> 任一外链源抓取失败时，`fetch_sources.py` 会**中止本轮**（退出码 1），主表保持原样，不会用不完整数据污染结果。

## 产物文件

| 文件 | 说明 |
|---|---|
| `all.txt` | 全部唯一 IPv4 主表，每行一个，数值升序 |
| `all.csv` | 按 /24 归并的归属统计表：`序号,CIDR归属厂商,CIDR归属地,CIDR,IP数量,IP列表`，按 IP 数量降序，UTF-8 with BOM |
| `go.csv` | 测速表：`IP 地址,平均延迟,下载速度(MB/s),地区码`，数值升序，UTF-8 with BOM |
| `新增IP.txt` | 本轮相对上次的净新增 IP（每轮覆盖） |
| `本轮数据源.txt` | 本轮四源去重后的全部 IP |

## 本机手动运行（等价流程）

```bash
python -u step_newdata.py           # 第 0 步：无 新数据/ CSV 时会打印 SKIP 并正常退出
python -u bootstrap.py              # 仅首次运行需要
python -u fetch_sources.py
python -u apply_update.py
for i in 1 2 3 4 5 6; do python -u enrich_cidrs.py && python -u verify.py --only-blank && break; sleep 20; done
python -u update_go.py 新增IP.txt
python -u verify.py
```

仅用 Python 标准库，Python 3.8+ 均可，无需安装依赖。

## 实现中的两个关键坑（已在脚本里处理）

1. **源 4 必须用 raw 地址**：给的是 GitHub blob 网页链接，直接抓会拿到 HTML。
2. **ip-api 免费接口约 20% 请求随机挂起**：必须用 10 秒快速超时 + 轻量重试（≤3 次）+ 每批增量落盘；**禁止长退避重试**（曾出现 9000+ CIDR 空转 30 分钟）。失败的批次会在下一轮或下次运行自动补上，工作流内置最多 6 轮重试直到零空白。
3. 缓存加载时**跳过空归属记录**，否则上一轮写入的空值会被误判为"已解析"而永远补不上。

## 归属数据说明

归属来自第三方 IP 库（ip-api.com），为**大致结果**。对 anycast/CDN（如 Cloudflare）IP，归属地是**最近接入点机房城市**，而非公司注册地，同一厂商会分散在多个国家，属正常现象。

香港 / 台湾 / 澳门标签已规范化为 **中国香港 / 中国台湾 / 中国澳门**。

## 提示词

完整可复用提示词见 [`提示词-IP清洗全流程.md`](./提示词-IP清洗全流程.md)，可直接粘贴给任意 AI 智能体复现整套流程。
