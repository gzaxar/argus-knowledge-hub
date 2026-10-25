const menu = document.querySelector('.menu-button');
const mobile = document.querySelector('.mobile-nav');
menu?.addEventListener('click', () => {
  const open = menu.getAttribute('aria-expanded') !== 'true';
  menu.setAttribute('aria-expanded', String(open));
  mobile?.classList.toggle('open', open);
});

const query = document.querySelector('#manual-query');
if (query) {
  const rows = [...document.querySelectorAll('.manual-row')];
  const empty = document.querySelector('.no-results');
  const filter = () => {
    const words = query.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const row of rows) {
      const matches = words.every(word => row.dataset.search.includes(word));
      row.hidden = !matches;
      if (matches) shown++;
    }
    empty.hidden = shown > 0;
  };
  query.addEventListener('input', filter);
  const term = new URLSearchParams(location.search).get('q');
  if (term) { query.value = term; filter(); }
}
