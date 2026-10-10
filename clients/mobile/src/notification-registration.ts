import {scopeOf, type Connection, type Store} from './core';
import {accountWorkAllowed} from './account-work';
type Receipt={version:1;installation_id:string;credential_id:string};
export const notificationRegistrationKey=(connection:Connection)=>'notification-registration:v1:'+scopeOf({...connection,identity:'daily'})+'|'+connection.session!.credentialId;
/** A random installation ID alone is not evidence of server registration. No push token is stored here. */
export async function rememberNotificationRegistration(store:Pick<Store,'put'>,connection:Connection,installation:string){
 if(!connection.session)return;
 if(!accountWorkAllowed(connection))throw new Error('账户状态已变化，通知登记未保存。');
 await store.put(notificationRegistrationKey(connection),{version:1,installation_id:installation,credential_id:connection.session.credentialId} satisfies Receipt);
}
export async function registeredNotificationInstallation(store:Pick<Store,'get'>,connection:Connection):Promise<string|null>{
 if(!connection.session)return null;
 const value=await store.get<Receipt>(notificationRegistrationKey(connection));
 return value?.version===1&&value.credential_id===connection.session.credentialId&&typeof value.installation_id==='string'&&/^[a-zA-Z0-9_-]{16,100}$/.test(value.installation_id)?value.installation_id:null;
}
export async function clearNotificationRegistration(store:Pick<Store,'put'>,connection:Connection){if(connection.session&&accountWorkAllowed(connection))await store.put(notificationRegistrationKey(connection),null);}
