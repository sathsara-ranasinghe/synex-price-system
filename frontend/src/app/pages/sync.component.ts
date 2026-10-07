import { DatePipe } from '@angular/common';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { forkJoin } from 'rxjs';
import { ApiService } from '../core/api.service';
import { errorText } from '../core/auth';
import { CompanyService } from '../core/company.service';
import { SyncLog, SyncStatus } from '../core/models';

@Component({
  selector: 'app-sync',
  standalone: true,
  imports: [DatePipe, MatButtonModule, MatIconModule, MatProgressBarModule],
  template: `
    <div class="head">
      <h1>QuickBooks Desktop sync</h1>
      <span class="spacer"></span>
      <button mat-stroked-button (click)="request(true)"><mat-icon>restart_alt</mat-icon> Full re-sync</button>
      <button mat-flat-button color="primary" (click)="request(false)"><mat-icon>sync</mat-icon> Sync now</button>
    </div>

    @if (status(); as s) {
      <section class="panel">
        @if (s.running; as r) {
          <p><strong>Sync running</strong> since {{ r.started_at | date: 'mediumTime' }} ({{ r.triggered_by }})</p>
          <mat-progress-bar mode="determinate" [value]="r.progress" />
        } @else if (s.pending_request) {
          <p><mat-icon class="inline">schedule</mat-icon> Sync requested — waiting for Web Connector on the VPS to poll.</p>
        } @else {
          <p>Last successful sync: <strong>{{ s.last_success ? (s.last_success.started_at | date: 'medium') : 'never' }}</strong>.
            Automatic sync every {{ s.run_every_minutes }} minutes.</p>
        }
      </section>

      <section class="panel">
        <h2>How it connects</h2>
        <p class="muted">QuickBooks Desktop 2024 runs on the VPS. <strong>QuickBooks Web Connector</strong> on the same VPS polls this
          server at <code>{{ s.qbwc_url }}</code> and runs read-only queries (vendors, items, purchase orders, item receipts, bills)
          against this company's file. Changes approved in the portal are written on the same connection.</p>
        <ol>
          <li>Download the Web Connector file below and copy it to the VPS.</li>
          <li>Open QuickBooks Desktop on the VPS as Admin with the company file, in single-user mode.</li>
          <li>In Web Connector choose <em>Add an application</em>, select the .qwc file and allow access
            "even if QuickBooks is not running".</li>
          <li>Enter the Web Connector password (QBWC_PASSWORD from the server .env) and tick <em>Auto-Run</em>.</li>
        </ol>
        <button mat-stroked-button (click)="qwc()"><mat-icon>download</mat-icon> Download .qwc for {{ company.current()?.name }}</button>
      </section>
    }

    <section class="panel flush scroll">
      <table class="simple">
        <tr><th>Started</th><th>Finished</th><th>Trigger</th><th>Status</th><th class="num">New</th><th class="num">Updated</th>
          <th>Messages</th></tr>
        @for (l of logs(); track l.sync_id) {
          <tr>
            <td>{{ l.started_at | date: 'short' }}</td><td>{{ l.finished_at | date: 'shortTime' }}</td><td>{{ l.triggered_by }}</td>
            <td><span class="tag" [class.ok]="l.status === 'success'" [class.bad]="l.status === 'failed'">{{ l.status }}</span></td>
            <td class="num">{{ l.records_inserted }}</td><td class="num">{{ l.records_updated }}</td>
            <td class="msg">{{ l.error_message }}</td>
          </tr>
        } @empty { <tr><td colspan="8" class="muted">No sync has run yet.</td></tr> }
      </table>
    </section>
  `,
  styles: [`section { margin-bottom: 16px; } .msg { white-space: pre-wrap; font-size: 12px; max-width: 420px; }
    .inline { vertical-align: middle; } code { background: var(--primary-soft); padding: 1px 4px; border-radius: 4px; }`],
})
export class SyncComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  company = inject(CompanyService);
  private snack = inject(MatSnackBar);
  status = signal<SyncStatus | null>(null);
  logs = signal<SyncLog[]>([]);
  private timer?: ReturnType<typeof setInterval>;

  ngOnInit() {
    this.load();
    this.timer = setInterval(() => this.load(), 10_000);
  }
  ngOnDestroy() { clearInterval(this.timer); }

  load() {
    forkJoin([this.api.syncStatus(), this.api.syncLogs()]).subscribe(([s, l]) => { this.status.set(s); this.logs.set(l); });
  }

  request(full: boolean) {
    if (full && !confirm('Re-read every vendor, item and the last year of purchase transactions from QuickBooks?')) return;
    this.api.requestSync(full).subscribe({
      next: (r) => { this.snack.open(r.message, 'OK', { duration: 5000 }); this.load(); },
      error: (e) => this.snack.open(errorText(e), 'OK'),
    });
  }

  qwc() { this.api.download(`/companies/${this.company.current()?.company_id}/qwc`).subscribe(); }
}
