# -*- coding: utf-8 -*-
"""★ 實際持倉（守則第 20 節）—— 即時頁與每日報告的「操作建議」都讀這一份

這是**唯一**要手動維護的持倉資料。買賣之後回來改這裡，兩份產出會同步。

欄位
  shares    持有股數（不是張數；1 張 = 1000 股，零股照填）
  cost      每股平均成本（元）——直接填券商 App 顯示的數字
  div_ps    ★ 持有期間內「每股已領到的股利」（元）。券商顯示的成本通常**不還原除權息**，
            填了這欄，報告會另外算一組「還原股利後的實質報酬」。沒領過或不確定就填 0。
  plan_lots ★ 你自己決定的「這一檔最多放到幾張」。
            **填了才會產生加碼張數建議**（規則：加碼區間內 → 可加 min(ADD_BATCH, plan_lots − 現有張數)）。
            留 None 表示未設上限 —— 頁面只會告訴你「現價已進入買進區間」，不替你決定加幾張。
            部位大小是資金配置決定，程式不猜。

⚠ 減碼／出場張數是**純算術**：拿 zones.py 已經訂好的區間規則（「先減 1/3」「全數出場」）
  套到實際張數上，不含任何新的主觀判斷。規則表見守則第 20.2 節。
"""

# 資料來源與時點（顯示在頁面上，讓人一眼知道這份持倉是什麼時候的）
AS_OF = "2026-08-13"
SOURCE = "券商 App 持股頁（每股平均成本，未還原除權息）"

POS = {
 # 代號        股數    每股成本   已領股利/股   計畫上限張數
 "1504": dict(shares=2000, cost=84.62,  div_ps=0.0, plan_lots=None),
 "2618": dict(shares=5000, cost=35.35,  div_ps=0.0, plan_lots=None),
 "1514": dict(shares=1000, cost=126.68, div_ps=0.0, plan_lots=None),
 "2603": dict(shares=1000, cost=193.28, div_ps=0.0, plan_lots=None),
}

# 每次加碼的批量（張）。只在 plan_lots 有填時才會用到。
ADD_BATCH = 1

# 分批減碼的比例（守則第 10 節的操作條件寫的是「先減 1/3」，這裡與之對齊）
TRIM_FRAC = 1.0 / 3.0

# ⚠ 除權息與成本的關係（填 div_ps 前先讀）：
#   4 檔 2026 年都已除權息（config.TIME_PRESSURE 有日期）——
#     1504 06/19 現金 2 元｜2618 07/08 現金 2 元｜1514 07/30 現金 2 元＋股票 0.2 元｜2603 06/17 現金 16 元
#   ★ 只有「除權息基準日之前就持有」才算領到。除息後才買進的部位 div_ps 要填 0，
#     填錯會把報酬率灌水。不確定就維持 0（寧可低估）。
#   ★ 1514 還有 0.2 元股票股利，配股會讓股數變多、每股成本下降，
#     券商 App 通常在新股上市後自動調整 —— 以 App 顯示的為準，不要自己再減一次。


if __name__ == "__main__":
    import sys
    try:                               # Windows 主控台預設 cp950，印不出 ⚠ 等字元
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    tot_c = tot_s = 0.0
    print("=" * 72)
    print("持倉一覽（%s，%s）" % (AS_OF, SOURCE))
    print("=" * 72)
    for c, p in POS.items():
        lots = p["shares"] / 1000.0
        cv = p["shares"] * p["cost"]
        tot_c += cv
        tot_s += p["shares"]
        print("%s  %6.2f 張  成本 %8.2f  投入 %10s  上限 %s"
              % (c, lots, p["cost"], "{:,.0f}".format(cv),
                 ("%s 張" % p["plan_lots"]) if p["plan_lots"] else "未設（不產生加碼張數）"))
    print("-" * 72)
    print("合計投入成本 %s 元　共 %.0f 股" % ("{:,.0f}".format(tot_c), tot_s))
    miss = [c for c, p in POS.items() if not p.get("shares") or not p.get("cost")]
    print("⚠ 股數或成本未填：", miss if miss else "無，全部齊全")
