'use strict';
(() => {
 let value=null, busy=false, error='';
 const en=()=>I18n.language==='en';
 const copy=(ru,english)=>en()?english:ru;
 function row(parent,label,content){const item=document.createElement('div');item.className='system-row';const title=document.createElement('dt'),body=document.createElement('dd');title.textContent=label;body.textContent=content;item.append(title,body);parent.append(item);}
 function size(bytes){return (bytes/1024**3).toLocaleString(en()?'en':'ru',{maximumFractionDigits:1})+' GB';}
 function render(){
  const root=document.getElementById('hardware-view');if(!root)return;root.replaceChildren();
  const heading=document.createElement('h1');heading.textContent=copy('Железо','Hardware');root.append(heading);
  const refresh=document.createElement('button');refresh.type='button';refresh.className='text-button';refresh.textContent=copy('Обновить','Refresh');refresh.disabled=busy;refresh.onclick=()=>load(true);root.append(refresh);
  if(error){const message=document.createElement('p');message.setAttribute('role','alert');message.textContent=error;root.append(message);}
  if(!value){if(!busy&&!error)load();return;}
  const facts=document.createElement('dl');facts.className='system-facts';
  row(facts,copy('Система','System'),value.system+' '+value.release);
  row(facts,copy('Архитектура','Architecture'),value.architecture);
  if(value.logicalCpuCount!==null)row(facts,copy('Потоки CPU','Logical CPUs'),String(value.logicalCpuCount));
  if(value.physicalMemoryBytes!==null)row(facts,copy('Память','Memory'),size(value.physicalMemoryBytes));
  row(facts,copy('Диск данных · свободно','Data disk · free'),size(value.dataDisk.freeBytes)+' / '+size(value.dataDisk.totalBytes));
  row(facts,copy('Проверено','Observed'),new Date(value.observedAt).toLocaleString(en()?'en':'ru'));
  root.append(facts);
 }
 async function load(force=false){if(busy||value&&!force)return;busy=true;error='';render();try{value=await request('/api/hardware');}catch(e){error=e.message;}finally{busy=false;render();}}
 window.AgentCityHardware={render,load};
})();
