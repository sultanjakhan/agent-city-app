const {test,expect}=require('./owner-fixture.cjs');

test.afterEach(async({page})=>{await page.unrouteAll({behavior:'wait'});});

for(const readFails of [false,true]){
 test(`extension conflict preserves draft and retries with fresh revision${readFails?' after a failed reload':''}`,async({page})=>{
  const errors=[],writes=[];page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(new URL(request.url()).pathname==='/api/extensions/save')writes.push(request.postDataJSON());});
  await page.goto('/#extensions');await expect(page.locator('.library-row').first()).toBeVisible();
  const initial=await(await page.request.get('/api/extensions')).json();
  const project=initial.projects[0],draftName=readFails?'Conflict draft after reload failure':'Conflict retained draft';
  await page.locator('.library-row').filter({has:page.getByRole('heading',{name:project.name,exact:true})}).getByRole('button',{name:'Изменить',exact:true}).click();
  await page.locator('#project-name').fill(draftName);
  const state=await(await page.request.get('/api/state')).json();
  const external=await page.request.post('/api/extensions/save',{
   data:{project:{...project,name:'External synthetic update'},revision:initial.revision},
   headers:{'X-Agent-City':'1','X-Agent-City-Token':state.csrfToken},
  });
  expect(external.status()).toBe(200);const newer=await external.json();expect(newer.revision).not.toBe(initial.revision);
  let failNextRead=readFails;
  if(readFails)await page.route('**/api/extensions',async route=>{
   if(failNextRead){failNextRead=false;await route.fulfill({status:503,json:{error:'Synthetic revision reload failed'}});}
   else await route.continue();
  });
  await page.locator('#save-project').click();
  await expect(page.locator('#project-error')).toContainText('Библиотека изменена');
  await expect(page.locator('#save-project')).toBeEnabled();
  await expect(page.locator('#project-name')).toHaveValue(draftName);
  await expect(page.locator('#project-dialog')).toBeVisible();
  expect(writes).toHaveLength(1);expect(writes[0].revision).toBe(initial.revision);
  if(readFails){
   // Keeping the old snapshot prevents a null dereference. The next explicit
   // save conflicts again and successfully reloads the current revision.
   const conflict=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/extensions/save');
   await page.locator('#save-project').click();expect((await conflict).status()).toBe(409);
   await expect(page.locator('#save-project')).toBeEnabled();
   await expect(page.locator('#project-name')).toHaveValue(draftName);
   expect(writes).toHaveLength(2);
  }
  const saved=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/extensions/save');
  await page.locator('#save-project').click();expect((await saved).status()).toBe(200);
  await expect(page.locator('#project-dialog')).toBeHidden();
  expect(writes.at(-1).revision).toBe(newer.revision);expect(writes.at(-1).project.id).toBe(project.id);
  const stored=await(await page.request.get('/api/extensions')).json();
  expect(stored.projects.find(row=>row.id===project.id).name).toBe(draftName);
  expect(stored.projects.filter(row=>row.id===project.id)).toHaveLength(1);
  await page.reload();await expect(page.getByRole('heading',{name:draftName,exact:true})).toBeVisible();
  expect(errors).toEqual([]);
 });
}
