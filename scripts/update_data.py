#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北斗悦达BI看板 · 当月数据自动更新（GitHub Actions 调用）
拉取 5 张 Google Sheets，全量重建当月 personalData / orders / products / dailyData，
按表头名字动态定位列（抗结构变化），校验通过后写回 index.html。
不提交（commit/push 由 workflow 负责）。校验失败 -> 退出码 1（workflow 不提交）。
"""
import csv, re, io, sys, urllib.request, subprocess, datetime

SHEETS = {
    # 个人（充值/盒子）：2026-07 起改用新表 1M3-...
    'charge': ('1M3-Jtwos2hujBVsl9WwzqMzog1i1RugCo4hBh1mK3sY', '0'),
    'box':    ('1M3-Jtwos2hujBVsl9WwzqMzog1i1RugCo4hBh1mK3sY', '174527901'),
    'orders': ('1mob_aU-Y4v-jycMFjLSQekEwEISrI92Z6KTpW5Nb0D4', '0'),  # 7月订单/请款流水
    # 收费产品：每日明细+总数 来自新表 1EjN(按月分区)；目标/预算 来自 7月产品目标表 1MpRa(按产品编号关联)
    'prodPD': ('1EjN4Mg3K_dxJwiZhU_BleCtk3cYgxFpW3wpEfck22bI', '0'),
    'prodTB': ('1MpRaGywYplqHzUiCzT2ecp5WBKeih4xHgouc7XNNoEQ', '0'),
    # 免费产品：7月表 1MpRa 的免费APP页（旧格式，含每日+目标+预算）
    'prodPF': ('1MpRaGywYplqHzUiCzT2ecp5WBKeih4xHgouc7XNNoEQ', '1210097737'),
}

def fetch(key):
    sid, gid = SHEETS[key]
    url = f'https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    raw = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')
    if raw.lstrip().lower().startswith('<!doctype') or '<html' in raw[:200].lower():
        sys.exit(f'[ERROR] 表 {key} 拉到的是HTML/登录页，可能公开权限被关闭。')
    return list(csv.reader(io.StringIO(raw)))

def num(s):
    s = (s or '').strip().replace(',', '').replace('%', '')
    if s == '':
        return 0
    try:
        f = float(s)
        return int(f) if f == int(f) else round(f, 2)
    except ValueError:
        return 0

def pct(s):
    s = (s or '').strip().replace('%', '')
    try:
        return round(float(s), 2)
    except ValueError:
        return 0

def norm(s):
    return re.sub(r'\s+', '', (s or '').strip())

# ---------- 个人表（按名字行动态定位） ----------
CHARGE_NAMES = {norm(a): b for a, b in [
    ('马奎斯','马奎斯'),('李漫妮','李漫妮'),('赵尘','赵尘'),('范玮琪','范玮琪'),('王勃','王勃'),
    ('双喜 / 聂淮序','双喜/聂淮序'),('聂淮序','双喜/聂淮序'),('张伟','张伟'),('渠道中心','渠道中心'),
    ('无极导量','无极导量'),('内部导量','内部导量')]}
BOX_NAMES = {norm(a): b for a, b in [('张伟 (金予)','张伟(金予)'), ('金予','张伟(金予)'), ('尹森','尹森')]}

def parse_personal(rows, name_map, mlabel):
    namerow = rows[0]
    cols = []
    for i, v in enumerate(namerow):
        k = norm(v)
        if k in name_map:
            cols.append((name_map[k], i))
    total_col = rtot_col = None
    for r in rows:
        for ci, c in enumerate(r):
            if c.strip() == '新增总计':
                total_col = ci
            elif c.strip() == '充值总计':
                rtot_col = ci
        if total_col is not None and rtot_col is not None:
            break
    def findrow(key):
        for r in rows:
            if r and r[0].strip() == key:
                return r
        return None
    tgt, rate, tot = findrow('月目标'), findrow('达成率'), findrow('合计')
    days = {}
    for r in rows:
        if not r:
            continue
        m = re.match(rf'^{mlabel}(\d+)日$', r[0].strip())
        if m:
            days[int(m.group(1))] = r
    return cols, total_col, rtot_col, tgt, rate, tot, days

def build_personal(charge, box, mlabel, dprefix):
    c_cols, c_tot, c_rtot, c_tgt, c_rate, c_total, c_days = parse_personal(charge, CHARGE_NAMES, mlabel)
    b_cols, b_tot, b_rtot, b_tgt, b_rate, b_total, b_days = parse_personal(box, BOX_NAMES, mlabel)
    people = []
    for nm, ci in c_cols:
        people.append(dict(name=nm, target=num(c_tgt[ci]), actual=num(c_total[ci]),
                           recharge=num(c_total[ci+1]), expense=num(c_total[ci+2]),
                           completion=pct(c_rate[ci])))
    for nm, ci in b_cols:
        people.append(dict(name=nm, target=num(b_tgt[ci]), actual=num(b_total[ci]),
                           recharge=num(b_total[ci+1]), expense=num(b_total[ci+2]),
                           completion=pct(b_rate[ci])))
    names = [p['name'] for p in people]
    daily = []
    for d in sorted(set(c_days) | set(b_days)):
        cr, br = c_days.get(d), b_days.get(d)
        ct = num(cr[c_tot]) if cr else 0
        bt = num(br[b_tot]) if br else 0
        if ct == 0 and bt == 0:
            continue
        cr_rt = num(cr[c_rtot]) if (cr and c_rtot is not None) else 0
        br_rt = num(br[b_rtot]) if (br and b_rtot is not None) else 0
        e = {'date': f'{dprefix}-{d:02d}', 'total': ct + bt, 'rtotal': cr_rt + br_rt, 'r': {}}
        for nm, ci in c_cols:
            e[nm] = num(cr[ci]) if cr else 0
            e['r'][nm] = num(cr[ci+1]) if cr else 0
        for nm, ci in b_cols:
            e[nm] = num(br[ci]) if br else 0
            e['r'][nm] = num(br[ci+1]) if br else 0
        daily.append(e)
    # 校验
    for e in daily:
        s = sum(e[n] for n in names)
        if s != e['total']:
            sys.exit(f'[ERROR] 个人 {e["date"]} 人均之和 {s} != total {e["total"]}（列定位可能错位）')
        rs = sum(e['r'][n] for n in names)
        if rs != e['rtotal']:
            sys.exit(f'[ERROR] 个人 {e["date"]} 充值人均之和 {rs} != 充值总计 {e["rtotal"]}（列定位可能错位）')
    for p in people:
        s = sum(e[p['name']] for e in daily)
        if s != p['actual']:
            sys.exit(f'[ERROR] 个人 {p["name"]} 累加 {s} != actual {p["actual"]}')
        rsum = sum(e['r'][p['name']] for e in daily)
        if rsum != p['recharge']:
            sys.exit(f'[ERROR] 个人 {p["name"]} 充值累加 {rsum} != recharge {p["recharge"]}')
    return people, daily, names

# ---------- 订单 ----------
def build_orders(rows):
    out = []
    for r in rows[1:]:
        if len(r) < 14 or not r[1].strip():
            continue
        out.append([r[1].strip(), r[2].strip(), r[3].strip(), r[4].strip(), r[5].strip(),
                    r[6].strip(), r[7].strip(), num(r[9]), num(r[12]), num(r[13])])
    return out

# ---------- 产品 ----------
PAID_MAP = {'抖音Max':'良淫（抖阴Max）','51动漫':'51动漫','PornHub':'Pornhub中文版','91PORN':'91Pron',
    '91短视频':'91短视频','暗网禁区':'暗网禁区','萝莉岛APP':'萝莉岛APP','51品茶':'51品茶','海角乱伦社区':'海角乱伦社区',
    'TikTok成人版':'TikTok成人版','AI色色':'Al色色','91妻友':'妻友','草榴社区':'草榴社区',
    '91鬼父DX-106':'91鬼父DX-106','小黄片DX-106(原91鬼父)':'91鬼父DX-106','17禁漫天堂':'禁漫天堂'}
FREE_MAP = {'51TikTok破解':'51tiktok破解','Pornhub免费版':'pornhub免费版','91成人盒子[GA]':'91成人盒子'}

def map_name(sheet_name, mp):
    if sheet_name in mp:
        return mp[sheet_name]
    return re.sub(r'^\d+', '', sheet_name).strip()  # 新产品：去掉开头年龄分级数字

def parse_products(rows, typ, total_i, consume_i, dn, dq, dr, rtot_i, dprefix):
    out = []
    mp = PAID_MAP if typ == '付费' else FREE_MAP
    for r in rows[2:]:
        if len(r) < 10 or not r[1].strip():
            continue
        sn = r[1].strip()
        if sn.startswith('6月') or sn.startswith('5月'):
            continue
        nm = map_name(sn, mp)
        target = num(r[2])
        budget = num(r[4]) if typ == '付费' else num(r[3])
        total = num(r[total_i])
        consume = num(r[consume_i])
        daily = []
        w = [0, 0]
        started = False
        for d in range(1, 32):
            nc = dn(d)
            if nc >= len(r):
                break
            if (r[nc] or '').strip() in ('', '无数据'):
                if started:
                    break          # 数据结束
                continue           # 前导空日：新产品上线前的空白，跳过、只采有值的天
            started = True
            nv = num(r[nc])
            qv = num(r[dq(d)]) if dq(d) < len(r) else 0
            rc = dr(d) if dr else -1
            rv = num(r[rc]) if (dr and 0 <= rc < len(r)) else 0
            daily.append((d, nv, qv, rv))
            if d <= 7: w[0] += nv
            elif d <= 14: w[1] += nv
        # 付费产品校验每日充值之和 = 总充值列
        if rtot_i is not None:
            rsum = sum(x[3] for x in daily)
            rtot = num(r[rtot_i])
            if rsum != rtot:
                sys.exit(f'[ERROR] 产品 {nm} 每日充值和 {rsum} != 总充值 {rtot}（充值列定位可能错位）')
        comp = round(total/target*100, 2) if target > 0 else 0
        crate = round(consume/budget*100, 2) if budget > 0 else 0
        cpa = round(consume/total, 2) if total > 0 else 0
        out.append(dict(name=nm, type=typ, target=target, budget=budget, w1=w[0], w2=w[1],
                        total=total, consume=consume, completion=comp, consumeRate=crate, cpa=cpa,
                        daily=[(f'{dprefix}-{d:02d}', nv, qv, rv) for d, nv, qv, rv in daily]))
    return out

# ---------- 收费产品：目标/预算取自原表(按产品编号)，每日明细取自新表 ----------
def build_tb(tb_rows):
    """原收费表 1YTv：产品编号 -> (target, budget, origname)。列: [2]新增目标 [4]开支预算。"""
    m = {}
    for r in tb_rows[2:]:
        if len(r) < 5 or not r[0].strip():
            continue
        code = r[0].strip()
        if not code.startswith('DX'):
            continue
        m[code] = (num(r[2]), num(r[4]), r[1].strip())
    return m

def parse_paid_new(rows, tb, mlabel, dprefix):
    """新收费表 1EjN（按月分区）。当月段结构：
       [0]编号 [1]名 [2]总新增 [3]总VIP [4]总金币 [5]总充值(可能#VALUE!) [6]总请款，
       每日 7 列块从 [7] 起：新增,新增环比,VIP,金币,总充值,充值环比,请款。
       目标/预算按产品编号从原表取；总充值 = VIP+金币（绕过表内 #VALUE!）。"""
    label = f'{mlabel}-收费APP'
    start = None
    for i, r in enumerate(rows):
        if r and r[0].strip() == label:
            start = i + 2   # 跳过段标题行 + 子表头行
            break
    if start is None:
        sys.exit(f'[ERROR] 新收费表找不到当月段 “{label}”')
    out = []
    for r in rows[start:]:
        code = r[0].strip() if r else ''
        if not code.startswith('DX'):
            break   # 段结束（遇到空行/汇总行）
        total = num(r[2]); vip = num(r[3]); coin = num(r[4]); consume = num(r[6])
        recharge = vip + coin
        daily = []
        w = [0, 0]
        started = False
        for d in range(1, 32):
            nc = 7 + (d-1)*7
            if nc >= len(r):
                break
            if (r[nc] or '').strip() in ('', '无数据'):
                if started:
                    break          # 数据结束
                continue           # 前导空日：新产品上线前的空白，跳过、只采有值的天
            started = True
            nv = num(r[nc])
            rc = 11 + (d-1)*7
            qc = 13 + (d-1)*7
            rv = num(r[rc]) if rc < len(r) else 0
            qv = num(r[qc]) if qc < len(r) else 0
            daily.append((d, nv, qv, rv))
            if d <= 7: w[0] += nv
            elif d <= 14: w[1] += nv
        # 校验：每日新增和=总新增（致命，看板要用total）
        s = sum(x[1] for x in daily)
        if s != total:
            sys.exit(f'[ERROR] 收费产品 {code} 每日新增和 {s} != 总新增 {total}')
        # 每日总充值和 vs VIP+金币：看板不使用此值，表内偶有不一致不应阻断更新，仅告警
        rsum = sum(x[3] for x in daily)
        if rsum != recharge:
            print(f'[WARN] 收费产品 {code} 每日总充值和 {rsum} != VIP+金币 {recharge}（表内不一致，看板不用此值，跳过）')
        if code not in tb:
            sys.exit(f'[ERROR] 收费产品 {code}({r[1].strip()}) 在原表找不到目标/预算')
        target, budget, origname = tb[code]
        nm = map_name(origname, PAID_MAP)   # 用原表名保持看板命名一致
        comp = round(total/target*100, 2) if target > 0 else 0
        crate = round(consume/budget*100, 2) if budget > 0 else 0
        cpa = round(consume/total, 2) if total > 0 else 0
        out.append(dict(name=nm, type='付费', target=target, budget=budget, w1=w[0], w2=w[1],
                        total=total, consume=consume, completion=comp, consumeRate=crate, cpa=cpa,
                        daily=[(f'{dprefix}-{dd:02d}', nv, qv, rv) for dd, nv, qv, rv in daily]))
    return out

def build_products(pd, tb_rows, pf, dprefix, mlabel):
    tb = build_tb(tb_rows)
    paid = parse_paid_new(pd, tb, mlabel, dprefix)
    free = parse_products(pf, '免费', 5, 6, lambda d: 8+(d-1)*4, lambda d: 10+(d-1)*4, None, None, dprefix)
    allp = paid + free
    for p in allp:
        s = sum(x[1] for x in p['daily'])
        if s != p['total']:
            sys.exit(f'[ERROR] 产品 {p["name"]} daily和 {s} != total {p["total"]}')
    return allp

# ---------- JS 生成 ----------
def js_people(people):
    return '\n'.join(
        "        { name:'%s', target:%s, actual:%s, recharge:%s, expense:%s, completion:%s }," %
        (p['name'], p['target'], p['actual'], p['recharge'], p['expense'], p['completion'])
        for p in people)

def js_pdaily(daily, names):
    def key(n):
        return f"'{n}'" if re.search(r'[\/()]', n) else n
    lines = []
    for e in daily:
        parts = [f"date:'{e['date']}'", f"total:{e['total']}", f"rtotal:{e['rtotal']}"]
        for n in names:
            parts.append(f"{key(n)}:{e[n]}")
        rparts = ", ".join(f"{key(n)}:{e['r'][n]}" for n in names)
        parts.append("r:{ " + rparts + " }")
        lines.append("        { " + ", ".join(parts) + " },")
    return '\n'.join(lines)

def js_orders(ords, varname):
    def jv(x):
        return f"'{x}'" if isinstance(x, str) else str(x)
    body = ',\n'.join("  [" + ",".join(jv(x) for x in o) + "]" for o in ords)
    return f"const {varname} = [\n{body}\n];"

def js_products(allp):
    return '\n'.join(
        "    { name:'%s', type:'%s', target:%s, budget:%s, w1:%s, w2:%s, total:%s, consume:%s, completion:%s, consumeRate:%s, cpa:%s }," %
        (p['name'], p['type'], p['target'], p['budget'], p['w1'], p['w2'], p['total'], p['consume'],
         p['completion'], p['consumeRate'], p['cpa'])
        for p in allp)

def js_pdata(allp):
    out = []
    for p in allp:
        arr = ", ".join('["%s", %s, %s, %s]' % (d, n, q, rv) for d, n, q, rv in p['daily'])
        out.append("    '%s': [%s]," % (p['name'], arr))
    return '\n'.join(out)

def replace_inner(block, start_marker, end_marker, new_inner):
    s = block.index(start_marker) + len(start_marker)
    e = block.index(end_marker, s)
    return block[:s] + new_inner + block[e:]

def main():
    html = open('index.html', encoding='utf-8').read()
    m = re.search(r"let currentMonth = '(\d+)月'", html)
    if not m:
        sys.exit('[ERROR] 找不到 currentMonth')
    mnum = int(m.group(1))
    mlabel = f'{mnum}月'
    dprefix = f'{mnum:02d}'
    if f"'{mlabel}': {{" not in html:
        sys.exit(f'[ERROR] monthConfigs 无当月键 {mlabel}，需手工建框架')

    charge = fetch('charge'); box = fetch('box'); orders_raw = fetch('orders')
    pd = fetch('prodPD'); tb = fetch('prodTB'); pf = fetch('prodPF')

    people, pdaily, names = build_personal(charge, box, mlabel, dprefix)
    ords = build_orders(orders_raw)
    allp = build_products(pd, tb, pf, dprefix, mlabel)

    # 当月块边界
    six = html.index(f"'{mlabel}': {{")
    nexts = [mm.start() for mm in re.finditer(r"'\d+月': \{", html) if mm.start() > six]
    end = min(nexts) if nexts else html.index('\n};', six)
    block = html[six:end]

    # orders 变量名
    om = re.search(r"orders:\s*([A-Za-z_]\w*)", block)
    ovar = om.group(1) if om else 'ordersJun'

    # 先只替换数据（不动 lastUpdated），用于判断数据是否真的变化
    block = replace_inner(block, 'products: [\n', '\n    ],', js_products(allp))
    block = replace_inner(block, 'dailyData: {\n', '\n    },', js_pdata(allp))
    block = replace_inner(block, 'personalData: {\n', '\n    },',
                          '      people: [\n' + js_people(people) + '\n      ],\n      daily: [\n' +
                          js_pdaily(pdaily, names) + '\n      ]')
    html_new = html[:six] + block + html[end:]
    html_new = re.sub(rf"const {ovar} = \[[\s\S]*?\];", js_orders(ords, ovar), html_new, count=1)

    if html_new == html:
        print(f'[OK] {mlabel} 数据无变化，未写入（个人{len(people)}人 产品{len(allp)}个 订单{len(ords)}条）')
        return

    # 数据有变化 -> 刷新当月 lastUpdated 为当前北京时间
    bj = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
    s2 = html_new.index(f"'{mlabel}': {{")
    nx = [mm.start() for mm in re.finditer(r"'\d+月': \{", html_new) if mm.start() > s2]
    e2 = min(nx) if nx else html_new.index('\n};', s2)
    blk2 = re.sub(r"lastUpdated: '[^']*'", f"lastUpdated: '{bj}'", html_new[s2:e2], count=1)
    html_new = html_new[:s2] + blk2 + html_new[e2:]

    open('index.html', 'w', encoding='utf-8').write(html_new)
    html = html_new

    # node 语法校验
    chk = subprocess.run(
        ["node", "-e",
         "const t=require('fs').readFileSync('index.html','utf8');"
         "const b=[...t.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)].map(x=>x[1]).join('\\n;\\n');"
         "require('vm').compileFunction(b);"],
        capture_output=True, text=True)
    if chk.returncode != 0:
        sys.exit('[ERROR] node 语法校验失败:\n' + chk.stderr)

    print(f'[OK] {mlabel} 个人{len(people)}人 产品{len(allp)}个 订单{len(ords)}条 '
          f'个人末日{pdaily[-1]["date"] if pdaily else "-"} lastUpdated={bj}')

if __name__ == '__main__':
    main()
