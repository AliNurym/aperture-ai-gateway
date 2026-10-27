import test from 'node:test';
import assert from 'node:assert/strict';
import { inspectRestoredSource, parseSentinelDraft, RESTORED_SOURCE_PLACEHOLDER, sourceIsAvailable } from '../src/utils/restoredSource.js';
import { sha256Hex } from '../src/utils/protocol.js';

test('restored source is matched against the saved quote hash', async () => {
  const source = 'print(6 * 7)\n';
  assert.equal(await inspectRestoredSource(source, await sha256Hex(source)), 'match');
  assert.equal(await inspectRestoredSource(source, await sha256Hex('print(7 * 7)\n')), 'different');
});

test('missing source and invalid saved hashes never claim a match', async () => {
  assert.equal(sourceIsAvailable(RESTORED_SOURCE_PLACEHOLDER), false);
  assert.equal(sourceIsAvailable(''), false);
  assert.equal(sourceIsAvailable('print(6 * 7)\n'), true);
  assert.equal(await inspectRestoredSource(RESTORED_SOURCE_PLACEHOLDER, 'ab'.repeat(32)), 'missing');
  assert.equal(await inspectRestoredSource('', 'ab'.repeat(32)), 'missing');
  assert.equal(await inspectRestoredSource('print(6 * 7)\n', 'not-a-hash'), 'unknown');
});

test('saved Sentinel drafts with recovery placeholders or malformed data are rejected', () => {
  assert.equal(parseSentinelDraft(null), null);
  assert.equal(parseSentinelDraft('{bad json'), null);
  assert.equal(parseSentinelDraft(JSON.stringify({ id: 'qa', source: RESTORED_SOURCE_PLACEHOLDER, prompt: 'review' })), null);
  assert.equal(parseSentinelDraft(JSON.stringify({ id: 'qa', source: 'print(6 * 7)\n' })), null);
  assert.deepEqual(parseSentinelDraft(JSON.stringify({ id: 'qa', source: 'print(6 * 7)\n', prompt: 'review' })), {
    id: 'qa', source: 'print(6 * 7)\n', prompt: 'review',
  });
});
