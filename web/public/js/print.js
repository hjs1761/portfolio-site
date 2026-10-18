// 이력서 「PDF로 저장」 버튼
(function () {
  var button = document.querySelector('[data-print]');
  if (button) button.addEventListener('click', function () { window.print(); });
})();
