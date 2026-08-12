# -*- coding: utf-8 -*-
"""RWD 驗證：360 / 390 / 768 / 1280px 四個寬度檢查橫向溢出與標題重疊
   ★ 移植時不用改。

   前置：pip install playwright && python -m playwright install chromium
   註：Claude in Chrome 擴充套件無法開 file://，RWD 驗證只能走 Playwright。
"""
import os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import config as C
from playwright.sync_api import sync_playwright

URL = "file:///" + os.path.join(C.REPO, C.YMD, "index.html").replace("\\", "/")
WIDTHS = [360, 390, 768, 1280]
fail = 0

with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
    for w in WIDTHS:
        pg = b.new_page(viewport={"width": w, "height": 900})
        pg.goto(URL, wait_until="load")
        pg.wait_for_timeout(400)
        sw = pg.evaluate("document.documentElement.scrollWidth")
        iw = pg.evaluate("window.innerWidth")
        ok = sw <= iw
        fail += 0 if ok else 1
        print("%4dpx  scrollWidth=%-6d innerWidth=%-6d %s"
              % (w, sw, iw, "OK" if ok else "★橫向溢出"))
        if not ok:
            for x in pg.evaluate("""() => {
              const out=[];const lim=document.documentElement.clientWidth;
              document.querySelectorAll('*').forEach(e=>{const r=e.getBoundingClientRect();
                if(r.right>lim+1||r.left<-1)
                  out.push((e.tagName+'.'+(e.className||'')).slice(0,60)+' right='+Math.round(r.right));});
              return out.slice(0,12);}"""):
                print("        溢出元素:", x)
        ov = pg.evaluate("""() => {
          const hs=[...document.querySelectorAll('#market h2, #market h3, .cnm, .sect')];
          const bad=[];
          for(let i=0;i<hs.length-1;i++){
            const a=hs[i].getBoundingClientRect(), b=hs[i+1].getBoundingClientRect();
            if(a.bottom>b.top+2 && a.top<b.bottom-2 && a.right>b.left+2 && a.left<b.right-2)
              bad.push(hs[i].textContent.trim().slice(0,20));}
          return bad;}""")
        leak = pg.evaluate("() => [...document.querySelectorAll('table')]"
                           ".filter(t=>!t.closest('.twrap')).length")
        print("        標題重疊：%s｜未包在 .twrap 的表格：%d"
              % ("無" if not ov else ov, leak))
        if leak:
            fail += 1
        pg.close()
    b.close()

print("\n結果：", "四個寬度全部通過" if fail == 0 else "★有 %d 項未通過，需修到全過才交付" % fail)
sys.exit(1 if fail else 0)
