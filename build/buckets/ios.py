# -*- coding: utf-8 -*-
# ================= iOS 服务桶（APNs 推送 + iCloud，统一走代理） =================
# 产物: dist/ios.module —— 小火箭里必须装在 direct 模块之前！
# 由 push.py 更名并并入 iCloud 主域；旧 dist/push.module 会被构建自动清理，
# 小火箭里需删除旧 push 模块、改添加 .../dist/ios.module（位置不变，direct 前）
# ------------------------------------------------------------------
# 为什么合成一桶（而不是 me.py 或 push/icloud 各一桶）:
#   两者都是"iOS 系统级通道走代理"(POLICY=PROXY) 且都要求排在 direct 前:
#   - APNs: 防 apple-cn 源把 init-*.push-apple.com 精确域劫成直连
#   - iCloud: proxy 桶的 Apple 全域名表(上游)其实已含 icloud.com 等主域
#     (实测 2026-10 已走代理)，此处显式单列 = 前置优先级防上游列表变动
#     截胡 + 模块里看得见好排查。me.com/mac.com 为 iCloud 邮件/日历旧域，
#     apple-cloudkit.com 为 iCloud/三方 App 的 CloudKit 存储域
# ------------------------------------------------------------------
# 域名依据: Apple 官方文档 Apple Platform Deployment - APNs 章节
#   push.apple.com 后缀  = courier/api 长连主域(1~8-courier, TCP 5223/443)
#   push-apple.com 后缀  = init-* 初始化域名
#   push-apple.com.akadns.net = init 域名 CNAME 目标(akadns 结尾不在上两后缀内)
#   Apple 不公布 APNs 专属 IP 段(散布 17.0.0.0/8 且漂移)；长连为 TLS 必带
#   SNI，域名规则 100% 命中，裸 IP 用专用端口 TCP 5223 兜底
# ==================================================================

POLICY = "PROXY"
TITLE = "iOS 服务（APNs推送+iCloud）"
GUARDS = (4, 50)          # 手写桶，上限收紧防误粘贴大列表

UPSTREAMS = []            # 纯手写，无上游

RULES = """
# ===== iOS 服务统一走 PROXY（本模块须排 direct 模块之前）=====
# 一、APNs 推送（依据 Apple 官方文档）:
#   push.apple.com 后缀 = courier/api 长连主域(TCP 5223/443)
#   push-apple.com 后缀 = init-* 初始化域名
#   push-apple.com.akadns.net = init 域名 CNAME 目标(不在上两后缀内,须单列)
#   DST-PORT,5223 = APNs 专用端口兜底(Apple 不公布专属 IP 段,长连必带 SNI)
# 二、iCloud 同步（美区 Apple ID 显式走代理）:
#   icloud.com / icloud-content.com = 同步主域
#   me.com / mac.com = iCloud 邮件/日历旧域
#   apple-cloudkit.com = iCloud 与三方 App 的 CloudKit 存储域
#
# ⚠ 使用注意: 改动本桶策略(PROXY<->DIRECT)或节点出口网段变化后，
#   系统已建立的 APNs 长连接可能"僵死"——表现为节点正常但收不到
#   任何推送（含 X/Telegram/微信等所有远程通知）。
#   修复: 开关一次飞行模式（约 1 分钟），强制 iOS 重建 APNs 连接
#   走新路由。改完先想起这一步，能少排查一小时。
DOMAIN-SUFFIX,push.apple.com
DOMAIN-SUFFIX,push-apple.com
DOMAIN-SUFFIX,push-apple.com.akadns.net
DST-PORT,5223
DOMAIN-SUFFIX,icloud.com
DOMAIN-SUFFIX,icloud-content.com
DOMAIN-SUFFIX,me.com
DOMAIN-SUFFIX,mac.com
DOMAIN-SUFFIX,apple-cloudkit.com
"""
