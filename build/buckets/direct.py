# -*- coding: utf-8 -*-
# ================= 直连桶（国内） =================
# 产物: dist/direct.module，小火箭里装在 me/reject 之后
# ------------------------------------------------------------------
# POLICY    本桶所有规则的最终策略：DIRECT
# UPSTREAMS 自动规则源；parser 可选:
#             v2fly    Loyalsoldier 域名文本（geosite:cn 等）
#             surge    blackmatrix7 带类型规则集
#             bm_domain blackmatrix7 X_Domain.list 点前缀清单
#             plain    每行一个域名的纯文本（后缀语义）
#             adguard  adblock 语法（DNS filter，仅拒桶适用）
#           optional=True 的源挂了只告警，不影响其他源
# RULES     你的补充规则，格式: 类型,值[,no-resolve|src]
#           （策略自动补成 POLICY；想让某域名走别的策略写进 me.py）
# GUARDS    条数防线(下限,上限)：防上游改版产出空/残缺模块
#          （总条数=上游条数+RULES 条数，越界构建失败）
# ==================================================================

POLICY = "DIRECT"
TITLE = "国内直连"
GUARDS = (50000, 600000)

UPSTREAMS = [
    # Loyalsoldier geosite:cn（felixonmars china-list 每日构建）
    dict(url="https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/direct-list.txt",
         parser="v2fly"),
    # 苹果国内业务域名（CDN/地图/推送国内节点）
    dict(url="https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/apple-cn.txt",
         parser="v2fly"),
    # 微信（blackmatrix7）
    dict(url="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Shadowrocket/WeChat/WeChat.list",
         parser="surge"),
]

RULES = """
# 在此追加手工直连规则，示例:
# DOMAIN-SUFFIX,yourcompany.cn
"""
