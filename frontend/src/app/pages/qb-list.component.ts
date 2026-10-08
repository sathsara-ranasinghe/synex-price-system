import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { Router, RouterLink } from '@angular/router';
import { Subject, debounceTime } from 'rxjs';
import { EntityMeta, FieldMeta, QbRecord } from '../core/models';
import { ApiService } from '../core/api.service';
import { PortalService } from '../core/portal.service';
import { HumanizePipe, MoneyPipe } from '../shared/shared';

// shown in fixed columns already
const FIXED = ['Name', 'RefNumber', 'TxnDate', 'CustomerRef', 'VendorRef', 'PayeeEntityRef'];

@Component({
  selector: 'app-qb-list',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule,
    MatPaginatorModule, MatProgressBarModule, MatSelectModule, MoneyPipe, HumanizePipe],
  template: `
    @if (ent(); as e) {
      <div class="head">
        <h1>{{ e.plural }}</h1>
        <span class="spacer"></span>
        <button mat-stroked-button (click)="exportExcel()"><mat-icon>table_view</mat-icon> Excel</button>
        @if (e.can_add && e.permissions.create) {
          <a mat-stroked-button [routerLink]="['/qb', e.key, 'import']"><mat-icon>upload_file</mat-icon> Import</a>
        }
        @if (e.can_add && e.permissions.create) {
          <a mat-flat-button color="primary" [routerLink]="['/qb', e.key, 'new']"><mat-icon>add</mat-icon> New {{ e.label.toLowerCase() }}</a>
        }
      </div>
      <div class="filters">
        <mat-form-field class="grow">
          <mat-icon matPrefix>search</mat-icon><mat-label>Search</mat-label>
          <input matInput [(ngModel)]="q" (ngModelChange)="typed$.next()" />
        </mat-form-field>
        @if (e.kind === 'list') {
          <mat-form-field class="narrow"><mat-label>Status</mat-label>
            <mat-select [(ngModel)]="active" (selectionChange)="reload(true)">
              <mat-option [value]="true">Active</mat-option><mat-option [value]="false">Inactive</mat-option>
              <mat-option [value]="null">All</mat-option>
            </mat-select>
          </mat-form-field>
        } @else {
          <mat-form-field class="narrow"><mat-label>From</mat-label><input matInput type="date" [(ngModel)]="from" (change)="reload(true)" /></mat-form-field>
          <mat-form-field class="narrow"><mat-label>To</mat-label><input matInput type="date" [(ngModel)]="to" (change)="reload(true)" /></mat-form-field>
        }
      </div>
      <div class="panel flush">
        @if (loading()) { <mat-progress-bar mode="indeterminate" /> }
        <div class="scroll">
          <table class="simple">
            <tr>
              <th>{{ e.kind === 'txn' ? 'No.' : 'Name' }}</th>
              @if (e.kind === 'txn') { <th>Date</th><th>Name</th> }
              @for (c of cols(); track c.path) { <th [class.num]="isNum(c)">{{ c.label }}</th> }
              @if (e.kind === 'txn') { <th class="num">Amount</th> }
            </tr>
            @for (r of rows(); track r.record_id) {
              <tr class="clickable" (click)="open(r)">
                <td><a [routerLink]="['/qb', e.key, r.record_id]" (click)="$event.stopPropagation()">{{ r.name || '(no number)' }}</a>
                  @if (!r.is_active) { <span class="tag">inactive</span> }</td>
                @if (e.kind === 'txn') { <td>{{ r.txn_date | date: 'mediumDate' }}</td><td>{{ r.party_name }}</td> }
                @for (c of cols(); track c.path) {
                  <td [class.num]="isNum(c)">{{ isNum(c) ? (r.columns[c.path] | money) : (r.columns[c.path] | humanize) }}</td>
                }
                @if (e.kind === 'txn') { <td class="num">{{ r.amount | money }}</td> }
              </tr>
            } @empty { <tr><td colspan="20" class="muted">Nothing found. Data appears after the next QuickBooks sync.</td></tr> }
          </table>
        </div>
        <mat-paginator [length]="total()" [pageIndex]="page - 1" [pageSize]="pageSize" [pageSizeOptions]="[25, 50, 100]"
                       (page)="onPage($event)" showFirstLastButtons />
      </div>
    }
  `,
  styles: [`.narrow { width: 160px; }`],
})
export class QbListComponent {
  entity = input.required<string>();
  private portal = inject(PortalService);
  private router = inject(Router);
  private api = inject(ApiService);
  ent = signal<EntityMeta | null>(null);
  rows = signal<QbRecord[]>([]);
  total = signal(0);
  loading = signal(false);
  typed$ = new Subject<void>();
  cols = computed(() => (this.ent()?.fields ?? []).filter((f) => f.list && !FIXED.includes(f.path)));

  q = '';
  active: boolean | null = true;
  from = '';
  to = '';
  page = 1;
  pageSize = 25;

  constructor() {
    this.typed$.pipe(debounceTime(300)).subscribe(() => this.reload(true));
    effect(() => {
      const key = this.entity();
      this.portal.load().then(() => {
        this.ent.set(this.portal.entity(key) ?? null);
        this.q = ''; this.from = ''; this.to = ''; this.page = 1;
        this.reload();
      });
    }, { allowSignalWrites: true });
  }

  isNum(f: FieldMeta) { return f.type === 'money' || f.type === 'decimal'; }

  reload(reset = false) {
    const e = this.ent();
    if (!e) return;
    if (reset) this.page = 1;
    this.loading.set(true);
    this.portal.list(e.key, { q: this.q, active: e.kind === 'list' ? this.active : null, date_from: this.from, date_to: this.to,
      page: this.page, page_size: this.pageSize }).subscribe({
      next: (p) => { this.rows.set(p.items); this.total.set(p.total); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  exportExcel() {
    const e = this.ent()!;
    this.api.download(`/files/export/${e.key}`, { q: this.q, active: e.kind === 'list' ? this.active : null,
      date_from: this.from, date_to: this.to }).subscribe();
  }

  onPage(e: PageEvent) { this.page = e.pageIndex + 1; this.pageSize = e.pageSize; this.reload(); }
  open(r: QbRecord) { this.router.navigate(['/qb', r.entity, r.record_id]); }
}
