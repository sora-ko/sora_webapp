/* DOMに依存しないAPIクライアント。別のフロントエンドからも利用できる。 */
(() => {
  window.createRecommendationClient = (baseUrl = '') => {
    const base = baseUrl.replace(/\/$/, '');
    async function json(url, options) {
      const response = await fetch(base + url, {...options, cache: 'no-store', credentials: 'omit'});
      let data;
      try { data = await response.json(); }
      catch { throw new Error('サーバーの応答を読み取れません。接続先と起動状態を確認してください。'); }
      if (!response.ok) {
        throw new Error(data.error?.message || `候補を取得できませんでした（HTTP ${response.status}）。`);
      }
      if (data.schema_version !== 1) throw new Error('画面とAPIの版が一致していません。再ビルドと再読み込みを確認してください。');
      return data;
    }
    return {
      async catalogs(signal) {
        const data = await json('/api/v1/recommendation-catalogs', {signal});
        if (!Array.isArray(data.catalogs)) throw new Error('カタログ一覧の形式が不正です。');
        return data.catalogs;
      },
      async recommend(context, file, signal) {
        const body = new FormData();
        for (const key of ['profile_id', 'academic_year', 'term', 'weekday', 'period']) {
          body.append(key, String(context[key]));
        }
        if (file) body.append('file', file, file.name);
        const data = await json('/api/v1/recommendations', {method: 'POST', body, signal});
        if (!data.context || !Array.isArray(data.candidates) || !Array.isArray(data.messages)
            || !data.checks || !data.counts || !['ok', 'empty', 'occupied', 'unknown'].includes(data.status)
            || !['catalog', 'timetable'].includes(data.basis)
            || !data.candidates.every(course => typeof course.course_code === 'string' && typeof course.name === 'string'
              && typeof course.category === 'string' && Number.isFinite(course.credits)
              && Array.isArray(course.terms) && Array.isArray(course.schedule)
              && course.schedule.every(slot => Number.isInteger(slot.weekday) && slot.weekday >= 1 && slot.weekday <= 7
                && Number.isInteger(slot.period) && slot.period >= 1))) {
          throw new Error('候補一覧の形式が画面に対応していません。');
        }
        return data;
      },
      async search(context, gradesFile, timetableFile, signal) {
        const body = new FormData();
        for (const key of ['profile_id', 'academic_year', 'term']) body.append(key, String(context[key]));
        body.append('grades_file', gradesFile, gradesFile.name);
        body.append('timetable_file', timetableFile, timetableFile.name);
        const data = await json('/api/v1/recommendation-searches', {method: 'POST', body, signal});
        const validBenefit = effect => effect && typeof effect.condition_id === 'string' && typeof effect.label === 'string'
          && ['before_shortfall', 'after_shortfall', 'reduced_credits'].every(key => Number.isFinite(effect[key]));
        const validCandidate = course => course && typeof course.course_code === 'string' && typeof course.name === 'string'
          && typeof course.category === 'string' && Number.isFinite(course.credits) && Array.isArray(course.terms)
          && Array.isArray(course.schedule) && course.schedule.every(slot => Number.isInteger(slot.weekday) && Number.isInteger(slot.period))
          && Array.isArray(course.benefits) && course.benefits.every(validBenefit)
          && Array.isArray(course.uncertain_benefits) && course.uncertain_benefits.every(validBenefit)
          && Array.isArray(course.review_reasons);
        if (!data.context || data.target_requirement_id !== 'graduation' || !['ok', 'empty', 'unknown'].includes(data.status)
            || !Array.isArray(data.baseline) || !data.baseline.every(condition => condition && typeof condition.label === 'string'
              && ['satisfied', 'not_satisfied', 'unknown'].includes(condition.status)
              && Number.isFinite(condition.confirmed_credit_shortfall))
            || !Array.isArray(data.free_slots) || !Array.isArray(data.candidates) || !data.candidates.every(validCandidate)
            || !Array.isArray(data.review_candidates) || !data.review_candidates.every(validCandidate)
            || !data.checks || !data.counts || !Array.isArray(data.messages)) {
          throw new Error('単位照合の候補一覧の形式が画面に対応していません。');
        }
        return data;
      },
    };
  };
})();
