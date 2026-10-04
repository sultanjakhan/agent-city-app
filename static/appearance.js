/* Local UI preference; no connection, policy or runtime data. */
(()=>{const key='agent-city.theme',media=matchMedia('(prefers-color-scheme: dark)');let choice='system';try{const stored=localStorage.getItem(key);if(['system','light','dark'].includes(stored))choice=stored;}catch{}
 function apply(){document.documentElement.dataset.theme=choice==='system'?(media.matches?'dark':'light'):choice;}
 apply();media.addEventListener('change',apply);const select=document.getElementById('appearance-theme');select.value=choice;select.addEventListener('change',()=>{choice=select.value;try{localStorage.setItem(key,choice);}catch{}apply();});
})();
