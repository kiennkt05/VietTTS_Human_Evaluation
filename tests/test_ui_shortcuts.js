/* Lightweight evaluator interaction checks; no browser or production data. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
assert.ok(script, 'inline app script');
const boot = script.indexOf("document.addEventListener('keydown',handleEvaluatorKey);setupListeners();");
assert.ok(boot > 0, 'boot code');
const main = {innerHTML: ''};
const audio = {paused: true, plays: 0, pauses: 0,
  play() { this.plays++; this.paused = false; return Promise.resolve(); },
  pause() { this.pauses++; this.paused = true; }};
const context = vm.createContext({
  URL, console,
  document: {
    getElementById(id) { return id === 'mainContent' ? main : id === 'sampleAudio' ? audio : id === 'statusDialog' ? {open: false} : null; },
    querySelector() { return {focus() {}}; },
  },
});
vm.runInContext(script.slice(0, boot), context);
vm.runInContext('renderEvaluator=()=>{};scheduleDraft=()=>{};saveDraft=async()=>{};toast=message=>{globalThis.lastToast=message};loadNext=async()=>{globalThis.nextCalls=(globalThis.nextCalls||0)+1}', context);
const app = vm.runInContext('app', context);
const fn = name => vm.runInContext(name, context);
const key = (value, target = {isContentEditable: false, closest: () => null}) => {
  let prevented = false;
  fn('handleEvaluatorKey')({key: value, target, repeat: false, altKey: false, ctrlKey: false, metaKey: false,
    preventDefault() { prevented = true; }});
  return prevented;
};
const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  app.user = {role: 'evaluator', username: 'temporary-test'};
  app.section = 'single';
  app.item = {target_text: 'Văn bản mục tiêu thật', audio_url: '/media/test.wav', style_instruction: 'Nói nhanh, rõ ràng'};
  app.form = fn('defaultForm')();
  assert.match(fn('dockHtml')(), /♫ Audio/);
  assert.match(fn('dockHtml')(), /Văn bản mục tiêu thật/);
  assert.doesNotMatch(fn('dockHtml')(), /Tham chiếu/);
  assert.doesNotMatch(fn('dockHtml')(), /Chỉ dẫn phong cách|Phím tắt/);
  const aside = fn('evaluatorAside')();
  assert.match(aside, /<aside class="card evaluatorAside"/);
  assert.match(aside, /id="stepTabsContainer"/);
  assert.doesNotMatch(aside, /Nói nhanh, rõ ràng|Chỉ dẫn phong cách/);
  assert.match(aside, /Space/);
  assert.match(aside, /Lựa chọn số 1 - số 5/);
  assert.doesNotMatch(aside, /<kbd>1–[35]<\/kbd>/);
  assert.match(html, /grid-template-areas:"dock aside" "stage aside" "footer aside"/);
  assert.match(fn('stageContent')(), /1\. Đọc đúng/);
  assert.doesNotMatch(fn('stageContent')(), /Đủ nội dung mục tiêu/);

  app.step = 1;
  const scoreMarkup = fn('stageContent')();
  assert.equal((fn('evaluatorAside')().match(/data-substep=/g) || []).length, 5, 'substep navigation in side panel');
  assert.doesNotMatch(scoreMarkup, /data-substep=/);
  assert.deepEqual([...scoreMarkup.matchAll(/data-score="pronunciation" data-value="([1-5])"/g)].map(match => match[1]), ['5', '4', '3', '2', '1']);
  const pronunciationLevels = vm.runInContext('CRITERIA.pronunciation.levels', context);
  for (const description of pronunciationLevels) assert.ok(scoreMarkup.includes(description), 'full score description visible');
  app.step = 0;

  assert.equal(key('ArrowRight'), true);
  await tick();
  assert.equal(app.step, 0, 'cannot advance without an accuracy state');
  assert.equal(key('1'), true);
  assert.equal(app.form.text_accuracy, 'no_error');
  assert.equal(key('3'), true);
  assert.equal(app.form.text_accuracy, 'unsure');
  assert.equal(key('2'), true);
  assert.equal(app.form.text_accuracy, 'has_error');
  assert.match(fn('stageContent')(), /a\. Thiếu nội dung/);
  assert.match(fn('stageContent')(), /Thiếu một hoặc nhiều từ/);
  assert.equal(key('a'), true);
  assert.deepEqual([...app.form.error_types], ['omission']);
  for (const letter of ['b', 'c', 'd']) assert.equal(key(letter), true);
  assert.equal(app.form.error_types.length, 4);
  assert.equal(key('b'), true);
  assert.equal(app.form.error_types.length, 3);
  assert.equal(key('ArrowRight'), true);
  await tick();
  assert.equal(app.step, 1);
  assert.equal(app.substep, 0);
  await fn('goToPosition')(6);
  assert.equal(app.step, 1, 'cannot jump past unscored criteria');

  const scoreKeys = ['pronunciation', 'intonation', 'pacing', 'audio_quality', 'naturalness'];
  for (let i = 0; i < scoreKeys.length; i++) {
    assert.equal(app.substep, i);
    assert.match(fn('stageContent')(), new RegExp('data-score="' + scoreKeys[i] + '"'));
    assert.equal(key(String(i + 1)), true);
    assert.equal(app.form[scoreKeys[i]], i + 1);
    if (i < scoreKeys.length - 1) { assert.equal(key('ArrowRight'), true); await tick(); }
  }
  assert.equal(key('Tab'), false, 'Tab retains native focus traversal');
  assert.equal(key(' '), true);
  assert.equal(audio.plays, 1);
  assert.equal(key(' '), true);
  assert.equal(audio.pauses, 1);
  assert.equal(key('1', {isContentEditable: false, closest: () => true}), false, 'typing in a field is untouched');
  assert.equal(key(' ', {isContentEditable: false, closest: () => true}), false, 'Space in a field is untouched');

  assert.equal(key('ArrowRight'), true);
  await tick();
  assert.equal(app.step, 2);
  assert.match(fn('stageContent')(), /1\. Thấp/);
  assert.match(fn('stageContent')(), /2\. Trung bình/);
  assert.match(fn('stageContent')(), /3\. Cao/);
  assert.equal(key('1'), true);
  assert.equal(app.form.confidence, 'low');
  assert.equal(key('2'), true);
  assert.equal(app.form.confidence, 'medium');
  assert.equal(key('3'), true);
  assert.equal(app.form.confidence, 'high');
  assert.equal(key('4'), false, 'only three confidence choices');
  app.form.naturalness = null;
  assert.equal(key('Enter'), false, 'cannot submit with a required score missing');
  app.form.naturalness = 5;
  const statusButton = {isContentEditable: false, closest: selector => selector === 'button' ? {matches: () => false} : null};
  assert.equal(key('Enter', statusButton), false, 'Enter on a status button retains its native action');
  assert.equal(key('ArrowLeft'), true);
  await tick();
  assert.equal(app.step, 1);
  assert.equal(app.substep, 4);
  assert.equal(key('ArrowRight'), true);
  await tick();
  assert.equal(app.step, 2);
  vm.runInContext('api=async()=>{globalThis.submitCalls=(globalThis.submitCalls||0)+1;return {duration_seconds:1}}', context);
  assert.equal(key('Enter'), true);
  assert.equal(key('Enter'), true, 'rapid second Enter is handled');
  await tick();
  assert.equal(context.submitCalls, 1, 'only one submission is sent');
  assert.equal(app.done, true);
  assert.equal(key('ArrowRight'), true);
  await tick();
  assert.equal(context.nextCalls, 1, 'right arrow opens next sample only after submission');

  fn('renderGuide')();
  assert.match(main.innerHTML, /Quy trình ba bước/);
  assert.match(main.innerHTML, /Điều khiển bàn phím/);
  assert.doesNotMatch(main.innerHTML, /Quy trình năm bước/);
  assert.equal((main.innerHTML.match(/<tr><td><strong>[1-5]<\/strong><\/td>/g) || []).length, 25);
  console.log('Evaluator stages, keyboard controls, error guidance and role guide: OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
