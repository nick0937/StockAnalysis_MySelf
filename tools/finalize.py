# -*- coding: utf-8 -*-
"""交付前檢查 → 重建首頁 → 寫 COMMIT_MSG.txt
   ★ 寫入順序必須是：個股報告（build_report.py）→ 首頁 → COMMIT_MSG，本檔負責後兩步。
   ★ 移植時不用改。
"""
import json, os, re, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "inputs"))
import config as C
from lib import band_of, total_score, market_score, tech_adj
import market as MK
from scores import S, ADV
from zones import ZONE
from shorts import EMPTY_S, HOLD_S, OPS_S, TGT_S
from chips import NOTES as CHIP_NOTES

D = os.path.join(BASE, "data")
IND = json.load(open(os.path.join(D, "indicators.json"), encoding="utf-8"))
# ★ 技術面分與大盤面分的組法必須與 build_report.py 完全一致（守則 §9.1）：
#   技術面 = inputs 判讀分 + lib.tech_adj 的客觀加減分（±10 封頂）；大盤面 = 環境分×50% + RS×50%。
#   ⚠ 2026-08-19 修：原本這裡只覆寫大盤面、漏了 tech_adj，導致 [1] 一致性檢查、首頁最高分、
#     COMMIT_MSG 的分數與排名全部用「判讀分」，與報告 HTML（已含加減分）不一致。
TADJ = {}
for c in C.CODES:
    adj, why = tech_adj(IND["stocks"][c])
    TADJ[c] = (S[c][1], adj, why)
    S[c] = (S[c][0], max(0, min(100, S[c][1] + adj)), S[c][2],
            market_score(MK.ENV_SCORE, IND["stocks"][c]["rs"]), S[c][4])
TOT = {c: total_score(S[c]) for c in C.CODES}
RANK = sorted(C.CODES, key=lambda c: -TOT[c])
nm = lambda c: IND["stocks"][c]["name"]

RP = os.path.join(C.REPO, C.YMD, "index.html")
H = open(RP, encoding="utf-8").read()

print("=" * 92)
print("交付前檢查（守則第 13 節）")
print("=" * 92)

# [1] 五面向小分與綜合分一致（floor(x+0.5) 半進位）
print("\n[1] 五面向小分 vs 綜合分")
bad = 0
for c in RANK:
    calc = total_score(S[c])
    ok = calc == TOT[c] and ('<span class="sbv">%d</span>' % TOT[c]) in H
    bad += 0 if ok else 1
    print("    %s %-8s %s → %d  %s" % (c, nm(c), S[c], TOT[c], "OK" if ok else "★不符"))
print("    結果：", "全部一致且已正確寫入 HTML" if bad == 0 else "有 %d 檔不符" % bad)

# [2] 大盤面分為公式值
print("\n[2] 大盤面分 = 環境分 %d × 50%% + RS × 50%%（不主觀給分）" % MK.ENV_SCORE)
for c in RANK:
    print("    %s %-8s RS %.2f → %d" % (c, nm(c), IND["stocks"][c]["rs"], S[c][3]))

# [2b] 技術面 = 判讀分 + 客觀加減分（守則 §9.1，2026-08-19 新增）
print("\n[2b] 技術面 = 判讀分 ＋ lib.tech_adj 客觀加減分（±10 封頂，手填無效）")
for c in RANK:
    base, adj, why = TADJ[c]
    print("    %s %-8s %d %+d = %-3d %s"
          % (c, nm(c), base, adj, S[c][1], "／".join(why) if why else "無訊號"))

# [3] 結構檢查
print("\n[3] 結構檢查")
NE = len(C.CODES)
for tag, want in [('id="market"', 1), ('id="overview"', 1), ('id="advice"', 1),
                  ('class="card stk"', NE), ('class="acts"', NE), ('class="ovr"', NE),
                  ('<h3 class="sh">月營收（近 %d 個月）</h3>' % C.N_MONTHLY, NE),
                  ('<h3 class="sh">每股盈餘（近 %d 季）</h3>' % C.N_EPS, NE),
                  ('<h3 class="sh">大戶籌碼（近 %d 週，約 3 個月）</h3>' % C.N_CONC, NE),
                  ('class="o-ev"', NE + 1), ('class="o-hv"', NE + 1),
                  ('<h3 class="sh">你的部位｜張數與成本</h3>', NE),   # 守則第 20 節
                  ('<h3 class="sh">你的持倉｜張數與成本</h3>', 1)]:
    got = H.count(tag)
    print("    %-52s %d（預期 %d）%s" % (tag[:52], got, want, "OK" if got == want else "★"))

# [4] 基準日與標題
ok = (('<span>資料基準日</span><b>%s（%s收盤）</b>' % (C.BASE_DATE, C.BASE_WEEKDAY)) in H
      and ('<title>%s %s' % (C.TITLE, C.BASE_DATE)) in H)
print("\n[4] 標題與基準日：", "OK" if ok else "★異常")

# [5] 「查無」標示
print("[5] 「查無」標示數量：", H.count("查無"), "處")

# [5a] 敘述篇幅（守則 §10：標籤 → 操作條件盒 → 3~6 句理由）
#   ⚠ 2026-08-24 新增。起因：08/11 每欄 2~4 句，逐期漂移到 08/20 的 5~7 句，
#     08/21 的詳版 HOLD 更暴衝到 10~12 句、字數 2.2 倍。追蹤檔數由 4 檔減為 2 檔，
#     省下的版面被逐期填滿——這是加料，不是資訊變多。改由程式盯著。
SENT_MAX = 6            # 每欄句數上限（＝守則 §10 的上限）
SENT_MIN = 3            # 下限
CHAR_MAX = 480          # ★ 每欄字數上限（去 HTML 標籤後）。只管句數會被繞過——
                        #   08/21 的 1514 持有是「7 句 870 字」＝平均一句 124 字，等於把三句塞成一句。
                        #   480 字 ≈ 08/17~08/18 那幾期的手感（當時 393~534 字）。


def _plain(t):
    return re.sub(r"<[^>]+>", "", t or "")


def _sent(t):
    return len([x for x in re.split(r"[。！？]", _plain(t)) if x.strip()])


print("\n[5a] 敘述篇幅（守則 §10：每欄 %d~%d 句、≤ %d 字；只量 shorts，那是唯一進報告的一份）"
      % (SENT_MIN, SENT_MAX, CHAR_MAX))
over = 0
for lab, d in (("空手", EMPTY_S), ("持有", HOLD_S), ("操作參考", OPS_S), ("目標價", TGT_S)):
    for c in C.CODES:
        n, ch = _sent(d.get(c, "")), len(_plain(d.get(c, "")))
        per = ch / n if n else 0
        flag = []
        if not (SENT_MIN <= n <= SENT_MAX):
            flag.append("%d 句超出 %d~%d" % (n, SENT_MIN, SENT_MAX))
        if ch > CHAR_MAX:
            flag.append("%d 字超出 %d" % (ch, CHAR_MAX))
        over += len(flag)
        print("    %-6s %s %-6s %2d 句 / %4d 字（每句 %3.0f 字）  %s"
              % (lab, c, IND["stocks"][c]["name"], n, ch, per,
                 "OK" if not flag else "★ " + "；".join(flag)))
print("    結果：", "全部在守則範圍內" if over == 0 else "★ %d 項超標，交付前請收斂" % over)

# [5b] 同一個數字被寫了幾遍（守則 §14 品質要求：不要同一事實反覆鋪陳）
#   ⚠ 2026-08-24 新增。08/21 實測：「外資 −2,204」等 5 個數字各出現在 10 個欄位。
#   合理的三處是：籌碼區塊原文一次、卡片理由一次、總結一次。
DUP_MAX = 3
_FIELDS = {
    "shorts.EMPTY_S": EMPTY_S, "shorts.HOLD_S": HOLD_S,
    "shorts.OPS_S": OPS_S, "shorts.TGT_S": TGT_S,
    "chips.NOTES": CHIP_NOTES,
}
_BLOBS = {k: " ".join(v.values()) for k, v in _FIELDS.items()}
_BLOBS["zones.buy_cond"] = " ".join(v["buy_cond"] for v in ZONE.values())
_BLOBS["zones.sell_cond"] = " ".join(v["sell_cond"] for v in ZONE.values())
_BLOBS["market.KEY_CHANGES"] = " ".join(MK.KEY_CHANGES)
_BLOBS["market.EVENTS"] = " ".join(MK.EVENTS)
_BLOBS["market.SUMMARY"] = MK.SUMMARY + getattr(MK, "HIDDEN_NOTE", "")

# 從所有敘述裡自動抓「帶正負號或千分位的數字／百分比」當候選，不用手動維護清單
_ALL = " ".join(_BLOBS.values())
_CAND = set(re.findall(r"[+−\-]?\d{1,3}(?:,\d{3})+|[+−\-]\d+(?:\.\d+)?%?|\d+\.\d+%", _plain(_ALL)))
# ★ 排除「基準事實」：基準日的指數與各檔收盤價、漲跌幅。
#   這些數字本來就會同時出現在價格區、籌碼判讀、關鍵變化與族群比較裡，
#   壓到 3 處只會扭曲文字。3 處上限要管的是「籌碼與技術明細的反覆鋪陳」。
_BASE_FACTS = set()
for _a in [IND["idx"]] + [IND["stocks"][c] for c in C.CODES]:
    for _v in (_a.get("chg_pct"), _a.get("close")):
        if _v is None:
            continue
        # ⚠ "%,.2f" 在 %-formatting 裡是非法的（千分位只有 str.format 支援）
        for _t in ("{:.2f}".format(_v), "{:+.2f}".format(_v), "{:,.2f}".format(_v)):
            _BASE_FACTS |= {_t, _t + "%", _t.replace("-", "−"), _t.replace("-", "−") + "%"}
_CAND -= _BASE_FACTS
_dup = []


def _count_fields(tok):
    """數這個 token 出現在幾個欄位裡。
    ⚠ 必須用邊界比對，不能用純子字串——否則 "0.04%" 會被 "−0.04%" 誤計，
    而那是兩個完全不同的數字（5 日集中度 vs 對族群超額）。"""
    pat = re.compile(r"(?<![0-9,.+\-−])" + re.escape(tok))
    return [n for n, b in _BLOBS.items() if pat.search(_plain(b))]


for tok in _CAND:
    if len(tok) < 4:
        continue
    hits = _count_fields(tok)
    if len(hits) > DUP_MAX:
        _dup.append((len(hits), tok, hits))
_dup.sort(reverse=True)
print("\n[5b] 同一數字的重複鋪陳（上限 %d 處：籌碼原文／卡片理由／總結）" % DUP_MAX)
if not _dup:
    print("    結果： 沒有任何數字超過 %d 處" % DUP_MAX)
else:
    for n, tok, hits in _dup[:12]:
        print("    ★ %-10s %2d 處 ｜ %s" % (tok, n, "、".join(hits)))
    print("    結果： ★ %d 個數字超過 %d 處——同一事實請只留籌碼原文＋一處理由＋一處總結"
          % (len(_dup), DUP_MAX))

# ── 重建首頁（保留舊期的摘要，只更新最新一期）─────────────────────
print("\n" + "=" * 92)
home_p = os.path.join(C.REPO, "index.html")
old = open(home_p, encoding="utf-8").read()
keep = dict(re.findall(r'<a class="it" href="\./(\d{8})/index\.html">(.*?)</a>', old, re.S))
idx = IND["idx"]
top = RANK[0]
y, m, dd = C.YMD[:4], C.YMD[4:6], C.YMD[6:]
keep[C.YMD] = ('\n  <span class="i-d">%s/%s/%s<em>%s</em><span class="new">最新</span></span>\n'
               '  <span class="i-m">%s <b>%s</b> <i class="%s">%+.2f（%+.2f%%）</i></span>\n'
               '  <span class="i-s">環境分 <b>%d</b>　追蹤 <b>%d</b> 檔　最高分 <b>%s(%s) %d</b></span>\n'
               '  <span class="i-go">開啟報告 →</span>\n'
               % (y, m, dd, C.BASE_WEEKDAY, C.INDEX_NAME, "{:,.2f}".format(idx["close"]),
                  "up" if idx["chg"] > 0 else "dn", idx["chg"], idx["chg_pct"],
                  MK.ENV_SCORE, len(C.CODES), nm(top), top, TOT[top]))

dirs = sorted([d for d in os.listdir(C.REPO)
               if re.fullmatch(r"\d{8}", d) and os.path.isdir(os.path.join(C.REPO, d))],
              reverse=True)
lst = ""
for i, d in enumerate(dirs):
    body = keep.get(d)
    if body is None:
        body = ('\n  <span class="i-d">%s/%s/%s</span>\n  <span class="i-m">收盤</span>\n'
                '  <span class="i-s">追蹤 <b>%d</b> 檔</span>\n'
                '  <span class="i-go">開啟報告 →</span>\n' % (d[:4], d[4:6], d[6:], len(C.CODES)))
    elif i > 0:
        body = body.replace('<span class="new">最新</span>', '')
    lst += '<a class="it" href="./%s/index.html">%s</a>' % (d, body)

head = old[:old.find('<a class="big"')]
foot = old[old.find('<div class="foot">'):]
open(home_p, "w", encoding="utf-8").write(
    head + '<a class="big" href="./%s/index.html">📊 收盤報告 · 閱讀最新一期 · %s/%s/%s</a>\n'
    % (dirs[0], dirs[0][:4], dirs[0][4:6], dirs[0][6:])
    + ' <h2 class="s">歷史報告（%d 期）</h2>\n' % len(dirs)
    + ' <div class="list">' + lst + '</div>\n ' + foot)
print("2) index.html 已重建，%d 期" % len(dirs))

# ── COMMIT_MSG.txt（★ 最後才寫）───────────────────────────────────
time.sleep(1.2)   # 確保 mtime 明確晚於首頁
gb, ge, gh = {}, {}, {}
for c in C.CODES:
    gb[band_of(TOT[c])] = gb.get(band_of(TOT[c]), 0) + 1
    _, ei, et, _, hi_, ht = ADV[c]
    ge["%s %s" % (ei, et)] = ge.get("%s %s" % (ei, et), 0) + 1
    gh["%s %s" % (hi_, ht)] = gh.get("%s %s" % (hi_, ht), 0) + 1

L = ["report(%s): %s %d 檔" % (C.YMD, C.TITLE, len(C.CODES)), "",
     "大盤    %s %s（%+.2f%%）環境分 %d"
     % (C.INDEX_NAME, "{:,.2f}".format(idx["close"]), idx["chg_pct"], MK.ENV_SCORE),
     "最高分  %s(%s)  %d  %s" % (nm(RANK[0]), RANK[0], TOT[RANK[0]], band_of(TOT[RANK[0]])),
     "最低分  %s(%s)  %d  %s" % (nm(RANK[-1]), RANK[-1], TOT[RANK[-1]], band_of(TOT[RANK[-1]])),
     "分佈    " + " ｜ ".join("%s %d" % (g, gb[g]) for _, g in C.BANDS if g in gb),
     "空手    " + " ｜ ".join("%s %d" % (k, v) for k, v in ge.items()),
     "持有    " + " ｜ ".join("%s %d" % (k, v) for k, v in gh.items()),
     "基準日  %s（%s收盤）" % (C.BASE_DATE, C.BASE_WEEKDAY), "", "雙情境建議"]
for c in RANK:
    _, ei, et, _, hi_, ht = ADV[c]
    L.append("        %-9s(%s) %2d｜空手 %s %s｜持有 %s %s"
             % (nm(c), c, TOT[c], ei, et, hi_, ht))
L += ["", "重點"] + ["- " + re.sub(r"<[^>]+>", "", x) for x in MK.KEY_CHANGES]
cm_p = os.path.join(C.REPO, "COMMIT_MSG.txt")
open(cm_p, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
print("3) COMMIT_MSG.txt 已寫入")

# ── 殘留舊分數掃描（守則陷阱 #14）─────────────────────────────────
print("\n[6] 殘留舊分數掃描")
CM = open(cm_p, encoding="utf-8").read()
prev = os.path.join(BASE, "data", "prev_scores.json")
old_scores = json.load(open(prev, encoding="utf-8")) if os.path.exists(prev) else {}
hit = 0
for c, o in old_scores.items():
    if c not in TOT or o == TOT[c]:
        continue
    for tag, txt in (("報告", H), ("COMMIT_MSG", CM)):
        for pat in ("%s %d 分" % (nm(c), o), "(%s) %d｜" % (c, o)):
            if pat in txt:
                print("    ★ %s 殘留 %s 舊分數：'%s'" % (tag, c, pat)); hit += 1
print("    結果：", "無殘留" if hit == 0 else "★發現 %d 處" % hit)
json.dump(TOT, open(prev, "w", encoding="utf-8"))

# ── 三個檔案 mtime 順序 ──────────────────────────────────────────
print("\n" + "=" * 92)
print("三個檔案（依寫入順序，必須是 個股報告 → 首頁 → COMMIT_MSG）")
for p in sorted([RP, home_p, cm_p], key=os.path.getmtime):
    t = time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(p)))
    print("    %-42s %8.1f KB  %s" % (p.replace(C.REPO + os.sep, ""),
                                      os.path.getsize(p) / 1024, t))
print("\n★ 不要自己 git commit／push —— 由使用者雙擊「建立Commit.bat」處理。")
