/* UI回帰テスト専用。従来の非保持APIを呼ぶアダプター。
 * Cookie・復元・期限の検証はcheck_session_reload.cjsで実際のクライアントを使用する。
 * アプリから配信・importしない。架空テストのFileだけをメモリで扱う。
 */
(() => {
  function factory(base = '') {
    let saved = {schema_version: 1, revision: 0, session: {expires_in_seconds: 1200}, report: null, timetable: null};
    const files = {report: null, timetable: null}, versions = {report: 0, timetable: 0}, listeners = new Set();
    async function request(path, fields, uploads, signal) {
      const body = new FormData();
      for (const [key, value] of Object.entries(fields || {})) if (value !== '' && value !== null && value !== undefined) body.append(key, String(value));
      for (const [key, file] of Object.entries(uploads || {})) if (file) body.append(key, file, file.name);
      const response = await fetch(base + '/api/v1/' + path, {method: 'POST', body, signal, cache: 'no-store', credentials: 'omit'});
      let data;
      try {data = await response.json();} catch {throw new Error('サーバーの応答を読み取れませんでした。');}
      if (!response.ok) throw Object.assign(new Error(data.error?.message || '処理に失敗しました。'), {code: data.error?.code});
      return data;
    }
    async function save(kind, path, fields, file, signal) {
      const version = ++versions[kind];
      saved[kind] = null; files[kind] = null;
      const result = await request(path, fields, {file}, signal);
      if (!result || result.schema_version !== (kind === 'report' ? 2 : 1)) throw new Error('応答の形式を確認できませんでした。');
      if (versions[kind] === version) {saved[kind] = result; files[kind] = file;}
      return {...saved, [kind]: result};
    }
    return {
      restore: async () => null,
      data: () => saved,
      check: () => true,
      onReset(callback) {listeners.add(callback);},
      saveReport: (fields, file, signal) => save('report', 'reports', fields, file, signal),
      saveTimetable: (file, signal) => save('timetable', 'timetables', {}, file, signal),
      async clear(resource) {
        const kind = resource === 'reports' ? 'report' : 'timetable';
        versions[kind]++;saved[kind]=null;files[kind]=null;return saved;
      },
      async end() {
        saved.report=null;saved.timetable=null;files.report=null;files.timetable=null;
        for(const listener of listeners) listener('ended');
      },
      suspend() {saved.report=null;saved.timetable=null;files.report=null;files.timetable=null;},
      slot: (fields, signal) => request('recommendations', fields, {file: files.timetable}, signal),
      search: (fields, signal) => request('recommendation-searches', fields,
        {grades_file: files.report, timetable_file: files.timetable}, signal),
    };
  }
  Object.defineProperty(window, 'createSessionClient', {configurable: true, get: () => factory, set() {}});
})();
