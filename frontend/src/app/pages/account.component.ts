import { HttpClient } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { AuthService, errorText } from '../core/auth';
import { InsightsService } from '../core/insights.service';

@Component({
  selector: 'app-account',
  standalone: true,
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule],
  template: `
    <div class="head"><div><h1>Account &amp; security</h1>
      <div class="sub">{{ auth.me()?.full_name || auth.me()?.username }} · {{ auth.me()?.email }}</div></div></div>

    <div class="grid">
      <!-- two-factor -->
      <section class="panel">
        <div class="title">
          <span class="ic" [class.on]="auth.me()?.totp_enabled"><mat-icon>phonelink_lock</mat-icon></span>
          <div><h2>Two-step verification</h2>
            <span class="tag" [class.ok]="auth.me()?.totp_enabled" [class.warn]="!auth.me()?.totp_enabled">
              {{ auth.me()?.totp_enabled ? 'On' : 'Off' }}</span></div>
        </div>
        <p class="muted">After your password, sign-in also asks for a 6-digit code from <strong>Google Authenticator</strong>
          (or Microsoft Authenticator / Authy) on your phone. Someone who learns your password still cannot get in.</p>

        @if (codes(); as list) {
          <div class="codes">
            <strong><mat-icon>key</mat-icon> Save your recovery codes</strong>
            <p class="muted small">Each code works once if you lose your phone. Keep them somewhere safe - they are not shown again.</p>
            <div class="list">@for (c of list; track c) { <code>{{ c }}</code> }</div>
            <button mat-stroked-button (click)="copy(list)"><mat-icon>content_copy</mat-icon> Copy</button>
            <button mat-stroked-button (click)="download(list)"><mat-icon>download</mat-icon> Download</button>
            <button mat-flat-button color="primary" (click)="codes.set(null)">I saved them</button>
          </div>
        } @else if (!auth.me()?.totp_enabled) {
          @if (setup(); as s) {
            <ol class="steps">
              <li>Install <strong>Google Authenticator</strong> from the App Store or Google Play.</li>
              <li>In the app tap <strong>+</strong> → <strong>Scan a QR code</strong> and scan this:</li>
            </ol>
            <div class="qr"><img [src]="s.qr" alt="QR code for Google Authenticator" width="200" height="200" />
              <div class="manual"><span class="muted small">Can't scan? Enter this key:</span><code>{{ group(s.secret) }}</code></div></div>
            <ol class="steps" start="3"><li>Type the 6-digit code the app shows:</li></ol>
            <div class="row">
              <mat-form-field><mat-label>Code</mat-label>
                <input matInput [(ngModel)]="code" maxlength="6" inputmode="numeric" autocomplete="one-time-code" /></mat-form-field>
              <button mat-flat-button color="primary" [disabled]="code.length !== 6 || busy()" (click)="enable()">Turn on</button>
              <button mat-button (click)="setup.set(null)">Cancel</button>
            </div>
          } @else {
            <button mat-flat-button color="primary" (click)="start()" [disabled]="busy()"><mat-icon>qr_code_2</mat-icon> Set up Google Authenticator</button>
          }
        } @else {
          <div class="row">
            <mat-form-field><mat-label>Authenticator code</mat-label>
              <input matInput [(ngModel)]="code" maxlength="9" autocomplete="one-time-code" /></mat-form-field>
            <button mat-stroked-button [disabled]="code.length < 6 || busy()" (click)="renew()"><mat-icon>autorenew</mat-icon> New recovery codes</button>
          </div>
          <details class="off">
            <summary>Turn off two-step verification</summary>
            <div class="row">
              <mat-form-field><mat-label>Password</mat-label><input matInput type="password" [(ngModel)]="offPassword" /></mat-form-field>
              <mat-form-field><mat-label>Authenticator code</mat-label><input matInput [(ngModel)]="offCode" maxlength="9" /></mat-form-field>
              <button mat-stroked-button color="warn" [disabled]="!offPassword || offCode.length < 6 || busy()" (click)="disable()">Turn off</button>
            </div>
          </details>
        }
      </section>

      <!-- daily summary -->
      <section class="panel">
        <div class="title"><span class="ic on"><mat-icon>mark_email_unread</mat-icon></span>
          <div><h2>Daily summary e-mail</h2>
            <span class="tag" [class.ok]="daily()" [class.warn]="!daily()">{{ daily() ? 'On' : 'Off' }}</span></div></div>
        <p class="muted">Every morning: yesterday's sales and payments, what customers owe, bills due this week, items to reorder
          and changes waiting for approval. Sent to {{ auth.me()?.email }}.</p>
        <div class="row">
          <button mat-stroked-button (click)="setDaily(!daily())" [disabled]="busy()">
            <mat-icon>{{ daily() ? 'notifications_off' : 'notifications_active' }}</mat-icon> {{ daily() ? 'Turn off' : 'Turn on' }}</button>
          <button mat-stroked-button (click)="preview()" [disabled]="busy()"><mat-icon>visibility</mat-icon> Preview</button>
          <button mat-stroked-button (click)="sendNow()" [disabled]="busy()"><mat-icon>send</mat-icon> Send me one now</button>
        </div>
        @if (digest()) { <pre class="digest">{{ digest() }}</pre> }
      </section>

      <!-- password -->
      <section class="panel">
        <div class="title"><span class="ic"><mat-icon>password</mat-icon></span><div><h2>Change password</h2></div></div>
        <div class="col">
          <mat-form-field><mat-label>Current password</mat-label><input matInput type="password" [(ngModel)]="cur" autocomplete="current-password" /></mat-form-field>
          <mat-form-field><mat-label>New password (8+ characters)</mat-label><input matInput type="password" [(ngModel)]="next" autocomplete="new-password" /></mat-form-field>
          <mat-form-field><mat-label>Repeat new password</mat-label><input matInput type="password" [(ngModel)]="next2" autocomplete="new-password" /></mat-form-field>
          @if (next && next2 && next !== next2) { <span class="err small">The new passwords do not match.</span> }
          <button mat-flat-button color="primary" [disabled]="!cur || next.length < 8 || next !== next2 || busy()" (click)="changePassword()">Change password</button>
        </div>
      </section>
    </div>
  `,
  styles: [`
    .grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 16px; align-items: start; }
    @media (max-width: 1000px) { .grid { grid-template-columns: 1fr; } }
    .title { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; } .title h2 { margin: 0 0 2px; }
    .ic { width: 40px; height: 40px; border-radius: 11px; display: grid; place-items: center; background: var(--warn-soft); color: var(--warn); }
    .ic.on { background: var(--ok-soft); color: var(--ok); }
    .title .ic:not(.on):has(mat-icon) { }
    .steps { margin: 8px 0; padding-left: 20px; } .steps li { margin: 4px 0; }
    .qr { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; margin: 8px 0 4px; }
    .qr img { border: 1px solid var(--line); border-radius: 12px; background: #fff; padding: 6px; }
    .manual { display: flex; flex-direction: column; gap: 4px; }
    code { background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px; padding: 3px 8px; font-size: 14px; letter-spacing: .05em; }
    .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; } .row mat-form-field { width: 220px; }
    .col { display: flex; flex-direction: column; gap: 6px; } .col button { align-self: flex-start; }
    .codes { padding: 14px; border-radius: 12px; background: var(--primary-soft); }
    .codes strong { display: flex; align-items: center; gap: 6px; }
    .codes .list { display: grid; grid-template-columns: repeat(4, max-content); gap: 8px; margin: 10px 0 14px; }
    .codes button { margin-right: 8px; }
    .off { margin-top: 12px; } .off summary { cursor: pointer; color: var(--muted); font-size: 13.5px; }
    .small { font-size: 12.5px; } .err { color: var(--danger); }
    .digest { white-space: pre-wrap; font: 12.5px/1.5 ui-monospace, Consolas, monospace; background: var(--surface-2);
      border: 1px solid var(--line); border-radius: 10px; padding: 12px; margin: 12px 0 0; max-height: 360px; overflow: auto; }
  `],
})
export class AccountComponent {
  auth = inject(AuthService);
  private http = inject(HttpClient);
  private snack = inject(MatSnackBar);
  private insights = inject(InsightsService);
  daily = computed(() => this.insights.prefs()?.daily_summary ?? true);
  digest = signal<string | null>(null);
  setup = signal<{ secret: string; qr: string } | null>(null);
  codes = signal<string[] | null>(null);
  busy = signal(false);
  code = '';
  offPassword = '';
  offCode = '';
  cur = '';
  next = '';
  next2 = '';

  constructor() { this.insights.loadPrefs().catch(() => undefined); }

  async setDaily(on: boolean) {
    await this.run(() => firstValueFrom(this.insights.savePrefs({ daily_summary: on })), on ? 'Daily summary turned on' : 'Daily summary turned off');
  }
  async preview() {
    const d = await this.run(() => firstValueFrom(this.insights.digest()));
    if (d) this.digest.set(d.body);
  }
  async sendNow() { await this.run(() => firstValueFrom(this.insights.sendDigest()).then((r) => { this.snack.open(r.message, '', { duration: 3000 }); })); }

  group(secret: string) { return secret.replace(/(.{4})/g, '$1 ').trim(); }

  private async run<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
    this.busy.set(true);
    try {
      const r = await fn();
      if (ok) this.snack.open(ok, '', { duration: 3000 });
      return r;
    } catch (e) {
      this.snack.open(errorText(e), 'OK');
      return undefined;
    } finally {
      this.busy.set(false);
    }
  }

  async start() {
    const s = await this.run(() => firstValueFrom(this.http.post<{ secret: string; qr: string }>('/api/auth/2fa/setup', {})));
    if (s) { this.setup.set(s); this.code = ''; }
  }

  async enable() {
    const r = await this.run(() => firstValueFrom(this.http.post<{ recovery_codes: string[] }>('/api/auth/2fa/enable', { code: this.code })),
      'Two-step verification is on');
    if (r) { this.codes.set(r.recovery_codes); this.setup.set(null); this.code = ''; await this.auth.loadMe(); }
  }

  async renew() {
    const r = await this.run(() => firstValueFrom(this.http.post<{ recovery_codes: string[] }>('/api/auth/2fa/recovery-codes', { code: this.code })));
    if (r) { this.codes.set(r.recovery_codes); this.code = ''; }
  }

  async disable() {
    const r = await this.run(() => firstValueFrom(this.http.post('/api/auth/2fa/disable', { password: this.offPassword, code: this.offCode })),
      'Two-step verification is off');
    if (r !== undefined) { this.offPassword = this.offCode = ''; await this.auth.loadMe(); }
  }

  async changePassword() {
    const r = await this.run(() => firstValueFrom(this.http.post('/api/auth/change-password', { current_password: this.cur, new_password: this.next })),
      'Password changed');
    if (r !== undefined) { this.cur = this.next = this.next2 = ''; }
  }

  copy(list: string[]) { navigator.clipboard?.writeText(list.join('\n')); this.snack.open('Copied', '', { duration: 1500 }); }

  download(list: string[]) {
    const blob = new Blob([`Synex QB Portal recovery codes for ${this.auth.me()?.email}\n\n${list.join('\n')}\n`], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'synex-qb-portal-recovery-codes.txt';
    a.click();
    URL.revokeObjectURL(a.href);
  }
}
