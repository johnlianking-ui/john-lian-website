/* Six-task program. The server is the authority for approvals and all money movements. */
window.RewardProgram = (() => {
  const tasks = [
    { step: 1, title: 'Task 1 — Review the community', description: 'Visit the designated group and review its content. Upload one screenshot.' },
    { step: 2, title: 'Task 2 — India’s economy', description: 'Read the information about India’s economy and current economic issues. Upload one screenshot.' },
    { step: 3, title: 'Task 3 — International news', description: 'Review international news and global economic updates. Upload one screenshot. Approval of Tasks 1–3 makes 100 available to withdraw.' },
    { step: 0, title: 'Verify your reward claim', description: 'Enter the amount you are claiming, from 20 to 30, and upload a screenshot showing that amount. An admin must verify it. It stays Pending until Task 6 is approved.' },
    { step: 4, title: 'Task 4 — Join the community', description: 'Join the designated community group and upload a screenshot showing your membership.' },
    { step: 5, title: 'Task 5 — Confirm membership and claim', description: 'Upload a screenshot confirming your group membership and your verified claimed amount. Approval of Tasks 4 and 5 adds 100 Pending.' },
    { step: 6, title: 'Task 6 — Final verification', description: 'Request an admin’s final check of your approved screenshots and reward claim. Approval releases your 120–130 Pending. No payment and no extra bonus.' }
  ];
  const names = { joining_bonus: 'Tasks 1–3 joining bonus', verified_claim: 'Verified reward claim', tasks_4_5_bonus: 'Tasks 4–5 bonus', pending_release: 'Task 6: Pending released (not a new reward)' };
  const versions = { tasks: 0, stats: 0, admin: 0, history: 0 };
  const money = value => `${Number(value).toFixed(2)} USD`;
  const byId = id => document.getElementById(id);
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function message(container, text) { container.replaceChildren(el('p', text)); }
  async function currentUser(client) {
    const { data, error } = await client.auth.getUser();
    if (error || !data.user) throw Error('Please log in again.');
    return data.user;
  }
  async function checked(query) {
    const { data, error } = await query;
    if (error) throw Error(error.message);
    return data;
  }
  function lockReason(step, approved) {
    if ([0, 4, 5, 6].includes(step) && ![1, 2, 3].every(n => approved.has(n))) return 'Available after Tasks 1–3 are approved.';
    if ([5, 6].includes(step) && !approved.has(0)) return 'Available after your reward claim is approved.';
    if (step === 6 && ![4, 5].every(n => approved.has(n))) return 'Available after Tasks 4 and 5 are approved.';
    return '';
  }
  function field(form, label, input, id) {
    input.id = id;
    const caption = el('label', label);
    caption.htmlFor = id;
    form.append(caption, input);
    return input;
  }
  function proofViewer(client, path) {
    const container = el('div');
    if (!path) return container;
    const button = el('button', 'View screenshot');
    button.type = 'button'; button.setAttribute('aria-expanded', 'false');
    const preview = el('div'); preview.hidden = true;
    button.onclick = async () => {
      if (!preview.hidden) {
        preview.hidden = true; button.textContent = 'View screenshot'; button.setAttribute('aria-expanded', 'false'); return;
      }
      button.disabled = true;
      try {
        const data = await checked(client.storage.from('reward-proofs').createSignedUrl(path, 120));
        const url = new URL(data.signedUrl);
        if (!['https:', 'http:'].includes(url.protocol)) throw Error('Invalid screenshot URL.');
        const img = el('img'); img.alt = 'Submitted screenshot'; img.src = url.href;
        img.onerror = () => message(preview, 'Screenshot could not load. Close and reopen to retry.');
        preview.replaceChildren(img); preview.hidden = false;
        button.textContent = 'Close screenshot'; button.setAttribute('aria-expanded', 'true');
      } catch (error) {
        message(preview, `Unable to open screenshot: ${error.message}`); preview.hidden = false;
        button.textContent = 'Close screenshot'; button.setAttribute('aria-expanded', 'true');
      } finally { button.disabled = false; }
    };
    container.append(button, preview);
    return container;
  }
  async function loadTasks(client) {
    const run = ++versions.tasks;
    const container = byId('tasks-list');
    message(container, 'Loading tasks…');
    try {
      const user = await currentUser(client);
      const rows = await checked(client.from('reward_submissions').select('*').eq('user_id', user.id).order('created_at', { ascending: false }));
      if (run !== versions.tasks) return;
      const approved = new Set(rows.filter(row => row.status === 'approved').map(row => row.step));
      container.replaceChildren();
      for (const task of tasks) {
        const row = rows.find(item => item.step === task.step && item.status !== 'rejected') || rows.find(item => item.step === task.step);
        const card = el('article', undefined, 'task-card reward-task');
        card.dataset.step = task.step;
        card.append(el('h4', task.title), el('p', task.description));
        const reason = lockReason(task.step, approved);
        if (row) {
          card.append(el('p', `Status: ${row.status}`, 'reward-status'));
          if (row.claim_amount !== null) card.append(el('p', `Claim: ${money(row.claim_amount)}`));
          if (row.review_note) card.append(el('p', `Admin feedback: ${row.review_note}`));
        }
        if (row && row.status !== 'rejected') {
          if (row.proof_path) card.append(proofViewer(client, row.proof_path));
        } else if (reason) {
          card.append(el('p', reason, 'reward-lock'));
        } else {
          const toggle = el('button', row ? 'Try again' : task.step === 6 ? 'Request final review' : 'Open submission');
          toggle.type = 'button'; toggle.setAttribute('aria-expanded', 'false');
          const form = el('form'); form.hidden = true; form.id = `reward-form-${task.step}`;
          toggle.setAttribute('aria-controls', form.id);
          toggle.onclick = () => { form.hidden = !form.hidden; toggle.setAttribute('aria-expanded', String(!form.hidden)); };
          const fields = el('fieldset');
          let amount, screenshot;
          if (task.step === 0) {
            amount = el('input'); amount.type = 'number'; amount.min = '20'; amount.max = '30'; amount.step = '0.01'; amount.required = true;
            field(fields, 'Claimed amount (USD, provisional)', amount, `reward-amount-${task.step}`);
          }
          if (task.step !== 6) {
            screenshot = el('input'); screenshot.type = 'file'; screenshot.accept = 'image/png,image/jpeg,image/webp'; screenshot.required = true;
            field(fields, 'Screenshot (PNG, JPEG or WebP; up to 5 MB)', screenshot, `reward-file-${task.step}`);
          }
          const details = el('textarea'); details.maxLength = 2000; details.rows = 3;
          field(fields, 'Additional details (optional)', details, `reward-details-${task.step}`);
          const submit = el('button', task.step === 6 ? 'Submit for final verification' : 'Submit for approval'); submit.type = 'submit';
          const clear = el('button', 'Clear'); clear.type = 'reset';
          const status = el('p'); status.setAttribute('role', 'status');
          fields.append(submit, clear); form.append(fields, status);
          let busy = false, uploadedFile = null, uploadedPath = null;
          form.onreset = () => { status.textContent = ''; uploadedFile = null; uploadedPath = null; };
          form.onsubmit = async event => {
            event.preventDefault();
            if (busy || !form.reportValidity()) return;
            const file = screenshot?.files[0];
            if (screenshot && (!file || !['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > 5242880 || !file.size)) {
              status.textContent = 'Choose a PNG, JPEG or WebP screenshot from 1 byte to 5 MB.'; return;
            }
            const claimed = amount ? Number(amount.value) : null;
            if (amount && (!Number.isFinite(claimed) || claimed < 20 || claimed > 30 || Math.abs(claimed * 100 - Math.round(claimed * 100)) > 0.000001)) {
              status.textContent = 'Enter 20–30 with at most two decimal places.'; return;
            }
            busy = true; fields.disabled = true; status.textContent = 'Submitting…';
            try {
              const activeUser = await currentUser(client);
              if (activeUser.id !== user.id) throw Error('Your account changed. Refresh before submitting.');
              if (file && uploadedFile !== file) {
                const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' }[file.type];
                const path = `${user.id}/${crypto.randomUUID()}.${extension}`;
                await checked(client.storage.from('reward-proofs').upload(path, file, { upsert: false, contentType: file.type }));
                uploadedFile = file; uploadedPath = path;
              }
              await checked(client.rpc('submit_reward_task', { task_step: task.step, screenshot_path: uploadedPath, details: details.value.trim(), claimed_amount: claimed }));
              // Keep the successful form disabled until refreshed; never resubmit automatically.
              status.textContent = 'Submitted. Waiting for admin approval.';
              form.reset(); status.textContent = 'Submitted. Waiting for admin approval.';
              await Promise.all([loadTasks(client), loadStats(client)]);
            } catch (error) {
              status.textContent = `Could not submit: ${error.message}`;
              fields.disabled = false; busy = false;
            }
          };
          card.append(toggle, form);
        }
        container.append(card);
      }
    } catch (error) {
      if (run === versions.tasks) message(container, `Rewards are currently unavailable. ${error.message}`);
    }
  }
  async function loadStats(client) {
    const run = ++versions.stats;
    const ids = ['dashboard-earnings','dashboard-balance','dashboard-pending','dashboard-completed'];
    ids.forEach(id => { byId(id).textContent = '—'; });
    byId('reward-summary-message').textContent = '';
    try {
      const user = await currentUser(client);
      const [events, balance, submissions] = await Promise.all([
        checked(client.from('reward_events').select('available_delta,pending_delta').eq('user_id', user.id)),
        checked(client.from('account_balances').select('balance').eq('user_id', user.id).maybeSingle()),
        checked(client.from('reward_submissions').select('step').eq('user_id', user.id).eq('status','approved'))
      ]);
      if (run !== versions.stats) return;
      byId('dashboard-earnings').textContent = money(events.reduce((sum, row) => sum + Number(row.available_delta) + Number(row.pending_delta), 0));
      byId('dashboard-pending').textContent = money(events.reduce((sum, row) => sum + Number(row.pending_delta), 0));
      // Preserve this existing dollar format: the withdrawal handler parses it.
      byId('dashboard-balance').textContent = `$${Number(balance?.balance || 0).toFixed(2)}`;
      byId('dashboard-completed').textContent = `${submissions.filter(row => row.step !== 0).length} / 6`;
    } catch (error) {
      if (run === versions.stats) byId('reward-summary-message').textContent = `Could not load account summary: ${error.message}`;
    }
  }
  async function loadAdmin(client) {
    const run = ++versions.admin;
    const container = byId('admin-rewards');
    message(container, 'Loading reward submissions…');
    try {
      const user = await currentUser(client);
      if (user.app_metadata?.role !== 'admin') { container.replaceChildren(); return; }
      const rows = await checked(client.from('reward_submissions').select('*').eq('status','pending').order('created_at', { ascending: true }).limit(100));
      if (run !== versions.admin) return;
      container.replaceChildren();
      if (!rows.length) message(container, 'No rewards waiting for review.');
      for (const row of rows) {
        const card = el('article', undefined, 'reward-review');
        card.append(el('h4', tasks.find(task => task.step === row.step).title), el('p', `User: ${row.user_id}`), el('p', row.proof_text));
        if (row.claim_amount !== null) card.append(el('p', `Verify claimed amount: ${money(row.claim_amount)}`));
        card.append(proofViewer(client, row.proof_path));
        if ([5,6].includes(row.step)) {
          const context = el('div');
          const view = el('button', 'Review earlier approved evidence'); view.type = 'button';
          view.onclick = async () => {
            view.disabled = true;
            try {
              const evidence = await checked(client.from('reward_submissions').select('*').eq('user_id',row.user_id).eq('status','approved').order('step'));
              context.replaceChildren();
              for (const prior of evidence) {
                context.append(el('p', `${tasks.find(task => task.step === prior.step).title}${prior.claim_amount === null ? '' : ': ' + money(prior.claim_amount)}`), el('p', prior.proof_text), proofViewer(client, prior.proof_path));
              }
            } catch (error) { message(context, error.message); }
            finally { view.disabled = false; }
          };
          card.append(view, context);
        }
        const form = el('form'); const fields = el('fieldset');
        const note = el('textarea'); note.maxLength = 2000; note.rows = 2;
        field(fields, 'Review note (required when rejecting)', note, `review-note-${row.id}`);
        const accept = el('button', row.step === 6 ? 'Approve and release Pending' : 'Approve'); accept.type = 'submit';
        const reject = el('button', 'Reject'); reject.type = 'button';
        const status = el('p'); status.setAttribute('role','status');
        let busy = false;
        const review = async approved => {
          if (busy) return;
          if (!approved && !note.value.trim()) { status.textContent = 'Explain what the client needs to correct.'; return; }
          busy = true; fields.disabled = true; status.textContent = 'Saving review…';
          try {
            await checked(client.rpc('review_reward_task', { request_id: row.id, approve: approved, note: note.value.trim() }));
            await Promise.all([loadAdmin(client), loadStats(client), loadTasks(client)]);
          } catch (error) { status.textContent = error.message; fields.disabled = false; busy = false; }
        };
        form.onsubmit = event => { event.preventDefault(); review(true); };
        reject.onclick = () => review(false);
        fields.append(accept, reject); form.append(fields, status); card.append(form); container.append(card);
      }
      if (rows.length === 100) container.append(el('p','Showing the oldest 100 pending submissions. Review these, then refresh to see more.'));
    } catch (error) {
      if (run === versions.admin) message(container, `Unable to load reward reviews: ${error.message}`);
    }
  }
  async function loadHistory(client) {
    const run = ++versions.history;
    const container = byId('transaction-history-list');
    message(container, 'Loading transactions…');
    try {
      const user = await currentUser(client);
      const [deposits, withdrawals, transfers, rewards] = await Promise.all([
        checked(client.from('deposits').select('*').eq('user_id',user.id).order('created_at',{ ascending: false }).limit(100)),
        checked(client.from('withdrawals').select('*').eq('user_id',user.id).order('created_at',{ ascending: false }).limit(100)),
        checked(client.from('internal_transfers').select('*').or(`sender_id.eq.${user.id},recipient_id.eq.${user.id}`).order('created_at',{ ascending: false }).limit(100)),
        checked(client.from('reward_events').select('*').eq('user_id',user.id).order('created_at',{ ascending: false }).limit(100))
      ]);
      if (run !== versions.history) return;
      const items = [
        ...deposits.map(row => ({ ...row, title: 'Deposit', text: `${money(row.amount)} · ${row.payment_method} · ${row.status}` })),
        ...withdrawals.map(row => ({ ...row, title: 'Withdrawal', text: `${money(row.amount)} · ${row.payment_method} · ${row.status}` })),
        ...transfers.map(row => ({ ...row, title: row.sender_id === user.id ? 'Transfer sent' : 'Transfer received', text: `${money(row.amount)} · ${row.status}` })),
        ...rewards.map(row => ({ ...row, title: names[row.event], text: `Available change: ${money(row.available_delta)} · Pending change: ${money(row.pending_delta)}` }))
      ].sort((a,b) => new Date(b.created_at) - new Date(a.created_at));
      container.replaceChildren(el('p', 'Latest 100 entries per category. Reward history covers the new six-task program. USD is provisional. Pending payment requests have not changed your balance.'));
      if (!items.length) container.append(el('p','No transactions yet.'));
      for (const row of items) {
        const card = el('article', undefined, 'transaction-history-item');
        card.append(el('h4',row.title), el('p',row.text), el('p',new Date(row.created_at).toLocaleString())); container.append(card);
      }
    } catch (error) {
      if (run === versions.history) message(container, `Unable to load transaction history: ${error.message}`);
    }
  }
  function reset() {
    Object.keys(versions).forEach(key => { versions[key]++; });
    ['tasks-list','admin-rewards','transaction-history-list'].forEach(id => byId(id).replaceChildren());
    ['dashboard-earnings','dashboard-balance','dashboard-pending','dashboard-completed'].forEach(id => { byId(id).textContent = '—'; });
  }
  return { loadTasks, loadStats, loadAdmin, loadHistory, reset };
})();
