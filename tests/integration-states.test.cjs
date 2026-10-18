const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
// Lightweight DOM model: these tests exercise real rendering/handlers, not a browser.
function element(tag,cls='',text=''){
 return {tag,cls,textContent:text,children:[],dataset:{},value:'',listeners:{},
  append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}},
  prepend(n){n.parentElement=this;this.children.unshift(n);},
  replaceChildren(...nodes){this.children=[];this.append(...nodes);},
  setAttribute(k,v){this[k]=v;},addEventListener(k,v){this.listeners[k]=v;}};
}
function harness(){
 const nodes=new Map(),calls=[];
 const $=id=>{if(!nodes.has(id))nodes.set(id,element('div'));return nodes.get(id);};
 const scope={URLSearchParams,location:{search:''},Date,Number,Object,
  document:{querySelectorAll:()=>[],createElement:element},$,el:element,
  t:(s,vars={})=>s.replace(/\{(\w+)\}/g,(_,k)=>vars[k]??''),when:s=>s,
  Option:function(label,value){return {textContent:label,value};},
  setTimeout:()=>1,view:'settings',settingsTab:'connectors',toast:()=>{},
  request:async(url,body)=>{calls.push({url,body});return url==='/api/cloud'?{configured:false}:scope.response;}};
 vm.createContext(scope);
 for(const file of ['dashboard.js','shared-tasks.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static',file),'utf8'),scope);
 return {scope,$,calls};
}
const source=(status='connected',extra={})=>({selectedId:'production',revision:'r1',candidates:[{id:'production',label:'Cicada',path:'synthetic.db'},{id:'dev',label:'DEV',path:'dev.db'}],observation:{status,readAt:'2026-10-18T00:00:00Z',taskCount:1,activeTaskCount:0,...extra}});
const success='2026-10-18T00:00:00Z',clock=Date.parse(success)+1000;
const exchange=extra=>({config:{enabled:true,staleAfterSeconds:300},lastSuccess:null,failure:null,tasks:{},outbox:{},...extra});

test('readable, empty, active, failed and unchecked sources do not imply synchronization',()=>{
 const {scope}=harness();
 assert.match(scope.connectorStatus(source()),/доступна для чтения.*Проверено/);
 assert.match(scope.connectorStatus(source()),/активных таймеров нет/);
 assert.match(scope.connectorStatus(source()),/не подтверждает обмен/);
 assert.match(scope.connectorStatus(source('connected',{taskCount:0})),/задач.*нет/);
 assert.match(scope.connectorStatus(source('connected',{activeTaskCount:2})),/таймеров.*2/);
 assert.match(scope.connectorStatus(source('error')),/Ошибка чтения/);
 assert.match(scope.connectorStatus(source('disconnected')),/не подключён/);
 assert.match(scope.connectorStatus({selectedId:'production'}),/ещё не проверено/);
});

test('refresh preserves unsaved selection and unavailable saved source remains selectable',async()=>{
 const {scope,$}=harness();scope.response=source();await scope.renderConnectors();
 $('cicada-source').value='dev';scope.showConnectorPath();
 assert.match($('cicada-source-message').textContent,/Сохрани выбор/);
 await scope.renderConnectors();assert.equal($('cicada-source').value,'dev');
 const other=harness();other.scope.response={...source('error'),candidates:[]};
 await other.scope.renderConnectors();assert.equal(other.$('cicada-source').value,'production');
 assert.ok(other.$('cicada-source').children.some(n=>n.value==='production'));
 assert.match(other.$('cicada-source-status').textContent,/Ошибка чтения/);
});

test('save uses exact revision and returned read failure instead of promising tasks will appear',async()=>{
 const {scope,$,calls}=harness();scope.response=source();await scope.renderConnectors();
 $('cicada-source').value='dev';scope.response={...source('error'),selectedId:'dev',revision:'r2'};
 await $('save-cicada-source').listeners.click();
 const write=calls.find(c=>c.body);assert.equal(write.url,'/api/connectors/cicada');
 assert.equal(write.body.sourceId,'dev');assert.equal(write.body.revision,'r1');
 assert.match($('cicada-source-message').textContent,/Выбор источника сохранён/);
 assert.match($('cicada-source-status').textContent,/Ошибка чтения/);
});

test('refresh failure replaces previous connected claim without changing source selection',async()=>{
 const {scope,$}=harness();scope.response=source();await scope.renderConnectors();
 scope.request=async()=>{throw Error('synthetic offline');};await scope.renderConnectors();
 assert.match($('cicada-source-status').textContent,/Не удалось проверить/);
 assert.equal($('cicada-source').value,'production');assert.equal($('check-cicada-source').disabled,false);
});

test('exchange distinguishes disabled, never exchanged, empty, stale and unknown age',()=>{
 const {scope}=harness(),status=value=>scope.taskConnectionStatus(value,clock);
 assert.match(status(exchange({config:{enabled:false},lastSuccess:success})),/выключен/);
 assert.match(status(exchange()),/Ожидается первый.*не подтверждает/);
 assert.match(status(exchange({lastSuccess:success})),/Обмен подтверждён.*задач пока нет/);
 assert.match(status(exchange({lastSuccess:success,tasks:{t:{}}})),/данные последнего успешного/);
 assert.match(status(exchange({lastSuccess:'2026-10-17T00:00:00Z'})),/устарели/);
 assert.match(status(exchange({lastSuccess:'invalid'})),/не подтверждено/);
 assert.match(status(exchange({lastSuccess:'2026-10-19T00:00:00Z'})),/не подтверждено/);
});

test('failed and pending/conflicted changes cannot disappear behind old exchange success',()=>{
 const {scope}=harness();
 const status=scope.taskConnectionStatus(exchange({lastSuccess:success,failure:{code:'task_connection_unavailable'},outbox:{a:{state:'pending'},b:{state:'conflict'},c:{state:'rejected'}}}),clock);
 assert.match(status,/Ошибка обмена/);assert.match(status,/подтверждения изменения: 1/);assert.match(status,/требуют проверки: 2/);
 assert.doesNotMatch(status,/Обмен подтверждён/);
 const pending=scope.taskConnectionStatus(exchange({lastSuccess:success,outbox:{a:{state:'pending'}}}),clock);
 assert.match(pending,/подтверждения изменения: 1/);
});

test('cloud profile is waiting, dated report exchange is scoped, and error overrides old success',()=>{
 const {scope}=harness();
 assert.match(scope.cloudStatus({configured:false}),/не подключено/);
 assert.match(scope.cloudStatus({configured:true}),/Ожидается первый/);
 assert.match(scope.cloudStatus({configured:true,lastSync:success}),/Последний успешный обмен отчётами/);
 assert.match(scope.cloudStatus({configured:true,lastSync:success}),/не синхронизация задач/);
 assert.match(scope.cloudStatus({configured:true,lastSync:success,error:'unauthorized'}),/отклонён/);
 assert.doesNotMatch(scope.cloudStatus({configured:true,state:'error',lastSync:success}),/успешный обмен/);
});

test('local-only cloud response hides mutation controls without requiring remoteDevices',async()=>{
 const {scope,$,calls}=harness();scope.request=async url=>{calls.push({url});return {configured:null,state:'paused',error:null,lastSync:null};};
 await scope.loadCloud();assert.match($('cloud-status').textContent,/приостановлена/);
 for(const id of ['sync-cloud','import-cloud','cloud-help'])assert.equal($(id).hidden,true);
 assert.ok(calls.every(c=>c.url==='/api/cloud'));
});
