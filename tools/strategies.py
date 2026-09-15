# -*- coding: utf-8 -*-
"""第 1.5 步：策略訊號（守則 §9.2，2026-09-15 新增）

★★★ 由來：使用者 2026-09-15 列出八項主要策略，要求「檢查有沒有使用，沒有要加入，
  有效判斷建議與分數」。稽核結果是——<b>三項完全沒有、一項結構上不適用、四項有資料但沒進評分</b>。
  本檔把其中七項變成<b>可機械計算、可逐項覆核的訊號</b>，寫進 indicators.json 的 stocks[code]["strat"]，
  再由 lib.strat_adj() 換成有上限的分數，並由 zones.py 取用其中的價位當觸發條件。

★ 八項的處理方式（⚠ 誠實標示，沒做的就說沒做）：
  ①VWAP ──────────── ✅ 新增：vwap20／vwap60／錨定 VWAP（自 52 週低點起算）
  ②區間突破 ──────── ✅ 新增：Donchian 前 20／60 日高低、區間位置、帶量確認
  ③短線剝頭皮 ────── ❌ <b>不適用，且不打算假裝做得到</b>
                      ——剝頭皮是<b>日內多次進出</b>的作法，本專案是「日線收盤報告＋一頁即時」，
                      <b>沒有分鐘級資料、沒有逐筆成交、沒有手續費與滑價模型</b>，
                      硬做出來的訊號會是誤導。⚠ <b>最接近的替代是即時頁的「現價 vs 當日區間位置」</b>，
                      已存在，但那是<b>觀察</b>不是策略。
  ④乖離率與均值回歸 ─ ⚠ 原本只有 bias20／bias60 的數字、寫在敘述裡<b>但沒有進任何評分規則</b>；
                      ✅ 本檔改為<b>用個股自身 120 日的乖離分布標準化（z 分數）</b>再判過熱／過冷。
  ⑤VWAP 防守與突破 ─ ✅ 新增：以「今日 vs 昨日相對 vwap20 的位置」判 突破／防守／失守／壓制
  ⑥支撐壓力拉回確認 ─ ⚠ 原本 zones.py 只<b>列出</b>支撐壓力，沒有「拉回確認」的判定；
                      ✅ 本檔給出機械定義（見 _pullback）
  ⑦缺口交易與回補 ── ✅ 新增：掃近 60 日跳空、判是否回補、列出<b>未回補缺口</b>當壓力／支撐
  ⑧趨勢跟隨與移動停利 ✅ 新增：ATR(14)、均線排列、<b>吊燈式移動停利（22 日最高 − 3×ATR）</b>
                      ——原本只有 2603 那次<b>個案式</b>的移動停利，沒有系統化規則。

⚠ 全部由本檔計算，<b>手填無效</b>（與 §9.1 的 tech_adj 同一原則）。
"""
import io
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "data", "raw")
IND_P = os.path.join(BASE, "data", "indicators.json")

# ── 參數（集中在這裡，改動要同步守則 §9.2）─────────────────────────
VWAP_N = 20          # 主要 VWAP 期間
VWAP_N2 = 60
DC_N = 20            # 區間突破：Donchian 前 N 日
DC_N2 = 60
ATR_N = 14
CHAND_N = 22         # 吊燈停利回看期
CHAND_K = 3.0        # 吊燈停利的 ATR 倍數
MR_LOOKBACK = 120    # 均值回歸：乖離 z 分數的樣本期
MR_Z = 2.0           # 過熱／過冷門檻（±2σ）
VOL_CONFIRM = 1.5    # 「帶量」門檻：20 日量比 ≥ 1.5
GAP_SCAN = 60        # 缺口掃描期
PULLBACK_N = 5       # 拉回確認：回看幾日內曾觸及支撐
TOUCH_TOL = 0.01     # 觸及容差 1%


def _load(sym):
    p = os.path.join(RAW, "%s.json" % sym)
    j = json.load(io.open(p, encoding="utf-8"))
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    rows = []
    for i in range(len(r["timestamp"])):
        o, h, l, c, v = (q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i])
        if None in (o, h, l, c):
            continue
        rows.append({"o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return rows


def _vwap(rows, n):
    """成交量加權平均價：Σ(典型價×量)/Σ量，典型價 =（高＋低＋收）/3。"""
    seg = rows[-n:]
    tv = sum(((x["h"] + x["l"] + x["c"]) / 3.0) * x["v"] for x in seg)
    vv = sum(x["v"] for x in seg)
    return (tv / vv) if vv else None


def _anchored_vwap(rows, anchor_i):
    seg = rows[anchor_i:]
    tv = sum(((x["h"] + x["l"] + x["c"]) / 3.0) * x["v"] for x in seg)
    vv = sum(x["v"] for x in seg)
    return (tv / vv) if vv else None


def _atr(rows, n=ATR_N):
    """Wilder ATR。"""
    if len(rows) < n + 1:
        return None
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["h"], rows[i]["l"], rows[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:n]) / n
    for t in trs[n:]:
        atr = (atr * (n - 1) + t) / n
    return atr


def _gaps(rows, scan=GAP_SCAN):
    """跳空與回補：向上跳空＝今日最低 > 昨日最高；向下跳空＝今日最高 < 昨日最低。
    回補＝之後任一日的價格區間回到缺口之內。"""
    out = []
    start = max(1, len(rows) - scan)
    for i in range(start, len(rows)):
        pv, cu = rows[i - 1], rows[i]
        up = cu["l"] > pv["h"]
        dn = cu["h"] < pv["l"]
        if not (up or dn):
            continue
        lo, hi = (pv["h"], cu["l"]) if up else (cu["h"], pv["l"])
        filled = any(rows[j]["l"] <= lo for j in range(i + 1, len(rows))) if up else \
                 any(rows[j]["h"] >= hi for j in range(i + 1, len(rows)))
        out.append({"i_from_end": len(rows) - 1 - i, "dir": "up" if up else "down",
                    "lo": round(lo, 2), "hi": round(hi, 2),
                    "size_pct": round((hi - lo) / pv["c"] * 100, 2), "filled": bool(filled)})
    return out


def _pullback(a, rows, levels):
    """⑥支撐壓力位拉回確認——機械定義。
       ⚠ 支撐＝<b>目前在收盤價之下</b>的位置（2026-09-15 修：第一版誤把布林上軌等壓力也納入）。
       「拉回確認」三條件都要成立：
         ①近 PULLBACK_N 日的最低價曾觸及某一支撐（低點 ≤ 支撐 ×(1+TOUCH_TOL)）；
         ②今日收盤仍在該支撐之上；③<b>今日收漲</b>（收 > 昨收）。
       只差③＝「拉回未確認」；今日收盤跌破近日還在腳下的支撐＝「支撐失守」。
       ★ 另記 body_warn：收漲但實體收黑（收 < 開）＝帶上影線，確認的品質較差。"""
    close, opn, prev_c = a["close"], a["open"], a["prev_close"]
    seg = rows[-PULLBACK_N:]
    lowest = min(x["l"] for x in seg)
    sup = [(nm, lv) for nm, lv in levels if lv is not None and lv <= close]
    best = None
    for nm, lv in sorted(sup, key=lambda x: -x[1]):      # 由近到遠
        if lowest <= lv * (1 + TOUCH_TOL):
            best = (nm, lv)
            break
    if best:
        nm, lv = best
        up = close > prev_c
        warn = (close < opn)
        return {"state": "拉回確認" if up else "拉回未確認", "level": nm, "px": round(lv, 2),
                "body_warn": bool(up and warn),
                "why": "近 %d 日最低 %.2f 觸及%s %.2f，收盤 %.2f 守住、當日%s%s"
                       % (PULLBACK_N, lowest, nm, lv, close, "收漲" if up else "收跌",
                          "（惟實體收黑，帶上影線）" if (up and warn) else "")}
    start_c = rows[-PULLBACK_N]["c"]
    broke = [(nm, lv) for nm, lv in levels if lv is not None and close < lv <= start_c]
    if broke:
        nm, lv = min(broke, key=lambda x: x[1])
        return {"state": "支撐失守", "level": nm, "px": round(lv, 2), "body_warn": False,
                "why": "%s %.2f 在近 %d 日內還在腳下，今日收盤 %.2f 已跌破"
                       % (nm, lv, PULLBACK_N, close)}
    return {"state": "無", "level": None, "px": None, "body_warn": False,
            "why": "近 %d 日未觸及任何支撐，收盤也未跌破近日支撐" % PULLBACK_N}


def compute(code, a, rows):
    """回傳一檔的策略訊號 dict。a = indicators.json 裡該檔的 dict。"""
    close = a["close"]
    has_vol = sum(x["v"] for x in rows[-VWAP_N:]) > 0
    s = {"has_volume": has_vol}

    # ①⑤ VWAP 與其防守／突破 ------------------------------------------------
    if has_vol:
        v20 = _vwap(rows, VWAP_N)
        v60 = _vwap(rows, VWAP_N2)
        # 錨定 VWAP：自 52 週低點那一天起算
        seg52 = rows[-240:] if len(rows) >= 240 else rows
        li = len(rows) - len(seg52) + min(range(len(seg52)), key=lambda i: seg52[i]["l"])
        va = _anchored_vwap(rows, li)
        prev_c = rows[-2]["c"]
        prev_v20 = _vwap(rows[:-1], VWAP_N)
        now_above = close > v20
        was_above = prev_c > prev_v20 if prev_v20 else now_above
        state = ("站上後防守" if (now_above and was_above) else
                 "當日突破" if (now_above and not was_above) else
                 "當日失守" if (not now_above and was_above) else "持續受壓")
        s["vwap"] = {"v20": round(v20, 2), "v60": round(v60, 2), "anchored": round(va, 2),
                     "anchor_bars": len(rows) - li,
                     "dev20_pct": round((close / v20 - 1) * 100, 2),
                     "dev_anchor_pct": round((close / va - 1) * 100, 2),
                     "state": state}
    else:
        s["vwap"] = {"state": "無量資料", "why": "Yahoo 的 ^TWII 不提供成交量，指數不計 VWAP"}

    # ② 區間突破（Donchian，用「前 N 日」不含今日）---------------------------
    def dc(n):
        seg = rows[-(n + 1):-1]
        return max(x["h"] for x in seg), min(x["l"] for x in seg)
    hi20, lo20 = dc(DC_N)
    hi60, lo60 = dc(DC_N2)
    vr = a.get("vr20") or 0
    if close > hi20:
        br = "帶量突破 %d 日高" % DC_N if vr >= VOL_CONFIRM else "突破 %d 日高（量未確認）" % DC_N
    elif close < lo20:
        br = "帶量跌破 %d 日低" % DC_N if vr >= VOL_CONFIRM else "跌破 %d 日低（量未確認）" % DC_N
    else:
        br = "區間內"
    s["range"] = {"hi20": round(hi20, 2), "lo20": round(lo20, 2),
                  "hi60": round(hi60, 2), "lo60": round(lo60, 2),
                  "pos20_pct": round((close - lo20) / (hi20 - lo20) * 100, 1) if hi20 > lo20 else None,
                  "vr20": round(vr, 2), "state": br}

    # ④ 乖離率與均值回歸（用自身 120 日乖離分布標準化）-----------------------
    ma20s = []
    for i in range(len(rows) - MR_LOOKBACK, len(rows)):
        if i < 20:
            continue
        m = sum(x["c"] for x in rows[i - 19:i + 1]) / 20.0
        ma20s.append((rows[i]["c"] / m - 1) * 100)
    if len(ma20s) >= 30:
        mu = sum(ma20s) / len(ma20s)
        sd = (sum((x - mu) ** 2 for x in ma20s) / len(ma20s)) ** 0.5
        z = (a["bias20"] - mu) / sd if sd else 0.0
        st = "過熱（回歸壓力）" if z >= MR_Z else "過冷（回歸支撐）" if z <= -MR_Z else "常態"
        s["meanrev"] = {"bias20": round(a["bias20"], 2), "mu": round(mu, 2), "sd": round(sd, 2),
                        "z": round(z, 2), "state": st}
    else:
        s["meanrev"] = {"state": "樣本不足"}

    # ⑥ 支撐壓力位拉回確認 ---------------------------------------------------
    levels = [("5 日線", a["ma"].get("5")), ("10 日線", a["ma"].get("10")),
              ("月線", a["ma"].get("20")), ("季線", a["ma"].get("60")),
              ("半年線", a["ma"].get("120")), ("年線", a["ma"].get("240")),
              ("布林下軌", a.get("bb_dn")), ("布林上軌", a.get("bb_up")),
              ("%d 日區間低" % DC_N, lo20), ("%d 日區間高" % DC_N, hi20)]
    s["pullback"] = _pullback(a, rows, levels)
    above = [(nm, lv) for nm, lv in levels if lv is not None and lv < close]
    below = [(nm, lv) for nm, lv in levels if lv is not None and lv > close]
    s["nearest_sup"] = (lambda t: {"name": t[0], "px": round(t[1], 2),
                                   "dist_pct": round((close / t[1] - 1) * 100, 2)})(max(above, key=lambda x: x[1])) if above else None
    s["nearest_res"] = (lambda t: {"name": t[0], "px": round(t[1], 2),
                                   "dist_pct": round((t[1] / close - 1) * 100, 2)})(min(below, key=lambda x: x[1])) if below else None

    # ⑦ 缺口 -----------------------------------------------------------------
    gs = _gaps(rows)
    s["gaps"] = {"all": gs, "unfilled": [g for g in gs if not g["filled"]],
                 "today": next((g for g in gs if g["i_from_end"] == 0), None)}

    # ⑧ 趨勢跟隨與移動停利 ---------------------------------------------------
    atr = _atr(rows)
    hh = max(x["h"] for x in rows[-CHAND_N:])
    chand = hh - CHAND_K * atr if atr else None
    m = a["ma"]
    bull = m["5"] > m["10"] > m["20"] > m["60"]
    bear = m["5"] < m["10"] < m["20"] < m["60"]
    s["trend"] = {"atr14": round(atr, 2) if atr else None,
                  "atr_pct": round(atr / close * 100, 2) if atr else None,
                  "hh%d" % CHAND_N: round(hh, 2),
                  "chandelier": round(chand, 2) if chand else None,
                  "chand_gap_pct": round((close / chand - 1) * 100, 2) if chand else None,
                  "align": "多頭排列" if bull else "空頭排列" if bear else "均線糾結",
                  "above_chand": bool(chand and close > chand)}

    # ③ 短線剝頭皮 —— 據實標示為不適用 ---------------------------------------
    s["scalp"] = {"state": "不適用",
                  "why": "剝頭皮需要分鐘級／逐筆資料與手續費滑價模型，本專案是日線收盤報告，"
                         "硬做會是誤導；最接近的替代（現價在當日區間的位置）已在即時頁，但那是觀察不是策略。"}
    return s


def main():
    import config as C
    ind = json.load(io.open(IND_P, encoding="utf-8"))
    for code, name, sym, _mk, _ind in C.STOCKS:
        a = ind["stocks"][code]
        ind["stocks"][code]["strat"] = compute(code, a, _load(sym))
    ind["idx"]["strat"] = compute("IDX", ind["idx"], _load("IDX_TWII"))
    json.dump(ind, io.open(IND_P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("=" * 96)
    print("策略訊號（守則 §9.2）　基準日 %s" % ind["idx"]["date"])
    print("=" * 96)
    for code, name, _s, _m, _i in C.STOCKS:
        s = ind["stocks"][code]["strat"]
        a = ind["stocks"][code]
        print("\n%s %s　收 %.2f" % (code, name, a["close"]))
        v = s["vwap"]
        print("  ①⑤ VWAP      v20 %.2f（乖離 %+.2f%%）｜錨定 %.2f（%d 根前的 52 週低起算，%+.2f%%）｜<%s>"
              % (v["v20"], v["dev20_pct"], v["anchored"], v["anchor_bars"], v["dev_anchor_pct"], v["state"]))
        r = s["range"]
        print("  ②  區間突破   前 %d 日 %.2f~%.2f（位置 %s%%）｜量比 %.2f｜<%s>"
              % (DC_N, r["lo20"], r["hi20"], r["pos20_pct"], r["vr20"], r["state"]))
        mr = s["meanrev"]
        print("  ④  均值回歸   乖離 %+.2f%%（120 日 μ %+.2f／σ %.2f）→ z %+.2f｜<%s>"
              % (mr["bias20"], mr["mu"], mr["sd"], mr["z"], mr["state"]))
        pb = s["pullback"]
        print("  ⑥  拉回確認   <%s>　%s" % (pb["state"], pb["why"]))
        su, re_ = s["nearest_sup"], s["nearest_res"]
        print("      最近支撐 %s %.2f（%+.2f%%）｜最近壓力 %s %.2f（%+.2f%%）"
              % (su["name"], su["px"], su["dist_pct"], re_["name"], re_["px"], re_["dist_pct"]))
        g = s["gaps"]
        uf = g["unfilled"]
        print("  ⑦  缺口       近 %d 日 %d 個｜未回補 %d 個%s"
              % (GAP_SCAN, len(g["all"]), len(uf),
                 "：" + "、".join("%s %.2f~%.2f（%d 根前）"
                                 % ("向上" if x["dir"] == "up" else "向下", x["lo"], x["hi"], x["i_from_end"])
                                 for x in uf) if uf else ""))
        t = s["trend"]
        print("  ⑧  趨勢／停利 ATR14 %.2f（%.2f%%）｜%s｜吊燈停利 %.2f（距現價 %+.2f%%）｜%s"
              % (t["atr14"], t["atr_pct"], t["align"], t["chandelier"], t["chand_gap_pct"],
                 "站上" if t["above_chand"] else "★ 已跌破"))
    print("\n  ③  短線剝頭皮 <不適用> —— %s" % ind["stocks"][C.CODES[0]]["strat"]["scalp"]["why"])


if __name__ == "__main__":
    import sys
    sys.path.insert(0, BASE)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
