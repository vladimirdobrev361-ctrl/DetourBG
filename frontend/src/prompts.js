// Големият въпрос „Да / Не“ върху картата — един бутон, удобен докато шофирате.

const el = id => document.getElementById(id);
let resolver = null;

export function ask({ title, html, image, yes = 'Да', no = 'Не' }) {
  el('prompt-title').textContent = title;
  el('prompt-text').innerHTML = html;
  const img = el('prompt-img');
  img.hidden = !image;
  if (image) img.src = image;
  el('prompt-yes').textContent = yes;
  el('prompt-no').textContent = no;
  el('prompt').hidden = false;
  el('prompt-yes').focus();
  return new Promise(resolve => { resolver = resolve; });
}

export const isAsking = () => resolver !== null;

function close(answer) {
  el('prompt').hidden = true;
  const r = resolver;
  resolver = null;
  r?.(answer);
}

el('prompt-yes').addEventListener('click', () => close(true));
el('prompt-no').addEventListener('click', () => close(false));
document.addEventListener('keydown', e => {
  if (el('prompt').hidden) return;
  if (e.key === 'Escape') close(false);
});
