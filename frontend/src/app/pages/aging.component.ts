import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, inject, input, signal, effect } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../core/auth';
import { Aging, AgingParty, BUCKETS, Bucket, InsightsService } from '../core/insights.service';
import { MoneyPipe } from '../shared/shared';

/** Who owes us (A/R) and whom we owe (A/P), split by how late it is. */
@Component({
  selector: 'app-aging',
  standalone: true,
  imports: [DatePipe, DecimalPipe, FormsModule, RouterLink, MatButtonModule, MatIconModule, MatProgressBarModule, MoneyPipe],
  template: `
    <div class="head">
      <div><h1>Aging</h1><div class="sub">Open invoices and bills by how many days they are past the due date · today {{ today | date: 'mediumDate' }}</div></div>
      <span class="spacer"></span>
      <div class="seg" role="tablist">
        @if (canAr()) { <button role="tab" [class.on]="side() === 'ar'" (click)="go('ar')"><mat-icon>call_received</mat-icon> Customers owe us</button> }
        @if (canAp()) { <button role="tab" [class.on]="side() === 'ap'" (click)="go('ap')"><mat-icon>call_made</mat-icon> We owe vendors</button> }
      </div>
    </div>

    @if (loading()) { <mat-progress-bar mode="indeterminate" /> }
    @if (data(); as a) {
      <div class="summary">
        <div class="total-card">
          <span>{{ a.side === 'ar' ? 'Total receivable' : 'Total payable' }}</span>
          <strong>{{ a.total | money }}</strong>
          <small [class.bad]="a.overdue > 0">{{ a.overdue | money }} overdue ({{ pct(a.overdue, a.total) }}%)</small>
        </div>
        <div class="buckets">
          @for (b of buckets; track b.key) {
            <button [class]="'bk ' + b.key + (filter() === b.key ? ' on' : '')" (click)="toggle(b.key)"
                    [attr.aria-pressed]="filter() === b.key">
              <span>{{ b.label }}</span><strong>{{ a.totals[b.key] | money }}</strong>
              <i class="bar"><i [style.width.%]="pct(a.totals[b.key], a.total)"></i></i>
            </button>
          }
        </div>
      </div>

      <div class="toolbar">
        <div class="searchbox"><mat-icon>search</mat-icon>
          <input [(ngModel)]="q" (ngModelChange)="qSig.set($event)" [placeholder]="'Find a ' + (a.side === 'ar' ? 'customer' : 'vendor') + '…'" aria-label="Search" /></div>
        @if (filter()) { <button mat-stroked-button (click)="filter.set(null)"><mat-icon>close</mat-icon> {{ bucketLabel(filter()!) }}</button> }
        <span class="muted small">{{ rows().length | number }} {{ a.side === 'ar' ? 'customers' : 'vendors' }}</span>
      </div>

      <section class="panel flush">
        <div class="scroll">
          <table class="simple">
            <thead><tr>
              <th>{{ a.side === 'ar' ? 'Customer' : 'Vendor' }}</th>
              @for (b of buckets; track b.key) { <th class="num">{{ b.label }}</th> }
              <th class="num">Total</th><th class="num">Oldest due</th>
            </tr></thead>
            <tbody>
              @for (p of rows(); track rowKey(p)) {
                <tr class="clickable" (click)="open(p)">
                  <td><strong>{{ p.name }}</strong><div class="muted small">{{ p.docs }} open {{ a.side === 'ar' ? 'invoice' : 'bill' }}{{ p.docs > 1 ? 's' : '' }}</div></td>
                  @for (b of buckets; track b.key) {
                    <td class="num" [class.zero]="!p[b.key]" [class.late]="b.key !== 'current' && p[b.key]">{{ p[b.key] ? (p[b.key] | money) : '–' }}</td>
                  }
                  <td class="num strong">{{ p.total | money }}</td>
                  <td class="num">{{ p.oldest_due | date: 'mediumDate' }}</td>
                </tr>
              } @empty {
                <tr><td colspan="8"><div class="empty"><mat-icon>celebration</mat-icon>
                  <div>{{ q || filter() ? 'Nothing matches.' : a.side === 'ar' ? 'No customer owes anything.' : 'Nothing to pay.' }}</div></div></td></tr>
              }
            </tbody>
          </table>
        </div>
      </section>
    }
  `,
  styles: [`
    .seg { display: inline-flex; padding: 3px; gap: 2px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; }
    .seg button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: none; font: inherit; font-size: 13.5px;
      font-weight: 500; color: var(--text-2); padding: 7px 14px; border-radius: 7px; cursor: pointer; }
    .seg button mat-icon { font-size: 18px; width: 18px; height: 18px; }
    .seg button.on { background: var(--surface); color: var(--primary); font-weight: 600; box-shadow: 0 1px 2px rgba(15, 23, 42, .1); }
    .summary { display: grid; grid-template-columns: 260px 1fr; gap: 14px; margin-bottom: 16px; }
    @media (max-width: 1000px) { .summary { grid-template-columns: 1fr; } }
    .total-card { display: flex; flex-direction: column; justify-content: center; gap: 4px; padding: 18px 20px; border-radius: var(--radius);
      color: #fff; background: linear-gradient(135deg, #0a5c80, #0b2e4f); }
    .total-card span { font-size: 12.5px; opacity: .8; } .total-card strong { font-size: 26px; letter-spacing: -.02em; }
    .total-card small { font-size: 12.5px; opacity: .9; } .total-card small.bad { color: #fecaca; opacity: 1; }
    .buckets { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
    @media (max-width: 800px) { .buckets { grid-template-columns: 1fr 1fr; } }
    .bk { display: flex; flex-direction: column; gap: 4px; text-align: left; padding: 14px; border-radius: var(--radius);
      border: 1px solid var(--line); background: var(--surface); font: inherit; cursor: pointer; color: var(--text);
      transition: border-color .15s, box-shadow .15s; --c: #16a34a; }
    .bk:hover { box-shadow: var(--shadow); } .bk.on { border-color: var(--c); box-shadow: 0 0 0 2px color-mix(in srgb, var(--c) 25%, transparent); }
    .bk span { font-size: 12px; color: var(--muted); font-weight: 500; } .bk strong { font-size: 17px; font-variant-numeric: tabular-nums; }
    .bk .bar { display: block; height: 5px; border-radius: 3px; background: var(--surface-2); overflow: hidden; }
    .bk .bar i { display: block; height: 100%; background: var(--c); border-radius: 3px; }
    .bk.d1_30 { --c: #eab308; } .bk.d31_60 { --c: #f97316; } .bk.d61_90 { --c: #ef4444; } .bk.d90_plus { --c: #b91c1c; }
    .toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
    .searchbox { flex: 1; min-width: 220px; max-width: 420px; display: flex; align-items: center; gap: 8px; height: 40px; padding: 0 12px;
      background: var(--surface); border: 1px solid var(--line-strong); border-radius: 10px; }
    .searchbox mat-icon { color: var(--muted); font-size: 20px; width: 20px; height: 20px; }
    .searchbox input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font: inherit; color: var(--text); }
    .small { font-size: 12px; } .zero { color: var(--muted) !important; } .late { color: var(--danger) !important; }
    .strong { font-weight: 700; color: var(--text) !important; }
  `],
})
export class AgingComponent {
  /** ?side=ar|ap from the URL */
  sideParam = input<string | undefined>(undefined, { alias: 'side' });
  private svc = inject(InsightsService);
  private auth = inject(AuthService);
  private router = inject(Router);
  today = new Date();
  buckets = BUCKETS;
  side = signal<'ar' | 'ap'>('ar');
  data = signal<Aging | null>(null);
  loading = signal(false);
  filter = signal<Bucket | null>(null);
  q = '';
  qSig = signal('');
  canAr = computed(() => this.auth.can('sales.view'));
  canAp = computed(() => this.auth.can('purchasing.view'));

  rows = computed(() => {
    this.qSig();
    const a = this.data();
    if (!a) return [];
    const words = this.q.toLowerCase().split(/\s+/).filter(Boolean);
    const f = this.filter();
    return a.parties.filter((p) => (!f || p[f] > 0) && words.every((w) => (p.name ?? '').toLowerCase().includes(w)));
  });

  constructor() {
    effect(() => {
      const s = this.sideParam() === 'ap' || (!this.canAr() && this.canAp()) ? 'ap' : 'ar';
      this.side.set(s);
      this.load();
    }, { allowSignalWrites: true });
  }

  go(s: 'ar' | 'ap') { this.router.navigate([], { queryParams: { side: s } }); }
  toggle(b: Bucket) { this.filter.set(this.filter() === b ? null : b); }
  rowKey(p: AgingParty) { return p.party_id || p.name || ''; }
  bucketLabel(b: Bucket) { return BUCKETS.find((x) => x.key === b)?.label ?? b; }
  pct(v: number, t: number) { return t ? Math.round((v / t) * 100) : 0; }

  load() {
    this.loading.set(true);
    this.svc.aging(this.side()).subscribe({
      next: (a) => { this.data.set(a); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  open(p: AgingParty) {
    const a = this.data()!;
    if (p.record_id) this.router.navigate(['/qb', a.party_entity, p.record_id]);
    else this.router.navigate(['/qb', a.doc_entity], { queryParams: { q: p.name } });
  }
}
