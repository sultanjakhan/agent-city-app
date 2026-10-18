const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const key='cicada-synthetic-shared';
function task(extra={}){return {id:'native-source-id',version:5,title:'Shared navigation',content:'',binding:{taskKey:key},reports:[],results:[],history:[],comments:[],intents:[],...extra};}
// Real registered Enter handler, pending-link routing and shared dialog code.
// Minimal element recording supports assertions; this is not browser acceptance.
function harness(search=''){
 const nodes=new Map(),toasts=[],native=[];
 function node(tag='div',text=''){return {tag,textContent:text,children:[],dataset:{},handlers:{},value:'',open:false,
  append(...items){this.children.push(...items);for(const item of items)if(item?.id)nodes.set(item.id,item);},
  replaceChildren(...items){this.children=items;},setAttribute(){},addEventListener(type,fn){this.handlers[type]=fn;},
  showModal(){this.open=true;},close(){this.open=false;}};}
 const $=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
 const scope={URLSearchParams,URL,Date,location:{search},document:{querySelectorAll:()=>[],createElement:node,body:node(),getElementById:id=>nodes.get(id)},
  $:id=>id==='shared-task-dialog'?nodes.get(id):$(id),el:(tag,cls,text)=>node(tag,text),t:s=>s,toast:s=>toasts.push(s),view:'dashboard'};
 vm.createContext(scope);
 for(const file of ['dashboard.js','shared-tasks.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/'+file),'utf8'),scope);
 scope.input={cicada:{tasks:[],historyTasks:[]},runs:[]};vm.runInContext('dashboardData=input',scope);
 // Leave real routing/dialog logic intact; skip unrelated list rendering.
 scope.renderDashboardRows=()=>scope.finishDashboardRender();scope.refreshTaskWidgetCount=()=>{};
 scope.openDashboardTask=k=>native.push(k);
 function setShared(tasks){scope.snapshot={config:{scopes:['tasks:read'],staleAfterSeconds:300},tasks,outbox:{}};vm.runInContext('sharedState=snapshot',scope);}
 function enter(value){$('dashboard-search').value=value;let prevented=false;$('dashboard-search').handlers.keydown({key:'Enter',preventDefault(){prevented=true;}});return prevented;}
 return {scope,$,nodes,toasts,native,setShared,enter,mode:()=>vm.runInContext('dashboardMode',scope),pending:()=>vm.runInContext('dashboardLinkPending',scope)};
}
test('Enter opens exact confirmed shared key in actual shared dialog, never source/run ID',()=>{
 const h=harness();h.setShared({[task().id]:task()});assert.equal(h.enter(key),true);
 const dialog=h.nodes.get('shared-task-dialog');assert.equal(dialog.open,true);
 assert.ok(dialog.children.some(n=>n.textContent?.includes('native-source-id · '+key+' · версия 5')));
 assert.equal(h.$('dashboard-search').value,'');assert.deepEqual(h.native,[]);assert.deepEqual(h.toasts,[]);
 dialog.close();h.enter('cicada-unknown');assert.equal(dialog.open,false);assert.equal(h.toasts.length,1);
 assert.equal(h.scope.openDashboardKey('native-source-id'),false);assert.equal(h.scope.openDashboardKey('run-only-id'),false);
});
test('exact pending URL waits for delayed shared load and then opens once',async()=>{
 const h=harness('?task='+key);h.scope.finishDashboardRender();assert.equal(h.pending(),key);
 let resolve;h.scope.request=()=>new Promise(r=>{resolve=r;});const loading=h.scope.loadSharedTasks();
 h.scope.finishDashboardRender();assert.equal(h.pending(),key);
 resolve({config:{scopes:['tasks:read']},tasks:{[task().id]:task()},outbox:{}});await loading;
 assert.equal(h.pending(),null);const dialog=h.nodes.get('shared-task-dialog');assert.equal(dialog.open,true);
 dialog.close();h.scope.finishDashboardRender();assert.equal(dialog.open,false);assert.deepEqual(h.native,[]);
});
test('shared link search selects current/history without treating fresh work as completed',()=>{
 for(const [extra,expected] of [[{},'current'],[{completed:true},'history'],[{completed:true,reports:[{receivedAt:new Date().toISOString(),report:{status:'running'}}]},'current']]){
  const h=harness();h.setShared({[task().id]:task(extra)});h.enter('https://example.invalid/?task='+key);assert.equal(h.mode(),expected);
 }
});
test('native alias/report navigation and unknown URL behavior remain intact',()=>{
 const h=harness();h.scope.input={cicada:{tasks:[{taskKey:'cicada-canonical',runTaskKeys:['cicada-canonical','cicada-alias'],completed:false}],historyTasks:[]},runs:[]};vm.runInContext('dashboardData=input',h.scope);
 h.enter('cicada-alias');assert.deepEqual(h.native,['cicada-alias']);assert.equal(h.mode(),'current');
 const unknown=harness('?task=cicada-unknown');unknown.setShared({});unknown.scope.finishDashboardRender();assert.equal(unknown.pending(),'cicada-unknown');assert.deepEqual(unknown.native,[]);assert.equal(unknown.nodes.has('shared-task-dialog'),false);
});
