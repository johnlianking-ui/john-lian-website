"""UI regression in the shared Preview browser with synthetic SDK responses only.
Start the static server, register Preview and open http://localhost:3000 first.
"""
import subprocess

JS = r'''(async () => {
 const assert=(ok,msg)=>{if(!ok)throw Error(msg)};
 const pause=()=>new Promise(r=>setTimeout(r,30));
 const original={from:supabaseClient.from,rpc:supabaseClient.rpc,getUser:supabaseClient.auth.getUser,storage:supabaseClient.storage.from};
 const uid='44444444-4444-4444-8444-444444444444';
 const other='55555555-5555-4555-8555-555555555555';
 let admin=false, uploadError=false, submitError=false, reviewError=false, queryError=false;
 const rows={reward_submissions:[],reward_events:[],account_balances:[],deposits:[],withdrawals:[],internal_transfers:[]};
 const calls=[],uploads=[];
 const attack='<img src=x onerror="window.rewardXSS=true">';
 supabaseClient.auth.getUser=async()=>({data:{user:{id:uid,email:'synthetic@example.invalid',app_metadata:{role:admin?'admin':'user'}}},error:null});
 supabaseClient.from=table=>{
   let data=[...(rows[table]||[])],single=false;
   const q={select:()=>q,eq:(key,value)=>{data=data.filter(r=>r[key]===value);return q;},
     or:()=>q,order:(key,options)=>{data.sort((a,b)=>options?.ascending===false?String(b[key]).localeCompare(String(a[key])):String(a[key]).localeCompare(String(b[key])));return q;},
     limit:n=>{data=data.slice(0,n);return q;},maybeSingle:()=>{single=true;return q;},
     then:(resolve,reject)=>Promise.resolve({data:single?data[0]||null:data,error:queryError?{message:'Synthetic unavailable'}:null}).then(resolve,reject)};
   return q;
 };
 supabaseClient.storage.from=()=>({upload:async(path,file)=>{uploads.push({path,file});return {data:{path},error:uploadError?{message:'Synthetic upload failure'}:null};},
   createSignedUrl:async(path,seconds)=>{calls.push({proof:path,seconds});return {data:{signedUrl:location.origin+'/missing-test-proof.png'},error:null};}});
 supabaseClient.rpc=async(name,args)=>{
   calls.push({name,args});
   if((name==='submit_reward_task'&&submitError)||(name==='review_reward_task'&&reviewError))return {data:null,error:{message:'Synthetic RPC failure'}};
   if(name==='submit_reward_task')rows.reward_submissions.push({id:crypto.randomUUID(),user_id:uid,step:args.task_step,proof_path:args.screenshot_path,proof_text:args.details,claim_amount:args.claimed_amount,status:'pending',created_at:new Date().toISOString()});
   if(name==='review_reward_task'){const row=rows.reward_submissions.find(r=>r.id===args.request_id);if(row)row.status=args.approve?'approved':'rejected';}
   return {data:'synthetic-result',error:null};
 };
 const step=n=>document.querySelector(`.reward-task[data-step="${n}"]`);
 const fillFile=form=>{const file=new File(['synthetic screenshot'],'proof.png',{type:'image/png'});const dt=new DataTransfer();dt.items.add(file);form.querySelector('input[type=file]').files=dt.files;};
 const approval=n=>({id:'approved-'+n,user_id:uid,step:n,status:'approved',proof_path:uid+'/proof.png',proof_text:'Proof',claim_amount:n===0?30:null,created_at:'2026-10-12T10:00:00Z'});
 try {
   showDashboard(); await loadTasks(); await loadDashboardStats();
   assert(document.querySelectorAll('.reward-task').length===7,'Seven tasks/claim cards');
   assert(step(6).textContent.includes('Tasks 1–3'),'Stage lock text');
   assert(!step(6).querySelector('form'),'Final submission must start locked');
   assert(document.getElementById('dashboard-balance').textContent==='$0.00','Missing balance row means zero');
   const card=step(1),toggle=card.querySelector('button');toggle.click();
   const form=card.querySelector('form');assert(!form.hidden,'Form opens');
   form.querySelector('textarea').value='Retained details';toggle.click();toggle.click();
   assert(form.querySelector('textarea').value==='Retained details','Toggle preserves details');
   assert(toggle.getAttribute('aria-expanded')==='true','Expanded state');
   fillFile(form);uploadError=true;form.requestSubmit();await pause();
   assert(form.textContent.includes('Synthetic upload failure')&&!form.querySelector('fieldset').disabled,'Upload failure recoverable');
   uploadError=false;submitError=true;form.requestSubmit();await pause();
   assert(form.textContent.includes('Synthetic RPC failure')&&!form.querySelector('fieldset').disabled,'RPC failure recoverable');
   const uploadCount=uploads.length;submitError=false;form.requestSubmit();form.requestSubmit();await pause();
   assert(uploads.length===uploadCount,'Retry reuses uploaded immutable screenshot');
   const submitted=calls.filter(c=>c.name==='submit_reward_task');
   assert(submitted.length===2,'Only failure and one successful RPC, no double click');
   assert(submitted[1].args.task_step===1&&submitted[1].args.details==='Retained details','Task payload');
   assert(submitted[1].args.screenshot_path.startsWith(uid+'/'),'Own screenshot path');
   assert(step(1).textContent.includes('Status: pending'),'Shows pending submission');
   rows.reward_submissions=[1,2,3].map(approval);await loadTasks();
   const claim=step(0);claim.querySelector('button').click();const cf=claim.querySelector('form');
   const amount=cf.querySelector('input[type=number]');
   for(const value of ['19.99','30.01','20.001']){amount.value=value;assert(!amount.checkValidity(),'Invalid claim '+value);}
   amount.value='30';fillFile(cf);cf.querySelector('textarea').value='Claim proof';
   cf.querySelector('[type=reset]').click();assert(amount.value===''&&cf.querySelector('textarea').value==='','Clear inputs');
   amount.value='30';fillFile(cf);cf.requestSubmit();await pause();
   assert(calls.filter(c=>c.name==='submit_reward_task').at(-1).args.claimed_amount===30,'Claim RPC amount');
   rows.reward_submissions=[1,2,3,0,4,5].map(approval);await loadTasks();
   assert(step(6).querySelector('form'),'Final unlocked after all approvals');
   step(6).querySelector('button').click();const ff=step(6).querySelector('form');
   assert(!ff.querySelector('input[type=file],input[type=number]'),'No payment or new screenshot at Task 6');
   ff.requestSubmit();await pause();const final=calls.filter(c=>c.name==='submit_reward_task').at(-1).args;
   assert(final.task_step===6&&final.claimed_amount===null&&final.screenshot_path===null,'Final review only');
   rows.reward_events=[
     {user_id:uid,event:'joining_bonus',available_delta:100,pending_delta:0,created_at:'2026-10-12T10:01:00Z'},
     {user_id:uid,event:'verified_claim',available_delta:0,pending_delta:30,created_at:'2026-10-12T10:02:00Z'},
     {user_id:uid,event:'tasks_4_5_bonus',available_delta:0,pending_delta:100,created_at:'2026-10-12T10:03:00Z'}];
   rows.account_balances=[{user_id:uid,balance:0}];await loadDashboardStats();
   assert(document.getElementById('dashboard-pending').textContent==='130.00 USD','Pending 130');
   assert(document.getElementById('dashboard-earnings').textContent==='230.00 USD','Total rewards 230');
   rows.reward_events.push({user_id:uid,event:'pending_release',available_delta:130,pending_delta:-130,created_at:'2026-10-12T10:04:00Z'});
   rows.account_balances[0].balance=130;await loadDashboardStats();
   assert(document.getElementById('dashboard-pending').textContent==='0.00 USD','Pending released');
   assert(document.getElementById('dashboard-earnings').textContent==='230.00 USD','Release is not counted as new earnings');
   rows.deposits=[{user_id:uid,amount:7,payment_method:attack,status:'approved',created_at:'2026-10-12T10:05:00Z'}];
   rows.withdrawals=[{user_id:uid,amount:100,payment_method:'bank',status:'approved',created_at:'2026-10-12T10:01:30Z'}];
   rows.internal_transfers=[{sender_id:uid,recipient_id:other,amount:2,status:'completed',created_at:'2026-10-12T10:06:00Z'},{sender_id:other,recipient_id:uid,amount:1,status:'completed',created_at:'2026-10-12T10:07:00Z'}];
   await loadWithdrawalHistory();const history=document.getElementById('transaction-history-list');
   assert(history.textContent.includes('Transfer sent')&&history.textContent.includes('Transfer received')&&history.textContent.includes('Withdrawal'),'History categories');
   assert(history.querySelector('article h4').textContent==='Transfer received','Newest history first');
   assert(history.textContent.includes(attack)&&!history.querySelector('img'),'History escapes database text');
   rows.reward_submissions=[{...approval(1),status:'rejected',review_note:attack}];await loadTasks();
   assert(step(1).textContent.includes(attack)&&!step(1).querySelector('img'),'Review feedback safe');
   assert(step(1).querySelector('button').textContent==='Try again','Rejected task allows retry');
   admin=true;rows.reward_submissions=[{...approval(0),id:'claim-admin',user_id:other,proof_path:other+'/proof.png',status:'pending',proof_text:attack},{...approval(6),id:'final-admin',user_id:other,status:'pending',proof_path:null},{...approval(1),user_id:other}];
   document.getElementById('admin-dashboard').style.display='block';await RewardProgram.loadAdmin(supabaseClient);
   let ac=document.querySelector('.reward-review');assert(ac.textContent.includes(attack)&&!ac.querySelector('img'),'Admin text safe');
   ac.querySelector('button').click();await pause();assert(calls.some(c=>c.proof===other+'/proof.png'&&c.seconds===120),'Private signed screenshot');
   ac.querySelector('button').click();assert(ac.querySelector('button').getAttribute('aria-expanded')==='false','Screenshot folds');
   let reviewForm=ac.querySelector('form');reviewForm.querySelector('button[type=button]').click();
   assert(reviewForm.textContent.includes('Explain'),'Reject requires feedback');
   reviewForm.querySelector('textarea').value='Need clearer screenshot';reviewError=true;reviewForm.querySelector('button[type=button]').click();await pause();
   assert(!reviewForm.querySelector('fieldset').disabled&&reviewForm.textContent.includes('Synthetic RPC failure'),'Admin failure recoverable');
   reviewError=false;reviewForm.querySelector('button[type=button]').click();await pause();
   assert(calls.some(c=>c.name==='review_reward_task'&&c.args.approve===false&&c.args.note==='Need clearer screenshot'),'Reject RPC');
   ac=document.querySelector('.reward-review');ac.querySelector('button').click();await pause();
   assert(ac.textContent.includes('Task 1 — Review the community'),'Final evidence context');
   ac.querySelector('form').requestSubmit();await pause();assert(calls.some(c=>c.name==='review_reward_task'&&c.args.approve===true),'Approve RPC');
   for(const id of ['deposit-nav-button','withdrawal-nav-button','withdraw-button','transaction-history-button','internal-transfer-button','deposit-method-button','bank-deposit-button','mobile-money-deposit-button','available-tasks-button']){
     const button=document.getElementById(id);const panel=document.getElementById(button.getAttribute('aria-controls'));
     const initial=getComputedStyle(panel).display!=='none';button.click();assert((getComputedStyle(panel).display!=='none')!==initial,'Toggle '+id);button.click();assert((getComputedStyle(panel).display!=='none')===initial,'Fold '+id);
   }
   await pause();
   for(const id of ['deposit-section','deposit-methods','bank-transfer-section','mobile-money-section','withdraw-form','internal-transfer-section','transaction-history-section'])document.getElementById(id).style.display='block';
   assert(document.documentElement.scrollWidth<=innerWidth,'No page overflow');
   for(const control of document.querySelectorAll('#user-dashboard input,#user-dashboard textarea,#admin-rewards textarea')){
     if(!control.getClientRects().length)continue;const r=control.getBoundingClientRect();assert(r.left>=0&&r.right<=innerWidth+1,'Control in viewport');
   }
   queryError=true;await loadDashboardStats();assert(document.getElementById('dashboard-balance').textContent==='—','No stale balance on query error');
   assert(document.getElementById('reward-summary-message').textContent.includes('unavailable'),'Summary error visible');
   RewardProgram.reset();assert(!document.getElementById('tasks-list').children.length,'Clear account data on logout');
   assert(!window.rewardXSS,'No stored script execution');
   return {result:'PASS',width:innerWidth,forms:true,stageGates:true,balances:true,history:true,admin:true,toggles:true};
 }finally{
   supabaseClient.from=original.from;supabaseClient.rpc=original.rpc;supabaseClient.auth.getUser=original.getUser;supabaseClient.storage.from=original.storage;
 }
})()'''
for width in (1440, 390):
    subprocess.run(['coderabbit-agent-browser', 'reload'], check=True)
    subprocess.run(['coderabbit-agent-browser', 'set', 'viewport', str(width), '900'], check=True)
    subprocess.run(['coderabbit-agent-browser', 'eval', 'new Promise(r=>setTimeout(r,500))'], check=True)
    result = subprocess.run(['coderabbit-agent-browser', 'eval', JS])
    if result.returncode:
        raise SystemExit(result.returncode)
subprocess.run(['coderabbit-agent-browser', 'reload'], check=True)
