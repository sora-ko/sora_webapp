/* DOM非依存。Cookieはブラウザーに任せ、解析結果とCSRFはメモリだけに置く。 */
(() => {
  window.createSessionClient = (baseUrl = '') => {
    const base = baseUrl.replace(/\/$/, '');
    let snapshot = null, csrf = null, deadline = null, timer = null, generation = 0, suspended = false;
    let initial = null, queue = Promise.resolve();
    const listeners = new Set(), requests = new Set();
    const failure = (message, code) => Object.assign(new Error(message), {code});
    const aborted = () => new DOMException('操作を取り消しました。', 'AbortError');

    function reset(reason) {
      const hadData = Boolean(csrf || snapshot);
      snapshot = null; csrf = null; deadline = null; clearTimeout(timer);
      if (hadData || reason === 'suspended' || reason === 'ended') generation += 1;
      for (const controller of requests) controller.abort();
      if (hadData || reason === 'suspended' || reason === 'ended') {
        for (const listener of listeners) listener(reason);
      }
    }
    function checkDeadline() {
      if (deadline !== null && performance.now() >= deadline) reset('expired');
    }
    function rememberSession(session, started) {
      if (!session || session.schema_version !== 1 || session.status !== 'active'
          || typeof session.csrf_token !== 'string' || !Number.isInteger(session.expires_in_seconds)
          || session.expires_in_seconds < 1) throw failure('セッションの応答を確認できません。', 'invalid_response');
      const candidate = started + Math.max(0, session.expires_in_seconds - 1) * 1000;
      deadline = csrf === session.csrf_token && deadline !== null ? Math.min(deadline, candidate) : candidate;
      csrf = session.csrf_token;
      if (performance.now() >= deadline) {
        reset('expired');
        throw failure('一時保持の期限が切れました。CSVを読み込み直してください。', 'session_required');
      }
      clearTimeout(timer);
      timer = setTimeout(() => reset('expired'), Math.max(0, deadline - performance.now()));
    }
    function remember(data, started) {
      if (!data || data.schema_version !== 1 || !Number.isInteger(data.revision) || data.revision < 0
          || !(data.report === null || data.report?.schema_version === 2)
          || !(data.timetable === null || data.timetable?.schema_version === 1)) {
        throw failure('復元情報の形式を確認できません。', 'invalid_response');
      }
      rememberSession(data.session, started);
      snapshot = data;
      return data;
    }
    async function request(path, {method = 'GET', body, signal, update = false} = {}) {
      if (suspended) throw aborted();
      const epoch = generation, started = performance.now();
      const controller = new AbortController();
      const abort = () => controller.abort();
      if (signal?.aborted) throw aborted();
      signal?.addEventListener('abort', abort, {once: true});
      requests.add(controller);
      const headers = {'X-Session-Request': '1'};
      if (update) {
        headers['X-CSRF-Token'] = csrf;
        headers['X-Session-Revision'] = String(snapshot?.revision ?? 0);
      }
      try {
        const response = await fetch(base + '/api/v1/session' + path,
          {method, body, headers, signal: controller.signal, credentials: 'include', cache: 'no-store'});
        let data;
        try { data = await response.json(); }
        catch { throw failure('サーバーの応答を読み取れません。', 'invalid_response'); }
        if (epoch !== generation || suspended) throw aborted();
        if (!response.ok) {
          if (response.status === 401) reset('expired');
          if (response.status === 409 && data.error?.code === 'session_revision_conflict') {
            // 別タブの入力を表示中の入力と混ぜない。再読込・明示的な再解析で復元する。
            reset('conflict'); initial = null;
          }
          throw failure(data.error?.message || '一時保持の処理に失敗しました。', data.error?.code || 'request_failed');
        }
        return {data, started};
      } catch (error) {
        if (error.name === 'AbortError' || error.code) throw error;
        throw failure('サーバーに接続できません。接続状態を確認してください。', 'network_error');
      } finally {
        requests.delete(controller);
        signal?.removeEventListener('abort', abort);
      }
    }
    async function load() {
      checkDeadline();
      try {
        const result = await request('/workspace');
        return remember(result.data, result.started);
      } catch (error) {
        if (error.code === 'session_required') return null;
        throw error;
      }
    }
    function initialize() {
      if (!initial) initial = load().then(() => undefined).catch(error => {initial = null; throw error;});
      return initial;
    }
    async function ensure(create) {
      await initialize(); checkDeadline();
      if (!csrf) {
        if (!create) throw failure('一時保持の期限が切れたか、解析済み情報がありません。CSVを読み込んでください。', 'session_required');
        const result = await request('', {method: 'POST'});
        rememberSession(result.data, result.started);
        await load();
      }
      if (!snapshot) throw failure('一時保持を開始できませんでした。', 'session_required');
    }
    function mutate(action, {create = false, signal} = {}) {
      checkDeadline();
      const epoch = generation;
      const task = queue.catch(() => {}).then(async () => {
        if (epoch !== generation || signal?.aborted || suspended) throw aborted();
        await ensure(create);
        if (signal?.aborted || suspended) throw aborted();
        try { return await action(); }
        catch (error) {
          // 解析失敗でも旧結果の破棄で更新番号は進む。最新番号だけを取り直す。
          if (!suspended && epoch === generation && error.code !== 'session_required') {
            try { await load(); } catch { /* 元のエラーを利用者へ返す。 */ }
          }
          throw error;
        }
      });
      queue = task.then(() => undefined, () => undefined);
      return task;
    }
    function form(fields, file) {
      const body = new FormData();
      for (const [key, value] of Object.entries(fields || {})) {
        if (value !== undefined && value !== null && value !== '') body.append(key, String(value));
      }
      if (file) body.append('file', file, file.name);
      return body;
    }
    async function save(kind, fields, file, signal) {
      return mutate(async () => {
        const result = await request('/' + kind, {method: 'POST', body: form(fields, file), signal, update: true});
        return remember(result.data, result.started);
      }, {create: true, signal});
    }
    return {
      async restore() { await initialize(); checkDeadline(); return snapshot; },
      data: () => { checkDeadline(); return snapshot; },
      check: () => { checkDeadline(); return Boolean(csrf); },
      onReset(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      suspend() { suspended = true; reset('suspended'); },
      saveReport: (fields, file, signal) => save('reports', fields, file, signal),
      saveTimetable: (file, signal) => save('timetables', {}, file, signal),
      clear(kind) {
        return mutate(async () => {
          const result = await request('/' + kind, {method: 'DELETE', update: true});
          return remember(result.data, result.started);
        }).catch(error => { if (error.code === 'session_required') return null; throw error; });
      },
      end() {
        return mutate(async () => {
          await request('', {method: 'DELETE', update: true}); reset('ended');
        }).catch(error => { if (error.code === 'session_required') { reset('ended'); return; } throw error; });
      },
      async slot(fields, signal) {
        await queue; await ensure(false);
        return (await request('/recommendations', {method: 'POST', body: form(fields), signal, update: true})).data;
      },
      async search(fields, signal) {
        await queue; await ensure(false);
        return (await request('/recommendation-searches', {method: 'POST', body: form(fields), signal, update: true})).data;
      },
    };
  };
})();
