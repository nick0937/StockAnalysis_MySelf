# -*- coding: utf-8 -*-
"""第 1 步：抓行情（Yahoo chart API）＋ 大盤成交金額（證交所 FMTQIK）→ data/raw/
   ★ 移植時不用改；標的來自 config.STOCKS。

   ⚠ 一定要帶正常 User-Agent，否則 Yahoo 回 429、玩股網回 403。
   ⚠ 盤中執行會拿到未完成 K 棒（成交量 0），由 calc_indicators.py 依 BASE_DATE 濾除。

   ★★ 2026-09-01 新增：<b>大盤指數的單日空值會自動由證交所官方端點回填</b>。
     Yahoo 的 ^TWII 偶爾整列回 null（已知 2026-08-17、2026-08-28 兩次），
     那會讓「基準日的漲跌」拿更早一天當基準——08/31 就被算成 +0.33%（實際 −0.44%），
     連 RS／Beta 都跟著失真。原本靠人工發現再手動回填，但<b>本檔每次重抓都會覆寫，
     補了也會被擦掉</b>（09/01 就再犯一次）。→ 改為抓完就自動掃、自動補、印出結果。
"""
import io, json, os, sys, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import config as C

OUT = os.path.join(BASE, "data", "raw")
os.makedirs(OUT, exist_ok=True)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def get(url, headers=None, tries=4, timeout=30):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


syms = [C.INDEX_SYM, C.OTC_SYM] + [C.SYM[c] for c in C.CODES]
print("=" * 84)
for s in syms:
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(s) + "?range=2y&interval=1d")
    try:
        raw = get(url)
    except Exception as e:
        print("%-12s FAIL  %s" % (s, e))
        continue
    open(os.path.join(OUT, s.replace("^", "IDX_") + ".json"), "wb").write(raw)
    d = json.loads(raw)["chart"]["result"][0]
    rows = [(t, c) for t, c in zip(d["timestamp"], d["indicators"]["quote"][0]["close"])
            if c is not None]
    print("%-12s OK  %4d 筆  最後收盤 %.2f" % (s, len(rows), rows[-1][1]))

# ── ★ 大盤指數空值自動回填（證交所 indicesReport/MI_5MINS_HIST，官方 OHLC）──
#   ⚠ 只補「整列為 null」的日期，絕不覆寫已有數值；成交量不補
#   （守則：指數量能一律以 FMTQIK 為準，Yahoo 的指數量比不採用）。
def backfill_index_nulls(path, months=2):
    """回傳 (補了幾列, 仍為空的日期清單)。"""
    import datetime
    d = json.loads(open(path, "rb").read().decode("utf-8"))
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    ts = r["timestamp"]
    nulls = {}
    for i in range(max(0, len(ts) - 60), len(ts)):          # 只看近 60 筆
        if q["close"][i] is None:
            nulls[datetime.datetime.fromtimestamp(ts[i]).strftime("%Y/%m/%d")] = i
    if not nulls:
        return 0, []
    # 依月份抓官方 OHLC
    official = {}
    for ymd in sorted({k[:7].replace("/", "") + "01" for k in nulls}):
        try:
            raw = get("https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
                      "?date=%s&response=json" % ymd)
            j = json.loads(raw)
            for row in j.get("data", []):
                roc = row[0].split("/")
                key = "%d/%s/%s" % (int(roc[0]) + 1911, roc[1], roc[2])
                official[key] = [float(x.replace(",", "")) for x in row[1:5]]
        except Exception as e:
            print("   ⚠ 官方端點抓取失敗（%s）：%s" % (ymd, e))
    done = []
    for key, i in sorted(nulls.items()):
        if key not in official:
            continue
        o, h, l, c = official[key]
        q["open"][i], q["high"][i], q["low"][i], q["close"][i] = o, h, l, c
        for a in (r.get("indicators", {}).get("adjclose") or []):
            if isinstance(a.get("adjclose"), list) and a["adjclose"][i] is None:
                a["adjclose"][i] = c
        done.append("%s（開 %.2f 高 %.2f 低 %.2f 收 %.2f）" % (key, o, h, l, c))
    if done:
        json.dump(d, io.open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return len(done), done, [k for k in sorted(nulls) if k not in official]


_idx_path = os.path.join(OUT, C.INDEX_SYM.replace("^", "IDX_") + ".json")
if os.path.isfile(_idx_path):
    print()
    print("★ 大盤指數空值檢查（近 60 筆）")
    try:
        n_done, done, left = backfill_index_nulls(_idx_path)
        if not n_done and not left:
            print("   結果： 沒有空值列，不需回填")
        for x in done:
            print("   ✅ 已由證交所官方 OHLC 回填 %s" % x)
        for x in left:
            print("   ★ %s 仍為空值——官方端點也查不到，請人工確認是否為休市日" % x)
    except Exception as e:
        print("   ★ 回填程序失敗：%s —— 請人工檢查空值列" % e)

# ── 大盤成交金額與股數（證交所 FMTQIK，官方、有整月歷史）──
ym = C.BASE_DATE[:7].replace("-", "") + "01"
try:
    raw = get("https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=%s&response=json" % ym)
    open(os.path.join(OUT, "twse_fmtqik.json"), "wb").write(raw)
    d = json.loads(raw)
    print("\nFMTQIK OK  stat=%s  欄位=%s" % (d.get("stat"), d.get("fields")))
    print("★ 把下列兩行填進 inputs/market.py 的 IDX_AMOUNT / IDX_VOLUME：")
    for row in d.get("data", [])[-3:]:
        roc = row[0].split("/")
        ad = "%d-%s-%s" % (int(roc[0]) + 1911, roc[1], roc[2])
        print('   "%s": %s,   # 成交股數 %s、加權指數 %s'
              % (ad, row[2].replace(",", ""), row[1].replace(",", ""), row[4]))
except Exception as e:
    print("\nFMTQIK FAIL：%s —— 改用玩股網 all-quote-info（id=='0000'）並在 market.py 手填" % e)

print("\n下一步：python calc_indicators.py")
