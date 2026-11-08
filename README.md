# shadowrocket 规则聚合

个人 Shadowrocket 分流规则：多上游自动聚合、GitHub Actions 每日构建、固定 URL 订阅。三桶模式（拦截 / 直连 / 代理）+ iOS 服务独立通道（APNs 推送 / iCloud）+ 定位欺骗 + 个人覆盖规则，策略仅 DIRECT / PROXY / REJECT（PROXY = 首页当前选中节点，单节点友好）。定位欺骗来自 [mekos2772/ios-location-spoofer](https://github.com/mekos2772/ios-location-spoofer)（MITM 改写 Apple 定位应答，配合 Cloudflare Worker 网页地图选点）。

> 本仓库由 AI 全程生成——方案设计、构建流水线（`build/` 全部代码）与本文档均由
> [TeleAgent 星辰超级智能体](https://www.teleai.com.cn/product/super-agent)（中电信人工智能）完成；
> 规则数据全部来自下表所列社区公开项目。

## 仓库结构

```
build/
├── build.py                  # 构建引擎（拉取→解析→合并→防线校验→产出）
├── config.py                 # 全局配置（REPO/URL_SCHEME）+ 特殊产物
├── buckets/                  # 规则桶，一桶一文件（加策略=复制一个文件）
│   ├── direct.py             #   国内直连桶 -> dist/direct.module
│   ├── proxy.py              #   代理桶     -> dist/proxy.module
│   ├── reject.py             #   拦截桶     -> dist/reject.module
│   ├── ios.py                #   iOS 服务桶(APNs+iCloud) -> dist/ios.module（手写，无上游）
│   └── me.py                 #   个人规则桶 -> dist/me.module（透传，每行自带策略）
└── templates/main.conf.template   # 主配置模板（{{URL::x.module}} 占位符）
dist/                         # 构建产物（提交入库，供手机远程订阅）
.github/workflows/build.yml         # 每日构建 + 变更提交
```

## 数据来源

| 产物 | 上游 | 说明 |
|---|---|---|
| direct.module | [Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat) `direct-list.txt`（geosite:cn） | 每日构建，源自 [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) 与 dnsmasq-china-list |
| direct.module | [Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat) `apple-cn.txt` | 苹果国内业务域名 |
| direct.module | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) WeChat（上游 ACL4SSR） | 微信域名 + USER-AGENT catch-all |
| proxy.module | [Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat) `proxy-list.txt`（geolocation-!cn） | 已知国外域名 |
| proxy.module | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) OpenAI / Anthropic / Netflix / YouTube / Disney / Telegram / Apple_Domain | 分领域补充（Telegram 含官方 IP 段） |
| reject.module | [AdGuard DNS filter](https://github.com/AdguardTeam/FiltersRegistry)（filter_15） | DNS 层广告/隐私拦截 |
| reject.module | [pgl.yoyo.org](https://pgl.yoyo.org/adservers/) 广告域名表 | 可选补充 |
| ios.module | Apple 官方文档（APNs 章节，手写） | 推送域名（push.apple.com 等）+ 5223 端口 + iCloud 同步主域（美区账号显式走代理） |

各上游的具体快照（sha1、条数、跳过数）见构建产物 `dist/report.txt`。

## 使用方法（小火箭端）

1. **首页** → 添加节点订阅并选中节点（PROXY 即指向它）
2. **配置** → 右上角 + → 添加 main.conf（两套任选其一）：

   - jsdelivr：`https://cdn.jsdelivr.net/gh/aiifan/shadowrocket@main/dist/main.conf`
   - raw 直链：`https://raw.githubusercontent.com/aiifan/shadowrocket/main/dist/main.conf`

3. **配置 → 模块** → 右上角 +，依次添加并启用，**顺序必须从上到下如下**（上 = 优先级高）：

   | # | 模块 (dist 下文件名) | 说明 |
   |---|---|---|
   | ① | `me.module` | 个人规则（置顶，覆盖一切） |
   | ② | `reject.module` | 拦截 |
   | ③ | `ios.module` | iOS 服务（APNs推送+iCloud），必须在直连前 |
   | ④ | `direct.module` | 国内直连 |
   | ⑤ | `proxy.module` | 代理 |

   完整链接 = **前缀 + 文件名**，两套任选（可混用；jsdelivr 国内可达但缓存约 12h，raw 更新即时但需代理可达）：

   ```text
   前缀 A:  https://cdn.jsdelivr.net/gh/aiifan/shadowrocket@main/dist/
   前缀 B:  https://raw.githubusercontent.com/aiifan/shadowrocket/main/dist/
   拼法:    <前缀><文件名>   例: <前缀 B>me.module
   ```

   > main.conf 头部注释里嵌的是 jsdelivr 链接；想让生成产物改嵌 raw，
   > 把 build/config.py 的 URL_SCHEME 改为 "raw" 重跑构建即可。

4. 分流逻辑：拦截 > iOS服务(推送+iCloud) > 直连 > 代理 > CN 的 IP 直连(GEOIP) > 其余走代理(FINAL)
   想临时全代理 / 全直连，直接关闭对应模块即可。

## 构建与维护

```bash
python build/build.py             # 拉上游 -> 解析 -> 合并 -> 校验 -> 产出 dist/
python build/build.py --offline   # 断网，仅用 .cache/ 本地缓存
python build/build.py --selftest  # 仅跑内置解析器自测
```

- 本机直连拉不动 GitHub：`$env:HTTPS_PROXY = "http://127.0.0.1:10809"` 后再跑（下载失败自动回退缓存）
- **改个人规则**：`build/buckets/me.py` 的 `RULES`（每行 `类型,值,策略`）
- **改某桶上游/手工补充**：`build/buckets/` 对应文件（`UPSTREAMS` / `RULES`，桶内策略自动统一）
- **改 General/DNS/兜底**：`build/templates/main.conf.template`
- **加新策略桶**：复制 `buckets/direct.py` 改名 → 模板头部【导入步骤】补一行同款引用 → 小火箭手动添加模块。构建会自动发现新桶，模板漏引用会有告警
- 防线机制：每桶有 [下限,上限] 条数区间，上游改版导致桶空/残缺时构建失败而非发出坏模块；产物 LF / 无 BOM 字节校验；自动源 DOMAIN-KEYWORD 一律丢弃（关键词规则只允许写在 me 桶，防误杀）

## CI（GitHub Actions）

- `build`：每日北京时间 10:30 自动构建（cron `30 2 * * *`），产物有变化才提交，无空提交；push 到 main（改动 `build/**`）也会触发；手动触发：Actions → build → Run workflow

## 仓库初始化 / 同步

首次（本机已有内容推到远端空仓库）：

```bash
git init -b main
git remote add origin git@github.com:aiifan/shadowrocket.git
git add -A
git commit -m "init: shadowrocket 规则聚合流水线"
git push -u origin main
```

日常：改完桶/模板后本地跑 `python build/build.py` 核对产物，再 push；或直接 push 让 CI 构建（定时任务每天兜底重跑）。

> 注意：`dist/` 是构建产物但**需要提交入库**（手机订阅靠它）；`.cache/` 为上游缓存，不入库。
> 仓库需保持 **public**：jsdelivr / raw.githubusercontent 只服务公开仓库，改私有后手机订阅会 404（私有仓库 Actions 仍可用，Free 账户每月 2000 分钟，但需另行设计配送，如另建公开配送仓库）。

## Fork 使用说明

想把这套流水线变成自己的？fork 之后按下面清单改，push 即得自己专属的构建。

**第一步（必做）**：fork 的仓库 → Actions 页 → 点 "I understand my workflows, go ahead and enable them" 启用 workflows（fork 后默认禁用）。

**第二步：按需修改**——

| # | 改什么 | 在哪 | 必须? | 不改的后果 |
|---|---|---|---|---|
| 1 | `REPO = "aiifan/shadowrocket"` 换成自己的 `用户名/仓库名` | `build/config.py` | **必须** | main.conf 与模块引用的 URL 仍指向本仓库——手机下载的还是原作者的产物，自己改什么都不生效 |
| 2 | 自用域名规则 | `build/buckets/me.py` | 按需 | 沿用原作者的三条自用域名（无功能损害） |
| 3 | skip-proxy 的银行域名等 | `build/templates/main.conf.template` | 按需 | 多几条无害的直连 |

**第三步**：push 改动 → build workflow 自动触发（约 15s）→ 仓库里 `dist/` 已是自己的产物，按「使用方法」一节添加订阅即可。

几个说明：

- 构建自包含：上游数据源全是公开项目，与谁 fork 无关；GitHub Actions 免费额度跑本流水线（每天约 2~3 分钟）完全够用；
- fork 后 `BRANCH = "main"` 一般不用动，除非你把默认分支改名了；

> AI生成
