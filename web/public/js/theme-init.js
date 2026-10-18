// 그리기 전에 실행(<head> 동기): 저장된 톤 적용 + 움직임 허용 여부 표시.
try {
  var t = localStorage.getItem('theme');
  document.documentElement.dataset.theme = t === 'light' || t === 'dark' ? t : 'dark';
} catch (e) {
  document.documentElement.dataset.theme = 'dark';
}
// 'motion' 이 있을 때만 등장 효과의 시작 상태(숨김)를 쓴다. 등장 스크립트가 4초 안에 준비되지 않으면
// 클래스를 떼서 처음부터 완성 상태로 보이게 한다 — 내용이 숨겨진 채 남는 일을 막는다.
try {
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.documentElement.classList.add('motion');
    window.setTimeout(function () {
      if (!window.__revealReady) document.documentElement.classList.remove('motion');
    }, 4000);
  }
} catch (e) {}
