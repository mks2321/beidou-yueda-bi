// 北斗悦达BI看板 · 投放策略云端同步后端（Google Apps Script）
// 存储：用 Script Properties 存一个 JSON：{ overrides:{产品:策略}, note:"策略说明" }
// 部署见同目录 README / 对话里的步骤。部署后把 /exec 网址发给我，填入 index.html 的 SYNC_URL。

const KEY = 'STRATEGY_DATA';

function doGet(e) {
  const raw = PropertiesService.getScriptProperties().getProperty(KEY) || '{"overrides":{},"note":""}';
  const cb = e && e.parameter && e.parameter.callback;
  if (cb) {
    // JSONP（看板读取用，绕开跨域）
    return ContentService.createTextOutput(cb + '(' + raw + ')')
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
  return ContentService.createTextOutput(raw).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
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
