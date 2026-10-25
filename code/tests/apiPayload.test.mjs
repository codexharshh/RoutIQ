import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeApiPayload } from '../src/services/apiPayload.ts';

test('normalizes a Django list response without discarding saved observations', () => {
  const observations = [{ id: 11 }, { id: 12 }];
  assert.deepEqual(normalizeApiPayload(observations, JSON.stringify(observations)), {
    results: observations,
  });
});
