(() => {
  document.querySelectorAll('[data-password-toggle]').forEach(button => {
    const input = document.getElementById(button.dataset.passwordToggle);
    if (!input) return;
    button.hidden = false;
    button.addEventListener('click', () => {
      const visible = input.type === 'password';
      input.type = visible ? 'text' : 'password';
      button.setAttribute('aria-pressed', String(visible));
      const label = `${visible ? 'Ocultar' : 'Mostrar'} ${button.dataset.passwordLabel}`;
      button.setAttribute('aria-label', label);
      button.title = label;
    });
  });
})();
