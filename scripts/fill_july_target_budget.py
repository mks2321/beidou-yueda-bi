#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从"7月目标预算表"(1MpRaGyw...)回填 index.html 7月产品的 target/budget，并重算 completion/consumeRate。
收费(gid=0): target=col2(新增) budget=col4(开支预算)
免费(sheet=免费APP): target=col2 budget=col3
以"总新增"(收费col5/免费col5)为匹配键，规避名字差异(萝莉岛APP vs 洛丽塔)。
"""
import csv, re, io, urllib.request, urllib.parse

SID = '1MpRaGywYplqHzUiCzT2ecp5WBKeih4xHgouc7XNNoEQ'

def num(s):
    s = (s or '').strip().replace(',', '').replace('%', '')
    if s == '':
        return 0
    try:
        f = float(s); return int(f) if f == int(f) else round(f, 2)
    except ValueError:
        return 0

def fetch_gid(gid):
    url = f'https://docs.google.com/spreadsheets/d/{SID}/export?format=csv&gid={gid}'
    return _get(url)

def fetch_sheet(name):
    url = f'https://docs.google.com/spreadsheets/d/{SID}/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(name)}'
    return _get(url)

def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    raw = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')
    return list(csv.reader(io.StringIO(raw)))

# key: 总新增 -> (target, budget)
tb = {}
paid = fetch_gid('0')
for r in paid[2:]:
    if len(r) < 6 or not r[1].strip() or not r[0].strip().startswith('DX'):
        continue
    total = num(r[5])
    tb[total] = (num(r[2]), num(r[4]))   # 收费: 新增目标, 开支预算
free = fetch_sheet('免费APP')
for r in free[2:]:
    if len(r) < 6 or not r[1].strip() or not r[0].strip().startswith('DX'):
        continue
    total = num(r[5])
    tb[total] = (num(r[2]), num(r[3]))   # 免费: 目标, 开支预算

print(f'[目标预算] 收集 {len(tb)} 个产品')

html = open('index.html', encoding='utf-8').read()
six = html.index("'7月': {")
end = html.index('dailyData:', six)
block = html[six:end]

PROD = re.compile(r"\{ name:'([^']*)', type:'([^']*)', target:(\d+), budget:(\d+), "
                  r"w1:(\d+), w2:(\d+), total:(\d+), consume:(\d+(?:\.\d+)?), "
                  r"completion:([\d.]+), consumeRate:([\d.]+), cpa:([\d.]+) \}")

miss = []
def repl(m):
    name, typ = m.group(1), m.group(2)
    w1, w2, total, consume, cpa = m.group(5), m.group(6), int(m.group(7)), float(m.group(8)), m.group(11)
    if total not in tb:
        miss.append(name)
        return m.group(0)
    target, budget = tb[total]
    comp = round(total/target*100, 2) if target > 0 else 0
    crate = round(consume/budget*100, 2) if budget > 0 else 0
    consume_s = int(consume) if consume == int(consume) else consume
    return ("{ name:'%s', type:'%s', target:%s, budget:%s, w1:%s, w2:%s, total:%s, consume:%s, "
            "completion:%s, consumeRate:%s, cpa:%s }" %
            (name, typ, target, budget, w1, w2, total, consume_s, comp, crate, cpa))

newblock, n = PROD.subn(repl, block)
print(f'[回填] 更新 {n} 个产品行' + (f'; 未匹配: {miss}' if miss else ''))
html = html[:six] + newblock + html[end:]
open('index.html', 'w', encoding='utf-8').write(html)
print('[写入] 完成')
