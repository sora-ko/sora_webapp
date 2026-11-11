/* 元Fileと対象プロファイルの公開メタデータをメモリ共有する。判定は各APIが生成する。 */
(() => {
  const files = {grades: null, timetable: null};
  const parsed = {grades: false, timetable: false};
  const session = window.createSessionClient();
  let profile = null;
  window.creditWorkspace = {
    session,
    files: () => ({...files}),
    parsed: () => ({...parsed}),
    setParsed(kind, value) {
      if (!Object.hasOwn(parsed, kind)) return;
      parsed[kind] = Boolean(value);
      window.dispatchEvent(new Event('credit-parsed-changed'));
    },
    clearLocal(reason) {
      files.grades=null;files.timetable=null;parsed.grades=false;parsed.timetable=false;
      window.dispatchEvent(new CustomEvent('credit-session-reset', {detail: {reason}}));
      window.dispatchEvent(new Event('credit-files-changed'));
      window.dispatchEvent(new Event('credit-parsed-changed'));
    },
    profile: () => profile ? {...profile} : null,
    setProfile(value) {
      const next = value?.profile_id ? Object.fromEntries(
        ['profile_id', 'institution', 'faculty', 'program', 'admission_year'].map(key => [key, value[key]])
      ) : null;
      if (JSON.stringify(next) === JSON.stringify(profile)) return;
      profile = next;
      window.dispatchEvent(new Event('credit-profile-changed'));
    },
    setFile(kind, file) {
      if (!Object.hasOwn(files, kind)) return;
      files[kind] = file || null;
      parsed[kind] = false;
      window.dispatchEvent(new Event('credit-files-changed'));
    },
  };
  session.onReset(reason => window.creditWorkspace.clearLocal(reason));
  window.addEventListener('pagehide', () => session.suspend());
  window.addEventListener('pageshow', event => {if (event.persisted) location.reload();});
  window.addEventListener('focus', () => session.check());
  document.addEventListener('visibilitychange', () => {if (!document.hidden) session.check();});
})();
