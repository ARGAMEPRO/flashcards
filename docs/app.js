/* Карточки: хранение в localStorage, интервалы по упрощённому SM-2. */
const KEY = 'cards.v1';
const state = { queue: [], current: null, answerShown: false };

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

function today() {
  return new Date().toISOString().slice(0, 10);
}

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

function startSession() {
  const cards = load().filter((c) => c.due <= today());
  state.queue = cards.map((c) => c.id);
  nextCard();
}

function nextCard() {
  state.answerShown = false;
  const cards = load();
  const id = state.queue.shift();
  const card = cards.find((c) => c.id === id);

  if (!card) {
    state.current = null;
    $('review-label').textContent = 'повторение';
    $('card-front').textContent = state.queue.length
      ? 'Загрузка…'
      : 'На сегодня всё. Возвращайтесь завтра или добавьте карточки.';
    $('card-back').classList.add('hidden');
    $('btn-show').classList.add('hidden');
    $('btn-know').classList.add('hidden');
    $('btn-dunno').classList.add('hidden');
    $('btn-start').classList.remove('hidden');
    renderStats();
    renderList();
    return;
  }

  state.current = card;
  $('review-label').textContent = `повтор №${(card.reviews || 0) + 1}`;
  $('card-front').textContent = card.front;
  $('card-back').textContent = card.back;
  $('card-back').classList.add('hidden');
  $('btn-start').classList.add('hidden');
  $('btn-show').classList.remove('hidden');
  $('btn-know').classList.add('hidden');
  $('btn-dunno').classList.add('hidden');
}

function showAnswer() {
  if (!state.current || state.answerShown) return;
  state.answerShown = true;
  $('card-back').classList.remove('hidden');
  $('btn-show').classList.add('hidden');
  $('btn-know').classList.remove('hidden');
  $('btn-dunno').classList.remove('hidden');
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

$('btn-start').addEventListener('click', startSession);
$('btn-show').addEventListener('click', showAnswer);
$('btn-know').addEventListener('click', () => grade(true));
$('btn-dunno').addEventListener('click', () => grade(false));

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
    showAnswer();
  }
  if (event.key === '1') grade(true);
  if (event.key === '2') grade(false);
});

renderStats();
renderList();
