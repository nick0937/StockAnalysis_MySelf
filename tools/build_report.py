# -*- coding: utf-8 -*-
"""產生個股報告 HTML → REPO/YYYYMMDD/index.html
   ★ 移植時不用改這個檔案。版面規格見 ../報告守則.md 第 11 節。

   讀取：
     ../報告樣式.css                完整樣式（整段內嵌，單一自足）
     data/indicators.json           行情與技術指標（calc_indicators.py 產生）
     data/fin.json                  財報衍生指標（calc_fin.py 產生）
     inputs/chips.py                籌碼（法人10/資券10/主力10/大戶13）
     inputs/monthly.py              月營收 12 期
     inputs/market.py               大盤判讀與建議書文字
     inputs/scores.py               五面向小分、基本面拆解、雙情境標籤
     inputs/zones.py                買賣區間與觸發條件
     inputs/shorts.py               各檔概述文字
"""
import json, os, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "inputs"))
import config as C
from lib import (n, cm, sgn, cls, num_td, band_of, scls, total_score, market_score,
                 spark, mc, twrap, mabar, chip, opbox, MA_LABEL)
import market as MK
from scores import S, FUND, ADV
from zones import ZONE
from shorts import EMPTY_S, HOLD_S, OPS_S, TGT_S
from monthly import MONTHLY, MNOTE
from chips import out as CHIP
from q2est import Q2EST, NOQ2

D = os.path.join(BASE, "data")
IND = json.load(open(os.path.join(D, "indicators.json"), encoding="utf-8"))
FIN = json.load(open(os.path.join(D, "fin.json"), encoding="utf-8"))
CSS = open(os.path.join(os.path.dirname(BASE), "報告樣式.css"), encoding="utf-8").read()

GEN_TIME = datetime.datetime.now().strftime("%Y-%m-%d %H:%M") + "（台北時間）"
BD, WD = C.BASE_DATE, C.BASE_WEEKDAY

# ── 大盤面分一律由公式計算，覆寫 inputs 中的值（避免主觀給分）──
for c in C.CODES:
    rs = IND["stocks"][c]["rs"]
    S[c] = (S[c][0], S[c][1], S[c][2], market_score(MK.ENV_SCORE, rs), S[c][4])
TOT = {c: total_score(S[c]) for c in C.CODES}
RANK = sorted(C.CODES, key=lambda c: -TOT[c])

O = []
A = O.append
idx = IND["idx"]
amt_t = MK.IDX_AMOUNT[BD] / 1e8
amt_y = sorted(MK.IDX_AMOUNT.items())[-2][1] / 1e8
vol_t = MK.IDX_VOLUME[BD] / 1000

# ══════════════════════════════════════════════ head
A('<!DOCTYPE html>\n<html lang="zh-Hant"><head>\n<meta charset="utf-8">')
A('<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">')
A('<meta name="color-scheme" content="light">')
A('<meta name="description" content="%s">' % C.DESC_TMPL.format(base_date=BD, n=len(C.CODES)))
A('<title>%s %s</title>' % (C.TITLE, BD))
A('<style>%s</style>' % CSS)
A('</head><body>')

# ══════════════════════════════════════════════ nav（★ 必須是 ul>li>a）
A('<nav class="nav"><ul>'
  '<li><a href="#market">大盤</a></li><li><a href="#overview">總覽</a></li>'
  '<li><a href="#stocks">各個股</a></li><li><a href="#advice">建議書</a></li>'
  '</ul></nav>')

# ══════════════════════════════════════════════ 標題區（精簡：4 格摘要卡＋一行指引）
A('<header id="top" class="hero"><h1>%s</h1>' % C.TITLE)
A('<div class="meta">'
  '<div><span>資料基準日</span><b>%s（%s收盤）</b></div>'
  '<div><span>產出時間</span><b>%s</b></div>'
  '<div><span>追蹤標的</span><b>%d 檔</b></div>'
  '<div><span>五面向權重</span><b>%s</b></div>'
  '</div>' % (BD, WD, GEN_TIME, len(C.CODES),
              "／".join("%s%s" % (w[0][:2], w[1].rstrip("%")) for w in C.WEIGHTS)))
A('<p class="hint">詳細內容（籌碼四表、月營收與 EPS、判斷理由、完整操作條件）請點'
  '<a href="#overview">總覽</a>中的個股名稱進入卡片；資料來源與完整性說明見'
  '<a href="#advice">文末建議書</a>。%s</p></header>'
  % (("<br>⚠ " + C.RERUN_NOTE) if C.RERUN_NOTE else ""))

# ══════════════════════════════════════════════ 大盤（只留指標）
A('<section id="market" class="card mkt">')
A('<h2 class="cnm">大盤趨勢｜%s <span class="px %s">%s</span> '
  '<span class="pchg %s">%s（%s）</span></h2>'
  % (C.INDEX_NAME, cls(idx["chg"]), cm(idx["close"], 2), cls(idx["chg"]),
     sgn(idx["chg"]), sgn(idx["chg_pct"], 2, True)))
A('<h3 class="sh">大盤指標</h3><div class="grid">')
pos = sum(1 for _, m in MK.ENV_ITEMS if m == "+")
A(mc("大盤環境分", "%d<br><small>六項中 %d 正 %d 負</small>"
     % (MK.ENV_SCORE, pos, len(MK.ENV_ITEMS) - pos)))
A(mc("收盤", cm(idx["close"], 2), cls(idx["chg"])))
A(mc("漲跌", "%s（%s）" % (sgn(idx["chg"]), sgn(idx["chg_pct"], 2, True)), cls(idx["chg"])))
A(mc("成交金額（億元）", "%s<br><small>前一日 %s（%s）</small>"
     % (cm(amt_t, 2), cm(amt_y, 2), sgn((amt_t / amt_y - 1) * 100, 2, True))))
A(mc("KD(9,3,3)", "K %s / D %s<br><small>前日 K %s / D %s</small>"
     % (n(idx["k"]), n(idx["d"]), n(idx["k_prev"]), n(idx["d_prev"]))))
A(mc("RSI(14)", "%s<br><small>前日 %s</small>" % (n(idx["rsi"]), n(idx["rsi_prev"]))))
A(mc("MACD", "DIF %s<br>DEA %s<br>柱 %s<small>（前日 %s／前二日 %s）</small>"
     % (n(idx["dif"], 1), n(idx["dea"], 1), n(idx["osc"], 1),
        n(idx["osc_prev"], 1), n(idx["osc_prev2"], 1))))
A(mc("乖離率", "20日 %s<br>60日 %s"
     % (sgn(idx["bias20"], 2, True), sgn(idx["bias60"], 2, True))))
A(mc("52週高／低", "%s / %s<br><small>距高點 %s</small>"
     % (cm(idx["hi52"], 2), cm(idx["lo52"], 2), sgn(idx["from_hi52"], 2, True))))
A(mc("報酬率", "1月 %s<br>3月 %s<br>6月 %s<br>1年 %s"
     % (sgn(idx["r20"], 2, True), sgn(idx["r60"], 2, True),
        sgn(idx["r120"], 2, True), sgn(idx["r240"], 2, True))))
A(mc("今年以來", sgn(idx["ytd"], 2, True), cls(idx["ytd"])))
A('</div>')
A('<h3 class="sh">六條均線位置</h3>' + mabar(idx))
A('<h3 class="sh">趨勢判讀</h3>')
A('<p class="para">%s<br><small>環境分組成：%s（六項中 %d 正 %d 負）。'
  '櫃買指數 %s 收 %s；%s</small></p>'
  % (MK.TREND.format(env=MK.ENV_SCORE),
     "、".join("%s%s" % (k, v) for k, v in MK.ENV_ITEMS),
     pos, len(MK.ENV_ITEMS) - pos, BD[5:].replace("-", "/"), n(MK.OTC_CLOSE), MK.OTC_NOTE))
A('<a class="top" href="#top">↑ 回頂端</a></section>')

# ══════════════════════════════════════════════ 總覽排名
A('<section id="overview" class="card"><h2 class="sect">總覽排名</h2>')

def band_label():
    """把 config.BANDS 轉成「≥70 買進｜55–69 觀察偏多｜45–54 觀察｜&lt;45 減碼／賣出」"""
    out = []
    for i, (lo, nm_) in enumerate(C.BANDS):
        if i == 0:
            out.append("≥%d %s" % (lo, nm_))
        elif lo == 0:
            out.append("&lt;%d %s" % (C.BANDS[i - 1][0], nm_))
        else:
            out.append("%d–%d %s" % (lo, C.BANDS[i - 1][0] - 1, nm_))
    return "｜".join(out)


A('<p class="para small">綜合分對照：%s。</p>' % band_label())
A('<div class="legend"><span class="lgt">標籤讀法：顏色深淺代表<b>該採取行動的急迫性</b>，不是好壞</span>'
  '<span class="lgrow"><u>空手</u>%s%s%s%s</span>'
  '<span class="lgrow"><u>持有</u>%s%s%s%s</span></div>'
  % (chip("e-go", "●", "可買進"), chip("e-part", "◎", "分批買進"),
     chip("e-wait", "○", "等回檔再買"), chip("e-no", "✕", "不建議買進"),
     chip("h-keep", "✓", "續抱"), chip("h-tp", "✓", "續抱並設停利"),
     chip("h-cut", "▼", "逢高減碼"), chip("h-exit", "✕", "近期出場")))
A('<div class="ovt"><div class="ovh"><span class="o-rk">排名</span><span class="o-nm">個股</span>'
  '<span class="o-px">收盤</span><span class="o-cg">漲跌%</span><span class="o-sc">綜合</span>'
  '<span class="o-ev">空手</span><span class="o-hv">持有</span></div>')
for i, c in enumerate(RANK, 1):
    a, sc, z = IND["stocks"][c], TOT[c], ZONE[c]
    ec, ei, et, hc, hi_, ht = ADV[c]
    nobuy = z["buy_zone"].startswith("暫不")
    A('<article class="ovr"><span class="o-rk">#%d</span>'
      '<span class="o-nm"><a href="#s%s">%s<em>%s</em></a></span>'
      '<span class="o-px %s">%s</span><span class="o-cg %s">%s</span>'
      '<span class="o-sc"><b class="%sb">%d</b><s>%s</s></span>'
      '<span class="o-ev"><span class="ol">空手</span>%s'
      '<span class="ol">%s</span><span class="ozn">%s</span></span>'
      '<span class="o-hv"><span class="ol">持有</span>%s'
      '<span class="ol">%s</span><span class="ozn">%s</span></span></article>'
      % (i, c, a["name"], c, cls(a["chg"]), n(a["close"]), cls(a["chg"]),
         sgn(a["chg_pct"], 2, True), scls(sc), sc, band_of(sc),
         chip(ec, ei, et), "買點" if nobuy else "買進", z["buy_zone"],
         chip(hc, hi_, ht), z["sell_lab"].replace("區間", ""), z["sell_zone"]))
A('</div>')
A('<p class="tnote">價位區間端點錨定<b>實際技術價位</b>（均線、布林軌、前波關鍵價），非主觀設定。'
  '完整的觸發條件、錨點來源、五面向小分與判斷理由，請點個股名稱進入卡片。</p>')
A('<a class="top" href="#top">↑ 回頂端</a></section>')
A('<h2 class="sect" id="stocks" style="margin:var(--pad);scroll-margin-top:56px">各個股</h2>')

# ══════════════════════════════════════════════ 個股卡片（12 個固定區塊）
for c in RANK:
    a, f_, ch, sc = IND["stocks"][c], FIN[c], CHIP[c], TOT[c]
    mk, ind_, sym = C.MKT[c]
    A('<section id="s%s" class="card stk"><div class="chd">' % c)
    A('<h2 class="cnm"><a href="#s%s">%s<em>%s</em></a></h2>' % (c, a["name"], c))
    A('<div class="cpx"><span class="px %s">%s</span><span class="pchg %s">%s（%s）</span></div>'
      % (cls(a["chg"]), n(a["close"]), cls(a["chg"]), sgn(a["chg"]), sgn(a["chg_pct"], 2, True)))
    A('<div class="cspk">%s</div>' % spark(a["spark"]))
    A('<div class="ctag"><span class="tg">%s</span><span class="tg">%s</span><span class="tg">%s</span>'
      '<span class="vd %sv">%s %d</span></div></div>'
      % (mk, ind_, sym, scls(sc), band_of(sc), sc))

    # 1 股價與技術指標
    A('<h3 class="sh">股價與技術指標</h3><div class="grid">')
    A(mc("收盤", n(a["close"]), cls(a["chg"])))
    A(mc("漲跌", "%s（%s）" % (sgn(a["chg"]), sgn(a["chg_pct"], 2, True)), cls(a["chg"])))
    A(mc("開／高／低", "%s / %s / %s" % (n(a["open"]), n(a["high"]), n(a["low"]))))
    A(mc("成交量（張）", "%s<br><small>5日均 %s／20日均 %s</small>"
         % (cm(a["vol_lots"], 0), cm(a["v5"], 0), cm(a["v20"], 0))))
    A(mc("量比", n(a["vr20"]) + "<br><small>當日量 ÷ 20 日均量</small>",
         "up" if a["vr20"] and a["vr20"] >= 1 else ""))
    A(mc("KD(9,3,3)", "K %s / D %s<br><small>前日 K %s / D %s</small>"
         % (n(a["k"]), n(a["d"]), n(a["k_prev"]), n(a["d_prev"]))))
    A(mc("RSI(14)", "%s<br><small>前日 %s</small>" % (n(a["rsi"]), n(a["rsi_prev"]))))
    A(mc("MACD", "DIF %s<br>DEA %s<br>柱 %s<small>（前日 %s）</small>"
         % (n(a["dif"], 2), n(a["dea"], 2), n(a["osc"], 3), n(a["osc_prev"], 3))))
    A(mc("布林(20,2)", "上 %s<br>中 %s<br>下 %s<br><small>%%B %s</small>"
         % (n(a["bb_up"]), n(a["bb_mid"]), n(a["bb_dn"]), n(a["pb"]))))
    A(mc("乖離率", "20日 %s<br>60日 %s" % (sgn(a["bias20"], 2, True), sgn(a["bias60"], 2, True))))
    A(mc("52週高／低", "%s / %s<br><small>距高點 %s</small>"
         % (n(a["hi52"]), n(a["lo52"]), sgn(a["from_hi52"], 2, True))))
    A(mc("報酬率", "1月 %s<br>3月 %s<br>6月 %s<br>1年 %s"
         % (sgn(a["r20"], 2, True), sgn(a["r60"], 2, True),
            sgn(a["r120"], 2, True), sgn(a["r240"], 2, True))))
    A(mc("今年以來", sgn(a["ytd"], 2, True), cls(a["ytd"])))
    A(mc("收盤價交叉驗證", "Yahoo %s<br>玩股網 %s<br><small class=\"ok\">一致</small>"
         % (n(a["close"]), n(float(ch["main"][0][1])))))
    A('</div>')

    # 2 均線位置
    A('<h3 class="sh">均線位置</h3>' + mabar(a))

    # 3 法人動態
    A('<h3 class="sh">法人動態（近 %d 個交易日，單位：張）</h3>' % C.N_INST)
    r = ""
    for row in ch["inst"][:C.N_INST]:
        cells = "".join('<td class="num %s">%s</td>' % (cls(float(x or 0)), x or "0")
                        for x in row[1:7])
        rest = "".join('<td class="num">%s</td>' % (x if x else "查無") for x in row[7:])
        r += '<tr><td>%s</td>%s%s</tr>' % (row[0], cells, rest)
    A(twrap('<table><thead><tr><th>日期</th><th>外資(不含自營)</th><th>外資自營</th><th>投信</th>'
            '<th>自營自行</th><th>自營避險</th><th>總合</th><th>估計持股外資(張)</th><th>投信(張)</th>'
            '<th>自營(張)</th><th>三大法人合計(張)</th><th>外資持股比重%%</th>'
            '<th>三大法人持股比重%%</th></tr></thead><tbody>%s</tbody></table>' % r))
    A('<p class="tnote">買賣超欄位紅色為買超、綠色為賣超；持股張數與持股比重為中性數值不上色。'
      '已驗證五欄買賣超相加等於「總合」欄，%d 檔 × %d 日共 %d 列全數成立。</p>'
      % (len(C.CODES), C.N_INST, len(C.CODES) * C.N_INST))

    # 4 資券變化
    A('<h3 class="sh">資券變化（近 %d 個交易日）</h3>' % C.N_MARGIN)
    r = ""
    for row in ch["margin"][:C.N_MARGIN]:
        r += ('<tr><td>%s</td>%s%s%s%s%s%s%s%s%s%s</tr>'
              % (row[0], num_td(row[1]), num_td(row[2], True), num_td(row[3]),
                 num_td(row[4], True), num_td(row[5]), num_td(row[6]), num_td(row[7]),
                 num_td(row[8]), num_td(row[9], True), num_td(row[10])))
    A(twrap('<table><thead><tr><th>日期</th><th>資餘</th><th>資增</th><th>券餘</th><th>券增</th>'
            '<th>券資比%%</th><th>資券互抵</th><th>當沖率%%</th><th>收盤價</th><th>漲跌%%</th>'
            '<th>成交量</th></tr></thead><tbody>%s</tbody></table>' % r))
    mnote = ('僅資增、券增與漲跌% 套用漲跌配色；餘額、券資比與收盤價為中性數值。'
             '<b>最新列與行情基準日一致</b>——融資融券於當日 21:00 才公布，'
             '若在盤後不久產出會落後一日，需隔日補跑。')
    if ch["note"]:
        mnote += "<b>⚠ " + ch["note"] + "</b>"
    A('<p class="tnote">%s</p>' % mnote)

    # 5 主力進出
    A('<h3 class="sh">主力進出（近 %d 個交易日）</h3>' % C.N_MAIN)
    r = ""
    for row in ch["main"][:C.N_MAIN]:
        r += ('<tr><td>%s</td><td class="num">%s</td><td class="num %s">%s</td>'
              '<td class="num %s">%s</td><td class="num %s">%s</td><td class="num %s">%s</td></tr>'
              % (row[0], row[1], cls(float(row[2])), row[2],
                 cls(-float(row[3])), row[3],
                 cls(float(row[4].rstrip('%'))), row[4],
                 cls(float(row[5].rstrip('%'))), row[5]))
    A(twrap('<table><thead><tr><th>日期</th><th>收盤價</th><th>主力買賣超</th><th>家數差</th>'
            '<th>5日集中度%%</th><th>20日集中度%%</th></tr></thead>'
            '<tbody>%s</tbody></table>' % r))
    A('<p class="tnote">家數差為負值代表籌碼集中（較佳），故此欄以「負＝紅」呈現。'
      '收盤價為中性數值不上色。</p>')

    # 6 大戶籌碼
    A('<h3 class="sh">大戶籌碼（近 %d 週，約 3 個月）</h3>' % C.N_CONC)
    r = ""
    for row in ch["conc"][:C.N_CONC]:
        r += '<tr><td>%s</td>%s</tr>' % (row[0],
                                         "".join('<td class="num">%s</td>' % x for x in row[1:]))
    A(twrap('<table><thead><tr><th>日期</th><th>%s%%</th><th>外資持股%%</th><th>投信持股%%</th>'
            '<th>自營商持股%%</th><th>董監持股%%</th></tr></thead><tbody>%s</tbody></table>'
            % (ch["conc_threshold"], r)))
    thrs = sorted(set(v["conc_threshold"] for v in CHIP.values()))
    A('<p class="tnote">全部為持股比重，屬中性數值不套用漲跌配色。'
      '<b>⚠ 大戶門檻各檔不同，本檔為「%s」</b>'
      '（門檻由來源網站決定、會隨個股條件而異，本報告一律以該檔頁面實際顯示的門檻為準；'
      '本組合出現的門檻有 %s，<b>跨個股比較此欄位時務必先確認門檻是否相同</b>）。'
      '為週資料，區間 %s ~ %s（共 %d 週）。</p>'
      % (ch["conc_threshold"], "、".join(thrs),
         ch["conc"][C.N_CONC - 1][0], ch["conc"][0][0], C.N_CONC))

    # 7 月營收
    A('<h3 class="sh">月營收（近 %d 個月）</h3>' % C.N_MONTHLY)
    mr = ""
    for row in MONTHLY[c][:C.N_MONTHLY]:
        mr += ('<tr><td>%s</td><td class="num">%s</td><td class="num %s">%s</td>'
               '<td class="num %s">%s</td><td class="num %s">%s</td></tr>'
               % (row["ym"], n(row["rev"]), cls(row["yoy"]), sgn(row["yoy"], 2, True),
                  cls(row["mom"]), sgn(row["mom"], 2, True),
                  cls(row["cum"]), sgn(row["cum"], 2, True)))
    A(twrap('<table><thead><tr><th>年月</th><th>營收(億)</th><th>YoY</th><th>MoM</th>'
            '<th>累計 YoY</th></tr></thead><tbody>%s</tbody></table>' % mr, "tnarrow"))
    A('<p class="tnote">單位：億元（原始仟元）。來源：玩股網月營收（轉載公開資訊觀測站公告）。%s</p>'
      % MNOTE.get(c, ""))

    # 8 每股盈餘
    A('<h3 class="sh">每股盈餘（近 %d 季）</h3>' % C.N_EPS)
    er = ""
    for row in f_["inc"][:C.N_EPS]:
        er += ('<tr><td>%s</td><td class="num">%s</td><td class="num %s">%s</td></tr>'
               % (row["q"], n(row["eps"]), cls(row["eps_yoy"]),
                  sgn(row["eps_yoy"], 2, True) if row["eps_yoy"] is not None else "—"))
    A(twrap('<table><thead><tr><th>季別</th><th>單季 EPS（元）</th><th>EPS YoY</th></tr></thead>'
            '<tbody>%s</tbody></table>' % er, "tnarrow tn3"))
    en = "最新已公布季 <b>%s</b>，來源 Yahoo 奇摩股市。" % f_["latest_q"]
    if c in Q2EST:
        en += ("<b>補充 %s（公司已公告 H1、Yahoo 尚未更新，以 H1 減 Q1 推算）：單季 EPS %s 元。</b>%s"
               % (Q2EST[c]["q"], n(Q2EST[c]["eps"]), Q2EST[c].get("note", "")))
    if c in NOQ2:
        en += NOQ2[c]
    if f_["eps_adjusted"]:
        en += ("<b>⚠ 面額變更（1 股拆 %d 股）：跨基準日（%s）之前各季 EPS 已一律除以 %d 換算，"
               "EPS YoY 以調整後數值重算；Yahoo 頁面顯示的年增率未做此調整因而嚴重失真。</b>"
               % (f_["split"][1], f_["split"][0], f_["split"][1]))
    en += (" 近四季 EPS 合計 %s 元｜本益比 %s｜股價淨值比 %s。"
           % (n(f_["eps4"]) if f_["eps4"] else "查無",
              n(f_["pe"], 1) if f_["pe"] else "查無（近四季虧損）",
              n(f_["pb"]) if f_["pb"] else "查無"))
    A('<p class="tnote">%s</p>' % en)

    # 9 法人目標價
    A('<h3 class="sh">法人目標價</h3><p class="para tgt">%s</p>' % TGT_S[c])

    # 10 五面向評分
    A('<h3 class="sh">五面向評分</h3><div class="sbs">')
    for (lab, wtxt, _), v in zip(C.WEIGHTS, S[c]):
        A('<div class="sbr"><span class="sbl">%s<em>%s</em></span>'
          '<span class="sbt"><i class="%s" style="width:%d%%"></i></span>'
          '<span class="sbv">%d</span></div>' % (lab, wtxt, scls(v), v, v))
    A('<div class="sbr tot"><span class="sbl">綜合分數</span>'
      '<span class="sbt"><i class="%s" style="width:%d%%"></i></span>'
      '<span class="sbv">%d</span></div></div>' % (scls(sc), sc, sc))
    A('<p class="tnote fdet">基本面 %d 分內部拆解：%s</p>'
      % (S[c][2], "、".join("%s %d/%d" % (p[0], v, p[1])
                            for p, v in zip(C.FUND_PARTS, FUND[c]))))

    # 11 建議｜兩種情境
    z = ZONE[c]
    ec, ei, et, hc, hi_, ht = ADV[c]
    A('<h3 class="sh">建議｜兩種情境</h3><div class="acts">')
    A('<div class="act"><div class="acth"><span class="actw">空手時</span>'
      '<span class="actq">在什麼價位、滿足什麼條件才買？</span>%s</div>%s'
      '<p class="actp">%s</p></div>'
      % (chip(ec, ei, et, big=True),
         opbox("買進區間", z["buy_zone"], z["buy_anchor"], "觸發條件", z["buy_cond"]),
         EMPTY_S[c]))
    A('<div class="act"><div class="acth"><span class="actw">已持有</span>'
      '<span class="actq">在什麼價位減碼、跌破什麼就出場？</span>%s</div>%s'
      '<p class="actp">%s</p></div></div>'
      % (chip(hc, hi_, ht, big=True),
         opbox(z["sell_lab"], z["sell_zone"], z["sell_anchor"], "出場觸發", z["sell_cond"]),
         HOLD_S[c]))

    # 12 操作參考
    A('<h3 class="sh">操作參考（價位）</h3><p class="para ops">%s</p>' % OPS_S[c])
    A('<a class="top" href="#top">↑ 回頂端</a></section>')

# ══════════════════════════════════════════════ 投資建議書總結
A('<section id="advice" class="card"><h2 class="sect">投資建議書總結</h2>')
A('<h3 class="sh">一句話總結</h3><p class="para">%s</p>' % MK.SUMMARY)

A('<h3 class="sh">兩種情境的建議總表</h3>')
rows = ""
for i, c in enumerate(RANK, 1):
    ec, ei, et, hc, hi_, ht = ADV[c]
    z = ZONE[c]
    rows += ('<tr><td>#%d %s<em>%s</em></td><td class="num">%s</td><td class="num">%d</td>'
             '<td>%s</td><td class="num">%s<br><small>%s</small></td>'
             '<td>%s</td><td class="num">%s<br><small>%s</small></td></tr>'
             % (i, IND["stocks"][c]["name"], c, n(IND["stocks"][c]["close"]), TOT[c],
                chip(ec, ei, et), z["buy_zone"], z["buy_anchor"],
                chip(hc, hi_, ht), z["sell_zone"], z["sell_lab"]))
A(twrap('<table><thead><tr><th>個股</th><th>收盤</th><th>綜合分</th><th>空手</th><th>買進區間</th>'
        '<th>持有</th><th>減碼／停利區間</th></tr></thead><tbody>%s</tbody></table>' % rows))
A('<p class="tnote"><b>分數建議與情境建議的差別</b>：分數建議只是五面向加權後的綜合評比，'
  '回答「這家公司整體好不好」；情境建議回答兩個完全不同的操作問題——'
  '空手看「現在這個價位的風險報酬比」，持有看「機會成本與時間壓力」。'
  '<b>兩者不一致是常態而非錯誤。</b></p>')

A('<h3 class="sh">依綜合分數分組</h3>')
grp = {}
for c in RANK:
    grp.setdefault(band_of(TOT[c]), []).append(c)
A('<div class="grps">%s</div>' % "".join(
    '<div class="grp"><h4>%s　<small>%d 檔</small></h4><p>%s</p></div>'
    % (g, len(grp.get(g, [])),
       "、".join("%s(%s) %d 分" % (IND["stocks"][x]["name"], x, TOT[x])
                 for x in grp.get(g, [])) or "無")
    for _, g in C.BANDS))

A('<h3 class="sh">當日關鍵變化</h3><ul class="lst">%s</ul>'
  % "".join("<li>%s</li>" % x for x in MK.KEY_CHANGES))
A('<h3 class="sh">必須注意的事件</h3><ul class="lst">%s</ul>'
  % "".join("<li>%s</li>" % x for x in MK.EVENTS))
A('<h3 class="sh">資料完整性說明</h3>')
A('<p class="para chipnote">%s</p>' % MK.HIDDEN_NOTE)
A('<ul class="lst">%s</ul>' % "".join("<li>%s</li>" % x for x in MK.DATA_NOTES))
A('<a class="top" href="#top">↑ 回頂端</a></section>')

A('<footer class="foot"><h3>免責聲明</h3>'
  '<p>本報告由自動化流程彙整公開資訊產生，僅供研究與教育參考，不構成任何投資建議、要約或招攬，'
  '亦不保證資料之完整性與正確性。所有評分為依既定公式計算之相對參考值，不代表對個股未來表現之預測。'
  '與公司正式公告或主管機關公開資訊有出入時，一律以官方公告為準。投資有風險，過去績效不代表未來表現。</p>'
  '<p class="gen">資料基準日 %s（%s收盤）｜產出時間 %s</p></footer>' % (BD, WD, GEN_TIME))
A('</body></html>')

html = "\n".join(O)
outdir = os.path.join(C.REPO, C.YMD)
os.makedirs(outdir, exist_ok=True)
open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write(html)
print("1) %s\\index.html 已寫入，%d 字元" % (C.YMD, len(html)))
print("   排名：" + "｜".join("%s %d" % (IND["stocks"][c]["name"], TOT[c]) for c in RANK))
