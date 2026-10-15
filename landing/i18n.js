// i18n.js — nexus-core landing language detection
(function() {
  'use strict';

  var SUPPORTED = ['ar', 'en'];
  var DEFAULT = 'en';
  var STORAGE_KEY = 'nexus-core-lang';

  function detectLang() {
    // 1. URL param ?lang=xx
    var params = new URLSearchParams(window.location.search);
    var urlLang = params.get('lang');
    if (urlLang && SUPPORTED.indexOf(urlLang) !== -1) return urlLang;

    // 2. localStorage (اختيار سابق)
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved && SUPPORTED.indexOf(saved) !== -1) return saved;
    } catch(e) {}

    // 3. لغة المتصفح
    var browserLang = (navigator.language || navigator.userLanguage || DEFAULT)
      .toLowerCase().split('-')[0];
    if (SUPPORTED.indexOf(browserLang) !== -1) return browserLang;

    return DEFAULT;
  }

  function isRedirectTarget() {
    var p = window.location.pathname;
    // الصفحة الرئيسية: /, /index.html, /landing/, /nexus-core/
    return /(\/|\/index\.html)$/.test(p)
        && p.indexOf('index.ar.html') === -1
        && p.indexOf('index.en.html') === -1;
  }

  function redirect() {
    if (!isRedirectTarget()) return;
    var lang = detectLang();
    window.location.replace('index.' + lang + '.html');
  }

  function switchLang(lang) {
    if (SUPPORTED.indexOf(lang) === -1) return;
    try { localStorage.setItem(STORAGE_KEY, lang); } catch(e) {}
    window.location.href = 'index.' + lang + '.html';
  }

  // Global function for onclick
  window.nexusSwitchLang = switchLang;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', redirect);
  } else {
    redirect();
  }
})();
