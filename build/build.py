#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shadowrocket 规则聚合构建脚本（纯标准库，Python 3.8+）

用法（任意目录均可，路径以本文件位置为基准）:
  python build/build.py             # 拉上游 -> 解析 -> 合并 -> 校验 -> 产出 dist/
  python build/build.py --offline   # 断网模式，仅使用 .cache/ 本地缓存
  python build/build.py --selftest  # 仅运行内置解析器自测，不产出文件

本机直连拉不动 GitHub 时先设代理（urllib 自动识别环境变量）:
  PowerShell:  $env:HTTPS_PROXY = "http://127.0.0.1:10809"
  bash:        export HTTPS_PROXY=http://127.0.0.1:10809

设计约定:
  1. 产物全部 LF 结尾、UTF-8 无 BOM，写盘后回读做字节校验。
  2. 确定性输出: 内容排序 + 不写时间戳，上游无变化时重复构建逐字节相同，
     CI 不产生空提交。
  3. 防线: 每个产物有条数区间（config.py guards），越界即失败；
     自动源的 DOMAIN-KEYWORD 规则一律丢弃（关键词规则只允许写在 src/rules/me.list）。
  4. 冲突只报告不静默解决（report.txt），处置归属用户。
"""

import argparse
import hashlib
import importlib.util
import ipaddress
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import config  # noqa: E402

CACHE_DIR = ROOT / ".cache"
DIST_DIR = ROOT / "dist"
BUCKETS_DIR = HERE / "buckets"
CONF_TPL = HERE / "templates" / "main.conf.template"

FAILURES = []
WARNINGS = []

# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
    r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def _valid_domain(d):
    return bool(_DOMAIN_RE.match(d))


def sha1_of(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------
# 解析器（纯函数，selftest 覆盖）
# --------------------------------------------------------------------------

def parse_v2fly(text):
    """v2fly/Loyalsoldier 域名列表 -> 带类型规则集。

    语法: full:X 精确域名 -> DOMAIN,X
          裸 X / +.X     -> DOMAIN-SUFFIX,X
          keyword:/regexp:/include:/含属性 等一律跳过（域集表达不了，防误杀）
    """
    rules, skipped = set(), 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("full:"):
            d = line[5:].strip().lower().rstrip(".")
            if _valid_domain(d):
                rules.add("DOMAIN," + d)
                continue
            skipped += 1
            continue
        if line.startswith("+."):
            line = line[2:]
        if ":" in line or " " in line or "@" in line:
            skipped += 1
            continue
        d = line.lower().strip(".")
        if _valid_domain(d):
            rules.add("DOMAIN-SUFFIX," + d)
        else:
            skipped += 1
    return rules, {"skipped": skipped}


def parse_plain(text):
    """每行一个域名的纯文本（yoyo 等广告域名表），后缀语义。"""
    domains, skipped = set(), 0
    for raw in text.splitlines():
        line = raw.strip().lower()
        if not line or line[0] in "#!/":
            continue
        if line.startswith("+."):
            line = line[2:]
        line = line.strip(".")
        if _valid_domain(line):
            domains.add(line)
        else:
            skipped += 1
    return domains, {"skipped": skipped}


def parse_bm_domain(text):
    """blackmatrix7 X_Domain.list 纯域名清单:
    前缀'.'=DOMAIN-SUFFIX（域名及全部子域），裸行=DOMAIN 精确匹配。"""
    rules, skipped = set(), 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.lower()
        if line.startswith("."):
            d = line[1:]
            if _valid_domain(d):
                rules.add("DOMAIN-SUFFIX," + d)
                continue
        elif _valid_domain(line):
            rules.add("DOMAIN," + line)
            continue
        skipped += 1
    return rules, {"skipped": skipped}


def parse_adguard(text):
    """AdGuard DNS filter（adblock 语法）-> (拦截集, 统计, 例外集)。

    取 ``||domain^$opt`` 形态的域名部分；@@ 例外规则单独返回，最后统一剔除。
    """
    blocks, exceptions, skipped = set(), set(), 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line[0] in "!#_/":
            skipped += 1
            continue
        exc = line.startswith("@@||")
        if exc or line.startswith("||"):
            base = line[4:] if exc else line[2:]
            d = _adguard_cut(base)
            if d:
                (exceptions if exc else blocks).add(d)
            else:
                skipped += 1
        else:
            skipped += 1
    return blocks, {"skipped": skipped}, exceptions


def _adguard_cut(body):
    cut = len(body)
    for ch in "^$/*?":
        idx = body.find(ch)
        if idx != -1 and idx < cut:
            cut = idx
    d = body[:cut].lower().rstrip(".")
    return d if _valid_domain(d) else None


_SURGE_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "IP-CIDR6",
    "IP-ASN", "USER-AGENT", "URL-REGEX", "GEOIP", "DST-PORT", "PROTOCOL",
}


def parse_surge(text):
    """Surge/blackmatrix7 规则集 -> 带类型规则集。

    - 允许行尾带策略字段（如 ``DOMAIN-SUFFIX,x,PROXY``），自动剥掉
    - ``IP-CIDR`` 里的 v6 地址规范化为 ``IP-CIDR6``（blackmatrix7 混用）
    - DOMAIN-KEYWORD 一律丢弃只计数（铁律: 关键词规则只进 me.list）
    """
    rules, keyword, skipped = set(), 0, 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        typ = parts[0].upper()
        if len(parts) < 2 or typ not in _SURGE_TYPES:
            skipped += 1
            continue
        val = parts[1]
        tail = parts[2] if len(parts) >= 3 and parts[2] in ("no-resolve", "src") else ""
        if typ.startswith("DOMAIN"):
            if not val or "/" in val or ":" in val or "*" in val:
                skipped += 1
                continue
            if typ == "DOMAIN-KEYWORD":
                keyword += 1
                continue
        elif typ in ("IP-CIDR", "IP-CIDR6"):
            try:
                net = ipaddress.ip_network(val, strict=False)
            except ValueError:
                skipped += 1
                continue
            typ = "IP-CIDR" if net.version == 4 else "IP-CIDR6"
        elif typ == "IP-ASN":
            if not val.isdigit():
                skipped += 1
                continue
        rules.add(typ + "," + val + ("," + tail if tail else ""))
    return rules, {"keyword": keyword, "skipped": skipped}


# --------------------------------------------------------------------------
# 下载（缓存 + 环境变量代理 + 失败回退缓存）
# --------------------------------------------------------------------------

class FetchError(Exception):
    pass


def fetch(url, offline=False, timeout=30):
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    cache = CACHE_DIR / (key + ".cache")
    if offline:
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="replace")
        raise FetchError("offline 模式且本地无缓存")
    last_exc = None
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.4.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            text = data.decode("utf-8", errors="replace")
            if not text.strip():
                raise ValueError("响应为空")
            CACHE_DIR.mkdir(exist_ok=True)
            cache.write_text(text, encoding="utf-8")
            return text
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(2 * attempt)
    if cache.exists():
        WARNINGS.append("下载失败，回退本地缓存: %s (%s)" % (url, last_exc))
        return cache.read_text(encoding="utf-8", errors="replace")
    raise FetchError("%s -> %s" % (url, last_exc))


def url_for(filename):
    if config.URL_SCHEME == "raw":
        return "https://raw.githubusercontent.com/%s/%s/dist/%s" % (
            config.REPO, config.BRANCH, filename)
    return "https://cdn.jsdelivr.net/gh/%s@%s/dist/%s" % (
        config.REPO, config.BRANCH, filename)


def script_url_for(filename):
    """js 脚本的运行时下载地址（script-path 用）。

    独立于 URL_SCHEME: 脚本是 MITM 命中瞬间实时拉取的依赖，
    jsdelivr 抽风会导致静默加载失败，固定走 raw（代理此时必然在线）。
    SCRIPT_URL_SCHEME = "jsdelivr" 可回退跟全局一致。
    """
    if getattr(config, "SCRIPT_URL_SCHEME", "raw") == "jsdelivr":
        return url_for(filename)
    return "https://raw.githubusercontent.com/%s/%s/dist/%s" % (
        config.REPO, config.BRANCH, filename)


# --------------------------------------------------------------------------
# 产物实现
# --------------------------------------------------------------------------

def build_artifact(art, offline):
    """预取所有输入；缺必选输入返回 None（可选输入缺失只告警）。"""
    ok = []
    for inp in art["inputs"]:
        try:
            text = fetch(inp["url"], offline)
        except FetchError as exc:
            msg = "[%s] 上游不可达: %s" % (art["file"], exc)
            if inp.get("optional"):
                WARNINGS.append(msg + "（可选输入，跳过）")
            elif art.get("optional"):
                WARNINGS.append(msg + "（可选产物，整体跳过）")
            else:
                FAILURES.append(msg)
            continue
        ok.append((inp, text))
    fetched_ok = [i for i, _t in ok]
    missing_required = [i for i in art["inputs"]
                        if not i.get("optional") and i not in fetched_ok]
    if missing_required:
        return None
    merged = dict(art)
    merged["_inputs"] = ok
    return merged


def realize_raw(art):
    inp, text = art["_inputs"][0]
    for token in art.get("must_contain", []):
        if token not in text:
            FAILURES.append("[%s] 内容缺少特征 %r，上游疑似变更" % (art["file"], token))
            return None
    return text


def parse_mitm_hostnames(text):
    """提取模块文本 [MITM] 段的 hostname 域名列表（纯函数，selftest 覆盖）。

    支持 "hostname = %APPEND% a, b" 与 "hostname = a, b" 两种写法。
    返回域名串（', ' 分隔）；无 [MITM] 段时返回 ""。
    """
    in_mitm = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_mitm = (s == "[MITM]")
            continue
        if in_mitm and s.lower().startswith("hostname"):
            val = s.split("=", 1)[1].strip()
            if val.startswith("%APPEND%"):
                val = val[len("%APPEND%"):].strip()
            domains = [d.strip() for d in val.split(",") if d.strip()]
            return ", ".join(domains)
    return ""


def append_argument_to(text, arg, origin):
    """在模块 [Script] 段 argument= 行末尾追加参数（如 configUrl=<url>）。

    上游 location-spoofer 的 argument 是行尾段（mode=...&debug=false），
    远程配置由此注入；找不到 argument= 行时返回 None（上游模板变更）。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "argument=" in line:
            lines[i] = line.rstrip() + "&" + arg
            return "\n".join(lines)
    return None


def realize_module(art, emitted):
    inp, text = art["_inputs"][0]
    target = art.get("rewrite_to", "")
    hits = 0
    arg_hits = 0
    if art.get("rewrite_js"):
        pat = re.compile(art["rewrite_js"])
        hits = len(pat.findall(text))
        text = pat.sub(script_url_for(target), text)
        if hits == 0:
            WARNINGS.append("[%s] rewrite 正则未命中任何 js 地址，模块仍指向上游" % art["file"])
    if art.get("append_argument"):
        patched = append_argument_to(text, art["append_argument"], art["file"])
        if patched is None:
            FAILURES.append("[%s] 未找到 argument= 行，无法注入 %r，上游模板疑似变更"
                            % (art["file"], art["append_argument"].split("=")[0]))
            return None
        text = patched
        arg_hits = 1
    for token in art.get("must_contain", []):
        if token not in text:
            FAILURES.append("[%s] 内容缺少特征 %r，模板疑似变更需人工检查" % (art["file"], token))
            return None
    if art.get("rewrite_js") and target not in emitted:
        if art.get("optional"):
            WARNINGS.append("[%s] 依赖的 %s 未产出，本模块跳过（上游恢复后重跑即可）"
                            % (art["file"], target))
            return None
        FAILURES.append("[%s] 依赖的 %s 未产出" % (art["file"], target))
        return None
    mitm = parse_mitm_hostnames(text)
    if mitm:
        MITM_MAP[art["file"]] = mitm
    return text, {"hits": hits, "arg_hits": arg_hits}


def realize_gm_module(art):
    """三桶模块：按解析器分流到域名集/带类型规则集，例外剔除后统一合并。

    返回 (domains, rules, stats, kw_total)；解析器不识别时返回 (None, None, [], 0)。
    """
    domains, exceptions, rules = set(), set(), set()
    stats, kw_total = [], 0
    for inp, text in art["_inputs"]:
        parser = inp["parser"]
        if parser == "adguard":
            blocks, st, exc = parse_adguard(text)
            domains |= blocks
            exceptions |= exc
            n_dom, n_rule, kw = len(blocks), 0, 0
        elif parser == "plain":
            got, st = parse_plain(text)
            domains |= got
            n_dom, n_rule, kw = len(got), 0, 0
        elif parser == "surge":
            got, st = parse_surge(text)
            rules |= got
            n_dom, n_rule, kw = 0, len(got), st.get("keyword", 0)
        elif parser == "v2fly":
            got, st = parse_v2fly(text)
            rules |= got
            n_dom, n_rule, kw = 0, len(got), st.get("keyword", 0)
        elif parser == "bm_domain":
            got, st = parse_bm_domain(text)
            rules |= got
            n_dom, n_rule, kw = 0, len(got), st.get("keyword", 0)
        else:
            FAILURES.append("[%s] gm_module 不支持解析器: %s" % (art["file"], parser))
            return None, None, [], 0
        kw_total += kw
        stats.append("%-9s 域名=%d 规则=%d 丢弃关键词=%d 跳过=%d\n    %s\n    sha1 %s" % (
            parser, n_dom, n_rule, kw, st["skipped"], inp["url"], sha1_of(text)))
    return domains - exceptions, rules, stats, kw_total


# --------------------------------------------------------------------------
# 产出写盘（LF / 无 BOM / 回读校验）
# --------------------------------------------------------------------------

def write_lf(path, content):
    if not content or not content.strip():
        FAILURES.append("[写盘] %s 内容为空" % path.name)
        return
    data = content.encode("utf-8")
    if not data.endswith(b"\n"):
        data += b"\n"
    path.write_bytes(data)
    back = path.read_bytes()
    if b"\r" in back:
        FAILURES.append("[字节校验] %s 含 CR" % path.name)
    if back.startswith(b"\xef\xbb\xbf"):
        FAILURES.append("[字节校验] %s 含 BOM" % path.name)
    return data


def _inline_lines(domains, rules, policy):
    """桶内规则内联展开为模块 [Rule] 行（纯函数，selftest 覆盖）。

    domains: 纯域名集（后缀语义）-> DOMAIN-SUFFIX,d,POLICY
    rules:   带类型规则集 -> TYPE,val,POLICY[,no-resolve]
    """
    lines = ["DOMAIN-SUFFIX,%s,%s" % (d, policy) for d in sorted(domains)]
    for r in sorted(rules):
        parts = r.split(",")
        tail = parts[2] if len(parts) >= 3 and parts[2] in ("no-resolve", "src") else ""
        head = parts[0] + "," + parts[1]
        lines.append(head + "," + policy + ("," + tail if tail else ""))
    return lines


def gm_module_text(art, domains, rules, comments=None):
    """三桶内联模块（GM 式：注释与规则内联进 [Rule] 段，注释在规则前）。"""
    head = [
        "#!name=%s" % (art.get("title") or art["file"].split(".")[0]),
        "#!desc=自动聚合(源: build/buckets/)，统一策略 %s；上游明细与交集报告见 dist/report.txt"
            % art["policy"],
        "#!category=分流",
        "",
        "[Rule]",
    ]
    body = list(comments or []) + _inline_lines(domains, rules, art["policy"])
    return "\n".join(head + body)


# --------------------------------------------------------------------------
# 规则桶（build/buckets/ 一桶一文件，动态发现）
# --------------------------------------------------------------------------

_RULE_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "IP-CIDR6",
    "IP-ASN", "USER-AGENT", "URL-REGEX", "GEOIP", "DST-PORT", "PROTOCOL",
}


def discover_buckets():
    """加载 buckets/*.py 为桶定义列表（文件名排序，确定性）。

    桶文件字段: POLICY / TITLE / GUARDS / UPSTREAMS / RULES
    POLICY=None 为透传桶（如 me.py）: 不拉上游，每行规则自带策略。
    返回: [{file: <桶名>.module, policy, title, guards, upstreams, rules_text}]
    """
    buckets = []
    for path in sorted(BUCKETS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location("bucket_" + path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # noqa: BLE001
            FAILURES.append("[桶 %s] 加载失败: %s" % (path.name, exc))
            continue
        buckets.append(dict(
            file=path.stem + ".module",
            policy=getattr(mod, "POLICY", None),
            title=getattr(mod, "TITLE", None) or path.stem,
            guards=getattr(mod, "GUARDS", None),
            upstreams=getattr(mod, "UPSTREAMS", []) or [],
            rules_text=getattr(mod, "RULES", "") or "",
        ))
    if not buckets:
        FAILURES.append("未发现任何桶文件（build/buckets/*.py）")
    return buckets


def parse_manual_rules(text, policy, origin):
    """解析桶内手工 RULES 文本 -> 带类型规则集（与上游规则同构）。

    gm 桶（policy 非 None）:  行格式 类型,值[,no-resolve|src]，策略自动=桶 POLICY；
                              若显式写了策略必须等于桶 POLICY，否则提示改到 me 桶。
    透传桶（policy=None）:    行必须 类型,值,策略[,no-resolve|src]，策略自选。
    """
    rules = set()
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split(",")]
        typ = parts[0].upper()
        if typ not in _RULE_TYPES or len(parts) < 2 or not parts[1]:
            FAILURES.append("[%s] 手工规则格式错误: %r" % (origin, s))
            continue
        if typ in ("IP-CIDR", "IP-CIDR6"):
            try:
                ipaddress.ip_network(parts[1], strict=False)
            except ValueError:
                FAILURES.append("[%s] 非法网段: %r" % (origin, s))
                continue
        if typ == "IP-ASN" and not parts[1].isdigit():
            FAILURES.append("[%s] IP-ASN 非数字: %r" % (origin, s))
            continue
        tail = ""
        if policy is None:
            if len(parts) < 3 or not parts[2]:
                FAILURES.append("[%s] 透传桶规则必须自带策略（类型,值,策略）: %r"
                                % (origin, s))
                continue
            pol, tail = parts[2], (parts[3] if len(parts) >= 4
                                   and parts[3] in ("no-resolve", "src") else "")
            rules.add(typ + "," + parts[1] + "," + pol
                      + (("," + tail) if tail else ""))
            continue
        extra = [p for p in parts[2:] if p]
        if extra and extra[-1] in ("no-resolve", "src"):
            tail = extra[-1]
            extra = extra[:-1]
        if extra and extra[0] == policy:
            extra = extra[1:]
        elif extra:
            FAILURES.append("[%s] 桶策略为 %s，想用 %s 请写到 me 桶: %r"
                            % (origin, policy, extra[0], s))
            continue
        if extra:
            FAILURES.append("[%s] 手工规则多余字段: %r" % (origin, s))
            continue
        rules.add(typ + "," + parts[1] + (("," + tail) if tail else ""))
    return rules


def _manual_body(text):
    """透传桶模块正文: 原样保留（含注释），仅去尾部空白。"""
    return "\n".join(text.strip().splitlines())


def _comment_lines(text):
    """提取桶 RULES 文本里的注释行（保留原顺序；gm 桶产物内联用）。

    桶内以 # 开头的行是维护者说明（改完会随构建进入产物模块，
    小火箭模块详情里可见）；规则行由 parse_manual_rules 解析。
    """
    return [l.rstrip() for l in text.splitlines() if l.strip().startswith("#")]


results, rules_by_file = [], {}
kw_drops = {}
emitted = set()
MITM_MAP = {}      # 模块名 -> MITM hostname 域名串（主配置 [MITM] 段引用）


def build_bucket(b, offline):
    """构建单个桶 -> (status, count)。结果写入全局 results/rules_by_file/emitted。"""
    fname = b["file"]
    stats = []
    manual = parse_manual_rules(b["rules_text"], b["policy"],
                                "build/buckets/%s.py" % fname.split(".")[0])

    if b["policy"] is None:
        # 透传桶（如 me.py）: 无上游，正文=原样手工行（含注释）
        text = "\n".join([
            "#!name=%s" % b["title"],
            "#!desc=个人覆盖规则（源: build/buckets/，模块置顶=优先级最高）",
            "#!category=分流",
            "",
            "[Rule]",
            _manual_body(b["rules_text"]),
        ])
        write_lf(DIST_DIR / fname, text)
        rules_by_file[fname] = manual
        emitted.add(fname)
        results.append((fname, "bucket", "OK", len(manual),
                        ["源: build/buckets/%s.py（透传桶，无上游）"
                         % fname.split(".")[0]]))
        return "OK", len(manual)

    # gm 桶: 预取上游后与手工规则合并
    inputs = _prefetch(b["upstreams"], fname, offline)
    if any(not i.get("optional") for i in b["upstreams"]) and \
            len(inputs) < sum(1 for i in b["upstreams"] if not i.get("optional")):
        results.append((fname, "bucket", "FAIL", 0, []))
        return "FAIL", 0
    dom, rul, stats, kw_total = realize_gm_module(dict(
        file=fname, policy=b["policy"], _inputs=inputs))
    if dom is None:
        results.append((fname, "bucket", "FAIL", 0, stats))
        return "FAIL", 0
    total = len(dom) + len(rul) + len(manual)
    if b["guards"]:
        lo, hi = b["guards"]
        if not lo <= total <= hi:
            FAILURES.append("[%s] 条数 %d 超出防线 [%d,%d]，上游疑似异常"
                            % (fname, total, lo, hi))
            results.append((fname, "bucket", "FAIL", total, stats))
            return "FAIL", total
    if kw_total:
        kw_drops[fname] = kw_total
    write_lf(DIST_DIR / fname,
             gm_module_text(dict(file=fname, title=b["title"], policy=b["policy"]),
                            dom, rul | manual, _comment_lines(b["rules_text"])))
    rules_by_file[fname] = ({"DOMAIN-SUFFIX,%s" % d for d in dom}) | rul | manual
    emitted.add(fname)
    results.append((fname, "bucket", "OK", total,
                    stats + ["手工规则 %d 条（源: build/buckets/%s.py）"
                             % (len(manual), fname.split(".")[0])]))
    return "OK", total


def _prefetch(inputs, fname, offline):
    """预取桶上游，返回成功列表；可选源失败只告警。"""
    ok = []
    for inp in inputs:
        try:
            ok.append((inp, fetch(inp["url"], offline)))
        except FetchError as exc:
            msg = "[%s] 上游不可达: %s" % (fname, exc)
            if inp.get("optional"):
                WARNINGS.append(msg + "（可选输入，跳过）")
            else:
                FAILURES.append(msg)
    return ok


_URL_TPL_RE = re.compile(r"\{\{URL::([^}\s]+)\}\}")
_MITM_TPL_RE = re.compile(r"\{\{MITM::([^}\s]+)\}\}")


def render_conf(available):
    if not CONF_TPL.exists():
        FAILURES.append("配置模板缺失: %s" % CONF_TPL)
        return None

    def repl(m):
        fname = m.group(1)
        if fname not in available:
            FAILURES.append("[main.conf] 引用的产物未生成: " + fname)
            return "ABOUT:MISSING:" + fname
        return url_for(fname)

    def repl_mitm(m):
        fname = m.group(1)
        val = MITM_MAP.get(fname, "")
        if not val:
            WARNINGS.append("[main.conf] %s 未提供 MITM 域名（上游缺失?），[MITM] 段将省略" % fname)
        return val

    out = CONF_TPL.read_text(encoding="utf-8")
    out = _URL_TPL_RE.sub(repl, out)
    out = _MITM_TPL_RE.sub(repl_mitm, out)
    # 上游缺失时 hostname 为空 -> 整段删除，避免产出空 [MITM] 段
    out = re.sub(r"\[MITM\](?:\n#[^\n]*)*\nhostname = \n(\n)?", "", out)
    leftovers = re.findall(r"\{\{[^}]*\}\}", out)
    if leftovers:
        FAILURES.append("[main.conf] 模板占位符未识别: %s" % leftovers)
    return out


# --------------------------------------------------------------------------
# 冲突检测与报告
# --------------------------------------------------------------------------

def _rule_domains(rules):
    s = set()
    for r in rules:
        p = r.split(",")
        if p[0] in ("DOMAIN", "DOMAIN-SUFFIX") and len(p) >= 2:
            s.add(p[1])
    return s


def conflict_lines(reject_domains, rules_by_file):
    """交集冲突只在桶之间检验（reject 桶的纯域名集与其他桶的域名）。"""
    lines = []

    def _domains_of(fname):
        return {r.split(",")[1] for r in rules_by_file.get(fname, set())
                if r.startswith(("DOMAIN,", "DOMAIN-SUFFIX,"))}

    direct_d = _domains_of("direct.module")
    proxy_d = _domains_of("proxy.module")
    checks = [
        ("REJECT ∩ DIRECT（按模块顺序将以 REJECT 拦截，预期为国内广告统计域名）",
         reject_domains & direct_d),
        ("REJECT ∩ PROXY（将对代理域名生效拦截，预期为国外广告域名）",
         reject_domains & proxy_d),
        ("DIRECT ∩ PROXY（两边都收录，direct 模块在前为先；预期为灰色双收录）",
         direct_d & proxy_d),
    ]
    for label, s in checks:
        lines.append("### %s: %d 条" % (label, len(s)))
        lines += ["    - " + d for d in sorted(s)[:50]]
        if len(s) > 50:
            lines.append("    ...（仅列前 50）")
        lines.append("")
    # v2fly 的 cn 与 geolocation-!cn 存在约 1%~2% 的双收录灰色地带
    # （苹果海外促销域名等），超过 8000 才视为上游数据异常
    if len(direct_d & proxy_d) > 8000:
        WARNINGS.append("DIRECT∩PROXY 交集 %d 条，远超正常水平（~2%%），上游数据可能异常"
                        % len(direct_d & proxy_d))
    return lines


def write_report(results, kw_drops, reject_domains, rules_by_file):
    lines = [
        "================ 规则聚合构建报告 ================",
        "仓库: %s@%s   URL_SCHEME=%s" % (config.REPO, config.BRANCH, config.URL_SCHEME),
        "说明: 本文件不含时间戳，上游无变化时重复构建逐字节相同。",
        "",
        "---- 产物清单 ----",
    ]
    for fname, kind, status, cnt, stats in results:
        lines.append("%-22s %-10s %-7s %8d" % (fname, kind, status, cnt))
        for s in stats:
            lines.append("    " + s.replace("\n", "\n    "))
        lines.append("")
    if kw_drops:
        lines.append("---- 自动源 DOMAIN-KEYWORD 丢弃统计（铁律，仅 me.list 允许） ----")
        lines += ["    %s: %d" % (k, v) for k, v in sorted(kw_drops.items())]
        lines.append("")
    lines.append("---- 交集冲突（只报告，处置见 conf 优先级与 me.list 覆盖） ----")
    lines += conflict_lines(reject_domains, rules_by_file)
    if WARNINGS:
        lines.append("---- 告警 ----")
        lines += ["  [W] " + w for w in WARNINGS]
        lines.append("")
    if FAILURES:
        lines.append("---- 失败 ----")
        lines += ["  [F] " + f for f in FAILURES]
        lines.append("")
    lines.append("规则数区间防线、URL 方案等见 build/config.py；小火箭导入步骤见 dist/main.conf 头部注释。")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 自测
# --------------------------------------------------------------------------

def selftest():
    got, st = parse_v2fly(
        "full:apps.apple.com\n"
        "google.com\n"
        "+.baidu.com\n"
        "keyword:tv\n"
        "example.com @cn\n"
        "regexp:.*\n"
        "bad..input\n")
    assert got == {"DOMAIN,apps.apple.com", "DOMAIN-SUFFIX,google.com",
                   "DOMAIN-SUFFIX,baidu.com"}, got
    assert st["skipped"] == 4, st

    got, st = parse_plain("# c\nqq.com\nQQ.COM.\n+.adsrvr.org\nbad line\n")
    assert got == {"qq.com", "adsrvr.org"}, got
    assert st["skipped"] == 1, st

    got, st = parse_bm_domain(".apple.com\napps.apple.com\n# c\nbad!\n")
    assert got == {"DOMAIN-SUFFIX,apple.com", "DOMAIN,apps.apple.com"}, got
    assert st["skipped"] == 1, st

    # 内联展开：域名后缀 + 带类型规则（含 no-resolve 尾缀） + 排序确定性
    lines = _inline_lines(
        {"b.com", "a.com"},
        {"DOMAIN-SUFFIX,netflix.com", "IP-CIDR,8.41.4.0/24,no-resolve",
         "IP-CIDR6,2400:cb00::/32", "IP-ASN,20473,no-resolve"},
        "REJECT")
    assert lines[0] == "DOMAIN-SUFFIX,a.com,REJECT"
    assert "DOMAIN-SUFFIX,b.com,REJECT" in lines
    assert "DOMAIN-SUFFIX,netflix.com,REJECT" in lines
    assert "IP-CIDR,8.41.4.0/24,REJECT,no-resolve" in lines, lines
    assert "IP-CIDR6,2400:cb00::/32,REJECT" in lines
    assert "IP-ASN,20473,REJECT,no-resolve" in lines
    assert lines == sorted(lines[:2]) + lines[2:], "前两条应按域名排序"

    # [MITM] hostname 提取：APPEND 与裸写两种格式 / 无段返回空
    assert parse_mitm_hostnames(
        "[Script]\nx = 1\n\n[MITM]\nhostname = %APPEND% a.com, b.cn\n"
    ) == "a.com, b.cn"
    assert parse_mitm_hostnames("[MITM]\nhostname = c.com\n") == "c.com"
    assert parse_mitm_hostnames("[Rule]\nDOMAIN,x.com,DIRECT\n") == ""
    # 空 hostname 时整段删除（含注释行）
    stripped = re.sub(
        r"\[MITM\](?:\n#[^\n]*)*\nhostname = \n(\n)?", "",
        "[General]\nx = 1\n\n[MITM]\n# 注释\nhostname = \n\n[Rule]\ny = 2\n")
    assert "[MITM]" not in stripped and "[General]" in stripped and "[Rule]" in stripped

    # argument 注入：找 argument= 行追加；找不到返回 None
    out = append_argument_to(
        "[Script]\nspoofer = type=http-response,script-path=x.js,argument=mode=response&debug=false\n\n[MITM]\nhostname = a.com",
        "configUrl=https://w.example/loc.json?token=t1", "t")
    assert "argument=mode=response&debug=false&configUrl=https://w.example/loc.json?token=t1" in out, out
    assert "hostname = a.com" in out          # 其余段落不受影响
    assert append_argument_to("no argument here\n", "x=1", "t") is None

    assert gm_module_text(
        dict(file="x.module", policy="DIRECT"), {"a.com"}, set()
    ).splitlines()[0] == "#!name=x"

    # gm 桶注释保留: RULES 里的 # 行随构建进入产物，规则前的注释块可见
    assert _comment_lines("# a\nDOMAIN,x\n   # b  \n\n") == ["# a", "   # b"]
    m = gm_module_text(dict(file="x.module", policy="PROXY"), set(),
                       {"DOMAIN-SUFFIX,a.com"}, ["# note"])
    assert "# note" in m and "DOMAIN-SUFFIX,a.com,PROXY" in m
    assert m.index("# note") < m.index("DOMAIN-SUFFIX,a.com"), "注释应在规则前"

    # 手工规则解析：gm 桶自动补策略 / 策略冲突拦截 / 透传桶三段校验
    got = parse_manual_rules(
        "# c\n\nDOMAIN-SUFFIX,qq.com\nIP-CIDR,1.2.3.0/24,no-resolve\n"
        "DOMAIN-SUFFIX,ok.com,DIRECT\n", "DIRECT", "t-direct")
    assert got == {"DOMAIN-SUFFIX,qq.com", "IP-CIDR,1.2.3.0/24,no-resolve",
                   "DOMAIN-SUFFIX,ok.com"}, got
    parse_manual_rules("DOMAIN-SUFFIX,x.com,PROXY\n", "DIRECT", "t-conflict")
    assert any("写到 me 桶" in f for f in FAILURES), "冲突策略应报错"
    FAILURES.clear()
    got = parse_manual_rules(
        "DOMAIN-SUFFIX,netflix.com,PROXY\nIP-CIDR,9.9.9.0/24,REJECT,no-resolve\n",
        None, "t-me")
    assert got == {"DOMAIN-SUFFIX,netflix.com,PROXY",
                   "IP-CIDR,9.9.9.0/24,REJECT,no-resolve"}, got
    parse_manual_rules("DOMAIN-SUFFIX,onlytwo\n", None, "t-me2")
    assert any("自带策略" in f for f in FAILURES), "透传桶缺策略应报错"
    FAILURES.clear()

    blocks, st, exc = parse_adguard(
        "! comment\n"
        "||ads.example.com^\n"
        "||track.example.com^$third-party\n"
        "@@||ok.example.com^\n"
        "##div\n"
        "/regexfilter/\n"
        "||bad*.com^\n"
        "0.0.0.0 hosts.line\n")
    assert blocks == {"ads.example.com", "track.example.com"}, blocks
    assert exc == {"ok.example.com"}, exc
    assert st["skipped"] == 5, st

    got, st = parse_surge(
        "# NAME: X\n"
        "DOMAIN-SUFFIX,netflix.com,PROXY\n"
        "DOMAIN,api.netflix.com\n"
        "IP-CIDR,8.41.4.0/24,no-resolve\n"
        "IP-CIDR,2400:cb00::/32\n"
        "IP-CIDR8,9.9.9.9\n"
        "IP-CIDR,not-a-cidr\n"
        "IP-ASN,20473,no-resolve\n"
        "DOMAIN-KEYWORD,openai\n"
        "USER-AGENT,Netflix*\n")
    assert "DOMAIN-SUFFIX,netflix.com" in got
    assert "DOMAIN,api.netflix.com" in got
    assert "IP-CIDR,8.41.4.0/24,no-resolve" in got
    assert "IP-CIDR6,2400:cb00::/32" in got, got   # v6 自动规范化
    assert "IP-ASN,20473,no-resolve" in got
    assert "USER-AGENT,Netflix*" in got
    assert not any(r.startswith("DOMAIN-KEYWORD,") for r in got)   # 铁律
    assert st["keyword"] == 1 and st["skipped"] == 2, st

    assert _valid_domain("xn--fiqs8s.xn--55qx5d.cn")
    assert not _valid_domain("a")
    assert not _valid_domain("a..b")
    assert not _valid_domain("-a.com")
    assert not _valid_domain("a b.com")

    print("selftest: 5 个解析器 + 内联展开/注释保留 + 手工规则解析 + 域名校验全部通过")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="shadowrocket 规则聚合构建",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="网络失败自动回退 .cache/ 缓存；HTTPS_PROXY 环境变量会被自动识别。")
    ap.add_argument("--offline", action="store_true", help="断网，仅用本地缓存")
    ap.add_argument("--selftest", action="store_true", help="只跑内置自测")
    args = ap.parse_args(argv)

    if args.selftest:
        selftest()
        return 0

    print("== 规则聚合构建 ==")
    print("模式: %s   URL_SCHEME=%s" % ("offline" if args.offline else "online",
                                        config.URL_SCHEME))
    print("订阅基址: %s" % url_for("main.conf"))
    DIST_DIR.mkdir(exist_ok=True)

    # 1) 规则桶（build/buckets/ 一桶一文件）
    buckets = discover_buckets()
    for b in buckets:
        build_bucket(b, args.offline)

    # 2) 特殊产物（spoofer 等，定义在 build/config.py）
    for art in config.EXTRA_ARTIFACTS:
        fname, kind = art["file"], art["kind"]
        fetched = build_artifact(art, args.offline)
        if fetched is None:
            results.append((fname, kind, "SKIP", 0, []))
            continue
        if kind == "raw":
            text = realize_raw(fetched)
            if text is None:
                results.append((fname, kind, "FAIL", 0, []))
                continue
            write_lf(DIST_DIR / fname, text)
            emitted.add(fname)
            results.append((fname, kind, "OK", len(text.splitlines()),
                            ["按原样分发 %d 字节" % len(text.encode("utf-8"))]))
        elif kind == "module":
            ret = realize_module(fetched, emitted)
            if ret is None:
                results.append((fname, kind, "SKIP/FAIL", 0, []))
                continue
            text, meta = ret
            write_lf(DIST_DIR / fname, text)
            emitted.add(fname)
            mod_stats = ["js 链接重写 %d 处 -> %s" % (meta["hits"],
                                                      art.get("rewrite_to"))]
            if meta.get("arg_hits"):
                mod_stats.append("argument 注入 %s" % art["append_argument"].split("=", 1)[0])
            results.append((fname, kind, "OK", len(text.splitlines()), mod_stats))
        else:
            FAILURES.append("[%s] 未知产物类型 %s" % (fname, kind))

    # 3) 桶生成了但模板没引用 -> 提醒补 {{URL::新桶.module}}
    if CONF_TPL.exists():
        referenced = set(_URL_TPL_RE.findall(CONF_TPL.read_text(encoding="utf-8")))
        for b in buckets:
            if b["file"] not in referenced:
                WARNINGS.append("桶 %s 已构建但模板未引用（小火箭里也需手动添加），"
                                "请在 build/templates/main.conf.template 补 %s"
                                % (b["file"], "{{URL::" + b["file"] + "}}"))

    # 4) 主配置
    conf = render_conf(emitted | {"main.conf"})
    if conf is not None:
        write_lf(DIST_DIR / "main.conf", conf)
        results.append(("main.conf", "conf", "OK", len(conf.splitlines()), []))

    # 报告（reject 桶域名单独提取；桶文件名 reject.module）
    reject_d = set()
    if "reject.module" in rules_by_file:
        reject_d = {r.split(",", 1)[1] for r in rules_by_file["reject.module"]
                    if r.startswith("DOMAIN-SUFFIX,")}
    # 构建全绿时清理 dist 里不再生成的残留（上游改版/配置瘦身后的旧产物）
    if not FAILURES:
        keep = emitted | {"main.conf", "report.txt"}
        for old in sorted(DIST_DIR.iterdir()):
            if old.is_file() and old.name not in keep:
                old.unlink()
                WARNINGS.append("已清理残留产物: %s" % old.name)
    report = write_report(results, kw_drops, reject_d, rules_by_file)
    write_lf(DIST_DIR / "report.txt", report)

    print("\n---- 产物 ----")
    for fname, _kind, status, cnt, _stats in results:
        print("  %-22s %-7s %8d" % (fname, status, cnt))
    if WARNINGS:
        print("\n---- 告警 (%d) ----" % len(WARNINGS))
        for w in WARNINGS:
            print("  [W] " + w)
    if FAILURES:
        print("\n[构建失败] %d 处问题:" % len(FAILURES))
        for f in FAILURES:
            print("  [F] " + f)
        return 1
    print("\n[构建成功] 产物在 dist/，审计报告: dist/report.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
