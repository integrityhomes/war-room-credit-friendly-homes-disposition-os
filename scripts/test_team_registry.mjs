// Node 24 can execute the actual TypeScript handler with fully isolated transports.
// No credentials, production files, database, HTTP, or deployment are used.
import assert from 'node:assert/strict';
let handler;
const objects = new Map();
globalThis.Deno = {
  env: { get: name => ({ SUPABASE_SERVICE_ROLE_KEY: 'fictional-key', SUPABASE_URL: 'https://example.invalid' })[name] },
  serve: fn => { handler = fn; },
};
globalThis.fetch = async (url, options = {}) => {
  const path = new URL(url).pathname;
  assert.equal(new URL(url).hostname, 'example.invalid');
  if (path === '/storage/v1/bucket') return Response.json([{ name: 'commandcore-team-registry' }]);
  if (path === '/storage/v1/object/list/commandcore-team-registry') {
    return Response.json([...objects.keys()].map(name => ({ name })));
  }
  const name = decodeURIComponent(path.split('/').at(-1));
  if (path.startsWith('/storage/v1/object/authenticated/commandcore-team-registry/members/')) {
    return Response.json(objects.get(name));
  }
  if (path.startsWith('/storage/v1/object/commandcore-team-registry/members/') && options.method === 'POST') {
    objects.set(name, JSON.parse(options.body));
    return Response.json({ ok: true });
  }
  throw new Error('Unexpected transport path');
};
await import('../supabase/functions/commandcore-team-registry/index.ts');
const call = async (member, key = 'fictional-key') => handler(new Request('https://example.invalid', {
  method: 'POST', headers: { authorization: `Bearer ${key}` }, body: JSON.stringify({ action: 'upsert', member }),
}));
const profile = { title: 'Synthetic coordinator', questionnaire: 'Complete synthetic source evidence', source: { hash: 'fictional' }, owner_approval_authority: false };
assert.equal((await (await handler(new Request('https://example.invalid'))).json()).profile_preservation_enabled, true);
assert.equal((await call({ id: 'example', name: 'Example Worker', roles: ['operator'], profile })).status, 200);
await call({ id: 'example', availability: 'away', current_load: 2 });
assert.deepEqual(objects.get('example.json').profile, profile);
assert.deepEqual(objects.get('example.json').roles, ['operator']);
await call({ id: 'example', profile: { title: 'Updated synthetic title' } });
assert.equal(objects.get('example.json').profile.questionnaire, profile.questionnaire);
assert.equal((await call({ id: 'example', profile: null })).status, 422);
const before = JSON.stringify([...objects]);
assert.equal((await call({ id: 'unauthorized' }, 'wrong')).status, 401);
assert.equal(JSON.stringify([...objects]), before);
console.log('Team registry handler: preservation, partial updates, invalid profile and authentication checks passed; zero external requests.');
