/* 不足単位の判定・仮配賦は新しい探索APIに任せ、既存のマス検索と分離する。 */
(() => {
  const $ = id => document.getElementById(id);
  const api = window.createRecommendationClient();
  const days = ['', '月', '火', '水', '木', '金'];
  let version = 0;
  let controller = null;
  const selected = () => window.creditRecommendations.catalogs().find(catalog =>
    `${catalog.academic_year}:${catalog.profile_id}` === $('recommendation-catalog').value);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text != null) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  };
  function invalidate() {
    version += 1;
    controller?.abort();
    controller = null;
    $('credit-search-form').setAttribute('aria-busy', 'false');
    $('credit-search-result').hidden = true;
    $('credit-search-error').hidden = true;
    $('credit-search-error').textContent = '';
    for (const id of ['credit-search-status', 'credit-search-baseline', 'credit-search-candidates',
      'credit-search-review-candidates', 'credit-search-review-summary', 'credit-search-notes', 'credit-search-json']) $(id).replaceChildren();
    $('credit-search-review').hidden = true;
    updateFiles();
  }
  function updateFiles() {
    const files = window.creditWorkspace.files();
    $('credit-search-files').textContent = `成績CSV：${files.grades ? '選択済み' : '未選択'} ／ 履修表CSV：${files.timetable ? '選択済み' : '未選択'}`;
  }
  function showError(message) {
    $('credit-search-result').hidden = true;
    $('credit-search-error').textContent = message;
    $('credit-search-error').hidden = false;
  }
  function updateCatalog() {
    const catalog = selected();
    $('credit-search-term').replaceChildren(...(catalog?.terms || []).map(term => {
      const option = node('option', `第${term}ターム`);
      option.value = String(term);
      return option;
    }));
    const currentTerm = $('timetable-term').value.split(':');
    if (catalog?.academic_year === Number(currentTerm[0]) && catalog.terms.includes(Number(currentTerm[1]))) {
      $('credit-search-term').value = currentTerm[1];
    }
    invalidate();
  }
  function card(course, review = false) {
    const element = node('details', null, 'recommendation-card');
    const title = node('summary');
    title.append(node('h4', course.name));
    element.append(title, node('span', course.category, 'recommendation-category'),
      node('p', `${course.credits} 単位 · ${course.course_code}`, 'muted'),
      node('p', course.schedule.map(slot => `${days[slot.weekday]}曜${slot.period}限`).join(' / '), 'muted'));
    const benefits = node('ul', null, 'credit-search-benefits');
    for (const effect of course.benefits) benefits.append(node('li', `${effect.label}：不足 ${effect.before_shortfall} → ${effect.after_shortfall} 単位`));
    for (const effect of course.uncertain_benefits) benefits.append(node('li', `${effect.label}：確認済み単位との差 ${effect.before_shortfall} → ${effect.after_shortfall} 単位（必要性は未確定）`));
    element.append(benefits);
    if (review && course.review_reasons.includes('matching_earned_course_unconfirmed')) element.append(node('p', '同名または同じ開講番号の成績に結果未確定の行があります。', 'muted'));
    return element;
  }
  $('credit-search-form').addEventListener('submit', async event => {
    event.preventDefault();
    invalidate();
    const files = window.creditWorkspace.files();
    const catalog = selected();
    const missing = [];
    if (!files.grades) missing.push('成績CSVが選択されていません。「単位集計」タブで成績CSVを選択してください。');
    if (!files.timetable) missing.push('履修表CSVが選択されていません。上の「履修表を読み込む」でCSVを選択してください。');
    if (missing.length) {
      showError(missing.join(' '));
      return;
    }
    if (!catalog) {
      showError('「教養候補の対象」で探索する対象を選択してください。');
      return;
    }
    if (!$('credit-search-term').value) {
      showError('探索するタームを選択してください。');
      return;
    }
    const currentVersion = version;
    controller = new AbortController();
    $('credit-search-form').setAttribute('aria-busy', 'true');
    $('credit-search-result').hidden = false;
    $('credit-search-status').textContent = '取得単位と空き時間を照合しています…';
    try {
      const data = await api.search({profile_id: catalog.profile_id, academic_year: catalog.academic_year,
        term: Number($('credit-search-term').value)}, files.grades, files.timetable, controller.signal);
      if (version !== currentVersion) return;
      $('credit-search-status').textContent = {
        ok: `空き時間に履修でき、不足を減らせる候補：${data.candidates.length}件`,
        empty: '現在の代表科目には、空き時間で不足を減らせる候補がありません。',
        unknown: '未確定の情報があるため、確実に不足を減らせる候補を確認できません。',
      }[data.status];
      $('credit-search-baseline').replaceChildren(...data.baseline.map(condition => node('p',
        `${condition.label}：${condition.status === 'unknown' ? `確認済み単位との差 ${condition.confirmed_credit_shortfall} 単位（判定不能）`
          : condition.status === 'satisfied' ? '充足' : `不足 ${condition.confirmed_credit_shortfall} 単位`}`)));
      $('credit-search-candidates').replaceChildren(...data.candidates.map(course => card(course)));
      $('credit-search-review').hidden = data.review_candidates.length === 0;
      $('credit-search-review-summary').textContent = `必要性や既存の成績に確認が必要な候補 ${data.review_candidates.length}件`;
      $('credit-search-review-candidates').replaceChildren(...data.review_candidates.map(course => card(course, true)));
      $('credit-search-notes').replaceChildren(...data.messages.map(message => node('p', message.message)));
      $('credit-search-json').textContent = JSON.stringify(data, null, 2);
    } catch (error) {
      if (version !== currentVersion || error.name === 'AbortError') return;
      showError(error.message);
    } finally {
      if (version === currentVersion) {
        controller = null;
        $('credit-search-form').setAttribute('aria-busy', 'false');
      }
    }
  });
  window.addEventListener('credit-files-changed', invalidate);
  window.addEventListener('recommendation-catalogs-loaded', updateCatalog);
  window.addEventListener('credit-timetable-parsed', updateCatalog);
  $('recommendation-catalog').addEventListener('change', updateCatalog);
  $('credit-search-term').addEventListener('change', invalidate);
  $('credit-search-clear').addEventListener('click', invalidate);
  $('timetable-term').addEventListener('change', updateCatalog);
  updateCatalog();
})();
