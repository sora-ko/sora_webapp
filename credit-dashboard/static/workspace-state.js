/* 元Fileと対象プロファイルの公開メタデータをメモリ共有する。判定は各APIが生成する。 */
(() => {
  const files = {grades: null, timetable: null};
  let profile = null;
  window.creditWorkspace = {
    files: () => ({...files}),
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
      window.dispatchEvent(new Event('credit-files-changed'));
    },
  };
})();
