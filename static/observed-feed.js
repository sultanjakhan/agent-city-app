/* Pure metadata mapping. Supplied bindings remain claims, not new authority. */
(function(root){
 'use strict';
 const metric=row=>({status:row?.status,startedAt:row?.startedAt,endedAt:row?.endedAt,durationMs:row?.durationMs,
  durationSource:row?.durationSource,model:row?.model,effort:row?.effort,coverage:row?.coverage,usage:row?.usage});
 const activity=rows=>(Array.isArray(rows)?rows:[]).map(e=>({id:e.id,at:e.at,label:e.label||e.kind,source:e.source}));
 function fromSnapshot(snapshot){
  const data=snapshot||{},sessions=Array.isArray(data.sessions)?data.sessions:[],source=data.source||{};
  const result=sessions.map(item=>{
   const stages=Array.isArray(item.stages)?item.stages:[],claim=item.attemptBinding;
   const matches=claim?.turnId?stages.filter(s=>s.id===claim.turnId):[];
   const bound=claim?.kind==='owner-approved-exact-turn'&&matches.length===1;
   const turn=bound?{...matches[0],coverage:matches[0].coverage??item.coverage}:null;
   const row={id:item.id,projectId:item.projectId,agentId:item.agentId,parentId:item.parentId,name:item.name,
    scope:{kind:bound?'turn':'session',id:bound?turn.id:item.id},...metric(bound?turn:item),
    task:bound?{title:item.name,goal:null,identity:{...claim.task,nativeTaskKey:claim.nativeTaskKey}}:null,
    appliedSkills:null,events:[],turns:[]};
   // A malformed binding must not expose inherited thread counters as turn data.
   if(claim&&!bound){Object.assign(row,metric({status:item.status,coverage:'unknown'}));return row;}
   const single=bound?turn:stages.length===1?stages[0]:null;
   row.events=activity(single?.events);
   if(bound&&claim.skillSource==='executor-reported'&&claim.skillsKnown===true){
    row.appliedSkills=(turn.events||[]).filter(e=>e.kind==='skill-applied'&&e.source==='executor-reported'&&typeof e.skill==='string')
     .map(e=>({id:e.id,at:e.at,skillId:e.skill,kind:'applied',source:'executor-reported'}));
    const ids=new Set(row.appliedSkills.map(e=>e.id));row.events=row.events.filter(e=>!ids.has(e.id));
   }
   // Skills/inventory strings and read events never become application evidence.
   if(!bound&&stages.length>1)row.turns=stages.map(stage=>({id:stage.id,name:stage.name,...metric(stage),events:activity(stage.events)}));
   return row;
  });
  const byId=new Map(sessions.map(s=>[s.id,s]));
  const edges=(Array.isArray(data.edges)?data.edges:[]).flatMap(edge=>{
   const a=byId.get(edge.from),b=byId.get(edge.to);
   if(!a||!b||a.projectId!==b.projectId||!a.agentId||!b.agentId)return [];
   return [{id:edge.id,projectId:a.projectId,fromAgentId:a.agentId,toAgentId:b.agentId,label:edge.kind==='spawn'?'Создание сессии':edge.kind==='transfer'?'Передача':'Наблюдаемая связь'}];
  });
  return {projects:data.projects||[],agents:data.agents||[],sessions:result,edges,
   source:{status:({live:'fresh',partial:'partial',stale:'stale',unavailable:'unavailable',unconfigured:'unknown'}[source.status])||'unknown',
    originalStatus:source.status||null,message:source.message||null,readAt:source.lastReadAt||null}};
 }
 function connect(view,{read,subscribe}){
  // Host owns fetch, cadence, lifecycle and visibility. No second polling loop.
  const accept=data=>{if(data)view.update(fromSnapshot(data));};
  accept(read());const unsubscribe=subscribe(accept);
  return {refresh(){accept(read());},disconnect(){if(typeof unsubscribe==='function')unsubscribe();}};
 }
 const api=Object.freeze({fromSnapshot,connect});if(typeof module==='object'&&module.exports)module.exports=api;else root.AgentCityObservedFeed=api;
})(typeof globalThis==='object'?globalThis:this);
