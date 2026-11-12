(() => {
  'use strict';
  const key = 'gestati.tema';
  const root = document.documentElement;
  const valid = value => ['claro', 'escuro'].includes(value);
  function apply(value) {
    root.dataset.theme = valid(value) ? value : 'claro';
    const dark = root.dataset.theme === 'escuro';
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      const label = dark ? 'Ativar modo claro' : 'Ativar modo escuro';
      button.setAttribute('aria-label', label);
      button.title = label;
      button.setAttribute('aria-pressed', String(dark));
    });
  }
  try { apply(localStorage.getItem(key)); }
  catch { apply('claro'); }
  document.addEventListener('DOMContentLoaded', () => {
    apply(root.dataset.theme);
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.hidden = false;
      button.addEventListener('click', () => {
        const value = root.dataset.theme === 'escuro' ? 'claro' : 'escuro';
        apply(value);
        let text = `Modo ${value} aplicado.`;
        try { localStorage.setItem(key, value); }
        catch { text += ' Não foi possível salvar a preferência neste navegador.'; }
        const status = document.getElementById('theme-announcement');
        if (status) status.textContent = text;
      });
    });
  });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) apply(event.newValue);
  });
})();
