// Real local-site smoke test: permit read-only risk estimation; block all other POSTs.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
(async()=>{
 const out=path.resolve(__dirname,'../../.local/trading-web/ego-051-live-'+new Date().toISOString().replace(/[:.]/g,'-'));fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE_PATH});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],blocked=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',route=>{const q=route.request(),url=new URL(q.url());
  if(q.method()!=='GET'&&url.pathname!=='/api/risk'){blocked.push(url.pathname);return route.abort();}
  return route.continue();
 });
 try{
  await page.goto('http://localhost:8765/#risk');await page.waitForFunction(()=>typeof session!=='undefined'&&session);
  await page.locator('#workspace-auto').uncheck();await page.locator('#risk-auto').uncheck();await page.locator('#live-quotes').uncheck();
  await page.selectOption('#broker','ibkr');await page.waitForFunction(()=>!busy);
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/risk',{timeout:90000});
  await page.locator('#risk-current').click();const r=await response,body=await r.json();assert.equal(r.status(),200);
  await page.locator('#page-content tbody tr').first().waitFor();assert.equal(await page.locator('#page-content tbody tr').count(),6);
  assert.equal(await page.title(),'Options workspace · 0.5.1');
  const version=await page.evaluate(()=>session.version);assert.equal(version,'0.5.1');
  await page.screenshot({path:path.join(out,'risk-real.png'),fullPage:true});
  for(const id of ['screening','attribution']){await page.locator(`[data-page="${id}"]`).click();await page.waitForTimeout(800);assert.equal(await page.locator('main h1').count(),1);}
  assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
  const result={version,browser:'Ego Lite',browserVersion:await browser.version(),riskStatus:body.status,horizons:body.horizons.length,errors,blocked,execution:'No orders submitted or cancelled'};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({...result,out}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
