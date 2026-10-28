/* API仕様とlocalhostのHTTP応答だけで試作UIを検証する。Pythonや既存UIをimportしない。
 * 使用するCSVは既知の架空サンプルとメモリ内生成のみ。応答・CSV・トレースを保存しない。
 */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const args=process.argv.slice(2);
const option=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const base=new URL(option('--base-url','http://localhost:8000'));
assert.equal(base.protocol,'http:');
assert(['localhost','127.0.0.1','[::1]'].includes(base.hostname),'localhostだけを使用する');
const examples=option('--examples-dir',path.join(process.cwd(),'examples'));
const screenshotDir=option('--screenshot-dir',null);
const firstYear=fs.readFileSync(path.join(examples,'first-year-sample.csv'));
const graduation=fs.readFileSync(path.join(examples,'graduation-sample-original-format.csv'));
assert(firstYear.toString('utf8').includes('架空'));
assert(new TextDecoder('shift_jis').decode(graduation).includes('架空'));
function csv(rows) {return Buffer.from(rows.map(row=>row.map(value=>'"'+String(value).replaceAll('"','""')+'"').join(',')).join('\r\n')+'\r\n');}
function timetable({empty=false,unknown=false,year=2026}={}) {
  const rows=[['[年度・学期]',unknown?'年度未確認':`${year}年度 第2学期`],['','月曜日','火曜日','水曜日','木曜日','金曜日']];
  for(let period=1;period<=5;period++) {
    const block=[[`${period}限`,'','','','',''],['','','','','',''],['','','','','','']];
    if(!empty && period===1) {block[0][1]='263G9991';block[1][1]='架空の登録科目';block[2][1]='架空教員';}
    if(!empty && period===2) {block[0][1]='264G9992';block[1][1]='架空の別ターム科目';block[2][1]='架空教員';}
    rows.push(...block);
  }
  if(!empty)rows.push(['集中講義','260T9999','','','','']);
  return csv(rows);
}

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'chrome'}:{}),...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
  let passed=0;
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:false});
    const outside=[],exceptions=[],policyErrors=[];
    await context.route('**/*',route=>{
      if(new URL(route.request().url()).origin!==base.origin){outside.push('outside-origin');return route.abort();}
      return route.continue();
    });
    const page=await context.newPage();page.setDefaultTimeout(12000);
    page.on('pageerror',error=>exceptions.push(error.message));
    page.on('console',message=>{if(message.type()==='error' && /Content Security Policy|Refused to/.test(message.text()))policyErrors.push('csp-error');});
    const check=async(name,action)=>{await action();passed++;console.log(`PASS ${String(passed).padStart(2,'0')} ${name}`);};
    const view=async(name)=>page.locator(`[data-view="${name}"]`).click();
    const image=async name=>{if(screenshotDir){fs.mkdirSync(screenshotDir,{recursive:true});await page.screenshot({path:path.join(screenshotDir,name),fullPage:false});}};
    const upload=async(selector,buffer,name)=>page.locator(selector).setInputFiles({name,mimeType:'text/csv',buffer});
    const grades=async(buffer=firstYear)=>{
      await view('overview');
      const responded=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/reports' && response.request().method()==='POST');
      await upload('#grades-input',buffer,'fictional-grades.csv');
      const response=await responded;assert.equal(response.status(),200);
      const data=await response.json();
      await page.waitForFunction(credits=>document.querySelector('#grades-status').textContent.includes(`${credits} 単位`),data.summary.earned_credits);
      return data;
    };
    const times=async(buffer=timetable())=>{
      await view('timetable');
      const responded=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/timetables' && response.request().method()==='POST');
      await upload('#timetable-input',buffer,'fictional-timetable.csv');
      const response=await responded;assert.equal(response.status(),200);
      const data=await response.json();
      await page.waitForFunction(()=>document.querySelector('#timetable-status').textContent.startsWith('時間割'));
      return data;
    };
    const find=async()=>{
      const responded=page.waitForResponse('**/api/v1/recommendation-searches');
      await page.locator('#search-button').click();
      const response=await responded;assert.equal(response.status(),200);
      const data=await response.json();
      await page.waitForFunction(()=>document.querySelector('#search-results').getAttribute('aria-busy')==='false');
      return data;
    };
    const slot=async(weekday,period)=>{
      const responded=page.waitForResponse('**/api/v1/recommendations');
      await page.locator(`[data-slot="${weekday}:${period}"]`).click();
      const response=await responded;assert.equal(response.status(),200);
      const data=await response.json();
      await page.waitForFunction(()=>document.querySelector('#slot-candidates').getAttribute('aria-busy')==='false');
      return data;
    };
    const frame=async()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.goto(new URL('/prototype/',base).href,{waitUntil:'networkidle'});
    await check('standalone UI loads using documented metadata, with no legacy globals',async()=>{
      await page.waitForFunction(()=>!document.querySelector('#profile-select').disabled);
      assert.equal(await page.locator('[data-view]').count(),3);
      assert.equal(await page.locator('#overview-empty').isVisible(),true);
      assert.equal(await page.locator('#view-timetable select[name="profile_id"]').count(),0);
      assert.equal(await page.evaluate(()=>typeof window.creditWorkspace),'undefined');
      assert.equal(await page.evaluate(()=>typeof window.createRecommendationClient),'undefined');
      await image('prototype-empty-desktop.png');
    });
    await check('search with no CSVs explains both missing inputs without sending student data',async()=>{
      await view('timetable');let calls=0;
      const listener=request=>{if(request.url().endsWith('/api/v1/recommendation-searches'))calls++;};
      page.on('request',listener);await page.locator('#search-button').click();
      assert.match(await page.locator('#search-error').textContent(),/成績CSV.*履修表CSV/s);
      assert.equal(calls,0);page.off('request',listener);
    });
    await check('catalog browsing needs neither a transcript nor an earlier analysis request',async()=>{
      await page.waitForSelector('[data-slot="1:1"]');
      const result=await slot(1,1);
      assert.equal(result.basis,'catalog');assert.equal(result.status,'ok');assert(result.candidates.length>0);
      assert.match(await page.locator('#slot-status').textContent(),/重複は未確認/);
      assert.equal(await page.locator('#slot-candidates .candidate-card').count(),result.candidates.length);
    });
    let graduateReport;
    await check('CP932 graduation sample displays exact API totals and student information',async()=>{
      graduateReport=await grades(graduation);
      assert.equal(graduateReport.summary.earned_credits,124);
      const stats=await page.locator('#stats .stat-number').allTextContents();
      assert.deepEqual(stats,['124単位','36単位','88単位','0単位']);
      assert.match(await page.locator('#student-name').textContent(),/架空/);
      assert.match(await page.locator('#student-meta').textContent(),/T00000000/);
      assert.equal(await page.locator('.evaluation[data-status="satisfied"]').count(),1);
      await image('prototype-graduation-desktop.png');
    });
    await check('requirement details, individual compulsory courses and official references are readable',async()=>{
      await page.locator('.evaluation > .condition-details > summary').click();
      assert.equal(await page.locator('.required-courses li').count(),16);
      await page.locator('.required-courses').evaluate(list=>list.closest('details').open=true);
      assert.equal(await page.locator('.required-courses li .badge.satisfied').count(),16);
      assert.equal(await page.locator('.evidence-details a').count()>0,true);
    });
    await check('course list filters, searches and paginates all transcript rows',async()=>{
      await view('courses');assert.equal(await page.locator('#course-rows tr').count(),25);
      assert.match(await page.locator('#course-count').textContent(),/58/);
      await page.locator('#course-filter-count button').filter({hasText:'次へ'}).click();
      assert.match(await page.locator('#course-filter-count').textContent(),/26–50/);
      await page.locator('#course-search').fill('プログラミング');
      const matched=graduateReport.courses.filter(course=>course.name.includes('プログラミング'));
      assert.equal(await page.locator('#course-rows tr').count(),matched.length);
      await page.locator('#course-search').fill('');await page.locator('#course-area').selectOption('liberal_arts');
      assert.equal(await page.locator('#course-rows tr').count(),10);
      await page.locator('#course-area').selectOption('all');
    });
    await check('one missing CSV produces a specific actionable error',async()=>{
      await view('timetable');await page.locator('#search-button').click();
      assert.match(await page.locator('#search-error').textContent(),/履修表CSV/);
      assert.doesNotMatch(await page.locator('#search-error').textContent(),/成績CSVを/);
    });
    await check('actual timetable response drives semesters, occupied slots and policy warnings',async()=>{
      const response=await times();assert.equal(response.ready_for_recommendation,true);
      assert.equal(await page.locator('.term-tab').count(),2);
      assert.equal(await page.locator('.slot-button.occupied').count(),1);
      assert.match(await page.locator('#timetable-notes').textContent(),/0/);
      await image('prototype-timetable-desktop.png');
    });
    await check('complete liberal requirements suppress shortage recommendations',async()=>{
      const data=await find();assert.equal(data.status,'empty');assert.equal(data.candidates.length,0);
      assert.match(await page.locator('#search-status').textContent(),/すべて充足/);
      assert.equal(await page.locator('#search-candidates .candidate-card').count(),0);
    });
    let firstReport;
    await check('switching transcripts clears old recommendations and shows year-specific evaluations',async()=>{
      firstReport=await grades();assert.equal(firstReport.summary.earned_credits,34);
      assert.equal(await page.locator('.evaluation').count(),2);
      assert.equal(await page.locator('#search-results').isVisible(),false);
      assert.equal(await page.locator('#stats .stat-number').first().textContent(),'34単位');
      await image('prototype-overview-desktop.png');
    });
    await check('all conditions start collapsed and appear exactly once when expanded',async()=>{
      const cards=page.locator('.evaluation');
      for(let index=0;index<firstReport.evaluations.length;index++) {
        const card=cards.nth(index),conditions=firstReport.evaluations[index].conditions;
        assert.equal(await card.locator('.condition-row:visible').count(),0);
        assert.equal(await card.locator(':scope > .condition-list').count(),0);
        assert.equal(await card.locator('.condition-row').count(),conditions.length);
        await card.locator(':scope > .condition-details > summary').click();
        assert.equal(await card.locator('.condition-row:visible').count(),conditions.length);
        assert.deepEqual(await card.locator('.condition-label').allTextContents(),conditions.map(condition=>condition.label));
        await card.locator(':scope > .condition-details > summary').click();
        assert.equal(await card.locator('.condition-row:visible').count(),0);
      }
    });
    await check('conditions can be narrowed to shortages without recalculating academic judgments',async()=>{
      await page.locator('#filter-conditions').click();
      assert.equal(await page.locator('#filter-conditions').getAttribute('aria-pressed'),'true');
      assert.equal(await page.locator('.evaluation[data-status="satisfied"]').count(),1);
      const cards=page.locator('.evaluation');
      for(let index=0;index<firstReport.evaluations.length;index++) {
        const card=cards.nth(index),needs=firstReport.evaluations[index].conditions.filter(condition=>condition.status!=='satisfied');
        assert.equal(await card.locator('.condition-row:visible').count(),0);
        await card.locator(':scope > .condition-details > summary').click();
        assert.deepEqual(await card.locator('.condition-label').allTextContents(),needs.map(condition=>condition.label));
        assert.equal(await card.locator('.condition-row:visible').count(),needs.length);
      }
      await page.locator('#filter-conditions').click();
      assert.equal(await page.locator('.evaluation .condition-row:visible').count(),0);
    });
    await check('student-facing text omits development labels while retaining academic and timetable cautions',async()=>{
      await page.locator('#policy-details > summary').click();
      assert.doesNotMatch(await page.locator('body').innerText(),/MVP|試作|プロトタイプ|デバッグ/iu);
      assert.match(await page.locator('#policy-notes').innerText(),/大学の正式な他プログラム科目の取扱いとは異なります/);
      assert.match(await page.locator('#policy-details').innerText(),/不合格を意味しません/);
      await page.locator('.evaluation').last().locator(':scope > .condition-details > summary').click();
      assert.match(await page.locator('.evaluation').last().innerText(),/在学期間を1年/);
      assert.doesNotMatch(await page.locator('body').innerText(),/MVP/iu);
      await page.locator('.evaluation').last().locator(':scope > .condition-details > summary').click();
      await page.locator('#policy-details > summary').click();
      await page.locator('#help-button').click();
      assert.equal(await page.locator('#help-dialog a[href="/"]').count(),0);
      assert.doesNotMatch(await page.locator('#help-dialog').innerText(),/従来|MVP|試作|API/iu);
      await page.keyboard.press('Escape');
      await view('timetable');
      assert.doesNotMatch(await page.locator('#calendar-scope').innerText(),/代表/);
      assert.doesNotMatch(await page.locator('#timetable-notes').innerText(),/MVP/iu);
      assert.match(await page.locator('#timetable-notes').innerText(),/除外した科目との時間重複は確認しません/);
      await view('overview');
    });
    let recommendationResult;
    await check('shortage search uses both original files and the report-side profile',async()=>{
      await view('timetable');recommendationResult=await find();
      assert.equal(recommendationResult.status,'ok');assert(recommendationResult.candidates.length>0);
      assert.equal(await page.locator('#search-candidates .candidate-card').count(),recommendationResult.candidates.length);
      assert.equal(recommendationResult.context.profile_id,await page.locator('#profile-select').inputValue());
      assert.equal(await page.locator('#search-candidates .candidate-benefits').count()>0,true);
    });
    await check('free and occupied cells preserve backend result meanings',async()=>{
      const free=await slot(2,2);assert.equal(free.status,'ok');assert.equal(free.checks.timetable,'checked');
      const occupied=await slot(1,1);assert.equal(occupied.status,'occupied');
      assert.equal(await page.locator('#slot-candidates .candidate-card').count(),0);
      assert.match(await page.locator('#slot-status').textContent(),/通常授業があります/);
    });
    await check('term changes clear results and never mix another terms busy cells',async()=>{
      await page.locator('.term-tab').filter({hasText:'第4ターム'}).click();
      assert.equal(await page.locator('#search-results').isVisible(),false);
      assert.match(await page.locator('.slot-button.occupied').textContent(),/264G9992/);
      await page.locator('.term-tab').filter({hasText:'第3ターム'}).click();
    });
    await check('desktop, tablet and mobile layouts contain their own scrolling tables',async()=>{
      for(const width of [1440,768,375,320]) {
        await page.setViewportSize({width,height:900});
        for(const name of ['overview','timetable','courses']) {
          await view(name);
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`${name} at ${width}`);
        }
        if(width===375){await view('overview');await page.evaluate(()=>scrollTo(0,0));await image('prototype-mobile.png');}
      }
      await page.setViewportSize({width:1440,height:1050});
    });
    await check('help dialog opens by keyboard and Escape returns focus',async()=>{
      await page.locator('#help-button').focus();await page.keyboard.press('Enter');
      assert.equal(await page.locator('#help-dialog').isVisible(),true);
      await page.keyboard.press('Escape');assert.equal(await page.locator('#help-dialog').isVisible(),false);
      assert.equal(await page.locator('#help-button').evaluate(button=>button===document.activeElement),true);
    });
    await check('unknown results and null credit values are never converted to failure or zero',async()=>{
      const data=structuredClone(firstReport);data.summary.earned_credits=null;
      for(const evaluation of data.evaluations){evaluation.status='unknown';evaluation.description='架空の情報不足による判定不能';for(const condition of evaluation.conditions){condition.status='unknown';condition.confirmed_credits=null;}}
      await page.route('**/api/v1/reports',route=>route.fulfill({json:data}));
      await view('overview');await upload('#grades-input',firstYear,'fictional-unknown.csv');
      await page.waitForFunction(()=>document.querySelectorAll('.evaluation[data-status="unknown"]').length===2);
      assert.equal(await page.locator('.evaluation[data-status="not_satisfied"]').count(),0);
      assert.equal(await page.locator('#stats .stat-number').first().textContent(),'—単位');
      await page.unroute('**/api/v1/reports');
    });
    await check('CSV-sourced HTML is displayed as text',async()=>{
      const text='<img src=x onerror=window.prototypeXss=true>';
      const buffer=csv([['[学生氏名]',text,'[在籍番号]','T00000000','[学年]','1'],['No.','科目','科目区分','単位数','合否'],['1',text,'英語（英語）','2','合']]);
      await grades(buffer);assert.equal(await page.locator('#student-name').textContent(),text);
      assert.equal(await page.locator('#student-name img').count(),0);
      assert.equal(await page.evaluate(()=>window.prototypeXss===true),false);
    });
    await check('passed, failed and unconfirmed CSV rows match the documented course states',async()=>{
      const buffer=csv([['[学生氏名]','架空の状態確認','[在籍番号]','T00000000','[学年]','1'],['No.','科目','科目区分','単位数','合否'],
        ['1','架空の修得科目','英語（英語）','2','合'],['2','架空の未修得科目','英語（英語）','2','否'],['3','架空の未確定科目','英語（英語）','2','']]);
      const data=await grades(buffer);
      assert.deepEqual(data.courses.map(course=>[course.result,course.status]),[['passed','passed'],['failed','failed'],['unconfirmed','unconfirmed']]);
      await view('courses');await page.locator('#course-result').selectOption('failed');
      assert.equal(await page.locator('#course-rows .badge.failed').count(),1);
      await page.locator('#course-result').selectOption('unconfirmed');
      assert.equal(await page.locator('#course-rows .badge.unconfirmed').count(),1);
      await page.locator('#course-result').selectOption('all');
      await view('overview');
    });
    await check('non-JSON and incompatible API responses clear previous student results',async()=>{
      for(const response of [{status:502,contentType:'text/html',body:'fictional gateway error'},{status:200,json:{schema_version:2}},{status:200,json:{schema_version:999}},{status:503,json:{error:{code:'fictional_missing_message'}}}]) {
        await page.route('**/api/v1/reports',route=>route.fulfill(response));
        await upload('#grades-input',firstYear,'fictional-invalid-response.csv');
        await page.waitForSelector('#grades-error:not([hidden])');
        assert.equal(await page.locator('#overview-results').isVisible(),false);
        assert.equal(await page.locator('#student-name').textContent(),'');
        assert.doesNotMatch(await page.locator('#grades-error').innerText(),/API|HTTP|schema_version/iu);
        await page.unroute('**/api/v1/reports');
      }
    });
    await check('upload size and empty-file errors are shown without making a request',async()=>{
      let requests=0;const listener=request=>{if(request.url().endsWith('/api/v1/reports'))requests++;};page.on('request',listener);
      await upload('#grades-input',Buffer.alloc(0),'fictional-empty.csv');assert.match(await page.locator('#grades-error').textContent(),/空のファイル/);
      await upload('#grades-input',Buffer.alloc(5*1024*1024+1),'fictional-large.csv');assert.match(await page.locator('#grades-error').textContent(),/5 MB/);
      assert.equal(requests,0);page.off('request',listener);
    });
    await check('HTTP errors recover when a valid CSV is chosen again',async()=>{
      await page.route('**/api/v1/reports',route=>route.fulfill({status:503,json:{error:{code:'fictional_failure',message:'架空の一時エラーです。'}}}));
      await upload('#grades-input',firstYear,'fictional-retry.csv');await page.waitForSelector('#grades-error:not([hidden])');
      assert.match(await page.locator('#grades-error').textContent(),/架空の一時エラー/);
      await page.unroute('**/api/v1/reports');await grades();assert.equal(await page.locator('#grades-error').isVisible(),false);
    });
    await check('late transcript responses cannot overwrite a newer selected file',async()=>{
      let release;const held=new Promise(resolve=>{release=resolve;});let calls=0;
      await page.route('**/api/v1/reports',async route=>{if(++calls>1)return route.continue();await held;await route.fulfill({json:firstReport});});
      await page.evaluate(()=>{window.originalPrototypeFetch=window.fetch;window.fetch=(url,options={})=>window.originalPrototypeFetch(url,{...options,signal:undefined});});
      const requested=page.waitForRequest('**/api/v1/reports');await upload('#grades-input',firstYear,'fictional-old.csv');await requested;
      await grades(graduation);
      const responded=page.waitForResponse('**/api/v1/reports');release();await responded;await frame();
      assert.equal(await page.locator('#stats .stat-number').first().textContent(),'124単位');
      await page.unroute('**/api/v1/reports');await page.evaluate(()=>{window.fetch=window.originalPrototypeFetch;delete window.originalPrototypeFetch;});
    });
    await check('unknown timetable years do not create guessed free time',async()=>{
      await times(timetable({empty:true,unknown:true}));
      assert.equal(await page.locator('.slot-button').count(),0);
      assert.match(await page.locator('#calendar-grid').textContent(),/開講年度・タームを確認できません/);
    });
    await check('a year without catalog data does not reuse another years offerings',async()=>{
      await times(timetable({empty:true,year:2027}));
      assert.match(await page.locator('#calendar-scope').textContent(),/対応する候補データなし/);
      let calls=0;const listener=request=>{if(request.url().endsWith('/api/v1/recommendations'))calls++;};page.on('request',listener);
      await page.locator('[data-slot="2:2"]').click();assert.match(await page.locator('#slot-error').textContent(),/2027年度/);
      assert.equal(calls,0);page.off('request',listener);
    });
    await check('invalid timetable CSV stays unconfirmed and can be cleared',async()=>{
      await upload('#timetable-input',Buffer.from('fictional invalid timetable'),'fictional-invalid.csv');
      await page.waitForSelector('#timetable-error:not([hidden])');
      await page.waitForFunction(()=>document.querySelector('#timetable-drop').closest('.panel').getAttribute('aria-busy')==='false');
      assert.equal(await page.locator('.slot-button').count(),0);
      await page.locator('#clear-timetable').click();assert.equal(await page.locator('#timetable-error').isVisible(),false);
      assert.equal(await page.locator('.slot-button').count(),25);
    });
    await check('clearing data discards a delayed shortage-search response',async()=>{
      await grades();await times();
      let release;const held=new Promise(resolve=>{release=resolve;});
      await page.route('**/api/v1/recommendation-searches',async route=>{await held;await route.fulfill({json:recommendationResult});});
      await page.evaluate(()=>{window.originalPrototypeFetch=window.fetch;window.fetch=(url,options={})=>window.originalPrototypeFetch(url,{...options,signal:undefined});});
      const requested=page.waitForRequest('**/api/v1/recommendation-searches');await page.locator('#search-button').click();await requested;
      await page.locator('#clear-all').click();const responded=page.waitForResponse('**/api/v1/recommendation-searches');release();await responded;await frame();
      assert.equal(await page.locator('#search-results').isVisible(),false);assert.equal(await page.locator('#search-candidates .candidate-card').count(),0);
      await page.unroute('**/api/v1/recommendation-searches');await page.evaluate(()=>{window.fetch=window.originalPrototypeFetch;delete window.originalPrototypeFetch;});
    });
    await check('uncertain recommendations remain separate from confirmed candidates',async()=>{
      await grades();await times();
      const data=structuredClone(recommendationResult);
      data.status='unknown';data.review_candidates=data.candidates.map(course=>({...course,benefits:[],uncertain_benefits:course.benefits,review_reasons:['matching_earned_course_unconfirmed']}));data.candidates=[];
      await page.route('**/api/v1/recommendation-searches',route=>route.fulfill({json:data}));
      await find();assert.equal(await page.locator('#search-candidates .candidate-card').count(),0);
      assert.equal(await page.locator('#review-candidates .candidate-card').count(),data.review_candidates.length);
      await page.locator('#review-summary').click();
      assert.match(await page.locator('#review-candidates').textContent(),/必要性は未確定/);
      assert.match(await page.locator('#review-candidates').textContent(),/結果未確定/);
      await page.unroute('**/api/v1/recommendation-searches');
    });
    await check('the single report-side profile also controls recommendations and invalidates old data',async()=>{
      const metadata=await (await page.request.get(new URL('/api/v1/rule-profiles',base).href)).json();
      const original=metadata.profiles[0],alternative={...original,profile_id:'fictional-prototype-profile',program:'架空の対象'};
      await page.route('**/api/v1/rule-profiles',route=>route.fulfill({json:{...metadata,profiles:[original,alternative]}}));
      await page.reload({waitUntil:'networkidle'});await grades();await times();await view('overview');
      await page.locator('#profile-select').selectOption(alternative.profile_id);
      assert.equal(await page.locator('#overview-results').isVisible(),false);
      await view('timetable');assert.match(await page.locator('#recommend-profile').textContent(),/架空の対象/);
      let calls=0;const listener=request=>{if(/\/api\/v1\/recommendations$/.test(request.url()))calls++;};page.on('request',listener);
      await page.locator('[data-slot="2:2"]').click();assert.match(await page.locator('#slot-error').textContent(),/対応する教養候補データがありません/);
      assert.equal(calls,0);page.off('request',listener);
      assert.equal(await page.locator('#view-timetable select').count(),0);
      await page.unroute('**/api/v1/rule-profiles');
    });
    await check('reload clears memory while cookies and persistent stores stay empty',async()=>{
      await page.reload({waitUntil:'networkidle'});
      await grades();await times();
      assert.deepEqual(await page.evaluate(()=>[localStorage.length,sessionStorage.length]),[0,0]);
      assert.deepEqual(await context.cookies(),[]);
      if(await page.evaluate(()=>Boolean(indexedDB.databases)))assert.deepEqual(await page.evaluate(()=>indexedDB.databases()),[]);
      await page.reload({waitUntil:'networkidle'});
      assert.equal(await page.locator('#grades-input').inputValue(),'');assert.equal(await page.locator('#timetable-input').inputValue(),'');
      assert.equal(await page.locator('#overview-empty').isVisible(),true);
    });
    await check('metadata failures explain the problem and allow reconnection',async()=>{
      await page.route('**/api/v1/rule-profiles',route=>route.fulfill({status:503,json:{error:{code:'fictional_unavailable',message:'架空の対象情報を取得できません。'}}}));
      await page.reload({waitUntil:'networkidle'});
      assert.match(await page.locator('#initial-error').textContent(),/架空の対象情報/);
      assert.equal(await page.locator('#profile-select').isDisabled(),true);
      await page.unroute('**/api/v1/rule-profiles');await page.locator('#initial-error button').click();
      await page.waitForFunction(()=>!document.querySelector('#profile-select').disabled);
      assert.equal(await page.locator('#initial-error').isVisible(),false);
    });
    assert.deepEqual(exceptions,[],'JavaScript exceptions');assert.deepEqual(policyErrors,[],'CSP violations');assert.deepEqual(outside,[],'external requests');
    console.log(JSON.stringify({passed,javascript_errors:0,csp_violations:0,external_requests:0,screenshots:Boolean(screenshotDir)}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
