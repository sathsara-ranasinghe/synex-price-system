import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Router } from '@angular/router';
import { AuthService, errorText } from '../core/auth';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, MatIconModule, MatProgressSpinnerModule],
  template: `
    <div class="page">
      <!-- brand panel -->
      <aside class="brand">
        <div class="pattern" aria-hidden="true"></div>
        <div class="brand-inner">
          <img class="logo" src="logo-white.png" alt="Synex Group" width="200" height="200" />
          <h1>QB Portal</h1>
          <p>QuickBooks Desktop for every Synex Group company, in your browser.</p>
        </div>
        <ul class="points">
          <li><mat-icon>sync</mat-icon> Synced with QuickBooks Desktop</li>
          <li><mat-icon>verified_user</mat-icon> Changes approved before they are saved</li>
          <li><mat-icon>history</mat-icon> Every change is logged</li>
        </ul>
      </aside>

      <!-- form -->
      <main class="side">
        @if (mfaToken()) {
          <form class="form" (ngSubmit)="verify()" [class.shake]="shake()">
            <img class="mobile-logo" src="logo.png" alt="Synex Group" width="72" height="72" />
            <div class="shield"><mat-icon>phonelink_lock</mat-icon></div>
            <h2>Two-step verification</h2>
            <p class="sub">{{ useRecovery() ? 'Enter one of your recovery codes (like AB12-CD34).'
              : 'Open Google Authenticator on your phone and enter the 6-digit code for Synex QB Portal.' }}</p>
            <label for="c">{{ useRecovery() ? 'Recovery code' : 'Authenticator code' }}</label>
            <div class="input">
              <mat-icon>pin</mat-icon>
              <input id="c" name="code" [(ngModel)]="code" required autocomplete="one-time-code" autofocus
                     [attr.inputmode]="useRecovery() ? 'text' : 'numeric'" [attr.maxlength]="useRecovery() ? 9 : 6"
                     [placeholder]="useRecovery() ? 'XXXX-XXXX' : '123456'" class="code" />
            </div>
            @if (error()) { <div class="note err" role="alert"><mat-icon>error_outline</mat-icon>{{ error() }}</div> }
            <button class="go" [disabled]="busy() || code.trim().length < 6">
              @if (busy()) { <mat-spinner diameter="20" /> } @else { Verify }
            </button>
            <div class="links">
              <button type="button" class="link" (click)="useRecovery.set(!useRecovery()); code = ''; error.set('')">
                {{ useRecovery() ? 'Use the authenticator app' : 'Lost your phone? Use a recovery code' }}</button>
              <button type="button" class="link" (click)="back()">Back</button>
            </div>
          </form>
        } @else {
        <form class="form" (ngSubmit)="submit()" [class.shake]="shake()">
          <img class="mobile-logo" src="logo.png" alt="Synex Group" width="72" height="72" />
          <h2>Sign in</h2>
          <p class="sub">Use the account your administrator gave you.</p>

          <label for="u">E-mail or username</label>
          <div class="input">
            <mat-icon>alternate_email</mat-icon>
            <input id="u" name="username" [(ngModel)]="username" required autocomplete="username" autofocus
                   placeholder="name@synexint.com" />
          </div>

          <label for="p">Password</label>
          <div class="input">
            <mat-icon>lock_outline</mat-icon>
            <input id="p" name="password" [type]="show() ? 'text' : 'password'" [(ngModel)]="password" required
                   autocomplete="current-password" (keyup)="onKey($event)" />
            <button type="button" class="eye" (click)="show.set(!show())" [attr.aria-label]="show() ? 'Hide password' : 'Show password'">
              <mat-icon>{{ show() ? 'visibility_off' : 'visibility' }}</mat-icon></button>
          </div>
          @if (caps()) { <div class="note warn"><mat-icon>keyboard_capslock</mat-icon> Caps Lock is on</div> }
          @if (error()) { <div class="note err" role="alert"><mat-icon>error_outline</mat-icon>{{ error() }}</div> }

          <button class="go" [disabled]="busy() || !username || !password">
            @if (busy()) { <mat-spinner diameter="20" /> } @else { Sign in }
          </button>
        </form>
        }
        <small class="foot">© {{ year }} Synex Group · Since 1999</small>
      </main>
    </div>
  `,
  styles: [`
    :host { --brand: #0a5c80; --brand-dark: #073f59; --ink: #0f2533; --muted: #5f7584; --line: #d6e0e7; }
    .page { min-height: 100vh; display: grid; grid-template-columns: minmax(420px, 46%) 1fr; background: #fff; }

    /* brand panel */
    .brand { position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: center;
      align-items: center; padding: 48px; color: #fff;
      background: linear-gradient(160deg, var(--brand) 0%, var(--brand-dark) 100%); }
    .pattern { position: absolute; inset: 0; opacity: .08; pointer-events: none;
      background-image: radial-gradient(#fff 1px, transparent 1px); background-size: 22px 22px; }
    .brand::after { content: ''; position: absolute; width: 520px; height: 520px; right: -200px; bottom: -220px;
      border-radius: 50%; border: 70px solid rgba(255,255,255,.05); pointer-events: none; }
    .brand-inner { position: relative; text-align: center; max-width: 380px; }
    .logo { width: 200px; height: 200px; object-fit: contain; }
    h1 { margin: 28px 0 10px; font-size: 34px; font-weight: 700; letter-spacing: -.02em; color: #fff; }
    .brand-inner p { margin: 0; font-size: 16px; line-height: 1.6; color: rgba(255,255,255,.82); }
    .points { position: absolute; bottom: 40px; left: 0; right: 0; display: flex; justify-content: center; gap: 22px;
      flex-wrap: wrap; list-style: none; margin: 0; padding: 0 24px; font-size: 13px; color: rgba(255,255,255,.8); }
    .points li { display: flex; align-items: center; gap: 6px; }
    .points mat-icon { font-size: 17px; width: 17px; height: 17px; color: rgba(255,255,255,.9); }

    /* form side */
    .side { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 24px; gap: 32px; }
    .form { width: 100%; max-width: 380px; display: flex; flex-direction: column; }
    .mobile-logo { display: none; }
    h2 { margin: 0; font-size: 30px; font-weight: 700; letter-spacing: -.02em; color: var(--ink); }
    .sub { margin: 8px 0 28px; color: var(--muted); font-size: 15px; }
    label { font-size: 13.5px; font-weight: 600; color: var(--ink); margin: 0 0 7px; }
    .input { display: flex; align-items: center; height: 50px; margin-bottom: 18px; border: 1.5px solid var(--line);
      border-radius: 10px; background: #fff; transition: border-color .15s, box-shadow .15s; }
    .input:focus-within { border-color: var(--brand); box-shadow: 0 0 0 4px rgba(10,92,128,.12); }
    .input > mat-icon { margin: 0 10px 0 14px; color: #8aa0ae; font-size: 21px; width: 21px; height: 21px; }
    .input:focus-within > mat-icon { color: var(--brand); }
    .input input { flex: 1; min-width: 0; height: 100%; border: 0; outline: 0; background: transparent; font: inherit;
      font-size: 15px; color: var(--ink); border-radius: 10px; }
    /* browser autofill: keep the white field instead of the yellow/blue fill */
    .input input:-webkit-autofill, .input input:-webkit-autofill:hover, .input input:-webkit-autofill:focus {
      -webkit-box-shadow: 0 0 0 100px #fff inset; -webkit-text-fill-color: var(--ink); caret-color: var(--ink);
      transition: background-color 9999s; }
    .eye { border: 0; background: none; color: #8aa0ae; cursor: pointer; height: 100%; padding: 0 14px; display: grid; place-items: center; }
    .eye:hover { color: var(--brand); }

    .note { display: flex; align-items: center; gap: 8px; margin: -6px 0 16px; font-size: 13.5px; }
    .note mat-icon { font-size: 18px; width: 18px; height: 18px; }
    .note.warn { color: #9a5b00; } .note.err { color: #c2410c; }

    .go { height: 50px; margin-top: 6px; border: 0; border-radius: 10px; cursor: pointer; font: inherit; font-size: 15.5px;
      font-weight: 600; color: #fff; background: var(--brand); display: grid; place-items: center;
      transition: background .15s, box-shadow .15s; }
    .go:hover:not(:disabled) { background: var(--brand-dark); box-shadow: 0 8px 20px rgba(10,92,128,.25); }
    .go:disabled { opacity: .5; cursor: default; }
    .go mat-spinner { --mdc-circular-progress-active-indicator-color: #fff; }
    .foot { color: #8aa0ae; font-size: 12.5px; }
    .input input::placeholder { color: #a9b8c2; }
    .code { letter-spacing: .3em; font-size: 20px !important; font-variant-numeric: tabular-nums; }
    .shield { width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; margin-bottom: 14px;
      background: #e6f0f5; color: var(--brand); }
    .links { display: flex; justify-content: space-between; margin-top: 14px; }
    .link { border: 0; background: none; color: var(--brand); font: inherit; font-size: 13.5px; cursor: pointer; padding: 0; }
    .link:hover { text-decoration: underline; }

    .shake { animation: shake .35s; }
    @keyframes shake { 25%, 75% { transform: translateX(-6px); } 50% { transform: translateX(6px); } }

    @media (max-width: 900px) {
      .page { grid-template-columns: 1fr; }
      .brand { display: none; }
      .mobile-logo { display: block; margin-bottom: 20px; }
    }
    @media (prefers-reduced-motion: reduce) { .shake { animation: none; } }
  `],
})
export class LoginComponent {
  private auth = inject(AuthService);
  private router = inject(Router);
  username = '';
  password = '';
  busy = signal(false);
  show = signal(false);
  caps = signal(false);
  shake = signal(false);
  error = signal('');
  mfaToken = signal<string | null>(null);
  useRecovery = signal(false);
  code = '';
  year = new Date().getFullYear();

  async verify() {
    this.busy.set(true);
    this.error.set('');
    try {
      await this.auth.verifyCode(this.mfaToken()!, this.code.trim());
      this.router.navigate(['/']);
    } catch (e) {
      this.error.set(errorText(e));
      if (/expired/i.test(this.error())) this.back();
      this.shake.set(true);
      setTimeout(() => this.shake.set(false), 400);
      this.code = '';
    } finally {
      this.busy.set(false);
    }
  }

  back() { this.mfaToken.set(null); this.useRecovery.set(false); this.code = ''; }

  onKey(e: KeyboardEvent) { this.caps.set(!!e.getModifierState?.('CapsLock')); }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      const mfa = await this.auth.login(this.username, this.password);
      if (mfa) {
        this.mfaToken.set(mfa);
        this.password = '';
        return;
      }
      this.router.navigate(['/']);
    } catch (e) {
      this.error.set(errorText(e));
      this.shake.set(true);
      setTimeout(() => this.shake.set(false), 400);
    } finally {
      this.busy.set(false);
    }
  }
}
