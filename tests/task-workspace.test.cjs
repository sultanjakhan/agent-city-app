const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const ns='11111111-1111-4111-8111-111111111111';
const fresh=new Date().toISOString();
function workspace(dashboard,sync){
 const context=vm.createContext({window:{},document:{addEventListener(){}},location:{search:''},URLSearchParams,Date,Map,Set,Intl,JSON,t:(s,v={})=>s.replace(/\{(\w+)\}/g,(_,k)=>v[k]),age:value=>(Date.now()-Date.parse(value))/1000});
 const dashboardCode=fs.readFileSync(path.join(root,'static/dashboard.js'),'utf8');
 vm.runInContext(dashboardCode.slice(0,dashboardCode.indexOf('async function loadDashboard(')),context);
 const shared=fs.readFileSync(path.join(root,'static/shared-tasks.js'),'utf8');
 vm.runInContext(shared.slice(0,shared.indexOf('async function loadSharedTasks(')),context);
 context.dashboardFixture=dashboard;context.syncFixture=sync;
 vm.runInContext('dashboardData=dashboardFixture;sharedState=syncFixture;function freshRun(run){return ["running","waiting"].includes(run.status)&&Date.parse(run.updatedAt)<=Date.now()+30000&&age(run.updatedAt)<=300;}',context);
 vm.runInContext(fs.readFileSync(path.join(root,'static/task-workspace.js'),'utf8'),context);
 return {records:()=>JSON.parse(JSON.stringify(context.window.AgentCityTasks.records())),aggregate:runs=>{context.fixtureRuns=runs;return JSON.parse(vm.runInContext('JSON.stringify(aggregateRuns(fixtureRuns))',context));}};
}
function data(tasks=[],runs=[]){return {cicada:{source:{id:'source-1',sourceNamespace:ns},tasks:[],availableTasks:tasks,historyTasks:[]},runs,workRegistry:{publishers:{},bindings:{}}};}
function sync(tasks={}){return {config:{staleAfterSeconds:300},tasks};}
function shared(id,key='cicada-stable-'+id){return {id,version:1,title:'Native shared',binding:{sourceNamespace:ns,sourceId:id,taskKey:key},reports:[],completed:false};}

test('native and shared projections join by namespace and ID while both report keys stay bound',()=>{
 const source={sourceId:'task-1',taskKey:'cicada-legacy-task-1',title:'Native title',version:1,completed:false};
 const task=shared('task-1');task.reports=[{runId:'same-run',sequence:2,status:'running',receivedAt:fresh,report:{inputTokens:20,outputTokens:5,stage:'Check',agent:'Codex'}}];
 const api=workspace(data([source],[{runId:'same-run',sequence:1,taskKey:source.taskKey,inputTokens:10,outputTokens:2,status:'running',stage:'Check',updatedAt:fresh}]),sync({'task-1':task}));
 const records=api.records();assert.equal(records.length,1);assert.equal(records[0].key,task.binding.taskKey);assert.equal(records[0].title,task.title);assert.equal(records[0].runs.length,1);assert.equal(records[0].runs[0].inputTokens,20);assert.equal(records[0].current,true);assert.ok(records[0].aliases.includes(source.taskKey));
 task.binding.sourceNamespace='22222222-2222-4222-8222-222222222222';task.binding.taskKey='cicada-other-task-1';assert.equal(api.records().length,2);
});

test('stale running is never current; awaiting review and active human timer remain current',()=>{
 const stale=shared('stale'),review=shared('review'),timer=shared('timer');
 stale.reports=[{runId:'stale-run',status:'running',receivedAt:new Date(Date.now()-600000).toISOString()}];review.review={state:'awaiting_review',resultVersion:1};timer.humanTimerActive=true;
 const records=workspace(data(),sync({stale,review,timer})).records();assert.equal(records.find(r=>r.sourceId==='stale').current,false);assert.equal(records.find(r=>r.sourceId==='review').current,true);assert.equal(records.find(r=>r.sourceId==='timer').current,true);
});

test('concurrent attempts with equal timestamps keep a task current while any real run is running',()=>{
 const task={sourceId:'task-1',taskKey:'cicada-bound-task-1',title:'Concurrent task',completed:false};
 const runs=['done','done','running'].map((status,index)=>({runId:'attempt-'+index,taskKey:task.taskKey,status,sequence:1,stage:['Research','Implementation','QA'][index],updatedAt:fresh}));
 const api=workspace(data([task],runs),sync()),record=api.records()[0];assert.equal(record.running,true);assert.equal(record.current,true);assert.equal(record.status,'working');
 runs[2].updatedAt=new Date(Date.now()-600000).toISOString();const stale=api.records()[0];assert.equal(stale.running,false);assert.equal(stale.current,false);assert.equal(stale.status,'idle');
});

test('only confirmed registry bindings add project context and reuse native ownership',()=>{
 const task={sourceId:'native-1',taskKey:'cicada-stable-native-1',title:'Cicada owns title',completed:false},binding={sourceNamespace:ns,sourceId:task.sourceId,taskKey:task.taskKey};
 const dashboard=data([task],[{runId:'actual-run',taskKey:task.taskKey,status:'done',sequence:1,updatedAt:fresh}]);
 const published={id:'parent-task',projectId:'project-1',title:'Published observation',status:'done',lastUpdated:fresh,provenance:{reference:'actual-source'},localBinding:binding};
 const snapshot={source:{publisherId:'parent',sourceNamespace:'33333333-3333-4333-8333-333333333333'},publishedAt:fresh,staleAfterSeconds:300,projects:[{id:'project-1',title:'Actual project'}],tasks:[published]};
 dashboard.workRegistry.publishers.parent={snapshot};dashboard.workRegistry.bindings[task.taskKey]={binding,source:{selectedId:'source-1',sourceNamespace:ns}};
 const api=workspace(dashboard,sync()),records=api.records();assert.equal(records.length,1);assert.equal(records[0].project,'Actual project');assert.equal(records[0].title,task.title);assert.equal(records[0].completed,false);assert.equal(records[0].runs.length,1);
 dashboard.workRegistry.bindings[task.taskKey].source.selectedId='another-source';const unpaired=api.records();assert.equal(unpaired.length,2);assert.equal(unpaired.find(r=>r.readOnly).runs.length,0);
});

test('latest cumulative counters are counted once and changing stages have no invented allocation',()=>{
 const api=workspace(data(),sync()),run={runId:'actual-1',sequence:1,inputTokens:10,outputTokens:2,stage:'Analysis',status:'done',updatedAt:fresh,history:[]};
 const report=api.aggregate([run,{...run,sequence:2,inputTokens:30,outputTokens:5,stage:'Check',history:[{stage:'Analysis'},{stage:'Check'}]},{runId:'actual-2',sequence:1,stage:'Check',status:'done',updatedAt:fresh,inputTokens:null,outputTokens:null}]);
 assert.equal(report.overall.count,2);assert.equal(report.overall.input.value,30);assert.equal(report.overall.input.known,1);assert.equal(report.unallocated.length,1);assert.equal(report.stages.length,1);assert.equal(report.stages[0].totals.input.known,0);
});
