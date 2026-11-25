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
  app.item = {target_text: 'Văn bản mục tiêu thật', audio_url: '/media/test.wav', style_instruction: ''};
  app.form = fn('defaultForm')();
  assert.match(fn('dockHtml')(), /♫ Audio/);
  assert.match(fn('dockHtml')(), /Văn bản mục tiêu thật/);
  assert.doesNotMatch(fn('dockHtml')(), /Tham chiếu/);
  assert.match(fn('stageContent')(), /1\. Đọc đúng/);
  assert.doesNotMatch(fn('stageContent')(), /Đủ nội dung mục tiêu/);

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
  assert.equal(key('ArrowLeft'), true);
  await tick();
  assert.equal(app.step, 1);
  assert.equal(app.substep, 4);
  app.done = true;
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
