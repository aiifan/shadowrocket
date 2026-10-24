# -*- coding: utf-8 -*-
# ================= 个人规则桶（置顶模块） =================
# 产物: dist/me.module — 小火箭模块列表里放最顶上，优先级最高，
#       可覆盖一切自动分流结果
# ------------------------------------------------------------------
# 本桶是"透传桶"(POLICY=None): 不拉上游，RULES 每行自带策略:
#   类型,值,策略[,no-resolve]
#   策略: DIRECT / PROXY / REJECT  （PROXY=当前选中节点）
# 适合: 误判纠正、临时屏蔽、某一域名单独指定策略
# 自动源的 DOMAIN-KEYWORD 一律被构建丢弃（防误杀），关键词规则只写这里
# ==================================================================

POLICY = None          # None = 每行规则必须自带策略
TITLE = "个人规则"

RULES = """
# --- 误判纠正示例: 某国内域名被分到代理，强制直连 ---
# DOMAIN-SUFFIX,example.com.cn,DIRECT

# --- 某国内备案站想走代理 ---
# DOMAIN-SUFFIX,some.cn.site,PROXY

# --- 追加屏蔽 ---
# DOMAIN-SUFFIX,ads.example.com,REJECT

# --- 某域名想单独走某个分支(比如 Telegram 图床) ---
# DOMAIN-SUFFIX,imgbox.com,PROXY

# 保底规则（有自己的规则后可删）
IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
"""
