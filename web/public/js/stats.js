// 방문 통계 — Cloudflare Web Analytics. 실제 주소에서만 켜고, 자동화 브라우저(배포 뒤 화면 검사)는 세지 않는다.
// 설정은 이 태그의 data-* 로 받는다(Base.astro). CSP 에 static.cloudflareinsights.com·cloudflareinsights.com 허용.
(function () {
  var me = document.currentScript;
  var token = me && me.dataset.token;
  if (!token || location.hostname !== me.dataset.host || navigator.webdriver) return;
  // 공식 스니펫과 같게 module 로 넣는다(module 은 기본으로 지연 실행된다)
  var s = document.createElement('script');
  s.type = 'module';
  s.src = 'https://static.cloudflareinsights.com/beacon.min.js';
  s.setAttribute('data-cf-beacon', JSON.stringify({ token: token }));
  document.head.appendChild(s);
})();
