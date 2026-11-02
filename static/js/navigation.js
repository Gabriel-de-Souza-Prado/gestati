(() => {
  document.documentElement.classList.add('navigation-ready');
  const header = document.querySelector('.topbar');
  if (!header) return;
  const menus = [...header.querySelectorAll('.nav-dropdown')];
  const toggle = header.querySelector('.navigation-toggle');
  const nav = header.querySelector('#primary-navigation');
  const closeMenus = except => menus.forEach(menu => { if (menu !== except) menu.open = false; });
  menus.forEach(menu => menu.addEventListener('toggle', () => {
    if (menu.open) closeMenus(menu);
  }));
  document.addEventListener('click', event => {
    menus.forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
    if (!header.contains(event.target) && toggle && nav) {
      nav.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const focusedMenu = menus.find(menu => menu.open && menu.contains(document.activeElement));
    closeMenus();
    if (focusedMenu) focusedMenu.querySelector('summary').focus();
    else if (toggle && nav && nav.classList.contains('is-open')) {
      nav.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.focus();
    }
  });
  toggle?.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    nav.classList.toggle('is-open', open);
    if (!open) closeMenus();
  });
})();
