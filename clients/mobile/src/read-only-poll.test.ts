import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ReadOnlyPoll} from './read-only-poll';
const drain=()=>new Promise<void>(resolve=>setImmediate(resolve));
function timers(){const jobs=new Map<number,{run:()=>void;delay:number}>();let id=0;return {jobs,schedule:(run:()=>void,delay:number)=>{jobs.set(++id,{run,delay});return id;},cancel:(key:unknown)=>{jobs.delete(key as number);},async fire(){const entry=jobs.entries().next().value!;assert.ok(entry);jobs.delete(entry[0]);entry[1].run();await drain();}};}
test('poll respects retry interval, stops after bounded reads and only explicit refresh opens another budget',async()=>{
 const clock=timers();let reads=0,accepted=0;const states:unknown[]=[];
 const poll=new ReadOnlyPoll({read:async()=>++reads,accept:()=>{accepted++;return 17000;},error:()=>false,limit:3,change:s=>states.push(s),...clock});
 poll.setForeground(true);await clock.fire();assert.equal([...clock.jobs.values()][0].delay,17000);
 await clock.fire();await clock.fire();assert.equal(reads,3);assert.equal(accepted,3);assert.equal(clock.jobs.size,0);
 assert.deepEqual(states.at(-1),{busy:false,stopped:false,exhausted:true});
 poll.setForeground(false);poll.setForeground(true);assert.equal(clock.jobs.size,0);
 poll.refresh();await clock.fire();assert.equal(reads,4);poll.dispose();assert.equal(clock.jobs.size,0);
});
test('background aborts in-flight read; even a transport ignoring abort cannot publish stale ready',async()=>{
 const clock=timers();let signal!:AbortSignal,resolve!:(value:string)=>void,accepted=0;
 const poll=new ReadOnlyPoll({read:s=>{signal=s;return new Promise<string>(r=>{resolve=r;});},accept:()=>{accepted++;return null;},error:()=>false,...clock});
 poll.setForeground(true);await clock.fire();poll.setForeground(false);assert.equal(signal.aborted,true);
 poll.setForeground(true);assert.equal(clock.jobs.size,0);resolve('ready');await drain();assert.equal(accepted,0);assert.equal(clock.jobs.size,1);poll.dispose();
});
test('account unmount/disposal blocks late callbacks and never schedules another read',async()=>{
 const clock=timers();let resolve!:(value:number)=>void,accepted=0,errors=0;
 const poll=new ReadOnlyPoll({read:()=>new Promise<number>(r=>{resolve=r;}),accept:()=>{accepted++;return 3000;},error:()=>{errors++;return false;},...clock});
 poll.setForeground(true);await clock.fire();poll.dispose();resolve(1);await drain();assert.equal(accepted,0);assert.equal(errors,0);assert.equal(clock.jobs.size,0);
});
test('network errors back off and stop after three failures; needs-review/401 stop immediately',async()=>{
 const clock=timers();let reads=0;const poll=new ReadOnlyPoll({read:async()=>{reads++;throw Error('synthetic');},accept:()=>null,error:()=>false,...clock});
 poll.setForeground(true);await clock.fire();assert.equal([...clock.jobs.values()][0].delay,6000);await clock.fire();assert.equal([...clock.jobs.values()][0].delay,12000);await clock.fire();assert.equal(reads,3);assert.equal(clock.jobs.size,0);poll.dispose();
 for(const failed of [true,false]){const t=timers();const p=new ReadOnlyPoll({read:async()=>{if(failed)throw Error('401');return 'needs_review';},accept:()=>null,error:()=>true,...t});p.setForeground(true);await t.fire();assert.equal(t.jobs.size,0);p.dispose();}
});
test('foreground initial read can respect a server registration lease longer than 30 seconds',async()=>{
 const clock=timers();const poll=new ReadOnlyPoll({read:async()=>1,accept:()=>45000,error:()=>true,...clock});poll.setForeground(true,45000);assert.equal([...clock.jobs.values()][0].delay,45000);await clock.fire();assert.equal([...clock.jobs.values()][0].delay,45000);poll.dispose();
});
