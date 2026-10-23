const {test}=require('node:test'),assert=require('node:assert/strict'),V=require('../static/observed-work.js'),F=require('../static/observed-feed.js'),H=require('../static/observed-host.js'),D=require('./observed-dom.cjs');
const session=(id,extra={})=>({id,projectId:'project-a',agentId:'agent-a',name:'Сессия '+id,scope:{kind:'session',id},status:'working',coverage:'partial',usage:{input:3,total:null},...extra});
const feed=sessions=>({source:{status:'partial'},projects:[{id:'project-a',name:'Проект А'}],agents:[{id:'agent-a',projectId:'project-a',name:'Координатор'}],sessions});
function setup(){const doc=D.document(),root=doc.createElement('div');doc.body.append(root);let routes=0;const ui=V.mount(root,{onRoute:()=>routes++,now:()=>Date.parse('2026-01-01T10:01:00Z')});return {doc,root,ui,routes:()=>routes};}
const by=(root,cls)=>root.querySelector('.'+cls);
test('real mount keeps selection, tabs, disclosures, focus, nodes and scroll across updates/completion',()=>{
 const h=setup(),data=feed([session('one'),session('two')]);h.ui.update(data);const row=by(h.root,'ow-session');row.click();
 const details=by(h.root,'ow-detail'),disclosure=h.root.querySelectorAll('details').find(n=>n.children[0]?.textContent==='Точный расход токенов');disclosure.open=true;disclosure.children[0].focus();h.root.scrollTop=287;details.scrollTop=91;
 const tabs=by(h.root,'ow-tabs');tabs.children[1].click();const before=h.routes();h.ui.update(feed([session('two'),session('one',{usage:{total:999},status:'completed'})]));
 assert.equal(h.ui.model.route.sessionId,'one');assert.equal(h.routes(),before);assert.equal(disclosure.open,true);assert.equal(h.doc.activeElement,disclosure.children[0]);assert.equal(h.root.scrollTop,287);assert.equal(details.scrollTop,91);assert.equal(tabs.children[1].getAttribute('aria-selected'),'true');assert.equal(details.hidden,false);
 assert.equal(h.ui.model.rows('history')[0].id,'one');assert.equal(h.root.querySelectorAll('.ow-session').length,1);
 h.ui.update(feed([]));assert.equal(details.hidden,false);assert.match(details.textContent,/недоступно/);assert.equal(h.ui.model.route.sessionId,'one');
});
test('single bound row has no artificial turn group; multiple genuine turns stay expandable',()=>{
 const h=setup();h.ui.update(feed([session('s',{scope:{kind:'turn',id:'exact'},turns:[{id:'one'}],task:{title:'Оригинальная задача',identity:{taskKey:'synthetic-exact'}}})]));by(h.root,'ow-session').click();
 assert.equal(h.root.querySelectorAll('.ow-turn').length,0);assert.match(by(h.root,'ow-metrics').textContent,/За выполнение/);
 h.ui.update(feed([session('s',{turns:[{id:'one',name:'Наблюдаемый ход 1'},{id:'two',name:'Наблюдаемый ход 2'}]})]));assert.equal(h.root.querySelectorAll('.ow-turn').length,2);
 const turn=by(h.root,'ow-turn');turn.open=true;h.ui.update(feed([session('s',{turns:[{id:'one'},{id:'two'}]})]));assert.equal(by(h.root,'ow-turn'),turn);assert.equal(turn.open,true);
});
test('unknown source exposes coverage without measured-zero claims; source text never becomes markup',()=>{
 const h=setup();h.ui.update({...feed([]),source:{status:'unavailable',message:'<script>synthetic</script>'}});assert.match(by(h.root,'ow-empty').textContent,/не подтверждён/);assert.equal(h.root.querySelectorAll('script').length,0);assert.match(by(h.root,'ow-freshness').textContent,/synthetic/);
});
test('host reuses cached feed and existing visibility lifecycle without route recursion/new transport',()=>{
 const doc=D.document(),nav=doc.createElement('nav'),aside=doc.createElement('aside');aside.className='app-header';aside.append(nav);doc.body.append(aside);
 // Host fixture selectors are the exact hooks, not private legacy source.
 doc.querySelector=s=>s==='.app-header nav'?nav:doc.documentElement.querySelector(s);
 for(const page of ['dashboard','sessions']){const n=doc.createElement('button');n.dataset.view=page;nav.append(n);}
 for(const id of ['live-sessions-view','dashboard-view','page-title']){const n=doc.createElement('section');n.id=id;doc.body.append(n);}doc.documentElement.dataset.agentCityMode='passive_dashboard';
 let visibility=0,reads=0;const listeners={};const win={LiveSessions:{viewChanged(){visibility++;},getSnapshot(){reads++;return {source:{status:'live'},projects:[{id:'project-a'}],agents:[],sessions:[]};},refresh:async()=>null,openProject(){},openSession(){}},addEventListener:(k,cb)=>listeners[k]=cb,removeEventListener:k=>delete listeners[k],renderDashboard(){throw Error('legacy dashboard must not render');}};
 win.render=()=>{win.LiveSessions.viewChanged(true,'dashboard');doc.getElementById('dashboard-view').hidden=false;win.renderDashboard();};win.setView=page=>{win.LiveSessions.viewChanged(true,page);};
 const adapter=H.install({document:doc,window:win,view:V,feed:F});win.render();assert.equal(doc.getElementById('dashboard-view').hidden,true);assert.equal(doc.getElementById('live-sessions-view').hidden,true);assert.equal(doc.getElementById('observed-work-view').hidden,false);
 const history=nav.children.find(n=>n.dataset.observedPage==='history');assert.equal(history.getAttribute('aria-label'),'История');assert.equal(history.querySelector('svg').getAttribute('aria-hidden'),'true');assert.equal(history.querySelector('circle').getAttribute('r'),'9');assert.equal(history.querySelector('path').getAttribute('d'),'M12 7v5l3 2');history.click();assert.equal(adapter.ui.model.route.page,'history');assert.ok(visibility<6);assert.equal(reads,1);
 listeners['agentcity:live-summary']({detail:{source:{status:'unavailable'},sessions:[]}});assert.equal(adapter.ui.model.route.page,'history');assert.equal(adapter.ui.model.data.source.status,'unavailable');adapter.disconnect();
});

test('late earlier activity reconciles sorted DOM order without replacing event/focus or scroll',()=>{
 const h=setup();const later={id:'later',at:'2026-01-01T10:01:00Z',label:'Позже'};
 h.ui.update(feed([session('s',{events:[later]})]));by(h.root,'ow-session').click();const events=by(h.root,'ow-events'),prior=events.children[0];prior.focus();h.root.scrollTop=80;
 h.ui.update(feed([session('s',{events:[later,{id:'earlier',at:'2026-01-01T10:00:00Z',label:'Раньше'}]})]));
 assert.deepEqual(events.children.map(n=>n.dataset.key),['event:earlier','event:later']);assert.equal(events.children[1],prior);assert.equal(h.doc.activeElement,prior);assert.equal(h.root.scrollTop,80);
});
test('session tabs support ArrowLeft/Right/Home/End, focus movement and polling preservation',()=>{
 const h=setup();h.ui.update(feed([session('s')]));by(h.root,'ow-session').click();const tabs=by(h.root,'ow-tabs');
 for(const [key,start,end] of [['ArrowRight',0,1],['ArrowRight',1,0],['ArrowLeft',0,1],['Home',1,0],['End',0,1]]){
  let prevented=false;for(const fn of tabs.handlers.keydown)fn({key,target:tabs.children[start],preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(h.doc.activeElement,tabs.children[end]);assert.equal(tabs.children[end].getAttribute('aria-selected'),'true');
 }
 h.ui.update(feed([session('s')]));assert.equal(tabs.children[1].getAttribute('aria-selected'),'true');assert.equal(h.doc.activeElement,tabs.children[1]);
});
test('History shows per-observation date, duration and session/execution scope without merging same-task rows',()=>{
 const h=setup();h.ui.update(feed([session('raw',{status:'completed',endedAt:'2026-01-01T10:01:00Z',durationMs:61000,usage:{total:500}}),session('bound',{status:'interrupted',scope:{kind:'turn',id:'exact-turn'},endedAt:'2026-01-01T11:01:00Z',usage:{total:null}})]));h.ui.navigate({page:'history'});
 const rows=h.root.querySelectorAll('.ow-session');assert.equal(rows.length,2);assert.match(rows[1].textContent,/За сессию.*2026.*1 мин 1 с/);assert.match(rows[0].textContent,/За выполнение.*2026.*Неизвестно/);rows[0].click();assert.match(by(h.root,'ow-metrics').textContent,/За выполнение/);
});

test('actual assembled bundle boots once in passive host and never fetches a new asset or endpoint',()=>{
 const {execFileSync}=require('node:child_process'),vm=require('node:vm');
 const bundle=execFileSync('python',['-c','from compat.observed_frontend import bundle; from pathlib import Path; print(bundle(Path.cwd()))'],{cwd:require('node:path').join(__dirname,'..'),encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
 const doc=D.document(),nav=doc.createElement('nav'),aside=doc.createElement('aside');aside.className='app-header';aside.append(nav);doc.body.append(aside);doc.querySelector=s=>s==='.app-header nav'?nav:doc.documentElement.querySelector(s);
 for(const id of ['live-sessions-view','dashboard-view','page-title']){const n=doc.createElement('section');n.id=id;doc.body.append(n);}doc.documentElement.dataset.agentCityMode='passive_dashboard';doc.readyState='complete';
 const listeners={},queue=[],scope={MutationObserver:class{observe(){}disconnect(){}},document:doc,URLSearchParams,Intl,Date,queueMicrotask:fn=>queue.push(fn),fetch:()=>{throw Error('unexpected transport');},addEventListener:(key,fn)=>{(listeners[key]??=[]).push(fn);},removeEventListener(){},LiveSessions:{viewChanged(){},getSnapshot:()=>({projects:[],agents:[],sessions:[],source:{status:'partial'}}),refresh:async()=>null,openProject(){},openSession(){}},renderDashboard(){}};
 scope.window=scope;scope.render=()=>{scope.LiveSessions.viewChanged(true,'dashboard');scope.renderDashboard();};scope.setView=page=>scope.LiveSessions.viewChanged(true,page);
 vm.runInNewContext(bundle,scope);assert.ok(scope.AgentCityObservedController);for(const fn of queue)fn();
 assert.equal(doc.querySelectorAll('.observed-work').length,1);assert.equal(doc.getElementById('observed-work-view').hidden,false);assert.equal(doc.getElementById('dashboard-view').hidden,true);
 for(const cb of listeners['agentcity:live-summary'])cb({detail:{source:{status:'unavailable'},sessions:[]}});
 assert.equal(doc.querySelectorAll('.observed-work').length,1);
});


test('main occupies the sole grid track until a detail selection exists on every page',()=>{
 const h=setup();h.ui.update(feed([session('one')]));const layout=by(h.root,'ow-layout');
 for(const page of ['home','projects','history']){h.ui.navigate({page});assert.equal(layout.className.includes('ow-detail-selected'),false);assert.equal(by(h.root,'ow-detail').hidden,true);}
 h.ui.navigate({page:'home',sessionId:'one'});assert.equal(layout.className.includes('ow-detail-selected'),true);
 h.ui.update(feed([]));assert.equal(layout.className.includes('ow-detail-selected'),true); // Selected unavailable detail stays open.
 h.ui.navigate({page:'home'});assert.equal(layout.className.includes('ow-detail-selected'),false);
 const css=require('node:fs').readFileSync(require('node:path').join(__dirname,'../static/observed-work.css'),'utf8');
 assert.match(css,/\.ow-layout \{[^}]*grid-template-columns:minmax\(0,1fr\)/);
 assert.match(css,/@media\(max-width:800px\) \{ \.ow-layout\.ow-detail-selected \{ grid-template-columns:minmax\(0,1fr\)/);
});
test('only explicit different-session selection focuses heading and reveals it when outside visible bounds',()=>{
 const h=setup();h.ui.update(feed([session('one'),session('two')]));const detail=by(h.root,'ow-detail'),heading=detail.querySelector('h3');heading.getBoundingClientRect=()=>({top:1200,bottom:1240});
 let rows=h.root.querySelectorAll('.ow-session');rows[0].click();assert.equal(h.doc.activeElement,heading);assert.deepEqual(heading.focusCalls,[{preventScroll:true}]);assert.equal(heading.scrollCalls.length,1);assert.equal(heading.tabIndex,-1);
 const disclosure=detail.querySelector('summary');disclosure.focus();disclosure.parentElement.open=true;h.root.scrollTop=370;
 h.ui.update(feed([session('one',{usage:{total:7}}),session('two')]));rows[0].click();
 assert.equal(h.doc.activeElement,disclosure);assert.equal(heading.scrollCalls.length,1);assert.equal(heading.focusCalls.length,1);assert.equal(h.root.scrollTop,370);
 heading.getBoundingClientRect=()=>({top:150,bottom:190});rows[1].click();assert.equal(h.doc.activeElement,heading);assert.equal(heading.focusCalls.length,2);assert.equal(heading.scrollCalls.length,1);
 // A clipped native main scroll container also requires reveal even within viewport.
 h.root.clientHeight=100;h.root.scrollHeight=1200;h.root.getBoundingClientRect=()=>({top:0,bottom:100});rows[0].click();assert.equal(heading.scrollCalls.length,2);
 h.ui.update(feed([session('one',{status:'completed'}),session('two')]));assert.equal(heading.scrollCalls.length,2);assert.equal(heading.focusCalls.length,3);assert.equal(h.ui.model.route.sessionId,'one');
});


test('same-name sessions identify supplied agents in Home and History while bound task title stays primary',()=>{
 const h=setup(),agents=[{id:'agent-a',projectId:'project-a',name:'Агент Альфа'},{id:'agent-b',projectId:'project-a',name:'Агент Бета'}];
 h.ui.update({...feed([session('a',{name:'Session 1'}),session('b',{name:'Session 1',agentId:'agent-b'}),session('linked',{name:'Session 1',scope:{kind:'turn',id:'exact'},task:{title:'Исходная задача'}})]),agents});
 let rows=h.root.querySelectorAll('.ow-session');assert.match(rows[0].textContent,/Агент Альфа · Session 1/);assert.match(rows[1].textContent,/Агент Бета · Session 1/);assert.equal(rows[2].querySelector('.ow-session-title').textContent,'Исходная задача');assert.match(rows[2].textContent,/Агент Альфа/);
 h.ui.update({...feed([session('a',{name:'Session 1',status:'completed'}),session('b',{name:'Session 1',agentId:'agent-b',status:'completed'})]),agents});h.ui.navigate({page:'history'});rows=h.root.querySelectorAll('.ow-session');assert.match(rows[0].textContent,/Агент Альфа · Session 1/);assert.match(rows[1].textContent,/Агент Бета · Session 1/);
});
test('History starts newest ended first with deterministic ID ties and retains keyed focus/scroll on updates',()=>{
 const h=setup(),old=session('old',{status:'completed',endedAt:'2026-01-01T10:00:00Z'}),a=session('new-a',{status:'completed',endedAt:'2026-01-01T11:00:00Z'}),b=session('new-b',{status:'completed',endedAt:'2026-01-01T12:00:00+01:00'}),unknown=session('unknown',{status:'interrupted'});
 h.ui.update(feed([old,b,unknown,a]));h.ui.navigate({page:'history'});const list=by(h.root,'ow-rows');assert.deepEqual(list.children.map(n=>n.dataset.key),['new-a','new-b','old','unknown']);
 const prior=list.children[2];prior.focus();h.root.scrollTop=430;
 h.ui.update(feed([unknown,old,a,b,session('middle',{status:'completed',endedAt:'2026-01-01T10:30:00Z'})]));assert.deepEqual(list.children.map(n=>n.dataset.key),['new-a','new-b','middle','old','unknown']);assert.equal(list.children[3],prior);assert.equal(h.doc.activeElement,prior);assert.equal(h.root.scrollTop,430);assert.equal(prior.scrollCalls,undefined);
});
test('narrow master/detail back restores list filters, position and row focus only on explicit return',()=>{
 const h=setup();h.doc.defaultView.innerWidth=600;const data=feed([session('one',{status:'completed'}),session('two',{status:'completed'})]);h.ui.update(data);h.ui.navigate({page:'history',projectId:'project-a',agentId:'agent-a'});
 const selected=by(h.root,'ow-session'),layout=by(h.root,'ow-layout');h.root.scrollTop=640;selected.click();assert.equal(layout.className.includes('ow-detail-selected'),true);assert.equal(by(h.root,'ow-back').textContent,'Назад к списку');
 h.root.scrollTop=20;const tab=by(h.root,'ow-tabs').children[1];tab.click();tab.focus();h.ui.update(data);assert.equal(h.doc.activeElement,tab);assert.equal(h.root.scrollTop,20);assert.equal(h.ui.model.route.sessionId,'one');
 by(h.root,'ow-back').click();assert.deepEqual(h.ui.model.route,{page:'history',projectId:'project-a',agentId:'agent-a',sessionId:null});assert.equal(h.doc.activeElement,selected);assert.equal(h.root.scrollTop,640);assert.equal(layout.className.includes('ow-detail-selected'),false);
 const css=require('node:fs').readFileSync(require('node:path').join(__dirname,'../static/observed-work.css'),'utf8');assert.match(css,/@media\(max-width:800px\)[^}]*} \.ow-layout\.ow-detail-selected>\.ow-main \{ display:none;/);
 selected.click();assert.equal(by(h.root,'ow-tabs').children[1].getAttribute('aria-selected'),'true');
});
test('return after selected execution completes retains Home rather than navigating to History',()=>{
 const h=setup();h.ui.update(feed([session('one')]));h.root.scrollTop=110;by(h.root,'ow-session').click();h.ui.update(feed([session('one',{status:'completed'})]));assert.equal(h.ui.model.route.sessionId,'one');by(h.root,'ow-back').click();assert.equal(h.ui.model.route.page,'home');assert.equal(h.ui.model.route.sessionId,null);assert.equal(h.doc.activeElement,by(h.root,'ow-main').querySelector('h2'));assert.equal(h.root.scrollTop,110);
});
test('Projects landing uses the single project-selection instruction',()=>{
 const h=setup();h.ui.navigate({page:'projects'});for(const status of ['partial','fresh','unavailable']){h.ui.update({...feed([]),source:{status}});assert.equal(by(h.root,'ow-empty').textContent,'Выберите проект.');}
});


test('boot observes only passive mode, installs once for either DOM/mode ordering, and preserves secondary page without collector fetch',()=>{
 const {execFileSync}=require('node:child_process'),vm=require('node:vm');
 const bundle=execFileSync('python',['-c','from compat.observed_frontend import bundle; from pathlib import Path; print(bundle(Path.cwd()))'],{cwd:require('node:path').join(__dirname,'..'),encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
 for(const ordering of ['dom-then-mode','mode-then-dom','both-ready','dom-ready-mode-later']){
  const doc=D.document(),nav=doc.createElement('nav'),aside=doc.createElement('aside');aside.className='app-header';aside.append(nav);doc.body.append(aside);doc.querySelector=s=>s==='.app-header nav'?nav:doc.documentElement.querySelector(s);
  for(const id of ['live-sessions-view','dashboard-view','page-title','catalog-view']){const n=doc.createElement('section');n.id=id;doc.body.append(n);}
  doc.getElementById('catalog-view').hidden=false;doc.getElementById('page-title').textContent='Модели';
  const models=doc.createElement('button');models.dataset.view='models';models.className='active';nav.append(models);
  const initiallyReady=ordering==='both-ready'||ordering==='dom-ready-mode-later';doc.readyState=initiallyReady?'complete':'loading';if(ordering==='both-ready')doc.documentElement.dataset.agentCityMode='passive_dashboard';
  const listeners={},queue=[],observers=[];let refreshes=0,renders=0,navigations=0;
  class Observer{constructor(cb){this.cb=cb;this.disconnected=false;observers.push(this);}observe(target,options){this.target=target;this.options=options;}disconnect(){this.disconnected=true;}}
  const scope={MutationObserver:Observer,document:doc,URLSearchParams,Intl,Date,queueMicrotask:fn=>queue.push(fn),fetch:()=>{throw Error('unexpected collector/transport request');},addEventListener:(key,fn)=>{(listeners[key]??=[]).push(fn);},removeEventListener:(key,fn)=>{listeners[key]=(listeners[key]||[]).filter(x=>x!==fn);},LiveSessions:{viewChanged(show){assert.equal(show,false);},getSnapshot:()=>null,refresh:async()=>{refreshes++;},openProject(){},openSession(){}},renderDashboard(){}};
  scope.window=scope;scope.render=()=>{renders++;scope.LiveSessions.viewChanged(false,'models');};scope.setView=()=>{navigations++;};
  vm.runInNewContext(bundle,scope);const observer=observers[0];assert.equal(observer.target,doc.documentElement);assert.deepEqual(JSON.parse(JSON.stringify(observer.options)),{attributes:true,attributeFilter:['data-agent-city-mode']});
  const dom=()=>{doc.readyState='complete';for(const fn of [...(doc.handlers.DOMContentLoaded||[])])fn();};
  const mode=()=>{doc.documentElement.dataset.agentCityMode='passive_dashboard';observer.cb();};
  if(ordering==='dom-then-mode'){dom();assert.equal(scope.AgentCityObservedController,undefined);mode();}
  if(ordering==='mode-then-dom'){mode();assert.equal(scope.AgentCityObservedController,undefined);dom();}
  if(ordering==='dom-ready-mode-later'){assert.equal(scope.AgentCityObservedController,undefined);mode();}
  assert.ok(scope.AgentCityObservedController);assert.equal(observer.disconnected,true);for(const fn of queue)fn();
  assert.equal(doc.getElementById('catalog-view').hidden,false);assert.equal(doc.getElementById('page-title').hidden,false);assert.equal(doc.getElementById('page-title').textContent,'Модели');assert.equal(models.className,'active');assert.equal(doc.getElementById('observed-work-view').hidden,true);
  assert.equal(nav.children.filter(n=>n.dataset.observedPage==='history').length,1);assert.equal(refreshes,0);assert.equal(navigations,0);assert.equal(renders,1);assert.equal((listeners['agentcity:live-summary']||[]).length,1); // Only the feed subscription remains.
  observer.cb();dom();for(const fn of [...(listeners['agentcity:live-summary']||[])])fn({detail:{source:{status:'unavailable'},sessions:[]}});
  assert.equal(nav.children.filter(n=>n.dataset.observedPage==='history').length,1);assert.equal(queue.length,1);assert.equal(refreshes,0);
 }
});


test('bound History copy is timeless, recorded duration omits redundant note, and only detail-heading outline is suppressed',()=>{
 const h=setup(),s=session('bound',{scope:{kind:'turn',id:'synthetic-old-turn'},status:'completed',endedAt:'2026-01-01T10:00:00Z',durationMs:12000,durationSource:'collector-reported-duration'});
 h.ui.update(feed([s]));h.ui.navigate({page:'history',sessionId:'bound'});assert.match(by(h.root,'ow-breadcrumb').textContent,/Выполнение/);assert.doesNotMatch(by(h.root,'ow-breadcrumb').textContent,/Текущий ход/);
 const note=by(h.root,'ow-metrics').children[0].children[2];assert.equal(note.hidden,true);assert.equal(note.textContent,'');assert.equal(h.ui.model.selected.durationMs,12000);assert.equal(h.doc.activeElement,by(h.root,'ow-detail-title'));
 h.ui.update(feed([{...s,durationSource:'derived-from-observed-turn-bounds'}]));assert.equal(note.hidden,false);assert.match(note.textContent,/границам/);assert.equal(h.ui.model.selected.durationMs,12000);
 const css=require('node:fs').readFileSync(require('node:path').join(__dirname,'../static/observed-work.css'),'utf8');assert.ok(css.includes('.observed-work .ow-detail-title:focus { outline:none; }'));assert.ok(css.includes('.ow-breadcrumb>.ow-crumb + .ow-crumb::before'));assert.ok(css.includes('.observed-work :focus-visible { outline:2px'));
});
