const {test,expect}=require('./owner-fixture.cjs');

async function processEditor(page){
 await page.goto('/#architecture');
 const repoId=await page.evaluate(async()=> (await request('/api/repositories')).repositories[0].id);
 await page.getByRole('textbox',{name:'Project ID',exact:true}).fill(repoId);
 return page.locator('#pipeline-editor');
}

test('stage edits survive selection and structural changes; successful save acknowledges the whole draft',async({page})=>{
 const editor=await processEditor(page);
 await editor.getByRole('textbox',{name:'Название этапа',exact:true}).fill('Review fixture');
 await editor.getByRole('button',{name:'Добавить этап',exact:true}).click();
 await editor.getByRole('textbox',{name:'Название этапа',exact:true}).fill('Work fixture');
 await editor.getByRole('tab',{name:'1. Review fixture',exact:true}).click();
 await expect(editor.getByRole('textbox',{name:'Название этапа',exact:true})).toHaveValue('Review fixture');
 expect((await page.evaluate(()=>agentCityDrafts.snapshot())).dirty).toBe(true);
 await editor.getByRole('tab',{name:'2. Work fixture',exact:true}).click();
 await editor.getByRole('button',{name:'Выше',exact:true}).click();
 await editor.getByRole('button',{name:'Добавить переход',exact:true}).click();
 await editor.getByRole('combobox',{name:'action',exact:true}).selectOption('next');
 await editor.getByRole('combobox',{name:'Целевой этап',exact:true}).selectOption({label:'Review fixture'});
 await editor.getByRole('button',{name:'Сохранить',exact:true}).click();
 await expect(editor.getByRole('status')).toHaveText('Конфигурация сохранена.');
 expect(await page.evaluate(()=>agentCityDrafts.snapshot())).toEqual({version:1,dirty:false,busy:false});
 await page.reload();
 await expect(editor.getByRole('textbox',{name:'Название этапа',exact:true})).toHaveValue('Work fixture');
 const saved=await page.evaluate(async()=> (await request('/api/pipelines')).pipelines[0]);
 expect(saved.stages.map(stage=>stage.name)).toEqual(['Work fixture','Review fixture']);
 expect(saved.stages[0].transitions[0].target).toBe(saved.stages[1].id);
 await expect(editor.getByRole('combobox',{name:'Целевой этап',exact:true})).toHaveValue(saved.stages[1].id);
});

test('canceling process replacement retains edits and does not write storage',async({page})=>{
 const editor=await processEditor(page),before=await page.evaluate(()=>request('/api/pipelines'));
 await editor.getByRole('textbox',{name:'Название этапа',exact:true}).fill('Keep this draft');
 await editor.getByRole('button',{name:'Новый',exact:true}).click();
 await page.getByRole('button',{name:'Вернуться к изменениям',exact:true}).click();
 await expect(editor.getByRole('textbox',{name:'Название этапа',exact:true})).toHaveValue('Keep this draft');
 expect(await page.evaluate(()=>request('/api/pipelines'))).toEqual(before);
 expect((await page.evaluate(()=>agentCityDrafts.snapshot())).dirty).toBe(true);
});
