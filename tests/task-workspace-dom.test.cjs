const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');

function workspace(){
 const dom=new JSDOM('<div id="tasks-workspace"></div>',{url:'http://localhost/',runScripts:'outside-only'}),w=dom.window;
 const ns='11111111-1111-4111-8111-111111111111',task={id:'task-1',version:3,title:'Shared task',content:'Description',stage:'',process:'',completed:false,reports:[],results:[],comments:[],review:null,binding:{sourceNamespace:ns,sourceId:'task-1',taskKey:'cicada-task-1'}};
 const fixture={config:{enabled:true,transport:'http',endpoint:'http://localhost/commands',sourceNamespace:ns,scopes:['tasks:read','tasks:write'],staleAfterSeconds:300},tasks:{[task.id]:task},outbox:{}},sent=[];
 Object.assign(w,{t:(s,v={})=>s.replace(/\{(\w+)\}/g,(_,k)=>v[k]),$:id=>w.document.getElementById(id),age:value=>(Date.now()-Date.parse(value))/1000,when:value=>value||'',toast(){},setView(){},scheduleDashboard(){},scrollTo(){},renderDashboardRows:()=>w.AgentCityTasks.render(),request:async(url,body)=>{
  if(url==='/api/task-sync/queue'){sent.push(body);if(body.arguments.patch?.status){task.completed=body.arguments.patch.status==='done';task.version++;}return {state:'pending'};}
  if(url==='/api/task-sync'||url==='/api/task-sync/exchange')return JSON.parse(JSON.stringify(fixture));
  throw Error('Unexpected request: '+url);
 },el:(tag,cls='',text='')=>{const node=w.document.createElement(tag);node.className=cls;node.textContent=text;return node;}});
 const run=code=>vm.runInContext(code,dom.getInternalVMContext()),dashboard=fs.readFileSync(path.join(root,'static/dashboard.js'),'utf8');
 run(dashboard.slice(0,dashboard.indexOf('async function loadDashboard(')));
 run(dashboard.slice(dashboard.indexOf('function freshRun('),dashboard.indexOf('function stageName(')));
 run(fs.readFileSync(path.join(root,'static/shared-tasks.js'),'utf8'));
 w.fixture=JSON.parse(JSON.stringify(fixture));
 run('var view="tasks";dashboardData={cicada:{tasks:[],availableTasks:[],historyTasks:[]},runs:[]};sharedState=fixture;');
 run(fs.readFileSync(path.join(root,'static/task-workspace.js'),'utf8'));
 w.AgentCityTasks.openShared(task.id);
 return {dom,w,fixture,task,sent,settle:()=>new Promise(resolve=>setImmediate(resolve)),refresh:()=>w.loadSharedTasks(),buttons:()=>[...w.document.querySelectorAll('button')],button:label=>[...w.document.querySelectorAll('button')].find(node=>node.textContent===label)};
}

test('completion and reopening use the latest confirmed task status while the screen stays open',async()=>{
 const app=workspace();try{
  app.button('Завершить задачу').click();await app.settle();
  assert.equal(app.sent[0].arguments.patch.status,'done');
  assert.ok(app.button('Вернуть в текущие'),'confirmed completion must expose reopening without closing the task');
  app.button('Вернуть в текущие').click();await app.settle();
  assert.equal(app.sent[1].arguments.patch.status,'task');assert.equal(app.sent[1].arguments.expectedVersion,4);
 }finally{app.dom.window.close();}
});

test('polling updates write controls for timer, scope and review changes while preserving local fields',async()=>{
 const app=workspace();try{
  const title=app.w.document.querySelector('[data-draft-field="title"]');title.value='Unsaved local title';
  app.task.humanTimerActive=true;await app.refresh();assert.equal(app.button('Завершить задачу').disabled,true);
  app.fixture.config.scopes=['tasks:read'];await app.refresh();
  assert.equal(app.button('Сохранить изменения').disabled,true);assert.equal(app.button('Добавить комментарий').disabled,true);assert.equal(title.value,'Unsaved local title');
  app.fixture.config.scopes=['tasks:read','tasks:write'];app.task.humanTimerActive=false;app.task.review={state:'awaiting_review',resultVersion:1};await app.refresh();
  assert.equal(app.button('Сохранить изменения').disabled,false);assert.equal(app.button('Завершить задачу').hidden,true);assert.equal(title.value,'Unsaved local title');
 }finally{app.dom.window.close();}
});
