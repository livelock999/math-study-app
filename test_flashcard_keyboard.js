// Browser APIs are mocked. This does not test a real microphone or speech service.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync('flashcard_keyboard/index.html', 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const emitted = [], timers = new Map(), listeners = {}, instances = [];
const documentListeners = {};
let nextTimer = 0, clock = 1000;
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.value = ''; this.isConnected = true; }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
  focus() {}
  querySelectorAll(tag) { return this.children.flatMap(c => [ ...(c.tag === tag ? [c] : []), ...c.querySelectorAll(tag) ]); }
}
const root = new Element('root');
const parent = { postMessage: message => emitted.push(message) };
class SpeechRecognition {
  constructor() { instances.push(this); this.starts = this.stops = this.aborts = 0; }
  start() { this.starts++; }
  stop() { this.stops++; }
  abort() { this.aborts++; }
}
const context = { document: {getElementById: () => root, createElement: tag => new Element(tag),
                             visibilityState: 'visible', body: {scrollHeight: 400},
                             addEventListener: (type, callback) => documentListeners[type] = callback},
  window: {parent, SpeechRecognition, focus() {}, addEventListener: (type, callback) => listeners[type] = callback},
  performance: {now: () => clock},
  setTimeout: (callback, delay) => { timers.set(++nextTimer, {callback, delay}); return nextTimer; },
  clearTimeout: id => timers.delete(id) };
vm.runInNewContext(source, context);
function render(token, phase = 'question', extra = {}) {
  listeners.message({source: parent, data: {type: 'streamlit:render', args: {token, phase, question: '9 + 4 = ?', ...extra}}});
}
function button(text) { return root.querySelectorAll('button').find(node => node.textContent === text); }
function answers() { return emitted.filter(m => m.type === 'streamlit:setComponentValue').map(m => m.value); }
function speech(text, isFinal = true) { const result = [{transcript: text}]; result.isFinal = isFinal; return {results: [result], resultIndex: 0}; }
render('a');
const input = root.querySelectorAll('input')[0];
input.value = '13';
clock = 2500;
button('こたえる ↵').onclick();
button('こたえる ↵').onclick();
assert.equal(answers().length, 1);
assert.equal(answers()[0].answer, 13);
assert.equal(answers()[0].input_method, 'keyboard');
assert.equal(answers()[0].response_time_sec, 1.5);
render('b');
button('🎤 こえで つづける').onclick();
instances[0].onend();
assert.equal(answers().at(-1).action, 'recognition_failed');
render('c');
button('🎤 こえで つづける').onclick();
const old = instances[1];
render('d');
const before = answers().length;
old.onresult(speech('13'));
assert.equal(answers().length, before);
button('🎤 こえで つづける').onclick();
const active = instances[2];
active.onresult(speech('3'));
active.onend();
assert.equal(answers().length, before + 1);
assert.equal(answers().at(-1).recognized_text, '3');
render('e', 'saved', {correct: true});
const advance = [...timers.values()].find(timer => timer.delay === 700);
button('つぎへ').onclick();
advance.callback();
assert.equal(answers().filter(event => event.token === 'e').length, 1);
render('f', 'question', {voice_enabled: true});
const autoVoice = [...timers.values()].find(timer => timer.delay === 0);
assert.ok(autoVoice);
autoVoice.callback();
assert.equal(instances.length, 4);
instances[3].onerror({error: 'not-allowed'});
assert.equal(answers().at(-1).voice_enabled, false);
render('g', 'question', {voice_enabled: true});
button('こえを とめる').onclick();
assert.equal(answers().at(-1).action, 'voice_off');
assert.equal(answers().at(-1).voice_enabled, false);

render('h', 'question', {voice_enabled: true, previous_correct: true});
assert.ok(root.querySelectorAll('p').some(node => node.textContent === '○ まえのカード せいかい'));
assert.equal([...timers.values()].some(timer => timer.delay === 350 || timer.delay === 700), false);
[...timers.values()].find(timer => timer.delay === 0).callback();
const streaming = instances.at(-1), count = answers().length;
assert.equal(streaming.interimResults, true);
streaming.onaudiostart();
assert.ok(button('きいているよ…'));
streaming.onresult(speech('3', false));
assert.equal(answers().length, count); // A partial 13 can start as 3: never grade it.
assert.ok(root.querySelectorAll('p').some(node => node.textContent === '「3」…'));
streaming.onspeechend(); streaming.onspeechend();
assert.equal(streaming.stops, 1);
assert.equal(answers().length, count); // stop requests a final result, not an answer.
clock += 250;
streaming.onresult(speech('13'));
streaming.onresult(speech('13'));
streaming.onend();
assert.equal(answers().length, count + 1);
assert.equal(answers().at(-1).recognized_text, '13');
assert.equal(answers().at(-1).response_time_sec, 0.25);
assert.ok(root.querySelectorAll('p').some(node => node.textContent === '「13」 を たしかめているよ…'));

render('i'); button('🎤 こえで つづける').onclick();
const unfinished = instances.at(-1), beforeUnfinished = answers().length;
unfinished.onresult(speech('13', false)); unfinished.onend();
assert.equal(answers().length, beforeUnfinished + 1);
assert.equal(answers().at(-1).action, 'recognition_failed');

render('j'); button('🎤 こえで つづける').onclick();
const interrupted = instances.at(-1);
interrupted.onresult(speech('3', false));
root.querySelectorAll('input')[0].value = '13'; button('こたえる ↵').onclick();
const afterManual = answers().length;
interrupted.onresult(speech('3')); interrupted.onspeechend();
assert.equal(answers().length, afterManual);
assert.equal(answers().at(-1).input_method, 'keyboard');

render('k', 'question', {voice_enabled: true});
const queued = [...timers.values()].find(timer => timer.delay === 0), beforeHidden = instances.length;
context.document.visibilityState = 'hidden'; documentListeners.visibilitychange(); queued.callback();
assert.equal(instances.length, beforeHidden);
assert.equal(answers().at(-1).action, 'voice_off');
assert.equal(answers().at(-1).voice_enabled, false);
console.log('PASS: duplicate submit, timing, unknown speech, stale speech, raw transcript, auto-next, immediate voice restart, permission error, voice stop, live interim display, final-only grading, speech-end finalization, incomplete speech, manual fallback, hidden-page cancellation');
