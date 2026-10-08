import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../core/api.service';
import { errorText } from '../core/auth';
import { Company, CompanyService } from '../core/company.service';

@Component({
  selector: 'app-companies',
  standalone: true,
  imports: [DatePipe, DecimalPipe, FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatMenuModule],
  template: `
    <div class="head">
      <div><h1>Companies</h1><div class="sub">Each QuickBooks company file has its own Web Connector login and its own data.</div></div>
      <span class="spacer"></span>
      @if (!form()) { <button mat-flat-button color="primary" (click)="startNew()"><mat-icon>add_business</mat-icon> Add company</button> }
    </div>

    @if (form(); as f) {
      <section class="panel form">
        <h2>{{ f.company_id ? 'Edit ' + f.name : 'New company' }}</h2>
        <div class="grid">
          <mat-form-field><mat-label>Company name</mat-label><input matInput [(ngModel)]="f.name" required (blur)="fillUser(f)" /></mat-form-field>
          <mat-form-field><mat-label>Web Connector username</mat-label>
            <input matInput [(ngModel)]="f.qbwc_username" [disabled]="!!f.company_id" required placeholder="synex_trading" />
            <mat-hint>Letters, numbers, _ . - only (no spaces)</mat-hint>
            @if (!f.company_id && f.qbwc_username && !userOk(f.qbwc_username)) {
              <mat-hint class="bad">No spaces or symbols - try {{ suggestUser(f.qbwc_username) }}</mat-hint> }</mat-form-field>
          <mat-form-field><mat-label>{{ f.company_id ? 'New Web Connector password (blank = keep)' : 'Web Connector password' }}</mat-label>
            <input matInput type="password" [(ngModel)]="f.password" minlength="8" autocomplete="new-password" /></mat-form-field>
        </div>
        @if (f.company_id) {
          <div class="grid">
            <mat-form-field><mat-label>Web Connector app name</mat-label><input matInput [(ngModel)]="f.app_name" maxlength="100" /></mat-form-field>
            <mat-form-field class="wide"><mat-label>Web Connector address (blank = server default)</mat-label>
              <input matInput [(ngModel)]="f.qbwc_url" placeholder="https://portal.synex.lk/qbwc" /></mat-form-field>
          </div>
          <div class="detect">
            <button mat-stroked-button type="button" (click)="detect()"><mat-icon>my_location</mat-icon> Use this computer's address</button>
            @if (suggestion(); as sg) { <span class="muted small">{{ sg.note }}</span> }
          </div>
          @if (f.app_name !== f.orig_app_name || (f.qbwc_url || '') !== (f.orig_qbwc_url || '')) {
            <div class="warn-box"><mat-icon>warning</mat-icon>
              <span>Changing the app name or address needs a new .qwc file. In Web Connector, <strong>Remove</strong> the old
                application, then <strong>Add</strong> the downloaded .qwc again. Until then this company will not sync.</span></div>
          }
        }
        <p class="muted small">Use a password of at least 8 characters. You type it once in Web Connector on the QuickBooks computer.</p>
        <div class="actions">
          <button mat-button (click)="form.set(null)">Cancel</button>
          <button mat-flat-button color="primary" (click)="save()" [disabled]="!valid(f)">Save</button>
        </div>
      </section>
    }

    <div class="cards">
      @for (c of rows(); track c.company_id) {
        <section class="panel card" [class.off]="!c.is_active">
          <div class="top">
            <span class="ic"><mat-icon>domain</mat-icon></span>
            <div class="title"><strong>{{ c.name }}</strong>
              <span class="muted small">{{ c.is_active ? 'Active' : 'Disabled' }} · {{ c.records | number }} records</span></div>
            <button mat-icon-button [matMenuTriggerFor]="m" aria-label="Company actions"><mat-icon>more_vert</mat-icon></button>
            <mat-menu #m="matMenu">
              <button mat-menu-item (click)="edit(c)"><mat-icon>edit</mat-icon>Edit name, password, app &amp; address</button>
              <button mat-menu-item (click)="qwc(c)"><mat-icon>download</mat-icon>Download .qwc file</button>
              @if (c.company_file) { <button mat-menu-item (click)="resetFile(c)"><mat-icon>link_off</mat-icon>Unbind company file</button> }
              <button mat-menu-item (click)="toggle(c)"><mat-icon>{{ c.is_active ? 'block' : 'check_circle' }}</mat-icon>
                {{ c.is_active ? 'Disable' : 'Enable' }}</button>
            </mat-menu>
          </div>
          <dl>
            <dt>Web Connector user</dt><dd><code>{{ c.qbwc_username }}</code></dd>
            <dt>Web Connector app</dt><dd>{{ c.app_name }}</dd>
            <dt>Web Connector address</dt><dd><code class="path">{{ c.effective_qbwc_url }}</code>
              @if (!c.qbwc_url) { <span class="muted small"> (server default)</span> }</dd>
            <dt>Company file</dt>
            <dd>@if (c.company_file) { <code class="path">{{ c.company_file }}</code> }
                @else { <span class="tag warn">Not connected yet</span> }</dd>
            <dt>Last sync</dt><dd>{{ c.last_sync ? (c.last_sync | date: 'medium') : 'Never' }}</dd>
          </dl>
          @if (!c.company_file) {
            <div class="steps">
              <strong>Connect this company</strong>
              <ol>
                <li>Download the <a (click)="qwc(c)">.qwc file</a> and copy it to the QuickBooks computer.</li>
                <li>Open this company's file in QuickBooks as Admin (single-user mode).</li>
                <li>Web Connector → Add an application → pick the .qwc → allow access → enter the password → Update Selected.</li>
              </ol>
              <span class="muted small">The first sync binds this company to that file. Later syncs from a different file are refused.</span>
            </div>
          }
        </section>
      }
    </div>
  `,
  styles: [`
    .form { margin-bottom: 18px; } .bad { color: var(--danger); }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px 16px; }
    .actions { display: flex; justify-content: flex-end; gap: 8px; } .small { font-size: 12.5px; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 16px; }
    .card.off { opacity: .6; }
    .top { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
    .ic { width: 40px; height: 40px; border-radius: 11px; display: grid; place-items: center; background: var(--primary-soft); color: var(--primary); }
    .title { flex: 1; display: flex; flex-direction: column; } .title strong { font-size: 15.5px; }
    dl { display: grid; grid-template-columns: 140px 1fr; gap: 8px 12px; margin: 0; font-size: 13.5px; }
    dt { color: var(--muted); } dd { margin: 0; min-width: 0; }
    code { background: var(--surface-2); border: 1px solid var(--line); padding: 1px 6px; border-radius: 6px; font-size: 12.5px; }
    .path { word-break: break-all; }
    .wide { grid-column: span 2; } @media (max-width: 700px) { .wide { grid-column: auto; } }
    .detect { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 4px 0 10px; }
    .warn-box { display: flex; gap: 10px; align-items: flex-start; padding: 10px 14px; margin-bottom: 10px; border-radius: 10px;
      background: var(--warn-soft); color: var(--warn); font-size: 13px; }
    .steps { margin-top: 14px; padding: 12px 14px; border-radius: 10px; background: var(--primary-soft); font-size: 13px; }
    .steps ol { margin: 6px 0; padding-left: 18px; } .steps a { cursor: pointer; text-decoration: underline; }
  `],
})
export class CompaniesComponent implements OnInit {
  private svc = inject(CompanyService);
  private api = inject(ApiService);
  private snack = inject(MatSnackBar);
  rows = signal<Company[]>([]);
  form = signal<{ company_id?: number; name: string; qbwc_username: string; password: string; app_name?: string;
    qbwc_url?: string; orig_app_name?: string; orig_qbwc_url?: string } | null>(null);
  suggestion = signal<{ url: string; note: string } | null>(null);

  ngOnInit() { this.load(); }
  load() { this.svc.all().subscribe((r) => this.rows.set(r)); }

  startNew() { this.form.set({ name: '', qbwc_username: '', password: '' }); }
  edit(c: Company) {
    this.suggestion.set(null);
    this.form.set({ company_id: c.company_id, name: c.name, qbwc_username: c.qbwc_username, password: '',
      app_name: c.app_name, qbwc_url: c.qbwc_url ?? '', orig_app_name: c.app_name, orig_qbwc_url: c.qbwc_url ?? '' });
  }

  detect() {
    this.svc.urlSuggestion().subscribe((sg) => {
      this.suggestion.set(sg);
      this.form.update((f) => (f ? { ...f, qbwc_url: sg.url } : f));
    });
  }

  private done(msg: string) {
    return {
      next: () => { this.snack.open(msg, '', { duration: 2500 }); this.form.set(null); this.load(); this.svc.load(); },
      error: (e: unknown) => this.snack.open(errorText(e), 'OK'),
    };
  }

  userOk(u: string) { return /^[A-Za-z0-9_.\-]{3,100}$/.test(u); }
  suggestUser(name: string) { return name.trim().toLowerCase().replace(/[^a-z0-9_.\-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 100); }
  fillUser(f: { company_id?: number; name: string; qbwc_username: string }) {
    if (!f.company_id && !f.qbwc_username && f.name) f.qbwc_username = this.suggestUser(f.name);
  }
  valid(f: { company_id?: number; name: string; qbwc_username: string; password: string }) {
    if ((f.name || '').trim().length < 2) return false;
    if (f.company_id) return !f.password || f.password.length >= 8;
    return this.userOk(f.qbwc_username) && (f.password || '').length >= 8;
  }

  save() {
    const f = this.form()!;
    if (f.company_id) {
      const body: Record<string, unknown> = { name: f.name, app_name: f.app_name, qbwc_url: f.qbwc_url ?? '' };
      if (f.password) body['qbwc_password'] = f.password;
      this.svc.update(f.company_id, body).subscribe(this.done('Company saved'));
    } else {
      this.svc.create({ name: f.name, qbwc_username: f.qbwc_username, qbwc_password: f.password }).subscribe(this.done('Company added'));
    }
  }

  toggle(c: Company) { this.svc.update(c.company_id, { is_active: !c.is_active }).subscribe(this.done(c.is_active ? 'Disabled' : 'Enabled')); }

  resetFile(c: Company) {
    if (!confirm(`Unbind ${c.name} from ${c.company_file}? The next sync binds it to whichever file Web Connector opens.`)) return;
    this.svc.update(c.company_id, { reset_company_file: true }).subscribe(this.done('Company file unbound'));
  }

  qwc(c: Company) { this.api.download(`/companies/${c.company_id}/qwc`).subscribe(); }
}
