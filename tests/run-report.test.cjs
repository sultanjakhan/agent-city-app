const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const scope={URLSearchParams,location:{search:''},document:{querySelectorAll:()=>[]},$:()=>({addEventListener(){}}),t:(text,values={})=>text.replace(/\{(\w+)\}/g,(_,key)=>String(values[key])),age:stamp=>(Date.now()-Date.parse(stamp))/1000};
vm.createContext(scope);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/dashboard.js'),'utf8'),scope);
const aggregate=rows=>JSON.parse(JSON.stringify(scope.aggregateRuns(rows)));
const run=(id,stage,input,output,extra={})=>({runId:id,sequence:1,agent:'agent-city',stage,inputTokens:input,outputTokens:output,mcpCalls:[],skills:[],model:'small-model',status:'done',firstReportedAt:'2026-09-27T08:00:00Z',updatedAt:'2026-09-27T08:01:00Z',history:[{stage,reportedAt:'2026-09-27T08:00:00Z'}],...extra});

test('repeated snapshots count latest sequence once, not history or array copies',()=>{
 const a=run('a','Extract',10,5),b={...a,sequence:2,inputTokens:20,outputTokens:7,history:[...a.history,{stage:'Extract',inputTokens:20,outputTokens:7}]};
 const out=aggregate([a,b,b]);assert.equal(out.overall.count,1);assert.equal(out.overall.input.value,20);assert.equal(out.stages[0].totals.output.value,7);
});
test('separate attempts add in their stage; separate stages keep their own counters',()=>{
 const out=aggregate([run('a','Extract',10,5),run('b','Extract',20,7,{status:'error'}),run('c','Review',8,2)]);
 assert.equal(out.overall.input.value,38);assert.equal(out.stages[0].totals.input.value,30);assert.equal(out.stages[1].totals.input.value,8);assert.equal(out.overall.statuses.error,1);
});
test('legacy stage changes retain overall usage without invented per-stage allocation',()=>{
 const out=aggregate([run('a','Verify',265,1368,{history:[{stage:'Infer'},{stage:'Verify'}]})]);
 assert.equal(out.overall.output.value,1368);assert.equal(out.stages.length,0);assert.equal(out.unallocated.length,1);
});
test('unknown is separate from measured zero for usage and MCP',()=>{
 const out=aggregate([run('a','Extract',0,0),run('b','Extract',null,null,{mcpCalls:null})]);
 assert.deepEqual(out.overall.input,{value:0,known:1,total:2});assert.equal(out.overall.mcp.known,1);assert.equal(out.overall.mcp.total,2);
});
test('MCP uses latest counters only and counts each distinct executor',()=>{
 const mcpCalls=[{server:'docs',tool:'read',calls:2}];
 const a=run('a','Tools',null,null,{mcpCalls}),b={...a,sequence:2,mcpCalls:[{server:'docs',tool:'read',calls:3}]};
 const out=aggregate([a,b,run('c','Tools',null,null,{mcpCalls})]);assert.equal(out.overall.mcp.calls[0].calls,5);
});
test('equal IDs from distinct origins remain separate and stage names stay literal',()=>{
 const stage='<img src=x onerror=alert(1)>',out=aggregate([run('a',stage,10,5),run('a',stage,20,7,{originDevice:'mac'})]);
 assert.equal(out.overall.count,2);assert.equal(out.overall.input.value,30);assert.equal(out.stages[0].stage,stage);
});
test('a truncated history cannot claim exact stage allocation',()=>{
 const out=aggregate([run('a','Review',100,20,{history:Array.from({length:30},()=>({stage:'Review',reportedAt:'2026-09-27T08:00:00Z'}))})]);
 assert.equal(out.unallocated.length,1);assert.equal(out.overall.input.value,100);
});

test('token headline distinguishes partial counts, known zero and no counters',()=>{
 const summary=rows=>JSON.parse(JSON.stringify(scope.tokenSummary(aggregate(rows).overall)));
 assert.deepEqual(summary([run('a','Extract',265,1656),run('b','Review',null,null)]),{value:1921,known:true,complete:false});
 assert.deepEqual(summary([run('a','Extract',0,0)]),{value:0,known:true,complete:true});
 assert.deepEqual(summary([run('a','Extract',null,null)]),{value:0,known:false,complete:false});
 assert.equal(summary([]).complete,false);
 assert.equal(scope.reportedCoverage(aggregate([run('a','Extract',265,1656),run('b','Review',null,null)])),1);
});

test('task time requires Cicada timer data and never estimates report timestamps',()=>{
 const result=value=>JSON.parse(JSON.stringify(scope.taskTime(value)));
 assert.deepEqual(result({actualMinutes:0,isActive:true}),{known:true,minutes:0,active:true});
 assert.equal(result({actualMinutes:74}).minutes,74);
 for(const actualMinutes of [null,undefined,-1,1.5,'14'])assert.equal(result({actualMinutes,firstReportedAt:'2026-09-27T08:00:00Z',updatedAt:'2026-09-27T09:00:00Z'}).known,false);
});

test('mixed attempt statuses do not claim the whole stage failed or finished',()=>{
 const state=rows=>JSON.parse(JSON.stringify(scope.groupState(rows)));
 assert.deepEqual(state([{status:'error'},{status:'done'}]),{tone:'error',label:'Неудачных попыток: 1'});
 assert.deepEqual(state([{status:'error'},{status:'running',updatedAt:new Date().toISOString()}]),{tone:'running',label:'Работает · ошибок: 1'});
});

test('stage skills and MCP remain local to each stage, including unresolved skill IDs',()=>{
 const a=run('a','Extract',1,2,{skillIds:['skill-a','skill-missing'],skills:[{id:'skill-a',name:'extract-fields'}],mcpCalls:[{server:'docs',tool:'read',calls:2}]}),b=run('b','Review',3,4,{skillIds:['skill-b'],skills:[{id:'skill-b',name:'qa-check'}],mcpCalls:[]});
 const report=aggregate([a,b]);assert.deepEqual(report.stages[0].totals.skills,['extract-fields','skill-missing']);assert.deepEqual(report.stages[1].totals.skills,['qa-check']);assert.equal(report.stages[0].totals.mcp.calls[0].calls,2);assert.equal(report.stages[1].totals.mcp.calls.length,0);assert.deepEqual(report.overall.skills,['extract-fields','skill-missing','qa-check']);
});
