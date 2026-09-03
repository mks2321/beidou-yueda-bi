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
    # 2026-09：个人表「9月-渠道投放每日业绩」两 tab：收费段 gid0 / 免费段 gid122581593（每人4列 新增/充值/请款/线路，同8月结构）
    'charge': ('13i4-Bvy36WdltmFGkakvON75BoTQLeoCbtfwKxHsGYw', '0'),
    'box':    ('13i4-Bvy36WdltmFGkakvON75BoTQLeoCbtfwKxHsGYw', '122581593'),
    'orders': ('1kwkeJX3OhaSYOcbV_1uAtc9Bk2bRzLrc0FM6WRo6x2Q', '0'),  # 9月订单/请款流水（18列同8月）
    # 收费+免费产品：老格式两段，含目标+预算+每日。段标题仍写「8月-…」，parse_month_section 按后缀匹配。
    'prodAll': ('1GLJvzh98by9PHGQj671jwZOneiF8cOk2GnQNuGTKTdE', '0'),
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
# 2026-09：个人表分「收费段」「免费段」。同时出现在两段的8人拆 xx(收费)/xx(免费)；收费专属4人不加后缀；悦达不收录(跳过)。
CHARGE_NAMES = {norm(a): b for a, b in [
    ('马奎斯','马奎斯'),('李漫妮','李漫妮'),('渠道中心','渠道中心'),('无极导量','无极导量'),
    ('赵尘','赵尘(收费)'),('范玮琪','范玮琪(收费)'),('王勃','王勃(收费)'),('聂淮序','聂淮序(收费)'),
    ('李蓓蓓','李蓓蓓(收费)'),('尹森','尹森(收费)'),('徐晃','徐晃(收费)'),('罗冰','罗冰(收费)')]}
BOX_NAMES = {norm(a): b for a, b in [
    ('尹森','尹森(免费)'),('徐晃','徐晃(免费)'),('罗冰','罗冰(免费)'),('赵尘','赵尘(免费)'),
    ('范玮琪','范玮琪(免费)'),('王勃','王勃(免费)'),('聂淮序','聂淮序(免费)'),('李蓓蓓','李蓓蓓(免费)')]}

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
    def exp_at(tot_row, ci):
        return num(tot_row[ci+2]) if (tot_row and ci+2 < len(tot_row)) else 0
    people = []
    for nm, ci in c_cols:
        people.append(dict(name=nm, target=num(c_tgt[ci]), expense=exp_at(c_total, ci)))
    for nm, ci in b_cols:
        people.append(dict(name=nm, target=num(b_tgt[ci]), expense=exp_at(b_total, ci)))
    names = [p['name'] for p in people]
    daily = []
    for d in sorted(set(c_days) | set(b_days)):
        cr, br = c_days.get(d), b_days.get(d)
        ct = num(cr[c_tot]) if cr else 0
        bt = num(br[b_tot]) if br else 0
        e = {'date': f'{dprefix}-{d:02d}', 'r': {}}
        for nm, ci in c_cols:
            e[nm] = num(cr[ci]) if cr else 0
            e['r'][nm] = num(cr[ci+1]) if cr else 0
        for nm, ci in b_cols:
            e[nm] = num(br[ci]) if br else 0
            e['r'][nm] = num(br[ci+1]) if br else 0
        # 每日总计按各人之和自动计算（表内“新增总计”列偶有填错/漏新人，不作准）
        e['total'] = sum(e[n] for n in names)
        e['rtotal'] = sum(e['r'][n] for n in names)
        if e['total'] == 0 and e['rtotal'] == 0:
            continue   # 空日
        if ct + bt and e['total'] != ct + bt:
            print(f'[WARN] 个人 {e["date"]} 人均之和 {e["total"]} != 表内新增总计 {ct + bt}（以人均之和为准）')
        daily.append(e)
    # 每人 actual/recharge/completion 由每日累加得出（月初“合计”行常未按人填）
    for p in people:
        p['actual'] = sum(e[p['name']] for e in daily)
        p['recharge'] = sum(e['r'][p['name']] for e in daily)
        p['completion'] = round(p['actual'] / p['target'] * 100, 2) if p['target'] > 0 else 0
    return people, daily, names

# ---------- 订单 ----------
def build_orders(rows):
    out = []
    for r in rows[1:]:
        if len(r) < 14 or not r[1].strip():
            continue
        note = r[17].strip() if len(r) > 17 else ''   # 备注列：内部/外部
        out.append([r[1].strip(), r[2].strip(), r[3].strip(), r[4].strip(), r[5].strip(),
                    r[6].strip(), r[7].strip(), num(r[9]), num(r[12]), num(r[13]), note])
    return out

# ---------- 产品 ----------
PAID_MAP = {'抖音Max':'良淫（抖阴Max）','51动漫':'51动漫','PornHub':'Pornhub中文版','91PORN':'91Pron',
    '91短视频':'91短视频','暗网禁区':'暗网禁区','萝莉岛APP':'萝莉岛APP','51品茶':'51品茶','海角乱伦社区':'海角乱伦社区',
    'TikTok成人版':'TikTok成人版','AI色色':'Al色色','91妻友':'妻友','草榴社区':'草榴社区',
    '91鬼父DX-106':'91鬼父DX-106','小黄片DX-106(原91鬼父)':'91鬼父DX-106','17禁漫天堂':'禁漫天堂'}
FREE_MAP = {'51TikTok破解':'51tiktok破解','Pornhub免费版':'pornhub免费版','91成人盒子[GA]':'91成人盒子',
    '91成人盒子[GA]片多多破解[91成人盒子GA]':'91成人盒子'}   # 9月改了全名，仍归一到 91成人盒子

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
        if code in tb:
            target, budget, origname = tb[code]
        else:
            # 新产品尚未加入目标预算表：暂记 0，不中止更新（补入 1MpRa 后自动生效）
            print(f'[WARN] 收费产品 {code}({r[1].strip()}) 目标表暂无目标/预算，暂记0')
            target, budget, origname = 0, 0, r[1].strip()
        nm = map_name(origname, PAID_MAP)   # 用目标表名保持看板命名一致
        comp = round(total/target*100, 2) if target > 0 else 0
        crate = round(consume/budget*100, 2) if budget > 0 else 0
        cpa = round(consume/total, 2) if total > 0 else 0
        out.append(dict(name=nm, type='付费', target=target, budget=budget, w1=w[0], w2=w[1],
                        total=total, consume=consume, completion=comp, consumeRate=crate, cpa=cpa,
                        daily=[(f'{dprefix}-{dd:02d}', nv, qv, rv) for dd, nv, qv, rv in daily]))
    return out

def parse_month_section(rows, label, typ, dprefix):
    """当月老格式产品表的一段(收费/免费)。列: [2]目标 [4]开支预算 [5]总新增 [9]总请款；
       每日7列块从[10]起：新增[10]，请款[16]，充值列(收费[14]/免费[15])。跳过前导空日。"""
    # 按后缀关键字匹配段标题（收费APP/免费盒子），忽略月份前缀——9月表段标题仍写「8月-…」
    key = norm(label.split('-')[-1])
    start = None
    for i, r in enumerate(rows):
        if r and r[0] and key in norm(r[0]):
            start = i + 2   # 跳过段标题行 + 子表头行
            break
    if start is None:
        sys.exit(f'[ERROR] 产品表找不到段 “{label}”（按后缀 {key} 匹配失败）')
    rc_off = 14 if typ == '付费' else 15
    mp = PAID_MAP if typ == '付费' else FREE_MAP
    out = []
    for r in rows[start:]:
        code = r[0].strip() if r else ''
        if not code.startswith('DX'):
            break
        nm = map_name(r[1].strip(), mp)
        target = num(r[2]); budget = num(r[4]); total = num(r[5]); consume = num(r[9])
        daily = []; w = [0, 0]; started = False
        for d in range(1, 32):
            nc = 10 + (d-1)*7
            if nc >= len(r):
                break
            if (r[nc] or '').strip() in ('', '无数据'):
                if started:
                    break
                continue
            started = True
            nv = num(r[nc])
            qc = 16 + (d-1)*7
            rc = rc_off + (d-1)*7
            qv = num(r[qc]) if qc < len(r) else 0
            rv = num(r[rc]) if rc < len(r) else 0
            daily.append((d, nv, qv, rv))
            if d <= 7: w[0] += nv
            elif d <= 14: w[1] += nv
        s = sum(x[1] for x in daily)
        if s != total:
            sys.exit(f'[ERROR] 产品 {nm}({code}) 每日新增和 {s} != 总新增 {total}')
        comp = round(total/target*100, 2) if target > 0 else 0
        crate = round(consume/budget*100, 2) if budget > 0 else 0
        cpa = round(consume/total, 2) if total > 0 else 0
        out.append(dict(name=nm, type=typ, target=target, budget=budget, w1=w[0], w2=w[1],
                        total=total, consume=consume, completion=comp, consumeRate=crate, cpa=cpa,
                        daily=[(f'{dprefix}-{dd:02d}', nv, qv, rv) for dd, nv, qv, rv in daily]))
    return out

def build_products(prod_rows, dprefix, mlabel):
    paid = parse_month_section(prod_rows, f'{mlabel}-收费APP', '付费', dprefix)
    free = parse_month_section(prod_rows, f'{mlabel}-免费盒子', '免费', dprefix)
    return paid + free

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
    prod_all = fetch('prodAll')

    people, pdaily, names = build_personal(charge, box, mlabel, dprefix)
    ords = build_orders(orders_raw)
    allp = build_products(prod_all, dprefix, mlabel)

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
