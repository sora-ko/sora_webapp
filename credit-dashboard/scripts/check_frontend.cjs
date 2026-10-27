/* localhost専用。架空CSVをメモリ内で生成し、参考UIを実ブラウザーで検証する。
 * Playwrightは開発環境から提供する。アプリの実行依存には追加しない。
 * CSV・API応答・トレース・動画は保存しない。任意の画面画像も架空データのみ。
 */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const baseUrl = new URL(option('--base-url', 'http://localhost:8000'));
assert(['localhost', '127.0.0.1', '[::1]'].includes(baseUrl.hostname), 'localhost以外へ送信できません');
assert.equal(baseUrl.protocol, 'http:');
const screenshotDir = option('--screenshot-dir', null);

function csv(rows) {
  return Buffer.from(rows.map(row => row.map(value => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\r\n') + '\r\n');
}

function timetableRows({empty = false, metadata = true, unresolved = false} = {}) {
  const blank = () => Array(7).fill('');
  const rows = metadata ? [
    ['[氏名]', '架空 画面確認', '', '', '[在籍番号]', 'T00000000', ''],
    ['[年度・学期]', '2026年度 第2学期', '', '', '', '', ''],
    ['[学年]', '2年', '', '', '', '', ''],
    blank(),
  ] : [];
  rows.push(['', '月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日']);
  for (let period = 1; period <= 7; period++) {
    const block = [blank(), blank(), blank()];
    block[0][0] = `${period}限`;
    if (!empty && (period === 1 || period === 2)) {
      block[0][1] = '263G9991';
      block[1][1] = '架空科目甲';
      block[2][1] = '架空教員';
    }
    if (!empty && period === 1) {
      block[0][4] = '263G9991';
      block[1][4] = '架空科目甲';
      block[2][4] = '架空教員';
      block[0][2] = '未登録';
      if (unresolved) block[1][2] = '架空番号欠落科目';
      block.push(['', '264G9992', '', '', '', '', ''],
        ['', '架空科目乙', '', '', '', '', ''], ['', '架空教員', '', '', '', '', '']);
    }
    rows.push(...block);
  }
  if (!empty) rows.push(['集中講義', '260T9999', '', '', '', '', '']);
  return rows;
}

function gradeRows(name = '架空 画面確認') {
  return [
    ['[学生氏名]', name, '[在籍番号]', 'T00000000', '[学生所属]', '架空所属', '[学年]', '1'],
    ['No.', '分野', '水準', '開講番号', '科目', '科目区分', '必選区分', '単位数', '合否'],
    ['1', '10', '1', 'X-1', '架空教養科目', '英語（英語）', '必修', '2', '合'],
  ];
}

(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.platform === 'win32' ? {channel: 'chrome'} : {}),
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {}),
  });
  let count = 0;
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: false});
    const outsideRequests = [];
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== baseUrl.origin) {
        outsideRequests.push('outside-origin');
        return route.abort();
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    const check = async (name, action) => {
      await action();
      count += 1;
      console.log(`PASS ${String(count).padStart(2, '0')} ${name}`);
    };
    const openParents = async selector => {
      await page.locator(selector).first().evaluate(element => {
        for (let parent = element.parentElement; parent; parent = parent.parentElement) {
          if (parent.tagName === 'DETAILS') parent.open = true;
        }
      });
    };
    const visible = async (selector, expected = true) => {
      if (expected) await openParents(selector);
      return page.waitForSelector(selector, {state: expected ? 'visible' : 'hidden'});
    };
    const click = async selector => { await openParents(selector); await page.locator(selector).click(); };
    const select = async (selector, value) => { await openParents(selector); await page.locator(selector).selectOption(value); };
    const upload = async (selector, buffer, name = 'fictional.csv') => {
      await page.locator(selector).setInputFiles({name, mimeType: 'text/csv', buffer});
    };
    const timetableUpload = async (rows = timetableRows()) => {
      await upload('#timetable-file', csv(rows), 'fictional-timetable.csv');
      await click('#timetable-submit');
      await visible('#timetable-dashboard');
    };
    const image = async name => {
      if (!screenshotDir) return;
      fs.mkdirSync(screenshotDir, {recursive: true});
      await page.screenshot({path: path.join(screenshotDir, name), fullPage: true});
    };

    await page.goto(baseUrl.href, {waitUntil: 'networkidle'});
    await check('CSV inputs start open while other content starts collapsed in both tabs', async () => {
      assert.equal(await page.locator('.csv-upload-panel[open]').count(), 2);
      assert.equal(await page.locator('details[open]:not(.csv-upload-panel)').count(), 0);
      assert.equal(await page.locator('#upload-form').isVisible(), true);
      await image('collapsed-report-desktop.png');
      await click('#timetable-tab');
      assert.equal(await page.locator('#timetable-form').isVisible(), true);
      assert.equal(await page.locator('#credit-search-form').isVisible(), false);
      assert.equal(await page.locator('details[open]:not(.csv-upload-panel)').count(), 0);
      await image('collapsed-timetable-desktop.png');
      await page.setViewportSize({width: 320, height: 1000});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await image('collapsed-timetable-mobile.png');
      await page.setViewportSize({width: 1440, height: 1000});
      await click('#report-tab');
    });
    await check('summaries toggle by mouse and keyboard while retaining input values', async () => {
      const summary = page.locator('summary:has(#upload-heading)');
      assert.equal(await page.locator('#upload-form').isVisible(), true);
      await page.locator('#residence-years').fill('1.5');
      await summary.click();
      assert.equal(await page.locator('#upload-form').isVisible(), false);
      await summary.focus();
      await summary.press('Enter');
      assert.equal(await page.locator('#residence-years').inputValue(), '1.5');
      assert.equal(await page.locator('#upload-form').isVisible(), true);
      await page.locator('#residence-years').fill('');
      await summary.press('Enter');
      assert.equal(await page.locator('#upload-form').isVisible(), false);
      await summary.press('Enter');
    });
    await check('initial tabs and profile loading', async () => {
      await page.waitForFunction(() => document.querySelector('#profile-select').value !== '');
      assert.equal(await page.getByRole('tab').count(), 2);
      await visible('#report-panel');
      await visible('#timetable-panel', false);
      await page.locator('#report-tab').focus();
      await page.keyboard.press('ArrowRight');
      await visible('#timetable-panel');
      assert.equal(await page.locator('#timetable-tab').getAttribute('aria-selected'), 'true');
      await visible('#timetable-empty');
    });
    await check('credit search shows both missing CSVs without requesting the API', async () => {
      let requests = 0;
      const countRequest = request => { if (new URL(request.url()).pathname === '/api/v1/recommendation-searches') requests += 1; };
      page.on('request', countRequest);
      assert.equal(await page.locator('#credit-search-submit').isDisabled(), false);
      await click('#credit-search-submit');
      await visible('#credit-search-error');
      const message = await page.locator('#credit-search-error').textContent();
      assert.match(message, /成績CSVが選択されていません/);
      assert.match(message, /履修表CSVが選択されていません/);
      assert.equal(await page.locator('#credit-search-result').isVisible(), false);
      assert.equal(requests, 0);
      page.off('request', countRequest);
    });
    await check('credit search identifies either missing CSV and clears the error on file selection', async () => {
      let requests = 0;
      const countRequest = request => { if (new URL(request.url()).pathname === '/api/v1/recommendation-searches') requests += 1; };
      page.on('request', countRequest);
      await click('#report-tab');
      await upload('#csv-file', csv(gradeRows()));
      await click('#timetable-tab');
      await visible('#credit-search-error', false);
      await click('#credit-search-submit');
      await visible('#credit-search-error');
      assert.match(await page.locator('#credit-search-error').textContent(), /履修表CSVが選択されていません/);
      assert.doesNotMatch(await page.locator('#credit-search-error').textContent(), /成績CSVが選択されていません/);
      await upload('#timetable-file', csv(timetableRows()));
      await visible('#credit-search-error', false);
      await click('#report-tab');
      await click('#clear-report');
      await click('#timetable-tab');
      await click('#credit-search-submit');
      await visible('#credit-search-error');
      assert.match(await page.locator('#credit-search-error').textContent(), /成績CSVが選択されていません/);
      assert.doesNotMatch(await page.locator('#credit-search-error').textContent(), /履修表CSVが選択されていません/);
      assert.equal(requests, 0);
      page.off('request', countRequest);
      await click('#timetable-clear');
      await visible('#credit-search-error', false);
      await click('#credit-search-clear');
    });
    await check('missing timetable file has a Japanese error', async () => {
      await click('#timetable-submit');
      await visible('#timetable-error');
      assert.match(await page.locator('#timetable-error').textContent(), /選択/);
    });
    await check('catalog browsing works without CSV and cell click calls recommendation API', async () => {
      await page.waitForFunction(() => !document.querySelector('#recommendation-browse').disabled);
      await click('#recommendation-browse');
      await visible('#timetable-error', false);
      assert.equal(await page.locator('#recommendation-preview-grid .slot-picker').count(), 25);
      await click('#recommendation-preview-grid [data-weekday="1"][data-period="1"] button');
      await page.waitForFunction(() => document.querySelector('#recommendation-json').textContent.length > 0);
      const data = JSON.parse(await page.locator('#recommendation-json').textContent());
      assert.equal(data.basis, 'catalog');
      assert.equal(data.status, 'ok');
      assert.ok(data.candidates.length > 0);
      assert.equal(data.checks.timetable, 'not_provided');
      assert.equal(await page.locator('.recommendation-card').count(), data.candidates.length);
      await image('recommendation-catalog-desktop.png');
    });
    await check('an uncovered slot shows an empty result and term change clears it', async () => {
      await click('#recommendation-preview-grid [data-weekday="1"][data-period="5"] button');
      await page.waitForFunction(() => document.querySelector('#recommendation-json').textContent.length > 0);
      assert.equal(JSON.parse(await page.locator('#recommendation-json').textContent()).status, 'empty');
      assert.equal(await page.locator('.recommendation-card').count(), 0);
      await select('#recommendation-preview-term', '3');
      await visible('#recommendation-result', false);
      assert.equal(await page.locator('#recommendation-json').textContent(), '');
    });
    await check('actual timetable API upload and selected term slots', async () => {
      await timetableUpload();
      assert.equal(await page.locator('#timetable-term').inputValue(), '2026:3');
      assert.equal(await page.locator('#timetable-grid [data-state="occupied"]').count(), 3);
      assert.equal(await page.locator('#timetable-grid th[scope="col"]').count(), 7);
      assert.equal(await page.locator('#timetable-courses tr').count(), 1);
      assert.match(await page.locator('#timetable-policy-notes').textContent(), /0.*除外/);
      assert.match(await page.locator('#timetable-json').textContent(), /display_contexts/);
      assert.doesNotMatch(await page.locator('#timetable-json').textContent(), /架空 画面確認|架空科目|T00000000/);
      await image('timetable-desktop.png');
    });
    await check('uploaded timetable cell identifies occupied slots through the backend', async () => {
      await click('#timetable-grid [data-weekday="1"][data-period="1"] button');
      await page.waitForFunction(() => document.querySelector('#recommendation-json').textContent.length > 0);
      const data = JSON.parse(await page.locator('#recommendation-json').textContent());
      assert.equal(data.basis, 'timetable');
      assert.equal(data.status, 'occupied');
      assert.equal(data.candidates.length, 0);
      assert.doesNotMatch(await page.locator('#recommendation-json').textContent(), /架空 画面確認|T00000000|架空科目甲/);
    });
    const timetableReport = JSON.parse(await page.locator('#timetable-json').textContent());
    await check('term change does not mix another term into the grid', async () => {
      await select('#timetable-term', '2026:4');
      assert.equal(await page.locator('#timetable-grid [data-state="occupied"]').count(), 1);
      assert.match(await page.locator('#timetable-grid').textContent(), /264G9992/);
      assert.doesNotMatch(await page.locator('#timetable-grid').textContent(), /263G9991/);
      await select('#timetable-term', '2026:3');
    });
    await check('a free timetable cell returns candidates with full timetable checks', async () => {
      await click('#timetable-grid [data-weekday="2"][data-period="2"] button');
      await page.waitForFunction(() => document.querySelector('#recommendation-json').textContent.length > 0);
      const data = JSON.parse(await page.locator('#recommendation-json').textContent());
      assert.equal(data.basis, 'timetable');
      assert.equal(data.checks.timetable, 'checked');
      assert.ok(data.candidates.length > 0);
      await image('recommendation-timetable-desktop.png');
      await page.setViewportSize({width: 320, height: 1000});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await image('recommendation-mobile.png');
      await page.setViewportSize({width: 1440, height: 1000});
    });
    await check('grade values and missing grade do not change candidates or block free cells', async () => {
      let expected;
      for (const grade of ['GRADE', '', '1年', '2年', '3年', '4年']) {
        const rows = timetableRows();
        rows.find(row => row[0] === '[学年]')[1] = grade;
        await timetableUpload(rows);
        await click('#timetable-grid [data-weekday="2"][data-period="2"] button');
        await page.waitForFunction(() => document.querySelector('#recommendation-json').textContent.length > 0);
        const data = JSON.parse(await page.locator('#recommendation-json').textContent());
        assert.equal(data.status, 'ok');
        assert.ok(data.candidates.length > 0);
        assert.equal(data.checks.grade, undefined);
        if (expected) assert.deepEqual(data.candidates, expected);
        expected = data.candidates;
      }
    });
    await check('grade upload uses its separate API and preserves timetable', async () => {
      await click('#report-tab');
      await upload('#csv-file', csv(gradeRows()), 'fictional-grades.csv');
      await click('#submit');
      await visible('#dashboard');
      assert.match(await page.locator('#student').textContent(), /架空 画面確認.*T00000000/);
      assert.equal(await page.locator('#evaluations .evaluation').count(), 2);
      await click('#timetable-tab');
      await visible('#timetable-dashboard');
      assert.equal(await page.locator('#timetable-term').inputValue(), '2026:3');
      await click('#report-tab');
      await visible('#dashboard');
      await image('report-desktop.png');
    });
    await check('credit search shares both files and returns independently simulated benefits', async () => {
      await click('#timetable-tab');
      assert.equal(await page.locator('#credit-search-submit').isDisabled(), false);
      await select('#credit-search-term', '3');
      await click('#credit-search-submit');
      await page.waitForFunction(() => document.querySelector('#credit-search-json').textContent.length > 0);
      const data = JSON.parse(await page.locator('#credit-search-json').textContent());
      assert.equal(data.status, 'ok');
      assert.equal(data.target_requirement_id, 'graduation');
      assert.ok(data.candidates.length > 0);
      assert.ok(data.candidates.every(course => course.benefits.length > 0));
      assert.equal(data.checks.earned_credits, 'checked');
      assert.doesNotMatch(await page.locator('#credit-search-json').textContent(), /架空 画面確認|T00000000|架空教養科目/);
      await image('credit-search-desktop.png');
      await page.setViewportSize({width: 320, height: 1000});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await image('credit-search-mobile.png');
      await page.setViewportSize({width: 1440, height: 1000});
    });
    await check('search results and course details start closed and expand without another request', async () => {
      assert.equal(await page.locator('#credit-search-result').evaluate(element => element.open), false);
      assert.equal(await page.locator('#credit-search-candidates details[open]').count(), 0);
      const resultSummary = page.locator('#credit-search-result > summary');
      await resultSummary.click();
      const first = page.locator('#credit-search-candidates .recommendation-card').first();
      assert.equal(await first.locator('.credit-search-benefits').isVisible(), false);
      await first.locator('summary').click();
      assert.equal(await first.locator('.credit-search-benefits').isVisible(), true);
      await first.locator('summary').click();
      assert.equal(await first.locator('.credit-search-benefits').isVisible(), false);
      assert.equal(await first.locator('summary').isVisible(), true);
    });
    await check('credit search excludes earned names across offering codes', async () => {
      const previous = JSON.parse(await page.locator('#credit-search-json').textContent());
      const acquired = previous.candidates[0];
      await click('#report-tab');
      const rows = gradeRows();
      rows.push(['2', '10', '1', 'FAKE-PREVIOUS-CODE', acquired.name, acquired.category, '選択', String(acquired.credits), '合']);
      await upload('#csv-file', csv(rows));
      await click('#timetable-tab');
      assert.equal(await page.locator('#credit-search-json').textContent(), '');
      await click('#credit-search-submit');
      await page.waitForFunction(() => document.querySelector('#credit-search-json').textContent.length > 0);
      const data = JSON.parse(await page.locator('#credit-search-json').textContent());
      assert.ok(data.counts.excluded_earned > 0);
      assert.ok(![...data.candidates, ...data.review_candidates].some(course => course.name === acquired.name));
    });
    await check('uncertain grades are separated from confirmed shortage recommendations', async () => {
      await click('#report-tab');
      const rows = gradeRows();
      rows[1] = ['No.', '分野', '水準', '開講番号', '科目', '科目区分', '必選区分', '単位数', '合否'];
      rows[2] = ['1', '10', '1', 'FAKE-UNCERTAIN', '架空未確定科目', '未確認の区分', '選択', '2', ''];
      await upload('#csv-file', csv(rows));
      await click('#timetable-tab');
      await click('#credit-search-submit');
      await page.waitForFunction(() => document.querySelector('#credit-search-json').textContent.length > 0);
      const data = JSON.parse(await page.locator('#credit-search-json').textContent());
      assert.equal(data.status, 'unknown');
      assert.equal(data.candidates.length, 0);
      assert.ok(data.review_candidates.length > 0);
      await visible('#credit-search-review');
      await click('#credit-search-clear');
      assert.equal(await page.locator('#credit-search-json').textContent(), '');
    });
    await check('credit search failure clears previous cards without affecting slot browsing', async () => {
      await page.route('**/api/v1/recommendation-searches', route => route.fulfill({status: 422,
        json: {error: {code: 'invalid_csv', message: '架空の入力エラー'}}}));
      await click('#credit-search-submit');
      await visible('#credit-search-error');
      assert.match(await page.locator('#credit-search-error').textContent(), /架空の入力エラー/);
      assert.equal(await page.locator('#credit-search-candidates .recommendation-card').count(), 0);
      await page.unroute('**/api/v1/recommendation-searches');
    });
    await check('credit search ignores an old response after either file changes', async () => {
      let release;
      const held = new Promise(resolve => { release = resolve; });
      await page.route('**/api/v1/recommendation-searches', async route => {
        await held;
        await route.fulfill({status: 200, json: {schema_version: 1}});
      });
      await page.evaluate(() => {
        window.searchOriginalFetch = window.fetch;
        window.fetch = (url, options = {}) => window.searchOriginalFetch(url, {...options, signal: undefined});
      });
      const requested = page.waitForRequest('**/api/v1/recommendation-searches');
      await click('#credit-search-submit');
      await requested;
      await click('#timetable-clear');
      const responded = page.waitForResponse('**/api/v1/recommendation-searches');
      release();
      await responded;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(await page.locator('#credit-search-json').textContent(), '');
      await visible('#credit-search-error', false);
      await visible('#credit-search-result', false);
      assert.equal(await page.locator('#credit-search-submit').isDisabled(), false);
      await page.unroute('**/api/v1/recommendation-searches');
      await page.evaluate(() => { window.fetch = window.searchOriginalFetch; delete window.searchOriginalFetch; });
      await timetableUpload();
      await click('#report-tab');
      await upload('#csv-file', csv(gradeRows()), 'fictional-grades.csv');
      await click('#submit');
      await visible('#dashboard');
      await click('#timetable-tab');
    });
    await check('responsive layouts keep overflow inside scrollable tables', async () => {
      for (const width of [320, 768, 1440]) {
        await page.setViewportSize({width, height: 1000});
        for (const tab of ['#report-tab', '#timetable-tab']) {
          await click(tab);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true,
            `page overflow at ${width}px in ${tab}`);
        }
        if (width === 320) await image('timetable-mobile.png');
      }
    });
    await check('clear only erases the selected feature', async () => {
      await click('#timetable-clear');
      await visible('#timetable-dashboard', false);
      assert.equal(await page.locator('#timetable-json').textContent(), '');
      assert.equal(await page.locator('#timetable-file').inputValue(), '');
      await click('#report-tab');
      await visible('#dashboard');
      await click('#clear-report');
      await visible('#dashboard', false);
      assert.equal(await page.locator('#json').textContent(), '');
      await click('#timetable-tab');
    });
    await check('unresolved information is never displayed as confirmed free time', async () => {
      await timetableUpload(timetableRows({unresolved: true}));
      assert.equal(await page.locator('#timetable-grid [data-state="empty"]').count(), 0);
      assert.ok(await page.locator('#timetable-grid [data-state="unconfirmed"]').count() > 0);
      assert.match(await page.locator('#timetable-readiness').textContent(), /要確認/);
      await visible('#timetable-warnings');
    });
    await check('unknown timetable status is preserved when a recommendation cell is clicked', async () => {
      await click('#timetable-grid [data-weekday="2"][data-period="2"] button');
      await page.waitForFunction(() => document.querySelector('#recommendation-json').textContent.length > 0);
      assert.equal(JSON.parse(await page.locator('#recommendation-json').textContent()).status, 'unknown');
      assert.equal(await page.locator('.recommendation-card').count(), 0);
    });
    await check('explicit empty semester still displays both terms', async () => {
      await timetableUpload(timetableRows({empty: true}));
      assert.equal(await page.locator('#timetable-term option').count(), 2);
      assert.equal(await page.locator('#timetable-grid [data-state="occupied"]').count(), 0);
      assert.equal(await page.locator('#timetable-grid [data-state="empty"]').count(), 42);
      await select('#timetable-term', '2026:4');
      assert.equal(await page.locator('#timetable-grid [data-state="empty"]').count(), 42);
    });
    await check('unknown year and term are not guessed for an empty timetable', async () => {
      await timetableUpload(timetableRows({empty: true, metadata: false}));
      assert.equal(await page.locator('#timetable-term').isDisabled(), true);
      assert.equal(await page.locator('#timetable-grid [data-state="empty"]').count(), 0);
      assert.equal(await page.locator('#timetable-grid [data-state="unconfirmed"]').count(), 42);
    });
    await check('new selection and invalid upload remove previous results', async () => {
      await timetableUpload();
      await upload('#timetable-file', Buffer.from('not,a,timetable\r\n'), 'fictional-invalid.csv');
      await visible('#timetable-dashboard', false);
      assert.equal(await page.locator('#timetable-json').textContent(), '');
      await click('#timetable-submit');
      await visible('#timetable-error');
      assert.equal(await page.locator('#timetable-submit').isEnabled(), true);
    });
    await check('drag and drop uses the new file and clears the native input', async () => {
      await page.locator('#timetable-drop-zone').evaluate((element, source) => {
        const transfer = new DataTransfer();
        transfer.items.add(new File([source], 'fictional-dropped.csv', {type: 'text/csv'}));
        element.dispatchEvent(new DragEvent('drop', {dataTransfer: transfer, bubbles: true, cancelable: true}));
      }, csv(timetableRows()).toString('utf8'));
      assert.equal(await page.locator('#timetable-file').inputValue(), '');
      assert.equal(await page.locator('#timetable-selected-file').textContent(), 'fictional-dropped.csv');
      await click('#timetable-submit');
      await visible('#timetable-dashboard');
    });
    for (const [name, response] of [
      ['non-JSON response', {status: 200, contentType: 'text/html', body: '<html>fictional</html>'}],
      ['incompatible JSON response', {status: 200, json: {schema_version: 999}}],
      ['missing API', {status: 404, json: {error: {message: '架空APIエラー'}}}],
    ]) {
      await check(`${name} is displayed without stale results`, async () => {
        await page.route('**/api/v1/timetables', route => route.fulfill(response));
        await upload('#timetable-file', csv(timetableRows()));
        await click('#timetable-submit');
        await visible('#timetable-error');
        await visible('#timetable-dashboard', false);
        assert.equal(await page.locator('#timetable-json').textContent(), '');
        await page.unroute('**/api/v1/timetables');
      });
    }
    await check('clearing an in-flight request rejects even an uncancelled old response', async () => {
      let release;
      const held = new Promise(resolve => { release = resolve; });
      await page.route('**/api/v1/timetables', async route => {
        await held;
        await route.fulfill({status: 200, json: timetableReport});
      });
      await page.evaluate(() => {
        window.originalFetchForTest = window.fetch;
        window.fetch = (url, options = {}) => window.originalFetchForTest(url, {...options, signal: undefined});
      });
      await upload('#timetable-file', csv(timetableRows()));
      const requested = page.waitForRequest('**/api/v1/timetables');
      await click('#timetable-submit');
      await requested;
      assert.equal(await page.locator('#timetable-submit').isDisabled(), true);
      await click('#timetable-clear');
      const responded = page.waitForResponse('**/api/v1/timetables');
      release();
      await responded;
      await page.waitForFunction(() => document.querySelector('#timetable-form').getAttribute('aria-busy') === 'false');
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await visible('#timetable-dashboard', false);
      assert.equal(await page.locator('#timetable-json').textContent(), '');
      await page.unroute('**/api/v1/timetables');
      await page.evaluate(() => { window.fetch = window.originalFetchForTest; delete window.originalFetchForTest; });
    });
    await check('grade text is rendered safely and context changes invalidate it', async () => {
      await click('#report-tab');
      await upload('#csv-file', csv(gradeRows('<img src=x onerror=window.csvXss=true>')));
      await click('#submit');
      await visible('#dashboard');
      assert.equal(await page.locator('#student img').count(), 0);
      assert.equal(await page.evaluate(() => window.csvXss === true), false);
      await openParents('#residence-years');
      await page.locator('#residence-years').fill('1');
      await visible('#dashboard', false);
      assert.equal(await page.locator('#json').textContent(), '');
    });
    await check('recommendation API failure clears cards and displays a useful error', async () => {
      await click('#timetable-tab');
      await click('#timetable-clear');
      await click('#recommendation-browse');
      await page.route('**/api/v1/recommendations', route => route.fulfill({status: 503, json: {error: {code: 'fictional_error', message: '架空のカタログエラー'}}}));
      await click('#recommendation-preview-grid [data-weekday="2"][data-period="2"] button');
      await page.waitForFunction(() => document.querySelector('#recommendation-status').textContent.includes('架空のカタログエラー'));
      assert.equal(await page.locator('.recommendation-card').count(), 0);
      assert.equal(await page.locator('#recommendation-json').textContent(), '');
      await page.unroute('**/api/v1/recommendations');
    });
    await check('switching recommendation cells rejects an old uncancelled response', async () => {
      let release;
      const held = new Promise(resolve => { release = resolve; });
      let calls = 0;
      await page.route('**/api/v1/recommendations', async route => {
        calls += 1;
        if (calls > 1) return route.continue();
        await held;
        await route.fulfill({status: 200, json: {
          schema_version: 1, context: {academic_year: 2026, term: 3, weekday: 1, period: 1},
          basis: 'catalog', status: 'empty', candidates: [], messages: [],
          checks: {timetable: 'not_provided'}, counts: {matching: 0, returned: 0, excluded_overlap: 0, excluded_unconfirmed: 0, excluded_registered: 0},
        }});
      });
      await page.evaluate(() => {
        window.originalFetchForTest = window.fetch;
        window.fetch = (url, options = {}) => window.originalFetchForTest(url, {...options, signal: undefined});
      });
      const requested = page.waitForRequest('**/api/v1/recommendations');
      await click('#recommendation-preview-grid [data-weekday="1"][data-period="1"] button');
      await requested;
      await click('#recommendation-preview-grid [data-weekday="2"][data-period="2"] button');
      await page.waitForFunction(() => {
        const raw = document.querySelector('#recommendation-json').textContent;
        return raw && JSON.parse(raw).context.weekday === 2;
      });
      const responded = page.waitForResponse('**/api/v1/recommendations');
      release();
      await responded;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(JSON.parse(await page.locator('#recommendation-json').textContent()).context.weekday, 2);
      await page.unroute('**/api/v1/recommendations');
      await page.evaluate(() => { window.fetch = window.originalFetchForTest; delete window.originalFetchForTest; });
    });
    await check('reload discards data and browser persistence is empty', async () => {
      await click('#timetable-tab');
      await timetableUpload();
      assert.deepEqual(await page.evaluate(() => [localStorage.length, sessionStorage.length]), [0, 0]);
      assert.deepEqual(await context.cookies(), []);
      await page.reload({waitUntil: 'networkidle'});
      await visible('#dashboard', false);
      await click('#timetable-tab');
      await visible('#timetable-dashboard', false);
      assert.equal(await page.locator('#timetable-json').textContent(), '');
      assert.equal(await page.locator('#timetable-file').inputValue(), '');
    });
    assert.deepEqual(pageErrors, [], 'browser JavaScript errors');
    assert.deepEqual(outsideRequests, [], 'external network requests');
    console.log(JSON.stringify({passed: count, browser_errors: 0, external_requests: 0, screenshots: Boolean(screenshotDir)}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
