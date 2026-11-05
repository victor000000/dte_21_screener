const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const {fixture}=require('./fixtures_051.cjs');
(async()=>{
 const output=path.resolve(__dirname,'../../.local/trading-web/ego-051-'+new Date().toISOString().replace(/[:.]/g,'-'));fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE_PATH});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
 const state={riskCalls:0,blockedWrites:[],holdRisk:false,currency:'USD'},errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date()});
 await page.route('**/api/**',r=>fixture(r,state));
 try{
  await page.goto('http://localhost:8765/#risk');await page.waitForFunction(()=>typeof session!=='undefined'&&session);
  await page.selectOption('#broker','ibkr');await page.waitForFunction(()=>snapshot!==null);
  await page.locator('#risk-auto').uncheck();await page.locator('#workspace-auto').uncheck();await page.locator('#live-quotes').uncheck();
  await page.locator('#risk-current').click();await page.getByText('TEST FIXTURE — NO BROKER DATA. Diagnostic only.',{exact:false}).first().waitFor();
  assert.equal(await page.locator('#page-content tbody tr').count(),6);checks.push('Six risk horizons render');
  await page.locator('#risk-draft').click();await page.waitForFunction(()=>document.querySelector('#page-content').textContent.includes('Hypothetical ticket included'));
  await page.screenshot({path:path.join(output,'risk-desktop.png'),fullPage:true});
  await page.locator('[data-key="underlying"]').fill('SPY');
  assert.equal(await page.locator('#page-content').textContent().then(t=>t.includes('Hypothetical ticket included')),false,'Editing a ticket must immediately remove old risk numbers from the main page');
  checks.push('Draft edit removes stale comparison');
  state.holdRisk=true;await page.locator('#risk-draft').click();await page.waitForFunction(()=>document.querySelector('#risk-draft').disabled);
  await page.locator('[data-key="strike"]').fill('600');while(!state.releaseRisk)await new Promise(r=>setTimeout(r,10));state.releaseRisk();state.holdRisk=false;
  await page.waitForFunction(()=>!document.querySelector('#estimate-risk').disabled);
  assert.equal(await page.locator('#page-content').textContent().then(t=>t.includes('Hypothetical ticket included')),false);checks.push('Delayed response discarded after edit');
  state.currency='EUR';await page.locator('#risk-current').click();await page.waitForFunction(()=>document.querySelector('#page-content').textContent.includes('€100,000'));
  const stats=await page.locator('.stats').textContent();assert.ok(!stats.includes('$5,000')&&!stats.includes('$10,000'),'Non-USD account budgets must not be labeled USD');checks.push('Account budget currency');state.currency='USD';
  await page.locator('#risk-current').click();await page.waitForFunction(()=>document.querySelector('.stats').textContent.includes('$100,000'));
  await page.locator('#risk-auto').check();
  let count=state.riskCalls;await page.clock.fastForward(65000);assert.equal(state.riskCalls,count,'Workspace pause must stop risk auto-refresh');
  await page.locator('#workspace-auto').check();await page.clock.fastForward(5000);await page.waitForFunction(()=>!document.querySelector('#estimate-risk').disabled);assert.ok(state.riskCalls>count,'Visible risk must auto-refresh');
  checks.push('Risk automatic refresh and workspace pause');await page.locator('#workspace-auto').uncheck();await page.locator('#risk-auto').uncheck();
  for(const width of [390,768,1440]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Risk overflow at ${width}`);}
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'risk-mobile.png'),fullPage:true});checks.push('Responsive risk widths');
  await page.setViewportSize({width:1440,height:1000});
  for(const id of ['positions','chain','cn','cn-risk','orders','logs','risk','screening','attribution','data']){
   await page.locator(`[data-page="${id}"]`).click();await page.waitForTimeout(150);assert.equal(await page.locator('main h1').count(),1,id+' heading');
   if(id==='data')await page.locator('#data-auto').uncheck();
   assert.equal(await page.locator(`[data-page="${id}"]`).getAttribute('aria-current'),'page');
  }
  checks.push('All ten navigation views');assert.deepEqual(errors,[]);assert.deepEqual(state.blockedWrites,[]);
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({browser:'Ego Lite',version:await browser.version(),checks,errors,blockedWrites:state.blockedWrites},null,2));
  console.log(JSON.stringify({passed:true,checks,output,errors}));
 }catch(e){await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});console.error(JSON.stringify({checks,errors,output}));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
