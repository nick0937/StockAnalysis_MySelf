# -*- coding: utf-8 -*-
"""★ 只保留最新 N 個開盤日的報告資料夾，超出的直接刪除（守則第 12.1 節，2026-08-27 使用者指示）

用途：每次跑今日／昨日報告之前先執行，避免 `YYYYMMDD/` 無限累積、首頁歷史卡片越來越長。
      `build_report.py` 開頭會自動呼叫本檔，所以正常流程不需要手動跑。

規則：
  ・只管 repo 根目錄下符合 `\\d{8}` 的報告資料夾，<b>其餘一律不碰</b>
    （data/、inputs/、live/、index.html、COMMIT_MSG.txt 都不在範圍內）。
  ・保留最新 KEEP 個（依資料夾名排序，就是開盤日順序），其餘整個資料夾刪除。
  ・刪除後 `finalize.py` 會用 `os.listdir` 重掃，首頁的歷史卡片自動同步成 KEEP 期。

⚠ 為什麼可以直接刪：報告資料夾每期都由使用者雙擊「建立Commit.bat」進版控，
  刪掉之後仍可用 `git checkout <commit> -- <資料夾>` 取回；但線上 GitHub Pages 的那一頁會消失。
  → 因此本檔<b>只刪已進版控的資料夾</b>；未 commit 的會跳過並印警告，避免真的弄丟。

⚠ 不在本檔範圍內、也不該砍到 10 天的東西（血淚提醒）：
  ・`data/raw/*.json` 是 Yahoo range=2y 的單一檔案、每次覆寫，
    <b>240 日均線、52 週高低、60 日 Beta 都需要兩年歷史</b>，砍了報告就算不出來。
  ・`inputs/chips.py` 的法人／資券／主力表本來就固定 10 列、大戶表 13 週（守則要求），
    由每期補新列砍最舊列維護，不由本檔處理。
"""
import os
import re
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import config as C

KEEP = 10          # ★ 保留最新幾個開盤日的報告資料夾


def _in_git(repo, name):
    """該資料夾是否已進版控（決定刪掉之後還能不能取回）。"""
    try:
        r = subprocess.run(["git", "log", "--oneline", "-1", "--", name + "/"],
                           cwd=repo, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return bool((r.stdout or "").strip())
    except Exception:
        return False


def prune(repo=None, keep=KEEP, quiet=False):
    """回傳 (deleted, skipped)。deleted 為已刪除的資料夾名稱清單。"""
    repo = repo or C.REPO
    dirs = sorted(d for d in os.listdir(repo)
                  if re.fullmatch(r"\d{8}", d) and os.path.isdir(os.path.join(repo, d)))
    over = dirs[:-keep] if len(dirs) > keep else []

    if not quiet:
        print("[0] 報告資料夾保留檢查（守則 §12.1：只留最新 %d 個開盤日）" % keep)
        print("    現有 %d 份，最新 %d 份保留：%s"
              % (len(dirs), min(keep, len(dirs)), "、".join(dirs[-keep:]) or "（無）"))

    if not over:
        if not quiet:
            print("    結果： 沒有超出 %d 天的資料夾，不需刪除" % keep)
        return [], []

    deleted, skipped = [], []
    for d in over:
        if not _in_git(repo, d):
            skipped.append(d)
            if not quiet:
                print("    ★ 跳過 %s —— <b>尚未 commit</b>，刪掉就取不回，本檔不動它" % d)
            continue
        shutil.rmtree(os.path.join(repo, d))
        deleted.append(d)
        if not quiet:
            print("    ✅ 已刪除 %s（已進版控，可用 git checkout 取回）" % d)

    if not quiet:
        print("    結果： 刪除 %d 份、跳過 %d 份；首頁的歷史卡片會由 finalize.py 自動同步"
              % (len(deleted), len(skipped)))
        if skipped:
            print("    ⚠ 跳過的請先讓使用者雙擊「建立Commit.bat」進版控，下次執行才會刪")
    return deleted, skipped


if __name__ == "__main__":
    d, s = prune()
    print()
    print("刪除：%s" % ("、".join(d) if d else "無"))
    print("跳過：%s" % ("、".join(s) if s else "無"))
