const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/victo/AppData/Local/OpenAI/Codex/runtimes/cua_node/1fb7137c46617d50/bin/node_modules/playwright');
(async()=>{
const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[];let writes=0,fail=false;
page.on('pageerror',e=>errors.push(e.message));
const json=(r,d)=>r.fulfill({json:d});
await page.route('**/api/**',async route=>{
 const req=route.request(),u=new URL(req.url());if(req.method()!=='GET'){writes++;return route.abort();}
 if(u.pathname==='/api/snapshot')return json(route,{account:{id:'PRIVATE_ACCOUNT',source:'IBKR fixture',equity:100000,buying_power:50000},positions:[{symbol:'SPY261120P00760000',qty:-2,average:10,mark:9,pnl:200,asset_class:'us_option',source:'Isolated test holdings'},{symbol:'SPY261120C00760000',qty:1,average:10,mark:11,pnl:100,asset_class:'us_option',source:'Isolated test holdings'}],orders:[],fills:[],received_at:new Date().toISOString()});
 if(u.pathname==='/api/receipts')return json(route,[]);
 if(u.pathname==='/api/market/connections')return json(route,{});
 if(u.pathname==='/api/market/underlying')return json(route,{observations:[],sources:[]});
 if(u.pathname==='/api/market/expiries')return json(route,{expiries:['2026-11-27']});
 const quote=s=>({symbol:s,bid:8,ask:9,bid_size:10,ask_size:10,source:'Test fixture',feed:'live',quote_time:new Date().toISOString(),received_at:new Date().toISOString()});
 if(u.pathname==='/api/market/chain')return json(route,{source:'fixture',rows:[{symbol:'SPY261127P00765000',underlying:'SPY',expiry:'2026-11-27',strike:765,right:'P',quote:quote('SPY261127P00765000')},{symbol:'SPY261127P00770000',underlying:'SPY',expiry:'2026-11-27',strike:770,right:'P',quote:null}]});
 if(u.pathname==='/api/market/quotes'){requests.push(u.searchParams.get('symbols'));if(fail)return route.fulfill({status:502,json:{error:'Simulated source outage'}});return json(route,{source:'fixture',rows:u.searchParams.get('symbols').split(',').map(s=>({symbol:s,quote:quote(s)}))});}
 return route.continue();
});
await page.goto('http://localhost:8765/#positions');await page.selectOption('#broker','ibkr');await page.locator('[data-close="SPY261120P00760000"]').waitFor();
await page.locator('[data-close="SPY261120P00760000"]').click();await page.waitForFunction(()=>document.querySelector('#ticket-quotes').textContent.includes('Test fixture'));
if(await page.locator('[data-key="intent"]').inputValue()!=='buy_to_close')throw Error('Short close intent');
await page.locator('[data-close="SPY261120C00760000"]').click();await page.waitForFunction(()=>document.querySelector('#ticket-quotes').textContent.includes('SPY261120C00760000'));
if(await page.locator('[data-key="intent"]').inputValue()!=='sell_to_close')throw Error('Long close intent');
await page.locator('[data-roll="SPY261120P00760000"]').click();await page.waitForFunction(()=>document.querySelector('#ticket-quotes').textContent.includes('Partial ticket quotes'));
if(!requests.at(-1).includes('SPY261120P00760000'))throw Error('Incomplete roll blocks close quote');
await page.locator('[data-page="chain"]').click();await page.locator('#load-expiries').click();await page.waitForFunction(()=>document.querySelector('#chain-expiry').value==='2026-11-27');await page.locator('#load-chain').click();await page.locator('[data-sell-chain="0"]').waitFor();
if(await page.locator('#chain-table .table-controls').count()!==1)throw Error('Chain controls absent');
await page.locator('[data-sell-chain="0"]').click();await page.waitForFunction(()=>document.querySelector('#ticket-quotes').textContent.includes('SPY261127P00765000'));
if(await page.locator('[data-key="intent"]').count()!==2)throw Error('Chain added third leg instead of filling roll');
if(await page.locator('[data-key="qty"]').nth(1).inputValue()!=='2')throw Error('Roll quantity lost');
if(!requests.at(-1).includes(','))throw Error('Both roll legs not quoted');
await page.locator('#live-quotes').uncheck();await page.locator('#chain-auto').uncheck();
fail=true;await page.locator('#refresh-quotes').click();await page.locator('.quote-refresh-error').waitFor();if(!await page.locator('#ticket-quotes').textContent().then(t=>t.includes('SPY261127P00765000')))throw Error('Failure discarded prior evidence');
await page.clock.setFixedTime(new Date(Date.now()+120000));await page.waitForTimeout(1300);
if(!await page.locator('#ticket-quotes').textContent().then(t=>t.includes('stale for live review')))throw Error('Paused quote ages frozen');
await page.locator('#new-ticket').click();await page.locator('[data-buy-chain="1"]').click();if(await page.locator('#limit').inputValue()!=='')throw Error('Missing quote invented limit');
await page.setViewportSize({width:390,height:844});const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
console.log(JSON.stringify({version:await page.title(),closeBothDirections:true,partialRollQuotes:true,rollChainReplacement:true,quoteFailureEvidence:true,ageWhilePaused:true,missingQuoteSafe:true,errors,writes,overflow}));
await browser.close();if(errors.length||writes||overflow)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
