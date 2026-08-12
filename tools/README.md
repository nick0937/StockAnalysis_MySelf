# tools／報告產生器

把「台股每日個股觀察報告」的產生流程參數化。**規格見 [`../報告守則.md`](../報告守則.md)，這裡只講怎麼跑。**

---

## 檔案分工

| 檔案 | 改不改 | 說明 |
|---|---|---|
| **`config.py`** | **★ 每次跑改基準日；移植改標的** | 唯一需要編輯的設定檔 |
| `lib.py` | ✗ | 共用工具（格式化、配色、sparkline、分數公式） |
| `fetch_quotes.py` | ✗ | 抓 Yahoo 行情 + 證交所大盤成交金額 → `data/raw/` |
| `calc_indicators.py` | ✗ | 本地算全套技術指標 + 相對強弱 → `data/indicators.json` |
| `calc_fin.py` | ✗ | 由 `inputs/fin_raw.json` 算財報衍生指標 → `data/fin.json` |
| `build_report.py` | ✗ | 產生 `REPO/YYYYMMDD/index.html` |
| `finalize.py` | ✗ | 交付前檢查 → 重建首頁 → 寫 `COMMIT_MSG.txt` |
| `verify_rwd.py` | ✗ | Playwright 四寬度 RWD 驗證 |
| **`inputs/*.py`** | **★ 每次跑都要更新** | 每日蒐集的資料與判斷（見下） |

`inputs/` 內附的是 **2026-08-11 的完整實際資料**，可直接當範例與格式範本。

| `inputs/` | 內容 | 來源 |
|---|---|---|
| `chips.py` | 法人 10 日／資券 10 日／主力 10 日／大戶 13 週＋**各檔實際門檻** | 玩股網（守則第 6 節） |
| `monthly.py` | 月營收 12 期（含 YoY／MoM／累計 YoY） | 玩股網 `monthly-revenue-data` |
| `fin_raw.json` | Yahoo 財報三表 + EPS 原始數字 | Yahoo 財報頁（守則第 7 節） |
| `q2est.py` | 公司已公告但 Yahoo 未更新的季度推算值 | 公開資訊觀測站 |
| `market.py` | 大盤環境分、趨勢判讀、建議書全部文字 | 判斷 + 子代理蒐集 |
| `scores.py` | 五面向小分、基本面內部拆解、雙情境標籤 | 判斷 |
| `zones.py` | 買賣區間、錨點來源、觸發條件 | 判斷（端點須錨定實際技術價位） |
| `shorts.py` | 各檔空手／持有／操作參考／目標價文字 | 判斷 + 子代理蒐集 |
| `qual_reference.py` | 公司題材、新聞、股利（**不顯示**，供評分與撰稿參考） | 子代理蒐集 |

---

## 每日跑報告

```bash
cd tools
# 0. 改 config.py 的 BASE_DATE / BASE_WEEKDAY / RERUN_NOTE
python fetch_quotes.py        # 抓行情，並印出要填進 market.py 的成交金額
python calc_indicators.py     # 算指標（會自動濾除盤中未完成 K 棒）
# 1. 用瀏覽器抓籌碼、月營收、財報 → 更新 inputs/chips.py, monthly.py, fin_raw.json
# 2. 派子代理查新聞／題材／目標價 → 更新 inputs/qual_reference.py, shorts.py
# 3. 判讀後更新 inputs/market.py, scores.py, zones.py, q2est.py
python calc_fin.py            # 算財報衍生指標（含 FCF=CFO+CFI 驗證）
python build_report.py        # 產生報告
python verify_rwd.py          # RWD 四寬度必須全過
python finalize.py            # 檢查 → 首頁 → COMMIT_MSG（順序已內建）
```

**不要自己 `git commit`／`push`** —— 由使用者雙擊「建立Commit.bat」處理。

---

## 移植到新追蹤組合（例如航運）

1. 複製整個 repo 骨架：`tools/`、`報告樣式.css`、`報告守則.md`、兩個 `.bat`、`.gitignore`、`index.html`。
2. **只改 `config.py`**：`STOCKS`、`REPO`、`TITLE`、`SPLIT`（面額變更股）、`TIME_PRESSURE`。
3. 清空 `inputs/` 各檔的資料，換成新組合（**保留檔案結構與註解**）。
4. 依上面的每日流程跑。

詳細清單見 [`../報告守則.md`](../報告守則.md) 第 16 節。

### 移植時最容易漏的三件事

1. **面額變更／股票分割**：新組合若有 1 股拆 N 股的個股，必須查出換發基準日填進 `config.SPLIT`。**漏掉會讓 EPS 年增率失真 N 倍**（Yahoo 頁面顯示的年增率本身就沒調整）。
2. **大戶門檻**：`inputs/chips.py` 的 `CONC_THRESHOLD` 必須逐檔讀頁面表頭，**不可假設都是 400 張**。
3. **大盤環境分是全組共用的**：同一天不同組合的 `ENV_SCORE` 應該一致，若兩個 repo 同日產出而環境分不同，其中一份算錯了。

---

## 設計上的注意事項（動程式前先讀）

- **單一自足**：`報告樣式.css` 是整段內嵌到 `<style>`，不可改用 `<link>` 外連。
- **半進位**：分數一律 `lib.half_up()`＝`floor(x+0.5)`，不要用 Python 內建 `round`（銀行家捨入）。
- **大盤面分不主觀給分**：`build_report.py` 會用公式覆寫 `scores.py` 裡的第 4 個值，手填無效。
- **`<nav>` 必須是 `ul > li > a`**，裸 `<a>` 會讓導覽列變直排。
- **`.meta` 是 grid 卡片容器**，子元素須為 `<div><span>標籤</span><b>值</b></div>`。
- **`.ovh` 與 `.ovr` 是兩個獨立 grid 容器**，欄寬必須用固定像素才會對齊。
- **欄位少的表格**要加 `.tnarrow`（3 欄再加 `.tn3`），否則會撐滿整頁。
- **寫入順序**：個股報告 → 首頁 → `COMMIT_MSG.txt`。`finalize.py` 已內建 1.2 秒間隔確保 mtime 可區分。
