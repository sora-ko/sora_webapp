/* localhost限定。架空CSVだけでCookie・復元・削除・期限を実ブラウザー確認する。
 * CSV、応答本文、Cookie、トレース、画像、動画をファイルやログへ出力しない。
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const args = process.argv.slice(2);
const option = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const {chromium} = require(option('--playwright-module', process.env.PLAYWRIGHT_MODULE || 'playwright'));
const base = new URL(option('--base-url', 'http://localhost:18080'));
const expiry = option('--expiry-url', null);
for (const url of [base, ...(expiry ? [new URL(expiry)] : [])]) {
  assert(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'Only localhost is permitted');
}
const exampleDir = option('--examples-dir', path.join(process.cwd(), 'examples'));
const grades = fs.readFileSync(path.join(exampleDir, 'first-year-sample.csv'));
assert(grades.toString('utf8').includes('架空') && grades.toString('utf8').includes('T00000000'));
const rows = [['[年度・学期]', '2026年度 第2学期'], ['', '月曜日', '火曜日', '水曜日', '木曜日', '金曜日']];
for (let period = 1; period <= 5; period++) {
  rows.push([`${period}限`, '', '', '', '', ''], ['', '', '', '', '', ''], ['', '', '', '', '', '']);
}
const timetable = Buffer.from(rows.map(row => row.map(value => JSON.stringify(value)).join(',')).join('\r\n') + '\r\n');

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.platform === 'win32' ? {channel: 'chrome'} : {}),
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  let passed = 0;
  const exceptions = [], external = [];
  const check = async (name, work) => {await work(); passed++; console.log(`PASS ${passed} ${name}`);};
  async function open(origin, prototype) {
    const context = await browser.newContext({acceptDownloads: false});
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== origin.origin) {external.push(true); return route.abort();}
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', () => exceptions.push(true));
    page.setDefaultTimeout(12000);
    const ui = prototype ? {
      grade: '#grades-input', table: '#timetable-input', report: '#overview-results', student: '#student-name',
      clearGrade: '#clear-grades', clearTable: '#clear-timetable', end: '#clear-all', search: '#search-button',
      error: '#grades-error', searchError: '#search-error', tableResult: '#timetable-status',
    } : {
      grade: '#csv-file', table: '#timetable-file', report: '#dashboard', student: '#student',
      clearGrade: '#clear-report', clearTable: '#timetable-clear', end: '#session-end', search: '#credit-search-form button[type="submit"]',
      error: '#error', searchError: '#credit-search-error', tableResult: '#timetable-dashboard',
    };
    async function click(selector) {
      await page.locator(selector).first().evaluate(item => {
        for (let parent = item.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
      });
      await page.locator(selector).first().click();
    }
    async function view(timetableView) {
      await click(prototype ? `[data-view="${timetableView ? 'timetable' : 'overview'}"]` : timetableView ? '#timetable-tab' : '#report-tab');
    }
    async function upload(kind, buffer, expected = 200) {
      await view(kind === 'timetables');
      const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/session/' + kind
        && response.request().method() === 'POST');
      await page.locator(kind === 'reports' ? ui.grade : ui.table).setInputFiles({name: 'fictional.csv', mimeType: 'text/csv', buffer});
      if (!prototype) await click(kind === 'reports' ? '#submit' : '#timetable-submit');
      const response = await responsePromise;
      assert.equal(response.status(), expected, 'Upload HTTP status');
      if (expected === 200) {
        if (kind === 'reports') await page.waitForSelector(ui.student + ':not(:empty)', {state: 'attached'});
        else if (prototype) await page.waitForFunction(() => !document.querySelector('#timetable-drop').closest('.panel').getAttribute('aria-busy') || document.querySelector('#timetable-drop').closest('.panel').getAttribute('aria-busy') === 'false');
        else await page.waitForSelector('#timetable-dashboard:not([hidden])');
      } else await page.waitForSelector(ui.error + ':not([hidden])');
    }
    async function probe() {
      return page.evaluate(async () => {
        const r = await fetch('/api/v1/session/workspace', {headers: {'X-Session-Request': '1'}, credentials: 'include', cache: 'no-store'});
        if (!r.ok) return {http: r.status};
        const data = await r.json();
        return {http: r.status, hasReport: Boolean(data.report), hasTimetable: Boolean(data.timetable),
          revision: data.revision, remaining: data.session.expires_in_seconds, credits: data.report?.summary.earned_credits};
      });
    }
    async function reload() {await page.reload({waitUntil: 'networkidle'});}
    await page.goto(new URL(prototype ? '/prototype/' : '/', origin).href, {waitUntil: 'networkidle'});
    return {context, page, ui, click, view, upload, probe, reload};
  }
  try {
    for (const prototype of [false, true]) {
      const label = prototype ? 'prototype' : 'original';
      const app = await open(base, prototype);
      const {context, page, ui, click, view, upload, probe, reload} = app;
      await check(label + ': visiting a blank page does not allocate a session', async () => {
        assert.equal((await probe()).http, 401);
        assert.equal((await context.cookies()).length, 0);
      });
      await check(label + ': parsing creates an HttpOnly Strict cookie and holds both results', async () => {
        await upload('reports', grades); await upload('timetables', timetable);
        const state = await probe();
        assert(state.hasReport && state.hasTimetable && state.credits === 34);
        const cookies = await context.cookies();
        assert(cookies.length === 1 && cookies[0].name === 'credit_session' && cookies[0].httpOnly && cookies[0].sameSite === 'Strict');
        assert.equal(await page.evaluate(() => document.cookie.split(';').some(item => item.trim().startsWith('credit_session='))), false);
      });
      await check(label + ': reload restores results with empty file inputs and unchanged deadline', async () => {
        const before = await probe();
        await reload();
        await page.waitForSelector(ui.student + ':not(:empty)', {state: 'attached'});
        const after = await probe();
        assert(after.hasReport && after.hasTimetable && after.credits === 34);
        assert(after.remaining <= before.remaining && after.revision === before.revision);
        assert.equal(await page.locator(ui.grade).inputValue(), '');
        assert.equal(await page.locator(ui.table).inputValue(), '');
      });
      await check(label + ': shortage search after reload sends fields without CSV files', async () => {
        await view(true);
        const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/session/recommendation-searches');
        await click(ui.search);
        const response = await pending;
        assert.equal(response.status(), 200);
        assert(!response.request().postDataBuffer().includes(Buffer.from('filename=')), 'Search must not resend CSV');
      });
      await check(label + ': another tab updating inputs invalidates an old query and reload restores the latest state', async () => {
        const peer = await context.newPage();
        try {
          await peer.goto(page.url(), {waitUntil: 'networkidle'});
          const pending = peer.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/session/reports'
            && response.request().method() === 'POST');
          if (!prototype) await peer.locator('#report-tab').click();
          await peer.locator(ui.grade).setInputFiles({name: 'fictional-peer.csv', mimeType: 'text/csv', buffer: grades});
          if (!prototype) await peer.locator('#submit').click();
          assert.equal((await pending).status(), 200);
          const rejected = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/session/recommendation-searches');
          await click(ui.search);
          assert.equal((await rejected).status(), 409);
          await page.waitForFunction(selector => document.querySelector(selector).textContent === '', ui.student);
          assert.match(await page.locator('#session-status').textContent(), /別のタブ|別の操作/);
          assert((await probe()).hasReport && (await probe()).hasTimetable, 'Conflict must not delete current server inputs');
        } finally {await peer.close();}
        await reload();
        await page.waitForSelector(ui.student + ':not(:empty)', {state: 'attached'});
        await view(true);
        const retried = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/session/recommendation-searches');
        await click(ui.search); assert.equal((await retried).status(), 200);
      });
      await check(label + ': another browser cannot restore these student results', async () => {
        const other = await open(base, prototype);
        assert.equal((await other.probe()).http, 401);
        assert.equal(await other.page.locator(other.ui.student).textContent(), '');
        await other.context.close();
      });
      await check(label + ': persistent browser stores remain empty', async () => {
        assert.deepEqual(await page.evaluate(async () => [localStorage.length, sessionStorage.length,
          indexedDB.databases ? (await indexedDB.databases()).length : 0, (await caches.keys()).length]), [0, 0, 0, 0]);
      });
      await check(label + ': forged CSRF cannot remove held results', async () => {
        const status = await page.evaluate(async () => {
          const options={credentials:'include',cache:'no-store',headers:{'X-Session-Request':'1'}};
          const current=await (await fetch('/api/v1/session/workspace',options)).json();
          return (await fetch('/api/v1/session/reports',{...options,method:'DELETE',headers:{...options.headers,
            'X-CSRF-Token':'invalid','X-Session-Revision':String(current.revision)}})).status;
        });
        assert.equal(status,403);assert((await probe()).hasReport);
      });
      await check(label + ': navigation and browser history restore without keeping an old page snapshot', async () => {
        await page.goto(new URL(prototype ? '/' : '/prototype/',base).href,{waitUntil:'networkidle'});
        await page.goBack({waitUntil:'domcontentloaded'});
        await page.waitForLoadState('networkidle');
        await page.waitForSelector(ui.student+':not(:empty)',{state:'attached'});
        assert((await probe()).hasReport && (await probe()).hasTimetable);
        assert.equal(await page.locator(ui.grade).inputValue(),'');
      });
      await check(label + ': restored CSV text cannot execute HTML', async () => {
        const text='<img src=x onerror=window.sessionTestXss=true>';
        const buffer=Buffer.from([['[学生氏名]',text,'[在籍番号]','T00000000','[学年]','1'],
          ['No.','科目','科目区分','単位数','合否'],['1','架空の教養科目','英語（英語）','2','合']]
          .map(row=>row.map(value=>JSON.stringify(value)).join(',')).join('\r\n')+'\r\n');
        await upload('reports',buffer);await reload();
        assert((await page.locator(ui.student).textContent()).includes(text));
        assert.equal(await page.locator(ui.student+' img').count(),0);
        assert.equal(await page.evaluate(()=>window.sessionTestXss===true),false);
      });
      await check(label + ': clearing a report persists across reload while timetable remains', async () => {
        await view(false);
        const deleted = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/session/reports' && response.request().method() === 'DELETE');
        await click(ui.clearGrade); assert.equal((await deleted).status(), 200);
        await reload(); const state = await probe();
        assert(!state.hasReport && state.hasTimetable);
        assert.equal(await page.locator(ui.student).textContent(), '');
      });
      await check(label + ': invalid replacement cannot restore the previous transcript', async () => {
        await upload('reports', grades);
        await upload('reports', Buffer.from('fictional invalid CSV'), 422);
        await reload(); const state = await probe();
        assert(!state.hasReport && state.hasTimetable);
        assert.equal(await page.locator(ui.student).textContent(), '');
      });
      await check(label + ': clearing during a delayed upload prevents result resurrection', async () => {
        await upload('reports',grades);await view(false);
        let release,arrived;
        const gate=new Promise(resolve=>{release=resolve;});
        const received=new Promise(resolve=>{arrived=resolve;});
        const delayed=async route=>{
          if(route.request().method()!=='POST')return route.continue();
          const response=await route.fetch();arrived();await gate;
          try {await route.fulfill({response});} catch { /* 取消済みリクエスト。 */ }
        };
        await page.route('**/api/v1/session/reports',delayed);
        await page.locator(ui.grade).setInputFiles({name:'fictional-delayed.csv',mimeType:'text/csv',buffer:grades});
        if(!prototype)await click('#submit');
        await received;
        const deleted=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/session/reports' && response.request().method()==='DELETE');
        await click(ui.clearGrade);assert.equal((await deleted).status(),200);
        release();await page.unroute('**/api/v1/session/reports',delayed);
        await reload();assert(!(await probe()).hasReport);
        assert.equal(await page.locator(ui.student).textContent(),'');
      });
      await check(label + ': clearing timetable persists and all-data deletion ends the session', async () => {
        await view(true);
        const deleted = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/session/timetables' && response.request().method() === 'DELETE');
        await click(ui.clearTable); assert.equal((await deleted).status(), 200);
        await reload(); assert(!(await probe()).hasTimetable);
        await upload('reports', grades);
        const ended = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/session' && response.request().method() === 'DELETE');
        await click(ui.end); assert.equal((await ended).status(), 200);
        await reload(); assert.equal((await probe()).http, 401);
        assert.equal(await page.locator(ui.student).textContent(), '');
      });
      await context.close();
      if (expiry) {
        const expiring = await open(new URL(expiry), prototype);
        await check(label + ': expiry removes visible data and files without a reload', async () => {
          await expiring.upload('reports', grades);
          const remaining = (await expiring.probe()).remaining;
          assert(remaining <= 15, 'Use a short TTL test server for --expiry-url');
          await expiring.page.waitForTimeout((remaining + 1) * 1000);
          assert.equal(await expiring.page.locator(expiring.ui.student).textContent(), '');
          assert.equal(await expiring.page.locator(expiring.ui.grade).inputValue(), '');
          assert.equal((await expiring.probe()).http, 401);
          assert.match(await expiring.page.locator('#session-status').textContent(), /期限/);
          await expiring.reload(); assert.equal((await expiring.probe()).http, 401);
        });
        await expiring.context.close();
      }
    }
    assert.equal(exceptions.length, 0, 'JavaScript exceptions');
    assert.equal(external.length, 0, 'External requests');
    console.log(JSON.stringify({passed, javascript_errors: 0, external_requests: 0, saved_student_artifacts: 0}));
  } finally {await browser.close();}
})().catch(error => {console.error(error.stack); process.exitCode = 1;});
