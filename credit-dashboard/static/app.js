const $ = (id) => document.getElementById(id);
let report = null;
let selectedFile = null;
let profiles = [];
let reportRequestVersion = 0;
let reportController = null;

function node(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value == null || value === '' ? '—' : String(value);
  if (className) element.className = className;
  return element;
}

function renderCards(summary) {
  $('cards').replaceChildren();
  const byMajor = Object.fromEntries(summary.majors.map((item) => [item.major, item]));
  const cards = [
    ['取得済み', `${summary.earned_credits} 単位`, `${summary.passed_count} 科目`],
    ['教養', `${byMajor['教養']?.earned_credits ?? 0} 単位`, `${byMajor['教養']?.course_count ?? 0} 科目`],
    ['専門', `${byMajor['専門']?.earned_credits ?? 0} 単位`, `${byMajor['専門']?.course_count ?? 0} 科目`],
    ['未確定', `${summary.unconfirmed_credits} 単位`, `${summary.unconfirmed_count} 科目`],
  ];
  cards.forEach(([title, amount, caption]) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.append(node('span', title, 'card-title'), node('strong', amount), node('span', caption, 'muted'));
    $('cards').append(card);
  });
}

function renderCategories(summary) {
  $('categories').replaceChildren();
  for (const major of ['教養', '専門', '不明', '対象外']) {
    const majorSummary = summary.majors.find((item) => item.major === major);
    if (!majorSummary) continue;
    const block = document.createElement('details');
    block.className = 'category-block';
    const title = node('summary', major);
    block.append(title);
    block.append(node('p', `取得済み ${majorSummary.earned_credits} 単位`, 'muted'));
    const grid = document.createElement('div');
    grid.className = 'category-grid';
    for (const category of summary.categories.filter((c) => c.major === major)) {
      const item = document.createElement('div');
      item.className = 'category-item';
      item.append(node('span', category.source_category), node('strong', `${category.earned_credits} 単位`));
      if (category.unconfirmed_count) item.append(node('small', `未確定 ${category.unconfirmed_credits} 単位`));
      grid.append(item);
    }
    block.append(grid);
    $('categories').append(block);
  }
}

function renderCourses() {
  $('courses').replaceChildren();
  if (!report) return;
  const filter = $('course-filter').value;
  for (const course of report.courses.filter((course) => (
    filter === 'all'
    || filter === `major:${course.major}`
    || filter === `category:${course.source_category}`
  ))) {
    const tr = document.createElement('tr');
    const status = {passed: '取得済み', failed: '不合格', unconfirmed: '未確定'}[course.status] || '不明';
    for (const [value, className] of [
      [course.name], [course.major], [course.source_category],
      [course.requirement_type], [course.credits, 'numeric'], [status, course.status]
    ]) tr.append(node('td', value, className));
    $('courses').append(tr);
  }
}

function renderCourseFilter(data) {
  const select = $('course-filter');
  select.replaceChildren(node('option', 'すべて'));
  select.firstElementChild.value = 'all';

  const majorGroup = document.createElement('optgroup');
  majorGroup.label = '大分類';
  for (const major of data.summary.majors) {
    const option = node('option', major.major);
    option.value = `major:${major.major}`;
    majorGroup.append(option);
  }

  const categoryGroup = document.createElement('optgroup');
  categoryGroup.label = '科目区分';
  for (const category of data.summary.categories) {
    const option = node('option', category.source_category);
    option.value = `category:${category.source_category}`;
    categoryGroup.append(option);
  }
  select.append(majorGroup, categoryGroup);
}

const statusLabels = {
  satisfied: '条件を満たす',
  not_satisfied: '条件を満たさない',
  unknown: '判定不能',
};

const requiredCourseStatusLabels = {
  satisfied: '修得済み',
  not_satisfied: '未修得・必要単位未達',
  unknown: '判定不能',
};

function renderEvaluations(evaluations) {
  const section = $('evaluation-section');
  const container = $('evaluations');
  container.replaceChildren();
  section.hidden = !evaluations.length;
  for (const evaluation of evaluations) {
    const card = document.createElement('details');
    card.className = `evaluation evaluation-${evaluation.status}`;
    const title = document.createElement('summary');
    title.append(node('h3', evaluation.title));
    const heading = document.createElement('div');
    heading.className = 'evaluation-heading';
    heading.append(
      node('span', statusLabels[evaluation.status] || evaluation.status, `status-badge ${evaluation.status}`),
    );
    card.append(title, heading, node('p', evaluation.description, 'evaluation-description'));

    const conditions = document.createElement('div');
    conditions.className = 'condition-list';
    for (const condition of evaluation.conditions) {
      const item = document.createElement('div');
      item.className = 'condition';
      item.append(
        node('strong', condition.label),
        node('span', statusLabels[condition.status] || condition.status, `status-badge ${condition.status}`),
        node('p', condition.description, 'muted'),
      );
      if (Array.isArray(condition.course_results)) {
        const details = document.createElement('details');
        details.className = 'required-course-details';
        const summary = node('summary', '必修科目ごとの修得状況');
        const list = document.createElement('ul');
        for (const course of condition.course_results) {
          const row = document.createElement('li');
          row.append(
            node('strong', course.name),
            document.createTextNode(' '),
            node('span', requiredCourseStatusLabels[course.status] || course.status, `status-badge ${course.status}`),
            node('p', course.description, 'muted'),
          );
          list.append(row);
        }
        details.append(summary, list);
        item.append(details);
      }
      conditions.append(item);
    }
    card.append(conditions);

    for (const source of evaluation.sources || []) {
      const sourceLine = document.createElement('p');
      sourceLine.className = 'source-link';
      sourceLine.append('根拠: ');
      const link = document.createElement('a');
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.textContent = `${source.title}（冊子 ${source.printed_pages.join(', ')}ページ）`;
      sourceLine.append(link);
      card.append(sourceLine);
    }
    if (evaluation.caveats?.length) {
      const details = document.createElement('details');
      const summary = node('summary', '判定上の要確認事項');
      const list = document.createElement('ul');
      for (const caveat of evaluation.caveats) list.append(node('li', caveat.message));
      details.append(summary, list);
      card.append(details);
    }
    container.append(card);
  }
}

function renderReport(data) {
  report = data;
  const student = data.student;
  const grade = student.grade && (student.grade.endsWith('年') ? student.grade : `${student.grade}年`);
  $('student').textContent = [
    ['氏名', student.name],
    ['学籍番号', student.student_number],
    ['所属', student.affiliation],
    ['学年', grade],
  ].filter(([, value]) => value).map(([label, value]) => `${label}: ${value}`).join(' · ')
    || '学生情報はCSVに未記入です';
  renderCards(data.summary);
  renderCategories(data.summary);
  renderCourseFilter(data);
  renderEvaluations(data.evaluations || []);
  $('course-count').textContent = `${data.summary.course_count} 科目`;
  renderCourses();
  $('warnings').hidden = data.warnings.length === 0;
  $('warnings').replaceChildren(...data.warnings.map((warning) => node('div', warning)));
  $('json').textContent = JSON.stringify(data, null, 2);
  $('dashboard').hidden = false;
}

function clearReport() {
  report = null;
  $('dashboard').hidden = true;
  for (const id of ['student', 'cards', 'categories', 'courses', 'warnings', 'evaluations']) {
    $(id).replaceChildren();
  }
  $('evaluation-section').hidden = true;
  $('course-count').textContent = '';
  $('json').textContent = '';
  $('course-filter').replaceChildren(node('option', 'すべて'));
  $('course-filter').firstElementChild.value = 'all';
}

function setSelectedFile(file) {
  invalidateReport();
  selectedFile = file || null;
  window.creditWorkspace.setFile('grades', selectedFile);
  $('selected-file').textContent = selectedFile ? selectedFile.name : 'ファイルが選択されていません';
}

function invalidateReport() {
  reportRequestVersion += 1;
  reportController?.abort();
  reportController = null;
  clearReport();
  $('submit').disabled = false;
  $('upload-form').setAttribute('aria-busy', 'false');
  $('error').hidden = true;
  $('error').textContent = '';
  $('status').textContent = '';
}

async function upload(event) {
  event.preventDefault();
  $('error').hidden = true;
  if (!selectedFile) {
    $('error').textContent = 'CSVファイルを選択してください。';
    $('error').hidden = false;
    return;
  }
  const button = $('submit');
  const version = ++reportRequestVersion;
  reportController?.abort();
  reportController = new AbortController();
  button.disabled = true;
  $('upload-form').setAttribute('aria-busy', 'true');
  clearReport();
  $('status').textContent = 'CSVを解析しています…';
  try {
    const body = new FormData();
    body.append('file', selectedFile, selectedFile.name);
    body.append('profile_id', $('profile-select').value);
    if ($('residence-years').value) body.append('residence_years', $('residence-years').value);
    const response = await fetch('/api/v1/reports', {method: 'POST', body, signal: reportController.signal, cache: 'no-store'});
    const data = await response.json();
    if (version !== reportRequestVersion) return;
    if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
    renderReport(data);
    $('status').textContent = '解析が完了しました。';
  } catch (error) {
    if (version !== reportRequestVersion || error.name === 'AbortError') return;
    clearReport();
    $('status').textContent = '';
    $('error').textContent = `解析に失敗しました: ${error.message}`;
    $('error').hidden = false;
  } finally {
    if (version === reportRequestVersion) {
      reportController = null;
      $('upload-form').setAttribute('aria-busy', 'false');
      button.disabled = false;
    }
  }
}

function profileLabel(profile) {
  return `${profile.institution} ${profile.faculty} ${profile.program}（${profile.admission_year}年度入学）`;
}

function updateTargetSummary() {
  const profile = profiles.find((item) => item.profile_id === $('profile-select').value);
  window.creditWorkspace.setProfile(profile);
  if (!profile) {
    $('target-summary').textContent = '対象プログラムを選択してください。';
    $('policy-notes').replaceChildren();
    $('policy-notes').hidden = true;
    return;
  }
  const implemented = new Set(profile.implemented_requirement_ids || []);
  const titles = (profile.requirements || [])
    .filter((requirement) => implemented.has(requirement.requirement_id))
    .map((requirement) => requirement.title);
  const evaluationText = titles.length ? ` · 対応要件: ${titles.join('、')}` : '';
  $('target-summary').textContent = `${profileLabel(profile)}${evaluationText}`;
  const notes = profile.policy_notes || [];
  $('policy-notes').replaceChildren(...notes.map((note) => node('p', note)));
  $('policy-notes').hidden = notes.length === 0;
}

async function loadProfiles() {
  try {
    const response = await fetch('/api/v1/rule-profiles', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok || !Array.isArray(data.profiles) || !data.profiles.length) {
      throw new Error('対象プロファイルを取得できません。');
    }
    profiles = data.profiles;
    const select = $('profile-select');
    select.replaceChildren();
    for (const profile of profiles) {
      const option = node('option', profileLabel(profile));
      option.value = profile.profile_id;
      option.selected = profile.profile_id === data.default_profile_id;
      select.append(option);
    }
    updateTargetSummary();
  } catch (error) {
    window.creditWorkspace.setProfile(null);
    $('error').textContent = `対象情報の取得に失敗しました: ${error.message}`;
    $('error').hidden = false;
  }
}

$('upload-form').addEventListener('submit', upload);
$('csv-file').addEventListener('change', (event) => setSelectedFile(event.target.files[0]));
$('course-filter').addEventListener('change', renderCourses);
$('profile-select').addEventListener('change', () => {
  invalidateReport();
  updateTargetSummary();
});
$('residence-years').addEventListener('input', invalidateReport);
$('clear-report').addEventListener('click', () => {
  $('csv-file').value = '';
  setSelectedFile(null);
});

const dropZone = $('drop-zone');
for (const eventName of ['dragenter', 'dragover']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add('dragging');
  });
}
for (const eventName of ['dragleave', 'drop']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove('dragging');
  });
}
dropZone.addEventListener('drop', (event) => {
  const file = event.dataTransfer.files[0];
  if (file) {
    $('csv-file').value = '';
    setSelectedFile(file);
  }
});

loadProfiles();
