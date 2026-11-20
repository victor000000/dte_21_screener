/* Exercise underlying refresh with deferred, synthetic responses. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ticker = {value: 'SPY'};
const panel = {};
const requests = [];
const context = {
    window: {},
    document: {},
    $: selector => ({'#chain-symbol': ticker, '#underlying-live': panel})[selector],
    setInterval() {},
    esc: String,
    time: String,
    money: String,
    api(url) {
        return new Promise((resolve, reject) => requests.push({url, resolve, reject}));
    },
};
vm.createContext(context);
const modulePath = path.resolve(__dirname, '../../../apps/trading_web/static/live-ui.js');
vm.runInContext(fs.readFileSync(modulePath, 'utf8'), context);

async function run() {
    const live = context.window.LiveUI;
    const old = live.load('SPY');
    live.clear();
    const current = live.load('SPY');
    assert.equal(requests.length, 2, 'reloading a cleared context must start a new request');

    requests[0].resolve({observations: [], note: 'prior context'});
    await old;
    assert.doesNotMatch(panel.innerHTML, /prior context/);
    assert.match(panel.innerHTML, /Refreshing/);

    requests[1].resolve({observations: [], note: 'current context'});
    await current;
    assert.match(panel.innerHTML, /current context/);
    assert.doesNotMatch(panel.innerHTML, /Refreshing/);

    const superseded = live.load('SPY', true);
    ticker.value = 'QQQ';
    live.clear();
    const replacement = live.load('QQQ');
    assert.match(requests[3].url, /symbol=QQQ$/);
    requests[2].reject(new Error('old request failed'));
    await superseded;
    assert.doesNotMatch(panel.innerHTML, /old request failed|current context/);
    requests[3].resolve({observations: [], note: 'replacement context'});
    await replacement;
    assert.match(panel.innerHTML, /replacement context/);
}

run().then(() => console.log('Underlying quotes ignore superseded results and errors.'), error => {
    console.error(error);
    process.exitCode = 1;
});
