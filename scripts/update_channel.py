#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北斗悦达BI看板 · 渠道码分析数据自动更新（GitHub Actions 调用）

数据源与 Google Sheets 那条线无关：直接查渠道管理系统的 GraphQL API
  1) supplierPage       当月新建的供应商
  2) distributePage     当月新建的投放分配单（= 渠道码）
  3) channelDetailReport 这些码在当月的每日新增/消耗/充值（BI 渠道明细）

重建 index.html 里的 `const channelData = {...};`，不提交（commit/push 由 workflow 负责）。
拉数或校验失败 -> 退出码 1。本步骤在 workflow 里是 continue-on-error，
失败不会连累 Google Sheets 那条线。

关键口径（改脚本前务必读）：
  * CPT（按时长买断）的 sysSettlementCnyMoney 在 BI 宽表里是**计费周期快照**，
    每一天都重复写同一个数，不是当日增量。直接 SUM 会把消耗放大近 9 倍。
    本脚本对「整段日期消耗恒定且 > 0」的码按**每码只计一次**处理。
  * 免费类 = 免费 + 半收费（productModelLabel），付费类 = 收费。按用户口径。
  * 当日数据次日落表，所以区间末日一般是昨天，daily 只保留有数的日子。
  * 组员维度按用户要求不展示，但仍在脚本内计算，用作「组员新增之和 = 总新增」的校验。
"""
import json, os, re, ssl, sys, urllib.request, datetime

API = 'https://www.channelnew.icu/api/admin-api/skill/graphql'
TOKEN = os.environ.get('SKILL_TOKEN', '')
SKILL_VERSION = os.environ.get('SKILL_VERSION', 'v1.5.69')
# 不带浏览器 UA 会被 CDN 403（error code 1010）
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 ChannelSkill-Python/1')


def graphql(query, variables=None):
    if not TOKEN:
        sys.exit('[ERROR] 缺少 SKILL_TOKEN 环境变量（GitHub Secret）。')
    body = json.dumps({'query': query, 'variables': variables or {}}).encode('utf-8')
    req = urllib.request.Request(API, data=body, method='POST', headers={
        'User-Agent': UA, 'Content-Type': 'application/json',
        'X-Skill-Token': TOKEN, 'X-Skill-Version': SKILL_VERSION,
        'X-Skill-Client': 'python'})
    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=90) as r:
            data = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        sys.exit('[ERROR] GraphQL 请求失败：%s' % e)
    if 'errors' in data:
        sys.exit('[ERROR] GraphQL 返回错误：%s' % json.dumps(data['errors'], ensure_ascii=False)[:500])
    return data['data']


def page_all(field, query, base_input, page_size=200):
    """标准 {total, list} 分页"""
    out, pn = [], 1
    while True:
        inp = dict(base_input, pageNo=pn, pageSize=page_size)
        d = graphql(query, {'input': inp})[field]
        out += d['list']
        if len(out) >= d['total'] or not d['list']:
            return out
        pn += 1
        if pn > 200:
            sys.exit('[ERROR] %s 分页超过 200 页，疑似死循环。' % field)


Q_SUP = ('query($input:SupplierPageInput){ supplierPage(input:$input){ total list { '
         'id supplierCode supplierName statusLabel memberAdminUser{id name} createTime } } }')

Q_DIST = ('query($input:DistributePageInput){ distributePage(input:$input){ total list { '
          'id channelCode statusLabel productModelLabel cooperationModeLabel '
          'channelSupplierInfoId memberAdminUser{id name} createTime } } }')

Q_BI = ('query($input:BiQueryInput){ channelDetailReport(input:$input){ total cursor list { '
        'statDate channelCode addNumber rechargeNumber rechargeMoney sysSettlementCnyMoney } } }')


def bi_rows(codes, start, end, chunk=100):
    """按渠道码分批 + cursor 游标翻页拉 BI 渠道明细。深翻超 1 万行会报错，故分批。"""
    rows = []
    for i in range(0, len(codes), chunk):
        part = codes[i:i + chunk]
        cursor, pn, got, total = None, 1, 0, None
        while True:
            inp = {'pageNo': pn, 'pageSize': 200, 'startDate': start,
                   'endDate': end, 'channelCodeList': part}
            if cursor:
                inp['cursor'] = cursor
            d = graphql(Q_BI, {'input': inp})['channelDetailReport']
            total = d['total']
            rows += d['list']
            got += len(d['list'])
            cursor = d.get('cursor')
            if got >= total or not d['list'] or not cursor:
                break
            pn += 1
            if pn > 200:
                sys.exit('[ERROR] BI 分页超过 200 页，疑似游标失效。')
        print('  BI 批 %d/%d：%d 码 → %d 行' % (i // chunk + 1, (len(codes) + chunk - 1) // chunk,
                                              len(part), got))
    return rows


def f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def is_free(model_label):
    """免费类 = 免费 + 半收费；付费类 = 收费"""
    return model_label != '收费'


def js(obj, indent=2):
    """输出紧凑 JS 字面量（键不加引号，避免 index.html 里风格突兀）"""
    def enc(o, lv):
        pad = ' ' * (indent * lv)
        if isinstance(o, dict):
            if not o:
                return '{}'
            items = ['%s%s: %s' % (' ' * (indent * (lv + 1)), k, enc(v, lv + 1)) for k, v in o.items()]
            return '{\n' + ',\n'.join(items) + '\n' + pad + '}'
        if isinstance(o, list):
            if not o:
                return '[]'
            # 元素是扁平 dict 时压成一行，表格数据更好读
            if all(isinstance(x, dict) and not any(isinstance(v, (dict, list)) for v in x.values()) for x in o):
                inner = [' ' * (indent * (lv + 1)) + '{ ' +
                         ', '.join('%s: %s' % (k, enc(v, 0)) for k, v in x.items()) + ' }' for x in o]
                return '[\n' + ',\n'.join(inner) + '\n' + pad + ']'
            return '[\n' + ',\n'.join(' ' * (indent * (lv + 1)) + enc(x, lv + 1) for x in o) + '\n' + pad + ']'
        if isinstance(o, str):
            return "'" + o.replace('\\', '\\\\').replace("'", "\\'") + "'"
        if isinstance(o, float):
            return str(int(o)) if o == int(o) else str(round(o, 2))
        if o is None:
            return 'null'
        return str(o)
    return enc(obj, 0)


def main():
    html = open('index.html', encoding='utf-8').read()
    m = re.search(r"let currentMonth = '(\d+)月'", html)
    if not m:
        sys.exit('[ERROR] 找不到 currentMonth')
    mnum = int(m.group(1))

    bj_now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    year = bj_now.year
    start = '%d-%02d-01' % (year, mnum)
    if mnum == 12:
        last = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last = datetime.date(year, mnum + 1, 1) - datetime.timedelta(days=1)
    end = last.isoformat()
    print('[INFO] 月份 %d月，区间 %s ~ %s' % (mnum, start, end))

    # 1) 当月新建供应商
    sups = page_all('supplierPage', Q_SUP,
                    {'createTimeStart': start + ' 00:00:00', 'createTimeEnd': end + ' 23:59:59'})
    sup_ids = {s['id'] for s in sups}
    print('[INFO] 新开供应商 %d 家' % len(sups))

    # 2) 当月新建渠道码
    dists = page_all('distributePage', Q_DIST,
                     {'createTimeStart': start + ' 00:00:00', 'createTimeEnd': end + ' 23:59:59'})
    meta = {d['channelCode']: d for d in dists if d.get('channelCode')}
    codes = list(meta)
    print('[INFO] 新开渠道码 %d 个' % len(codes))
    if not codes:
        sys.exit('[ERROR] 当月没有拉到任何渠道码，疑似接口或权限异常。')

    # 3) BI 每日明细
    rows = bi_rows(codes, start, end)
    print('[INFO] BI 明细 %d 行' % len(rows))

    # ---- 聚合 ----
    cost_series = {}   # code -> [每日消耗]
    add = {}
    rech = {}
    rn = {}
    daily = {}         # statDate -> {'free':x,'paid':y}
    for r in rows:
        c = r['channelCode']
        if c not in meta:
            continue
        cost_series.setdefault(c, []).append(f(r.get('sysSettlementCnyMoney')))
        v = f(r.get('addNumber'))
        add[c] = add.get(c, 0) + v
        rech[c] = rech.get(c, 0) + f(r.get('rechargeMoney'))
        rn[c] = rn.get(c, 0) + f(r.get('rechargeNumber'))
        k = 'free' if is_free(meta[c]['productModelLabel']) else 'paid'
        d = daily.setdefault(r['statDate'], {'free': 0.0, 'paid': 0.0})
        d[k] += v

    def cost(c):
        """CPT 周期快照：整段恒定且 >0 -> 只计一次；否则按日累加"""
        v = cost_series.get(c, [])
        if len(v) > 1 and len(set(v)) == 1 and v[0] > 0:
            return v[0]
        return sum(v)

    days = sorted(d for d, x in daily.items() if (x['free'] + x['paid']) > 0)
    if not days:
        sys.exit('[ERROR] BI 明细没有任何有新增的日期，疑似数据异常。')

    tot_add = sum(add.values())
    tot_cost = sum(cost(c) for c in codes)
    tot_rech = sum(rech.values())
    tot_rn = sum(rn.values())

    def bucket(sel, name):
        cs = [c for c in codes if sel(c)]
        a = sum(add.get(c, 0) for c in cs)
        return {'name': name, 'codes': len(cs),
                'active': sum(1 for c in cs if add.get(c, 0) > 0),
                'zero': sum(1 for c in cs if add.get(c, 0) <= 0),
                'closed': sum(1 for c in cs if meta[c]['statusLabel'] == '已关闭'),
                'add': int(a), 'cost': round(sum(cost(c) for c in cs), 2),
                'recharge': round(sum(rech.get(c, 0) for c in cs), 2),
                'rechargeUsers': int(sum(rn.get(c, 0) for c in cs))}

    split = [bucket(lambda c: is_free(meta[c]['productModelLabel']), '免费类'),
             bucket(lambda c: not is_free(meta[c]['productModelLabel']), '付费类')]
    sub_split = [bucket(lambda c: meta[c]['productModelLabel'] == '免费', '纯免费'),
                 bucket(lambda c: meta[c]['productModelLabel'] == '半收费', '半收费')]
    supplier_split = [bucket(lambda c: meta[c]['channelSupplierInfoId'] in sup_ids, '新供应商'),
                      bucket(lambda c: meta[c]['channelSupplierInfoId'] not in sup_ids, '老供应商')]

    # 供应商状态分布
    st = {}
    for s in sups:
        st[s['statusLabel']] = st.get(s['statusLabel'], 0) + 1
    status = [{'name': k, 'count': v} for k, v in sorted(st.items(), key=lambda kv: -kv[1])]

    # 按组员
    mem = {}
    for c in codes:
        n = (meta[c].get('memberAdminUser') or {}).get('name') or '未分配'
        e = mem.setdefault(n, {'name': n, 'suppliers': 0, 'codes': 0, 'active': 0,
                               'add': 0, 'free': 0, 'paid': 0, 'cost': 0.0})
        e['codes'] += 1
        a = add.get(c, 0)
        e['add'] += a
        if a > 0:
            e['active'] += 1
        e['cost'] += cost(c)
        e['free' if is_free(meta[c]['productModelLabel']) else 'paid'] += a
    for s in sups:
        n = (s.get('memberAdminUser') or {}).get('name') or '未分配'
        mem.setdefault(n, {'name': n, 'suppliers': 0, 'codes': 0, 'active': 0,
                           'add': 0, 'free': 0, 'paid': 0, 'cost': 0.0})['suppliers'] += 1
    # 组员维度不再展示在看板上，但保留计算用于一致性校验
    members = sorted(mem.values(), key=lambda x: -x['add'])
    for e in members:
        e['add'] = int(e['add']); e['free'] = int(e['free']); e['paid'] = int(e['paid'])
        e['cost'] = round(e['cost'], 2)

    codes_with_vol = {meta[c]['channelSupplierInfoId'] for c in codes if add.get(c, 0) > 0}

    data = {
        'updated': bj_now.strftime('%Y-%m-%d %H:%M'),
        'period': {'start': days[0], 'end': days[-1], 'days': len(days)},
        'suppliers': {
            'total': len(sups),
            'withCode': len({meta[c]['channelSupplierInfoId'] for c in codes} & sup_ids),
            'withVolume': len(codes_with_vol & sup_ids),
            'status': status},
        'codes': {'total': len(codes),
                  'active': sum(1 for c in codes if add.get(c, 0) > 0),
                  'zero': sum(1 for c in codes if add.get(c, 0) <= 0),
                  'closed': sum(1 for c in codes if meta[c]['statusLabel'] == '已关闭')},
        'totals': {'add': int(tot_add), 'cost': round(tot_cost, 2),
                   'recharge': round(tot_rech, 2), 'rechargeUsers': int(tot_rn)},
        'split': split,
        'subSplit': sub_split,
        'supplierSplit': supplier_split,
        'daily': [{'d': d[5:], 'free': int(daily[d]['free']), 'paid': int(daily[d]['paid'])} for d in days],
    }

    # ---- 一致性校验（失败即退出，workflow 不提交）----
    s_add = sum(x['add'] for x in split)
    if s_add != int(tot_add):
        sys.exit('[ERROR] 免费/付费新增之和 %d ≠ 总新增 %d' % (s_add, int(tot_add)))
    d_add = sum(x['free'] + x['paid'] for x in data['daily'])
    if abs(d_add - int(tot_add)) > 1:
        sys.exit('[ERROR] 每日新增之和 %d ≠ 总新增 %d' % (d_add, int(tot_add)))
    m_add = sum(x['add'] for x in members)
    if m_add != int(tot_add):
        sys.exit('[ERROR] 组员新增之和 %d ≠ 总新增 %d（内部校验，组员数据不上看板）' % (m_add, int(tot_add)))
    if sum(x['codes'] for x in split) != len(codes):
        sys.exit('[ERROR] 免费/付费码数之和 ≠ 总码数')
    if tot_cost > tot_add * 200 and tot_add > 0:
        sys.exit('[ERROR] 单新增成本 %.1f 异常偏高，疑似 CPT 周期快照被按天累加。' % (tot_cost / tot_add))

    new_block = 'const channelData = ' + js(data) + ';'
    pat = re.compile(r'const channelData = \{[\s\S]*?\n\};')
    if not pat.search(html):
        sys.exit('[ERROR] index.html 里找不到 const channelData = {...};')
    html_new = pat.sub(lambda _: new_block, html, count=1)

    if html_new == html:
        print('[OK] 渠道码数据无变化，未写入。')
        return
    open('index.html', 'w', encoding='utf-8').write(html_new)
    print('[OK] 渠道码数据已写入：供应商 %d 家 · 渠道码 %d 个 · 新增 %d · 消耗 %.0f · 区间 %s~%s（%d天）'
          % (len(sups), len(codes), int(tot_add), tot_cost, days[0], days[-1], len(days)))
    print('     免费类 新增 %d / 消耗 %.0f ；付费类 新增 %d / 消耗 %.0f'
          % (split[0]['add'], split[0]['cost'], split[1]['add'], split[1]['cost']))


if __name__ == '__main__':
    main()
