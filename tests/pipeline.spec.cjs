const {test,expect}=require('./owner-fixture.cjs');
test('technical pipeline editor saves and previews without execution',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/#architecture');await expect(page.locator('#pipeline-editor')).toContainText('Только технические пайплайны');
 const repo=(await (await page.request.get('/api/repositories')).json()).repositories[0];
 await page.getByLabel('Project ID',{exact:true}).fill(repo.id);
 await page.getByText('Лимиты пайплайна',{exact:true}).click();
 await page.locator('#pipeline-editor > details').first().getByLabel('tokens',{exact:true}).fill('100');
 await page.getByRole('button',{name:'Preview правил и конфликтов',exact:true}).click();
 await expect(page.locator('#pipeline-editor pre')).toContainText('"canRun": false');
 await expect(page.locator('#pipeline-editor pre')).toContainText('repository-profiles.json');
 await expect(page.locator('#pipeline-editor pre')).toContainText('\"projectBudgetSupport\": \"unknown\"');
 await page.getByRole('button',{name:'Сохранить конфигурацию',exact:true}).click();
 await expect(page.locator('#pipeline-editor pre')).toContainText('Конфигурация сохранена');
 await page.reload();await expect(page.getByLabel('Project ID',{exact:true})).toHaveValue(repo.id);
 await page.screenshot({path:'test-results/pipeline-architecture.png',fullPage:true});
 expect(errors).toEqual([]);
});
