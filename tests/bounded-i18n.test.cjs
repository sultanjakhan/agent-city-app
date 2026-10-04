const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const base=path.resolve(__dirname,'..');
const read=file=>fs.readFileSync(path.join(base,file),'utf8').replace(/\r\n/g,'\n');
const baseSource=file=>require('node:child_process').execFileSync('git',['-c','safe.directory=*','-c','core.fsmonitor=false','show','0792833c56d6c997b1e5b69074719ca4d835a38a:'+file],{cwd:base,encoding:'utf8'});
const copy=JSON.parse(read('tests/bounded-copy.json'));
function dom(language){
 const d=new JSDOM(read('static/index.html'),{url:'http://synthetic.invalid/',runScripts:'outside-only'});
 d.window.localStorage.setItem('agentcity-language',language);
 d.window.eval(read('static/i18n.js')+';globalThis.qaI18n=I18n;globalThis.I18n=I18n;');
 return d;
}
(async()=>{
 const originalOwner=baseSource('static/owner-session.js'),currentOwner=read('static/owner-session.js');
 // Copy changes must preserve the authorization and retry implementations exactly.
 const connect=source=>source.slice(source.indexOf(' async function connect()'));
 const retry=source=>source.match(/retry\.onclick=async\(\)=>\{.*?\};/)[0];
 assert.equal(connect(currentOwner),connect(originalOwner));assert.equal(retry(currentOwner),retry(originalOwner));

 const d=dom('en'),w=d.window,$=id=>w.document.getElementById(id);w.qaI18n.init();
 assert.equal($('save-repo-profile').textContent,'Save profile');
 assert.equal($('connection-client').getAttribute('aria-label'),'Provider client');
 assert.equal($('work-registry-preview').textContent,'Preview import');
 assert.equal($('work-registry-apply').textContent,'Apply import');
 assert.equal($('project-policy-editor').querySelector('summary').textContent,'Project policy');
 assert.equal($('work-registry').querySelector('summary').textContent,'Published work registry');
 for(const [key,ru] of Object.entries(copy)){assert.equal(w.qaI18n.t(key),key);w.qaI18n.setLanguage('ru');assert.equal(w.qaI18n.t(key),ru);w.qaI18n.setLanguage('en');}
 let fetches=0;w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.fetch=async()=>{fetches++;throw Error('synthetic denial');};
 w.eval(read('static/owner-session.js'));await w.agentCityOwnerReady;
 const dialog=$('owner-session-dialog');assert.equal(dialog.querySelector('h2').textContent,'Agent City session unavailable');
 assert.equal(dialog.querySelector('button').textContent,'Check session again');
 assert.equal(dialog.getAttribute('aria-labelledby'),dialog.querySelector('h2').id);
 w.qaI18n.setLanguage('ru');assert.match(dialog.querySelector('h2').textContent,/Сессия/);assert.equal(fetches,1);
 w.qaI18n.setLanguage('en');assert.equal(dialog.querySelector('button').textContent,'Check session again');assert.equal(fetches,1);
 // Registry mocks exercise actual UI handlers without HTTP, execution or persistence.
 w.t=w.qaI18n.t;w.$=$;w.dashboardData={};
 const rawTitle='Source: literal title',rawOperation='waitingFor raw user data',rawReference='operation';
 const snapshot={source:{publisherId:'publisher-raw',sourceNamespace:'namespace-raw'},publishedAt:new Date().toISOString(),staleAfterSeconds:3600,projects:[{id:'p',title:rawTitle}],tasks:[{id:'task-raw',projectId:'p',parentTaskId:null,title:rawTitle,status:'running',relationship:'root',lastUpdated:new Date().toISOString(),provenance:{reference:rawReference},operation:rawOperation,waitingFor:null,result:null,localBinding:null}]};
 const state={publishers:{p:{snapshot,receivedAt:'received-raw'}},bindings:{},revision:7};
 const envelope={kind:'snapshot',userText:'Сохранить профиль',snapshot};let calls=[];
 w.request=async(url,payload)=>{calls.push({url,payload});if(url.endsWith('/preview'))return{envelope,previewToken:'synthetic-preview',revision:7};return state;};
 w.eval(read('static/work-registry.js'));await w.renderWorkRegistry();
 assert.equal($('work-registry-tasks').querySelector('summary').textContent,rawTitle);
 assert.match($('work-registry-tasks').textContent,/published snapshot/);
 const requestsBeforeLanguage=calls.length;
 w.qaI18n.setLanguage('ru');assert.match($('work-registry-tasks').textContent,/опубликованный снимок/);assert.equal(calls.length,requestsBeforeLanguage);
 assert.equal(w.registryEnum('external-status'),'external-status');
 assert.equal($('work-registry-tasks').querySelector('summary').textContent,rawTitle);
 assert.ok($('work-registry-tasks').textContent.includes(rawOperation));assert.ok($('work-registry-tasks').textContent.includes(rawReference));
 const raw=JSON.stringify(envelope);w.TextDecoder=TextDecoder;
 Object.defineProperty($('work-registry-file'),'files',{value:[{size:raw.length,arrayBuffer:async()=>Buffer.from(raw)}]});
 $('work-registry-file').dispatchEvent(new w.Event('change'));await new Promise(resolve=>setImmediate(resolve));
 assert.equal($('work-registry-message').textContent,copy['File selected. Preview before applying.']);
 w.qaI18n.setLanguage('en');assert.equal($('work-registry-message').textContent,'File selected. Preview before applying.');
 $('work-registry-preview').click();await new Promise(resolve=>setImmediate(resolve));
 assert.equal($('work-registry-preview-body').textContent,JSON.stringify(envelope,null,2));
 assert.deepEqual(JSON.parse(JSON.stringify(calls.find(x=>x.url.endsWith('/preview')).payload)),{document:raw,revision:7});
 w.qaI18n.setLanguage('ru');assert.equal($('work-registry-preview-body').textContent,JSON.stringify(envelope,null,2));
 w.confirm=message=>{assert.equal(message,copy['Save this local import? No task execution will start.']);return true;};
 $('work-registry-apply').click();await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(JSON.parse(JSON.stringify(calls.find(x=>x.url.endsWith('/apply')).payload)),{previewToken:'synthetic-preview',revision:7});
 d.window.close();
 // Actual script order: denial before I18n exists, then saved EN initialization.
 const start=new JSDOM(read('static/index.html'),{url:'http://synthetic.invalid/',runScripts:'outside-only'}),sw=start.window;
 sw.localStorage.setItem('agentcity-language','en');sw.HTMLDialogElement.prototype.showModal=function(){this.open=true;};sw.fetch=async()=>{throw Error('synthetic');};
 sw.eval(read('static/owner-session.js'));await sw.agentCityOwnerReady;sw.eval(read('static/i18n.js')+';globalThis.I18n=I18n;I18n.init();');
 assert.equal(sw.document.querySelector('#owner-session-dialog h2').textContent,'Agent City session unavailable');start.window.close();
 console.log('PASS bounded DOM: shared labels/accessibility, registry raw-data and request contracts, owner denial and language changes');
})().catch(error=>{console.error(error);process.exitCode=1;});
