import { DatePipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../core/api.service';
import { AuthService, errorText } from '../core/auth';
import { QBWrite } from '../core/models';

const KIND_LABEL: Record<string, string> = { qb_add: 'Create', qb_mod: 'Edit', qb_delete: 'Delete', qb_void: 'Void' };

@Component({
  selector: 'app-qb-changes',
  standalone: true,
  imports: [DatePipe, MatButtonModule, MatButtonToggleModule, MatIconModule],
  template: `
    <div class="head">
      <h1>QuickBooks changes</h1>
      <span class="spacer"></span>
      <mat-button-toggle-group [value]="filter()" (change)="filter.set($event.value); load()">
        <mat-button-toggle value="pending">Awaiting approval</mat-button-toggle>
        <mat-button-toggle value="approved,sent">Queued</mat-button-toggle>
        <mat-button-toggle value="failed">Failed</mat-button-toggle>
        <mat-button-toggle value="done,rejected">History</mat-button-toggle>
      </mat-button-toggle-group>
    </div>
    <p class="muted">Changes made here are written to QuickBooks Desktop only after approval, the next time
      Web Connector polls (within a few minutes). Nothing is written to QuickBooks until then.</p>

    <div class="panel flush scroll">
      <table class="simple">
        <tr><th>Type</th><th>Change</th><th>Requested</th><th>Status</th><th></th></tr>
        @for (w of rows(); track w.write_id) {
          <tr>
            <td><span class="tag">{{ label[w.kind] || w.kind }}</span>
              <div class="muted small">{{ w.payload['module'] }}</div></td>
            <td>{{ w.summary }}
              @if (w.error_message) { <div class="err">{{ w.error_message }}</div> }
              @if (w.qb_ref && w.status === 'done') { <div class="muted small">QuickBooks ref: {{ w.qb_ref }}</div> }
            </td>
            <td>{{ w.requested_by }}<div class="muted small">{{ w.requested_at | date: 'short' }}</div></td>
            <td><span class="tag" [class.ok]="w.status === 'done'" [class.bad]="w.status === 'failed' || w.status === 'rejected'">
              {{ w.status === 'approved' ? 'queued' : w.status }}</span>
              @if (w.sent_at) { <div class="muted small">{{ w.sent_at | date: 'short' }}</div> }
            </td>
            <td class="actions">
              @if (canApprove(w)) {
                @if (w.status === 'pending') {
                  <button mat-flat-button color="primary" (click)="approve(w)">Approve</button>
                  <button mat-stroked-button (click)="reject(w)">Reject</button>
                }
                @if (w.status === 'failed') {
                  <button mat-stroked-button (click)="retry(w)"><mat-icon>replay</mat-icon> Retry</button>
                  <button mat-button (click)="reject(w)">Discard</button>
                }
              }
            </td>
          </tr>
        } @empty { <tr><td colspan="5" class="muted">Nothing here.</td></tr> }
      </table>
    </div>
  `,
  styles: [`.actions { white-space: nowrap; } .actions button { margin-right: 6px; } .small { font-size: 12px; }
    .err { color: var(--danger); font-size: 12px; margin-top: 4px; }`],
})
export class QbChangesComponent implements OnInit {
  private api = inject(ApiService);
  private snack = inject(MatSnackBar);
  private auth = inject(AuthService);
  canApprove(w: QBWrite) {
    return this.auth.can(`${w.payload?.['module'] as string}.approve`);
  }
  label = KIND_LABEL;
  filter = signal('pending');
  rows = signal<QBWrite[]>([]);

  ngOnInit() { this.load(); }
  load() { this.api.qbWrites(this.filter()).subscribe((r) => this.rows.set(r)); }

  private done(msg: string) {
    return {
      next: () => { this.snack.open(msg, '', { duration: 2500 }); this.load(); },
      error: (e: unknown) => this.snack.open(errorText(e), 'OK'),
    };
  }

  approve(w: QBWrite) { this.api.qbWriteApprove(w.write_id).subscribe(this.done('Approved - will be sent on the next sync')); }
  retry(w: QBWrite) { this.api.qbWriteRetry(w.write_id).subscribe(this.done('Queued again')); }
  reject(w: QBWrite) {
    const note = prompt('Reason') ?? '';
    if (!note) return;
    this.api.qbWriteReject(w.write_id, note).subscribe(this.done('Rejected'));
  }
}
