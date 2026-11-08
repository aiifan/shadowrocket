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
# 定位欺骗（spoofer）已停用：上游失效 + 主配置 [MITM] 段已移除，
# 不再构建/分发 spoofer.module 与 location-spoofer.js。
# 如需恢复，从 git 历史找回本段与模板 [MITM] 段即可。
EXTRA_ARTIFACTS = []
