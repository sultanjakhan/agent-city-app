'use strict';
// A website is a reference, not an API endpoint. No automatic fetching or inference.
let providerSaving=false,providerRemoving=null,providerDraft='',providerAddedId=null;
function adoptProviderState(snapshot){providerStateEpoch++;state=snapshot;render();}
async function providerRequest(path,body){
 const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),15000);
 try{
  const response=await fetch(path,{signal:controller.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json','X-Agent-City':'1','X-Agent-City-Token':state?.csrfToken||''},body:JSON.stringify(body)}:{})});
  const data=await response.json();
  if(!response.ok){const error=Error(data.error||t('Не удалось выполнить запрос'));error.status=response.status;throw error;}
  return data;
 }catch(error){
  if(!error.status)throw Error(t('Ответ не получен. Перед повтором проверь список: изменение могло сохраниться.'));
  throw error;
 }finally{clearTimeout(deadline);}
}
function providerBusy(value){
 providerSaving=value;
 for(const id of ['provider-website','provider-api-key','save-provider','close-provider','confirm-remove-provider','cancel-remove-provider'])$(id).disabled=value;
 $('save-provider').textContent=t(value?'Сохранение…':providerAddedId?'Сохранить ключ':'Добавить');
 $('confirm-remove-provider').textContent=t(value?'Сохранение…':'Удалить провайдера');
}
$('add-provider').addEventListener('click',()=>{
 if(providerSaving)return;
 $('provider-form').reset();$('provider-error').textContent='';providerDraft='';providerAddedId=null;$('provider-website').readOnly=false;$('save-provider').textContent=t('Добавить');
 $('provider-dialog').showModal();$('provider-website').focus();
});
function closeProvider(){
 if(providerSaving)return;
 if(($('provider-website').value!==providerDraft||$('provider-api-key').value)&&!confirm(t('Закрыть без сохранения?')))return;
 $('provider-dialog').close();
}
$('close-provider').addEventListener('click',closeProvider);
$('provider-dialog').addEventListener('cancel',e=>{e.preventDefault();closeProvider();});
$('provider-dialog').addEventListener('close',()=>{$('provider-api-key').value='';});
$('provider-form').addEventListener('submit',async e=>{
 e.preventDefault();if(providerSaving||!state?.providerRegistry)return;
 if(keyAction){$('provider-error').textContent=t('Дождись сохранения ключа');return;}
 providerBusy(true);$('provider-error').textContent='';let savingKey=false;
 try{
  const key=$('provider-api-key').value.trim();
  if(!providerAddedId){
   let resolution;
   if(key){resolution=await providerRequest('/api/providers/resolve',{website:$('provider-website').value});if(!resolution.keySupported)throw Error(t('Для этого сайта ввод ключа не поддерживается. Добавь провайдера без ключа.'));}
   const snapshot=await providerRequest('/api/providers/add',{website:$('provider-website').value,revision:state.providerRegistry.revision});adoptProviderState(snapshot);
   providerDraft=$('provider-website').value;
   if(key){providerAddedId=resolution.id;$('provider-website').readOnly=true;}
  }
  if(key){savingKey=true;keyAction='provider-add';const snapshot=await providerRequest('/api/credential',{provider:providerAddedId,action:'save',key});$('provider-api-key').value='';adoptProviderState(snapshot);}
  $('provider-dialog').close();render();toast('Провайдер сохранён.');
 }catch(error){
  $('provider-error').textContent=savingKey?t(error.status?'Провайдер сохранён, но ключ не сохранён. Повтори сохранение ключа или закрой окно; провайдер останется в списке.':'Сохранение ключа не подтверждено. Провайдер остаётся в списке. Перед повтором проверь его состояние.'):t(error.message);
  if(!savingKey&&error.status===409)try{adoptProviderState(await providerRequest('/api/state'));}catch{}
 }finally{if(keyAction==='provider-add')keyAction=null;providerBusy(false);}
});
function openRemoveProvider(source){
 if(providerSaving)return;
 providerRemoving=source;$('remove-provider-name').textContent=source.name;
 $('remove-provider-error').textContent='';$('remove-provider-dialog').showModal();
}
$('cancel-remove-provider').addEventListener('click',()=>{if(!providerSaving)$('remove-provider-dialog').close();});
$('remove-provider-dialog').addEventListener('cancel',e=>{if(providerSaving)e.preventDefault();});
$('confirm-remove-provider').addEventListener('click',async()=>{
 if(providerSaving||!providerRemoving)return;
 providerBusy(true);$('remove-provider-error').textContent='';
 try{
  const snapshot=await providerRequest('/api/providers/remove',{id:providerRemoving.id,revision:state.providerRegistry.revision});adoptProviderState(snapshot);
  $('remove-provider-dialog').close();render();toast('Провайдер удалён из списка.');
 }catch(error){
  $('remove-provider-error').textContent=t(error.message);
  if(error.status===409)try{adoptProviderState(await providerRequest('/api/state'));}catch{}
 }finally{providerBusy(false);}
});
window.addEventListener('beforeunload',e=>{
 if(providerSaving||($('provider-dialog').open&&($('provider-website').value!==providerDraft||$('provider-api-key').value))){e.preventDefault();e.returnValue='';}
});
