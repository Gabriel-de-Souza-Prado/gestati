(() => {
  document.documentElement.classList.add('formsets-ready');
  const deletion = row => row.querySelector('input[name$="-DELETE"]');
  const deleted = row => {
    const field = deletion(row);
    return field && (field.type === 'checkbox' ? field.checked : ['on', 'true', '1'].includes(field.value.toLowerCase()));
  };
  function remove(row) {
    const checkbox = deletion(row);
    if (!checkbox) return;
    if (checkbox.type === 'checkbox') checkbox.checked = true;
    else checkbox.value = 'on';
    row.hidden = true;
    row.querySelectorAll('input,select,textarea,button').forEach(field => {
      if (field !== checkbox && field.type !== 'hidden') field.disabled = true;
    });
  }
  function refresh() {
    document.querySelectorAll('[data-formset-row]').forEach(row => {
      if (deleted(row)) remove(row);
    });
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-row]');
    if (!button) return;
    const row = button.closest('[data-formset-row]');
    const container = row.parentElement;
    remove(row);
    const next = [...container.querySelectorAll('[data-remove-row]')].find(b => !b.closest('[data-formset-row]').hidden);
    if (next) next.focus();
    else container.parentElement.querySelector('[data-adicionar],#os-adicionar-peca')?.focus();
  });
  function add(container, total, template) {
    const prefix = total.name.replace(/-TOTAL_FORMS$/, '');
    const reusable = [...container.querySelectorAll('[data-formset-row]')].find(deleted);
    const index = reusable ? Number(deletion(reusable).name.slice(prefix.length + 1).split('-')[0]) : Number(total.value);
    if (index >= 50) return false;
    const html = template.innerHTML.replaceAll('__prefix__', String(index));
    if (reusable) reusable.outerHTML = html;
    else {
      container.insertAdjacentHTML('beforeend', html);
      total.value = String(index + 1);
    }
    return true;
  }
  window.GestatiFormsets = {add, refresh};
  refresh();
})();
