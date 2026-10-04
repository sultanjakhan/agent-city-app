const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(path.join(__dirname, '../desktop/recovery.js'), 'utf8');
function harness() {
  const requests = [], timers = new Map(); let timerId=0;
  const context=vm.createContext({window:{draft:{text:'Synthetic unsaved draft'}},performance:{timeOrigin:1},AbortController,
    setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),
    fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))});
  const start=vm.runInContext('('+template+')',context);
  return {context,start,requests,timers};
}
const settled=()=>new Promise(resolve=>setImmediate(resolve));
test('start returns synchronous primitive, not a Promise; exactly one bootstrap only',()=>{
  const h=harness();const draft=h.context.window.draft;
  const result=h.start('synthetic-operation','c'.repeat(43));
  assert.equal(typeof result,'string');assert.equal(JSON.stringify(result),'"started"');
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/api/owner-bootstrap');
  assert.equal(h.requests[0].options.method,'POST');assert.equal(h.context.window.draft,draft);
});
test('successful completion is observed as ok without changing draft or retrying',async()=>{
  const h=harness();const draft=h.context.window.draft;h.start('synthetic-operation','c'.repeat(43));
  assert.equal(h.context.window.__agentCityDesktopRecovery.status,'pending');
  h.requests[0].resolve({ok:true});await settled();
  assert.equal(h.context.window.__agentCityDesktopRecovery.status,'ok');assert.equal(h.context.window.draft,draft);
  assert.equal(h.requests.length,1);assert.equal(h.timers.size,0);
});
test('refused/network failures resolve to explicit refusal',async()=>{
  for(const network of [false,true]) {
    const h=harness();h.start('synthetic-operation','c'.repeat(43));
    if(network)h.requests[0].reject(new Error('synthetic'));else h.requests[0].resolve({ok:false});
    await settled();assert.equal(h.context.window.__agentCityDesktopRecovery.status,'refused');assert.equal(h.requests.length,1);
  }
});
test('deadline aborts and late success cannot turn expiry into success',async()=>{
  const h=harness();h.start('synthetic-operation','c'.repeat(43));
  [...h.timers.values()][0]();assert.equal(h.context.window.__agentCityDesktopRecovery.status,'expired');
  assert.equal(h.requests[0].options.signal.aborted,true);
  h.requests[0].resolve({ok:true});await settled();assert.equal(h.context.window.__agentCityDesktopRecovery.status,'expired');
});
test('stale operation cannot complete the replacement marker',async()=>{
  const h=harness();h.start('old-operation','c'.repeat(43));h.start('new-operation','d'.repeat(43));
  assert.equal(h.requests[0].options.signal.aborted,true);h.requests[0].resolve({ok:true});await settled();
  assert.equal(h.context.window.__agentCityDesktopRecovery.operation,'new-operation');
  assert.equal(h.context.window.__agentCityDesktopRecovery.status,'pending');
  h.requests[1].resolve({ok:false});await settled();assert.equal(h.context.window.__agentCityDesktopRecovery.status,'refused');
});
test('document replacement cannot accept a previous document completion',async()=>{
  const h=harness();h.start('synthetic-operation','c'.repeat(43));
  h.context.performance.timeOrigin=2;h.requests[0].resolve({ok:true});await settled();
  assert.equal(h.context.window.__agentCityDesktopRecovery.status,'pending');
  h.context.window={draft:{text:'Replacement document'}};
  assert.equal(h.context.window.__agentCityDesktopRecovery,undefined);
});
