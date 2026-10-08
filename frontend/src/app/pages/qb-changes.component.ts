import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { AuthService, errorText } from '../core/auth';
import { InsightsService, WriteDiff } from '../core/insights.service';
import { QBWrite } from '../core/models';

const KIND: Record<string, { label: string; icon: string }> = {
  qb_add: { label: 'New', icon: 'add_circle' }, qb_mod: { label: 'Edit', icon: 'edit' },
  qb_delete: { label: 'Delete', icon: 'delete' }, qb_void: { label: 'Void', icon: 'block' },
};
const TABS = [
  { key: 'pending', label: 'Awaiting approval', icon: 'pending_actions' },
  { key: 'approved,sent', label: 'Queued', icon: 'schedule_send' },
  { key: 'failed', label: 'Failed', icon: 'error_outline' },
  { key: 'done,rejected', label: 'History', icon: 'history' },
];

/** Approval inbox: see exactly what changes, approve or reject in one click, or approve many at once. */
@Component({
  selector: 'app-qb-changes',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, MatButtonModule, MatCheckboxModule, MatIconModule, MatProgressBarModule],
  template: `
    <div class="head">
      <div><h1>Changes &amp; approvals</h1>
        <div class="sub">Nothing is written to QuickBooks until it is approved. Approved changes go on the next Web Connector sync.</div></div>
    </div>

    <div class="tabs" role="tablist">
      @for (t of tabs; track t.key) {
        <button role="tab" [class.on]="filter() === t.key" (click)="setTab(t.key)">
          <mat-icon>{{ t.icon }}</mat-icon>{{ t.label }}
          @if (t.key === 'pending' && pendingCount()) { <span class="count">{{ pendingCount() }}</span> }
        </button>
      }
    </div>

    @if (filter() === 'pending' && approvable().length > 1) {
      <div class="bulk">
        <mat-checkbox [checked]="allPicked()" [indeterminate]="picked().size > 0 && !allPicked()" (change)="pickAll($event.checked)">
          Select all</mat-checkbox>
        <span class="spacer"></span>
        @if (picked().size) {
          <button mat-flat-button color="primary" (click)="approveSelected()" [disabled]="busy()">
            <mat-icon>done_all</mat-icon> Approve {{ picked().size }} selected</button>
        }
      </div>
    }

    @if (loading()) { <mat-progress-bar mode="indeterminate" /> }
    <div class="list">
      @for (w of rows(); track w.write_id) {
        <article class="card" [class.open]="openId() === w.write_id" [class.sel]="picked().has(w.write_id)">
          <div class="top" (click)="toggle(w)">
            @if (filter() === 'pending' && canApprove(w)) {
              <mat-checkbox (click)="$event.stopPropagation()" [checked]="picked().has(w.write_id)" (change)="pick(w, $event.checked)"
                            [attr.aria-label]="'Select ' + w.summary" />
            }
            <span class="kind" [class]="'kind ' + w.kind"><mat-icon>{{ kind(w).icon }}</mat-icon></span>
            <div class="txt">
              <strong>{{ w.summary }}</strong>
              <small class="muted">{{ kind(w).label }} · {{ w.payload['module'] }} · {{ w.requested_by }} · {{ w.requested_at | date: 'medium' }}</small>
              @if (w.error_message) { <div class="err">{{ w.error_message }}</div> }
            </div>
            <span class="tag" [class.ok]="w.status === 'done'" [class.bad]="w.status === 'failed' || w.status === 'rejected'"
                  [class.warn]="w.status === 'pending'">{{ w.status === 'approved' ? 'queued' : w.status }}</span>
            <mat-icon class="chev">expand_more</mat-icon>
          </div>

          @if (openId() === w.write_id) {
            <div class="body">
              @if (diff(); as d) {
                @if (d.record) {
                  <a class="rec" [routerLink]="['/qb', d.entity, d.record.record_id]"><mat-icon>open_in_new</mat-icon>
                    Open {{ d.label.toLowerCase() }} {{ d.record.name }}</a>
                }
                @if (d.fields.length) {
                  <table class="diff">
                    <tr><th>Field</th>
                      @if (w.kind !== 'qb_add') { <th>{{ w.status === 'pending' || w.status === 'failed' ? 'Now in QuickBooks' : 'Before' }}</th> }
                      @if (w.kind !== 'qb_delete' && w.kind !== 'qb_void') {
                        <th>{{ w.kind === 'qb_add' ? 'Value' : w.status === 'pending' || w.status === 'failed' ? 'Will become' : 'After' }}</th> }</tr>
                    @for (f of d.fields; track f.label) {
                      <tr><td class="muted">{{ f.label }}</td>
                        @if (w.kind !== 'qb_add') { <td><span class="old">{{ f.old ?? '(empty)' }}</span></td> }
                        @if (w.kind !== 'qb_delete' && w.kind !== 'qb_void') { <td><span class="new">{{ f.new ?? '(empty)' }}</span></td> }
                      </tr>
                    }
                  </table>
                }
                @if (d.lines_new.length || d.lines_old.length) {
                  <div class="lines">
                    @if (d.lines_old.length) { <div><h3>Lines now</h3>@for (l of d.lines_old; track $index) { <div class="ln old">{{ l }}</div> }</div> }
                    @if (d.lines_new.length) { <div><h3>{{ w.kind === 'qb_add' ? 'Lines' : 'Lines after' }}</h3>@for (l of d.lines_new; track $index) { <div class="ln new">{{ l }}</div> }</div> }
                  </div>
                }
                @if (!d.fields.length && !d.lines_new.length && !d.lines_old.length) { <p class="muted">No field details for this change.</p> }
              } @else { <mat-progress-bar mode="indeterminate" /> }

              @if (canApprove(w)) {
                <div class="actions">
                  @if (w.status === 'pending') {
                    <input class="note" [(ngModel)]="note" placeholder="Reason (needed to reject)" aria-label="Reason" />
                    <button mat-stroked-button color="warn" [disabled]="!note.trim() || busy()" (click)="reject(w)"><mat-icon>close</mat-icon> Reject</button>
                    <button mat-flat-button color="primary" [disabled]="busy()" (click)="approve(w)"><mat-icon>check</mat-icon> Approve</button>
                  }
                  @if (w.status === 'failed') {
                    <input class="note" [(ngModel)]="note" placeholder="Reason (optional)" aria-label="Reason" />
                    <button mat-button (click)="reject(w, true)">Discard</button>
                    <button mat-flat-button color="primary" (click)="retry(w)"><mat-icon>replay</mat-icon> Try again</button>
                  }
                </div>
              }
            </div>
          }
        </article>
      } @empty {
        @if (!loading()) {
          <div class="empty"><mat-icon>{{ filter() === 'pending' ? 'task_alt' : 'inbox' }}</mat-icon>
            <div>{{ filter() === 'pending' ? 'All caught up - nothing waiting for approval.' : 'Nothing here.' }}</div></div>
        }
      }
    </div>
  `,
  styles: [`
    .tabs { display: flex; gap: 4px; flex-wrap: wrap; border-bottom: 1px solid var(--line); margin-bottom: 14px; }
    .tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: none; font: inherit; font-size: 13.5px;
      font-weight: 500; color: var(--muted); padding: 10px 12px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
    .tabs button mat-icon { font-size: 18px; width: 18px; height: 18px; }
    .tabs button.on { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }
    .count { background: var(--warn); color: #fff; font-size: 11px; font-weight: 700; border-radius: 999px; padding: 1px 7px; }
    .bulk { display: flex; align-items: center; gap: 10px; padding: 6px 12px; margin-bottom: 10px; background: var(--surface);
      border: 1px solid var(--line); border-radius: 10px; }
    .list { display: flex; flex-direction: column; gap: 8px; }
    .card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden;
      transition: border-color .15s, box-shadow .15s; }
    .card.open { border-color: color-mix(in srgb, var(--primary) 35%, var(--line)); box-shadow: var(--shadow); }
    .card.sel { background: var(--primary-soft); }
    .top { display: flex; align-items: center; gap: 12px; padding: 12px 14px; cursor: pointer; }
    .kind { width: 34px; height: 34px; flex: none; border-radius: 9px; display: grid; place-items: center; background: var(--primary-soft); color: var(--primary); }
    .kind.qb_add { background: var(--ok-soft); color: var(--ok); } .kind.qb_delete, .kind.qb_void { background: var(--danger-soft); color: var(--danger); }
    .kind mat-icon { font-size: 19px; width: 19px; height: 19px; }
    .txt { flex: 1; min-width: 0; display: flex; flex-direction: column; } .txt strong { font-weight: 550; } .txt small { font-size: 12px; }
    .chev { color: var(--muted); transition: transform .15s; } .card.open .chev { transform: rotate(180deg); }
    .err { color: var(--danger); font-size: 12.5px; margin-top: 2px; }
    .body { padding: 4px 16px 16px 60px; }
    @media (max-width: 700px) { .body { padding-left: 16px; } }
    .rec { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; margin-bottom: 10px; }
    .rec mat-icon { font-size: 16px; width: 16px; height: 16px; }
    .diff { width: 100%; border-collapse: collapse; font-size: 13.5px; margin-bottom: 12px; }
    .diff th { text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); padding: 6px 8px;
      border-bottom: 1px solid var(--line); }
    .diff td { padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
    .old { background: var(--danger-soft); color: var(--danger); padding: 1px 6px; border-radius: 4px; text-decoration: line-through;
      text-decoration-color: color-mix(in srgb, var(--danger) 50%, transparent); }
    .new { background: var(--ok-soft); color: var(--ok); padding: 1px 6px; border-radius: 4px; font-weight: 550; }
    .lines { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 12px; }
    .lines h3 { margin: 0 0 6px; color: var(--muted); }
    .ln { font-size: 12.5px; padding: 6px 8px; border-radius: 6px; margin-bottom: 4px; }
    .ln.old { background: var(--danger-soft); } .ln.new { background: var(--ok-soft); }
    .actions { display: flex; gap: 8px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
    .note { flex: 1; min-width: 200px; max-width: 360px; height: 36px; padding: 0 10px; border: 1px solid var(--line-strong);
      border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; }
  `],
})
export class QbChangesComponent implements OnInit {
  private api = inject(ApiService);
  private svc = inject(InsightsService);
  private snack = inject(MatSnackBar);
  private auth = inject(AuthService);
  tabs = TABS;
  filter = signal('pending');
  rows = signal<QBWrite[]>([]);
  loading = signal(false);
  busy = signal(false);
  openId = signal<number | null>(null);
  diff = signal<WriteDiff | null>(null);
  picked = signal<Set<number>>(new Set());
  pendingCount = signal(0);
  note = '';

  approvable = computed(() => this.rows().filter((w) => w.status === 'pending' && this.canApprove(w)));
  allPicked = computed(() => this.approvable().length > 0 && this.approvable().every((w) => this.picked().has(w.write_id)));

  canApprove(w: QBWrite) { return this.auth.can(`${w.payload?.['module'] as string}.approve`); }
  kind(w: QBWrite) { return KIND[w.kind] ?? { label: w.kind, icon: 'sync' }; }

  ngOnInit() { this.load(); }

  setTab(k: string) { this.filter.set(k); this.openId.set(null); this.picked.set(new Set()); this.load(); }

  load() {
    this.loading.set(true);
    this.api.qbWrites(this.filter()).subscribe({
      next: (r) => {
        this.rows.set(r);
        this.loading.set(false);
        if (this.filter() === 'pending') this.pendingCount.set(r.length);
        if (r.length === 1 && this.filter() === 'pending') this.toggle(r[0]);
      },
      error: () => this.loading.set(false),
    });
    if (this.filter() !== 'pending') this.api.qbWrites('pending').subscribe((r) => this.pendingCount.set(r.length));
  }

  toggle(w: QBWrite) {
    if (this.openId() === w.write_id) { this.openId.set(null); return; }
    this.openId.set(w.write_id);
    this.note = '';
    this.diff.set(null);
    this.svc.diff(w.write_id).subscribe({ next: (d) => this.diff.set(d), error: () => this.diff.set({ kind: w.kind, entity: '', label: '',
      record: null, fields: [], lines_old: [], lines_new: [] }) });
  }

  pick(w: QBWrite, on: boolean) {
    const s = new Set(this.picked());
    if (on) s.add(w.write_id); else s.delete(w.write_id);
    this.picked.set(s);
  }
  pickAll(on: boolean) { this.picked.set(on ? new Set(this.approvable().map((w) => w.write_id)) : new Set()); }

  private after(msg: string) {
    return {
      next: () => { this.busy.set(false); this.snack.open(msg, '', { duration: 3000 }); this.openId.set(null); this.load(); },
      error: (e: unknown) => { this.busy.set(false); this.snack.open(errorText(e), 'OK'); },
    };
  }

  approve(w: QBWrite) { this.busy.set(true); this.api.qbWriteApprove(w.write_id).subscribe(this.after('Approved - goes to QuickBooks on the next sync')); }
  retry(w: QBWrite) { this.busy.set(true); this.api.qbWriteRetry(w.write_id).subscribe(this.after('Queued again')); }
  reject(w: QBWrite, discard = false) {
    const note = this.note.trim() || (discard ? 'Discarded' : '');
    if (!note) return;
    this.busy.set(true);
    this.api.qbWriteReject(w.write_id, note).subscribe(this.after(discard ? 'Discarded' : 'Rejected'));
  }

  approveSelected() {
    const ids = [...this.picked()];
    if (!confirm(`Approve ${ids.length} changes? They will be written to QuickBooks on the next sync.`)) return;
    this.busy.set(true);
    this.svc.approveMany(ids).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.picked.set(new Set());
        this.snack.open(`Approved ${r.approved.length}` + (r.skipped.length ? `, skipped ${r.skipped.length}` : ''), 'OK', { duration: 4000 });
        this.load();
      },
      error: (e) => { this.busy.set(false); this.snack.open(errorText(e), 'OK'); },
    });
  }
}
