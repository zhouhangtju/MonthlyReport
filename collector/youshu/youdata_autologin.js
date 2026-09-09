#!/usr/bin/env node
'use strict';

/* 有数平台全自动登录并刷新凭证。零 npm 依赖，需要 Node.js 22+ 和 Edge/Chrome。 */
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const HERE = __dirname;
const BASE = 'http://10.76.134.138:30000';
const LOGIN_URL = BASE + '/bi/dash/login1';
const CDP = 'http://127.0.0.1:18800';
const LOGIN_CONFIG = path.join(HERE, 'youdata_login.json');
const DATA_CONFIG = path.join(HERE, '有数配置.json');
const PROFILE_DIR = path.join(HERE, 'edge_profile');

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8'));

function browserCandidates() {
  const out = [];
  if (process.env.YOUDATA_BROWSER) out.push(process.env.YOUDATA_BROWSER);
  if (process.platform === 'win32') {
    for (const root of [process.env['PROGRAMFILES(X86)'], process.env.PROGRAMFILES, process.env.LOCALAPPDATA].filter(Boolean)) {
      out.push(path.join(root, 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
      out.push(path.join(root, 'Google', 'Chrome', 'Application', 'chrome.exe'));
    }
  } else if (process.platform === 'darwin') {
    out.push('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge');
    out.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
  } else {
    out.push('/usr/bin/microsoft-edge', '/usr/bin/microsoft-edge-stable');
    out.push('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium');
  }
  return [...new Set(out)];
}

function findBrowser() {
  for (const candidate of browserCandidates()) {
    try { if (fs.statSync(candidate).isFile()) return candidate; } catch (_) {}
  }
  throw new Error('未找到 Edge/Chrome；可设置 YOUDATA_BROWSER 指定浏览器路径');
}

async function cdpReady() {
  try { return (await fetch(CDP + '/json/version')).ok; } catch (_) { return false; }
}

async function ensureBrowser() {
  if (await cdpReady()) {
    console.log('[1/5] 复用已启动的 CDP 浏览器');
    return;
  }
  const executable = findBrowser();
  fs.mkdirSync(PROFILE_DIR, { recursive: true });
  console.log('[1/5] 启动浏览器:', executable);
  const child = spawn(executable, [
    '--remote-debugging-port=18800', '--remote-debugging-address=127.0.0.1',
    '--user-data-dir=' + PROFILE_DIR, '--no-first-run', '--no-default-browser-check', LOGIN_URL,
  ], { detached: true, stdio: 'ignore' });
  child.unref();
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (await cdpReady()) return;
    await sleep(500);
  }
  throw new Error('浏览器 CDP 端口 18800 未就绪');
}

async function getPageTarget() {
  const targets = await (await fetch(CDP + '/json')).json();
  const pages = targets.filter(item => item.type === 'page');
  return pages.find(item => (item.url || '').startsWith(BASE)) || pages[0];
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let nextId = 0;
    const pending = new Map();
    const api = {
      onRequest: null,
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const id = ++nextId;
          pending.set(id, { res, rej });
          ws.send(JSON.stringify({ id, method, params }));
        });
      },
      close() { try { ws.close(); } catch (_) {} },
    };
    ws.onopen = () => resolve(api);
    ws.onerror = event => reject(new Error('CDP WebSocket 连接失败: ' + String(event.message || event)));
    ws.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.method === 'Network.requestWillBeSent' && api.onRequest) api.onRequest(message.params);
      if (message.id && pending.has(message.id)) {
        const item = pending.get(message.id);
        pending.delete(message.id);
        message.error ? item.rej(new Error(JSON.stringify(message.error))) : item.res(message.result || {});
      }
    };
  });
}

async function evaluate(api, expression) {
  const result = await api.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error('页面脚本执行失败');
  return result.result ? result.result.value : undefined;
}

async function waitFor(api, expression, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { if (await evaluate(api, expression)) return; } catch (_) {}
    await sleep(500);
  }
  throw new Error('等待超时: ' + label);
}

function loginExpression(account, password) {
  return `(() => {
    const visible = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    const first = selectors => selectors.map(s => [...document.querySelectorAll(s)].find(visible)).find(Boolean);
    const user = first(['input[name="uniqueId"]','input[name="username"]','input[type="email"]','input[placeholder*="账号"]','input[placeholder*="用户名"]','input[placeholder*="邮箱"]','input[placeholder*="手机"]','input[type="text"]']);
    const pwd = first(['input[name="password"]','input[type="password"]','input[placeholder*="密码"]']);
    if (!user || !pwd) return {ok:false, reason:'未找到账号或密码输入框'};
    const setValue = (el, value) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value);
      for (const type of ['input','change','blur']) el.dispatchEvent(new Event(type, {bubbles:true}));
    };
    setValue(user, ${JSON.stringify(account)});
    setValue(pwd, ${JSON.stringify(password)});
    const controls = [...document.querySelectorAll('button,[role="button"],input[type="submit"]')];
    const button = controls.find(el => visible(el) && (/登录/.test(el.innerText || el.value || '') || el.type === 'submit'));
    if (button) button.click();
    else pwd.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter',code:'Enter',bubbles:true}));
    return {ok:true};
  })()`;
}

function getReportUrl() {
  const cfg = readJson(DATA_CONFIG);
  for (const name of ['企宽投诉清单', '新装退单']) {
    const task = (cfg.tasks || []).find(item => item.name === name);
    if (task && task.referrer) return task.referrer;
  }
  return BASE + '/bi/dash/folder/31';
}

function updateConfig(credentials) {
  const cfg = readJson(DATA_CONFIG);
  cfg.headers = cfg.headers || {};
  cfg.headers.cookie = credentials.cookie;
  cfg.headers['x-csrf-token'] = credentials.csrf;
  cfg.headers['x-roomid'] = credentials.roomid;
  cfg.headers['x-sid'] = credentials.sid;
  fs.writeFileSync(DATA_CONFIG, JSON.stringify(cfg, null, 2) + '\n', 'utf8');
}

async function main() {
  if (typeof fetch !== 'function' || typeof WebSocket !== 'function') {
    throw new Error('需要 Node.js 22+（提供内置 fetch 和 WebSocket）');
  }
  if (!fs.existsSync(LOGIN_CONFIG)) throw new Error('缺少账号密码文件: ' + LOGIN_CONFIG);
  if (!fs.existsSync(DATA_CONFIG)) throw new Error('缺少取数配置文件: ' + DATA_CONFIG);
  const login = readJson(LOGIN_CONFIG);
  if (!login.account || !login.password) throw new Error('youdata_login.json 中账号或密码为空');

  await ensureBrowser();
  const target = await getPageTarget();
  if (!target) throw new Error('CDP 中没有浏览器页面');
  const api = await connect(target.webSocketDebuggerUrl);
  const captured = { csrf: '', roomid: '', sid: '' };
  api.onRequest = params => {
    const request = params.request || {};
    if (!/\/bi\/api\//.test(request.url || '')) return;
    const headers = {};
    for (const [key, value] of Object.entries(request.headers || {})) headers[key.toLowerCase()] = value;
    captured.csrf = headers['x-csrf-token'] || captured.csrf;
    captured.roomid = headers['x-roomid'] || captured.roomid;
    captured.sid = headers['x-sid'] || captured.sid;
  };
  await api.send('Network.enable');
  await api.send('Page.enable');
  await api.send('Runtime.enable');

  console.log('[2/5] 打开有数登录页');
  await api.send('Page.navigate', { url: LOGIN_URL });
  await waitFor(api, `document.readyState !== 'loading'`, 20000, '登录页加载');
  await waitFor(api, `!!document.querySelector('input[type="password"]')`, 20000, '密码输入框出现');
  console.log('[3/5] 自动填写账号密码并登录:', login.account);
  const result = await evaluate(api, loginExpression(login.account, login.password));
  if (!result || !result.ok) throw new Error((result && result.reason) || '填写登录表单失败');
  await waitFor(api, `!location.href.includes('/login1')`, 60000, '登录成功跳转');

  const reportUrl = getReportUrl();
  console.log('[4/5] 进入报告页并抓取凭证:', reportUrl);
  await api.send('Page.navigate', { url: reportUrl });
  await waitFor(api, `document.readyState !== 'loading'`, 30000, '报告页加载');
  await api.send('Page.reload', { ignoreCache: true });
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline && !(captured.csrf && captured.roomid && captured.sid)) await sleep(500);

  const cookieResult = await api.send('Network.getCookies', { urls: [BASE] });
  const cookies = cookieResult.cookies || [];
  const wanted = new Set(['SESSION_YOUDATA', 'SESSION_YOUDATA.sig', 'YDNESIO']);
  const picked = cookies.filter(item => wanted.has(item.name));
  const cookie = (picked.length ? picked : cookies).map(item => item.name + '=' + item.value).join('; ');
  api.close();

  const credentials = { cookie, ...captured };
  const missing = Object.entries(credentials).filter(([, value]) => !value).map(([key]) => key);
  if (missing.length) throw new Error('未抓到完整凭证: ' + missing.join(', '));
  updateConfig(credentials);
  console.log('[5/5] OK 已更新:', DATA_CONFIG);
  console.log('      cookie/csrf/roomid/sid 已刷新（敏感值不打印）');
}

main().catch(error => {
  console.error('[ERROR]', error.message || error);
  process.exit(1);
});
