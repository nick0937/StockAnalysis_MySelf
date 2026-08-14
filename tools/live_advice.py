# -*- coding: utf-8 -*-
"""盤中即時操作建議（守則第 19 節）—— 可隨時重跑，每次覆蓋 REPO/live/index.html

做什麼：抓即時報價（證交所 MIS）→ 對照最近一期報告訂下的操作區間（inputs/zones.py 的 LIVE）
        → 直接給「空手該不該買、持有該不該賣」，只講操作，不重複收盤報告的細節。
        ★ 並依 inputs/positions.py 的實際持倉，算出「你這次該動幾張」（守則第 20 節）。

不做什麼：不重算五面向評分、不抓籌碼與財報。盤中資料不足以改變評分，
          真正的評分一律以收盤後的正式報告為準。

用法：python live_advice.py          （盤中隨時可跑，會覆蓋 live/index.html）
"""
import json, os, sys, time, urllib.request, datetime

try:                                   # Windows 主控台預設 cp950，印不出 ⚡✅ 等字元
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "inputs"))
import config as C
from zones import ZONE, LIVE
from scores import S, ADV
from positions import POS, TRIM_FRAC, AS_OF as POS_AS_OF, SOURCE as POS_SRC
from lib import total_score, market_score, pl, position_plan, cm, n
import market as MK

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TPE = datetime.timezone(datetime.timedelta(hours=8))


def now_tpe():
    return datetime.datetime.now(TPE)


def fetch_live():
    """證交所 MIS 即時報價（延遲約 5~20 秒）。回傳 {code: {...}}"""
    ch = "%7C".join("tse_%s.tw" % c for c in C.CODES)
    url = ("https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
           "?ex_ch=%s&json=1&delay=0" % ch)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://mis.twse.com.tw/stock/fibest.jsp"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("rtcode") != "0000":
        raise RuntimeError("MIS 回應異常：%s" % d.get("rtmessage"))

    def f(x):
        try:
            return float(x)
        except Exception:
            return None

    out = {}
    for a in d.get("msgArray", []):
        code = a.get("c")
        px, px_src = f(a.get("z")), "成交價"
        if px is None:                      # 該瞬間無成交 → 用最佳買賣中價
            b = f((a.get("b") or "").split("_")[0])
            s_ = f((a.get("a") or "").split("_")[0])
            if b and s_:
                px, px_src = round((b + s_) / 2, 2), "委買賣中價"
            elif b:
                px, px_src = b, "最佳買價"
        prev = f(a.get("y"))
        out[code] = {
            "name": a.get("n"), "px": px, "px_src": px_src, "prev": prev,
            "open": f(a.get("o")), "high": f(a.get("h")), "low": f(a.get("l")),
            "vol": f(a.get("v")),                       # 累積成交量（張）
            "up_lim": f(a.get("u")), "dn_lim": f(a.get("w")),
            "t": a.get("t"),
            "chg_pct": ((px / prev - 1) * 100) if (px and prev) else None,
        }
    return out


def judge(code, q, ind):
    """機械判斷：回傳 (空手結論, 持有結論, 狀態說明)"""
    z, lv = ZONE[code], LIVE[code]
    px, prev = q["px"], q["prev"]
    e_lab, h_lab = ADV[code][2], ADV[code][5]
    vol, v20 = q["vol"], ind["v20"]
    vr = (vol / v20) if (vol and v20) else None      # 對 20 日均量的比值（尚未收盤，僅供參考）

    # ── 空手 ──────────────────────────────────────────────
    if lv["buy_lo"] is None:                          # 昨日結論為「暫不設買點」
        w = lv["watch"]
        if w and px and px > w and vr and vr >= 1.0:
            empty = ("<b>條件已觸發</b>：帶量站上關鍵價 %.2f 元（現價 %.2f、量能已達 20 日均量的 %.2f 倍），"
                     "昨日設定的重新評估門檻成立 → <b>可小量試單</b>，但務必等收盤確認站穩" % (w, px, vr))
            tone = "go"
        elif w and px and px > w:
            empty = ("已站上關鍵價 %.2f 元（現價 %.2f）<b>但量能不足</b>"
                     "（目前僅 20 日均量的 %s 倍），<b>先不追</b>，等量能跟上或收盤確認"
                     % (w, px, ("%.2f" % vr) if vr else "查無"))
            tone = "warn"
        else:
            empty = ("<b>維持不建議買進</b>：關鍵價 %s 元未突破（現價 %.2f）"
                     % (("%.2f" % w) if w else "見昨日條件", px or 0))
            tone = "no"
    else:
        lo, hi = lv["buy_lo"], lv["buy_hi"]
        if px is None:
            empty, tone = "現價查無，無法判斷", "no"
        elif px < lo:
            empty = ("<b>已跌破買進區間下緣 %.2f 元</b>（現價 %.2f）——區間暫時失效，"
                     "等止穩再看，不要接下墜的刀" % (lo, px))
            tone = "warn"
        elif lo <= px <= hi:
            empty = ("<b>✅ 已進入買進區間 %.2f – %.2f 元</b>（現價 %.2f）→ <b>可分批進場</b>"
                     % (lo, hi, px))
            tone = "go"
        else:
            empty = ("仍高於買進區間上緣 %.2f 元（現價 %.2f，還要跌 %.1f%% 才進區間）→ <b>續等</b>"
                     % (hi, px, (px / hi - 1) * 100))
            tone = "wait"

    # ── 持有 ──────────────────────────────────────────────
    slo, shi, stop = lv["sell_lo"], lv["sell_hi"], lv["stop"]
    lab = z["sell_lab"]
    if px is None:
        hold = "現價查無，無法判斷"
    elif stop and px < stop:
        hold = ("<b>⚠ 已跌破出場價 %.2f 元</b>（現價 %.2f）→ <b>觸發出場條件，依昨日計畫處理</b>"
                % (stop, px))
    elif shi and px > shi:
        if vr and vr >= 1.5:
            hold = ("<b>已帶量突破%s上緣 %.2f 元</b>（現價 %.2f、量能達 20 日均量 %.2f 倍）——"
                    "<b>這比較像趨勢轉強而非反彈</b>，停利可縮手或改用移動停利"
                    "（例如跌破當日低點 %.2f 元再走）" % (lab, shi, px, vr, q["low"] or 0))
        else:
            hold = ("<b>已站上%s上緣 %.2f 元</b>（現價 %.2f）但量能未明顯放大 → "
                    "<b>可先分批減碼</b>，保留部位觀察收盤" % (lab, shi, px))
    elif slo and px >= slo:
        hold = ("<b>✅ 已進入%s %.2f – %.2f 元</b>（現價 %.2f）→ <b>可分批執行</b>"
                % (lab, slo, shi, px))
    else:
        gap = ((slo / px - 1) * 100) if (slo and px) else None
        hold = ("<b>續抱</b>：未達%s %.2f 元（現價 %.2f，還差 %s），"
                "也未跌破出場價 %.2f 元"
                % (lab, slo or 0, px, ("%.1f%%" % gap) if gap else "查無", stop or 0))

    # ── 狀態說明（一句話）──────────────────────────────
    bits = []
    if q["chg_pct"] is not None:
        bits.append("較昨收 %+.2f%%" % q["chg_pct"])
    if vr:
        bits.append("量能為 20 日均量的 %.2f 倍" % vr)
    if q["px"] and q["up_lim"] and q["px"] >= q["up_lim"] - 0.01:
        bits.append("<b>已達漲停</b>")
    if q["px"] and q["dn_lim"] and q["px"] <= q["dn_lim"] + 0.01:
        bits.append("<b>已達跌停</b>")
    note = "、".join(bits)
    return empty, hold, note, tone


def my_plan(code, q, vr):
    """★ 依實際持倉算「這次該動幾張」（守則第 20 節）。回傳 (部位列 HTML, 操作建議 HTML, 純文字)"""
    p, px = POS.get(code), q["px"]
    lvv = dict(LIVE[code], _lab=ZONE[code]["sell_lab"])
    if not p or not p.get("shares"):
        return ('<div class="pos none">目前無持倉 —— 下方「空手」那一行就是給你看的</div>',
                '<span class="adv">無持倉，依上方「空手」結論處理</span>', None)

    money = lambda v: ("+" if v > 0 else "") + cm(v)
    d = pl(p["shares"], p["cost"], px, p.get("div_ps") or 0.0)
    r = position_plan(px, lvv, p, vr=vr, trim_frac=TRIM_FRAC)
    k = "up" if d["pl"] > 0 else ("dn" if d["pl"] < 0 else "flat")
    strip = ('<div class="pos" data-pos="%s"><span>持有 <b>%.0f 張</b></span><span>成本 <b>%s</b></span>'
             '<span>現值 <b>%s</b></span><span class="%s">未實現 <b>%s 元（%+.2f%%）</b></span></div>'
             % (code, d["lots"], n(d["cost"]), cm(d["mkt_val"]), k, money(d["pl"]), d["pl_pct"]))

    nl, lots, be = r["n_lots"], r["lots"], r["breakeven"]
    if r["act"] == "exit":
        t = ("上方結論＝出場，換算成 <b>%.0f 張（全部）</b>；以現價 %.2f 元計，"
             "這一筆實現 <b>%s 元</b>" % (lots, px, money(r["realized"])))
    elif r["act"] == "trim":
        t = ("上方結論＝%s，換算成 <b>%.0f 張</b>（共 %.0f 張，留 %.0f 張）；"
             "以現價 %.2f 元計，這 %.0f 張實現 <b>%s 元</b>"
             % (r["title"], lots, nl, nl - lots, px, lots, money(r["realized"])))
    elif r["act"] == "trail":
        t = "上方結論＝改移動停利，<b>%.0f 張全數保留</b>，這個價位不減" % nl
    elif r["act"] == "addzone":
        t = ("上方結論＝可買進，<b>現價在加碼區間 %.2f – %.2f 元內</b>"
             "（每 1 張約需 <b>%s 元</b>）；<b>加幾張由你自己決定</b>，本頁不算張數。"
             "手上已有 %.0f 張" % (r["buy_lo"], r["buy_hi"], cm(r["unit"]), nl))
    else:
        t = "上方結論＝續抱，<b>%.0f 張不動</b>" % nl
    if not r["in_profit"] and px:
        t += "　·　距解套價 %.2f 元還要漲 %.1f%%" % (be, (be / px - 1) * 100)
    if r["note"]:
        t += '<span class="pw">%s</span>' % r["note"]
    return strip, '<span class="adv" data-conv="%s">%s</span>' % (code, t), r


def main():
    t0 = now_tpe()
    IND = json.load(open(os.path.join(BASE, "data", "indicators.json"), encoding="utf-8"))
    Q = fetch_live()

    # 綜合分（沿用最近一期報告）
    TOT = {}
    for c in C.CODES:
        v = list(S[c]); v[3] = market_score(MK.ENV_SCORE, IND["stocks"][c]["rs"])
        TOT[c] = total_score(tuple(v))
    order = sorted(C.CODES, key=lambda c: -TOT[c])

    mkt_open = (t0.hour * 60 + t0.minute) < 13 * 60 + 30 and t0.weekday() < 5
    state = ("盤中" if (9 * 60 <= t0.hour * 60 + t0.minute) and mkt_open
             else ("盤前" if mkt_open else "已收盤"))

    cards, plans, tot_cv, tot_mv, sim = [], {}, 0.0, 0.0, []
    for c in order:
        q, ind = Q.get(c), IND["stocks"][c]
        if not q:
            continue
        empty, hold, note, tone = judge(c, q, ind)
        vr = (q["vol"] / ind["v20"]) if (q["vol"] and ind["v20"]) else None
        strip, act, r = my_plan(c, q, vr)
        plans[c] = r
        p = POS.get(c)
        if p and p.get("shares") and q["px"]:
            tot_cv += p["shares"] * p["cost"]
            tot_mv += p["shares"] * q["px"]
        cls = "up" if (q["chg_pct"] or 0) > 0 else ("dn" if (q["chg_pct"] or 0) < 0 else "flat")

        # ★ 試算器資料（守則第 20.4 節）：只餵「換算層」需要的東西。
        #   act/title 由現價對區間決定，與成本無關，因此在這裡算好、JS 不再重算。
        lv = LIVE[c]
        sim.append(dict(
            code=c, name=q["name"], px=q["px"],
            lots=(p["shares"] / 1000.0) if (p and p.get("shares")) else 0.0,
            cost=(p["cost"] if p else 0.0), div_ps=((p.get("div_ps") or 0.0) if p else 0.0),
            act=(r["act"] if r else "none"), title=(r.get("title", "") if r else ""),
            lab=ZONE[c]["sell_lab"].replace("區間", ""),
            sell_lo=lv.get("sell_lo"), sell_hi=lv.get("sell_hi"),
            buy_lo=lv.get("buy_lo"), buy_hi=lv.get("buy_hi"), stop=lv.get("stop")))

        simbox = ("""
 <div class="sim" data-sim="%s">
  <div class="sf">
   <label>假設每股成本<input type="number" step="0.01" min="0" data-f="cost" value="%s"></label>
   <label>假設張數<input type="number" step="1" min="0" data-f="lots" value="%s"></label>
   <button type="button" data-f="reset">還原</button>
  </div>
  <p class="sn">改這兩格只會重算上面「換算張數」那一行的金額與解套價。<b>空手與持有的結論不會變</b>
  —— 它們只看現價與報告訂下的區間，跟你買在哪裡無關。試算不寫回 positions.py。</p>
 </div>""" % (c, ("%.2f" % p["cost"]) if (p and p.get("cost")) else "",
              ("%.0f" % (p["shares"] / 1000.0)) if (p and p.get("shares")) else ""))

        cards.append("""
<div class="k">
 <div class="kh"><span class="nm">%s <em>%s</em></span>
  <span class="px %s">%.2f<small>%+.2f%%</small></span>
  <span class="sc">綜合 %d</span></div>
 <div class="st">%s<small>（%s，資料時間 %s）</small></div>
 %s
 <div class="row"><span class="tag e">空手</span><span class="adv %s">%s</span></div>
 <div class="row"><span class="tag h">持有</span><span class="adv">%s</span></div>
 <div class="row me"><span class="tag m">換算<br>張數</span>%s</div>
 %s
 <div class="base">昨日結論：空手 <b>%s</b>｜持有 <b>%s</b>　·　%s</div>
</div>""" % (q["name"], c, cls, q["px"] or 0, q["chg_pct"] or 0, TOT[c],
             note, q["px_src"], q["t"], strip, tone, empty, hold, act, simbox,
             ADV[c][2], ADV[c][5],
             ("買進 %s" % ZONE[c]["buy_zone"]) + "｜" + ("%s %s" % (ZONE[c]["sell_lab"], ZONE[c]["sell_zone"]))))

    # 投資組合合計（只算有持倉的）
    tpl_ = tot_mv - tot_cv
    todo = [(c, plans[c]) for c in order if plans.get(c) and plans[c]["act"] in ("exit", "trim")]
    sumbar = ('<div class="sum"><div class="sr"><span>投入成本</span><b>%s</b></div>'
              '<div class="sr"><span>目前市值</span><b>%s</b></div>'
              '<div class="sr %s"><span>未實現損益</span><b>%s 元（%+.2f%%）</b></div>'
              '<div class="sr"><span>有動作的檔數</span><b>%s</b></div></div>'
              % (cm(tot_cv), cm(tot_mv),
                 "up" if tpl_ > 0 else ("dn" if tpl_ < 0 else "flat"),
                 ("+" if tpl_ > 0 else "") + cm(tpl_),
                 (tpl_ / tot_cv * 100) if tot_cv else 0.0,
                 ("%d 檔有動作" % len(todo)) if todo else "無，全部續抱"))

    html = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>盤中即時操作建議 · %s</title>
<style>
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%%}
:root{--bg:#f4f6f9;--card:#fff;--ink:#1a2230;--ink2:#4a5768;--ink3:#7a8798;
 --line:#dde3ea;--up:#c62828;--dn:#1b7a3d;--acc:#1f5fa9;--nav:#1b2534}
html,body{margin:0;padding:0;max-width:100%%;overflow-x:hidden}
body{background:var(--bg);color:var(--ink);overflow-wrap:break-word;line-height:1.6;
 font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",-apple-system,"Segoe UI",sans-serif;font-size:15px}
.hd{background:var(--nav);color:#fff;padding:18px 12px 16px}
.hd h1{margin:0 0 4px;font-size:clamp(19px,5vw,27px);display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.hd .bdg{background:#c07a12;color:#fff;font-size:12px;font-weight:800;border-radius:999px;
 padding:3px 11px;letter-spacing:.5px}
.hd p{margin:0;color:#b9c6d6;font-size:clamp(12px,3.3vw,14px)}
.hd .nb{margin-top:7px;font-size:11.5px;color:#e0c27f;background:rgba(192,122,18,.18);
 border:1px solid rgba(224,194,127,.35);border-radius:7px;padding:6px 9px;line-height:1.55}
.wrap{padding:12px;display:grid;gap:10px}
.k{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 13px}
.kh{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:2px}
.nm{font-size:17px;font-weight:800}.nm em{font-style:normal;font-size:12.5px;color:var(--ink3);font-weight:600}
.px{font-size:19px;font-weight:800;font-variant-numeric:tabular-nums;margin-left:auto}
.px small{font-size:13px;margin-left:5px}
.px.up,.px.up small{color:var(--up)}.px.dn,.px.dn small{color:var(--dn)}
.sc{font-size:11.5px;color:var(--ink3);background:#f2f5f9;border-radius:999px;padding:2px 9px;font-weight:700}
.st{font-size:12.5px;color:var(--ink2);margin-bottom:9px}
.st small{color:var(--ink3);font-size:11.5px}
.row{display:grid;grid-template-columns:46px minmax(0,1fr);gap:9px;align-items:start;margin-top:7px}
.tag{font-size:12px;font-weight:800;border-radius:6px;padding:3px 0;text-align:center;color:#fff;line-height:1.25}
.tag.e{background:#17497f}.tag.h{background:#8a5a00}.tag.m{background:#1b2534;font-size:11px}
.adv{font-size:13.5px;color:var(--ink)}
.adv.go{color:#17497f}.adv.warn{color:#9e3414}.adv.no{color:var(--ink3)}
.row.me{margin-top:9px;padding-top:9px;border-top:1px solid var(--line)}
.row.me .adv{font-size:14px}
.pw{display:block;margin-top:5px;font-size:12px;color:#8a5a00;background:#fff8e6;
 border:1px solid #e0c27f;border-radius:6px;padding:6px 8px;line-height:1.6}
.pos{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--ink2);
 background:#f7f9fc;border:1px solid var(--line);border-radius:7px;padding:7px 9px}
.pos b{font-variant-numeric:tabular-nums;color:var(--ink)}
.pos .up b{color:var(--up)}.pos .dn b{color:var(--dn)}
.pos.none{color:var(--ink3);font-style:normal}
.sum{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--line);
 border:1px solid var(--line);border-radius:9px;overflow:hidden;margin-bottom:2px}
.sr{background:var(--card);padding:8px 10px;display:flex;flex-direction:column;gap:1px}
.sr span{font-size:11px;color:var(--ink3)}
.sr b{font-size:15px;font-variant-numeric:tabular-nums}
.sr.up b{color:var(--up)}.sr.dn b{color:var(--dn)}
@media(min-width:640px){.sum{grid-template-columns:repeat(4,minmax(0,1fr))}}
.sim{margin:8px 0 0 55px;border:1px dashed #c9d3de;border-radius:8px;background:#fafcfe}
.sim .sf{display:flex;flex-wrap:wrap;gap:8px;align-items:end;padding:9px 10px 8px}
.sim label{font-size:11.5px;color:var(--ink2);display:flex;flex-direction:column;gap:3px;flex:1 1 120px;min-width:0}
.sim input{width:100%%;font:inherit;font-size:16px;font-variant-numeric:tabular-nums;
 padding:6px 8px;border:1px solid #c9d3de;border-radius:6px;background:#fff;color:var(--ink);min-height:38px}
.sim input:focus{outline:2px solid #17497f;outline-offset:-1px}
.sim button{font:inherit;font-size:12px;font-weight:700;padding:0 12px;min-height:38px;
 border:1px solid #c9d3de;border-radius:6px;background:#eef2f7;color:#17497f;cursor:pointer;flex:0 0 auto}
.sim button:active{background:#dde5ee}
.sim .sn{margin:0;padding:0 10px 9px;font-size:11px;color:var(--ink3);line-height:1.55}
.simon{background:#fff8e6;border-color:#e0a01e}
.simtag{display:inline-block;margin-left:6px;font-size:10.5px;font-weight:800;padding:1px 7px;
 border-radius:99px;background:#c07a12;color:#fff;vertical-align:1px}
@media(max-width:520px){.sim{margin-left:0}}
.base{margin-top:9px;padding-top:8px;border-top:1px dashed var(--line);font-size:11.5px;color:var(--ink3)}
.foot{margin:4px 12px 18px;padding:11px 12px;background:#eef1f5;border:1px solid var(--line);
 border-radius:10px;font-size:11.5px;color:var(--ink3);line-height:1.75}
.back{display:block;margin:0 12px 12px;padding:11px;background:var(--acc);color:#fff;border-radius:10px;
 text-align:center;font-weight:800;text-decoration:none;font-size:14px}
@media(min-width:1000px){.hd,.wrap,.foot,.back{max-width:860px;margin-left:auto;margin-right:auto}}
</style>
<header class="hd">
 <h1><span class="bdg">⚡ 即時</span>盤中即時操作建議</h1>
 <p>%s · 產生於 %s（台北）· 基礎報告：%s（%s收盤）</p>
 <div class="nb"><b>這不是收盤報告</b>——本頁只用即時報價對照最新一期報告訂下的買賣區間，
 <b>不含五面向評分、籌碼、財報與新聞</b>。要看完整分析請回首頁開當日的「台股每日個股觀察報告」。</div>
</header>
<div class="wrap">%s
 <p style="margin:0;font-size:11px;color:#7a8798;line-height:1.7">
 <b>持倉來源</b>：%s（%s）。張數與成本改在 <code>tools/inputs/positions.py</code>，即時頁與每日報告會同步。
 <b>持倉不會改變「空手」與「持有」的結論</b> —— 那兩行完全照舊，只依報價與報告訂下的區間判斷；
 「換算張數」只是把同一個結論換算成你的張數與金額（先減 1/3、跌破出場價全出）。
 <b>加碼張數一律不算</b>，只告訴你區間端點與每 1 張的金額，加幾張你自己決定。
 成本為券商顯示值，<b>未還原除權息</b>。</p>
%s</div>
<a class="back" href="../index.html">← 回總覽首頁</a>
<script>
/* ★ 成本試算器（守則第 20.4 節）——只重算「換算層」。
   空手／持有兩行由 Python 產生後即不再更動，JS 完全不碰它們。
   act（出場／減碼／續抱…）由現價對區間決定，已在 Python 算好，這裡不重算。 */
(function(){
var D=%s, LOT=1000, TRIM=%s;
function cm(v,d){d=d||0;return (v<0?"-":"")+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});}
function nf(v,d){d=(d===undefined)?2:d;return Math.abs(v)>=1000?cm(v,d):v.toFixed(d);}
function money(v){return (v>0?"+":"")+cm(Math.round(v));}
function halfUp(x){return Math.floor(x+0.5);}
function trimLots(n){return Math.max(1,Math.min(Math.floor(n),halfUp(n*TRIM)));}
function calc(s,cost,lots){
 var px=s.px, be=cost-s.div_ps, sh=lots*LOT;
 var o={be:be,lots:lots,cv:sh*cost,mv:sh*px,inProfit:px>=be};
 o.pl=o.mv-o.cv; o.plPct=cost?((px/cost-1)*100):0;
 o.act=(lots>0)?s.act:"none";
 if(o.act==="exit"){o.n=lots;}
 else if(o.act==="trim"){o.n=trimLots(lots);}
 else {o.n=0;}
 o.realized=(o.act==="exit"||o.act==="trim")?(px-cost)*o.n*LOT:0;
 return o;
}
function render(s,cost,lots,dirty){
 var o=calc(s,cost,lots), px=s.px, t;
 var posEl=document.querySelector('[data-pos="'+s.code+'"]');
 var cvEl=document.querySelector('[data-conv="'+s.code+'"]');
 if(!posEl||!cvEl)return o;
 var k=o.pl>0?"up":(o.pl<0?"dn":"flat");
 posEl.innerHTML='<span>持有 <b>'+o.lots.toFixed(0)+' 張</b></span><span>成本 <b>'+nf(cost)+'</b></span>'
  +'<span>現值 <b>'+cm(o.mv)+'</b></span><span class="'+k+'">未實現 <b>'+money(o.pl)
  +' 元（'+(o.plPct>0?"+":"")+o.plPct.toFixed(2)+'%%）</b></span>'
  +(dirty?'<span class="simtag">試算</span>':'');
 if(o.act==="none"){t='目前無持倉 —— 依上方「空手」結論處理';}
 else if(o.act==="exit"){t='上方結論＝出場，換算成 <b>'+o.n.toFixed(0)+' 張（全部）</b>；以現價 '+px.toFixed(2)
  +' 元計，這一筆實現 <b>'+money(o.realized)+' 元</b>';}
 else if(o.act==="trim"){t='上方結論＝'+s.title+'，換算成 <b>'+o.n.toFixed(0)+' 張</b>（共 '+o.lots.toFixed(0)
  +' 張，留 '+(o.lots-o.n).toFixed(0)+' 張）；以現價 '+px.toFixed(2)+' 元計，這 '+o.n.toFixed(0)
  +' 張實現 <b>'+money(o.realized)+' 元</b>';}
 else if(o.act==="trail"){t='上方結論＝改移動停利，<b>'+o.lots.toFixed(0)+' 張全數保留</b>，這個價位不減';}
 else if(o.act==="addzone"){t='上方結論＝可買進，<b>現價在加碼區間 '+s.buy_lo.toFixed(2)+' – '+s.buy_hi.toFixed(2)
  +' 元內</b>（每 1 張約需 <b>'+cm(px*LOT)+' 元</b>）；<b>加幾張由你自己決定</b>，本頁不算張數。手上已有 '
  +o.lots.toFixed(0)+' 張';}
 else {t='上方結論＝續抱，<b>'+o.lots.toFixed(0)+' 張不動</b>';}
 if(!o.inProfit&&px){t+='　·　距解套價 '+o.be.toFixed(2)+' 元還要漲 '+((o.be/px-1)*100).toFixed(1)+'%%';}
 if(s.sell_hi&&o.be>s.sell_hi){
  t+='<span class="pw">成本對照：解套價 '+o.be.toFixed(2)+' 元高於'+s.lab+'上緣 '+s.sell_hi.toFixed(2)
   +' 元 —— 在這個區間執行會實現虧損，金額如上。</span>';
 }else if(s.sell_lo&&o.be<=s.sell_lo&&(o.act==="trim"||o.act==="trail")){
  t+='<span class="pw">成本對照：解套價 '+o.be.toFixed(2)+' 元低於'+s.lab+'下緣 '+s.sell_lo.toFixed(2)
   +' 元 —— 整段區間都在成本之上，執行即為實現獲利。</span>';
 }else if(s.buy_lo&&s.stop&&s.buy_lo<s.stop&&s.stop<=(s.buy_hi||0)){
  t+='<span class="pw">價位對照：買進區間下緣 '+s.buy_lo.toFixed(2)+' 元低於出場價 '+s.stop.toFixed(2)+' 元，兩者重疊。</span>';
 }
 cvEl.innerHTML=t;
 return o;
}
function totals(){
 var cv=0,mv=0,todo=0;
 D.forEach(function(s){
  var box=document.querySelector('[data-sim="'+s.code+'"]');
  var c=parseFloat(box.querySelector('[data-f=cost]').value),
      l=parseFloat(box.querySelector('[data-f=lots]').value);
  if(!isFinite(c)||c<=0)c=s.cost; if(!isFinite(l)||l<0)l=s.lots;
  var dirty=(Math.abs(c-s.cost)>1e-9)||(Math.abs(l-s.lots)>1e-9);
  box.classList.toggle("simon",dirty);
  var o=render(s,c,l,dirty);
  cv+=o.cv; mv+=o.mv;
  if(o.act==="exit"||o.act==="trim")todo++;
 });
 var bar=document.querySelector(".sum");
 if(bar){var pl=mv-cv, k=pl>0?"up":(pl<0?"dn":"flat");
  bar.innerHTML='<div class="sr"><span>投入成本</span><b>'+cm(cv)+'</b></div>'
   +'<div class="sr"><span>目前市值</span><b>'+cm(mv)+'</b></div>'
   +'<div class="sr '+k+'"><span>未實現損益</span><b>'+money(pl)+' 元（'
   +(cv?((pl/cv*100)>0?"+":""):"")+(cv?(pl/cv*100).toFixed(2):"0.00")+'%%）</b></div>'
   +'<div class="sr"><span>有動作的檔數</span><b>'+(todo?todo+" 檔有動作":"無，全部續抱")+'</b></div>';}
}
document.addEventListener("input",function(e){if(e.target.closest(".sim"))totals();});
document.addEventListener("click",function(e){
 var b=e.target.closest('[data-f=reset]'); if(!b)return;
 var box=b.closest(".sim"), s=D.filter(function(x){return x.code===box.dataset.sim;})[0];
 box.querySelector('[data-f=cost]').value=s.cost?s.cost.toFixed(2):"";
 box.querySelector('[data-f=lots]').value=s.lots?s.lots.toFixed(0):"";
 totals();
});
})();
</script>
<div class="foot">
 <p><b>這一頁只回答「現在該怎麼做」</b>：拿最近一期收盤報告訂下的買賣區間與出場價，
 對照證交所即時報價（MIS，延遲約 5~20 秒），判斷現價落在哪一段。
 <b>不重算五面向評分、不抓籌碼與財報</b>——盤中資料不足以改變評分，評分一律以收盤後的正式報告為準。</p>
 <p><b>⚠ 盤中判斷務必留意</b>：①未收盤前的量能只是累積值，與收盤後的量比不能直接比較；
 ②突破或跌破在收盤前都可能被打回，建議至少等尾盤再確認；
 ③本頁每次執行都會覆蓋，顯示的是產生當下的狀態，不會自動更新，請重新執行取得最新。</p>
 <p>本頁由自動化流程彙整公開資訊產生，僅供研究與教育參考，不構成投資建議。投資有風險，過去績效不代表未來表現。</p>
</div>
""" % (t0.strftime("%m/%d %H:%M"),
       state, t0.strftime("%Y/%m/%d %H:%M:%S"), C.BASE_DATE, C.BASE_WEEKDAY,
       sumbar, POS_SRC, POS_AS_OF, "".join(cards),
       json.dumps(sim, ensure_ascii=False), repr(TRIM_FRAC))

    out_dir = os.path.join(C.REPO, "live")
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "index.html")
    open(p, "w", encoding="utf-8").write(html)

    print("=" * 88)
    print("⚡【即時】盤中即時操作建議（非收盤報告）｜%s｜產生於 %s"
          % (state, t0.strftime("%Y/%m/%d %H:%M:%S")))
    print("基礎報告：%s（%s收盤）｜輸出：live/index.html（每次覆蓋）" % (C.BASE_DATE, C.BASE_WEEKDAY))
    print("=" * 88)
    import re

    def strip(s):                       # HTML → 主控台純文字（警示框另起一行）
        return re.sub(r"<[^>]+>", "", s.replace('<span class="pw">', "\n      ⚠ "))

    for c in order:
        q = Q.get(c)
        if not q:
            continue
        ind = IND["stocks"][c]
        e, h, note, _ = judge(c, q, ind)
        vr = (q["vol"] / ind["v20"]) if (q["vol"] and ind["v20"]) else None
        _, act, r = my_plan(c, q, vr)
        print("\n%s %s  %.2f (%+.2f%%)  %s" % (c, q["name"], q["px"] or 0, q["chg_pct"] or 0, note))
        if r:
            d = pl(POS[c]["shares"], POS[c]["cost"], q["px"], POS[c].get("div_ps") or 0.0)
            print("   部位：%.0f 張 · 成本 %.2f · 現值 %s · 未實現 %s（%+.2f%%）"
                  % (d["lots"], d["cost"], cm(d["mkt_val"]),
                     ("+" if d["pl"] > 0 else "") + cm(d["pl"]), d["pl_pct"]))
        print("   空手：%s" % strip(e))
        print("   持有：%s" % strip(h))
        print("   換算：%s" % strip(act))
    print("\n" + "-" * 88)
    print("投資組合：投入 %s ｜ 市值 %s ｜ 未實現 %s 元（%+.2f%%）｜ 待處理 %s"
          % (cm(tot_cv), cm(tot_mv), ("+" if tpl_ > 0 else "") + cm(tpl_),
             (tpl_ / tot_cv * 100) if tot_cv else 0.0,
             "、".join("%s %s %.0f 張" % (c, plans[c]["title"], plans[c]["lots"]) for c, _ in todo)
             or "無，全部續抱"))
    print("持倉來源：%s（%s）——買賣後請改 tools/inputs/positions.py" % (POS_SRC, POS_AS_OF))
    print("\n已寫入 %s（%d 字元）" % (p, len(html)))


if __name__ == "__main__":
    main()
