const {test,expect}=require('./owner-fixture.cjs');
test('all catalog keeps unknown, speech, moderation and structured rows without model requests',async({page})=>{
 const writes=[];page.on('request',r=>{if(r.method()==='POST')writes.push(new URL(r.url()).pathname);});
 await page.route('**/api/state',async route=>{const data=await(await route.fetch()).json();data.sources.find(s=>s.id==='zen').catalogPolicy='all';data.credentials.zen=true;data.catalogs.zen.models=['unknown','audio','moderation','structured'].map(kind=>({id:`test-${kind}`,name:`Typed ${kind}`,kind,developer:'unknown',priceVerified:false}));await route.fulfill({json:data});});
 await page.goto('/#models');await page.locator('#toggle-filters').click();await page.locator('#provider-filter').selectOption('zen');await expect(page.locator('.model-row')).toHaveCount(4);
 for(const kind of ['unknown','audio','moderation','structured']){
  await page.getByRole('button',{name:`Typed ${kind}`,exact:true}).click();await expect(page.locator('#dialog-id')).toHaveText(`test-${kind}`);await expect(page.locator('#dialog-routes').getByRole('button',{name:'Проверить',exact:true})).toHaveCount(0);await expect(page.locator('#dialog-routes').getByRole('button',{name:'Условия доступа',exact:true})).toBeVisible();await page.keyboard.press('Escape');
 }
 expect(writes).toEqual([]);
});
