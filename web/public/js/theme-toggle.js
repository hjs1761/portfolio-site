// 톤 전환 버튼. 선택은 localStorage 에 저장한다(못 쓰는 환경이면 이번 방문에만 적용).
(function () {
  var button = document.querySelector('[data-theme-toggle]');
  var root = document.documentElement;
  if (!button) return;

  function sync() {
    var dark = root.dataset.theme !== 'light';
    button.setAttribute('aria-label', dark ? '밝은 톤으로 전환' : '어두운 톤으로 전환');
  }

  button.addEventListener('click', function () {
    var next = root.dataset.theme === 'light' ? 'dark' : 'light';
    root.dataset.theme = next;
    try {
      localStorage.setItem('theme', next);
    } catch (e) {}
    sync();
  });

  sync();
})();
