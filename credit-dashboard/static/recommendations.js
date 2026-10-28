/* 参考UI。候補の抽出・時間重複・学務判定はAPIが担当する。 */
(() => {
  const $ = id => document.getElementById(id);
  const days = ['', '月', '火', '水', '木', '金', '土', '日'];
  const api = window.createRecommendationClient();
  let catalogs = [];
  let catalogLoading = true;
  let catalogError = '';
  let timetableFile = null;
  let timetableContext = null;
  let version = 0;
  let request = null;

  function node(tag, text, className) {
    const item = document.createElement(tag);
    if (text != null) item.textContent = String(text);
    if (className) item.className = className;
    return item;
  }
  const selectedCatalog = () => {
    const profile = window.creditWorkspace.profile();
    const matches = catalogs.filter(catalog => catalog.profile_id === profile?.profile_id);
    if (timetableFile) return matches.find(catalog => catalog.academic_year === timetableContext?.academic_year);
    return matches.sort((a, b) => b.academic_year - a.academic_year)[0];
  };
  function selectionMessage() {
    if (!window.creditWorkspace.profile()) return '「単位集計」タブで対象プログラムを選択してください。';
    if (catalogLoading) return '候補データを読み込んでいます。しばらくお待ちください。';
    if (catalogError) return catalogError;
    if (timetableFile && !timetableContext?.academic_year) return '履修表の開講年度を確認できません。年度・タームの情報を確認してください。';
    const year = timetableContext?.academic_year;
    return `単位集計で選択した対象${year ? `の${year}年度` : ''}に対応する教養候補データがありません。`;
  }

  function invalidate() {
    version += 1;
    request?.abort();
    request = null;
    $('recommendation-result').hidden = true;
    $('recommendation-result').setAttribute('aria-busy', 'false');
    for (const id of ['recommendation-heading', 'recommendation-status', 'recommendation-notes', 'recommendation-candidates',
      'recommendation-count', 'recommendation-json']) $(id).replaceChildren();
    document.querySelectorAll('.slot-picker[aria-pressed="true"]').forEach(button => button.setAttribute('aria-pressed', 'false'));
  }

  function picker(cell, context) {
    if (!context || Number(cell.dataset.weekday) > 5 || Number(cell.dataset.period) > 5) return;
    const button = node('button', null, 'slot-picker');
    button.type = 'button';
    button.setAttribute('aria-label', `第${context.term}ターム ${days[Number(cell.dataset.weekday)]}曜${cell.dataset.period}限の教養候補を確認`);
    button.setAttribute('aria-pressed', 'false');
    button.append(...cell.childNodes, node('span', '候補を見る', 'slot-picker-hint'));
    cell.replaceChildren(button);
    button.addEventListener('click', () => showCandidates({
      ...context, weekday: Number(cell.dataset.weekday), period: Number(cell.dataset.period),
    }, button));
  }

  async function showCandidates(context, button) {
    invalidate();
    const catalog = selectedCatalog();
    button.closest('.calendar-panel')?.after($('recommendation-result'));
    $('recommendation-result').hidden = false;
    $('recommendation-heading').textContent = `第${context.term}ターム · ${days[context.weekday]}曜${context.period}限`;
    button.setAttribute('aria-pressed', 'true');
    if (!catalog) {
      $('recommendation-status').textContent = selectionMessage();
      return;
    }
    if (catalog.academic_year !== context.academic_year) {
      $('recommendation-status').textContent = 'この開講年度に対応する教養候補データがありません。';
      return;
    }
    const currentVersion = version;
    request = new AbortController();
    $('recommendation-result').setAttribute('aria-busy', 'true');
    $('recommendation-status').textContent = '候補を確認しています…';
    $('recommendation-result').scrollIntoView({block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    try {
      const data = await api.recommend({...context, profile_id: catalog.profile_id}, timetableFile, request.signal);
      if (currentVersion !== version) return;
      $('recommendation-status').textContent = {
        ok: data.basis === 'timetable' ? 'すべての曜限で、履修表の通常授業と重複しない候補です。' : 'カタログ上の候補です。履修中の授業との重複は未確認です。',
        empty: '現在の代表科目には、この条件で提示できる候補がありません。',
        occupied: 'この枠には授業があります。別の枠を選んでください。',
        unknown: '未確認の情報があるため、候補の判定を保留しています。',
      }[data.status];
      $('recommendation-count').textContent = `${data.counts.returned} 件`;
      $('recommendation-notes').replaceChildren(...data.messages.map(message => node('p', message.message)));
      const excluded = data.counts.excluded_overlap + data.counts.excluded_registered + data.counts.excluded_unconfirmed;
      if (excluded) $('recommendation-notes').append(node('p', `重複・登録済み・未確認で除外：${excluded}件`));
      $('recommendation-candidates').replaceChildren(...data.candidates.map(course => {
        const card = node('details', null, 'recommendation-card');
        const title = node('summary');
        title.append(node('h4', course.name));
        card.append(title, node('span', course.category, 'recommendation-category'));
        const details = node('div', null, 'recommendation-course-meta');
        details.append(node('strong', `${course.credits} 単位`), node('code', course.course_code));
        card.append(details, node('p', course.schedule.map(slot => `${days[slot.weekday]}曜${slot.period}限`).join(' / '), 'muted'));
        return card;
      }));
      $('recommendation-json').textContent = JSON.stringify(data, null, 2);
    } catch (error) {
      if (currentVersion !== version || error.name === 'AbortError') return;
      $('recommendation-status').textContent = `取得に失敗しました：${error.message}`;
    } finally {
      if (currentVersion === version) {
        request = null;
        $('recommendation-result').setAttribute('aria-busy', 'false');
      }
    }
  }

  function renderPreview() {
    invalidate();
    const catalog = selectedCatalog();
    if (!catalog) return;
    const context = {academic_year: catalog.academic_year, term: Number($('recommendation-preview-term').value)};
    const table = node('table', null, 'calendar-table recommendation-calendar');
    const head = node('thead');
    const headers = node('tr');
    headers.append(node('th', '時限'));
    catalog.weekdays.forEach(day => headers.append(node('th', `${days[day]}曜日`)));
    head.append(headers);
    const body = node('tbody');
    for (const period of catalog.periods) {
      const row = node('tr');
      row.append(node('th', `${period}限`));
      for (const day of catalog.weekdays) {
        const cell = node('td');
        cell.dataset.weekday = String(day);
        cell.dataset.period = String(period);
        cell.append(node('span', '教養科目', 'catalog-slot-label'));
        picker(cell, context);
        row.append(cell);
      }
      body.append(row);
    }
    table.append(head, body);
    $('recommendation-preview-grid').replaceChildren(table);
  }

  function updateCatalog() {
    invalidate();
    const profile = window.creditWorkspace.profile();
    $('recommendation-target').textContent = profile
      ? `単位集計と共通：${profile.faculty} ${profile.program}（${profile.admission_year}年度入学）`
      : '対象プログラムは「単位集計」タブで選択してください。';
    const catalog = selectedCatalog();
    const previousTerm = $('recommendation-preview-term').value;
    $('recommendation-preview-term').replaceChildren();
    $('recommendation-browse').disabled = !catalog;
    if (!catalog) {
      $('recommendation-scope').textContent = selectionMessage();
      $('recommendation-preview-grid').replaceChildren();
      $('recommendation-preview').hidden = true;
      window.dispatchEvent(new Event('recommendation-context-changed'));
      return;
    }
    for (const term of catalog.terms) {
      const option = node('option', `第${term}ターム`);
      option.value = String(term);
      $('recommendation-preview-term').append(option);
    }
    if (catalog.terms.includes(Number(previousTerm))) $('recommendation-preview-term').value = previousTerm;
    $('recommendation-scope').textContent = `${catalog.academic_year}年度 · 代表${catalog.course_count}科目。学年での絞り込みなし。修得済み・不足単位は未照合です。`;
    if (!$('recommendation-preview').hidden) renderPreview();
    window.dispatchEvent(new Event('recommendation-context-changed'));
  }

  window.addEventListener('credit-profile-changed', updateCatalog);
  $('recommendation-preview-term').addEventListener('change', renderPreview);
  $('recommendation-browse').addEventListener('click', () => {
    if (!selectedCatalog()) return;
    $('timetable-error').hidden = true;
    $('timetable-error').textContent = '';
    $('timetable-empty').hidden = true;
    $('recommendation-preview').hidden = false;
    renderPreview();
  });
  window.creditRecommendations = {
    catalogs: () => [...catalogs],
    selectedCatalog,
    selectionMessage,
    timetableContext: () => timetableContext ? {...timetableContext} : null,
    decorateCell: picker,
    invalidate,
    clear() {
      invalidate();
      timetableFile = null;
      timetableContext = null;
      $('recommendation-preview').hidden = true;
      $('recommendation-browse').hidden = false;
      updateCatalog();
    },
    setTimetable(_data, file) {
      invalidate();
      timetableFile = file;
      $('recommendation-preview').hidden = true;
      $('recommendation-browse').hidden = true;
    },
    setTimetableContext(context) {
      timetableContext = context ? {...context} : null;
      updateCatalog();
    },
  };

  (async () => {
    try {
      catalogs = await api.catalogs();
      catalogLoading = false;
      updateCatalog();
    } catch (error) {
      catalogLoading = false;
      catalogError = `候補データを読み込めません：${error.message}`;
      updateCatalog();
    }
  })();
})();
