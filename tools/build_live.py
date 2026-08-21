# -*- coding: utf-8 -*-
"""當日即時投資建議 → REPO/live/index.html（每次執行直接覆蓋）

用「最新一期日報的買賣區間與雙情境建議」＋「即時報價」，
只輸出可以立刻執行的動作：空手要不要買／買在哪個區間，持有要不要抱／賣在哪個區間。

★ 移植時不用改；標的、區間、建議全部來自 config.py 與 inputs/。
★ 不重算任何評分或技術指標——均線、布林、20 日均量一律沿用基準日的 data/indicators.json，
  只有價格與成交量是即時的。這樣才不會出現「盤中未完成 K 棒污染指標」的問題。

用法：
    python build_live.py          # 盤中可重複執行，每次覆蓋 live/index.html
"""
import json, os, re, sys, time, datetime, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "inputs"))
import config as C
from lib import (total_score, market_score, band_of, tech_adj,
                 pl as pl_calc, position_plan)
import market as MK
from scores import S, ADV
# ★ MySelf 專屬：LIVE 為結構化價位、positions 為實際持倉（守則第 19.4／20 節）
from zones import ZONE, LIVE
from positions import POS, TRIM_FRAC, AS_OF as POS_AS_OF, SOURCE as POS_SRC

D = os.path.join(BASE, "data")
IND = json.load(open(os.path.join(D, "indicators.json"), encoding="utf-8"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
LIVE_DIR = os.path.join(C.REPO, "live")

# 綜合分（與日報一致：大盤面由公式覆寫、技術面加上 §9.1 的客觀加減分）
# ★ 修正：原本直接用 scores.S 的技術「判讀分」，漏掉 lib.tech_adj 的客觀加減分，
#   會讓即時頁的「日報 N 分」比日報本身少 1 分（守則 §9.1：手填無效、一律由程式套用）。
for c in C.CODES:
    _adj, _ = tech_adj(IND["stocks"][c])
    S[c] = (S[c][0], max(0, min(100, S[c][1] + _adj)), S[c][2],
            market_score(MK.ENV_SCORE, IND["stocks"][c]["rs"]), S[c][4])
TOT = {c: total_score(S[c]) for c in C.CODES}


# ── 抓即時報價 ────────────────────────────────────────────────────
# ★ 來源優先序（2026-08-18 改）。原本只用 Yahoo，實測延遲 15~20 分鐘，
#   盤中會拿 20 分鐘前的價去比對買賣區間，動作可能已經過期，因此改為：
#   1) 玩股網 all-quote-info —— 全市場一次取回，時間戳幾乎零延遲，有真正的最新成交價與當日張數
#   2) 證交所 MIS getStockInfo —— 5 秒揭示的即時快照。個股 z（最新成交價）常回 "-"，
#      此時退用最佳一檔買賣的中價，來源標記為「證交所(中價)」
#   3) Yahoo chart —— 延遲 15~20 分鐘，只當最後手段，來源會標明「延遲」
#   三者都正規化成 Yahoo 的欄位名，後面的判定邏輯完全不必改。
WG_URL = "https://www.wantgoo.com/investrue/all-quote-info"
MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=%s&json=1&delay=0"
WG_INDEX, MIS_INDEX = "0000", "tse_t00.tw"     # 加權指數在兩邊的代號


def _get(url, tries=3, timeout=25):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None                # 濾掉 nan


def norm_wg(r):
    """玩股網 → Yahoo 欄位名。volume 單位是張，乘回 1000 股以符合下游算法。"""
    px = _f(r.get("close"))
    if not px:
        return None
    vol, t = _f(r.get("volume")), r.get("time")
    return {"regularMarketPrice": px,
            "previousClose": _f(r.get("previousClose")) or _f(r.get("flat")),
            "regularMarketDayHigh": _f(r.get("high")),
            "regularMarketDayLow": _f(r.get("low")),
            "regularMarketVolume": vol * 1000 if vol is not None else None,
            "regularMarketTime": int(t / 1000) if t else None,
            "_src": "玩股網"}


def norm_mis(m):
    """MIS → Yahoo 欄位名。z 為 "-" 時退用最佳一檔買賣中價。"""
    px, src = _f(m.get("z")), "證交所"
    if not px:
        bid = _f((m.get("b") or "").split("_")[0])
        ask = _f((m.get("a") or "").split("_")[0])
        px = (bid + ask) / 2 if (bid and ask) else (bid or ask)
        src = "證交所(中價)"
    if not px:
        return None
    vol, t = _f(m.get("v")), m.get("tlong")
    return {"regularMarketPrice": px,
            "previousClose": _f(m.get("y")),
            "regularMarketDayHigh": _f(m.get("h")),
            "regularMarketDayLow": _f(m.get("l")),
            "regularMarketVolume": vol * 1000 if vol is not None else None,
            "regularMarketTime": int(int(t) / 1000) if t else None,
            "_src": src}


def fetch_wg():
    try:
        d = _get(WG_URL)
    except Exception as e:
        print("    ★ 玩股網取價失敗，改用備援來源：%s" % e)
        return {}
    rows = d if isinstance(d, list) else (d.get("data") or [])
    return {str(r.get("id", "")): r for r in rows if isinstance(r, dict)}


def fetch_mis(chans):
    try:
        d = _get(MIS_URL % "|".join(chans))
    except Exception as e:
        print("    ★ 證交所取價失敗：%s" % e)
        return {}
    return {str(m.get("c", "")): m for m in (d.get("msgArray") or [])}


def mis_chan(code):
    return ("otc_%s.tw" if C.SYM[code].endswith(".TWO") else "tse_%s.tw") % code


def quote_yahoo(sym):
    """最後手段：Yahoo，延遲 15~20 分鐘。"""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + sym.replace("^", "%5E") + "?range=1d&interval=5m")
    try:
        m = dict(_get(url)["chart"]["result"][0]["meta"])
        m["_src"] = "Yahoo(延遲)"
        return m
    except Exception as e:
        print("    ★ %s Yahoo 取價失敗：%s" % (sym, e))
        return None


def num(m, *keys):
    for k in keys:
        v = m.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None

print("=" * 92)
print("當日即時投資建議")
print("=" * 92)
print("依據日報：%s（%s收盤）" % (C.BASE_DATE, C.BASE_WEEKDAY))

# 1) 玩股網一次取回全市場（含加權指數）
WG = fetch_wg()
Q = {}
for c in C.CODES:
    m = norm_wg(WG.get(c) or {})
    if m:
        Q[c] = m
QI = norm_wg(WG.get(WG_INDEX) or {})

# 2) 缺的用證交所 MIS 補（連同加權指數）
miss = [c for c in C.CODES if c not in Q]
if miss or not QI:
    MIS = fetch_mis([mis_chan(c) for c in miss] + ([MIS_INDEX] if not QI else []))
    for c in miss:
        m = norm_mis(MIS.get(c) or {})
        if m:
            Q[c] = m
    if not QI:
        QI = norm_mis(MIS.get("t00") or {})

# 3) 還是缺的才落到 Yahoo（延遲 15~20 分鐘）
for c in C.CODES:
    if c not in Q:
        m = quote_yahoo(C.SYM[c])
        if m:
            Q[c] = m
if not QI:
    QI = quote_yahoo(C.INDEX_SYM)

if not Q:
    sys.exit("★ 全部取價失敗，中止（未覆蓋既有 live 頁）")

SRCS = sorted({m.get("_src", "?") for m in Q.values()} | ({QI.get("_src", "?")} if QI else set()))
SRC_LABEL = "／".join(SRCS)
DELAYED = any("延遲" in s for s in SRCS)

# 報價時間：取各檔最新的 regularMarketTime
qt = max(int(m.get("regularMarketTime") or 0) for m in Q.values())
if QI:
    qt = max(qt, int(QI.get("regularMarketTime") or 0))
QT = datetime.datetime.fromtimestamp(qt)
NOW = datetime.datetime.now()
LAG = max(0, int((NOW - QT).total_seconds() // 60))   # 來源時間戳會進位到整分，可能略超前本機時鐘，夾到 0 免得出現負延遲
TODAY = NOW.strftime("%Y-%m-%d")
SAME_DAY = QT.strftime("%Y-%m-%d") == TODAY

# 盤別：09:00~13:30 為盤中。
# ★ 用本機時間（NOW）判盤別，不能用報價時間（QT）——收盤後 QT 永遠停在 13:30，
#   若以 QT 判斷，之後每次執行都會誤標成「盤中」。QT 只用來判斷報價新舊。
_hm = NOW.hour * 60 + NOW.minute
if not SAME_DAY:
    PHASE, PHASE_CLS = "休市（報價為前一交易日收盤）", "ph-off"
elif _hm < 9 * 60:
    PHASE, PHASE_CLS = "尚未開盤", "ph-off"
elif _hm < 13 * 60 + 30:
    PHASE, PHASE_CLS = "盤中", "ph-live"
else:
    PHASE, PHASE_CLS = "已收盤（報價為今日收盤價）", "ph-close"

STALE = QT.strftime("%Y-%m-%d") == C.BASE_DATE   # 報價還停在日報基準日 → 尚未有新行情


# ── 區間字串 → 數字 ──────────────────────────────────────────────
def bounds(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*[–\-~〜]\s*(\d+(?:\.\d+)?)", s)
    return (float(m.group(1)), float(m.group(2))) if m else None


def fmt(x, nd=2):
    return "查無" if x is None else ("{:,.%df}" % nd).format(x)


def mny(v):
    """★ MySelf 專屬：帶正負號與千分位的金額。%% 格式化不支援逗號旗標，故用 str.format。"""
    return "{:+,.0f}".format(v or 0)


# ── 逐檔判定 ─────────────────────────────────────────────────────
ROWS, ALERTS = [], []
for c in C.CODES:
    m, a, z = Q.get(c), IND["stocks"][c], ZONE[c]
    if not m:
        continue
    px = num(m, "regularMarketPrice")
    pc = num(m, "previousClose", "chartPreviousClose")
    hi = num(m, "regularMarketDayHigh")
    lo = num(m, "regularMarketDayLow")
    vol = num(m, "regularMarketVolume")
    lots = vol / 1000 if vol is not None else None
    chg = px - pc if (px is not None and pc is not None) else None
    chgp = chg / pc * 100 if (chg is not None and pc) else None
    # 量能：即時張數 ÷ 基準日的 20 日均量
    vr = lots / a["v20"] if (lots is not None and a.get("v20")) else None
    ma5, ma20, ma60 = a["ma"].get("5"), a["ma"].get("20"), a["ma"].get("60")
    up_ma = sum(1 for k in ("5", "10", "20", "60", "120", "240")
                if a["ma"].get(k) and px and px >= a["ma"][k])

    bz, sz = bounds(z["buy_zone"]), bounds(z["sell_zone"])
    _, e_ico, e_lab, _, h_ico, h_lab = ADV[c]

    # 空手
    if bz is None:                                    # 「暫不設買點」
        e_cls, e_act = "a-no", "不宜買進"
        e_why = "日報未設買點（%s）。重新評估門檻：%s" % (z["buy_anchor"], z["buy_cond"])
    elif bz[0] <= px <= bz[1]:
        e_cls, e_act = "a-buy", "已進入買進區間，可分批買進"
        e_why = "買進區間 %s（%s）。仍須確認：%s" % (z["buy_zone"], z["buy_anchor"], z["buy_cond"])
        ALERTS.append((c, "買", "價格進入買進區間 %s" % z["buy_zone"]))
    elif px > bz[1]:
        e_cls, e_act = "a-wait", "偏貴，等回到 %s" % z["buy_zone"]
        e_why = "距區間上緣 %s 元還有 %+.1f%%（%s）。" % (fmt(bz[1]), (px / bz[1] - 1) * 100, z["buy_anchor"])
    else:
        e_cls, e_act = "a-warn", "已跌破買進區間下緣，先別接"
        e_why = ("現價低於區間下緣 %s 元（%s），代表原本錨定的支撐已失守，"
                 "買進理由要重新確認：%s" % (fmt(bz[0]), z["buy_anchor"], z["buy_cond"]))
        ALERTS.append((c, "警", "跌破買進區間下緣 %s 元" % fmt(bz[0])))

    # 持有
    # ★ 必須尊重日報的持有結論：h-exit（近期出場）／h-cut（減碼）不可因為「還沒到區間」
    #   就講成「續抱」，否則會與日報結論互相矛盾。
    h_kind = ADV[c][3]                      # h-tp / h-cut / h-exit
    base = {"h-exit": "出場", "h-cut": "減碼"}.get(h_kind, "停利")
    # ★ MySelf 專屬：帶量突破上緣時，日報訂的是「改移動停利、不要機械式賣光」，
    #   不可講成「優先執行」——否則會與同一張卡片下方由 lib.position_plan 算出的
    #   「改移動停利、N 張不動」互相矛盾。門檻與 position_plan 一致（量比 ≥ 1.5）。
    if sz and px > sz[1] and h_kind == "h-tp" and vr is not None and vr >= 1.5:
        h_cls = "a-hold"
        h_act = "帶量突破%s上緣，改移動停利、不要機械式賣光" % z["sell_lab"]
        h_why = ("量比 %.2f 倍 ≥ 1.5 且已站上上緣 %s 元——依日報這是「趨勢轉強而非反彈」，"
                 "既有部位改用移動停利跟著走，不在此價位機械式賣光。%s"
                 % (vr, fmt(sz[1]), z["sell_cond"]))
        ALERTS.append((c, "警", "帶量站上%s上緣 %s 元（量比 %.2f 倍）→ 改移動停利"
                       % (z["sell_lab"], fmt(sz[1]), vr)))
    elif sz and px > sz[1]:
        h_cls = "a-sell"
        h_act = "已高於%s上緣，優先執行" % z["sell_lab"]
        h_why = "%s %s（%s）。%s" % (z["sell_lab"], z["sell_zone"], z["sell_anchor"], z["sell_cond"])
        ALERTS.append((c, "賣", "價格高於%s上緣 %s 元" % (z["sell_lab"], fmt(sz[1]))))
    elif sz and px >= sz[0]:
        h_cls = "a-sell"
        h_act = "已進入%s，依原訂條件執行" % z["sell_lab"]
        h_why = "%s %s（%s）。%s" % (z["sell_lab"], z["sell_zone"], z["sell_anchor"], z["sell_cond"])
        ALERTS.append((c, "賣", "價格進入%s %s" % (z["sell_lab"], z["sell_zone"])))
    elif ma20 and px < ma20:
        h_cls, h_act = "a-cut", "跌破月線 %s 元，加快%s" % (fmt(ma20), base)
        h_why = "月線為中期多空分界，已在其下；不必等回到%s。原訂條件：%s" % (z["sell_lab"], z["sell_cond"])
        ALERTS.append((c, "警", "跌破月線 %s 元" % fmt(ma20)))
    elif ma5 and px < ma5:
        # ★ 鐵則：日報判「出場／減碼」者，跌破 5 日線不可弱化成「先縮手」
        if h_kind in ("h-exit", "h-cut"):
            h_cls = "a-cut"
            h_act = "已跌破 5 日線 %s 元，%s不必再等反彈" % (fmt(ma5), base)
            h_why = "日報結論已是「%s」，短線又轉弱，依原訂條件加快執行。%s" % (ADV[c][5], z["sell_cond"])
        else:
            h_cls, h_act = "a-warn", "跌破 5 日線 %s 元，先縮手" % fmt(ma5)
            h_why = "短線轉弱但月線 %s 元未破。原訂條件：%s" % (fmt(ma20), z["sell_cond"])
    elif h_kind == "h-exit":
        h_cls, h_act = "a-cut", "低於出場區間，仍應在期限內分批出場"
        h_why = ("日報結論是「%s」，不因價格未到 %s 而改為續抱；"
                 "反彈至 %s 分批出。%s" % (ADV[c][5], z["sell_zone"], z["sell_zone"], z["sell_cond"]))
    elif h_kind == "h-cut":
        # ★ 鐵則 3：日報若已宣告某一段減碼觸發，不可講成「等反彈到區間再減」——那等於取消已觸發的動作
        if z.get("done"):
            h_cls = "a-cut"
            h_act = "已觸發的減碼先執行，其餘反彈至 %s" % z["sell_zone"]
            h_why = "<b>%s</b>。目前價格未到%s（%s）；跌破 5 日線 %s 元則剩餘部位也不必等反彈。%s" % (
                z["done"], z["sell_lab"], z["sell_anchor"], fmt(ma5), z["sell_cond"])
        else:
            h_cls, h_act = "a-warn", "反彈至 %s 再減碼" % z["sell_zone"]
            h_why = "日報結論是「%s」，目前價格未到%s（%s）；跌破 5 日線 %s 元則不必等反彈。%s" % (
                ADV[c][5], z["sell_lab"], z["sell_anchor"], fmt(ma5), z["sell_cond"])
    elif z.get("done"):
        # ★ 鐵則 3：停利區間曾被觸及者，跌回區間下緣之下不等於「未觸發任何條件」
        h_cls = "a-warn"
        h_act = "已觸發的%s先執行，其餘續抱" % base
        h_why = "<b>%s</b>。%s在 %s（%s）；跌破 5 日線 %s 元先縮手。%s" % (
            z["done"], z["sell_lab"], z["sell_zone"], z["sell_anchor"], fmt(ma5), z["sell_cond"])
    else:
        h_cls, h_act = "a-hold", "續抱，未觸發任何條件"
        h_why = "%s在 %s（%s）；跌破 5 日線 %s 元先縮手。%s" % (
            z["sell_lab"], z["sell_zone"], z["sell_anchor"], fmt(ma5), z["sell_cond"])

    # ★ MySelf 專屬：實際持倉的損益與「換算成幾張」（守則第 20.2 節，純算術）
    #   ⚠ 不產生新結論、不改寫上方措辭；動作與用語一律沿用 zones.py 那一套。
    p = POS.get(c)
    pos = pl_calc(p["shares"], p["cost"], px, p.get("div_ps") or 0.0) if p else None
    lv = dict(LIVE[c]); lv["_lab"] = z["sell_lab"]
    plan = position_plan(px, lv, p, vr, TRIM_FRAC) if p else None
    if plan and plan["act"] in ("exit", "trim"):
        ALERTS.append((c, "倉", "你的部位：%s %g 張（以現價計實現 %s 元）"
                       % (plan["title"], plan["lots"], mny(plan.get("realized")))))

    if c in C.TIME_PRESSURE:
        ALERTS.append((c, "時", C.TIME_PRESSURE[c].split("、")[0]))

    ROWS.append(dict(c=c, name=C.NAME[c], px=px, chg=chg, chgp=chgp, hi=hi, lo=lo,
                     lots=lots, vr=vr, up_ma=up_ma, tot=TOT[c], band=band_of(TOT[c]),
                     e_ico=e_ico, e_lab=e_lab, h_ico=h_ico, h_lab=h_lab,
                     e_cls=e_cls, e_act=e_act, e_why=e_why,
                     h_cls=h_cls, h_act=h_act, h_why=h_why,
                     tp=C.TIME_PRESSURE.get(c, ""),
                     hk=h_kind, sz0=sz[0] if sz else None, sz1=sz[1] if sz else None,
                     ma5=ma5, ma20=ma20, slab=z["sell_lab"], szone=z["sell_zone"],
                     pos=pos, plan=plan, cost=(p or {}).get("cost")))

ROWS.sort(key=lambda r: -r["tot"])

# ── 產生 HTML ────────────────────────────────────────────────────
CSS = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
:root{--bg:#f4f6f9;--card:#fff;--ink:#1a2230;--ink2:#4a5768;--ink3:#7a8798;--line:#dde3ea;
 --up:#c62828;--dn:#1b7a3d;--acc:#1f5fa9;--nav:#1b2534;--pad:12px;--r:10px}
html,body{margin:0;padding:0;max-width:100%;overflow-x:hidden}
body{background:var(--bg);color:var(--ink);overflow-wrap:break-word;word-break:break-word;
 font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
 font-size:15px;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:var(--acc);text-decoration:none}
.hd{background:var(--nav);color:#fff;padding:18px var(--pad) 16px}
.hdin{max-width:960px;margin:0 auto}
.hd h1{margin:0 0 5px;font-size:clamp(19px,5.2vw,29px);line-height:1.25}
.hd p{margin:0;color:#b9c6d6;font-size:clamp(12px,3.3vw,14px)}
.ph{display:inline-block;border-radius:999px;padding:2px 11px;font-size:11.5px;font-weight:700;margin-right:7px}
.ph-live{background:var(--up);color:#fff} .ph-close{background:#3d4d66;color:#dbe4ef}
.ph-off{background:#55617a;color:#e6ecf4}
.wrap{padding:var(--pad);max-width:960px;margin:0 auto}
.back{display:inline-flex;align-items:center;min-height:34px;font-size:13px;font-weight:700;margin-bottom:10px}
.idx{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:11px 13px;margin-bottom:12px;
 font-variant-numeric:tabular-nums;font-size:14px}
.idx b{font-size:19px} .idx i{font-style:normal;font-weight:700}
.up{color:var(--up)} .dn{color:var(--dn)}
h2.s{margin:16px 0 9px;font-size:clamp(15px,4.2vw,19px);padding-left:9px;border-left:3px solid var(--acc)}
.alerts{background:#fff6f4;border:1px solid #f0cdc4;border-radius:var(--r);padding:10px 13px;margin-bottom:12px;font-size:13.5px}
.alerts ul{margin:6px 0 0;padding-left:19px} .alerts li{margin-bottom:3px}
.alerts .t{display:inline-block;min-width:22px;text-align:center;border-radius:5px;font-size:11px;font-weight:800;
 padding:0 4px;margin-right:6px;color:#fff}
.t-買{background:var(--up)} .t-賣{background:var(--dn)} .t-警{background:#b25e00} .t-時{background:#5b4bbd}
.cards{display:grid;gap:10px}
.cd{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:12px 13px}
.cnm{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;margin-bottom:7px}
.cnm b{font-size:17px} .cnm .cd-c{color:var(--ink3);font-size:13px;font-variant-numeric:tabular-nums}
.sc{margin-left:auto;font-size:12px;color:var(--ink3);font-weight:700}
.pxr{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;font-variant-numeric:tabular-nums;
 padding-bottom:8px;border-bottom:1px solid var(--line);margin-bottom:8px}
.pxr .p{font-size:25px;font-weight:800;line-height:1.1}
.pxr .d{font-size:14.5px;font-weight:700}
.pxr .x{font-size:12px;color:var(--ink3)}
.act{display:grid;gap:2px 9px;grid-template-columns:44px minmax(0,1fr);margin-bottom:7px}
.act:last-child{margin-bottom:0}
.act .k{grid-column:1;font-size:11.5px;font-weight:800;color:#fff;border-radius:6px;text-align:center;
 align-self:start;padding:3px 0;margin-top:1px}
.act .k.ke{background:#3d4d66} .act .k.kh{background:#2e6b4f}
.act .v{grid-column:2;font-size:14.5px;font-weight:800}
.act .w{grid-column:2;font-size:12.5px;color:var(--ink2);line-height:1.6}
.act .pv{grid-column:2;font-size:11.5px;color:var(--ink3);margin-bottom:1px}
.a-buy{color:var(--up)} .a-sell{color:var(--dn)} .a-cut{color:var(--dn)}
.a-warn{color:#b25e00} .a-wait{color:var(--ink2)} .a-no{color:var(--ink3)} .a-hold{color:var(--acc)}
.tp{margin-top:7px;padding:6px 9px;background:#f3f0ff;border:1px solid #ded6fb;border-radius:7px;
 font-size:12px;color:#4b3fa8;line-height:1.6}
.sim{margin-top:9px;padding:9px 10px;background:#f6f8fb;border:1px dashed #c3cfdf;border-radius:8px}
.sim .sh{display:flex;flex-wrap:wrap;align-items:baseline;gap:7px;margin-bottom:7px;font-size:11.5px;color:var(--ink3)}
.sim .sh b{font-size:12.5px;color:var(--ink2)}
.simrow{display:flex;gap:7px;align-items:center}
.simrow input{flex:1;min-width:0;max-width:190px;border:1px solid var(--line);border-radius:7px;
 padding:7px 10px;font-size:16px;font-variant-numeric:tabular-nums;background:#fff;color:var(--ink)}
.simrow input:focus{outline:2px solid var(--acc);outline-offset:-1px;border-color:var(--acc)}
.simx{border:1px solid var(--line);background:#fff;color:var(--ink3);border-radius:7px;
 padding:7px 12px;font-size:12.5px;cursor:pointer;min-height:36px}
.simout{margin-top:7px;line-height:1.65}
.simstat{font-size:12.5px;font-variant-numeric:tabular-nums;color:var(--ink2);margin-bottom:3px}
.simadv{font-size:13.5px;font-weight:800}
.simadv .sw{display:block;font-weight:400;font-size:12.5px;color:var(--ink2);margin-top:1px}
.simwarn{margin-top:4px;font-size:12px;color:#b25e00}
/* ★ MySelf 專屬：實際持倉（守則第 20.4 節）*/
.sum{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:11px 13px;margin-bottom:12px}
.sum .st{font-size:12px;color:var(--ink3);margin-bottom:6px}
.sum .sg{display:grid;gap:7px 12px;grid-template-columns:repeat(2,minmax(0,1fr));font-variant-numeric:tabular-nums}
.sum .sg>div{min-width:0}
.sum .sg span{display:block;font-size:11.5px;color:var(--ink3)}
.sum .sg b{font-size:16px;font-weight:800}
.sum .todo{margin-top:8px;padding-top:7px;border-top:1px solid var(--line);font-size:12.5px;color:var(--ink2)}
.pos{margin-top:8px;padding:8px 10px;background:#f2f7fb;border:1px solid #cddff0;border-radius:8px;
 font-size:12.5px;line-height:1.7;font-variant-numeric:tabular-nums}
.pos .ph2{font-size:11.5px;color:var(--ink3);margin-bottom:2px}
.pos .pw{margin-top:4px;font-size:12.5px;font-weight:800}
.pos .pn{margin-top:4px;padding:5px 8px;background:#fff8ec;border:1px solid #e8d5a8;border-radius:6px;
 font-size:11.5px;font-weight:400;color:#7a5200;line-height:1.6}
.t-倉{background:#1f5fa9}
@media(min-width:640px){.sum .sg{grid-template-columns:repeat(4,minmax(0,1fr))}}
.foot{margin-top:16px;padding:12px 13px;background:#eef1f5;border:1px solid var(--line);border-radius:var(--r);
 font-size:11.5px;color:var(--ink3);line-height:1.75}
.foot h3{margin:0 0 4px;font-size:12.5px;color:var(--ink2)}
.foot p{margin:0 0 7px} .foot p:last-child{margin:0}
@media(min-width:640px){:root{--pad:16px} .act{grid-template-columns:52px minmax(0,1fr)}}
@media(min-width:1000px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
"""

# ── 成本模擬（純前端計算；輸入值存 localStorage，頁面重產後仍保留）──────
# ★ 這段是 JS 原始碼，輸出時不經過 % 格式化，內含 % 字元無妨。
SIM_JS = """<script>
(function(){
"use strict";
var FEE=1.00585; // 買賣手續費各 0.1425% ＋ 證交稅 0.3%
function n1(x){return (x>=0?"+":"")+x.toFixed(1);}
function f2(x){return x.toLocaleString("zh-Hant-TW",{minimumFractionDigits:2,maximumFractionDigits:2});}
function money(x){return (x>=0?"+":"-")+Math.abs(Math.round(x)).toLocaleString("zh-Hant-TW");}
function kls(x){return x>0?"up":(x<0?"dn":"");}
function advise(d,cost,px){
  var ret=(px/cost-1)*100, be=cost*FEE;
  var ma5=parseFloat(d.ma5)||null, ma20=parseFloat(d.ma20)||null;
  var sz0=d.sz0?parseFloat(d.sz0):null, slab=d.slab, szone=d.szone;
  var dist=(sz0&&px<sz0)?("距"+slab+"下緣 "+f2(sz0)+" 元還有 "+n1((sz0/px-1)*100)+"%。"):"";
  var cls,act,why;
  if(d.hk==="h-exit"||d.hk==="h-cut"){
    var verb=d.hk==="h-exit"?"出場":"減碼";
    if(ret>=0){cls="a-sell";act="尚有獲利 "+n1(ret)+"%，趁獲利依日報建議"+verb;
      why="日報結論已是「"+verb+"」，持有成本再低也不改變趨勢轉弱的判斷；趁還有獲利執行，優於之後被迫停損。";}
    else{cls="a-cut";act="已虧損 "+n1(ret)+"%，仍應依日報建議"+verb+"，別等回本";
      why="損益兩平價 "+f2(be)+" 元只是你的成本記號，不是技術支撐；"+verb+"的理由與你的成本無關，凹單只會擴大虧損。";}
  }else if(sz0!==null&&px>=sz0){
    if(ret>0){cls="a-sell";act="已進"+slab+"且獲利 "+n1(ret)+"%，分批停利";
      why="價格已在 "+szone+" 內，獲利入袋優先；其餘部位依原訂移動停利條件。";}
    else{cls="a-warn";act="價格已到"+slab+"，但你仍虧損 "+n1(ret)+"%——視為減損出場機會";
      why="成本比"+slab+"還高，別為了回本而凹單；依原訂條件處理"+(ma5?"，跌破 5 日線 "+f2(ma5)+" 元先減碼":"")+"。";}
  }else if(ret<=-10){
    if(ma20&&px<ma20){cls="a-cut";act="虧損 "+n1(ret)+"% 且已破月線，建議分批停損";
      why="虧損超過 10% 停損紀律，月線 "+f2(ma20)+" 元也已失守；攤平或等反彈只會擴大風險。";}
    else{cls="a-cut";act="虧損 "+n1(ret)+"% 已觸停損紀律，月線失守即出";
      why="一般停損紀律為 -10%"+(ma20?"；月線 "+f2(ma20)+" 元是最後防線，跌破不要再等":"")+"。";}
  }else if(ret<=-5){
    cls="a-warn";act="虧損 "+n1(ret)+"%，進入警戒區";
    why=(ma20?"先守月線 "+f2(ma20)+" 元；":"")+"虧損擴大到 10% 就應執行停損，別讓小虧變大虧。"+dist;
  }else if(ret<0){
    cls="a-hold";act="小幅虧損 "+n1(ret)+"%，依上方原建議操作";
    why="損益兩平價約 "+f2(be)+" 元（含費）。"+dist;
  }else if(ret<5){
    cls="a-hold";act="小幅獲利 "+n1(ret)+"%，續抱等"+slab;
    why="可把防守價設在損益兩平 "+f2(be)+" 元附近，避免由盈轉虧。"+dist;
  }else if(ret<15){
    cls="a-hold";act="獲利 "+n1(ret)+"%，續抱等"+slab+"，防守價上移";
    why="防守價可上移到 "+f2(Math.max(ma5||0,be))+" 元（5 日線與損益兩平取高者），鎖住既有獲利。"+dist;
  }else{
    cls="a-sell";act="獲利已達 "+n1(ret)+"%，可先分批停利，不必等"+slab;
    why="雖未進 "+szone+"，但保護獲利優先——先出一部分，其餘依原訂移動停利條件。"+dist;
  }
  return {ret:ret,be:be,cls:cls,act:act,why:why};
}
document.querySelectorAll(".sim").forEach(function(el){
  var d=el.dataset, inp=el.querySelector("input"), out=el.querySelector(".simout"),
      clr=el.querySelector(".simx"), key="livecost:"+d.c, px=parseFloat(d.px);
  function render(){
    var cost=parseFloat(inp.value);
    if(!(cost>0)||!(px>0)){out.hidden=true;try{localStorage.removeItem(key);}catch(e){}return;}
    try{localStorage.setItem(key,inp.value);}catch(e){}
    var r=advise(d,cost,px), pl=(px-cost)*1000;
    var html='<div class="simstat">報酬率 <b class="'+kls(r.ret)+'">'+n1(r.ret)+'%</b>　'
      +'每張帳面損益 <b class="'+kls(pl)+'">'+money(pl)+' 元</b>　'
      +'含費損益兩平 '+f2(r.be)+' 元</div>'
      +'<div class="simadv '+r.cls+'">'+r.act+'<span class="sw">'+r.why+'</span></div>';
    if(cost>px*4||cost<px/4)html+='<div class="simwarn">⚠ 成本與現價差距超過 4 倍，'
      +'請確認是否輸入錯誤（例如把總金額當成每股成本）。</div>';
    out.innerHTML=html;out.hidden=false;
  }
  inp.addEventListener("input",render);
  clr.addEventListener("click",function(){inp.value="";render();});
  // ★ MySelf 專屬：inputs/positions.py 已把真實每股成本預填進 value，
  //   因此 localStorage 沒存過也要算一次（原版只在 localStorage 有值時才算）。
  try{var s=localStorage.getItem(key);if(s){inp.value=s;}}catch(e){}
  if(inp.value){render();}
});
})();
</script>"""

A = [].append
H = []


def w(s):
    H.append(s)


w('<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">')
w('<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">')
w('<meta name="color-scheme" content="light">')
w('<meta name="robots" content="noindex">')
w('<meta name="description" content="當日即時投資建議 — 以最新一期日報的買賣區間比對即時報價，只給操作動作">')
w("<title>當日即時投資建議｜%s</title>" % C.TITLE)
w("<style>%s</style>\n</head>\n<body>" % CSS)

w('<header class="hd"><div class="hdin">')
w("<h1>當日即時投資建議</h1>")
w('<p><span class="ph %s">%s</span>報價時間 %s（%s・來源 %s）　依據 <b>%s（%s收盤）</b>日報的買賣區間</p>'
  % (PHASE_CLS, PHASE, QT.strftime("%m/%d %H:%M"),
     ("約 %d 分鐘前" % LAG) if LAG >= 1 else "即時",
     SRC_LABEL, C.BASE_DATE, C.BASE_WEEKDAY))
w("</div></header>")
w('<div class="wrap">')
w('<a class="back" href="../index.html">← 回首頁</a>')

if STALE:
    w('<div class="alerts"><b>⚠ 目前取得的報價仍是 %s 的收盤價</b>，'
      '尚未有新一日的行情（可能是尚未開盤或休市）。下方的動作等同日報結論，'
      '待開盤後重新執行即可更新。</div>' % C.BASE_DATE)

if QI:
    ip = num(QI, "regularMarketPrice")
    ipc = num(QI, "previousClose", "chartPreviousClose")
    ic = (ip - ipc) if (ip is not None and ipc is not None) else None
    icp = (ic / ipc * 100) if (ic is not None and ipc) else None
    k = "up" if (ic or 0) > 0 else ("dn" if (ic or 0) < 0 else "")
    w('<div class="idx">%s　<b>%s</b>　<i class="%s">%s（%s%%）</i>　'
      '<span style="color:var(--ink3)">日報環境分 %d</span></div>'
      % (C.INDEX_NAME, fmt(ip), k,
         ("%+.2f" % ic) if ic is not None else "查無",
         ("%+.2f" % icp) if icp is not None else "查無", MK.ENV_SCORE))

# ★ MySelf 專屬：投資組合合計（守則第 20.4 節）
_ph = [r for r in ROWS if r.get("pos")]
if _ph:
    _cv = sum(r["pos"]["cost_val"] for r in _ph)
    _mv = sum(r["pos"]["mkt_val"] for r in _ph)
    _pl = _mv - _cv
    _k = "up" if _pl > 0 else ("dn" if _pl < 0 else "")
    _todo = ["%s %s %g 張" % (r["name"], r["plan"]["title"], r["plan"]["lots"])
             for r in _ph if r.get("plan") and r["plan"]["act"] in ("exit", "trim")]
    w('<div class="sum">')
    w('<div class="st">你的投資組合（持倉來源：%s，%s）</div>' % (POS_SRC, POS_AS_OF))
    w('<div class="sg">'
      '<div><span>投入成本</span><b>%s</b></div>'
      '<div><span>目前市值</span><b>%s</b></div>'
      '<div><span>未實現損益</span><b class="%s">%s</b></div>'
      '<div><span>報酬率</span><b class="%s">%+.2f%%</b></div>'
      '</div>'
      % ("{:,.0f}".format(_cv), "{:,.0f}".format(_mv), _k,
         mny(_pl), _k, (_pl / _cv * 100) if _cv else 0.0))
    if _todo:
        w('<div class="todo"><b>待處理：</b>%s'
          '<br><span style="color:var(--ink3);font-size:11.5px">'
          '★ 張數是把日報訂好的區間規則套到實際持倉的算術結果，不是新的判斷；'
          '加碼張數一律不算（分母是可動用資金，程式不知道）。</span></div>'
          % "、".join(_todo))
    w("</div>")

if ALERTS:
    w('<div class="alerts"><b>需要注意（%d 項）</b><ul>' % len(ALERTS))
    for c, t, s in ALERTS:
        w('<li><span class="t t-%s">%s</span>%s %s——%s</li>' % (t, t, C.NAME[c], c, s))
    w("</ul></div>")

w('<h2 class="s">各檔操作動作（依日報綜合分排序）</h2>')
w('<div class="cards">')
for r in ROWS:
    k = "up" if (r["chg"] or 0) > 0 else ("dn" if (r["chg"] or 0) < 0 else "")
    w('<div class="cd">')
    w('<div class="cnm"><b>%s</b><span class="cd-c">%s</span>'
      '<span class="sc">日報 %d 分・%s</span></div>' % (r["name"], r["c"], r["tot"], r["band"]))
    w('<div class="pxr"><span class="p %s">%s</span>'
      '<span class="d %s">%s（%s%%）</span>'
      '<span class="x">高 %s／低 %s　量 %s 張（約當 20 日均量 %s）　站上 %d/6 條均線</span></div>'
      % (k, fmt(r["px"]), k,
         ("%+.2f" % r["chg"]) if r["chg"] is not None else "查無",
         ("%+.2f" % r["chgp"]) if r["chgp"] is not None else "查無",
         fmt(r["hi"]), fmt(r["lo"]), fmt(r["lots"], 0),
         ("%.0f%%" % (r["vr"] * 100)) if r["vr"] is not None else "查無", r["up_ma"]))
    w('<div class="act"><span class="k ke">空手</span>'
      '<span class="pv">日報建議：%s %s</span>'
      '<span class="v %s">%s</span><span class="w">%s</span></div>'
      % (r["e_ico"], r["e_lab"], r["e_cls"], r["e_act"], r["e_why"]))
    w('<div class="act"><span class="k kh">持有</span>'
      '<span class="pv">日報建議：%s %s</span>'
      '<span class="v %s">%s</span><span class="w">%s</span></div>'
      % (r["h_ico"], r["h_lab"], r["h_cls"], r["h_act"], r["h_why"]))
    # ★ MySelf 專屬：持倉列與「換算張數」（守則第 20.4 節，排在空手／持有之後，不取代它們）
    if r.get("pos"):
        _p, _pn = r["pos"], r.get("plan")
        _k2 = "up" if _p["pl"] > 0 else ("dn" if _p["pl"] < 0 else "")
        w('<div class="pos">')
        w('<div class="ph2">你的部位</div>')
        w('%g 張・成本 %s　現值 %s　未實現 <b class="%s">%s（%+.2f%%）</b>'
          % (_p["lots"], fmt(_p["cost"]), "{:,.0f}".format(_p["mkt_val"]),
             _k2, mny(_p["pl"]), _p["pl_pct"]))
        if _pn:
            if _pn["act"] in ("exit", "trim"):
                w('<div class="pw">上方「持有」＝%s，換算成 %g 張'
                  '（共 %g 張，留 %g 張）；以現價 %s 元計，這 %g 張實現 %s 元</div>'
                  % (_pn["title"], _pn["lots"], _pn["n_lots"], _pn["n_lots"] - _pn["lots"],
                     fmt(r["px"]), _pn["lots"], mny(_pn.get("realized"))))
            elif _pn["act"] == "trail":
                w('<div class="pw">上方「持有」＝%s，%g 張不動（帶量突破，不機械式賣光）</div>'
                  % (_pn["title"], _pn["n_lots"]))
            elif _pn["act"] == "addzone":
                w('<div class="pw">現價在加碼區間 %s – %s 元內（每 1 張約需 %s 元），'
                  '加幾張由你自己決定</div>'
                  % (fmt(_pn["buy_lo"]), fmt(_pn["buy_hi"]), "{:,.0f}".format(_pn["unit"] or 0)))
            else:
                w('<div class="pw">上方「持有」＝%s，%g 張不動%s</div>'
                  % (_pn["title"], _pn["n_lots"],
                     ("　·　距解套價 %s 元還要漲 %.1f%%"
                      % (fmt(_pn["breakeven"]), (_pn["breakeven"] / r["px"] - 1) * 100))
                     if (r["px"] and _pn["breakeven"] > r["px"]) else ""))
            if _pn.get("note"):
                w('<div class="pn">⚠ %s</div>' % _pn["note"])
        w("</div>")

    ga = lambda v: "" if v is None else ("%g" % v)
    w('<div class="sim" data-c="%s" data-px="%s" data-sz0="%s" data-sz1="%s" '
      'data-ma5="%s" data-ma20="%s" data-hk="%s" data-slab="%s" data-szone="%s">'
      '<div class="sh"><b>💰 成本模擬</b><span>%s</span></div>'
      '<div class="simrow"><input type="number" inputmode="decimal" step="any" min="0" '
      'placeholder="每股成本（元）" aria-label="%s 持有成本"%s>'
      '<button type="button" class="simx">清除</button></div>'
      '<div class="simout" hidden></div></div>'
      % (r["c"], ga(r["px"]), ga(r["sz0"]), ga(r["sz1"]),
         ga(r["ma5"]), ga(r["ma20"]), r["hk"], r["slab"], r["szone"],
         # ★ MySelf 專屬：有真實持倉者用 inputs/positions.py 的每股成本預填，載入即算
         ("已用 inputs/positions.py 的實際成本 %.2f 元預填，可改成別的數字試算（不改變上方日報建議）"
          % r["cost"]) if r.get("cost") else
         "輸入你的每股成本，看對「你的部位」的模擬建議（不改變上方日報建議）",
         r["name"],
         (' value="%.2f"' % r["cost"]) if r.get("cost") else ""))
    if r["tp"]:
        w('<div class="tp"><b>⏳ 時間壓力</b>：%s</div>' % r["tp"])
    w("</div>")
w("</div>")

w('<div class="foot"><h3>這頁在做什麼</h3>'
  '<p>把 <b>%s 日報</b>訂下的買賣區間與條件，拿去比對<b>當下的報價</b>，只輸出「現在該做什麼」。'
  '均線、布林通道、20 日均量等技術位一律沿用日報基準日的收盤計算值，<b>不用盤中未完成的 K 棒重算</b>；'
  '頁面上只有價格、漲跌、成交量是即時的。判斷邏輯固定：'
  '價格落在買進區間內＝可分批買、高於區間＝等回檔、跌破區間下緣＝支撐失守先別接；'
  '持有則依序檢查是否進入停利／減碼／出場區間、是否跌破月線、是否跌破 5 日線。</p>'
  '<h3>成本模擬怎麼算</h3>'
  '<p>各卡片的「成本模擬」只在你的瀏覽器內計算（輸入值存在本機瀏覽器，頁面重新產生後仍保留，不會上傳）。'
  '報酬率＝現價÷成本−1；每張帳面損益＝（現價−成本）×1,000，未含費用；'
  '損益兩平價＝成本×1.00585（買賣手續費各 0.1425%% 加證交稅 0.3%%）。'
  '模擬規則：日報已判「減碼／出場」者不因成本高低翻案；'
  '獲利且已進停利區＝分批停利、獲利達 15%% 可提前部分停利、'
  '虧損 5%% 進入警戒、虧損 10%% 觸及停損紀律（並以月線為最後防線）。此為規則式試算，非投資建議。</p>'
  '<h3>報價來源與延遲</h3>'
  '<p>Yahoo Finance 即時報價（%s），台股報價通常有數分鐘至 15 分鐘延遲，'
  '成交量為當日累計。本頁每次執行都會整份覆蓋，不保留歷史。</p>'
  '<h3>免責聲明</h3>'
  '<p>本頁由自動化流程產生，僅供研究與教育參考，不構成投資建議、要約或招攬，'
  '亦不保證資料之完整性、即時性與正確性。實際下單前請自行以券商報價複核價格，'
  '投資有風險，讀者應自行判斷並承擔所有投資決策之後果。</p></div>'
  % (C.BASE_DATE, QT.strftime("%Y-%m-%d %H:%M")))

w('</div>\n<p style="text-align:center;color:#7a8798;font-size:11.5px;margin:14px 0 20px">'
  '產生時間 %s（台北時間）</p>' % NOW.strftime("%Y-%m-%d %H:%M"))
w(SIM_JS)
w("</body>\n</html>")

os.makedirs(LIVE_DIR, exist_ok=True)
lp = os.path.join(LIVE_DIR, "index.html")
open(lp, "w", encoding="utf-8", newline="\n").write("\n".join(H) + "\n")
print("\n0) 報價來源：%s，報價時間 %s（延遲 %d 分鐘）"
      % (SRC_LABEL, QT.strftime("%m/%d %H:%M"), LAG))
print("1) live/index.html 已覆蓋，%d 檔、%d 項提醒" % (len(ROWS), len(ALERTS)))

meta = {"quote_time": QT.strftime("%Y-%m-%d %H:%M"), "gen_time": NOW.strftime("%Y-%m-%d %H:%M"),
        "phase": PHASE, "base_date": C.BASE_DATE, "alerts": len(ALERTS),
        "source": SRC_LABEL, "lag_min": LAG, "delayed": DELAYED}
json.dump(meta, open(os.path.join(D, "live_meta.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ── 同步首頁按鈕上的時間戳（不動其他內容）──────────────────────────
home = os.path.join(C.REPO, "index.html")
if os.path.exists(home):
    s = open(home, encoding="utf-8").read()
    lab = "%s · %s" % (PHASE, QT.strftime("%H:%M"))
    s2 = re.sub(r'(<span class="lvt">).*?(</span>)', r"\g<1>" + lab + r"\g<2>", s, count=1)
    if s2 != s:
        open(home, "w", encoding="utf-8").write(s2)
        print("2) 首頁即時按鈕時間戳已更新：%s" % lab)
    elif '<span class="lvt">' in s:
        print("2) 首頁即時按鈕時間戳已是最新：%s" % lab)
    else:
        print("2) 首頁尚無即時按鈕（跑一次 finalize.py 即會產生）")

print("\n各檔動作：")
for r in ROWS:
    print("    %s %-8s %8s  空手 %-28s 持有 %s"
          % (r["c"], r["name"], fmt(r["px"]), r["e_act"], r["h_act"]))
