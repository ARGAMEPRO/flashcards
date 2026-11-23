/* Карточки: localStorage, интервалы по упрощённому SM-2, переворот в 3D. */
const KEY = 'cards.v1';
const state = { queue: [], current: null, flipped: false };

const $ = (id) => document.getElementById(id);

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || [];
  } catch {
    return [];
  }
}

function save(cards) {
  localStorage.setItem(KEY, JSON.stringify(cards));
}

const today = () => new Date().toISOString().slice(0, 10);

function addDays(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function nextInterval(interval, ease, known) {
  if (!known) return [1, Math.max(1.3, ease - 0.2)];
  let next = interval === 0 ? 1 : interval === 1 ? 3 : Math.round(interval * ease);
  next = Math.min(next, 365);
  return [next, Math.min(2.8, ease + 0.05)];
}

function renderStats() {
  const cards = load();
  const due = cards.filter((c) => c.due <= today()).length;
  $('stats').textContent = `${cards.length} всего · ${due} к повтору`;
}

function renderList() {
  const cards = load().slice().reverse();
  const list = $('list');
  list.innerHTML = '';
  if (!cards.length) {
    list.innerHTML = '<li><b>Пока пусто</b><span>добавьте первую</span></li>';
    return;
  }
  cards.slice(0, 20).forEach((c) => {
    const li = document.createElement('li');
    const left = document.createElement('b');
    left.textContent = c.front;
    const right = document.createElement('span');
    right.textContent = c.due;
    li.append(left, right);
    list.append(li);
  });
}

function unflip() {
  state.flipped = false;
  $('flip').classList.remove('flipped');
  $('btn-know').classList.add('hidden');
  $('btn-dunno').classList.add('hidden');
}

function startSession() {
  state.queue = load().filter((c) => c.due <= today()).map((c) => c.id);
  nextCard();
}

function nextCard() {
  unflip();
  const cards = load();
  const id = state.queue.shift();
  const card = cards.find((c) => c.id === id);

  if (!card) {
    state.current = null;
    $('review-label').textContent = 'повторение';
    $('card-front').textContent = 'На сегодня всё. Возвращайтесь завтра или добавьте карточки.';
    $('card-back').textContent = '';
    $('flip-hint').textContent = '';
    $('btn-start').classList.remove('hidden');
    renderStats();
    renderList();
    return;
  }

  state.current = card;
  $('review-label').textContent = `повтор №${(card.reviews || 0) + 1}`;
  $('card-front').textContent = card.front;
  $('card-back').textContent = card.back;
  $('flip-hint').textContent = 'нажмите на карточку';
  $('btn-start').classList.add('hidden');
}

function flip() {
  if (!state.current) return;
  state.flipped = !state.flipped;
  $('flip').classList.toggle('flipped', state.flipped);
  $('btn-know').classList.toggle('hidden', !state.flipped);
  $('btn-dunno').classList.toggle('hidden', !state.flipped);
}

function grade(known) {
  if (!state.current) return;
  const cards = load();
  const card = cards.find((c) => c.id === state.current.id);
  if (!card) return;

  const [interval, ease] = nextInterval(card.interval || 0, card.ease || 2.5, known);
  card.interval = interval;
  card.ease = ease;
  card.due = addDays(interval);
  card.reviews = (card.reviews || 0) + 1;
  save(cards);

  if (!known) state.queue.push(card.id);
  nextCard();
}

$('flip').addEventListener('click', flip);
$('btn-start').addEventListener('click', startSession);
$('btn-know').addEventListener('click', (event) => { event.stopPropagation(); grade(true); });
$('btn-dunno').addEventListener('click', (event) => { event.stopPropagation(); grade(false); });

$('add-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const front = $('front').value.trim();
  const back = $('back').value.trim();
  if (!front || !back) return;

  const cards = load();
  cards.push({
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    front,
    back,
    ease: 2.5,
    interval: 0,
    due: today(),
    reviews: 0,
  });
  save(cards);
  $('add-form').reset();
  renderStats();
  renderList();
});

document.addEventListener('keydown', (event) => {
  if (event.target.tagName === 'INPUT') return;
  if (event.code === 'Space') {
    event.preventDefault();
    flip();
  }
  if (event.key === '1') grade(true);
  if (event.key === '2') grade(false);
});

renderStats();
renderList();
