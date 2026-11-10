/* 화면 테마: 자동(시스템) → 라이트 → 다크 → 자동 순서로 바꾼다.
   선택은 이 브라우저에만 저장한다. 저장소를 못 쓰는 환경에서도 동작한다. */
(function () {
  var KEY = 'table-review-theme', root = document.documentElement;
  var NAMES = {dark: '다크', light: '라이트', auto: '자동'};
  var ICONS = {dark: '☾', light: '☀', auto: '◐'};

  function read() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function write(v) { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) { /* 저장 불가 */ } }

  var q = new URLSearchParams(location.search).get('theme');           // ?theme=dark|light 는 저장 없이 임시 적용
  var pref = (q === 'dark' || q === 'light') ? q : read();
  if (pref !== 'dark' && pref !== 'light') pref = null;

  function apply() {
    if (pref) root.setAttribute('data-theme', pref); else root.removeAttribute('data-theme');
    var b = document.getElementById('theme-btn');
    if (!b) return;
    var k = pref || 'auto';
    b.textContent = ICONS[k] + ' ' + NAMES[k];
    b.setAttribute('aria-label', '화면 테마: ' + NAMES[k] + '. 누르면 바뀝니다');
    b.title = k === 'auto' ? '시스템 설정을 따릅니다' : NAMES[k] + ' 모드로 고정됨';
  }

  apply();                                                              // 첫 화면이 깜빡이지 않도록 바로 적용
  document.addEventListener('DOMContentLoaded', function () {
    var b = document.getElementById('theme-btn');
    if (!b) return;
    b.addEventListener('click', function () {
      pref = pref === null ? 'light' : (pref === 'light' ? 'dark' : null);
      write(pref); apply();
    });
    apply();
  });
})();
