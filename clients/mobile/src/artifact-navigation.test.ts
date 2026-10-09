import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readArtifactNavigation} from './artifact-navigation';
const connection = {endpoint: 'https://pajio.example/', identity: 'daily'};
const payload = {type: 'pajio-open-artifact', identity: 'daily', id: 'art_abcd1234'};
test('only result navigation from the authenticated conversation and current identity is accepted', () => {
  assert.equal(readArtifactNavigation(JSON.stringify(payload), 'https://pajio.example/?identity=daily', connection), payload.id);
  for (const source of ['https://other.example/', 'https://pajio.example/api/artifacts/art_abcd1234/content', 'file:///app', 'https://user@pajio.example/']) assert.equal(readArtifactNavigation(JSON.stringify(payload), source, connection), null);
  for (const patch of [{identity:'other'}, {id:'../../foo'}, {type:'run-tool'}, {command:'delete'}]) assert.equal(readArtifactNavigation(JSON.stringify({...payload,...patch}), connection.endpoint, connection), null);
});
