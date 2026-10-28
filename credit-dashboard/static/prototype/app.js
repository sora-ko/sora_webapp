import {createApi, ApiError} from './api.js';

const api = createApi();
const $ = id => document.getElementById(id);
const days = ['', '月', '火', '水', '木', '金', '土', '日'];
const paths = {
  dashboard:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  calendar:'M4 5h16v16H4z M8 2v6 M16 2v6 M4 10h16 M8 14h1 M13 14h3 M8 18h1 M13 18h3',
  list:'M8 6h13 M8 12h13 M8 18h13 M3 6h.1 M3 12h.1 M3 18h.1',
  upload:'M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6',
  plus:'M12 5v14 M5 12h14', arrow:'M4 12h16 M14 6l6 6-6 6',
  leaf:'M20 3C7 1 1 10 6 17s17-1 14-14z M5 21L16 9',
  shield:'M12 3l8 3v6c0 5-8 9-8 9S4 17 4 12V6z M8 12l3 3 5-6',
  help:'M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5 M12 17v.1 M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
  spark:'M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z',
  user:'M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M4 21v-3a8 6 0 0 1 16 0v3',
  filter:'M4 5h16 M7 12h10 M10 19h4', info:'M12 11v6 M12 7v.1 M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
  search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',
  trash:'M4 6h16 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7',
  check:'M5 12l4 4L19 6', clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2',
};
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({viewBox:'0 0 24 24', fill:'none', stroke:'currentColor', 'stroke-width':'1.7', 'stroke-linecap':'round', 'stroke-linejoin':'round', 'aria-hidden':'true'})) svg.setAttribute(key, value);
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', paths[name] || paths.info);
  svg.append(path);
  return svg;
}
document.querySelectorAll('[data-icon]').forEach(item => item.append(icon(item.dataset.icon)));
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined && text !== null) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}
const finite = value => typeof value === 'number' && Number.isFinite(value);
const number = value => finite(value) ? new Intl.NumberFormat('ja-JP', {maximumFractionDigits:2}).format(value) : '—';
const present = value => value === null || value === undefined || value === '' ? '—' : String(value);
const triLabel = status => ({satisfied:'条件を満たす', not_satisfied:'不足あり', unknown:'要確認'}[status] || '要確認');
const courseStatus = course => course.status ?? course.result;
const resultLabel = status => ({passed:'修得済み', failed:'未修得', unconfirmed:'要確認'}[status] || '要確認');
function badge(status, course = false) {
  const known = (course ? ['passed','failed','unconfirmed'] : ['satisfied','not_satisfied','unknown']).includes(status);
  const safe = known ? status : 'unknown';
  const item = node('span', undefined, `badge ${safe}`);
  item.append(icon(['satisfied','passed'].includes(safe) ? 'check' : 'clock'), document.createTextNode(course ? resultLabel(status) : triLabel(status)));
  return item;
}
// APIの注意事項は残し、開発段階を表す語だけを利用者向けの文に置き換える。
function displayMessage(value) {
  return String(value ?? '')
    .replaceAll('CSVの学年と在学年数が一致するMVP前提により、', 'CSVに記載された学年に基づき、')
    .replaceAll('MVP独自方針として、', 'この画面では、')
    .replaceAll('利用者指定のMVP方針で', '')
    .replace(/\bMVP\b/giu, '')
    .trim();
}
function error(id, message = '') { $(id).textContent = displayMessage(message); $(id).hidden = !message; }
const state = {
  profiles:[], catalogs:[], profileId:null, catalogError:'', view:'overview', gradesFile:null, timetableFile:null,
  report:null, timetable:null, context:null, slot:null, selectedSlot:null, search:null, onlyNeeds:false, coursePage:0, busy:{},
};
const jobs = new Map();
const epochs = {};
const profile = () => state.profiles.find(item => item.profile_id === state.profileId);
const contextKey = context => context ? `${context.academic_year}:${context.term}` : '';
function catalog() {
  const matches = state.catalogs.filter(item => item.profile_id === state.profileId);
  if (state.timetable) return matches.find(item => item.academic_year === state.context?.academic_year);
  return matches.sort((a,b) => b.academic_year - a.academic_year)[0];
}
function catalogMessage() {
  if (!profile()) return '単位の状況から、対象カリキュラムを選択してください。';
  if (state.catalogError) return state.catalogError;
  if (state.timetable && !state.context) return '履修表の開講年度・タームを確認できません。年度の情報を確認してください。';
  return `この対象${state.context ? `の${state.context.academic_year}年度` : ''}に対応する教養候補データがありません。`;
}
function busy(key, active) {
  state.busy[key] = active;
  const areas = {report:$('grades-drop').closest('.panel'), table:$('timetable-drop').closest('.panel'), slot:$('slot-candidates'), search:$('search-results')};
  areas[key]?.setAttribute('aria-busy', String(active));
  if (key === 'report') $('retry-grades').disabled = active;
  if (key === 'search') {
    $('search-button').disabled = active;
    $('search-button').replaceChildren(document.createTextNode(active ? '照合しています…' : '不足単位から探す'), icon('arrow'));
  }
}
function cancel(key) {
  epochs[key] = (epochs[key] || 0) + 1;
  jobs.get(key)?.abort();
  jobs.delete(key);
  busy(key, false);
}
async function run(key, action, success, failure) {
  cancel(key);
  const epoch = epochs[key];
  const controller = new AbortController();
  jobs.set(key, controller);
  busy(key, true);
  try {
    const data = await action(controller.signal);
    if (epochs[key] === epoch) success(data);
  } catch (exception) {
    if (epochs[key] === epoch && exception.name !== 'AbortError') failure(exception);
  } finally {
    if (epochs[key] === epoch) { jobs.delete(key); busy(key, false); if (key === 'table') renderCalendar(); }
  }
}
function activate(view, focus = false) {
  state.view = view;
  for (const name of ['overview','timetable','courses']) $('view-'+name).hidden = name !== view;
  document.querySelectorAll('[data-view]').forEach(button => {
    const active = button.dataset.view === view;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  $('page-label').textContent = {overview:'単位の状況', timetable:'時間割・教養', courses:'科目一覧'}[view];
  if (focus) { $('main-content').focus(); window.scrollTo({top:0, behavior:'instant'}); }
}
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => activate(button.dataset.view, true)));
$('go-upload').addEventListener('click', () => { activate('overview', true); $('choose-grades').focus(); });
$('go-recommend').addEventListener('click', () => activate('timetable', true));
$('help-button').addEventListener('click', () => $('help-dialog').showModal());
$('close-help').addEventListener('click', () => $('help-dialog').close());

function renderTarget() {
  const item = profile();
  $('profile-pill').textContent = item ? `${item.admission_year}年度入学 · ${item.program}` : '対象を未選択';
  $('recommend-profile').textContent = item ? `${item.admission_year}年度入学 · ${item.program}` : '対象カリキュラムを選択してください';
  $('policy-notes').replaceChildren(...(item?.policy_notes || []).map(note => node('p', displayMessage(note))));
}
function renderFiles() {
  $('grades-file-name').textContent = state.gradesFile?.name || 'ファイルをここにドロップ';
  $('timetable-file-name').textContent = state.timetableFile?.name || '登録済み授業との重複を確認できます。';
  $('grades-actions').hidden = !state.gradesFile;
  $('timetable-actions').hidden = !state.timetableFile;
  $('matching-files').textContent = `成績CSV：${state.gradesFile ? '選択済み' : '未選択'}　／　履修表CSV：${state.timetableFile ? '選択済み' : '未選択'}`;
}
function renderOverview() {
  const data = state.report;
  $('overview-empty').hidden = Boolean(data);
  $('overview-results').hidden = !data;
  $('courses-empty').hidden = Boolean(data);
  $('course-panel').hidden = !data;
  $('course-count').textContent = data ? `${number(data.summary.course_count)} 科目` : 'CSV未読み込み';
  if (!data) {
    for (const id of ['student-name','student-meta','stats','evaluations','report-warnings','course-rows','course-filter-count']) $(id).replaceChildren();
    $('report-warnings').hidden = true;
    return;
  }
  $('student-name').textContent = data.student.name || '氏名未記載';
  const grade = present(data.student.grade);
  $('student-meta').textContent = [data.student.student_number, grade === '—' ? '学年未確認' : /^\d+$/.test(grade) ? `${grade}年` : grade].filter(Boolean).join(' · ');
  const major = name => data.summary.majors?.find(item => item.major === name)?.earned_credits;
  const stats = [
    ['修得済み単位',data.summary.earned_credits,'合格・単位数確認済み','check'],
    ['教養科目',major('教養'),'修得済みの教養単位','leaf'],
    ['専門科目',major('専門'),'修得済みの専門単位','list'],
    ['結果確認待ち',data.summary.unconfirmed_credits,'取得済みには含めません','clock'],
  ];
  $('stats').replaceChildren(...stats.map(([label,value,note,image]) => {
    const card = node('div', undefined, 'stat-card');
    const title = node('p',label,'stat-label'); title.append(icon(image));
    const amount = node('p',number(value),'stat-number'); amount.append(node('small','単位'));
    card.append(title,amount,node('p',note,'stat-footnote')); return card;
  }));
  $('evaluations').replaceChildren(...data.evaluations.map(renderEvaluation));
  $('report-warnings').replaceChildren(...data.warnings.map(warning => node('p', displayMessage(typeof warning === 'string' ? warning : warning.message))));
  $('report-warnings').hidden = !data.warnings.length;
  renderCourses();
}
function progress(value, maximum) {
  const meter = node('progress');
  meter.max = maximum;
  meter.value = Math.min(value,maximum);
  meter.setAttribute('aria-label', `確認済み ${number(value)} / ${number(maximum)}`);
  return meter;
}
function renderCondition(condition) {
  const row = node('div',undefined,'condition-row');
  const top = node('div',undefined,'condition-top');
  top.append(node('span',condition.label,'condition-label'));
  let confirmed, minimum, unit;
  if (finite(condition.minimum_credits)) { confirmed=condition.confirmed_credits; minimum=condition.minimum_credits; unit='単位'; }
  else if (finite(condition.minimum_years)) { confirmed=condition.confirmed_years; minimum=condition.minimum_years; unit='年'; }
  else if (finite(condition.required_course_count)) { confirmed=condition.satisfied_course_count; minimum=condition.required_course_count; unit='科目'; }
  if (unit) top.append(node('span',`${number(confirmed)} / ${number(minimum)} ${unit}`,'condition-value'));
  else top.append(badge(condition.status));
  row.append(top);
  if (minimum > 0 && finite(confirmed)) row.append(progress(confirmed,minimum));
  if (condition.status === 'unknown') row.append(node('p', finite(condition.confirmed_credit_shortfall)
    ? `要確認 · 確認済み単位との差 ${number(condition.confirmed_credit_shortfall)} 単位` : '要確認 · 情報が不足しています','condition-note'));
  else if (condition.status === 'not_satisfied') row.append(node('p', finite(condition.confirmed_credit_shortfall)
    ? `あと ${number(condition.confirmed_credit_shortfall)} 単位` : '不足している条件があります','condition-note'));
  if (condition.description) row.append(node('p',displayMessage(condition.description),'condition-description'));
  if (Array.isArray(condition.course_results)) {
    const detail = node('details',undefined,'condition-details');
    detail.append(node('summary','必修科目ごとの確認結果'));
    const list = node('ul',undefined,'required-courses');
    for (const course of condition.course_results) {
      const item = node('li'); item.append(node('span',course.name),badge(course.status)); list.append(item);
    }
    detail.append(list); row.append(detail);
  }
  return row;
}
function renderEvaluation(evaluation) {
  const card = node('article',undefined,'panel evaluation');
  card.dataset.status = evaluation.status;
  const header = node('div',undefined,'evaluation-header');
  header.append(node('h3',evaluation.title),badge(evaluation.status));
  card.append(header,node('p',displayMessage(evaluation.description),'evaluation-description'));
  const conditions = evaluation.conditions || [];
  const satisfied = conditions.filter(item => item.status === 'satisfied').length;
  card.append(node('p',`個別条件 ${satisfied} / ${conditions.length} 項目で充足を確認`,'evaluation-count'));
  if (conditions.length) card.append(progress(satisfied,conditions.length));
  const needs = conditions.filter(item => item.status !== 'satisfied');
  if (conditions.length) {
    const details = node('details',undefined,'condition-details');
    const visibleConditions = state.onlyNeeds ? needs : conditions;
    details.append(node('summary',`${state.onlyNeeds ? '不足・要確認の内訳を見る' : '条件の内訳をすべて見る'}（${visibleConditions.length}項目）`));
    const list = node('div',undefined,'condition-list'); list.append(...visibleConditions.map(renderCondition));
    if (!visibleConditions.length) list.append(node('p','不足・要確認の条件はありません。','all-checked'));
    details.append(list); card.append(details);
  }
  if (evaluation.sources?.length || evaluation.caveats?.length) {
    const details = node('details',undefined,'evidence-details'); details.append(node('summary','根拠・注意事項'));
    for (const source of evaluation.sources || []) {
      try {
        const url = new URL(source.url);
        if (!['https:','http:'].includes(url.protocol)) continue;
        const link = node('a',`${source.title}${source.printed_pages?.length ? ` · 冊子${source.printed_pages.join('・')}頁` : ''}`);
        link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer';
        const p=node('p'); p.append(link); details.append(p);
      } catch { /* 未知の出典URLはリンクにしない。 */ }
    }
    for (const caveat of evaluation.caveats || []) details.append(node('p',displayMessage(caveat.message)));
    card.append(details);
  }
  return card;
}
$('filter-conditions').addEventListener('click', () => {
  state.onlyNeeds=!state.onlyNeeds;
  $('filter-conditions').setAttribute('aria-pressed', String(state.onlyNeeds));
  renderOverview();
});

function renderCourses() {
  if (!state.report) return;
  const query=$('course-search').value.trim().normalize('NFKC').toLowerCase();
  const area=$('course-area').value, result=$('course-result').value;
  const matches=state.report.courses.filter(course => (area==='all' || course.curriculum_area===area)
    && (result==='all' || courseStatus(course)===result)
    && `${course.name} ${course.course_code || ''}`.normalize('NFKC').toLowerCase().includes(query));
  const size=25;
  state.coursePage=Math.max(0,Math.min(state.coursePage,Math.ceil(matches.length/size)-1));
  const rows=matches.slice(state.coursePage*size,(state.coursePage+1)*size).map(course => {
    const row=node('tr'); const name=node('td',course.name);
    if (course.course_code) name.append(node('code',course.course_code));
    const status=node('td'); status.append(badge(courseStatus(course),true));
    row.append(name,node('td',course.source_category),node('td',number(course.credits)),status,node('td',present(course.earned_year)));
    return row;
  });
  if (!rows.length) { const row=node('tr'),cell=node('td','該当する科目がありません。検索条件を変更してください。'); cell.colSpan=5; row.append(cell); rows.push(row); }
  $('course-rows').replaceChildren(...rows);
  const first=matches.length ? state.coursePage*size+1 : 0;
  $('course-filter-count').replaceChildren(document.createTextNode(`${matches.length} 科目中 ${first}–${Math.min((state.coursePage+1)*size,matches.length)} 件を表示　`));
  if (matches.length>size) {
    for (const [label,offset,disabled] of [['前へ',-1,state.coursePage===0],['次へ',1,(state.coursePage+1)*size>=matches.length]]) {
      const button=node('button',label,'text-button'); button.type='button'; button.disabled=disabled;
      button.addEventListener('click',()=>{state.coursePage+=offset;renderCourses();});
      $('course-filter-count').append(button,document.createTextNode('　'));
    }
  }
}
for (const id of ['course-search','course-area','course-result']) $(id).addEventListener(id==='course-search'?'input':'change',()=>{state.coursePage=0;renderCourses();});

function contexts() {
  if (state.timetable) return state.timetable.display_contexts;
  const item=catalog();
  return item ? item.terms.map(term=>({academic_year:item.academic_year,term})) : [];
}
function syncContext() {
  const items=contexts();
  state.context=items.find(item=>contextKey(item)===contextKey(state.context)) || items[0] || null;
}
function markSlot() {
  document.querySelectorAll('.slot-button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.slot===state.selectedSlot)));
}
function renderCalendar() {
  syncContext();
  const item=catalog();
  const current=state.context;
  $('calendar-scope').textContent=current ? `${current.academic_year}年度${item ? ' · 教養科目' : ' · 対応する候補データなし'}` : catalogMessage();
  $('term-tabs').replaceChildren(...contexts().map(context=>{
    const button=node('button',`第${context.term}ターム`,'term-tab'); button.type='button';
    button.setAttribute('aria-label',`${context.academic_year}年度 第${context.term}ターム`);
    button.setAttribute('aria-pressed',String(contextKey(current)===contextKey(context)));
    button.addEventListener('click',()=>{state.context=context;invalidateRecommendations();renderCalendar();});
    return button;
  }));
  $('calendar-note').textContent=state.timetable ? '空き時間の表示は、読み取れた年度・曜日・時限の範囲です。履修許可は未確認です。'
    : '履修表未読み込み：登録済み授業との重複は確認していません。';
  $('timetable-notes').replaceChildren(...[...(state.timetable?.policy_notes || []),...(state.timetable?.warnings || []).map(note=>note.message)].map(note=>node('p',displayMessage(note))));
  if (!current || (state.timetableFile && !state.timetable)) {
    $('calendar-grid').replaceChildren(node('p',state.busy.table && !state.timetable ? '時間割を読み込んでいます…' : state.timetableFile && !state.timetable ? '履修表CSVを確認できませんでした。上のメッセージを確認し、読み直すか解除してください。' : catalogMessage(),'notice'));
    return;
  }
  const weekdays=state.timetable?.represented_weekdays || item?.weekdays || [];
  const periods=state.timetable?.represented_periods || item?.periods || [];
  const table=node('table',undefined,'timetable-table'); const head=node('thead'),titles=node('tr');
  const corner=node('th','時限'); corner.scope='col'; titles.append(corner);
  weekdays.forEach(day=>{const th=node('th',`${days[day]}曜日`);th.scope='col';titles.append(th);});
  head.append(titles); const body=node('tbody');
  for (const period of periods) {
    const row=node('tr'),heading=node('th',`${period}限`); heading.scope='row';row.append(heading);
    for (const weekday of weekdays) {
      const cell=node('td');
      const occupied=state.timetable?.busy_slots.some(slot=>slot.academic_year===current.academic_year && slot.term===current.term && slot.weekday===weekday && slot.period===period);
      const unknown=state.timetable && !state.timetable.ready_for_recommendation;
      const button=node('button',undefined,`slot-button ${occupied?'occupied':unknown?'unknown':'available'}`);
      button.type='button';button.dataset.slot=`${weekday}:${period}`;
      button.setAttribute('aria-label',`第${current.term}ターム ${days[weekday]}曜${period}限の教養候補`);
      button.setAttribute('aria-pressed',String(state.selectedSlot===button.dataset.slot));
      button.append(icon(occupied?'calendar':unknown?'help':'plus'),node('span',occupied?'通常授業あり':unknown?'未確認':'候補を探す'));
      if (occupied) {
        const courses=state.timetable.courses.filter(course=>course.academic_year===current.academic_year && course.term===current.term
          && course.slots.some(slot=>slot.weekday===weekday && slot.period===period));
        for (const course of courses) button.append(node('span',course.course_code,'slot-code'));
      }
      if (weekday>5 || period>5) { button.disabled=true;button.title='教養候補の探索範囲は月〜金・1〜5限です。'; }
      else button.addEventListener('click',()=>findSlot(weekday,period));
      cell.append(button); row.append(cell);
    }
    body.append(row);
  }
  table.append(head,body);$('calendar-grid').replaceChildren(table);
}
function invalidateRecommendations() {
  cancel('slot');cancel('search');state.slot=null;state.search=null;state.selectedSlot=null;
  error('slot-error');error('search-error');renderSlot();renderSearch();markSlot();
}
function renderSlot() {
  $('slot-heading').textContent=state.selectedSlot && state.context
    ? `第${state.context.term}ターム · ${days[Number(state.selectedSlot.split(':')[0])]}曜${state.selectedSlot.split(':')[1]}限` : '気になる時間を選択';
  $('slot-candidates').replaceChildren();$('slot-notes').replaceChildren();
  if (!state.slot) { $('slot-status').textContent='時間割のマスを押すと、その時間に開講する教養科目が表示されます。'; return; }
  const data=state.slot;
  $('slot-status').textContent={ok:`${data.candidates.length}件の候補が見つかりました。${data.basis==='timetable'?'全曜限の重複を確認済みです。':'登録授業との重複は未確認です。'}`,
    empty:'この時間の教養候補は見つかりませんでした。別のマスもお試しください。',occupied:'この時間には通常授業があります。別の時間を選んでください。',unknown:'未確認の情報があるため、候補の判定を保留しています。'}[data.status] || '候補の判定状態を確認できません。';
  $('slot-candidates').append(...data.candidates.map(course=>candidateCard(course)));
  $('slot-notes').append(...data.messages.map(message=>node('p',displayMessage(message.message))));
}
function candidateCard(course, review=false) {
  const card=node('article',undefined,'candidate-card');const top=node('div',undefined,'candidate-top');
  top.append(node('h4',course.name),node('span',`${number(course.credits)} 単位`,'credit-pill'));
  card.append(top,node('span',course.category,'category-label'));
  const meta=node('p',undefined,'course-meta');
  meta.append(document.createTextNode(course.schedule.map(slot=>`${days[slot.weekday]}曜${slot.period}限`).join(' / ')),node('code',course.course_code));card.append(meta);
  if (course.benefits?.length || course.uncertain_benefits?.length) {
    const list=node('ul',undefined,'candidate-benefits');
    for (const effect of course.benefits || []) list.append(node('li',`${effect.label}：不足 ${number(effect.before_shortfall)} → ${number(effect.after_shortfall)} 単位`));
    for (const effect of course.uncertain_benefits || []) list.append(node('li',`${effect.label}：確認済み単位との差 ${number(effect.before_shortfall)} → ${number(effect.after_shortfall)} 単位（必要性は未確定）`,'uncertain'));
    card.append(list);
  }
  if (review && course.review_reasons?.includes('matching_earned_course_unconfirmed')) card.append(node('p','同名または同じ開講番号の成績に、結果未確定の行があります。','small-notes'));
  return card;
}
function validateCandidates(data, search=false) {
  if (!Array.isArray(data.candidates) || !Array.isArray(data.messages) || (search && (!Array.isArray(data.baseline) || !Array.isArray(data.review_candidates)))) throw new ApiError('候補情報の形式を確認できませんでした。','invalid_response');
  for (const course of [...data.candidates,...(search?data.review_candidates:[])]) {
    if (!course || typeof course.name!=='string' || !Array.isArray(course.schedule)) throw new ApiError('候補の時間割情報を確認できませんでした。','invalid_response');
  }
}
function findSlot(weekday,period) {
  cancel('slot');state.slot=null;error('slot-error');state.selectedSlot=`${weekday}:${period}`;renderSlot();markSlot();
  const item=catalog();
  if (!item || !state.context) { error('slot-error',catalogMessage());return; }
  $('slot-status').textContent='この時間の教養候補を確認しています…';
  run('slot',signal=>api.slot({profile_id:state.profileId,...state.context,weekday,period},state.timetableFile,signal),data=>{
    validateCandidates(data);state.slot=data;renderSlot();
  },exception=>{$('slot-status').textContent='候補を取得できませんでした。';error('slot-error',exception.message);});
}
function renderSearch() {
  const data=state.search;
  $('search-results').hidden=!data;
  for (const id of ['search-status','search-candidates','review-summary','review-candidates','search-baseline','search-notes']) $(id).replaceChildren();
  $('review-details').hidden=true;
  if (!data) return;
  const fulfilled=data.messages.some(message=>message.code==='liberal_requirements_satisfied');
  $('search-status').textContent=fulfilled ? '教養の必修・選択必修・選択・合計は、すべて充足しています。'
    : {ok:`不足を補う候補が ${data.candidates.length} 件見つかりました`, empty:'この条件で、不足を減らせる候補は見つかりませんでした',unknown:'必要性や時間情報を確認できないため、探索結果は要確認です'}[data.status] || '探索結果を確認してください';
  $('search-candidates').append(...data.candidates.map(course=>candidateCard(course)));
  $('review-details').hidden=!data.review_candidates.length;
  $('review-summary').textContent=`要確認の候補 ${data.review_candidates.length}件`;
  $('review-candidates').append(...data.review_candidates.map(course=>candidateCard(course,true)));
  $('search-baseline').append(...data.baseline.map(condition=>node('p',`${condition.label}：${condition.status==='satisfied'?'充足':condition.status==='unknown'
    ?`確認済み単位との差 ${number(condition.confirmed_credit_shortfall)} 単位（要確認）`:`不足 ${number(condition.confirmed_credit_shortfall)} 単位`}`,'baseline-item')));
  $('search-notes').append(...data.messages.map(message=>node('p',displayMessage(message.message))));
}
$('search-button').addEventListener('click',()=>{
  cancel('search');state.search=null;renderSearch();error('search-error');
  const missing=[];
  if (!state.gradesFile) missing.push('成績CSVを「単位の状況」から追加してください。');
  if (!state.timetableFile) missing.push('履修表CSVをこの画面の上部から追加してください。');
  if (missing.length) { error('search-error',missing.join(' ')); return; }
  if (state.busy.table || !state.timetable) { error('search-error','履修表CSVの読み込みを完了してください。上部のエラーがあれば、CSVを読み直してください。');return; }
  if (!catalog() || !state.context) { error('search-error',catalogMessage());return; }
  $('search-results').hidden=false;$('search-status').textContent='取得単位と空き時間を照合しています…';
  run('search',signal=>api.search({profile_id:state.profileId,...state.context},state.gradesFile,state.timetableFile,signal),data=>{
    validateCandidates(data,true);state.search=data;renderSearch();
  },exception=>{renderSearch();error('search-error',exception.message);});
});
$('clear-search').addEventListener('click',()=>{cancel('search');state.search=null;error('search-error');renderSearch();});

function clearReport() {cancel('report');state.report=null;state.coursePage=0;renderOverview();error('grades-error');$('grades-status').textContent='';}
function checkFile(file) {
  if (!file) return;
  if (file.size>5*1024*1024) throw new ApiError('ファイルが5 MBを超えています。大学から取得したCSVを確認してください。','file_too_large');
  if (!file.size) throw new ApiError('空のファイルです。内容のあるCSVを選択してください。','empty_file');
}
function readGrades(file) {
  clearReport();invalidateRecommendations();state.gradesFile=file || null;renderFiles();
  if (!file) return;
  try {checkFile(file);} catch (exception) {error('grades-error',exception.message);return;}
  if (!profile()) {error('grades-error','対象カリキュラムの読み込みを完了してください。');return;}
  $('grades-status').textContent='成績CSVを読み込んでいます…';
  run('report',signal=>api.report({profile_id:state.profileId,residence_years:$('residence-years').value},file,signal),data=>{
    if (!data.student || !data.summary || !Array.isArray(data.courses) || !Array.isArray(data.evaluations) || !Array.isArray(data.warnings)) throw new ApiError('成績情報の形式を確認できませんでした。','invalid_response');
    state.report=data;renderOverview();$('grades-status').textContent=`${number(data.summary.course_count)}科目を読み込みました。修得済みは ${number(data.summary.earned_credits)} 単位です。`;
  },exception=>{state.report=null;renderOverview();$('grades-status').textContent='';error('grades-error',exception.message);});
}
function readTimetable(file) {
  cancel('table');state.timetable=null;state.timetableFile=file || null;state.context=null;invalidateRecommendations();
  renderFiles();error('timetable-error');$('timetable-status').textContent='';
  if (!file) {renderCalendar();return;}
  try {checkFile(file);} catch(exception) {error('timetable-error',exception.message);renderCalendar();return;}
  $('timetable-status').textContent='履修表CSVを読み込んでいます…';
  run('table',signal=>api.timetable(file,signal),data=>{
    if (!Array.isArray(data.display_contexts) || !Array.isArray(data.busy_slots) || !Array.isArray(data.courses)
      || !Array.isArray(data.represented_weekdays) || !Array.isArray(data.represented_periods)
      || typeof data.ready_for_recommendation!=='boolean') throw new ApiError('履修表の形式を確認できませんでした。','invalid_response');
    state.timetable=data;syncContext();renderCalendar();
    $('timetable-status').textContent=data.ready_for_recommendation ? '時間割を読み込みました。気になるマスを選択してください。' : '時間割に未確認の情報があります。注意事項を確認してください。';
  },exception=>{state.timetable=null;$('timetable-status').textContent='';error('timetable-error',exception.message);renderCalendar();});
  renderCalendar();
}
for (const [kind,reader] of [['grades',readGrades],['timetable',readTimetable]]) {
  $('choose-'+kind).addEventListener('click',() => $(kind+'-input').click());
  $(kind+'-input').addEventListener('change',event=>reader(event.target.files[0]));
  const zone=$(kind+'-drop');
  for (const event of ['dragenter','dragover']) zone.addEventListener(event,action=>{action.preventDefault();zone.classList.add('dragging');});
  for (const event of ['dragleave','drop']) zone.addEventListener(event,action=>{action.preventDefault();zone.classList.remove('dragging');});
  zone.addEventListener('drop',event=>{const file=event.dataTransfer.files[0];if(file){$(kind+'-input').value='';reader(file);}});
}
$('retry-grades').addEventListener('click',()=>readGrades(state.gradesFile));
$('clear-grades').addEventListener('click',()=>{$('grades-input').value='';readGrades(null);});
$('clear-timetable').addEventListener('click',()=>{$('timetable-input').value='';readTimetable(null);});
$('profile-select').addEventListener('change',()=>{
  state.profileId=$('profile-select').value;clearReport();invalidateRecommendations();state.context=null;renderTarget();renderCalendar();
  if(state.gradesFile) $('grades-status').textContent='対象を変更しました。「このCSVで再解析」を押すと、新しい対象で確認できます。';
});
$('residence-years').addEventListener('input',()=>{clearReport();if(state.gradesFile)$('grades-status').textContent='判定条件を変更しました。「このCSVで再解析」を押してください。';});
$('clear-all').addEventListener('click',()=>{
  $('grades-input').value='';$('timetable-input').value='';$('residence-years').value='';
  readGrades(null);readTimetable(null);$('course-search').value='';$('course-area').value='all';$('course-result').value='all';
});
async function load() {
  error('initial-error');
  await Promise.allSettled([
    run('profiles',signal=>api.profiles(signal),data=>{
      if(!Array.isArray(data.profiles) || !data.profiles.length) throw new ApiError('利用できる対象カリキュラムがありません。');
      state.profiles=data.profiles;
      state.profileId=data.profiles.some(item=>item.profile_id===state.profileId) ? state.profileId
        : data.profiles.find(item=>item.profile_id===data.default_profile_id)?.profile_id || data.profiles[0].profile_id;
      $('profile-select').replaceChildren(...data.profiles.map(item=>{
        const option=node('option',`${item.institution} ${item.faculty} ${item.program}（${item.admission_year}年度入学）`);
        option.value=item.profile_id;return option;
      }));
      $('profile-select').value=state.profileId;$('profile-select').disabled=false;renderTarget();renderCalendar();
    },exception=>{
      state.profileId=null;$('profile-select').disabled=true;renderTarget();renderCalendar();
      error('initial-error',exception.message+' ');
      const retry=node('button','再接続する','text-button');retry.type='button';retry.addEventListener('click',load);$('initial-error').append(retry);
    }),
    run('catalogs',signal=>api.catalogs(signal),data=>{
      if(!Array.isArray(data.catalogs))throw new ApiError('教養候補の対象情報を確認できませんでした。');
      state.catalogs=data.catalogs;state.catalogError='';renderCalendar();
    },exception=>{state.catalogs=[];state.catalogError=exception.message;renderCalendar();}),
  ]);
}
renderFiles();renderOverview();renderSlot();renderSearch();
load();
