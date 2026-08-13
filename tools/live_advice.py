# -*- coding: utf-8 -*-
"""盤中即時操作建議（守則第 19 節）—— 可隨時重跑，每次覆蓋 REPO/live/index.html

做什麼：抓即時報價（證交所 MIS）→ 對照最近一期報告訂下的操作區間（inputs/zones.py 的 LIVE）
        → 直接給「空手該不該買、持有該不該賣」，只講操作，不重複收盤報告的細節。

不做什麼：不重算五面向評分、不抓籌碼與財報。盤中資料不足以改變評分，
          真正的評分一律以收盤後的正式報告為準。

用法：python live_advice.py          （盤中隨時可跑，會覆蓋 live/index.html）
"""
import json, os, sys, time, urllib.request, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "inputs"))
import config as C
from zones import ZONE, LIVE
from scores import S, ADV
from lib import total_score, market_score
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

    cards = []
    for c in order:
        q, ind = Q.get(c), IND["stocks"][c]
        if not q:
            continue
        empty, hold, note, tone = judge(c, q, ind)
        cls = "up" if (q["chg_pct"] or 0) > 0 else ("dn" if (q["chg_pct"] or 0) < 0 else "flat")
        cards.append("""
<div class="k">
 <div class="kh"><span class="nm">%s <em>%s</em></span>
  <span class="px %s">%.2f<small>%+.2f%%</small></span>
  <span class="sc">綜合 %d</span></div>
 <div class="st">%s<small>（%s，資料時間 %s）</small></div>
 <div class="row"><span class="tag e">空手</span><span class="adv %s">%s</span></div>
 <div class="row"><span class="tag h">持有</span><span class="adv">%s</span></div>
 <div class="base">昨日結論：空手 <b>%s</b>｜持有 <b>%s</b>　·　%s</div>
</div>""" % (q["name"], c, cls, q["px"] or 0, q["chg_pct"] or 0, TOT[c],
             note, q["px_src"], q["t"], tone, empty, hold,
             ADV[c][2], ADV[c][5],
             ("買進 %s" % ZONE[c]["buy_zone"]) + "｜" + ("%s %s" % (ZONE[c]["sell_lab"], ZONE[c]["sell_zone"]))))

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
.hd h1{margin:0 0 4px;font-size:clamp(19px,5vw,27px)}
.hd p{margin:0;color:#b9c6d6;font-size:clamp(12px,3.3vw,14px)}
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
.tag{font-size:12px;font-weight:800;border-radius:6px;padding:3px 0;text-align:center;color:#fff}
.tag.e{background:#17497f}.tag.h{background:#8a5a00}
.adv{font-size:13.5px;color:var(--ink)}
.adv.go{color:#17497f}.adv.warn{color:#9e3414}.adv.no{color:var(--ink3)}
.base{margin-top:9px;padding-top:8px;border-top:1px dashed var(--line);font-size:11.5px;color:var(--ink3)}
.foot{margin:4px 12px 18px;padding:11px 12px;background:#eef1f5;border:1px solid var(--line);
 border-radius:10px;font-size:11.5px;color:var(--ink3);line-height:1.75}
.back{display:block;margin:0 12px 12px;padding:11px;background:var(--acc);color:#fff;border-radius:10px;
 text-align:center;font-weight:800;text-decoration:none;font-size:14px}
@media(min-width:1000px){.hd,.wrap,.foot,.back{max-width:860px;margin-left:auto;margin-right:auto}}
</style>
<header class="hd">
 <h1>盤中即時操作建議</h1>
 <p>%s · 產生於 %s（台北）· 基礎報告：%s（%s收盤）</p>
</header>
<div class="wrap">%s</div>
<a class="back" href="../index.html">← 回總覽首頁</a>
<div class="foot">
 <p><b>這一頁只回答「現在該怎麼做」</b>：拿最近一期收盤報告訂下的買賣區間與出場價，
 對照證交所即時報價（MIS，延遲約 5~20 秒），判斷現價落在哪一段。
 <b>不重算五面向評分、不抓籌碼與財報</b>——盤中資料不足以改變評分，評分一律以收盤後的正式報告為準。</p>
 <p><b>⚠ 盤中判斷務必留意</b>：①未收盤前的量能只是累積值，與收盤後的量比不能直接比較；
 ②突破或跌破在收盤前都可能被打回，建議至少等尾盤再確認；
 ③本頁每次執行都會覆蓋，顯示的是產生當下的狀態，不會自動更新，請重新執行取得最新。</p>
 <p>本頁由自動化流程彙整公開資訊產生，僅供研究與教育參考，不構成投資建議。投資有風險，過去績效不代表未來表現。</p>
</div>
""" % (t0.strftime("%%m/%%d %%H:%%M") if False else t0.strftime("%m/%d %H:%M"),
       state, t0.strftime("%Y/%m/%d %H:%M:%S"), C.BASE_DATE, C.BASE_WEEKDAY,
       "".join(cards))

    out_dir = os.path.join(C.REPO, "live")
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "index.html")
    open(p, "w", encoding="utf-8").write(html)

    print("=" * 88)
    print("盤中即時操作建議｜%s｜產生於 %s" % (state, t0.strftime("%Y/%m/%d %H:%M:%S")))
    print("基礎報告：%s（%s收盤）" % (C.BASE_DATE, C.BASE_WEEKDAY))
    print("=" * 88)
    for c in order:
        q = Q.get(c)
        if not q:
            continue
        e, h, note, _ = judge(c, q, IND["stocks"][c])
        strip = lambda s: s.replace("<b>", "").replace("</b>", "")
        print("\n%s %s  %.2f (%+.2f%%)  %s" % (c, q["name"], q["px"] or 0, q["chg_pct"] or 0, note))
        print("   空手：%s" % strip(e))
        print("   持有：%s" % strip(h))
    print("\n已寫入 %s（%d 字元）" % (p, len(html)))


if __name__ == "__main__":
    main()
