const $ = (id) => document.getElementById(id);
let report = null;
let selectedFile = null;

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
  for (const major of ['教養', '専門', '不明']) {
    const majorSummary = summary.majors.find((item) => item.major === major);
    if (!majorSummary) continue;
    const block = document.createElement('div');
    block.className = 'category-block';
    const title = node('h3', `${major} · ${majorSummary.earned_credits} 単位`);
    block.append(title);
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
  for (const id of ['student', 'cards', 'categories', 'courses', 'warnings']) {
    $(id).replaceChildren();
  }
  $('course-count').textContent = '';
  $('json').textContent = '';
  $('course-filter').replaceChildren(node('option', 'すべて'));
  $('course-filter').firstElementChild.value = 'all';
}

function setSelectedFile(file) {
  selectedFile = file || null;
  $('selected-file').textContent = selectedFile ? selectedFile.name : 'ファイルが選択されていません';
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
  button.disabled = true;
  clearReport();
  $('status').textContent = 'CSVを解析しています…';
  try {
    const body = new FormData();
    body.append('file', selectedFile, selectedFile.name);
    const response = await fetch('/api/v1/reports', {method: 'POST', body, cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`);
    renderReport(data);
    $('status').textContent = '解析が完了しました。';
  } catch (error) {
    clearReport();
    $('status').textContent = '';
    $('error').textContent = `解析に失敗しました: ${error.message}`;
    $('error').hidden = false;
  } finally {
    button.disabled = false;
  }
}

$('upload-form').addEventListener('submit', upload);
$('csv-file').addEventListener('change', (event) => setSelectedFile(event.target.files[0]));
$('course-filter').addEventListener('change', renderCourses);

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
  if (file) setSelectedFile(file);
});
