# wallet.md — Cấu Hình Agent 2 Copy Trader
# ─────────────────────────────────────────────────────────────────────────────
# FILE NÀY DO BẠN SỬA — Agent 2 hot-reload mỗi 15 giây (không cần restart)
#
# Cấu trúc file:
#   ## Settings       → bật/tắt chế độ, risk management
#   ## Manual Wallets → ví bạn muốn copy tay
#   ## Blacklist      → ví bạn muốn bỏ qua
#   ## Active Wallets → DO Agent 1 TỰ GHI (đừng sửa tay)
# ─────────────────────────────────────────────────────────────────────────────


## Settings

# ── Chế độ copy ──────────────────────────────────────────────────────────────
# AUTO_COPY=on  → copy theo Agent 1 (đọc copy_queue.jsonl)
# AUTO_COPY=off → tạm dừng auto copy (queue vẫn tích lại, bật lại sẽ đọc tiếp)
AUTO_COPY=off

# MANUAL_COPY=on  → copy ví bạn chỉ định trong ## Manual Wallets bên dưới
# MANUAL_COPY=off → tạm dừng manual copy
MANUAL_COPY=on

# ── Risk Management ──────────────────────────────────────────────────────────
# Tổng USDC bot được phép dùng (0 = không giới hạn)
# Bot sẽ từ chối đặt lệnh khi tổng đã dùng >= MAX_TOTAL_BUDGET
MAX_TOTAL_BUDGET=500

# USDC tối đa cho 1 lệnh (0 = không giới hạn)
# Kelly tự động điều chỉnh: ví Kelly≥0.15 → $50, Kelly<0.15 → $25
# MAX_PER_MARKET ghi đè kelly nếu nhỏ hơn
MAX_PER_MARKET=100

# Stop loss: tự đóng vị thế nếu lỗ >= N% kể từ lúc vào
# Ví dụ: STOP_LOSS_PCT=30 → lỗ 30% → bán hết
STOP_LOSS_PCT=30

# Không mở quá N vị thế cùng lúc (0 = không giới hạn)
MAX_OPEN_POSITIONS=10

# Không copy nếu giá > (1 - MIN_SPREAD) — tức là quá gần kết quả
# Ví dụ: MIN_SPREAD=0.05 → không copy nếu YES đang ở > 0.95 (gần chắc chắn = không còn upside)
MIN_SPREAD=0.05

# Tần suất poll Manual Wallets (giây)
SCAN_INTERVAL_SECONDS=30


## Manual Wallets
# ─────────────────────────────────────────────────────────────────────────────
# Cú pháp: ĐỊA_CHỈ_VÍ | BUDGET_USDC | CATEGORY_FILTER | GHI_CHÚ
#
# BUDGET_USDC:       USDC tối đa để copy ví này (vẫn bị giới hạn bởi MAX_PER_MARKET)
# CATEGORY_FILTER:   "all" hoặc "crypto", "geopolitics", "sports"
#                    → chỉ copy trade trong category này
# GHI_CHÚ:          Để bạn nhớ tại sao thêm ví này
#
# Specialists — Large bettors with focused edge (auto-added 2026-03-14 06:44)
# Budget: 200 USDC mỗi specialist (cao vì trade size lớn, có edge)
0xca72a747f0e4007d75e3067ffd12fc12000b7637 | 200 | geopolitics | SPECIALIST: avg $187k, Politics/Geopolitics
0x4a49ce5fe2d6faadbc0b279c4d2bd5f41665285e | 200 | geopolitics | SPECIALIST: avg $162k, Politics, WR 100%
0x94f199fb7789f1aef7fff6b758d6b375100f4c7a | 200 | sports | SPECIALIST: avg $103k, Sports (Arsenal)
0x019782cab5d844f02bafb71f512758be78579f3c | 200 | sports | SPECIALIST: avg $81k, Sports (Arsenal)
0x25e64cd559e8c46a888d8ebfa47d4490e810cc9f | 200 | geopolitics | SPECIALIST: avg $71k, Politics (Korea)
0xd1be0932c621cc31edb32eae5cc7e8394faccc57 | 200 | sports | SPECIALIST: avg $58k, Sports (Celta Vigo)
0x8453f6aa62cba5e5302f501849ffaf83dff2ecc3 | 200 | sports | SPECIALIST: avg $53k, Super Bowl
# ─────────────────────────────────────────────────────────────────────────────


## Blacklist
# ─────────────────────────────────────────────────────────────────────────────
# Ví trong đây bị bỏ qua hoàn toàn (cả AUTO và MANUAL)
# Cú pháp: ĐỊA_CHỈ | LÝ_DO
# ─────────────────────────────────────────────────────────────────────────────


## Active Wallets
# [Agent1 auto-update] 2026-03-27 09:30 UTC  (115 wallets)
0x31a53df5265bc4717ab01c7a7d4b97677d339d41 | 50 | all | score=0.83 kelly=0.891 wr=90.5%
0x31a53df5265bc4717ab01c7a7d4b97677d339d41 | 50 | all | score=0.83 kelly=0.891 wr=90.5%
0xa8caf30a6a9c6e670f5602827f4e435d1d4cd535 | 50 | all | score=0.80 kelly=0.647 wr=86.7%
0xa8caf30a6a9c6e670f5602827f4e435d1d4cd535 | 50 | all | score=0.80 kelly=0.647 wr=86.7%
0xbe907f61234b2044c2947cbb7abcdb3c2011f61c | 50 | all | score=0.78 kelly=1.000 wr=100.0%
0xbe907f61234b2044c2947cbb7abcdb3c2011f61c | 50 | all | score=0.78 kelly=1.000 wr=100.0%
0x6f3ebff1b1e46515c20782cc9b65581a7894ee32 | 50 | all | score=0.76 kelly=1.000 wr=100.0%
0x6f3ebff1b1e46515c20782cc9b65581a7894ee32 | 50 | all | score=0.76 kelly=1.000 wr=100.0%
0x4e1255034cb8827631bbcd0756c657962fdd7a56 | 50 | all | score=0.76 kelly=1.000 wr=100.0%
0x4e1255034cb8827631bbcd0756c657962fdd7a56 | 50 | all | score=0.76 kelly=1.000 wr=100.0%
0x56813812fc837eedb614d8c231787f83a865e113 | 50 | all | score=0.76 kelly=0.828 wr=88.9%
0x56813812fc837eedb614d8c231787f83a865e113 | 50 | all | score=0.76 kelly=0.828 wr=88.9%
0x9055d013ef95f32c17249b434381d08ee7ed8dad | 50 | all | score=0.76 kelly=1.000 wr=100.0%
0x9055d013ef95f32c17249b434381d08ee7ed8dad | 50 | all | score=0.76 kelly=1.000 wr=100.0%
0xdbe99f1ecf8a60a67638951fdaf024e5ef260382 | 50 | all | score=0.75 kelly=0.883 wr=94.4%
0xdbe99f1ecf8a60a67638951fdaf024e5ef260382 | 50 | all | score=0.75 kelly=0.883 wr=94.4%
0x796590ec48bca1d8fd773bf52a66bf82e21409d9 | 50 | all | score=0.73 kelly=1.000 wr=100.0%
0x796590ec48bca1d8fd773bf52a66bf82e21409d9 | 50 | all | score=0.73 kelly=1.000 wr=100.0%
0xe40362b6d2c1eb1134da886f4c64f02f08f6e5a4 | 50 | all | score=0.73 kelly=0.593 wr=82.5%
0xe40362b6d2c1eb1134da886f4c64f02f08f6e5a4 | 50 | all | score=0.73 kelly=0.593 wr=82.5%
0x0979bad57d7a1403db89cbcd9c52bf43f2138d9b | 50 | all | score=0.72 kelly=0.459 wr=76.5%
0x0979bad57d7a1403db89cbcd9c52bf43f2138d9b | 50 | all | score=0.72 kelly=0.459 wr=76.5%
0x0e9b9cb7ee710b57fbcbefdcb518a3a986a16e75 | 50 | all | score=0.72 kelly=0.727 wr=85.0%
0x0e9b9cb7ee710b57fbcbefdcb518a3a986a16e75 | 50 | all | score=0.72 kelly=0.727 wr=85.0%
0x2095416f8bfe2c12c72216efd932d15aaf84b87c | 50 | all | score=0.72 kelly=0.760 wr=92.3%
0x2095416f8bfe2c12c72216efd932d15aaf84b87c | 50 | all | score=0.72 kelly=0.760 wr=92.3%
0x3a135a81197b87dcb147e2091d61f39c3e977ea6 | 50 | all | score=0.72 kelly=0.466 wr=87.5%
0x3a135a81197b87dcb147e2091d61f39c3e977ea6 | 50 | all | score=0.72 kelly=0.466 wr=87.5%
0x26ff68e9216fc6e0696194f2cf9b19fe06c88ed7 | 50 | all | score=0.72 kelly=0.808 wr=89.4%
0x26ff68e9216fc6e0696194f2cf9b19fe06c88ed7 | 50 | all | score=0.72 kelly=0.808 wr=89.4%
0x744c072005bde6ddab8764a7477f61d3d22ae37f | 50 | all | score=0.71 kelly=0.588 wr=80.9%
0x744c072005bde6ddab8764a7477f61d3d22ae37f | 50 | all | score=0.71 kelly=0.588 wr=80.9%
0x1b1a53f7c37765d722a048b60841975690143852 | 50 | all | score=0.71 kelly=0.626 wr=85.3%
0x1b1a53f7c37765d722a048b60841975690143852 | 50 | all | score=0.71 kelly=0.626 wr=85.3%
0x736fb63d482a985fce51cde2533c1948c9ced6d6 | 50 | all | score=0.70 kelly=0.754 wr=92.9%
0x736fb63d482a985fce51cde2533c1948c9ced6d6 | 50 | all | score=0.70 kelly=0.754 wr=92.9%
0x425f23ef1da939300ec4b39da840af831ea64d26 | 50 | all | score=0.70 kelly=0.895 wr=92.9%
0x425f23ef1da939300ec4b39da840af831ea64d26 | 50 | all | score=0.70 kelly=0.895 wr=92.9%
0xe52c0a1327a12edc7bd54ea6f37ce00a4ca96924 | 50 | all | score=0.70 kelly=0.505 wr=80.1%
0xe52c0a1327a12edc7bd54ea6f37ce00a4ca96924 | 50 | all | score=0.70 kelly=0.505 wr=80.1%
0x4dfd481c16d9995b809780fd8a9808e8689f6e4a | 50 | all | score=0.69 kelly=0.602 wr=72.2%
0x4dfd481c16d9995b809780fd8a9808e8689f6e4a | 50 | all | score=0.69 kelly=0.602 wr=72.2%
0xe5c8026239919339b988fdb150a7ef4ea196d3e7 | 50 | all | score=0.69 kelly=0.531 wr=71.6%
0xe5c8026239919339b988fdb150a7ef4ea196d3e7 | 50 | all | score=0.69 kelly=0.531 wr=71.6%
0x8119010a6e589062aa03583bb3f39ca632d9f887 | 50 | all | score=0.68 kelly=0.800 wr=81.0%
0x8119010a6e589062aa03583bb3f39ca632d9f887 | 50 | all | score=0.68 kelly=0.800 wr=81.0%
0x5eb4bd8da1d5c67016ef0e9ff140c96ea977cac8 | 50 | all | score=0.68 kelly=0.634 wr=89.2%
0x5eb4bd8da1d5c67016ef0e9ff140c96ea977cac8 | 50 | all | score=0.68 kelly=0.634 wr=89.2%
0x21f7e463afb18b15df1cc94cd4a3bd27e7af8f97 | 50 | all | score=0.66 kelly=0.644 wr=80.3%
0x21f7e463afb18b15df1cc94cd4a3bd27e7af8f97 | 50 | all | score=0.66 kelly=0.644 wr=80.3%
0xd38ad20037839959d89165cf448568d584b28d26 | 50 | all | score=0.66 kelly=0.567 wr=75.6%
0xd38ad20037839959d89165cf448568d584b28d26 | 50 | all | score=0.66 kelly=0.567 wr=75.6%
0x4cbc2e1b8addfb1f9dd8897ef44fddedfc45a37b | 50 | all | score=0.65 kelly=0.872 wr=89.7%
0x4cbc2e1b8addfb1f9dd8897ef44fddedfc45a37b | 50 | all | score=0.65 kelly=0.872 wr=89.7%
0x7026b2c083d560fca195052493ad2704493b9ab1 | 50 | all | score=0.65 kelly=0.735 wr=85.2%
0x7026b2c083d560fca195052493ad2704493b9ab1 | 50 | all | score=0.65 kelly=0.735 wr=85.2%
0x8e5c0cc55cda93d6cae14becb3b738a44dcaa68a | 50 | all | score=0.64 kelly=0.607 wr=65.7%
0x8e5c0cc55cda93d6cae14becb3b738a44dcaa68a | 50 | all | score=0.64 kelly=0.607 wr=65.7%
0x647e8333632690e3e48dc3b40295589b417bdd9b | 50 | all | score=0.64 kelly=0.326 wr=80.8%
0x647e8333632690e3e48dc3b40295589b417bdd9b | 50 | all | score=0.64 kelly=0.326 wr=80.8%
0xa8948e141de09e8ed204681e4beb4d2473075324 | 50 | all | score=0.63 kelly=0.714 wr=77.8%
0xa8948e141de09e8ed204681e4beb4d2473075324 | 50 | all | score=0.63 kelly=0.714 wr=77.8%
0xbc43a2f0deb85ba4ad316300762972089c911540 | 50 | all | score=0.62 kelly=0.763 wr=77.1%
0xbc43a2f0deb85ba4ad316300762972089c911540 | 50 | all | score=0.62 kelly=0.763 wr=77.1%
0xd5440411345a5c4cf02199f1d346b1f598264d5e | 50 | all | score=0.61 kelly=0.584 wr=75.5%
0xd5440411345a5c4cf02199f1d346b1f598264d5e | 50 | all | score=0.61 kelly=0.584 wr=75.5%
0xab73ebff13a966453bd957b366a8a5b7c2893763 | 50 | all | score=0.61 kelly=0.790 wr=81.2%
0xab73ebff13a966453bd957b366a8a5b7c2893763 | 50 | all | score=0.61 kelly=0.790 wr=81.2%
0xcf0d7f69cf162918b33fc1ea7449583fa537132d | 50 | all | score=0.60 kelly=0.393 wr=68.3%
0xcf0d7f69cf162918b33fc1ea7449583fa537132d | 50 | all | score=0.60 kelly=0.393 wr=68.3%
0xac4a7b23c01c1bbb6a6030c74a825e9f96db7617 | 50 | all | score=0.59 kelly=0.273 wr=77.7%
0xac4a7b23c01c1bbb6a6030c74a825e9f96db7617 | 50 | all | score=0.59 kelly=0.273 wr=77.7%
0x79f293c48f651baa31c8086a228102f57b127620 | 50 | all | score=0.56 kelly=0.354 wr=64.0%
0x79f293c48f651baa31c8086a228102f57b127620 | 50 | all | score=0.56 kelly=0.354 wr=64.0%
0x7d0a0ad88ffdd1a598837dfc23d3f316749a09a6 | 50 | all | score=0.56 kelly=0.595 wr=78.5%
0x7d0a0ad88ffdd1a598837dfc23d3f316749a09a6 | 50 | all | score=0.56 kelly=0.595 wr=78.5%
0x9fba105a62b838769d4c389517cadb973f9056d0 | 50 | all | score=0.56 kelly=0.563 wr=81.2%
0x9fba105a62b838769d4c389517cadb973f9056d0 | 50 | all | score=0.56 kelly=0.563 wr=81.2%
0x05670a9813243e7a5af6ffa2aa013b4960fd2c55 | 50 | all | score=0.55 kelly=0.667 wr=69.2%
0x05670a9813243e7a5af6ffa2aa013b4960fd2c55 | 50 | all | score=0.55 kelly=0.667 wr=69.2%
0x49b306b0c083ebf5230dce5b151ecfaf63f06486 | 50 | all | score=0.53 kelly=0.550 wr=61.3%
0x49b306b0c083ebf5230dce5b151ecfaf63f06486 | 50 | all | score=0.53 kelly=0.550 wr=61.3%
0x8cc8560dfbd3b39a7aee6d1209876ebad9f1f1b3 | 50 | all | score=0.52 kelly=0.737 wr=75.0%
0x8cc8560dfbd3b39a7aee6d1209876ebad9f1f1b3 | 50 | all | score=0.52 kelly=0.737 wr=75.0%
0x63f9c3e16a29f46773ebcb1ab83a90c4d1154723 | 50 | all | score=0.52 kelly=0.582 wr=71.4%
0x63f9c3e16a29f46773ebcb1ab83a90c4d1154723 | 50 | all | score=0.52 kelly=0.582 wr=71.4%
0x019782cab5d844f02bafb71f512758be78579f3c | 50 | all | score=0.50 kelly=1.000 wr=100.0%
0x147fc85ff0e14b44257865a566efc3a2cffbb1d5 | 50 | all | score=0.50 kelly=0.664 wr=66.7%
0x147fc85ff0e14b44257865a566efc3a2cffbb1d5 | 50 | all | score=0.50 kelly=0.664 wr=66.7%
0x25e64cd559e8c46a888d8ebfa47d4490e810cc9f | 50 | all | score=0.50 kelly=0.500 wr=50.0%
0x4a49ce5fe2d6faadbc0b279c4d2bd5f41665285e | 50 | all | score=0.50 kelly=1.000 wr=100.0%
0x8453f6aa62cba5e5302f501849ffaf83dff2ecc3 | 50 | all | score=0.50 kelly=1.000 wr=100.0%
0x94f199fb7789f1aef7fff6b758d6b375100f4c7a | 50 | all | score=0.50 kelly=1.000 wr=100.0%
0xca72a747f0e4007d75e3067ffd12fc12000b7637 | 25 | all | score=0.50 kelly=0.000 wr=0.0%
0xd1be0932c621cc31edb32eae5cc7e8394faccc57 | 25 | all | score=0.50 kelly=0.000 wr=0.0%
0x0562c423912e325f83fa79df55085979e1f5594f | 50 | all | score=0.48 kelly=0.626 wr=63.2%
0x0562c423912e325f83fa79df55085979e1f5594f | 50 | all | score=0.48 kelly=0.626 wr=63.2%
0x06d00e6307b288427c8e32e146b602e1a58a254f | 50 | all | score=0.47 kelly=0.279 wr=67.4%
0x06d00e6307b288427c8e32e146b602e1a58a254f | 50 | all | score=0.47 kelly=0.279 wr=67.4%
0xbec7a683cb46ac0e04e9a26d703f893d4d036cfd | 50 | all | score=0.47 kelly=0.214 wr=69.9%
0xbec7a683cb46ac0e04e9a26d703f893d4d036cfd | 50 | all | score=0.47 kelly=0.214 wr=69.9%
0xebf8698b6b61025c8a230c75a2a692a1537992b8 | 50 | all | score=0.45 kelly=0.239 wr=60.0%
0xebf8698b6b61025c8a230c75a2a692a1537992b8 | 50 | all | score=0.45 kelly=0.239 wr=60.0%
0xb58e6facae9b43c650c22d9821daa04b28f1d570 | 25 | all | score=0.39 kelly=0.111 wr=66.7%
0xb58e6facae9b43c650c22d9821daa04b28f1d570 | 25 | all | score=0.39 kelly=0.111 wr=66.7%
0x141ef9052a46984e9d403100dc9c611d48388c87 | 50 | all | score=0.39 kelly=0.166 wr=69.1%
0x141ef9052a46984e9d403100dc9c611d48388c87 | 50 | all | score=0.39 kelly=0.166 wr=69.1%
0x6c9264336622411ea73283e7624bb2a6e00b1322 | 50 | all | score=0.29 kelly=0.151 wr=60.6%
0x6c9264336622411ea73283e7624bb2a6e00b1322 | 50 | all | score=0.29 kelly=0.151 wr=60.6%
0x6f3e3e93f770813110288c348d157041530f13dc | 25 | all | score=0.27 kelly=0.059 wr=70.0%
0x6f3e3e93f770813110288c348d157041530f13dc | 25 | all | score=0.27 kelly=0.059 wr=70.0%
0x12afddef5bc473db74aa37b63a1119f34572ff78 | 25 | all | score=0.27 kelly=0.079 wr=64.7%
0x12afddef5bc473db74aa37b63a1119f34572ff78 | 25 | all | score=0.27 kelly=0.079 wr=64.7%
0x4cc9c10d6b69273b32a9f7f1d3f092b5f61e7a80 | 25 | all | score=0.25 kelly=0.109 wr=60.0%
0x4cc9c10d6b69273b32a9f7f1d3f092b5f61e7a80 | 25 | all | score=0.25 kelly=0.109 wr=60.0%