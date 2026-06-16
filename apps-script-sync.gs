// 北斗悦达BI看板 · 投放策略云端同步后端（Google Apps Script）· 通用存储版
// 存储：Script Properties 存看板发来的整个 JSON（overrides / note / notes / 以后任意字段）。
// 权限：写入需校验编辑密码 EDIT_PWD（存在 Script Properties，不写在代码里）。
//   · 未设 EDIT_PWD：任何人可写  · 设了 EDIT_PWD：只有带正确密码的请求能写
// 读取永远开放。以后看板新增同步字段无需再改本后端。

const KEY = 'STRATEGY_DATA';
const DEFAULT = '{"overrides":{},"note":"","notes":{}}';

function doGet(e) {
  const p = (e && e.parameter) || {};
  const cb = p.callback;
  const out = function (txt) {
    return ContentService.createTextOutput(cb ? cb + '(' + txt + ')' : txt)
      .setMimeType(cb ? ContentService.MimeType.JAVASCRIPT : ContentService.MimeType.JSON);
  };

  if (p.action === 'set') {
    const realPwd = PropertiesService.getScriptProperties().getProperty('EDIT_PWD') || '';
    if (realPwd && p.pwd !== realPwd) {
      return out(JSON.stringify({ ok: false, error: '密码错误' }));
    }
    try {
      const data = JSON.parse(p.payload || '{}');
      if (typeof data !== 'object' || data === null) throw '数据格式错误';
      PropertiesService.getScriptProperties().setProperty(KEY, JSON.stringify(data));
      return out(JSON.stringify({ ok: true }));
    } catch (err) {
      return out(JSON.stringify({ ok: false, error: String(err) }));
    }
  }

  const raw = PropertiesService.getScriptProperties().getProperty(KEY) || DEFAULT;
  return out(raw);
}
