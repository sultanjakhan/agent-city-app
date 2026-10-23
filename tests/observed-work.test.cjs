const {test}=require('node:test'),assert=require('node:assert/strict');
const V=require('../static/observed-work.js'),F=require('../static/observed-feed.js');
const session=(id,extra={})=>({id,projectId:'project-a',agentId:'agent-a',name:'Наблюдение '+id,scope:{kind:'session',id},status:'working',coverage:'partial',usage:{input:3,output:null,total:null},appliedSkills:null,...extra});
const feed=(sessions,extra={})=>({source:{status:'fresh',readAt:'2026-01-01T10:00:00Z'},projects:[{id:'project-a',name:'Проект А'},{id:'project-b',name:'Проект Б'}],agents:[{id:'agent-a',projectId:'project-a',name:'Координатор'},{id:'agent-b',projectId:'project-a',name:'Исполнитель'}],sessions,edges:[],...extra});
module.exports={session,feed};
test('Home is observed current work; History one row per returned observation; no native task lifecycle mutation',()=>{
 const data=feed([session('working'),session('ended',{status:'completed',turns:[{id:'one',status:'completed'},{id:'two',status:'completed'}],task:{title:'Исходная задача',completed:false}}),session('interrupted',{status:'interrupted'}),session('unknown',{status:'unknown'})]);
 const before=JSON.stringify(data),m=V.createModel().update(data);
 assert.deepEqual(m.rows().map(s=>s.id),['working']);assert.deepEqual(m.rows('history').map(s=>s.id),['ended','interrupted']);assert.equal(JSON.stringify(data),before);
 m.navigate({page:'projects',projectId:'project-a'});assert.deepEqual(m.rows().map(s=>s.id),['working','unknown']);
});
test('silence/source failure never implies waiting/completion and does not clear selected execution',()=>{
 const m=V.createModel({page:'home',sessionId:'selected'}).update(feed([session('selected')]));
 m.update(feed([session('selected',{status:'completed'})],{source:{status:'unavailable',originalStatus:'unavailable'}}));
 assert.equal(m.route.sessionId,'selected');assert.equal(m.selected.status,'completed');assert.equal(m.rows().length,0);assert.equal(m.rows('history').length,1);
 m.update(feed([]));assert.equal(m.route.sessionId,'selected');assert.equal(m.selected,null);
});
test('updates are atomic on malformed scope/duplicate IDs, stable order does not follow reordered input',()=>{
 const m=V.createModel().update(feed([session('a'),session('b')]));m.update(feed([session('b'),session('a')]));assert.deepEqual(m.rows().map(s=>s.id),['a','b']);
 assert.throws(()=>m.update(feed([session('x'),session('x')])));assert.throws(()=>m.update(feed([session('x',{scope:null})])));assert.deepEqual(m.rows().map(s=>s.id),['a','b']);
});
test('exact route hooks round trip opaque identities without inventing task links',()=>{
 const r={page:'history',projectId:'project:/opaque ?#',agentId:null,sessionId:'session:opaque'};assert.deepEqual(V.parseRoute(V.formatRoute(r)),r);
});
test('unknown measurements remain null, zero is known, subsets are never added, no historical/model fallback',()=>{
 const s=V.normalize(feed([session('s',{usage:{input:10,output:2,total:null,cachedInput:8,reasoningOutput:1},tokens:999999,threadModel:'old'})])).sessions[0];
 assert.equal(s.usage.total,null);assert.equal(s.usage.input,10);assert.equal(s.model,null);assert.equal(V.number(0),'0');
 assert.equal(V.timing({...s,status:'completed',startedAt:'2026-01-01T10:00:00Z',endedAt:'2026-01-01T10:01:00Z'},Date.now()).value,null);
 assert.match(V.timing({...s,startedAt:'2026-01-01T10:00:00Z'},Date.parse('2026-01-01T10:01:00Z')).note,/не завершённая/);
});
test('Projects uses explicit same-project recorded edges and current session counts, never persistent inferred agents',()=>{
 const m=V.createModel().update(feed([session('a'),session('b',{agentId:'agent-b'})],{edges:[{id:'edge',projectId:'project-a',fromAgentId:'agent-a',toAgentId:'agent-b'},{id:'unrelated',projectId:'project-b',fromAgentId:'agent-a',toAgentId:'agent-b'}]}));
 assert.equal(m.projectEdges('project-a').length,1);assert.equal(m.projectAgents('project-a')[0].currentCount,1);
 m.update(feed([session('a',{status:'completed'})]));assert.equal(m.projectAgents('project-a').length,0);assert.equal(m.projectEdges('project-a').length,0);
});
function raw(){return {source:{status:'partial',message:'Synthetic coverage',lastReadAt:'2026-01-01T10:00:00Z'},projects:[{id:'project-a'}],agents:[{id:'agent-a',projectId:'project-a'}],sessions:[{id:'s',projectId:'project-a',agentId:'agent-a',status:'completed',name:'Исходная задача',usage:{total:99999},model:'thread-model',skills:['read-only-skill'],stages:[{id:'turn-a',name:'Ход 1',status:'completed',usage:{input:5,output:2,total:7},events:[{id:'read',at:null,kind:'skill-read',skill:'read-only-skill'},{id:'apply',kind:'skill-applied',skill:'skill-exact-id',source:'executor-reported'}]}]}]};}
test('feed retains session scope and one History row, never converts raw skills/turns into task attempts',()=>{
 const data=raw(),result=F.fromSnapshot(data),s=result.sessions[0];assert.equal(s.scope.kind,'session');assert.equal(s.usage.total,99999);assert.equal(s.appliedSkills,null);assert.equal(s.task,null);assert.equal(s.turns.length,0);
 assert.equal(V.createModel({page:'history'}).update(result).rows().length,1);assert.equal(result.source.status,'partial');
 data.sessions[0].stages.push({id:'turn-b',name:'Ход 2',status:'completed'});assert.equal(F.fromSnapshot(data).sessions[0].turns.length,2);
});
test('bound row replaces raw scope with exact turn, application evidence requires source guard and explicit event',()=>{
 const data=raw(),row=data.sessions[0];row.attemptBinding={kind:'owner-approved-exact-turn',turnId:'turn-a',task:{profile:'dev',sourceKey:'synthetic',sourceId:'synthetic-original',taskKey:'synthetic-exact'},skillSource:'executor-reported',skillsKnown:true};
 let s=F.fromSnapshot(data).sessions[0];assert.equal(s.scope.kind,'turn');assert.equal(s.scope.id,'turn-a');assert.equal(s.usage.total,7);assert.equal(s.model,undefined);assert.equal(s.task.identity.sourceId,'synthetic-original');assert.deepEqual(s.appliedSkills.map(s=>s.skillId),['skill-exact-id']);assert.equal(s.events.length,1);
 row.attemptBinding.skillSource='read';assert.equal(F.fromSnapshot(data).sessions[0].appliedSkills,null);
 row.attemptBinding.turnId='missing';s=F.fromSnapshot(data).sessions[0];assert.equal(s.usage,undefined);assert.equal(s.task,null);
});
test('cached bridge subscribes and disconnects, no second transport/polling or native mutations',()=>{
 const seen=[],data=raw();let callback,removed=false;const connection=F.connect({update:s=>seen.push(s)},{read:()=>data,subscribe:cb=>{callback=cb;return ()=>removed=true;}});
 assert.equal(seen.length,1);callback(data);connection.refresh();assert.equal(seen.length,3);connection.disconnect();assert.equal(removed,true);
});

test('Projects landing → project → agent excludes finished/global rows while retaining unknown observations and selected finished detail',()=>{
 const current=session('current'),unknown=session('unknown',{status:'unknown',agentId:'agent-b'}),finished=session('finished',{status:'completed'}),other=session('other',{projectId:'project-b'});
 const m=V.createModel({page:'projects'}).update(feed([current,unknown,finished,other]));
 assert.deepEqual(m.rows(),[]);assert.deepEqual(m.projectAgents(null),[]);
 m.navigate({page:'projects',projectId:'project-a'});assert.deepEqual(m.rows().map(s=>s.id),['current','unknown']);assert.deepEqual(m.projectAgents('project-a').map(a=>a.id),['agent-a']);
 m.navigate({page:'projects',projectId:'project-a',agentId:'agent-a',sessionId:'current'});assert.deepEqual(m.rows().map(s=>s.id),['current']);
 m.update(feed([{...current,status:'completed'},unknown,finished,other]));assert.deepEqual(m.rows(),[]);assert.equal(m.selected.id,'current');assert.equal(m.selected.status,'completed');assert.equal(m.route.sessionId,'current');
 m.navigate({page:'projects',projectId:'project-a',agentId:'agent-b'});assert.deepEqual(m.rows().map(s=>s.id),['unknown']);assert.equal(m.rows()[0].status,'unknown');
 m.navigate({page:'history',projectId:'project-a'});assert.deepEqual(m.rows().map(s=>s.id),['current','finished']);
});
