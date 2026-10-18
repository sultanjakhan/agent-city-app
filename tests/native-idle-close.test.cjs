const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const cs=fs.readFileSync(path.join(__dirname,'../desktop/IdleClosePolicy.cs'),'utf8');
const script=cs.match(/InstallScript = """\n([\s\S]*?)\n    """;/)[1];
// Execute the production native-injected observer; no live WebView claim.
function harness(){
 const listeners={},storage=new Map(),state={dialog:false,guard:false};
 const document={readyState:'complete',addEventListener:(event,fn)=>listeners[event]=fn,querySelector:()=>state.dialog?{}:null};
 const window={dispatchEvent:e=>{if(state.guard)e.preventDefault();},fetch:()=>Promise.resolve('response')};window.top=window;
 const scope={window,document,Event,Promise,localStorage:{getItem:k=>storage.get(k)||null}};
 vm.createContext(scope);vm.runInContext(script,scope);
 return {window,state,storage,listeners,snapshot:()=>JSON.parse(JSON.stringify(window.__agentCityIdleClose.snapshot()))};
}
test('clean idle page is observable without confirmation, while unload guards/durable unsent drafts block',()=>{
 const h=harness();assert.deepEqual(h.snapshot(),{ready:true,dirty:false,unverifiedEdits:false,pendingRequests:0,openDialog:false});
 h.state.guard=true;assert.equal(h.snapshot().dirty,true);h.state.guard=false;
 h.storage.set('agent-city-shared-unsent-v1','{"pending":{"arguments":{"content":"private"}}}');
 const result=h.snapshot();assert.equal(result.dirty,true);assert.doesNotMatch(JSON.stringify(result),/private|content|arguments/);
 h.storage.set('agent-city-shared-unsent-v1','invalid');assert.deepEqual(h.snapshot(),{ready:false});
});
test('observed edits defer conservatively and returning to the initial value clears the observation',()=>{
 const h=harness(),input={type:'text',value:'initial',matches:()=>true};
 h.listeners.focusin({target:input});input.value='draft';h.listeners.input({target:input});
 assert.equal(h.snapshot().unverifiedEdits,true);input.value='initial';assert.equal(h.snapshot().unverifiedEdits,false);
 const unfocused={value:'unknown',matches:()=>true};h.listeners.change({target:unfocused});assert.equal(h.snapshot().unverifiedEdits,true);
});
test('open dialogs and pending requests are reported; completed/rejected fetches settle',async()=>{
 const h=harness();h.state.dialog=true;assert.equal(h.snapshot().openDialog,true);h.state.dialog=false;
 let release;h.window.fetch=undefined;
 // A second isolated observer wraps the actual supplied fetch implementation.
 const listeners={},document={readyState:'complete',addEventListener:(e,f)=>listeners[e]=f,querySelector:()=>null};
 const window={dispatchEvent(){},fetch:()=>new Promise(r=>release=r)};window.top=window;
 vm.runInNewContext(script,{window,document,Event,Promise,localStorage:{getItem:()=>null}});
 const pending=window.fetch('/synthetic');assert.equal(window.__agentCityIdleClose.snapshot().pendingRequests,1);
 release('ok');assert.equal(await pending,'ok');assert.equal(window.__agentCityIdleClose.snapshot().pendingRequests,0);
});
