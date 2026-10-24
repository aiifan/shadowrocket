# -*- coding: utf-8 -*-
# ================= 拒绝桶（广告/隐私拦截） =================
# 产物: dist/reject.module，小火箭里装在 me 之后、直连桶之前
# （必须在 direct 前面：国内广告域名两边都收录，靠顺序拦下）
# 字段说明见 direct.py 头部注释
# ==================================================================

POLICY = "REJECT"
TITLE = "拦截"
GUARDS = (10000, 300000)

UPSTREAMS = [
    # AdGuard DNS filter（现行官方地址，DNS 层纯域名拦截）
    dict(url="https://raw.githubusercontent.com/AdguardTeam/FiltersRegistry/master/filters/filter_15_DnsFilter/filter.txt",
         parser="adguard"),
    # yoyo 广告域名表（可选补充）
    dict(url="https://pgl.yoyo.org/adservers/serverlist.php?hostformat=nohtml&showintro=0",
         parser="plain", optional=True),
]

RULES = """
# 在此追加手工屏蔽规则，示例:
# DOMAIN-SUFFIX,ads.example.com
"""
