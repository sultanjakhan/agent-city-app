/* Capability lives only in launcher memory and a removed URL fragment.
   The browser receives a session cookie without Expires/Max-Age; server authority
   lives only in this process. No localStorage/sessionStorage or secret logging. */
(()=>{
 let capability=null;const fragment=location.hash;
 if(fragment.startsWith('#owner-bootstrap=')){capability=fragment.slice(17);history.replaceState(null,'',location.pathname+location.search+'#dashboard');}
 let blocked=null;
 const copy=message=>typeof I18n==='undefined'?message:I18n.t(message);
 let ownerCopy=[];
 function renderCopy(){for(const [node,key] of ownerCopy)node.textContent=copy(key);}
 document.addEventListener('agentcity-language-change',renderCopy);
 function lock(){if(blocked)return;ownerCopy=[];blocked=document.createElement('dialog');blocked.id='owner-session-dialog';const title=document.createElement('h2');title.id='owner-session-title';blocked.setAttribute('aria-labelledby',title.id);title.textContent=copy("Сессия Agent City недоступна");ownerCopy.push([title,"Сессия Agent City недоступна"]);const message=document.createElement('p');message.textContent=copy("Откройте приложение через его launcher. Если сервер перезапущен или браузерная сессия потеряна, требуется новый запуск через launcher. Черновики в этой вкладке сохранены.");ownerCopy.push([message,"Откройте приложение через его launcher. Если сервер перезапущен или браузерная сессия потеряна, требуется новый запуск через launcher. Черновики в этой вкладке сохранены."]);const retry=document.createElement('button');retry.type='button';retry.textContent=copy("Проверить сессию снова");ownerCopy.push([retry,"Проверить сессию снова"]);retry.onclick=async()=>{retry.disabled=true;window.agentCityOwnerReady=connect();if(await window.agentCityOwnerReady){if(typeof load==='function')load();}else retry.disabled=false;};blocked.addEventListener('cancel',event=>event.preventDefault());blocked.append(title,message,retry);document.body.append(blocked);blocked.showModal();}
 async function connect(){try{
   if(capability){const value=capability;capability=null;const response=await fetch('/api/owner-bootstrap',{method:'POST',headers:{'Content-Type':'application/json','X-Agent-City':'1'},body:JSON.stringify({capability:value})});if(!response.ok)throw Error();}
   const response=await fetch('/api/owner-session');if(!response.ok)throw Error();
   if(blocked){blocked.close();blocked.remove();blocked=null;}return true;
 }catch{lock();return false;}}
 window.agentCityOwnerDenied=lock;window.agentCityOwnerReady=connect();
})();
