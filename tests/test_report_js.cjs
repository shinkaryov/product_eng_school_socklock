// Lightweight JS behavior checks using DOM stubs. Does not test browser layout.
// Usage: node tests/test_report_js.cjs demo_output/report.html
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8'),payload=html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1],script=html.match(/<\/script><script>([\s\S]*?)<\/script>/)[1];
const elements={};
function element(id){return elements[id]??(elements[id]={value:id==='sort'?'priority':'',textContent:id==='data'?payload:'',innerHTML:'',events:{},addEventListener(name,fn){this.events[name]=fn}})}
let exported=null;const document={getElementById:element,createElement(){return {click(){}}}};
const ctx={document,console,Intl,Blob,URL:{createObjectURL(b){exported=b;return 'blob:test'},revokeObjectURL(){}},setTimeout:f=>f()};vm.createContext(ctx);vm.runInContext(script,ctx);
assert.equal(element('currency').value,'USD');assert.equal((element('rows').innerHTML.match(/<tr>/g)||[]).length,7);assert.ok(element('timeline').innerHTML.includes('<svg'));assert.ok(element('bars').innerHTML.includes('<svg'));assert.ok(element('actions').innerHTML.includes('DECLINE_REVIEW'));
element('currency').value='EUR';element('currency').events.change();assert.equal((element('rows').innerHTML.match(/<tr>/g)||[]).length,1);assert.ok(!element('rows').innerHTML.includes('steady_winner'));
element('currency').value='USD';element('currency').events.change();element('status').value='KILL_REVIEW';element('status').events.input();assert.equal((element('rows').innerHTML.match(/<tr>/g)||[]).length,2);
element('search').value='no_sales';element('search').events.input();assert.equal((element('rows').innerHTML.match(/<tr>/g)||[]).length,1);element('download').onclick();assert.ok(exported instanceof Blob);
element('search').value='';element('status').value='';element('sort').value='egp';element('sort').events.input();assert.ok(element('rows').innerHTML.indexOf('steady_winner')<element('rows').innerHTML.indexOf('declining'));
console.log('PASS: JS rendering, two SVG charts, currency/status/search filters, sorting, CSV export. Browser layout not tested.');
