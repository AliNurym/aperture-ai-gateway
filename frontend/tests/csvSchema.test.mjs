import assert from 'node:assert/strict';
import test from 'node:test';
import { csvHeader, validateCsvMapping } from '../src/utils/csvSchema.js';
import { createBatchPlan } from '../src/utils/workflowPlan.js';

test('real export headers support BOM, quotes and regional delimiters', () => {
  assert.deepEqual(csvHeader('\uFEFF"Department";"Net; revenue"\r\nSales;"1.234,56"', ';'), ['Department', 'Net; revenue']);
  assert.deepEqual(csvHeader('"a""b",amount\nteam,0.1'), ['a"b', 'amount']);
  for (const text of ['category,amount,amount\n', 'category,\n', '"category,amount', '"category"oops,amount\n']) assert.throws(() => csvHeader(text));
});

test('column and numeric policies are bound into every batch in the plan', () => {
  const item = { object_id: 'obj-' + 'ab'.repeat(16), name: 'sales.csv', sha256: 'ab'.repeat(32), size_bytes: 44 };
  const mapping = { category_column: 'Department', amount_column: 'Revenue', delimiter: ';', decimal_separator: ',', thousands_separator: '.', missing_category: 'reject' };
  const plan = createBatchPlan([item], 100000, 60, mapping);
  for (const [key, value] of Object.entries(mapping)) assert.equal(plan.steps[0].parameters[key], value);
  assert.throws(() => validateCsvMapping({ category_column: 'x', amount_column: 'x' }));
  assert.throws(() => validateCsvMapping({ decimal_separator: ',', thousands_separator: ',' }));
});
