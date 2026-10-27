/* 参考UI。候補の抽出・時間重複・学務判定はAPIが担当する。 */
(() => {
  const $ = id => document.getElementById(id);
  const days = ['', '月', '火', '水', '木', '金', '土', '日'];
  const api = window.createRecommendationClient();
  let catalogs = [];
  let timetableFile = null;
  let version = 0;
  let request = null;

  function node(tag, text, className) {
    const item = document.createElement(tag);
    if (text != null) item.textContent = String(text);
    if (className) item.className = className;
    return item;
  }
  const key = catalog => `${catalog.academic_year}:${catalog.profile_id}`;
  const selectedCatalog = () => catalogs.find(catalog => key(catalog) === $('recommendation-catalog').value);

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
      $('recommendation-status').textContent = '利用できるカタログを選択してください。';
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
    const catalog = selectedCatalog();
    $('recommendation-preview-term').replaceChildren();
    if (!catalog) return;
    for (const term of catalog.terms) {
      const option = node('option', `第${term}ターム`);
      option.value = String(term);
      $('recommendation-preview-term').append(option);
    }
    $('recommendation-scope').textContent = `${catalog.academic_year}年度 · 代表${catalog.course_count}科目。学年での絞り込みなし。修得済み・不足単位は未照合です。`;
    if (!$('recommendation-preview').hidden) renderPreview();
  }

  $('recommendation-catalog').addEventListener('change', updateCatalog);
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
    decorateCell: picker,
    invalidate,
    clear() {
      invalidate();
      timetableFile = null;
      $('recommendation-preview').hidden = true;
      $('recommendation-browse').hidden = false;
    },
    setTimetable(_data, file) {
      invalidate();
      timetableFile = file;
      $('recommendation-preview').hidden = true;
      $('recommendation-browse').hidden = true;
    },
  };

  (async () => {
    try {
      catalogs = await api.catalogs();
      $('recommendation-catalog').replaceChildren();
      for (const catalog of catalogs) {
        const option = node('option', `${catalog.academic_year}年度 · ${catalog.program}`);
        option.value = key(catalog);
        $('recommendation-catalog').append(option);
      }
      $('recommendation-browse').disabled = catalogs.length === 0;
      window.dispatchEvent(new Event('recommendation-catalogs-loaded'));
      if (!catalogs.length) $('recommendation-scope').textContent = '推薦用カタログがありません。公開データJSONの配置を確認してください。';
      else updateCatalog();
    } catch (error) {
      $('recommendation-scope').textContent = `候補データを読み込めません：${error.message}`;
    }
  })();
})();
