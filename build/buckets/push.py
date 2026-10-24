# -*- coding: utf-8 -*-
# ================= iOS 推送桶（APNs） =================
# 产物: dist/push.module —— 小火箭里必须装在 direct 模块之前！
# 否则 init-*.push-apple.com 会被 direct 桶的 apple-cn 源截胡成直连
# ------------------------------------------------------------------
# 现状缺陷: proxy 桶的 apple.com 后缀已让 courier/api.push.apple.com
# 走 PROXY，但 apple-cn 精确域把 init-* 劫成 DIRECT，
# 推送会话"init 直连 + 长连代理"劈叉 —— 本桶统一为全部 PROXY
#
# 域名依据: Apple 官方文档（Apple Platform Deployment - APNs）
#   push.apple.com 后缀     = courier / api 长连接主域
#                             (1~8-courier.push.apple.com, TCP 5223/443)
#   push-apple.com 后缀     = init-* 初始化域名
#   push-apple.com.akadns.net = init 域名的 CNAME 目标(akadns 不落在
#                             上面两后缀内，须单独一条)
# IP 说明: Apple 不公布 APNs 专用 IP 段(实测散布 17.0.0.0/8 多个子段
#   且漂移，写死 /24 无意义)。APNs 长连接为 TLS 必带 SNI，域名规则
#   100% 命中; 裸 IP 场景用 APNs 专用端口 TCP 5223 兜底
# ==================================================================

POLICY = "PROXY"
TITLE = "推送"
GUARDS = (2, 50)          # 手写桶，上限收紧防误粘贴大列表

UPSTREAMS = []            # 纯手写，无上游

RULES = """
# ---- APNs 域名 ----
DOMAIN-SUFFIX,push.apple.com
DOMAIN-SUFFIX,push-apple.com
DOMAIN-SUFFIX,push-apple.com.akadns.net
# ---- 端口兜底（TCP 5223 为 APNs 专用端口，iOS 上基本只有推送使用）----
DST-PORT,5223
# 想把所有 Apple 自有服务(不只推送)整段兜进代理，解开下行注释:
# IP-CIDR,17.0.0.0/8,no-resolve
"""
