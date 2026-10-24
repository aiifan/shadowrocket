# -*- coding: utf-8 -*-
"""全局配置 —— 分桶后这里只放全局参数与非桶特殊产物。

规则桶在 build/buckets/ 目录，一桶一文件:
  direct.py / proxy.py / reject.py / me.py
想加新策略桶（如 game.py）:
  1. 复制 direct.py 改名，改 POLICY/TITLE/UPSTREAMS/RULES
  2. build/templates/main.conf.template 注释里补一行 {{URL::game.module}}
     并在小火箭里手动添加该模块
桶文件字段说明见 direct.py 头部注释。
"""

# GitHub 路径 = 订阅 URL 的基础。仓库在 GitHub 上的实际 owner/repo 与默认分支
REPO = "aiifan/shadowrocket"     # TODO: 确认与你 GitHub 新建仓库一致，不一致改这里
BRANCH = "main"

# 订阅 URL 方案:
#   jsdelivr  国内可达（约 12h 缓存）  https://cdn.jsdelivr.net/gh/REPO@BRANCH/...
#   raw       GitHub 直链，更新即时但需代理可达
URL_SCHEME = "jsdelivr"

# 脚本类资源(script-path)的下载方案 —— 独立于 URL_SCHEME。
#   js 文件是小火箭 MITM 命中瞬间实时拉取的运行时依赖，不敢用 jsdelivr
#   （国内偶发抽风 → “模块好好的脚本加载失败”静默失效）; raw 直链在
#   代理在线时(MITM 命中时必然在线)始终可达
SCRIPT_URL_SCHEME = "raw"

# ---------------------------------------------------------------------------
# 特殊产物（不走三桶机制）
# ---------------------------------------------------------------------------
_MS = "https://raw.githubusercontent.com/mekos2772/ios-location-spoofer/main"

# 定位欺骗「地图选点」远程配置：小火箭模块通过 configUrl 拉取 Worker 上的
# loc.json，地图选点保存即生效（约 60s 缓存）。
#
# 敏感信息走环境变量（本文件与仓库全程不含 token）：
#   spoofer 模块的 configUrl 取自环境变量 SPOOFER_CONFIG_URL —— 仅 CI 构建时
#   生效（Actions Secret 同名注入；本地构建默认不注入，本地想注入时：
#   $env:SPOOFER_CONFIG_URL="https://.../loc.json?token=xxx" 再跑构建）。
#   想改回非敏感静态写法，把 append_argument_env 换成 append_argument 即可。
# Worker 的部署方式见 .github/workflows/deploy-worker.yml（首次需配 4 个 Secrets）
EXTRA_ARTIFACTS = [
    # 定位欺骗脚本（原样分发，spoofer.module 依赖它，顺序必须在前）
    dict(
        file="location-spoofer.js", kind="raw", optional=True,
        must_contain=["wloc"],
        inputs=[dict(url=_MS + "/location-spoofer.js", parser="raw")],
    ),
    # 定位欺骗模块（拷贝上游 + 脚本 URL 重写为自托管，独立开关）
    dict(
        file="spoofer.module", kind="module", optional=True, policy="定位欺骗(独立模块)",
        rewrite_to="location-spoofer.js",
        rewrite_js=r"https?://[^\s\"'<>]+/location-spoofer\.js",
        append_argument_env="SPOOFER_CONFIG_URL:configUrl",
        must_contain=["gs-loc.apple.com"],
        inputs=[dict(url=_MS + "/ios-location-spoofer.sgmodule", parser="module")],
    ),
]
