import assert from 'node:assert/strict';
import test from 'node:test';
import type {CloudState} from './cloud-apps-model';
import {onboardingCloudStatus} from './onboarding-connection-state';

const authorization={id:'request',url:'https://accounts.feishu.cn/device',user_code:'TEST',expires_at:1800000000,interval:5};

test('pending revocation overrides both a stale connection and an outstanding authorization',()=>{
  const states:CloudState['state'][]=['not_configured','configured','authorizing','authorization_expired','connected','expired'];
  for(const state of states)for(const pending of [null,authorization]){
    assert.equal(onboardingCloudStatus({state,configured:true,revocation_pending:true,authorization:pending}),'revoking');
  }
});

test('connection success requires connected state and completed revocation',()=>{
  assert.equal(onboardingCloudStatus({state:'connected',configured:true,revocation_pending:false,authorization:null}),'connected');
  assert.equal(onboardingCloudStatus({state:'expired',configured:true,revocation_pending:false,authorization:null}),'available');
  assert.equal(onboardingCloudStatus({state:'authorizing',configured:true,revocation_pending:false,authorization}),'authorizing');
  assert.equal(onboardingCloudStatus({state:'not_configured',configured:false,revocation_pending:false,authorization:null}),'unavailable');
});
