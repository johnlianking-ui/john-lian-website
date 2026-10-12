// Supabase owns code generation, expiry, rate limiting, and email verification.
(() => {
  const emailForm = document.getElementById('registration-email-form');
  const codeForm = document.getElementById('registration-code-form');
  const passwordForm = document.getElementById('register-form');
  const emailInput = document.getElementById('register-email');
  const codeInput = document.getElementById('registration-code');
  const resendButton = document.getElementById('resend-registration-code');
  const message = document.getElementById('register-message');
  let step = 'email';
  let pendingEmail = '';
  let pendingGender = '';
  let verifiedUserId = null;
  let busy = false;
  let resendAt = 0;
  let timer;

  function render() {
    emailForm.hidden = step === 'password' || step === 'done';
    codeForm.hidden = step !== 'code';
    passwordForm.hidden = step !== 'password';
    emailInput.readOnly = step !== 'email';
    emailForm.querySelectorAll('input[type=checkbox], input[type=radio]').forEach(el => { el.disabled = busy || step !== 'email'; });
    emailForm.querySelector('button').disabled = busy || step !== 'email';
    codeForm.querySelectorAll('button, input').forEach(el => { el.disabled = busy; });
    passwordForm.querySelectorAll('button, input').forEach(el => { el.disabled = busy || step !== 'password'; });
    const seconds = Math.max(0, Math.ceil((resendAt - Date.now()) / 1000));
    resendButton.disabled = busy || seconds > 0;
    resendButton.textContent = seconds ? `Resend in ${seconds}s` : 'Resend Code';
  }

  function cooldown() {
    resendAt = Date.now() + 60000;
    clearInterval(timer);
    timer = setInterval(() => {
      render();
      if (Date.now() >= resendAt) clearInterval(timer);
    }, 1000);
  }

  async function sendCode() {
    const { error } = await supabaseClient.auth.signInWithOtp({
      email: pendingEmail,
      options: { shouldCreateUser: true }
    });
    if (error) throw error;
    step = 'code';
    codeInput.value = '';
    cooldown();
    message.textContent = `A verification code was requested for ${pendingEmail}. Check your inbox and spam folder.`;
  }

  emailForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || step !== 'email' || !emailForm.reportValidity()) return;
    pendingEmail = emailInput.value.trim();
    pendingGender = emailForm.querySelector('input[name=register-gender]:checked')?.value || '';
    busy = true;
    render();
    message.textContent = 'Sending verification code...';
    try {
      await sendCode();
    } catch (error) {
      message.textContent = `Could not send the code: ${error.message || 'Please try again.'}`;
    } finally {
      busy = false;
      render();
      if (step === 'code') codeInput.focus();
    }
  });

  resendButton.addEventListener('click', async () => {
    if (busy || step !== 'code' || Date.now() < resendAt) return;
    busy = true;
    render();
    try {
      await sendCode();
    } catch (error) {
      message.textContent = `Could not resend the code: ${error.message || 'Please try again.'}`;
    } finally {
      busy = false;
      render();
    }
  });

  document.getElementById('change-registration-email').addEventListener('click', () => {
    if (busy || step !== 'code') return;
    step = 'email';
    pendingEmail = '';
    pendingGender = '';
    verifiedUserId = null;
    codeForm.reset();
    message.textContent = '';
    render();
    emailInput.focus();
  });

  codeForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || step !== 'code' || !codeForm.reportValidity()) return;
    busy = true;
    render();
    message.textContent = 'Verifying email...';
    try {
      const { data, error } = await supabaseClient.auth.verifyOtp({
        email: pendingEmail, token: codeInput.value.trim(), type: 'email'
      });
      if (error) throw error;
      if (!data.user || !data.session || !data.user.email_confirmed_at ||
          data.user.email.toLowerCase() !== pendingEmail.toLowerCase()) {
        throw new Error('Email verification did not complete. Request another code.');
      }
      verifiedUserId = data.user.id;
      step = 'password';
      clearInterval(timer);
      document.getElementById('verified-registration-email').textContent = `Verified: ${data.user.email}`;
      codeForm.reset();
      message.textContent = 'Email verified. Choose your password below.';
    } catch (error) {
      message.textContent = `Unable to verify: ${error.message || 'The code may be incorrect or expired.'}`;
    } finally {
      busy = false;
      render();
      if (step === 'password') document.getElementById('register-password').focus();
    }
  });

  passwordForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || step !== 'password' || !passwordForm.reportValidity()) return;
    const password = document.getElementById('register-password').value;
    if (password !== document.getElementById('register-confirm-password').value) {
      message.textContent = 'Passwords do not match.';
      return;
    }
    busy = true;
    render();
    message.textContent = 'Saving password...';
    try {
      // Revalidate the authenticated identity in case another tab changed sessions.
      const { data, error } = await supabaseClient.auth.getUser();
      if (error || !data.user || data.user.id !== verifiedUserId ||
          !data.user.email_confirmed_at || data.user.email.toLowerCase() !== pendingEmail.toLowerCase()) {
        step = 'email';
        verifiedUserId = null;
        pendingEmail = '';
        pendingGender = '';
        passwordForm.reset();
        const { error: signOutError } = await supabaseClient.auth.signOut({ scope: 'local' });
        if (signOutError) throw new Error('Your session changed. Please sign out and verify your email again.');
        throw new Error('Your session changed or expired. Verify your email again.');
      }
      const { error: passwordError } = await supabaseClient.auth.updateUser({
        password,
        ...(pendingGender ? { data: { gender: pendingGender } } : {})
      });
      if (passwordError) throw passwordError;
      passwordForm.reset();
      step = 'done';
      message.textContent = 'Your password is saved. You are signed in and can use your dashboard.';
      updateUserStatus();
    } catch (error) {
      message.textContent = error.message || 'Could not save your password. Please try again.';
    } finally {
      busy = false;
      render();
    }
  });

  render();
})();
