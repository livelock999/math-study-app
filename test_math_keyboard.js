// DOM mocks verify custom number entry; real device keyboards need device testing.
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const source = fs.readFileSync('keyboard/index.html', 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
let root, document, clock = 1000;
const sent = [], windowEvents = {}, documentEvents = {}, timers = new Map();
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.events = {};
    this.attributes = {}; this.isConnected = true; this._value = ''; this.className = '';
    this.classList = {add: (...names) => this.className += ' ' + names.join(' '),
      toggle: (name, on) => { const names = this.className.split(/\s+/).filter(n => n && n !== name); if (on) names.push(name); this.className = names.join(' '); }}; }
  get value() { return this._value; }
  set value(value) { this._value = String(value); this.selectionStart = this.selectionEnd = this._value.length; }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; this.textContent = ''; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
  focus() { document.activeElement = this; this.events.focus?.(); }
  click() { this.focus(); this.onclick?.(); }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  querySelectorAll(selector) { return this.children.flatMap(child => [
    ...(selector[0] === '.' ? child.className.split(/\s+/).includes(selector.slice(1)) ? [child] : []
      : child.tagName === selector.toUpperCase() ? [child] : []), ...child.querySelectorAll(selector)]); }
}
root = new Element('div');
document = {activeElement: null, body: {scrollHeight: 700}, createElement: tag => new Element(tag),
  createTextNode: text => {const e = new Element('text'); e.textContent = text; return e;},
  getElementById: id => id === 'root' ? root : root.querySelectorAll('input').find(e => e.id === id),
  addEventListener: (name, callback) => documentEvents[name] = callback};
const parent = {postMessage: value => sent.push(value)};
vm.runInNewContext(source, {document, window: {parent, focus() {}, addEventListener: (name, callback) => windowEvents[name] = callback},
  performance: {now: () => clock}, setTimeout: callback => {const id = timers.size + 1; timers.set(id, callback); return id;}, clearTimeout: id => timers.delete(id)});
function text(e) { return (e.textContent || '') + e.children.map(text).join(''); }
function button(name) { const e = root.querySelectorAll('button').find(e => text(e) === name); assert.ok(e, name); return e; }
function input(id = 'answer') { return document.getElementById(id); }
function render(token, phase = 'question', extra = {}) {
  windowEvents.message({source: parent, data: {type: 'streamlit:render', args: {token, question_id: token, phase, question: '8 + 5 = ?', ...extra}}});
}
function last() { return sent.filter(m => m.type === 'streamlit:setComponentValue').at(-1)?.value; }
function key(value, extra = {}) { const e = {key: value, preventDefault() {this.prevented = true;}, ...extra}; documentEvents.keydown(e); return e; }
render('touch');
assert.equal(input().readOnly, true); assert.equal(input().inputMode, 'none');
button('1').click(); button('3').click(); assert.equal(input().value, '13');
button('けす').click(); button('2').click(); assert.equal(input().value, '12');
button('こたえる').click(); assert.equal(last().answer, 12); assert.equal(last().action, 'answer');
const submitted = sent.length; button('3').click(); assert.equal(input().value, '12'); assert.equal(sent.length, submitted);

render('hardware'); input().focus(); key('１'); key('3'); key('4'); key('5'); assert.equal(input().value, '134');
input().setSelectionRange(0, 3); key('8'); assert.equal(input().value, '8');
key('Backspace'); assert.equal(input().value, ''); key('Enter'); assert.notEqual(last().token, 'hardware');
key('2'); key('Enter'); assert.equal(last().answer, 2);
render('guard'); input().focus(); key('1', {isComposing: true}); key('2', {ctrlKey: true}); assert.equal(input().value, '');

render('equation2', 'equation', {word_problem: true, draft: {equation_left: '8'}});
assert.equal(input('equation_left').value, '8'); assert.equal(input('equation_left').readOnly, true);
button('つぎの かず').click(); button('5').click(); button('しきを きめる').click();
assert.equal(last().action, 'submit_equation'); assert.equal(last().equation_left, 8); assert.equal(last().equation_right, 5);

render('equation3', 'equation', {word_problem: true, three_word_problem: true});
button('2').click(); button('つぎの かず').click(); button('3').click(); button('つぎの かず').click(); button('4').click();
input('equation_left').focus(); button('けす').click(); button('5').click();
assert.equal(input('equation_left').value, '5'); assert.equal(input('equation_right').value, '3'); assert.equal(input('equation_third').value, '4');
assert.ok(input('equation_left').className.includes('keypad-target'));
input('equation_third').focus(); button('しきを きめる').click(); assert.equal(last().equation_third, 4);

render('draft', 'question', {draft: {answer: '19'}, hint_text: 'ヒント', hint_level: 0});
button('ヒントを みる').click(); assert.equal(last().draft.answer, '19');
render('resumed', 'question', {draft: {answer: '19'}}); assert.equal(input().value, '19');
assert.equal(input().inputMode, 'none'); assert.equal(input().readOnly, true);
render('feedback', 'feedback', {correct: true, answer: 19});
assert.equal(root.querySelectorAll('input').length, 0); button('つぎへ ↵').click(); assert.equal(last().action, 'next');
console.log('PASS: keypad-only fields, digits/delete/limits, hardware keys, selection replacement, no duplicate answer, empty validation, IME/modifier guards, two/three-number equations, active field, draft preservation, feedback navigation');
