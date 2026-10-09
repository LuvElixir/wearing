import type {CloudState} from './cloud-apps-model';

export function onboardingCloudStatus(cloud:Pick<CloudState,'state'|'configured'|'revocation_pending'|'authorization'>):'revoking'|'connected'|'authorizing'|'available'|'unavailable' {
  if(cloud.revocation_pending)return 'revoking';
  if(cloud.state==='connected')return 'connected';
  if(cloud.authorization)return 'authorizing';
  return cloud.configured?'available':'unavailable';
}
