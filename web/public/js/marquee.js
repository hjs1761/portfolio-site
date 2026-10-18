// 기술 스택 띠: 화면 밖이거나 탭이 숨으면 멈춘다(보이지 않는 반복 애니메이션 금지).
(function () {
  var nodes = document.querySelectorAll('[data-marquee]');
  if (!nodes.length || !('IntersectionObserver' in window)) return;
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) e.target.removeAttribute('data-paused');
      else e.target.setAttribute('data-paused', '');
    });
  });
  nodes.forEach(function (n) {
    io.observe(n);
  });
})();
