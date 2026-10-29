const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('ubt-platform/index.html','utf8');
const code=html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const storage=new Map(),session=new Map(),els=new Map();let selected=null;
function el(id){if(!els.has(id))els.set(id,{value:'',classList:{add(){},remove(){},toggle(){}},replaceChildren(){},innerHTML:'',innerText:'',disabled:false});return els.get(id)}
const context={console,Date,Math,JSON,Number,String,Object,Array,window:{scrollTo(){}},document:{getElementById:el,querySelector:s=>s==='input[name="recheck"]:checked'?selected:el(s),createTextNode:s=>s},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},sessionStorage:{getItem:k=>session.get(k),setItem:(k,v)=>session.set(k,v),removeItem:k=>session.delete(k)},alert(){},confirm:()=>true,setInterval:()=>1,clearInterval(){},setTimeout(){}};
vm.createContext(context);vm.runInContext(code,context);const run=s=>vm.runInContext(s,context);
run(`currentUser='one@example.com';persistUser();`);
for(const [id,bank] of Object.entries(run('localQuestionBank'))){assert(bank.length>=5,id);for(const q of bank){assert(q.recheck,id);assert(q.options[q.correct_idx]);assert.equal(q.skill_id,q.recheck.skill_id);assert.equal(q.topic,q.recheck.topic)}}
run(`startDiagnosticTest('math_lit');userAnswers={};submitTest();`);
assert.equal(run('userData().history.length'),1);assert.equal(run('userData().history[0].score'),0);
run('submitTest()');assert.equal(run('userData().history.length'),1);
run('cachedStore=null');assert.equal(run('userData().history.length'),1);assert.equal(Object.keys(run('userData().skills')).length,5);
run(`openAgentReview('ml1')`);selected={value:String((run('recheckQuestion.correct_idx')+1)%4)};run('submitRecheckAnswer()');assert.equal(run('userData().skills[reviewQuestion.skill_id].mastered'),false);
run(`openAgentReview('ml1')`);selected={value:String(run('recheckQuestion.correct_idx'))};run('submitRecheckAnswer()');run('cachedStore=null');assert.equal(run('userData().skills[reviewQuestion.skill_id].mastered'),true);
run(`currentUser='two@example.com';persistUser()`);assert.equal(run('userData().history.length'),0);
run(`userData().profile.profilePair='Math-Physics';persistUser();cachedStore=null`);assert.equal(run('getActiveSubjects().at(-1).id'),'physics');
run(`startDiagnosticTest('physics');currentTestQuestions.forEach((q,i)=>userAnswers[i]=q.correct_idx);submitTest()`);assert.equal(run('userData().history[0].percent'),100);
run(`currentUser='one@example.com'`);assert.equal(run('userData().history.length'),1);
console.log('PASS: 45 diagnostic + 45 follow-up items; persistence, reload, isolation, profile pair, scoring, duplicate submission, wrong and correct recheck.');
