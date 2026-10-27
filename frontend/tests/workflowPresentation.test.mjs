import test from 'node:test';
import assert from 'node:assert/strict';
import { workflowStepDisplayState } from '../src/utils/workflowPresentation.js';

test('shows a cancelled receipt as Cancelled in workflow progress', () => {
  assert.equal(workflowStepDisplayState({
    state: 'failed',
    receipt: { execution_status: 'cancelled' },
  }), 'cancelled');
});

test('keeps genuine failures and completed steps distinct', () => {
  assert.equal(workflowStepDisplayState({ state: 'failed', receipt: { execution_status: 'failed' } }), 'failed');
  assert.equal(workflowStepDisplayState({ state: 'completed', receipt: { execution_status: 'completed' } }), 'completed');
});
