import { useEffect, useId, useRef, useState } from 'react';
import { Eye, EyeOff, ShieldCheck, X } from 'lucide-react';
import { ApiError, api } from './api';
import type { Account } from './api';
import './account.css';

function PasswordField({label, value, onChange, minimum = 1, autoComplete = 'current-password'}: {
  label: string; value: string; onChange: (value: string) => void; minimum?: number; autoComplete?: string;
}) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const [caps, setCaps] = useState(false);
  return <div className="account-field"><label htmlFor={id}>{label}</label><div className="account-password"><input id={id} type={visible?'text':'password'} value={value} onChange={e=>onChange(e.target.value)} autoComplete={autoComplete} minLength={minimum} maxLength={128} required onKeyUp={e=>setCaps(e.getModifierState('CapsLock'))} onBlur={()=>setCaps(false)}/><button type="button" aria-label={`${visible?'Hide':'Show'} ${label.toLowerCase()}`} aria-pressed={visible} onClick={()=>setVisible(!visible)}>{visible?<EyeOff size={18}/>:<Eye size={18}/>}</button></div>{caps&&<small className="account-hint">Caps Lock is on.</small>}</div>;
}

export function AccountDialog({ user, recovery, onClose, onAuthenticated, onSignedOut }: {
  user: Account | null; onClose: () => void; onAuthenticated: (user: Account | null) => void; onSignedOut: () => void;
  recovery?: {token: string; username: string} | null;
}) {
  const [mode, setMode] = useState<'login' | 'register' | 'recover'>(recovery?'recover':'login');
  const [username, setUsername] = useState(recovery?.username??'');
  const [recoveryCode, setRecoveryCode] = useState(recovery?.token??'');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [isError, setIsError] = useState(false);
  const [retryUntil, setRetryUntil] = useState(0);
  const [time, setTime] = useState(Date.now());
  const panel = useRef<HTMLElement>(null);
  const notice = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  const retrySeconds = Math.max(0, Math.ceil((retryUntil-time)/1000));
  const disabled = busy || retrySeconds>0;
  const managed = user && mode!=='recover';
  close.current = onClose;
  useEffect(()=>{
    if(recovery){setMode('recover');setRecoveryCode(recovery.token);setUsername(recovery.username);setPassword('');setNewPassword('');setConfirmation('');setMessage('');}
  },[recovery]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panel.current?.querySelector<HTMLElement>('button')?.focus();
    function keys(event: KeyboardEvent) {
      if (event.key === 'Escape') close.current();
      if (event.key !== 'Tab') return;
      const targets = [...panel.current!.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href], textarea')].filter((item) => item.offsetParent !== null);
      const first = targets[0], last = targets.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener('keydown', keys);
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', keys); previous?.focus(); };
  }, []);
  useEffect(()=>{if(message)notice.current?.scrollIntoView({block:'nearest'});},[message]);
  useEffect(()=>{if(!retryUntil)return;const timer=window.setInterval(()=>setTime(Date.now()),1000);return()=>window.clearInterval(timer);},[retryUntil]);
  function showError(error: unknown) {
    setIsError(true);
    setMessage(error instanceof Error ? error.message : 'Something went wrong. Please try again.');
    if(error instanceof ApiError && error.status===429) {
      setRetryUntil(Date.now()+Math.min(3600,Math.max(1,error.retryAfter||60))*1000);setTime(Date.now());
    }
  }
  function switchMode(next: 'login'|'register'|'recover') {
    setMode(next);setPassword('');setNewPassword('');setConfirmation('');setMessage('');
  }

  async function authenticate(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      const result = await api.authenticate(mode==='register'?'register':'login', { username:username.trim(), password, ...(mode === 'register' ? { display_name: name } : {}) });
      onAuthenticated(result.user); setPassword(''); onClose();
    } catch (error) {
      if(error instanceof ApiError && error.status===409 && mode==='register') {
        setMode('login');setPassword('');setIsError(true);setMessage('This username is already registered. Sign in with your existing password, or choose Forgot password.');
      } else showError(error);
    }
    finally { setBusy(false); }
  }
  async function recoverPassword(event: React.FormEvent) {
    event.preventDefault();setMessage('');
    if(newPassword!==confirmation){setIsError(true);setMessage('The passwords do not match. Enter the same new password twice.');return;}
    setBusy(true);
    try {
      await api.recoverPassword(recoveryCode.trim(), newPassword);
      onSignedOut();setRecoveryCode('');setNewPassword('');setConfirmation('');setPassword('');setMode('login');setIsError(false);
      setMessage('Your password has been reset. Sign in with your new password.');
    } catch(error) {showError(error);} finally {setBusy(false);}
  }
  async function signout() {
    setBusy(true);
    try { await api.logout(); onSignedOut(); onClose(); }
    catch (error) { showError(error); }
    finally { setBusy(false); }
  }
  async function changePassword(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage('');
    try { await api.password(password, newPassword); setPassword(''); setNewPassword(''); onSignedOut(); setIsError(false);setMessage('Password changed. Sign in again.'); }
    catch (error) { showError(error); }
    finally { setBusy(false); }
  }
  async function deleteAccount(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage('');
    try { await api.deleteAccount(password); setPassword(''); onSignedOut(); setIsError(false);setMessage('Your account and personal reports have been deleted.'); }
    catch (error) { showError(error); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop" onClick={onClose}><section ref={panel} className="modal panel account-dialog" role="dialog" aria-modal="true" aria-labelledby="account-title" onClick={(e) => e.stopPropagation()}>
    <header className="account-header"><div><ShieldCheck className="teal" size={25}/><h2 id="account-title">{managed ? `Hello, ${user.display_name}` : mode==='recover'?'Reset your password':mode === 'login' ? 'Welcome back' : 'Create your account'}</h2></div><button className="modal-close" onClick={onClose} aria-label="Close account"><X size={21} /></button></header>
    <div className="account-body">
    {message && <div ref={notice} className={`account-notice ${isError?'account-error':'account-success'}`} role={isError?'alert':'status'}>{message}</div>}
    {managed ? <><p>Signed in as {user.username}. Reports use your account and the location you choose to share.</p><p>{user.verified_contributor ? 'Your contributor account has been verified.' : 'Your sightings are collected for review. Contributor verification is required before they can influence arrival estimates.'}</p>
      <p>Surface delay reports can contribute after three accounts agree. Verification is required for identified train sightings.</p><button className="outline" onClick={signout} disabled={busy}>Sign out and clear queued reports</button>
      <details className="account-details"><summary>Change password</summary><form onSubmit={changePassword}>
        <label>CURRENT PASSWORD<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} maxLength={128} required /></label>
        <label>NEW PASSWORD<input type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={12} maxLength={128} required /></label>
        <button className="primary" disabled={busy}>Change password and sign out</button>
      </form></details>
      <details className="account-details"><summary>Delete account and personal reports</summary><p>This permanently removes your account, sessions and personal reports. Confirm with your current password.</p><form onSubmit={deleteAccount}><label>CURRENT PASSWORD<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} maxLength={128} required /></label><button className="outline" disabled={busy}>Delete my account</button></form></details>
      {user.role === 'admin' && <details className="account-details"><summary>Import operator timetable</summary><p>Load a dated timetable JSON matching the configured network version.</p><input type="file" accept="application/json,.json" aria-label="Import timetable" disabled={busy} onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; setBusy(true); try { await api.timetable(JSON.parse(await file.text())); setMessage('Timetable imported. Upcoming services will refresh automatically.'); } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); event.target.value = ''; } }} /></details>}
    </> : mode==='recover' ? <><p>Choose a new password for {username?<strong>{username}</strong>:'your account'} using a one-time recovery link or code from your application administrator.</p><form onSubmit={recoverPassword}>
      <label>RECOVERY CODE<input type="password" autoComplete="off" value={recoveryCode} onChange={e=>setRecoveryCode(e.target.value)} spellCheck={false} minLength={32} maxLength={128} required/></label>
      <PasswordField label="NEW PASSWORD" value={newPassword} onChange={setNewPassword} minimum={12} autoComplete="new-password"/>
      <PasswordField label="CONFIRM NEW PASSWORD" value={confirmation} onChange={setConfirmation} minimum={12} autoComplete="new-password"/>
      <small className="account-hint">Use at least 12 characters. Recovery links expire after 30 minutes and work once.</small>
      <button className="primary" disabled={disabled}>{busy?'Resetting…':'Reset password'}</button>
    </form><button className="text-button account-back" type="button" disabled={busy} onClick={()=>switchMode('login')}>Back to sign in</button></> : <><p>{mode === 'register' ? 'Save your sightings and help other passengers. Choose a username and a password of at least 12 characters.' : 'Sign in to share sightings and manage your account.'}</p><form onSubmit={authenticate}>
      {mode === 'register' && <label>YOUR NAME<input autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} required /></label>}
      <label>USERNAME<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value.trim())} minLength={3} maxLength={32} pattern="[A-Za-z0-9_]+" required /></label>
      <PasswordField label="PASSWORD" value={password} onChange={setPassword} minimum={mode==='register'?12:1} autoComplete={mode==='login'?'current-password':'new-password'}/>
      {mode==='register'&&<small className="account-hint">Username: 3–32 letters, numbers or underscores.</small>}
      {mode==='login'&&<button className="text-button account-forgot" type="button" disabled={busy} onClick={()=>switchMode('recover')}>Forgot password?</button>}
      <button className="primary" disabled={disabled}>{busy ? 'Please wait…' : retrySeconds>0 ? `Try again in ${retrySeconds}s` : mode === 'login' ? 'Sign in' : 'Create account'}</button>
      <button className="text-button account-switch" type="button" disabled={busy} onClick={() => switchMode(mode==='login'?'register':'login')}>{mode === 'login' ? 'Create an account' : 'Already registered? Sign in'}</button>
    </form></>}
    {mode==='recover'&&retrySeconds>0&&<p className="account-hint" role="status">Try again in {retrySeconds} seconds.</p>}
    <p className="account-privacy"><ShieldCheck size={13}/>Your password is stored securely. Report locations are shared only when you submit a report.</p>
    </div>
  </section></div>;
}
