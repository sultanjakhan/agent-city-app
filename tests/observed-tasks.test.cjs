const {test}=require('node:test'),assert=require('node:assert/strict'),T=require('../static/observed-tasks.js'),V=require('../static/observed-work.js'),F=require('../static/observed-feed.js'),H=require('../static/observed-host.js'),D=require('./observed-dom.cjs');
const now=Date.parse('2026-01-01T10:00:00Z'),recent='2026-01-01T09:59:00Z',old='2025-12-01T00:00:00Z';
const source={profile:'synthetic-profile',sourceKey:'0123456789abcdef',label:'Синтетический источник'};
const task=(id,extra={})=>({sourceId:id,taskKey:'cicada-'+source.sourceKey+'-'+id,title:'Одинаковое название',completed:false,isActive:false,processLabel:'Процесс, не проект',...extra});
const binding=t=>T.identity(source,t),run=(t,extra={})=>({runId:'run-'+t.sourceId,sequence:1,taskKey:t.taskKey,status:'running',updatedAt:recent,...extra});
const snapshot=(tasks,runs=[],extra={})=>({asOf:recent,cicada:{status:'connected',source,readAt:recent,tasks,...extra},runs});
const observed=sessions=>({source:{status:'fresh'},projects:[{id:'p',name:'Явный проект'}],agents:[{id:'a',projectId:'p',name:'Агент'}],sessions});
const execution=(id,t,extra={})=>({id,name:'Session 1',projectId:'p',agentId:'a',taskBinding:binding(t),scope:{kind:'turn',id:'turn-'+id},status:'working',...extra});
const model=()=>T.createModel({now:()=>now});
test('authoritative identity isolates same-name tasks, full bound identities and multiple executions without totals',()=>{
 const a=task('a'),b=task('b'),m=model();m.update(snapshot([a,b]));m.observe(observed([execution('one',a),execution('two',a),execution('wrong',b,{taskBinding:{...binding(b),profile:'other'}})]));
 assert.equal(m.rows().length,1);const row=m.rows()[0];assert.equal(row.id,T.key(binding(a)));assert.equal(row.sessionCount,2);assert.equal(row.agentCount,1);assert.deepEqual(row.projectNames,['Явный проект']);assert.equal(row.linked.length,2);assert.equal(row.usage,undefined);
 m.observe(observed([execution('one',a),execution('other',b)]));assert.equal(m.rows().length,2);assert.notEqual(m.rows()[0].id,m.rows()[1].id);
 m.observe({...observed([execution('one',a)]),source:{status:'unavailable'}});assert.equal(m.rows()[0].sessionCount,null);
});
test('attention precedes current once, only explicit unresolved latest user requests survive age',()=>{
 const a=task('a',{isActive:true}),b=task('b'),c=task('c'),m=model();m.update(snapshot([a,b,c],[run(a,{status:'waiting',reasonCode:'approval',updatedAt:old}),run(b,{status:'waiting',reasonCode:'dependency',updatedAt:old}),run(c,{status:'waiting',reasonCode:'user_input',updatedAt:old})]));
 assert.equal(m.rows().length,2);assert.ok(m.rows().every(t=>t.attention));assert.equal(m.get(T.key(binding(a))).requestOld,true);
 m.update(snapshot([a,b,c],[run(a,{sequence:2,status:'done'}),run(a,{status:'waiting',reasonCode:'approval'}),run(c,{sequence:2,status:'error',reasonCode:'verification'})]));assert.deepEqual(m.rows().map(t=>t.identity.sourceId),['a']);assert.equal(m.rows()[0].attention,false);
 for(const reason of ['access','quota','connection','execution','verification',null]){const x=model();x.update(snapshot([b],[run(b,{status:'waiting',reasonCode:reason})]));assert.equal(x.rows()[0].attention,false);}
});
test('timer vs report freshness and skew, paused/planned/waiting tags are not current',()=>{
 const a=task('a',{isPaused:true,waiting:true}),m=model();m.update(snapshot([a]));assert.equal(m.rows().length,0);
 for(const [delta,eligible] of [[300000,true],[300001,false],[-30000,true],[-30001,false]]){m.update(snapshot([a],[run(a,{sequence:2+Math.abs(delta),updatedAt:new Date(now-delta).toISOString()})]));const x=model();x.update(snapshot([a],[run(a,{updatedAt:new Date(now-delta).toISOString()})]));assert.equal(x.rows().length>0,eligible);}
 const completed=task('done',{completed:true,isActive:true});m.update(snapshot([completed],[run(completed)]));assert.equal(m.rows().length,0);
});
test('partial/failure/disconnection preserve qualified rows; recovery complete empty differs; unknown counts are not zero',()=>{
 const a=task('a',{isActive:true}),m=model(),id=T.key(binding(a));m.update(snapshot([a]));assert.equal(m.get(id).sessionCount,null);assert.deepEqual(m.get(id).projectNames,[]);
 m.update(snapshot([],[],{hasMore:true}));assert.equal(m.source.status,'partial');assert.equal(m.rows()[0].present,false);
 m.update(null,Error('synthetic'));assert.equal(m.source.status,'stale');assert.equal(m.rows().length,1);assert.equal(m.rows()[0].stale,true);
 m.update({cicada:{status:'disconnected'}});assert.equal(m.source.status,'disconnected');assert.equal(m.rows().length,1);
 m.update(snapshot([]));assert.equal(m.source.status,'complete');assert.equal(m.rows().length,0);assert.equal(m.get(id).present,false);
});
test('namespace changes cannot cross-join old reports or observations, terminal report resolves even omitted task',()=>{
 const a=task('a'),m=model();m.update(snapshot([a],[run(a,{status:'waiting',reasonCode:'user_input'})]));m.update(snapshot([], [run(a,{sequence:2,status:'done'})]));assert.equal(m.rows().length,0);
 const x=model();x.update(snapshot([a],[run(a,{status:'waiting',reasonCode:'approval'})]));x.update(snapshot([a],[run(a,{sequence:2,status:'waiting',reasonCode:'approval'})],{source:{...source,profile:'other'}}));assert.equal(x.rows().length,0);
 x.observe(observed([execution('old',a)]));assert.equal(x.rows().length,0);
});
test('real renderer task → executions → exact detail → back, inactive selection and disclosure/focus/scroll stay stable',()=>{
 const doc=D.document(),root=doc.createElement('div');doc.body.append(root);doc.defaultView.innerWidth=600;
 const ui=V.mount(root,{taskHome:T,now:()=>now}),a=task('a',{isActive:true}),data=snapshot([a]);ui.update(observed([execution('one',a)]));ui.updateTasks(data);
 const row=root.querySelector('.ow-task-row');assert.match(row.textContent,/Одинаковое название/);assert.doesNotMatch(row.textContent,/Процесс, не проект/);root.scrollTop=420;row.click();const detail=root.querySelector('.ow-task-detail'),heading=detail.querySelector('h3');assert.equal(doc.activeElement,heading);assert.match(detail.textContent,/Связанные выполнения/);
 const disclosure=detail.querySelector('details');disclosure.open=true;disclosure.querySelector('summary').focus();root.scrollTop=60;ui.update(observed([]));ui.updateTasks(snapshot([task('a')]));assert.equal(ui.home.selected,T.key(binding(a)));assert.equal(disclosure.open,true);assert.equal(doc.activeElement,disclosure.querySelector('summary'));assert.equal(root.scrollTop,60);assert.match(detail.textContent,/Сейчас не подтверждена/);
 ui.update(observed([execution('one',a)]));ui.updateTasks(data);detail.querySelector('.ow-task-execution').click();assert.equal(ui.model.route.sessionId,'one');assert.equal(detail.hidden,true);assert.match(root.querySelector('.ow-back').textContent,/Назад к задаче/);
 ui.update(observed([execution('one',a,{status:'completed'})]));root.querySelector('.ow-back').click();assert.equal(ui.model.route.sessionId,null);assert.equal(ui.home.selected,T.key(binding(a)));assert.equal(doc.activeElement,detail.querySelector('.ow-task-execution'));
 ui.updateTasks(data);root.querySelector('.ow-task-back').click();assert.equal(ui.home.selected,null);assert.equal(doc.activeElement,root.querySelector('.ow-task-row'));assert.equal(root.scrollTop,420);
 root.querySelector('.ow-task-row').focus();root.querySelector('.ow-task-row').click();assert.equal(doc.activeElement,heading); // Native button keyboard activation uses the same path.
});
test('no-session task view is honest; attention hidden when absent and raw session inventory never appears on Home',()=>{
 const doc=D.document(),root=doc.createElement('div');doc.body.append(root);const ui=V.mount(root,{taskHome:T,now:()=>now}),a=task('a',{isActive:true});ui.update(observed([execution('unbound',a,{taskBinding:null})]));ui.updateTasks(snapshot([a]));
 assert.equal(root.querySelectorAll('.ow-task-row').length,1);assert.equal(root.querySelectorAll('.ow-rows')[0].children.length,0);assert.doesNotMatch(root.textContent,/Нужно ваше участие/);root.querySelector('.ow-task-row').click();assert.match(root.querySelector('.ow-task-detail').textContent,/Сессии не привязаны/);
 ui.navigate({page:'history'});assert.equal(root.querySelector('.ow-task-home').hidden,true);ui.navigate({page:'projects'});assert.equal(root.querySelector('.ow-empty').textContent,'Выберите проект.');
});
test('host uses cached lexical feed and original loader/schedule, no boot fetch on secondary page and no duplicate timer',async()=>{
 const doc=D.document(),nav=doc.createElement('nav'),aside=doc.createElement('aside');aside.className='app-header';aside.append(nav);doc.body.append(aside);doc.querySelector=s=>s==='.app-header nav'?nav:doc.documentElement.querySelector(s);
 for(const id of ['live-sessions-view','dashboard-view','page-title','catalog-view']){const n=doc.createElement('section');n.id=id;doc.body.append(n);}doc.documentElement.dataset.agentCityMode='passive_dashboard';
 let loads=0,schedules=0,refreshes=0,cache={snapshot:snapshot([task('cached',{isActive:true})])},accept;
 const win={LiveSessions:{viewChanged(){},getSnapshot:()=>null,refresh(){refreshes++;},openProject(){},openSession(){}},addEventListener(){},removeEventListener(){},renderDashboardRows(){throw Error('old DOM rendering');},async loadDashboard(force){loads++;assert.equal(typeof force,'boolean');schedules++;win.renderDashboardRows();},render(){win.LiveSessions.viewChanged(false,'models');}};
 const originalLoad=win.loadDashboard,adapter=H.install({document:doc,window:win,view:V,feed:F,taskHome:T,taskFeed:{read:()=>cache,subscribe:fn=>{accept=fn;return()=>{accept=null;};}}});
 assert.equal(loads,0);assert.equal(adapter.ui.home.model.rows().length,1);win.render();assert.equal(doc.getElementById('observed-work-view').hidden,true);assert.equal(doc.getElementById('catalog-view').hidden,false);
 win.LiveSessions.viewChanged(true,'dashboard');win.renderDashboard();await Promise.resolve();assert.equal(loads,1);assert.equal(schedules,1);assert.equal(refreshes,0);assert.equal(doc.getElementById('dashboard-view').hidden,true);
 cache={snapshot:null,error:Error('synthetic failure')};accept();assert.equal(adapter.ui.home.model.source.status,'stale');assert.equal(adapter.ui.home.model.rows().length,1);
 await win.loadDashboard(true);assert.equal(loads,2);assert.equal(schedules,2);adapter.disconnect();assert.equal(win.loadDashboard,originalLoad);assert.equal(accept,null);
});

test('open task remains selected with explicitly old-source facts after source switch, without current timer claims',()=>{
 const doc=D.document(),root=doc.createElement('div');doc.body.append(root);const ui=V.mount(root,{taskHome:T,now:()=>now}),a=task('a',{isActive:true});ui.updateTasks(snapshot([a]));root.querySelector('.ow-task-row').click();const selected=ui.home.selected;
 const heading=root.querySelector('.ow-task-detail').querySelector('h3');heading.focus();root.scrollTop=87;
 ui.updateTasks(snapshot([a],[],{source:{...source,profile:'new-profile',label:'Новый источник'}}));const detail=root.querySelector('.ow-task-detail');assert.equal(ui.home.selected,selected);assert.equal(doc.activeElement,heading);assert.equal(root.scrollTop,87);assert.match(detail.textContent,/прежнего источника/);assert.match(detail.textContent,/Синтетический источник/);assert.doesNotMatch(detail.textContent,/Таймер Cicada идёт|Новый источник/);assert.equal(ui.home.model.get(selected).eligible,false);
});
test('default bridge reads actual global lexical dashboard cache and asynchronous completion/error',async()=>{
 const vm=require('node:vm'),fs=require('node:fs'),doc=D.document();for(const id of ['live-sessions-view','dashboard-view']){const n=doc.createElement('section');n.id=id;doc.body.append(n);}
 const scope={document:doc,AgentCityObserved:V,AgentCityObservedFeed:F,AgentCityTaskHome:T,initial:snapshot([task('lexical',{isActive:true})]),LiveSessions:{viewChanged(){},getSnapshot:()=>null,openProject(){},openSession(){}},addEventListener(){},removeEventListener(){}};scope.window=scope;
 vm.runInNewContext('let dashboardData=initial; let dashboardReadError=null; async function loadDashboard(){await Promise.resolve(); dashboardReadError="synthetic failure"; renderDashboardRows();}',scope);
 vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../static/observed-host.js'),'utf8'),scope);const adapter=scope.AgentCityObservedHost.install();assert.equal(scope.dashboardData,undefined);assert.equal(adapter.ui.home.model.rows().length,1);await scope.loadDashboard(false);assert.equal(adapter.ui.home.model.source.status,'stale');adapter.disconnect();
});
test('mapper exports task identity only for the existing exact-bound-turn contract',()=>{
 const a=task('a'),base={id:'mapped',projectId:'p',agentId:'a',status:'working',stages:[{id:'exact',status:'working'}]},claim={kind:'owner-approved-exact-turn',turnId:'exact',task:binding(a)};
 const read=attemptBinding=>F.fromSnapshot({sessions:[{...base,attemptBinding}]}).sessions[0];assert.deepEqual(read(claim).taskBinding,binding(a));assert.equal(read({...claim,turnId:'missing'}).taskBinding,null);assert.equal(read(null).taskBinding,null);
});
