import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { previewResult } from '../src/utils/resultPreview.js';

function preview(name, text) {
  const bytes = new TextEncoder().encode(text);
  return previewResult({ name, size_bytes: bytes.byteLength }, bytes);
}

test('CSV handles BOM, CRLF, escaped quotes and multiline fields', () => {
  const result = preview('report.csv', '\uFEFFcategory,note\r\n"tools, cloud","a ""quoted"" note"\r\nservices,"two\r\nlines"\r\n');
  assert.equal(result.type, 'table');
  assert.deepEqual(result.columns, ['category', 'note']);
  assert.deepEqual(result.rows, [['tools, cloud', 'a "quoted" note'], ['services', 'two\r\nlines']]);
  assert.equal(result.count, 2);
});

test('CSV blank lines do not prevent a table preview', () => {
  const result = preview('report.csv', '\ncategory,amount\n\nservices,2.5\n\nnetwork,3\n\n');
  assert.equal(result.type, 'table');
  assert.deepEqual(result.rows, [['services', '2.5'], ['network', '3']]);
  assert.equal(result.count, 2);
});

test('CSV preserves quoted empty records and trailing empty fields', () => {
  const one = preview('single.csv', 'value\n""\n');
  assert.equal(one.type, 'table');
  assert.deepEqual(one.rows, [['']]);
  const two = preview('report.csv', 'category,amount\nservices,');
  assert.deepEqual(two.rows, [['services', '']]);
});

test('CSV preview limits visible rows while reporting the complete record count', () => {
  const result = preview('large.csv', 'id,amount\n' + Array.from({ length: 150 }, (_, index) => `${index},1\n`).join(''));
  assert.equal(result.rows.length, 100);
  assert.equal(result.count, 150);
  assert.deepEqual(result.rows.at(-1), ['99', '1']);
});

test('CSV with unfinished quotes falls back to its original text', () => {
  const text = 'category,amount\n"unfinished,1';
  const result = preview('report.csv', text);
  assert.equal(result.type, 'text');
  assert.equal(result.text, text);
  assert.match(result.note, /unfinished quoted field/);
});

test('JSON category reports display counters, totals and averages', () => {
  const result = preview('report.json', JSON.stringify({ valid_rows: 3, invalid_rows: 1,
    groups: { services: { rows: 2, total: 6 }, network: { rows: 1, total: -1.5 } } }));
  assert.equal(result.type, 'report');
  assert.deepEqual(result.metrics, [['Accepted rows', 3], ['Skipped rows', 1], ['Categories', 2]]);
  assert.deepEqual(result.rows, [['services', '2', '6', '3'], ['network', '1', '-1.5', '-1.5']]);
});

test('JSON with no accepted rows still displays a useful empty report', () => {
  const result = preview('report.json', '{"valid_rows":0,"invalid_rows":2,"groups":{}}');
  assert.equal(result.type, 'report');
  assert.deepEqual(result.rows, []);
  assert.equal(result.count, 0);
});

test('JSON record tables align optional columns and preserve nested values', () => {
  const result = preview('rows.json', '[{"category":"services","detail":{"ok":true}},{"amount":3}]');
  assert.deepEqual(result.columns, ['category', 'detail', 'amount']);
  assert.deepEqual(result.rows, [['services', '{"ok":true}', ''], ['', '', '3']]);
});

test('saved SDK demonstration JSON and CSV can be read by the frontend preview', async () => {
  for (const name of ['report.json', 'categories.csv']) {
    const bytes = await readFile(new URL('./fixtures/' + name, import.meta.url));
    const result = previewResult({ name, size_bytes: bytes.byteLength }, bytes);
    assert.ok(['report', 'table'].includes(result.type));
    assert.equal(result.count, 4);
    if (name.endsWith('.json')) {
      assert.deepEqual(result.metrics, [['Accepted rows', 11988], ['Skipped rows', 12], ['Categories', 4]]);
    } else {
      assert.ok(result.columns.includes('minimum'));
      assert.ok(result.columns.includes('maximum'));
    }
  }
});
