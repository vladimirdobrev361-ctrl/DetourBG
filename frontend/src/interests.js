// Интересите като един подреден списък: първият е най-важен.
// Подреждане с плъзгане (мишка) или със стрелките (телефон, клавиатура).

export const INTERESTS = {
  history: '🏛 История',
  nature: '🌲 Природа',
  museum: '🖼 Музеи',
  religion: '⛪ Храмове',
  hiking: '🥾 Хайкинг',
  cycling: '🚴 Колоездене',
  fitness: '🏋 Фитнес',
  sport_other: '🏅 Други спортове',
};

const KEY = 'detourbg.interests';
let order = load();
let dragging = null;

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY));
    if (Array.isArray(saved)) return saved.filter(k => k in INTERESTS);
  } catch { /* няма достъп до хранилището */ }
  return ['history', 'nature'];
}

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(order)); } catch { /* без запазване */ }
}

export const selectedInterests = () => [...order];

function move(from, to) {
  if (to < 0 || to >= order.length || from === to) return;
  const [k] = order.splice(from, 1);
  order.splice(to, 0, k);
  render();
}

export function render() {
  const list = document.getElementById('priority');
  const pool = document.getElementById('interest-pool');
  list.innerHTML = order.length ? order.map((k, i) => `
    <li draggable="true" data-key="${k}">
      <span class="grip" aria-hidden="true">⋮⋮</span>
      <span class="rank">${i + 1}</span>
      <span class="name">${INTERESTS[k]}</span>
      <button type="button" data-up="${i}" aria-label="По-напред" ${i === 0 ? 'disabled' : ''}>↑</button>
      <button type="button" data-down="${i}" aria-label="По-назад" ${i === order.length - 1 ? 'disabled' : ''}>↓</button>
      <button type="button" data-remove="${k}" aria-label="Махни">✕</button>
    </li>`).join('') : '<li class="empty-row">Няма избрани интереси — ще предлагаме всичко поравно.</li>';
  pool.innerHTML = Object.keys(INTERESTS).filter(k => !order.includes(k))
    .map(k => `<button type="button" data-add="${k}">+ ${INTERESTS[k]}</button>`).join('');
  save();
}

export function init() {
  const list = document.getElementById('priority');
  const pool = document.getElementById('interest-pool');
  pool.addEventListener('click', e => {
    const b = e.target.closest('[data-add]');
    if (b) { order.push(b.dataset.add); render(); }
  });
  list.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.up) move(+b.dataset.up, +b.dataset.up - 1);
    else if (b.dataset.down) move(+b.dataset.down, +b.dataset.down + 1);
    else if (b.dataset.remove) { order = order.filter(k => k !== b.dataset.remove); render(); }
  });
  list.addEventListener('dragstart', e => {
    const li = e.target.closest('li[data-key]');
    if (!li) return;
    dragging = li.dataset.key;
    li.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
  });
  list.addEventListener('dragover', e => {
    if (!dragging) return;
    e.preventDefault();
    const over = e.target.closest('li[data-key]');
    if (!over || over.dataset.key === dragging) return;
    const r = over.getBoundingClientRect();
    const after = e.clientY > r.top + r.height / 2;
    const from = order.indexOf(dragging);
    let to = order.indexOf(over.dataset.key) + (after ? 1 : 0);
    if (from < to) to -= 1;
    if (to !== from) move(from, to);
  });
  list.addEventListener('dragend', () => { dragging = null; render(); });
  render();
}
