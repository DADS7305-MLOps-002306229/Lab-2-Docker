const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const number = value => new Intl.NumberFormat().format(value);
const state = {cards: [], archived: [], calendar: [], editing: null, clockOffset: 0, today: '', renderSignature: null, calendarKey: null};
const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
let toastTimer;
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 3500);
}
async function api(path, method = 'GET', body) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
  return data;
}
async function load() {
  try {
    const data = await api('/api/cards');
    const signature = JSON.stringify([data.cards, data.archived]);
    const changed = state.renderSignature !== signature;
    state.renderSignature = signature;
    state.cards = data.cards;
    state.archived = data.archived;
    state.calendar = data.calendar;
    state.today = data.today;
    state.clockOffset = data.server_now - Date.now();
    $('#today-label').dateTime = data.today;
    $('#today-label').textContent = new Date(data.today + 'T12:00:00').toLocaleDateString(undefined, {weekday:'long', month:'long', day:'numeric'});
    if (changed) render();
    else renderCalendar();
  } catch (error) { toast('Couldn’t load your progress. Check the server and refresh.'); }
}
function schedule(card) {
  if (card.mode === 'date') return 'Date range';
  if (card.mode === 'daily') return 'Every day';
  if (card.mode === 'weekdays') return card.weekdays.map(d => days[d]).join(', ');
  return 'Manual';
}
function nextUpdate(card) {
  if (card.current >= card.target) return 'Completed';
  if (card.mode === 'date') return `Completes ${formatDate(card.end_date)}`;
  const date = new Date(card.last_date + 'T12:00:00');
  for (let i = 1; i <= 7; i++) {
    date.setDate(date.getDate() + 1);
    if (card.mode === 'daily' || card.weekdays.includes((date.getDay() + 6) % 7)) {
      return `Next update ${i === 1 ? 'tomorrow' : date.toLocaleDateString(undefined, {weekday:'long'})} · +${number(card.step)}`;
    }
  }
  return '';
}
function formatDate(value) {
  return new Date(value + 'T12:00:00').toLocaleDateString(undefined, {month:'short',day:'numeric',year:'numeric'});
}
function heatmap(total, fraction, label = 'Dots show overall completion') {
  const filled = Math.floor(fraction * total);
  return `<div class="dot-grid" data-filled="${filled}" aria-hidden="true" title="${escapeHTML(label)}">${Array.from({length: total}, (_, index) => `<span class="${index < filled ? 'is-filled' : ''}"></span>`).join('')}</div>`;
}
function calendarDots(c) {
  // A year uses weeks so its dots remain readable in the pinned column.
  return c.period === 'year' ? Math.ceil(c.cells / 7) : c.cells;
}
function renderCalendar() {
  const now = Date.now() + state.clockOffset;
  const readings = state.calendar.map(c => {
    const fraction = Math.max(0, Math.min(1, (now - c.start) / (c.end - c.start)));
    const percentage = Math.min(99, Math.floor(fraction * 100));
    const left = Math.max(0, c.end - now);
    const remaining = c.period === 'day' ? `${Math.ceil(left/3600000)} hours remaining` : `${Math.ceil(left/86400000)} days remaining`;
    return {c, fraction, percentage, remaining};
  });
  const key = JSON.stringify(state.calendar.map(c => [c.period, c.start, c.end]));
  const root = $('#calendar-cards');
  if (key === state.calendarKey) {
    readings.forEach(({c, fraction, percentage, remaining}) => {
      const card = root.querySelector(`[data-period="${c.period}"]`);
      card.querySelector('.time-value strong').innerHTML = `${percentage}<span>%</span>`;
      card.querySelector('.time-track').setAttribute('aria-valuenow', percentage);
      card.querySelector('.time-track>span').style.width = `${fraction * 100}%`;
      card.querySelector('.widget-caption').innerHTML = `${remaining}${c.period === 'week' ? '<span>Mon–Sun</span>' : ''}`;
      const grid = card.querySelector('.dot-grid');
      const filled = Math.floor(fraction * calendarDots(c));
      if (Number(grid.dataset.filled) !== filled) {
        grid.dataset.filled = filled;
        grid.querySelectorAll('span').forEach((dot, index) => dot.classList.toggle('is-filled', index < filled));
      }
    });
    return;
  }
  state.calendarKey = key;
  root.innerHTML = readings.map(({c, fraction, percentage, remaining}) => `<article class="time-card time-${c.period}" data-period="${c.period}">
      <h3>${c.title}</h3>
      <div class="time-value"><strong>${percentage}<span>%</span></strong><span>elapsed</span></div>
      ${heatmap(calendarDots(c), fraction, c.period === 'year' ? 'Each dot represents a week of the year' : c.period === 'day' ? 'Each dot represents an hour' : 'Each dot represents a day')}
      <div class="time-track" role="progressbar" aria-label="${c.title} elapsed" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percentage}"><span style="width:${fraction*100}%"></span></div>
      <p class="widget-caption">${remaining}${c.period === 'week' ? '<span>Mon–Sun</span>' : ''}</p>
    </article>`).join('');
  window.ProgressMotion?.calendar(root);
}
function goalCard(c) {
  const done = c.current >= c.target;
  const fraction = c.current / c.target;
  const percentage = done ? 100 : Math.floor(fraction * 100);
  const manual = c.mode === 'manual';
  const dated = c.mode === 'date';
  const upcoming = dated && c.start_date > state.today;
  const kind = dated ? 'Date range' : manual ? 'Manual' : 'Scheduled';
  const status = done ? 'Completed' : upcoming ? 'Not started' : dated ? `${number(c.target-c.current)} days remaining` : `${number(c.target-c.current)} ${escapeHTML(c.unit)} remaining`;
  const caption = dated ? `${formatDate(c.start_date)} – ${formatDate(c.end_date)}` : c.mode === 'weekdays' ? schedule(c) : c.mode === 'daily' ? 'Updates daily' : `${number(c.step)} ${escapeHTML(c.unit)} per step`;
  return `<article class="progress-card ${c.color}${done ? ' is-complete' : ''}" data-card-id="${c.id}" data-current="${c.current}" data-target="${c.target}">
    <div class="card-header"><span class="card-kind">${kind}</span><button class="edit-button" data-edit="${c.id}" aria-label="Edit ${escapeHTML(c.title)}" title="Edit progress">Edit</button></div>
    <h3>${escapeHTML(c.title)}</h3>
    ${c.description ? `<p class="card-description">${escapeHTML(c.description)}</p>` : ''}
    <div class="progress-body">
      <div class="progress-reading"><div class="progress-value"><strong class="current-number">${number(c.current)}</strong><span> / ${number(c.target)} ${escapeHTML(c.unit)}${dated ? ' elapsed' : ''}</span></div><span class="percentage">${percentage}%</span></div>
      ${heatmap(Math.min(c.target, 60), fraction)}
      <div class="progress-track" role="progressbar" aria-label="${escapeHTML(c.title)}" aria-valuemin="0" aria-valuemax="${c.target}" aria-valuenow="${c.current}"><span style="width:${fraction*100}%"></span></div>
      <p class="progress-status">${status}</p>
    </div>
    <div class="card-bottom"><p class="schedule-label" title="${escapeHTML(manual ? `${c.step} ${c.unit} per step` : nextUpdate(c))}">${caption}</p>
    ${manual && !done ? `<div class="stepper" role="group" aria-label="Update ${escapeHTML(c.title)}"><button data-adjust="${c.id}" data-direction="-1" aria-label="Subtract ${c.step} from ${escapeHTML(c.title)}" ${c.current === 0 ? 'disabled' : ''}>−</button><button data-adjust="${c.id}" data-direction="1" aria-label="Add ${c.step} to ${escapeHTML(c.title)}">+</button></div>` : `<span class="card-state">${done ? 'Complete' : ''}</span>`}</div>
  </article>`;
}
function render() {
  const focused = document.activeElement;
  const focusSelector = focused?.dataset.adjust ? `[data-adjust="${focused.dataset.adjust}"][data-direction="${focused.dataset.direction}"]` : focused?.dataset.edit ? `[data-edit="${focused.dataset.edit}"]` : null;
  renderCalendar();
  $('#card-count').textContent = state.cards.length;
  $('#archive-count').textContent = state.archived.length;
  $('#cards').innerHTML = state.cards.map(goalCard).join('');
  $('#archive-cards').innerHTML = state.archived.map(goalCard).join('');
  $('#empty').hidden = state.cards.length > 0;
  $('#archive-empty').hidden = state.archived.length > 0;
  window.ProgressMotion?.cards($('#cards'));
  window.ProgressMotion?.cards($('#archive-cards'));
  if (focusSelector) {
    const target = document.querySelector(focusSelector);
    if (target && !target.closest('details:not([open])')) target.focus({preventScroll: true});
  }
}
async function handleCardClick(event) {
  const edit = event.target.closest('[data-edit]');
  if (edit) return openEditor([...state.cards, ...state.archived].find(c => c.id === Number(edit.dataset.edit)));
  const adjust = event.target.closest('[data-adjust]');
  if (!adjust || adjust.disabled) return;
  const card = state.cards.find(c => c.id === Number(adjust.dataset.adjust));
  event.target.closest('.stepper').querySelectorAll('button').forEach(b => b.disabled = true);
  try {
    await api(`/api/cards/${adjust.dataset.adjust}/adjust`, 'POST', {direction: Number(adjust.dataset.direction)});
    if (Number(adjust.dataset.direction) === 1 && card.current + card.step >= card.target) toast('Completed. Moved to archive.');
    await load();
  } catch(error) {toast(error.message); await load();}
}
$('#cards').addEventListener('click', handleCardClick);
$('#archive-cards').addEventListener('click', handleCardClick);
const form = $('#card-form');
$('#color-picker').innerHTML = ['blue','purple','green','orange','pink','teal'].map(color => `<label class="${color}"><input type="radio" name="color" value="${color}" aria-label="${color}" ${color === 'blue' ? 'checked' : ''}><span>✓</span></label>`).join('');
const weekdayNames = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
document.querySelectorAll('#weekdays input').forEach((input,i) => input.setAttribute('aria-label',weekdayNames[i]));
function updateSchedule() {
  const mode = form.elements.mode.value;
  $('#weekdays').hidden = mode !== 'weekdays';
  $('#schedule-help').textContent = mode === 'manual' ? 'Use + and − to update progress.' : 'Updates at midnight (server time), starting on the next scheduled day.';
}
function updateType() {
  const dated = form.elements.progress_type.value === 'date';
  $('#date-fields').hidden = !dated;
  $('#date-fields').disabled = !dated;
  $('#step-fields').hidden = dated;
  $('#step-fields').disabled = dated;
}
function updateEndDateMin() {
  const value = form.elements.start_date.value;
  form.elements.end_date.min = value ? new Date(new Date(value + 'T00:00:00Z').getTime() + 86400000).toISOString().slice(0,10) : '';
}
form.elements.progress_type.addEventListener('change', updateType);
form.elements.start_date.addEventListener('change', updateEndDateMin);
form.elements.mode.addEventListener('change',updateSchedule);
form.elements.target.addEventListener('input', () => {form.elements.current.max = form.elements.target.value;});
function openEditor(card = null) {
  state.editing = card;
  form.reset();
  $('#form-error').textContent = '';
  $('#editor-title').textContent = card ? 'Edit progress' : 'Add progress';
  $('#save-card').textContent = card ? 'Save changes' : 'Add progress';
  $('#delete-card').hidden = !card;
  form.elements.progress_type.value = card?.mode === 'date' ? 'date' : 'steps';
  form.elements.start_date.value = card?.start_date || state.today;
  form.elements.end_date.value = card?.end_date || new Date(new Date((state.today || new Date().toISOString().slice(0,10)) + 'T00:00:00Z').getTime() + 30*86400000).toISOString().slice(0,10);
  if (card) {
    for (const key of ['title','description','target','current','unit','step','color']) form.elements[key].value = card[key];
    form.elements.mode.value = card.mode === 'date' ? 'manual' : card.mode;
    document.querySelectorAll('#weekdays input').forEach(input => input.checked = card.weekdays.includes(Number(input.value)));
  }
  form.elements.current.max = form.elements.target.value;
  updateSchedule();
  updateType();
  updateEndDateMin();
  $('#editor').showModal();
}
$('#new-card').addEventListener('click', () => openEditor());
$('#empty-create').addEventListener('click', () => openEditor());
['#close-editor','#cancel-editor'].forEach(selector => $(selector).addEventListener('click', () => $('#editor').close()));
form.addEventListener('submit', async event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(form));
  if (values.progress_type === 'date') values.mode = 'date';
  else ['target','current','step'].forEach(key => values[key] = Number(values[key]));
  values.weekdays = [...document.querySelectorAll('#weekdays input:checked')].map(input => Number(input.value));
  values.icon = state.editing?.icon || ({blue:'sparkles',purple:'book',green:'plane',orange:'activity',pink:'layers',teal:'sun'})[values.color];
  $('#save-card').disabled = true;
  try {
    await api(state.editing ? `/api/cards/${state.editing.id}` : '/api/cards', state.editing ? 'PUT' : 'POST', values);
    $('#editor').close();
    const complete = values.mode === 'date' ? values.end_date <= state.today : values.current >= values.target;
    toast(complete ? 'Completed. Moved to archive.' : state.editing ? 'Changes saved.' : 'Progress added.');
    await load();
  } catch(error) {$('#form-error').textContent = error.message;}
  finally {$('#save-card').disabled = false;}
});
$('#delete-card').addEventListener('click', () => $('#delete-dialog').showModal());
$('#cancel-delete').addEventListener('click', () => $('#delete-dialog').close());
$('#confirm-delete').addEventListener('click', async () => {
  $('#confirm-delete').disabled = true;
  try {
    await api(`/api/cards/${state.editing.id}`, 'DELETE', {});
    $('#delete-dialog').close(); $('#editor').close();
    toast('Progress card deleted.'); await load();
  } catch(error) {toast(error.message);}
  finally {$('#confirm-delete').disabled = false;}
});
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => {
  const bounds = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
}));
load();
setInterval(() => {if (!document.hidden && !$('#editor').open) load();}, 30000);
document.addEventListener('visibilitychange', () => {if (!document.hidden && !$('#editor').open) load();});

setInterval(() => {if (!document.hidden && state.calendar.length) renderCalendar();}, 1000);
