import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveUserDisplayName } from './src/utils/userDisplayName.ts';

test('1. Resolves display name for Pratham user', () => {
  const user = {
    id: '1',
    email: 'pk@gmail.com',
    full_name: 'Pratham',
    role: 'CITIZEN',
    status: 'ACTIVE',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  const name = resolveUserDisplayName(user);
  assert.equal(name, 'Pratham');
});

test('2. Resolves display name for Rahul user', () => {
  const user = {
    id: '2',
    email: 'rahul@nammaclean.local',
    full_name: 'Rahul',
    role: 'CITIZEN',
    status: 'ACTIVE',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  const name = resolveUserDisplayName(user);
  assert.equal(name, 'Rahul');
});

test('3. Falls back to formatted email name when full_name is missing', () => {
  const user = {
    id: '3',
    email: 'ananya.rao@example.com',
    role: 'CITIZEN',
    status: 'ACTIVE',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  const name = resolveUserDisplayName(user);
  assert.equal(name, 'Ananya rao');
});

test('4. Falls back to locality when full_name is missing but locality is present', () => {
  const user = {
    id: '4',
    email: 'citizen_123@example.com',
    locality: 'Yelahanka Satellite Town',
    role: 'CITIZEN',
    status: 'ACTIVE',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  const name = resolveUserDisplayName(user);
  assert.equal(name, 'Yelahanka Satellite Town');
});

test('5. Handles missing profile data and unauthenticated guest gracefully', () => {
  const nameNull = resolveUserDisplayName(null);
  assert.equal(nameNull, null);

  const nameUndefined = resolveUserDisplayName(undefined);
  assert.equal(nameUndefined, null);

  const emptyUser = { id: '', email: '', role: 'CITIZEN', status: 'ACTIVE', created_at: '', updated_at: '' };
  const nameEmpty = resolveUserDisplayName(emptyUser);
  assert.equal(nameEmpty, null);
});
