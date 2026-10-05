'use strict';
(() => {
 let value=null,busy=false,error='';
 const labels={'Tasks':['Задачи','Tasks'],'Executions':['Запуски','Executions'],'Processes':['Процессы','Processes'],'Standards':['Стандарты','Standards'],'Project standards':['Назначения стандартов','Project standards'],'Project profiles':['Профили проектов','Project profiles'],'Global rules':['Общие правила','Global rules'],'Source bindings':['Источники','Source bindings']};
 const copy=(ru,english)=>I18n.language==='en'?english:ru;
 function render(){
  const root=document.getElementById('architecture-storage-view');if(!root)return;root.replaceChildren();
  const title=document.createElement('h1');title.textContent=copy('Хранение','Storage');root.append(title);
  const refresh=document.createElement('button');refresh.type='button';refresh.className='text-button';refresh.textContent=copy('Обновить','Refresh');refresh.disabled=busy;refresh.onclick=()=>load(true);root.append(refresh);
  if(error){const message=document.createElement('p');message.setAttribute('role','alert');message.textContent=error;root.append(message);}
  if(!value){if(!busy&&!error)load();return;}
  const list=document.createElement('dl');list.className='system-facts';
  for(const location of value.locations){const item=document.createElement('div');item.className='system-row';const heading=document.createElement('dt'),body=document.createElement('dd'),path=document.createElement('code'),owner=document.createElement('small');heading.textContent=copy(...labels[location.name]);owner.textContent=location.owner;path.textContent=location.path||copy('Не подключено','Not connected');body.append(owner,path);item.append(heading,body);list.append(item);}
  root.append(list);
 }
 async function load(force=false){if(busy||value&&!force)return;busy=true;error='';render();try{value=await request('/api/storage-map');}catch(e){error=e.message;}finally{busy=false;render();}}
 window.AgentCityStorage={render,load};
})();
