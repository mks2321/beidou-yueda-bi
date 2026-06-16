// 北斗悦达BI看板 · 投放策略云端同步后端（Google Apps Script）
// 存储：Script Properties 存一个 JSON：{ overrides:{产品:策略}, note:"策略说明" }
// 权限：写入需校验编辑密码。密码不写在代码里，存在 Script Properties 的 EDIT_PWD（你自己在后台设）。
//   · 未设 EDIT_PWD 时：任何人可写（兼容旧行为）
//   · 设了 EDIT_PWD 时：只有带正确密码的请求能写，其他人只能读
// 读取（看板加载）永远开放。

const KEY = 'STRATEGY_DATA';

function doGet(e) {
  const p = (e && e.parameter) || {};
  const cb = p.callback;
  const out = txt => ContentService.createTextOutput(cb ? cb + '(' + txt + ')' : txt)
      .setMimeType(cb ? ContentService.MimeType.JAVASCRIPT : ContentService.MimeType.JSON);

  // 写入：?action=set&pwd=...&payload=<JSON>
  if (p.action === 'set') {
    const realPwd = PropertiesService.getScriptProperties().getProperty('EDIT_PWD') || '';
    if (realPwd && p.pwd !== realPwd) {
      return out(JSON.stringify({ ok: false, error: '密码错误' }));
    }
    try {
      const data = JSON.parse(p.payload || '{}');
      const clean = JSON.stringify({
        overrides: (data && data.overrides && typeof data.overrides === 'object') ? data.overrides : {},
        note: (data && typeof data.note === 'string') ? data.note : ''
      });
      PropertiesService.getScriptProperties().setProperty(KEY, clean);
      return out(JSON.stringify({ ok: true }));
    } catch (err) {
      return out(JSON.stringify({ ok: false, error: String(err) }));
    }
  }

  // 读取
  const raw = PropertiesService.getScriptProperties().getProperty(KEY) || '{"overrides":{},"note":""}';
  return out(raw);
}

// 兼容保留：旧的 POST 写入（无密码校验，仅在未设 EDIT_PWD 时建议使用）
function doPost(e) {
  const realPwd = PropertiesService.getScriptProperties().getProperty('EDIT_PWD') || '';
  if (realPwd) {
    return ContentService.createTextOutput('unauthorized').setMimeType(ContentService.MimeType.TEXT);
  }
  try {
    const data = JSON.parse(e.postData.contents);
    const clean = JSON.stringify({
      overrides: (data && data.overrides && typeof data.overrides === 'object') ? data.overrides : {},
      note: (data && typeof data.note === 'string') ? data.note : ''
    });
    PropertiesService.getScriptProperties().setProperty(KEY, clean);
    return ContentService.createTextOutput('ok').setMimeType(ContentService.MimeType.TEXT);
  } catch (err) {
    return ContentService.createTextOutput('err: ' + err).setMimeType(ContentService.MimeType.TEXT);
  }
}
