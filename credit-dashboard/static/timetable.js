/* 履修表APIの接続と表示。学務判定や推薦処理はここで実装しない。 */
(() => {
  const $ = (id) => document.getElementById(id);
  const dayNames = ['', '月', '火', '水', '木', '金', '土', '日'];
  let selectedFile = null;
  let timetable = null;
  let requestVersion = 0;
  let controller = null;

  function element(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text == null ? '—' : String(text);
    if (className) item.className = className;
    return item;
  }

  function clearResult() {
    timetable = null;
    window.creditRecommendations.clear();
    $('timetable-dashboard').hidden = true;
    $('timetable-empty').hidden = false;
    for (const id of ['timetable-context', 'timetable-readiness', 'timetable-cards',
      'timetable-policy-notes', 'timetable-warnings', 'timetable-term', 'timetable-grid',
      'timetable-courses', 'timetable-course-count', 'timetable-json']) $(id).replaceChildren();
    $('timetable-policy-notes').hidden = true;
    $('timetable-warnings').hidden = true;
  }

  function setFile(file) {
    requestVersion += 1;
    controller?.abort();
    controller = null;
    selectedFile = file || null;
    window.creditWorkspace.setFile('timetable', selectedFile);
    $('timetable-selected-file').textContent = selectedFile ? selectedFile.name : 'ファイルが選択されていません';
    $('timetable-submit').disabled = false;
    $('timetable-submit').textContent = '履修表を解析';
    $('timetable-form').setAttribute('aria-busy', 'false');
    $('timetable-error').hidden = true;
    $('timetable-error').textContent = '';
    $('timetable-status').textContent = '';
    clearResult();
  }

  function validate(data) {
    const isYearTerm = (value) => value && Number.isInteger(value.academic_year)
      && Number.isInteger(value.term) && value.term >= 1 && value.term <= 4;
    const isSlot = (value) => value && Number.isInteger(value.weekday)
      && value.weekday >= 1 && value.weekday <= 7 && Number.isInteger(value.period) && value.period >= 1;
    if (!data || data.schema_version !== 1 || data.format !== 'niigata-rsrefer-grid'
      || !data.context || !Array.isArray(data.courses) || !Array.isArray(data.busy_slots)
      || !Array.isArray(data.display_contexts) || !data.display_contexts.every(isYearTerm)
      || !Array.isArray(data.represented_weekdays) || !data.represented_weekdays.every((day) => Number.isInteger(day) && day >= 1 && day <= 7)
      || !Array.isArray(data.represented_periods) || !data.represented_periods.every((period) => Number.isInteger(period) && period >= 1)
      || !data.courses.every((course) => isYearTerm(course) && typeof course.course_code === 'string'
        && Array.isArray(course.slots) && course.slots.every(isSlot))
      || !data.busy_slots.every((slot) => isYearTerm(slot) && isSlot(slot))
      || !Array.isArray(data.unresolved_courses) || !Array.isArray(data.warnings)
      || !Array.isArray(data.policy_notes) || typeof data.ready_for_recommendation !== 'boolean'
      || !Number.isInteger(data.excluded_term_zero_course_count)) {
      throw new Error('解析結果の形式が画面に対応していません。Dockerを利用している場合は再ビルドしてください。');
    }
  }

  async function requestTimetable(file, signal) {
    const body = new FormData();
    body.append('file', file, file.name);
    const response = await fetch('/api/v1/timetables', {method: 'POST', body, signal, cache: 'no-store'});
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error('サーバーの応答を読み取れませんでした。接続先と起動状態を確認してください。');
    }
    if (!response.ok) {
      if (response.status === 404) throw new Error('履修表APIが見つかりません。Dockerを利用している場合は再ビルドしてください。');
      throw new Error(data.error?.message || `HTTP ${response.status}`);
    }
    validate(data);
    return data;
  }

  function selectedContext() {
    if (!timetable) return null;
    return timetable.display_contexts.find((item) => `${item.academic_year}:${item.term}` === $('timetable-term').value) || null;
  }

  function matchesContext(item, context) {
    return context && item.academic_year === context.academic_year && item.term === context.term;
  }

  function renderCards(context) {
    const cards = [
      ['読み取った通常科目', `${timetable.courses.length} 科目`, 'すべてのタームの合計'],
      ['表示中の占有枠', context ? `${timetable.busy_slots.filter((slot) => matchesContext(slot, context)).length} 枠` : '—', '同じ曜日・時限の重複を除く'],
      ['番号0による除外', `${timetable.excluded_term_zero_course_count} 科目`, '利用者指定のMVP方針'],
      ['未解決の項目', `${timetable.unresolved_courses.length} 件`, timetable.ready_for_recommendation ? '読み取り上の未解決事項なし' : '下の注意事項を確認してください'],
    ];
    $('timetable-cards').replaceChildren(...cards.map(([label, value, help]) => {
      const card = element('div', undefined, 'card');
      card.append(element('span', label, 'card-title'), element('strong', value), element('span', help, 'muted'));
      return card;
    }));
  }

  function renderGrid(context, courses) {
    const table = element('table', undefined, 'calendar-table');
    const caption = element('caption', context
      ? `${context.academic_year}年度 第${context.term}タームの通常授業` : '対象ターム未確認の時間割');
    const head = element('thead');
    const headings = element('tr');
    const periodHeading = element('th', '時限');
    periodHeading.scope = 'col';
    headings.append(periodHeading);
    for (const day of timetable.represented_weekdays) {
      const heading = element('th', `${dayNames[day]}曜日`);
      heading.scope = 'col';
      headings.append(heading);
    }
    head.append(headings);
    const body = element('tbody');
    for (const period of timetable.represented_periods) {
      const row = element('tr');
      const heading = element('th', `${period}限`);
      heading.scope = 'row';
      row.append(heading);
      for (const day of timetable.represented_weekdays) {
        const cell = element('td');
        cell.dataset.weekday = String(day);
        cell.dataset.period = String(period);
        const matching = courses.filter((course) => course.slots.some((slot) => slot.weekday === day && slot.period === period));
        const occupied = timetable.busy_slots.some((slot) => matchesContext(slot, context) && slot.weekday === day && slot.period === period);
        const unresolved = timetable.unresolved_courses.some((item) => item.weekday === day && item.period === period);
        if (occupied || matching.length) {
          cell.dataset.state = 'occupied';
          const chip = element('div', undefined, 'course-chip');
          chip.append(element('span', '通常授業あり', 'course-chip-label'));
          if (matching.length) matching.forEach((course) => chip.append(element('code', course.course_code)));
          else chip.append(element('span', '番号未確認'));
          if (unresolved) chip.append(element('small', '要確認の情報もあります'));
          cell.append(chip);
        } else if (!context || !timetable.ready_for_recommendation || unresolved) {
          cell.dataset.state = 'unconfirmed';
          cell.append(element('span', '未確認', 'slot-unconfirmed'));
        } else {
          cell.dataset.state = 'empty';
          cell.append(element('span', '通常授業なし', 'slot-empty'));
        }
        window.creditRecommendations.decorateCell(cell, context);
        row.append(cell);
      }
      body.append(row);
    }
    table.append(caption, head, body);
    $('timetable-grid').replaceChildren(table);
  }

  function renderSelectedTerm() {
    if (!timetable) return;
    const context = selectedContext();
    window.creditRecommendations.setTimetableContext(context);
    const courses = timetable.courses.filter((course) => matchesContext(course, context));
    renderCards(context);
    renderGrid(context, courses);
    $('timetable-course-count').textContent = `${courses.length} 科目`;
    $('timetable-courses').replaceChildren();
    if (!courses.length) {
      const row = element('tr');
      const cell = element('td', context ? 'このタームの通常科目は読み取られていません。' : '表示する年度・タームを確認できません。', 'empty-table-cell');
      cell.colSpan = 3;
      row.append(cell);
      $('timetable-courses').append(row);
    }
    for (const course of courses) {
      const row = element('tr');
      row.append(element('td', course.course_code), element('td', `${course.academic_year}年度 · 第${course.term}ターム`),
        element('td', course.slots.map((slot) => `${dayNames[slot.weekday]}${slot.period}限`).join(' / ')));
      $('timetable-courses').append(row);
    }
  }

  function renderTimetable(data) {
    timetable = data;
    window.creditRecommendations.setTimetable(data, selectedFile);
    const context = data.context;
    $('timetable-context').textContent = context.academic_year != null
      ? `${context.academic_year}年度${context.semester != null ? ` · 第${context.semester}学期` : ''}${context.term != null ? ` · 第${context.term}ターム` : ''}`
      : 'CSV全体の年度・学期は未確認です';
    $('timetable-readiness').textContent = data.ready_for_recommendation ? '読み取り確認済み（MVP前提）' : '要確認事項があります';
    $('timetable-readiness').className = `status-badge ${data.ready_for_recommendation ? 'satisfied' : 'unknown'}`;
    $('timetable-policy-notes').replaceChildren(...data.policy_notes.map((note) => element('p', note)));
    $('timetable-policy-notes').hidden = data.policy_notes.length === 0;
    $('timetable-warnings').replaceChildren(...data.warnings.map((warning) => element('p', warning.message)));
    if (!data.ready_for_recommendation) {
      $('timetable-warnings').prepend(element('strong', '未確認の枠を空き時間とは扱っていません。'));
    }
    $('timetable-warnings').hidden = data.ready_for_recommendation && data.warnings.length === 0;
    $('timetable-term').replaceChildren();
    for (const item of data.display_contexts) {
      const option = element('option', `${item.academic_year}年度 · 第${item.term}ターム`);
      option.value = `${item.academic_year}:${item.term}`;
      $('timetable-term').append(option);
    }
    $('timetable-term').disabled = data.display_contexts.length === 0;
    if (!data.display_contexts.length) $('timetable-term').append(element('option', '年度・ターム未確認'));
    renderSelectedTerm();
    $('timetable-json').textContent = JSON.stringify(data, null, 2);
    $('timetable-dashboard').hidden = false;
    $('timetable-empty').hidden = true;
    window.dispatchEvent(new Event('credit-timetable-parsed'));
  }

  $('timetable-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!selectedFile) {
      $('timetable-error').textContent = '履修表CSVを選択してください。';
      $('timetable-error').hidden = false;
      return;
    }
    const version = ++requestVersion;
    controller?.abort();
    controller = new AbortController();
    clearResult();
    $('timetable-error').hidden = true;
    $('timetable-form').setAttribute('aria-busy', 'true');
    $('timetable-submit').disabled = true;
    $('timetable-submit').textContent = '解析中…';
    $('timetable-status').textContent = '履修表CSVを解析しています…';
    try {
      const data = await requestTimetable(selectedFile, controller.signal);
      if (version !== requestVersion) return;
      renderTimetable(data);
      $('timetable-status').textContent = '履修表の読み取りが完了しました。';
    } catch (error) {
      if (version !== requestVersion || error.name === 'AbortError') return;
      clearResult();
      $('timetable-status').textContent = '';
      $('timetable-error').textContent = `解析に失敗しました: ${error.message}`;
      $('timetable-error').hidden = false;
    } finally {
      if (version === requestVersion) {
        controller = null;
        $('timetable-form').setAttribute('aria-busy', 'false');
        $('timetable-submit').disabled = false;
        $('timetable-submit').textContent = '履修表を解析';
      }
    }
  });
  $('timetable-file').addEventListener('change', (event) => setFile(event.target.files[0]));
  $('timetable-clear').addEventListener('click', () => {
    $('timetable-file').value = '';
    setFile(null);
  });
  $('timetable-term').addEventListener('change', renderSelectedTerm);
  const dropZone = $('timetable-drop-zone');
  for (const type of ['dragenter', 'dragover']) dropZone.addEventListener(type, (event) => {
    event.preventDefault();
    dropZone.classList.add('dragging');
  });
  for (const type of ['dragleave', 'drop']) dropZone.addEventListener(type, (event) => {
    event.preventDefault();
    dropZone.classList.remove('dragging');
  });
  dropZone.addEventListener('drop', (event) => {
    const file = event.dataTransfer.files[0];
    if (file) {
      $('timetable-file').value = '';
      setFile(file);
    }
  });
})();
