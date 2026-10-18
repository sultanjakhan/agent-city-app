const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
// Unit checks of real projection/filter functions; these are not browser acceptance.
function harness(data){
 const nodes=new Map();
 const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',dataset:{},addEventListener(){},replaceChildren(...children){this.children=children;}});return nodes.get(id);};
 const scope={URLSearchParams,location:{search:''},document:{querySelectorAll:()=>[]},$,t:s=>s,
  Option:function(text,value){return {text,value};},age:stamp=>(Date.now()-Date.parse(stamp))/1000};
 vm.createContext(scope);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/dashboard.js'),'utf8'),scope);
 scope.input=data;vm.runInContext('dashboardData=input',scope);return {scope,$};
}
const run=(id,key,status='done',extra={})=>({runId:id,taskKey:key,agent:'codex',model:null,status,updatedAt:new Date().toISOString(),...extra});
const plain=value=>JSON.parse(JSON.stringify(value));

test('done is not native acceptance; missing and unbound identities remain current',()=>{
 const task={taskKey:'cicada-native',title:'Review',completed:false};
 const {scope}=harness({cicada:{tasks:[],historyTasks:[task]},runs:[run('known',task.taskKey),run('missing','cicada-removed'),run('unbound',null)]});
 assert.equal(scope.currentDashboardEntries().length,3);assert.equal(scope.historyEntries().length,0);
 assert.equal(scope.findDashboardTask('run:local:unbound').unbound,true);
});

test('confirmed completion moves to history only after live work stops',()=>{
 const task={taskKey:'cicada-native',completed:true};const report=run('worker',task.taskKey,'running');
 const {scope}=harness({cicada:{tasks:[],historyTasks:[task]},runs:[report]});
 assert.equal(scope.currentDashboardEntries().length,1);assert.equal(scope.historyEntries().length,0);
 report.status='waiting';assert.equal(scope.currentDashboardEntries().length,1);
 report.status='done';assert.equal(scope.currentDashboardEntries().length,0);assert.equal(scope.historyEntries().length,1);
});

test('confirmed source aliases group together and same run IDs across devices stay distinct',()=>{
 const task={taskKey:'canonical',runTaskKeys:['canonical','legacy'],completed:false};
 const {scope}=harness({cicada:{tasks:[task],historyTasks:[]},runs:[run('a','legacy'),run('b','canonical'),run('same',null),run('same',null,'done',{originDevice:'mac'})]});
 const rows=scope.currentDashboardEntries();assert.equal(rows.length,3);
 assert.equal(scope.findDashboardTask('legacy').taskKey,'canonical');assert.equal(scope.findDashboardTask('canonical')._runs?.length||scope.taskRuns(task).length,2);
});

test('project and tag filters intersect and preserve literal sentinel-like values',()=>{
 const task={title:'Literal',projects:['null','alpha'],tags:['project:alpha','tag:review','task-stage-log:ignored@date']};
 const {scope,$}=harness({cicada:{tasks:[task],historyTasks:[]},runs:[]});
 assert.deepEqual(plain(scope.dashboardMetadata(task)),{projects:['null','alpha'],tags:['tag:review']});
 $('dashboard-project').value=JSON.stringify('null');$('dashboard-tag').value=JSON.stringify('tag:review');
 assert.equal(scope.dashboardMatchesMetadata(task),true);
 $('dashboard-tag').value=JSON.stringify('tag:build');assert.equal(scope.dashboardMatchesMetadata(task),false);
 $('dashboard-project').value='null';$('dashboard-tag').value='null';assert.equal(scope.dashboardMatchesMetadata({}),true);
});

test('polling retains a selected project after it disappears and never broadens the filter',()=>{
 const {scope,$}=harness({cicada:{tasks:[],historyTasks:[]},runs:[]});
 $('dashboard-project').value=JSON.stringify('removed');scope.refreshDashboardFilters();
 assert.equal($('dashboard-project').value,JSON.stringify('removed'));
 assert.ok($('dashboard-project').children.some(o=>o.value===JSON.stringify('removed')));
 assert.equal(scope.dashboardMatchesMetadata({projects:['other']}),false);
});

test('search includes exact task/run IDs and tags without borrowing a configured model',()=>{
 const {scope,$}=harness({cicada:{tasks:[],historyTasks:[]},runs:[]});
 const task={sourceId:'native-id',tags:'project:alpha,tag:review'},reports=[run('exact-run',null,'done',{configuredModel:'not-observed'})];
 for(const query of ['native-id','exact-run','alpha','tag:review']){$('dashboard-search').value=query;assert.equal(scope.dashboardMatchesSearch(task,reports),true);}
 $('dashboard-search').value='not-observed';assert.equal(scope.dashboardMatchesSearch(task,reports),false);
});
