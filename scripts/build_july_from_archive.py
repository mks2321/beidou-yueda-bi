#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性：从"多月份归档表"(1EjN4Mg...)的 7月块 读产品+每日数据，写入 index.html 的 '7月' monthConfigs。
该表无目标/预算 -> target/budget=0。个人投放/订单仍停在6月，7月保持空。
"""
import csv, re, io, urllib.request, sys

ARCH = '1EjN4Mg3K_dxJwiZhU_BleCtk3cYgxFpW3wpEfck22bI'
GID_PAID, GID_FREE = '0', '1121068973'
DPREFIX = '07'

PAID_MAP = {'抖音Max':'良淫（抖阴Max）','51动漫':'51动漫','PornHub':'Pornhub中文版','91PORN':'91Pron',
    '91短视频':'91短视频','暗网禁区':'暗网禁区','萝莉岛APP':'萝莉岛APP','51品茶':'51品茶','海角乱伦社区':'海角乱伦社区',
    'TikTok成人版':'TikTok成人版','AI色色':'Al色色','91妻友':'妻友','草榴社区':'草榴社区',
    '91鬼父DX-106':'91鬼父DX-106','小黄片DX-106(原91鬼父)':'91鬼父DX-106','17禁漫天堂':'禁漫天堂','洛丽塔':'洛丽塔'}
FREE_MAP = {'51TikTok破解':'51tiktok破解','Pornhub免费版':'pornhub免费版','91成人盒子[GA]':'91成人盒子'}
STOP = {'', '收费', '免费', '总数', '目标', '合计', '产品'}

def fetch(gid):
    url = f'https://docs.google.com/spreadsheets/d/{ARCH}/export?format=csv&gid={gid}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    raw = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')
    return list(csv.reader(io.StringIO(raw)))

def num(s):
    s = (s or '').strip().replace(',', '').replace('%', '')
    if s == '':
        return 0
    try:
        f = float(s); return int(f) if f == int(f) else round(f, 2)
    except ValueError:
        return 0

def map_name(sn, mp):
    if sn in mp:
        return mp[sn]
    return re.sub(r'^\d+', '', sn).strip()

def find_block(rows):
    """返回7月块的子表头行索引(col0=='产品编号')"""
    for i, r in enumerate(rows):
        if r and r[0].strip() == '产品编号':
            return i
    sys.exit('[ERROR] 找不到子表头 产品编号')

def parse_paid(rows):
    hi = find_block(rows)
    out = []
    for r in rows[hi+1:]:
        nm_raw = (r[1].strip() if len(r) > 1 else '')
        if r[0].strip() in STOP and nm_raw == '':
            break
        if nm_raw == '' or nm_raw in STOP:
            break
        nm = map_name(nm_raw, PAID_MAP)
        total = num(r[2]); consume = num(r[6])
        daily = []
        for N in range(1, 32):
            nc = 7 + (N-1)*7
            if nc >= len(r) or (r[nc] or '').strip() == '':
                break
            daily.append((N, num(r[nc]), num(r[13+(N-1)*7]) if 13+(N-1)*7 < len(r) else 0,
                             num(r[11+(N-1)*7]) if 11+(N-1)*7 < len(r) else 0))
        out.append(build(nm, '付费', total, consume, daily, rtotal_check=num(r[5])))
    return out

def parse_free(rows):
    hi = find_block(rows)
    out = []
    for r in rows[hi+1:]:
        nm_raw = (r[1].strip() if len(r) > 1 else '')
        if nm_raw == '' or nm_raw in STOP:
            break
        nm = map_name(nm_raw, FREE_MAP)
        total = num(r[2]); consume = num(r[3])
        daily = []
        for N in range(1, 32):
            nc = 5 + (N-1)*4
            if nc >= len(r) or (r[nc] or '').strip() == '':
                break
            daily.append((N, num(r[nc]), num(r[7+(N-1)*4]) if 7+(N-1)*4 < len(r) else 0, 0))
        out.append(build(nm, '免费', total, consume, daily, rtotal_check=None))
    return out

def build(nm, typ, total, consume, daily, rtotal_check):
    s = sum(x[1] for x in daily)
    if s != total:
        print(f'[WARN] {nm} 每日新增和 {s} != 总新增 {total}')
    w1 = sum(x[1] for x in daily if x[0] <= 7)
    w2 = sum(x[1] for x in daily if 8 <= x[0] <= 14)
    cpa = round(consume/total, 2) if total > 0 else 0
    return dict(name=nm, type=typ, target=0, budget=0, w1=w1, w2=w2, total=total,
                consume=consume, completion=0, consumeRate=0, cpa=cpa,
                daily=[(f'{DPREFIX}-{d:02d}', nv, qv, rv) for d, nv, qv, rv in daily])

def js_products(allp):
    return '\n'.join(
        "    { name:'%s', type:'%s', target:%s, budget:%s, w1:%s, w2:%s, total:%s, consume:%s, completion:%s, consumeRate:%s, cpa:%s }," %
        (p['name'], p['type'], p['target'], p['budget'], p['w1'], p['w2'], p['total'], p['consume'],
         p['completion'], p['consumeRate'], p['cpa']) for p in allp)

def js_pdata(allp):
    out = []
    for p in allp:
        arr = ", ".join('["%s", %s, %s, %s]' % (d, n, q, rv) for d, n, q, rv in p['daily'])
        out.append("    '%s': [%s]," % (p['name'], arr))
    return '\n'.join(out)

def replace_inner(block, start, end, inner):
    s = block.index(start) + len(start); e = block.index(end, s)
    return block[:s] + inner + block[e:]

def main():
    paid = parse_paid(fetch(GID_PAID))
    free = parse_free(fetch(GID_FREE))
    allp = paid + free
    print(f'[解析] 付费{len(paid)} 免费{len(free)} 共{len(allp)}个产品; '
          f'日数={len(allp[0]["daily"]) if allp else 0}')
    for p in allp:
        print(f'  {p["name"]}({p["type"]}) total={p["total"]} consume={p["consume"]} cpa={p["cpa"]} 天数={len(p["daily"])}')

    html = open('index.html', encoding='utf-8').read()
    six = html.index("'7月': {")
    nexts = [m.start() for m in re.finditer(r"'\d+月': \{", html) if m.start() > six]
    end = min(nexts) if nexts else html.index('\n};', six)
    block = html[six:end]
    if 'products: [\n    ],' in block:  # 空框架
        block = block.replace('products: [\n    ],', 'products: [\n' + js_products(allp) + '\n    ],')
        block = block.replace('dailyData: {\n    },', 'dailyData: {\n' + js_pdata(allp) + '\n    },')
    else:  # 已有数据, 替换内部
        block = replace_inner(block, 'products: [\n', '\n    ],', js_products(allp))
        block = replace_inner(block, 'dailyData: {\n', '\n    },', js_pdata(allp))
    html = html[:six] + block + html[end:]
    open('index.html', 'w', encoding='utf-8').write(html)
    print('[写入] 7月 products/dailyData 完成')

if __name__ == '__main__':
    main()
