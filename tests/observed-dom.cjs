// Tiny DOM recording for behavioral tests; not a layout/browser oracle.
class Node{
 constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.dataset={};this.attributes={};this.handlers={};this._text='';this.hidden=false;this.open=false;this.scrollTop=0;this.value='';this.className='';this.classList={toggle:(k,on)=>{const keys=new Set(this.className.split(' ').filter(Boolean));on?keys.add(k):keys.delete(k);this.className=[...keys].join(' ');}};}
 get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}set textContent(v){this._text=String(v);this.children=[];}
 get firstElementChild(){return this.children[0]||null;}
 get nextElementSibling(){if(!this.parentElement)return null;return this.parentElement.children[this.parentElement.children.indexOf(this)+1]||null;}
 get isConnected(){let n=this;while(n.parentElement)n=n.parentElement;return n===this.ownerDocument.documentElement;}
 insertBefore(n,cursor){if(n===cursor)return;if(n.parentElement)n.remove();const i=cursor?this.children.indexOf(cursor):this.children.length;if(i<0)throw Error('missing DOM cursor');this.children.splice(i,0,n);n.parentElement=this;}
 append(...nodes){for(const n of nodes){if(n.parentElement)n.remove();this.children.push(n);n.parentElement=this;}}
 after(node){const a=this.parentElement.children,index=a.indexOf(this);a.splice(index+1,0,node);node.parentElement=this.parentElement;}
 remove(){if(this.parentElement){const a=this.parentElement.children;a.splice(a.indexOf(this),1);this.parentElement=null;}}
 setAttribute(k,v){this.attributes[k]=String(v);}getAttribute(k){return this.attributes[k]??null;}removeAttribute(k){delete this.attributes[k];}
 addEventListener(type,fn){(this.handlers[type]??=[]).push(fn);}removeEventListener(type,fn){this.handlers[type]=(this.handlers[type]||[]).filter(x=>x!==fn);}
 click(){if(this.disabled)return;for(const fn of this.handlers.click||[])fn({target:this});}focus(){this.ownerDocument.activeElement=this;}
 closest(selector){let n=this;while(n){if(matches(n,selector))return n;n=n.parentElement;}return null;}
 querySelectorAll(selector){return all(this).filter(n=>selector.split(',').some(s=>matches(n,s.trim())));}querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}
const all=n=>n.children.flatMap(c=>[c,...all(c)]);
function matches(n,s){if(s.startsWith('.'))return s.split('.').slice(1).every(k=>n.className.split(' ').includes(k));const m=s.match(/^\[([^=]+)(?:="?([^"\]]+)"?)?\]$/);if(m){let v=m[1].startsWith('data-')?n.dataset[m[1].slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]:n.getAttribute(m[1]);return v!==undefined&&v!==null&&(m[2]===undefined||v===m[2]);}return n.tagName===s.toUpperCase();}
function document(){const d={createElement:tag=>new Node(tag,d),handlers:{},addEventListener:Node.prototype.addEventListener,removeEventListener:Node.prototype.removeEventListener};d.documentElement=new Node('html',d);d.body=new Node('body',d);d.documentElement.append(d.body);d.getElementById=id=>all(d.documentElement).find(n=>n.id===id)||null;d.querySelectorAll=s=>d.documentElement.querySelectorAll(s);d.querySelector=s=>d.documentElement.querySelector(s);return d;}
module.exports={Node,document,all};
