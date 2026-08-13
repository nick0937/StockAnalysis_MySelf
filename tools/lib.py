# -*- coding: utf-8 -*-
"""共用工具：數字格式化、漲跌配色、sparkline、表格包裝、分數標籤
   ★ 移植時不用改這個檔案。"""
import math
import config as C


# ── 數字格式化 ──────────────────────────────────────────────────
def n(v, d=2):
    """一般數值：>=1000 加千分位，None → 查無"""
    if v is None:
        return "查無"
    return "{:,.{}f}".format(v, d) if abs(v) >= 1000 else "{:.{}f}".format(v, d)


def cm(v, d=0):
    """一律加千分位"""
    return "查無" if v is None else "{:,.{}f}".format(v, d)


def sgn(v, d=2, pct=False):
    """帶正負號，pct=True 補上 %"""
    if v is None:
        return "查無"
    return ("%+." + str(d) + "f") % v + ("%" if pct else "")


def cls(v):
    """漲跌配色 class：紅漲、綠跌、平"""
    if v is None:
        return ""
    return "up" if v > 0 else ("dn" if v < 0 else "flat")


def num_td(v, colored=False, d=None):
    """表格數字格，'--' 與 None 原樣顯示不上色"""
    if v in (None, "--", ""):
        return '<td class="num">--</td>'
    txt = v if d is None else n(float(v), d)
    if colored:
        return '<td class="num %s">%s</td>' % (cls(float(str(v).rstrip("%"))), txt)
    return '<td class="num">%s</td>' % txt


# ── 分數 ────────────────────────────────────────────────────────
def band_of(sc):
    for lo, name in C.BANDS:
        if sc >= lo:
            return name
    return C.BANDS[-1][1]


def scls(sc):
    """分數條 class"""
    return "s70" if sc >= 70 else ("s55" if sc >= 55 else ("s45" if sc >= 45 else "s00"))


def half_up(x):
    """★ 一律用 floor(x+0.5) 半進位，不要用 Python 內建 round 的銀行家捨入"""
    return int(math.floor(x + 0.5))


def total_score(five):
    """five = (籌碼, 技術, 基本, 大盤, 消息)"""
    return half_up(sum(v * w for v, (_, _, w) in zip(five, C.WEIGHTS)))


def market_score(env_score, rs):
    """大盤面分 = 大盤環境分 × 50% + RS 分 × 50%（不主觀給分）"""
    return half_up(env_score * .5 + rs * .5)


def rs_score(ex5, ex20, ex60):
    """RS 分 = 50 + clamp(ex5×1.0 + ex20×1.2 + ex60×0.6, -35, +35)，再 clamp 15~85"""
    raw = ex5 * 1.0 + ex20 * 1.2 + ex60 * 0.6
    return max(15.0, min(85.0, 50 + max(-35.0, min(35.0, raw))))


# ── HTML 片段 ───────────────────────────────────────────────────
def spark(seq):
    """seq = [{'d':..,'c':..}, ...]，viewBox 0 0 100 100，y 反轉（最高價在頂）"""
    cs = [x["c"] for x in seq]
    lo, hi = min(cs), max(cs)
    rng = (hi - lo) or 1.0
    pts = " ".join("%.2f,%.2f" % (100.0 * i / (len(cs) - 1), (hi - c) / rng * 100)
                   for i, c in enumerate(cs))
    col = "var(--up)" if cs[-1] >= cs[0] else "var(--dn)"
    return ('<svg class="spk" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">'
            '<polyline points="%s" fill="none" stroke="%s" stroke-width="1.6" '
            'vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"/></svg>'
            % (pts, col))


def mc(label, val, k=""):
    """指標格一格"""
    return ('<div class="mc %s"><span class="mcl">%s</span>'
            '<span class="mcv">%s</span></div>' % (k, label, val))


def twrap(inner, extra=""):
    """★ 所有資料表格都必須包在 .twrap 內（可橫向捲動、第一欄 sticky）
       欄位少的表格加 extra='tnarrow'（3 欄再加 'tn3'）避免撐滿整個寬度"""
    return ('<div class="thint">← 可左右滑動 →</div><div class="twrap %s">%s</div>'
            % (extra, inner))


MA_LABEL = [(5, "5日"), (10, "10日"), (20, "月線"),
            (60, "季線"), (120, "半年線"), (240, "年線")]


def mabar(a):
    """六條均線位置條。a 需有 close 與 ma{'5':..,'10':..,...}"""
    ma = a["ma"]
    ups = [k for k, _ in MA_LABEL if ma.get(str(k)) and a["close"] > ma[str(k)]]
    h = ('<div class="mabh">均線位置：站上 <b>%d/%d</b> 條</div><div class="mabs">'
         % (len(ups), len(MA_LABEL)))
    for k, lab in MA_LABEL:
        v = ma.get(str(k))
        if v is None:
            h += '<span class="mab no">%s 查無</span>' % lab
        else:
            h += ('<span class="mab %s">%s %s %s</span>'
                  % ("ok" if a["close"] > v else "no", lab,
                     "✓" if a["close"] > v else "✗", n(v)))
    return h + "</div>"


def chip(cls_, sym, label, big=False):
    return ('<span class="chip %s%s"><i>%s</i>%s</span>'
            % (cls_, " big" if big else "", sym, label))


# ══════════════════════════════════════════════════════════════════
# 實際持倉的操作建議（守則第 20 節）
# ★ 純算術：把 zones.py 已訂好的區間規則套到 inputs/positions.py 的實際張數上。
#   這裡不做任何新的主觀判斷，也不改雙情境標籤。
# ══════════════════════════════════════════════════════════════════
LOT = 1000          # 1 張 = 1000 股


def pl(shares, cost, px, div_ps=0.0):
    """未實現損益。回傳 dict：投入成本／現值／損益金額／報酬率／還原股利後報酬率"""
    if not shares or not cost or px is None:
        return None
    cv, mv = shares * cost, shares * px
    d = {"lots": shares / float(LOT), "cost": cost, "px": px,
         "cost_val": cv, "mkt_val": mv, "pl": mv - cv, "pl_pct": (px / cost - 1) * 100,
         "breakeven": cost}
    if div_ps:
        d["pl_adj"] = (mv - cv) + shares * div_ps
        d["pl_adj_pct"] = ((px + div_ps) / cost - 1) * 100
        d["breakeven"] = cost - div_ps
    return d


def zone_state(px, lv):
    """現價落在 LIVE 區間的哪一段。優先序：出場價 > 停利/減碼 > 買進 > 續抱

    below_stop 跌破出場價｜above_sell 高於停利上緣｜in_sell 停利/減碼區間內
    in_buy 買進區間內｜below_buy 跌破買進區間下緣｜hold 其餘（區間之間）
    """
    if px is None:
        return None
    if lv.get("stop") and px < lv["stop"]:
        return "below_stop"
    if lv.get("sell_hi") and px > lv["sell_hi"]:
        return "above_sell"
    if lv.get("sell_lo") and px >= lv["sell_lo"]:
        return "in_sell"
    if lv.get("buy_lo") and lv.get("buy_hi"):
        if px < lv["buy_lo"]:
            return "below_buy"
        if px <= lv["buy_hi"]:
            return "in_buy"
    return "hold"


def trim_lots(total_lots, frac=1.0 / 3.0):
    """分批減碼張數＝半進位(總張數 × frac)，至少 1 張、至多全部"""
    return max(1, min(int(total_lots), half_up(total_lots * frac)))


def position_plan(px, lv, p, vr=None, add_batch=1, trim_frac=1.0 / 3.0):
    """★ 守則第 20.2 節的規則表。回傳 dict 或 None（無持倉）

    act:  exit 出清｜trim 減碼｜trail 改移動停利｜add 加碼｜keep 續抱
    lots: 這次該動的張數（keep/trail 為 0）
    realized: 若真的動了這些張數，會實現多少損益（元）
    """
    if not p or not p.get("shares"):
        return None
    n_lots = p["shares"] / float(LOT)
    cost, div_ps = p["cost"], p.get("div_ps") or 0.0
    be = cost - div_ps                       # 解套價（還原已領股利）
    st = zone_state(px, lv)
    up = px is not None and px >= be         # 這一筆是賺是賠
    plan = p.get("plan_lots")
    r = {"state": st, "lots": 0.0, "n_lots": n_lots, "breakeven": be,
         "in_profit": up, "act": "keep", "warn": None}

    if st == "below_stop":
        r["act"], r["lots"] = "exit", n_lots
        r["title"] = "觸發出場" if up else "觸發停損"
    elif st == "above_sell" and vr is not None and vr >= 1.5:
        r["act"], r["title"] = "trail", "改移動停利"
    elif st in ("above_sell", "in_sell"):
        r["act"], r["lots"] = "trim", trim_lots(n_lots, trim_frac)
        r["title"] = "分批停利" if up else "分批減碼（認賠）"
    elif st == "in_buy":
        if plan and plan > n_lots:
            r["act"], r["lots"] = "add", min(add_batch, plan - n_lots)
            r["title"] = "可加碼"
        else:
            r["title"] = "進入買進區間（未設計畫上限，不產生加碼張數）"
    else:
        r["title"] = "續抱"

    if px is not None:
        r["realized"] = (px - cost) * r["lots"] * LOT if r["act"] in ("exit", "trim") else 0.0
        r["add_cost"] = px * r["lots"] * LOT if r["act"] == "add" else 0.0

    # 機械檢查：區間與成本／出場價的位置關係（純數字比較，不是判斷）
    if lv.get("sell_hi") and be > lv["sell_hi"]:
        r["warn"] = ("解套價 %.2f 元高於%s上緣 %.2f 元 —— <b>這一檔的減碼區間全數低於成本，"
                     "任何在區間內的動作都是認賠，不是停利</b>" % (be, lv.get("_lab", "停利區間"), lv["sell_hi"]))
    elif lv.get("buy_lo") and lv.get("stop") and lv["buy_lo"] < lv["stop"] <= (lv.get("buy_hi") or 0):
        r["warn"] = ("買進區間下緣 %.2f 元<b>低於</b>出場價 %.2f 元 —— 區間內的加碼與持有的出場條件"
                     "互相矛盾，加碼前先確認站穩 %.2f 元" % (lv["buy_lo"], lv["stop"], lv["stop"]))
    return r


def opbox(zone_lab, zone, anchor, cond_lab, cond):
    """★ 操作條件盒：價位區間 + 錨點來源 + 觸發條件（守則第 10 節）"""
    return ('<div class="opbox"><span class="aol">%s</span>'
            '<span class="aoz">%s<small>%s</small></span>'
            '<span class="aol">%s</span><span class="aoc">%s</span></div>'
            % (zone_lab, zone, anchor, cond_lab, cond))
