(function () {
  'use strict';
  var key = 'kanit-panel-tema';
  var mode = 'light';
  try { if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) mode = 'dark'; } catch (_) {}
  try { var stored = localStorage.getItem(key); if (stored === 'light' || stored === 'dark') mode = stored; } catch (_) {}
  function apply() {
    document.documentElement.setAttribute('data-theme', mode);
    document.documentElement.style.colorScheme = mode;
    document.querySelectorAll('[data-tema-toggle]').forEach(function (b) {
      b.textContent = mode === 'dark' ? 'Açık tema' : 'Koyu tema';
      b.setAttribute('aria-label', mode === 'dark' ? 'Açık temaya geç' : 'Koyu temaya geç');
      b.setAttribute('aria-pressed', mode === 'dark' ? 'true' : 'false');
    });
  }
  apply();
  document.addEventListener('DOMContentLoaded', apply);
  document.addEventListener('click', function (e) {
    var button = e.target.closest('[data-tema-toggle]');
    if (!button) return;
    mode = mode === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(key, mode); } catch (_) {}
    apply();
  });
})();
