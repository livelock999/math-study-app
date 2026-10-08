// Browser APIs are mocked. This does not test a real microphone or speech service.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync('flashcard_keyboard/index.html', 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const emitted = [], timers = new Map(), listeners = {}, instances = [];
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
  constructor() { instances.push(this); }
  start() {}
  abort() {}
}
const context = { document: {getElementById: () => root, createElement: tag => new Element(tag),
                             body: {scrollHeight: 400}, addEventListener() {}},
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
old.onresult({results: [[{transcript: '13'}]]});
assert.equal(answers().length, before);
button('🎤 こえで つづける').onclick();
const active = instances[2];
active.onresult({results: [[{transcript: '3'}]]});
active.onend();
assert.equal(answers().length, before + 1);
assert.equal(answers().at(-1).recognized_text, '3');
render('e', 'saved', {correct: true});
const advance = [...timers.values()].find(timer => timer.delay === 700);
button('つぎへ').onclick();
advance.callback();
assert.equal(answers().filter(event => event.token === 'e').length, 1);
render('f', 'question', {voice_enabled: true});
const autoVoice = [...timers.values()].find(timer => timer.delay === 350);
assert.ok(autoVoice);
autoVoice.callback();
assert.equal(instances.length, 4);
instances[3].onerror({error: 'not-allowed'});
assert.equal(answers().at(-1).voice_enabled, false);
render('g', 'question', {voice_enabled: true});
button('こえを とめる').onclick();
assert.equal(answers().at(-1).action, 'voice_off');
assert.equal(answers().at(-1).voice_enabled, false);
console.log('PASS: duplicate submit, timing, unknown speech, stale speech, raw transcript, auto-next, continuous voice, permission error, voice stop');
