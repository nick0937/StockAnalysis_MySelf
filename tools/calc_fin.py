# -*- coding: utf-8 -*-
"""由 inputs/fin_raw.json（Yahoo 財報頁原始數字）計算衍生指標 → data/fin.json
   ★ 移植時不用改。面額變更設定在 config.SPLIT。

   單位：Yahoo 財報為仟元；輸出的金額欄位一律換成億元。
   驗證：自由現金流 = 營業現金流 + 投資現金流（Yahoo 的 FCF 定義），逐季檢查。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

BASE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(BASE, "data")
RAW = json.load(open(os.path.join(BASE, "inputs", "fin_raw.json"), encoding="utf-8"))
IND = json.load(open(os.path.join(D, "indicators.json"), encoding="utf-8"))
CHIP = None
try:
    sys.path.insert(0, os.path.join(BASE, "inputs"))
    from chips import out as CHIPS_OUT
    CHIP = CHIPS_OUT
except Exception:
    CHIP = json.load(open(os.path.join(D, "chips.json"), encoding="utf-8"))


def qkey(q):
    return int(q[:4]) * 10 + int(q[5])


def f(x):
    try:
        return float(x)
    except Exception:
        return None


out = {}
bad_identity = []
for code in C.CODES:
    sym = C.SYM[code]
    r = RAW[sym]
    inc, bal, cf = r["income-statement"], r["balance-sheet"], r["cash-flow-statement"]
    qs = inc["q"]

    # ── 推算流通股數：三大法人合計張數 ÷ 三大法人持股比重 ──
    inst0 = CHIP[code]["inst"][0]
    lots, ratio = f(inst0[10]), f(inst0[12])
    shares_k = lots / (ratio / 100) if lots and ratio else None   # 仟股

    # ── EPS（面額變更調整）──
    eps_raw = {}
    for row in r["eps"]:
        p = row.split("|")
        eps_raw[p[0].replace(" ", "")] = f(p[1])
    eps = {}
    split_q, mult = C.SPLIT.get(code, (None, 1))
    for q, v in eps_raw.items():
        if v is None:
            eps[q] = None
        elif split_q and qkey(q) < qkey(split_q):
            eps[q] = v / float(mult)          # ★ 跨基準日之前一律除以倍數
        else:
            eps[q] = v

    # ── 損益表近 8 季（三率、YoY）──
    rows = []
    for i, q in enumerate(qs):
        rev = f(inc["v"]["營業收入"][i])
        gp = f(inc["v"]["營業毛利"][i])
        op = f(inc["v"]["營業利益"][i])
        ni = f(inc["v"]["稅後淨利"][i])
        rev_yoy = None
        if i + 4 < len(qs):
            pr = f(inc["v"]["營業收入"][i + 4])
            if pr:
                rev_yoy = (rev / pr - 1) * 100
        e = eps.get(q)
        eq = None
        if i + 4 < len(qs):
            pe = eps.get(qs[i + 4])
            if pe not in (None, 0) and e is not None and pe > 0:
                eq = (e / pe - 1) * 100        # 去年同季虧損則年增率無意義，留 None
        rows.append({"q": q, "rev": rev / 100000.0, "rev_yoy": rev_yoy,
                     "gm": gp / rev * 100 if rev else None,
                     "om": op / rev * 100 if rev else None,
                     "nm": ni / rev * 100 if rev else None,
                     "eps": e, "eps_yoy": eq})

    # ── 資產負債表：最新季 / 前一季 / 去年同季 ──
    def bcol(i):
        ta, tl = f(bal["v"]["總資產"][i]), f(bal["v"]["總負債"][i])
        eq_ = f(bal["v"]["股東權益"][i])
        ca, cl = f(bal["v"]["流動資產"][i]), f(bal["v"]["流動負債"][i])
        return {"q": bal["q"][i], "ta": ta / 1e5, "tl": tl / 1e5, "eq": eq_ / 1e5,
                "ca": ca / 1e5, "cl": cl / 1e5,
                "debt_ratio": tl / ta * 100 if ta else None,
                "current_ratio": ca / cl * 100 if cl else None,
                "bps": eq_ / shares_k if shares_k else None}
    bs = [bcol(0), bcol(1), bcol(4)]

    # ── 現金流量表：最新季 + 近四季合計 ──
    cfo = [f(x) for x in cf["v"]["營業現金流"]]
    cfi = [f(x) for x in cf["v"]["投資現金流"]]
    cff = [f(x) for x in cf["v"]["融資現金流"]]
    fcf = [f(x) for x in cf["v"]["自由現金流"]]
    nis = [f(x) for x in inc["v"]["稅後淨利"]]
    for i in range(len(fcf)):
        if abs((cfo[i] + cfi[i]) - fcf[i]) > 1:
            bad_identity.append((code, cf["q"][i]))
    cash = {"q": cf["q"][0],
            "cfo": cfo[0] / 1e5, "cfi": cfi[0] / 1e5, "cff": cff[0] / 1e5,
            "fcf": fcf[0] / 1e5, "ni": nis[0] / 1e5,
            "cfo_ni": cfo[0] / nis[0] if nis[0] else None,
            "cfo4": sum(cfo[:4]) / 1e5, "cfi4": sum(cfi[:4]) / 1e5,
            "cff4": sum(cff[:4]) / 1e5, "fcf4": sum(fcf[:4]) / 1e5,
            "ni4": sum(nis[:4]) / 1e5,
            "cfo_ni4": sum(cfo[:4]) / sum(nis[:4]) if sum(nis[:4]) else None}

    eps4 = [eps.get(q) for q in qs[:4]]
    eps4s = sum(x for x in eps4 if x is not None) if all(x is not None for x in eps4) else None
    close = IND["stocks"][code]["close"]

    out[code] = {"latest_q": qs[0], "shares_k": shares_k, "inc": rows, "bs": bs,
                 "cash": cash, "eps4": eps4s,
                 "pe": close / eps4s if eps4s and eps4s > 0 else None,
                 "pb": close / bs[0]["bps"] if bs[0]["bps"] else None,
                 "eps_adjusted": code in C.SPLIT,
                 "split": list(C.SPLIT.get(code, (None, 1)))}

json.dump(out, open(os.path.join(D, "fin.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

print("=" * 96)
print("財報衍生指標已寫入 data/fin.json")
print("FCF = CFO + CFI 恆等式：", "全部通過" if not bad_identity else "★不符 %s" % bad_identity)
print("-" * 96)
for code in C.CODES:
    o = out[code]
    r0, r4 = o["inc"][0], o["inc"][4]
    print("%s %-8s 最新季 %s｜三率 %.2f/%.2f/%.2f（去年同季 %.2f/%.2f/%.2f）｜"
          "負債比 %.2f%%｜CFO÷淨利 單季 %s 近四季 %s｜近四季EPS %s｜PE %s PB %s%s"
          % (code, C.NAME[code], o["latest_q"], r0["gm"], r0["om"], r0["nm"],
             r4["gm"], r4["om"], r4["nm"], o["bs"][0]["debt_ratio"],
             "%.2f" % o["cash"]["cfo_ni"] if o["cash"]["cfo_ni"] else "n/a",
             "%.2f" % o["cash"]["cfo_ni4"] if o["cash"]["cfo_ni4"] else "n/a",
             "%.2f" % o["eps4"] if o["eps4"] else "n/a",
             "%.1f" % o["pe"] if o["pe"] else "n/a",
             "%.2f" % o["pb"] if o["pb"] else "n/a",
             "｜★EPS 已依面額變更 1:%d 還原" % o["split"][1] if o["eps_adjusted"] else ""))
