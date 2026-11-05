/* Age quote evidence continuously, including paused and failed-refresh views. */
window.QuoteClock=(()=>{
 function label(q){
  const age=q.quote_time?(Date.now()-Date.parse(q.quote_time))/1000:null;
  const valid=age!==null&&Number.isFinite(age)&&age>=-5;
  const elapsed=valid?(age<60?Math.max(0,Math.round(age))+'s old':Math.round(age/60)+'m old'):(q.quote_time?'invalid quote timestamp':'exchange age unknown');
  return `${q.source||'Unknown'} · ${q.feed||'missing'} · ${q.session||'session unverified'} · ${elapsed}${valid&&age>30?' · stale for live review':''}`;
 }
 function html(q={}){return `<span data-quote-clock="${esc(JSON.stringify(q))}">${esc(label(q))}</span>`;}
 function tick(){
  document.querySelectorAll('[data-quote-clock]').forEach(el=>{try{el.textContent=label(JSON.parse(el.dataset.quoteClock));}catch{el.textContent='Quote clock unavailable';}});
  document.querySelectorAll('[data-quote-readiness]').forEach(el=>{const age=(Date.now()-Date.parse(el.dataset.quoteReadiness))/1000;el.textContent=Number.isFinite(age)&&age>30?'Quote check is over 30 seconds old — refresh before reviewing a trade.':'';});
 }
 setInterval(tick,1000);return {html,tick};
})();
