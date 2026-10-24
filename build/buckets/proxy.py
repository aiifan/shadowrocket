# -*- coding: utf-8 -*-
# ================= 代理桶（已知国外域名） =================
# 产物: dist/proxy.module，小火箭里装在直连桶之后
# 策略用 PROXY 关键字 = 小火箭首页当前选中的节点（单节点直接用）
# 字段说明见 direct.py 头部注释
# ==================================================================

POLICY = "PROXY"
TITLE = "代理"
GUARDS = (10000, 400000)

UPSTREAMS = [
    # Loyalsoldier geolocation-!cn（gfwlist+v2fly 社区维护）
    dict(url="https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/proxy-list.txt",
         parser="v2fly"),
    # ---- 分领域补充（blackmatrix7，皆并入 PROXY 桶）----
    dict(url="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/OpenAI/OpenAI.list",
         parser="surge", optional=True),
    dict(url="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/Anthropic/Anthropic.list",
         parser="surge", optional=True),
    dict(url="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/Netflix/Netflix.list",
         parser="surge"),
    dict(url="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/YouTube/YouTube.list",
         parser="surge"),
    dict(url="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/Disney/Disney.list",
         parser="surge"),
    dict(url="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/Telegram/Telegram.list",
         parser="surge"),
    # 苹果海外域名（Apple_Domain.list 为全量域名清单）
    dict(url="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/Apple/Apple_Domain.list",
         parser="bm_domain"),
]

RULES = """
# 在此追加手工代理规则，示例:
# DOMAIN-SUFFIX,example.dev
"""
