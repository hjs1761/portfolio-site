// 화면에 들어온 [data-reveal] 요소에 .in-view 를 붙인다(한 번만). 도식 선 그리기·측정 막대·사례 목록 등장.
(function () {
  window.__revealReady = true;
  var nodes = document.querySelectorAll('[data-reveal]');
  if (!nodes.length) return;
  if (!('IntersectionObserver' in window)) {
    nodes.forEach(function (n) { n.classList.add('in-view'); });
    return;
  }
  var io = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('in-view');
          io.unobserve(e.target);
        }
      });
    },
    { rootMargin: '0px 0px -12% 0px', threshold: 0.15 }
  );
  nodes.forEach(function (n) { io.observe(n); });
})();
