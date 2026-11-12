(() => {
  'use strict';
  document.documentElement.classList.add('navigation-ready');
  const header = document.querySelector('.topbar');
  const nav = document.querySelector('#primary-navigation');
  if (!header) return;
  const menus = [...document.querySelectorAll('.nav-dropdown')];
  const floatingMenus = [...header.querySelectorAll('.nav-dropdown')];
  const toggle = header.querySelector('.navigation-toggle');
  const closeMenus = except => menus.forEach(menu => { if (menu !== except) menu.open = false; });
  const closeNavigation = () => {
    nav?.classList.remove('is-open');
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.setAttribute('aria-label', 'Abrir navegação');
  };
  menus.forEach(menu => menu.addEventListener('toggle', () => {
    if (menu.open) closeMenus(menu);
  }));
  nav?.querySelector('.is-current')?.setAttribute('open', '');
  document.addEventListener('click', event => {
    floatingMenus.forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
    if (!header.contains(event.target) && !nav?.contains(event.target)) closeNavigation();
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const focusedMenu = menus.find(menu => menu.open && menu.contains(document.activeElement));
    if (focusedMenu) {
      focusedMenu.open = false;
      focusedMenu.querySelector('summary').focus();
    } else {
      floatingMenus.forEach(menu => { menu.open = false; });
      if (toggle && nav?.classList.contains('is-open')) {
        closeNavigation();
        toggle.focus();
      }
    }
  });
  toggle?.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Fechar navegação' : 'Abrir navegação');
    nav.classList.toggle('is-open', open);
  });
})();
