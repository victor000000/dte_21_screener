/* Operate on loaded rows only; move existing nodes to preserve trade actions. */
window.TableUI=(()=>{
 const states=new Map();
 const safe=value=>{let s=String(value).replaceAll('"','""');if(/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s+'"';};
 function bind(){document.querySelectorAll('#page-content table').forEach((table,index)=>{
  if(table.dataset.controls)return;table.dataset.controls='true';
  const scroll=table.closest('.table-scroll');if(scroll){scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label',table.caption?.textContent||'Scrollable data table');}
  const key=page+':'+index, state=states.get(key)||{filter:'',column:-1,ascending:true};states.set(key,state);
  const rows=[...table.tBodies[0]?.rows||[]], heads=[...table.querySelectorAll('thead th')];
  const bar=document.createElement('div');bar.className='table-controls';
  const input=document.createElement('input');input.type='search';input.placeholder='Filter loaded rows';input.setAttribute('aria-label','Filter loaded table '+(index+1));input.value=state.filter;
  const count=document.createElement('span');count.className='muted';
  const download=document.createElement('button');download.textContent='Export visible CSV';download.type='button';
  bar.append(input,count,download);table.parentNode.insertBefore(bar,table);
  function apply(){rows.forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(state.filter.toLowerCase()));
   if(state.column>=0){const val=r=>r.cells[state.column]?.textContent.trim()||'';
    const num=s=>/^[¥$−+\-\d,.%\s]+$/.test(s)?Number(s.replace(/[¥$,%\s]/g,'').replace('−','-')):NaN;
    [...rows].sort((a,b)=>{const x=val(a),y=val(b),nx=num(x),ny=num(y);return (Number.isFinite(nx)&&Number.isFinite(ny)?nx-ny:x.localeCompare(y,undefined,{numeric:true}))*(state.ascending?1:-1);}).forEach(row=>table.tBodies[0].append(row));
   }
   heads.forEach((h,i)=>h.setAttribute('aria-sort',i===state.column?(state.ascending?'ascending':'descending'):'none'));
   count.textContent=rows.filter(r=>!r.hidden).length+'/'+rows.length+' loaded rows';
  }
  heads.forEach((h,i)=>{if(!h.textContent.trim())return;const b=document.createElement('button');b.textContent=h.textContent;b.title='Sort loaded rows';h.replaceChildren(b);b.onclick=()=>{state.ascending=state.column===i?!state.ascending:true;state.column=i;apply();};});
  input.oninput=()=>{state.filter=input.value;apply();};
  download.onclick=()=>{const selected=[heads.map(h=>h.textContent),...[...table.tBodies[0].rows].filter(r=>!r.hidden).map(r=>[...r.cells].map(c=>c.innerText))];const url=URL.createObjectURL(new Blob(['\uFEFF'+selected.map(r=>r.map(safe).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=page+'-loaded-table-'+(index+1)+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};apply();
 });}
 return {bind};
})();
