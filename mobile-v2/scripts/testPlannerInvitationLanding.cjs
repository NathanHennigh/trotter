const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../../backend/app/routers/planner_landing.py'), 'utf8');
const script = source.match(/<script nonce="__NONCE__">([\s\S]*?)<\/script>/)[1];
const token = 'a'.repeat(43);
const preview = { inviter_name: 'A friend', role: 'contributor', trip: {
  title: 'Morocco, together', start_date: '2026-11-09', end_date: '2026-11-15',
} };

async function page({ userAgent = 'Android', platform = '', maxTouchPoints = 0,
  hash = `#token=${token}`, web = 'https://trotter.example', iosDownload = '', response = preview, ok = true } = {}) {
  const elements = new Map(), requests = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, { hidden: true, listeners: {},
      addEventListener(event, callback) { this.listeners[event] = callback; },
      set innerHTML(_) { assert.fail('Untrusted invitation content must remain text'); },
    });
    return elements.get(id);
  };
  const location = { hash, origin: 'https://api.trotter.example' };
  vm.runInNewContext(script.replace('__WEB_URL__', JSON.stringify(web)).replace('__IOS_DOWNLOAD_URL__', JSON.stringify(iosDownload)), {
    URL, URLSearchParams, Intl, Date, AbortController, navigator: { userAgent, platform, maxTouchPoints },
    location, document: { getElementById: element }, setTimeout: () => 1, clearTimeout: () => {},
    fetch: async (url, options) => { requests.push({ url, options }); return { ok, json: async () => response }; },
  });
  await new Promise(resolve => setImmediate(resolve));
  return { element, location, requests };
}

test('Android download keeps the invitation and exposes a return-to-app handoff without joining', async () => {
  const { element, location, requests } = await page();
  assert.equal(element('download').hidden, false);
  assert.equal(element('download').href, 'https://trotter.example/downloads/trotter-android.apk');
  assert.equal(element('native').hidden, false);
  element('download').listeners.click();
  assert.match(element('install-help').textContent, /return to this invitation and tap Open in Trotter/);
  assert.equal(element('install-help').hidden, false);
  assert.equal(location.hash, `#token=${token}`);
  assert.equal(element('native').href, `trotterv2://planner-invite?token=${token}`);
  assert.equal(element('web').href, `https://trotter.example/#planner-invitation=${token}`);
  assert.deepEqual(requests.map(request => request.url), ['/planner/invites/resolve']);
  assert.equal(JSON.parse(requests[0].options.body).token, token);
  assert.equal(requests[0].options.credentials, 'omit');
});

for (const device of [
  { userAgent: 'iPhone' }, { userAgent: 'Macintosh', platform: 'MacIntel', maxTouchPoints: 5 },
]) test(`Apple mobile offers the installed app and browser without a fake install destination (${device.userAgent})`, async () => {
  const { element } = await page(device);
  assert.equal(element('native').hidden, false);
  assert.equal(element('native').href, `trotterv2://planner-invite?token=${token}`);
  assert.equal(element('download').hidden, true);
  assert.equal(element('ios-download').hidden, true);
  assert.equal(element('web').hidden, false);
  assert.equal(element('web').className, 'secondary');
  assert.match(element('install-help').textContent, /browser/);
});

test('iPhone TestFlight handoff preserves the invitation and makes the return step explicit', async () => {
  const iosDownload = 'https://testflight.apple.com/join/AbCdEfGh';
  const { element, location, requests } = await page({ userAgent: 'iPhone', iosDownload });
  assert.equal(element('ios-download').hidden, false);
  assert.equal(element('ios-download').href, iosDownload);
  assert.equal(element('ios-download').textContent, 'Get the iPhone beta');
  assert.match(element('install-help').textContent, /return to this invitation and tap Open in Trotter/);
  assert.equal(location.hash, `#token=${token}`);
  assert.equal(requests.length, 1);
  assert.equal(element('download').hidden, true);
});

test('App Store links use release copy and desktop never offers an iPhone download', async () => {
  const iosDownload = 'https://apps.apple.com/us/app/trotter/id123456789';
  const iphone = await page({ userAgent: 'iPhone', iosDownload });
  assert.equal(iphone.element('ios-download').textContent, 'Get the iPhone app');
  const desktop = await page({ userAgent: 'Windows NT 10.0', iosDownload });
  assert.equal(desktop.element('ios-download').hidden, true);
});

test('desktop makes browser participation the primary action', async () => {
  const { element } = await page({ userAgent: 'Windows NT 10.0' });
  assert.equal(element('web').className, 'primary');
  assert.equal(element('native').hidden, true);
  assert.equal(element('download').hidden, true);
});

test('expired and malformed invitations cannot offer an install-and-join path', async () => {
  for (const options of [{ response: { status: 'expired' } }, { hash: `#token=${token}&token=${token}` }]) {
    const { element, requests } = await page(options);
    assert.equal(element('native').hidden, true);
    assert.equal(element('download').hidden, true);
    assert.equal(element('ios-download').hidden, true);
    assert.equal(element('web').hidden, true);
    if (options.hash) assert.equal(requests.length, 0);
  }
});

test('unconfigured browser host cannot produce a download URL and titles remain plain text', async () => {
  const title = '<img src=x onerror=alert(1)>';
  const { element } = await page({ web: '', response: { ...preview, trip: { ...preview.trip, title } } });
  assert.equal(element('download').hidden, true);
  assert.equal(element('web').hidden, true);
  assert.equal(element('title').textContent, title);
});
