// Only independently authored components and synthetic metadata; no private baseline.
const {test,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../static/observed-work.js'),'utf8');
const css=fs.readFileSync(path.join(__dirname,'../static/observed-work.css'),'utf8');
test('synthetic responsive view and polling state preservation',async({page},info)=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Agent City · synthetic fixture</title><style>body{margin:0;padding:20px}</style><p>Синтетические данные</p><div id="test-root"></div></html>');
 await page.addStyleTag({content:css});await page.addScriptTag({content:code});
 await page.evaluate(()=>{
  const s={id:'synthetic-session',projectId:'synthetic-project',agentId:'synthetic-agent',name:'Сессия',status:'working',coverage:'partial',scope:{kind:'turn',id:'synthetic-turn'},startedAt:'2026-01-01T10:00:00Z',durationMs:null,usage:{input:9000000000,output:null,total:null,cachedInput:2},model:'synthetic-model-with-a-realistically-long-opaque-identifier',task:{title:'Проверить длинное название задачи и устойчивое поведение обновлений интерфейса',identity:{taskKey:'synthetic-opaque-task-key'}},events:[{id:'synthetic-event',at:'2026-01-01T10:00:01Z',label:'Наблюдаемое событие'}],appliedSkills:[{id:'synthetic-use',skillId:'synthetic-explicitly-applied-skill',kind:'applied',source:'executor-reported'}]};
  window.fixture={source:{status:'partial',message:'Только синтетический источник'},projects:[{id:s.projectId,name:'Синтетический проект'}],agents:[{id:s.agentId,projectId:s.projectId,name:'Координатор'}],sessions:[s]};
  window.ui=AgentCityObserved.mount(document.getElementById('test-root'));window.ui.update(window.fixture);
 });
 await page.locator('.ow-session').click();await page.getByText('Точный расход токенов',{exact:true}).click();
 const summary=page.getByText('Точный расход токенов',{exact:true});await summary.focus();
 await page.evaluate(()=>{window.focused=document.activeElement;window.fixture.sessions[0].status='completed';window.fixture.source.status='stale';window.ui.update(window.fixture);});
 expect(await page.evaluate(()=>document.activeElement===window.focused)).toBe(true);
 await expect(page.locator('.ow-detail')).toBeVisible();await expect(page.locator('.ow-disclosure').first()).toHaveAttribute('open','');
 expect(await page.evaluate(()=>window.ui.model.route.sessionId)).toBe('synthetic-session');
 expect(await page.evaluate(()=>window.ui.model.rows('history').length)).toBe(1);
 for(const [name,width,height] of [['desktop',1280,900],['narrow',700,900],['mobile',390,844]]){
  await page.setViewportSize({width,height});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(name+'.png'),fullPage:true});
 }
 expect(errors).toEqual([]);
});
