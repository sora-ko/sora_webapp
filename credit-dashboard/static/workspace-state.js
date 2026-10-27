/* 画面間で元Fileだけをメモリ共有する。解析結果の正本は各APIが生成する。 */
(() => {
  const files = {grades: null, timetable: null};
  window.creditWorkspace = {
    files: () => ({...files}),
    setFile(kind, file) {
      if (!Object.hasOwn(files, kind)) return;
      files[kind] = file || null;
      window.dispatchEvent(new Event('credit-files-changed'));
    },
  };
})();
