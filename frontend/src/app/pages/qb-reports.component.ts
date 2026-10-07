import { DatePipe } from '@angular/common';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { errorText } from '../core/auth';
import { ApiService } from '../core/api.service';
import { PortalService } from '../core/portal.service';

@Component({
  selector: 'app-qb-reports',
  standalone: true,
  imports: [DatePipe, FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatSelectModule],
  template: `
    <h1>QuickBooks reports</h1>
    <section class="panel run">
      <mat-form-field class="grow"><mat-label>Report</mat-label>
        <mat-select [(ngModel)]="type">
          @for (r of portal.meta()?.reports ?? []; track r.key) { <mat-option [value]="r.key">{{ r.label }}</mat-option> }
        </mat-select>
      </mat-form-field>
      <mat-form-field><mat-label>From</mat-label><input matInput type="date" [(ngModel)]="from" /></mat-form-field>
      <mat-form-field><mat-label>To</mat-label><input matInput type="date" [(ngModel)]="to" /></mat-form-field>
      <button mat-flat-button color="primary" [disabled]="!type" (click)="run()"><mat-icon>play_arrow</mat-icon> Run</button>
    </section>
    <p class="muted small">Reports are produced by QuickBooks itself on the next Web Connector poll, usually within a few minutes.</p>

    <div class="layout">
      <section class="panel flush history">
        <table class="simple">
          @for (r of list(); track r.report_id) {
            <tr class="clickable" [class.sel]="r.report_id === current()?.report_id" (click)="show(r.report_id)">
              <td>{{ r.label }}<div class="muted small">{{ r.from_date ?? '' }} {{ r.to_date ? '→ ' + r.to_date : '' }}</div></td>
              <td><span class="tag" [class.ok]="r.status === 'done'" [class.bad]="r.status === 'failed'">{{ r.status }}</span>
                <div class="muted small">{{ r.requested_at | date: 'short' }}</div></td>
            </tr>
          } @empty { <tr><td class="muted">No reports yet.</td></tr> }
        </table>
      </section>

      <section class="panel report">
        @if (current(); as c) {
          @if (c.status === 'done' && c.result) {
            <div class="rhead"><div><h2>{{ c.result.title }}</h2><div class="muted small">{{ c.result.subtitle }}</div></div>
              <button mat-stroked-button (click)="excel(c.report_id)"><mat-icon>table_view</mat-icon> Excel</button></div>
            <div class="scroll">
              <table class="simple rep">
                <tr>@for (col of c.result.columns; track $index) { <th [class.num]="$index > 0">{{ col }}</th> }</tr>
                @for (row of c.result.rows; track $index) {
                  <tr [class]="row.kind">
                    @for (cell of row.cells; track $index) { <td [class.num]="$index > 0">{{ $index > 0 ? fmt(cell) : cell }}</td> }
                  </tr>
                }
              </table>
            </div>
          } @else if (c.status === 'failed') {
            <p class="err">{{ c.error_message }}</p>
          } @else {
            <p class="muted"><mat-icon class="inline">schedule</mat-icon> Waiting for QuickBooks…</p>
          }
        } @else { <p class="muted">Run a report or pick one from the list.</p> }
      </section>
    </div>
  `,
  styles: [`
    .run { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; } .grow { flex: 1; min-width: 240px; }
    .small { font-size: 12px; } .layout { display: grid; grid-template-columns: 300px 1fr; gap: 16px; }
    @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
    tr.sel td { background: var(--primary-soft); }
    .rep tr.text td { font-weight: 600; padding-top: 14px; } .rep tr.subtotal td, .rep tr.total td { font-weight: 600; border-top: 2px solid var(--line); }
    .rhead { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; }
    .err { color: var(--danger); } .inline { vertical-align: middle; }
  `],
})
export class QbReportsComponent implements OnInit, OnDestroy {
  portal = inject(PortalService);
  private snack = inject(MatSnackBar);
  private api = inject(ApiService);
  list = signal<any[]>([]);
  current = signal<any | null>(null);
  type = '';
  from = new Date(new Date().getFullYear(), 0, 1).toISOString().slice(0, 10);
  to = new Date().toISOString().slice(0, 10);
  private timer?: ReturnType<typeof setInterval>;

  ngOnInit() {
    this.portal.load();
    this.refresh();
    this.timer = setInterval(() => {
      this.refresh();
      const c = this.current();
      if (c && c.status === 'queued') this.show(c.report_id);
    }, 8000);
  }
  ngOnDestroy() { clearInterval(this.timer); }

  refresh() { this.portal.reports().subscribe((r) => this.list.set(r)); }
  show(id: number) { this.portal.report(id).subscribe((r) => this.current.set(r)); }
  excel(id: number) { this.api.download(`/files/report/${id}`).subscribe(); }
  fmt(v: string) { const n = Number(v); return v === '' || isNaN(n) ? v : n.toLocaleString('en-LK', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

  run() {
    this.portal.runReport(this.type, this.from || null, this.to || null).subscribe({
      next: (r) => { this.refresh(); this.show(r.report_id); },
      error: (e) => this.snack.open(errorText(e), 'OK'),
    });
  }
}
