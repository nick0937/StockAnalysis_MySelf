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
from lib import band_of, total_score, market_score
import market as MK
from scores import S, ADV
from zones import ZONE

D = os.path.join(BASE, "data")
IND = json.load(open(os.path.join(D, "indicators.json"), encoding="utf-8"))
for c in C.CODES:
    S[c] = (S[c][0], S[c][1], S[c][2],
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

# [3] 結構檢查
print("\n[3] 結構檢查")
NE = len(C.CODES)
for tag, want in [('id="market"', 1), ('id="overview"', 1), ('id="advice"', 1),
                  ('class="card stk"', NE), ('class="acts"', NE), ('class="ovr"', NE),
                  ('<h3 class="sh">月營收（近 %d 個月）</h3>' % C.N_MONTHLY, NE),
                  ('<h3 class="sh">每股盈餘（近 %d 季）</h3>' % C.N_EPS, NE),
                  ('<h3 class="sh">大戶籌碼（近 %d 週，約 3 個月）</h3>' % C.N_CONC, NE),
                  ('class="o-ev"', NE + 1), ('class="o-hv"', NE + 1)]:
    got = H.count(tag)
    print("    %-52s %d（預期 %d）%s" % (tag[:52], got, want, "OK" if got == want else "★"))

# [4] 基準日與標題
ok = (('<span>資料基準日</span><b>%s（%s收盤）</b>' % (C.BASE_DATE, C.BASE_WEEKDAY)) in H
      and ('<title>%s %s' % (C.TITLE, C.BASE_DATE)) in H)
print("\n[4] 標題與基準日：", "OK" if ok else "★異常")

# [5] 「查無」標示
print("[5] 「查無」標示數量：", H.count("查無"), "處")

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
    head + '<a class="big" href="./%s/index.html">閱讀最新一期 · %s/%s/%s</a>\n'
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
