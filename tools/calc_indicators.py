# -*- coding: utf-8 -*-
"""第 1 步（續）：本地計算全套技術指標 + 相對強弱 → data/indicators.json
   ★ 移植時不用改。★ 所有指標都在本地算，不採用任何第三方計算值。

   會依 config.BASE_DATE 濾除日期 > 基準日的列（盤中執行會拿到未完成 K 棒）。
"""
import json, os, sys, math, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import config as C
from lib import rs_score

RAW = os.path.join(BASE, "data", "raw")
CUT = C.BASE_DATE


def tw_date(ts):
    return datetime.datetime.fromtimestamp(ts + 8 * 3600, datetime.UTC).strftime("%Y-%m-%d")


def load(sym):
    d = json.load(open(os.path.join(RAW, sym.replace("^", "IDX_") + ".json"), encoding="utf-8"))
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    seen = {}
    for i, t in enumerate(res["timestamp"]):
        c = q["close"][i]
        if c is None:
            continue
        dt = tw_date(t)
        if dt > CUT:                      # ★ 濾除未完成 K 棒
            continue
        seen[dt] = {"d": dt, "o": q["open"][i], "h": q["high"][i],
                    "l": q["low"][i], "c": c, "v": q["volume"][i] or 0}
    return [seen[k] for k in sorted(seen)]


sma = lambda a, k: sum(a[-k:]) / k if len(a) >= k else None


def ema_series(a, k):
    m, out, e = 2 / (k + 1), [], None
    for x in a:
        e = x if e is None else x * m + e * (1 - m)
        out.append(e)
    return out


def kd_series(rows, k=9):
    ks, ds, kk, dd = [], [], 50.0, 50.0
    for i in range(len(rows)):
        w = rows[max(0, i - k + 1):i + 1]
        hi, lo = max(r["h"] for r in w), min(r["l"] for r in w)
        rsv = 50.0 if hi == lo else (rows[i]["c"] - lo) / (hi - lo) * 100
        kk = 2 / 3 * kk + 1 / 3 * rsv
        dd = 2 / 3 * dd + 1 / 3 * kk
        ks.append(kk); ds.append(dd)
    return ks, ds


def rsi_series(cl, k=14):
    out = [None] * len(cl)
    if len(cl) <= k:
        return out
    g = sum(max(cl[i] - cl[i - 1], 0) for i in range(1, k + 1)) / k
    l = sum(max(cl[i - 1] - cl[i], 0) for i in range(1, k + 1)) / k
    out[k] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(k + 1, len(cl)):
        ch = cl[i] - cl[i - 1]
        g = (g * (k - 1) + max(ch, 0)) / k
        l = (l * (k - 1) + max(-ch, 0)) / k
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def pstd(a):
    m = sum(a) / len(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / len(a))


ret = lambda cl, k: (cl[-1] / cl[-1 - k] - 1) * 100 if len(cl) > k else None


def analyze(rows, label):
    cl = [r["c"] for r in rows]
    vol = [r["v"] for r in rows]
    last, prev = rows[-1], rows[-2]
    ks, ds = kd_series(rows)
    rs_ = rsi_series(cl)
    e12, e26 = ema_series(cl, 12), ema_series(cl, 26)
    dif = [x - y for x, y in zip(e12, e26)]
    dea = ema_series(dif, 9)
    osc = [x - y for x, y in zip(dif, dea)]
    mid = sma(cl, 20)
    sd = pstd(cl[-20:]) if len(cl) >= 20 else None
    up = mid + 2 * sd if mid else None
    dn = mid - 2 * sd if mid else None
    base = datetime.date.fromisoformat(last["d"])
    yr = [r for r in rows if (base - datetime.date.fromisoformat(r["d"])).days <= 365]
    hi52, lo52 = max(r["h"] for r in yr), min(r["l"] for r in yr)
    py = [r for r in rows if r["d"][:4] < last["d"][:4]]
    v5, v20 = sma(vol, 5), sma(vol, 20)
    return {"label": label, "date": last["d"], "close": last["c"],
            "open": last["o"], "high": last["h"], "low": last["l"], "prev_close": prev["c"],
            "chg": last["c"] - prev["c"], "chg_pct": (last["c"] / prev["c"] - 1) * 100,
            "vol_shares": last["v"], "vol_lots": last["v"] / 1000,
            "ma": {str(k): sma(cl, k) for k in (5, 10, 20, 60, 120, 240)},
            "bias20": (last["c"] / mid - 1) * 100 if mid else None,
            "bias60": (last["c"] / sma(cl, 60) - 1) * 100 if sma(cl, 60) else None,
            "k": ks[-1], "d": ds[-1], "k_prev": ks[-2], "d_prev": ds[-2],
            "rsi": rs_[-1], "rsi_prev": rs_[-2],
            "dif": dif[-1], "dea": dea[-1], "osc": osc[-1],
            "osc_prev": osc[-2], "osc_prev2": osc[-3],
            "bb_up": up, "bb_mid": mid, "bb_dn": dn,
            "pb": (last["c"] - dn) / (up - dn) * 100 if up and up != dn else None,
            "bw": (up - dn) / mid * 100 if mid else None,
            "v5": v5 / 1000 if v5 else None, "v20": v20 / 1000 if v20 else None,
            "vr": last["v"] / v5 if v5 else None,
            "vr20": last["v"] / v20 if v20 else None,
            "hi52": hi52, "lo52": lo52,
            "from_hi52": (last["c"] / hi52 - 1) * 100,
            "from_lo52": (last["c"] / lo52 - 1) * 100,
            "r1": ret(cl, 1), "r5": ret(cl, 5), "r20": ret(cl, 20), "r60": ret(cl, 60),
            "r120": ret(cl, 120), "r240": ret(cl, 240),
            "ytd": (cl[-1] / py[-1]["c"] - 1) * 100 if py else None,
            "spark": [{"d": r["d"], "c": r["c"]} for r in rows[-20:]], "n": len(rows)}


idx_rows = load(C.INDEX_SYM)
result = {"idx": analyze(idx_rows, C.INDEX_NAME), "stocks": {}}
idx_d = [r["d"] for r in idx_rows]
idx_c = [r["c"] for r in idx_rows]

# 櫃買歷史序列可用性檢查
try:
    otc = load(C.OTC_SYM)
    if otc[-1]["d"] != C.BASE_DATE:
        print("⚠ %s 歷史序列停更於 %s（≠ 基準日 %s）→ 相對強弱一律以 %s 為基準，"
              "櫃買只取當日收盤值並在報告註明"
              % (C.OTC_SYM, otc[-1]["d"], C.BASE_DATE, C.INDEX_SYM))
except Exception:
    print("⚠ %s 無資料 → 相對強弱一律以 %s 為基準" % (C.OTC_SYM, C.INDEX_SYM))

for code in C.CODES:
    rows = load(C.SYM[code])
    a = analyze(rows, C.NAME[code])
    a.update(code=code, name=C.NAME[code], sym=C.SYM[code],
             market=C.MKT[code][0], industry=C.MKT[code][1])
    dm = {r["d"]: r["c"] for r in rows}
    common = [d for d in idx_d if d in dm]
    sc = [dm[d] for d in common]
    ic = [idx_c[idx_d.index(d)] for d in common]
    ex = {}
    for k in (1, 5, 20, 60):
        ex[k] = ((sc[-1] / sc[-1 - k] - 1) * 100 - (ic[-1] / ic[-1 - k] - 1) * 100
                 if len(sc) > k else None)
    sr = [sc[i] / sc[i - 1] - 1 for i in range(len(sc) - 60, len(sc))]
    ir = [ic[i] / ic[i - 1] - 1 for i in range(len(ic) - 60, len(ic))]
    ms, mi = sum(sr) / len(sr), sum(ir) / len(ir)
    cov = sum((x - ms) * (y - mi) for x, y in zip(sr, ir)) / len(sr)
    vi = sum((y - mi) ** 2 for y in ir) / len(ir)
    vs = sum((x - ms) ** 2 for x in sr) / len(sr)
    a["ex"] = {str(k): v for k, v in ex.items()}
    a["beta"] = cov / vi if vi else None
    a["corr"] = cov / math.sqrt(vs * vi) if vs and vi else None
    a["rs"] = rs_score(ex[5], ex[20], ex[60])
    result["stocks"][code] = a

json.dump(result, open(os.path.join(BASE, "data", "indicators.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

i = result["idx"]
print("=" * 100)
print("基準日 %s｜%s 收 %.2f（%+.2f%%）｜K %.2f RSI %.2f OSC %.1f｜站上均線 %d/6"
      % (i["date"], C.INDEX_NAME, i["close"], i["chg_pct"], i["k"], i["rsi"], i["osc"],
         sum(1 for k in (5, 10, 20, 60, 120, 240)
             if i["ma"][str(k)] and i["close"] > i["ma"][str(k)])))
print("-" * 100)
print("%-5s %-9s %8s %8s %7s %7s %7s %8s %6s %6s %6s" %
      ("代號", "名稱", "收盤", "漲跌%", "K", "RSI", "乖離20", "距52高", "RS", "Beta", "corr"))
for c in C.CODES:
    a = result["stocks"][c]
    print("%-5s %-9s %8.2f %+8.2f %7.2f %7.2f %+7.2f %+8.2f %6.1f %6.2f %6.2f"
          % (c, a["name"], a["close"], a["chg_pct"], a["k"], a["rsi"],
             a["bias20"], a["from_hi52"], a["rs"], a["beta"], a["corr"]))
print("\n下一步：填好 inputs/*.py 後 python calc_fin.py → build_report.py → finalize.py")
