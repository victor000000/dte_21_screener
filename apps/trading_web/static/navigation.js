/* Explicit, allowlisted deep links for every workspace view. */
window.WorkspaceNavigation=(()=>{
 const pages=new Set(['positions','chain','cn','cn-risk','orders','logs','risk','screening','attribution','data']);
 const current=()=>pages.has(location.hash.slice(1))?location.hash.slice(1):'positions';
 function go(target){if(!pages.has(target))return;page=target;history.pushState(null,'','#'+target);render();}
 addEventListener('popstate',()=>{page=current();render();});
 addEventListener('hashchange',()=>{page=current();render();});
 return {current,go};
})();
