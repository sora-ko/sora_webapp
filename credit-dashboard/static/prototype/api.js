/* 文書化されたHTTP APIだけを使う。既存画面・Pythonモジュールには依存しない。 */
export class ApiError extends Error {
  constructor(message, code = 'request_failed', details = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.details = details;
  }
}

export function createApi(base = '') {
  const origin = base.replace(/\/$/, '');
  async function request(path, {fields, files, signal, schema} = {}) {
    const options = {cache: 'no-store', credentials: 'omit', signal};
    if (fields || files) {
      options.method = 'POST';
      options.body = new FormData();
      for (const [key, value] of Object.entries(fields || {})) {
        if (value !== null && value !== undefined && value !== '') options.body.append(key, String(value));
      }
      for (const [key, file] of Object.entries(files || {})) {
        if (file) options.body.append(key, file, file.name);
      }
    }
    let response;
    try { response = await fetch(origin + path, options); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new ApiError('サーバーに接続できませんでした。接続を確認して、もう一度お試しください。', 'network_error');
    }
    let data;
    try { data = await response.json(); }
    catch { throw new ApiError('サーバーの応答を読み取れませんでした。もう一度お試しください。', 'invalid_response'); }
    if (!response.ok) throw new ApiError(data.error?.message || '処理に失敗しました。時間をおいてもう一度お試しください。', data.error?.code, data.error?.details);
    if (!data || typeof data !== 'object' || (schema !== undefined && data.schema_version !== schema)) {
      throw new ApiError('情報を正しく読み込めませんでした。ページを再読み込みして、もう一度お試しください。', 'invalid_response');
    }
    return data;
  }
  return {
    profiles: signal => request('/api/v1/rule-profiles', {signal}),
    catalogs: signal => request('/api/v1/recommendation-catalogs', {signal, schema: 1}),
    report: (fields, file, signal) => request('/api/v1/reports', {fields, files: {file}, signal, schema: 2}),
    timetable: (file, signal) => request('/api/v1/timetables', {files: {file}, signal, schema: 1}),
    slot: (fields, file, signal) => request('/api/v1/recommendations', {fields, files: {file}, signal, schema: 1}),
    search: (fields, grades, timetable, signal) => request('/api/v1/recommendation-searches', {
      fields, files: {grades_file: grades, timetable_file: timetable}, signal, schema: 1,
    }),
  };
}
