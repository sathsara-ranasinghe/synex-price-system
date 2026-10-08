import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { BUCKETS, InsightsService, PartyOverview } from '../core/insights.service';
import { MoneyPipe } from './shared';

/** Customer / vendor at a glance: balance, aging, open documents, payments and a 12-month trend. */
@Component({
  selector: 'app-party-overview',
  standalone: true,
  imports: [DatePipe, RouterLink, MatButtonModule, MatIconModule, MatTooltipModule, MoneyPipe],
  template: `
    @if (o(); as o) {
      <div class="stats">
        <div class="st main"><span>{{ isCustomer() ? 'Owes us' : 'We owe' }}</span><strong>{{ o.open_total | money }}</strong>
          <small>{{ o.open_count }} open {{ isCustomer() ? 'invoice' : 'bill' }}{{ o.open_count === 1 ? '' : 's' }}</small></div>
        <div class="st" [class.bad]="o.overdue_total > 0"><span>Overdue</span><strong>{{ o.overdue_total | money }}</strong>
          <small>{{ o.overdue_total > 0 ? 'Past the due date' : 'Nothing late' }}</small></div>
        @if (o.credit_limit) {
          <div class="st" [class.bad]="o.open_total > o.credit_limit"><span>Credit limit</span><strong>{{ o.credit_limit | money }}</strong>
            <small>{{ o.open_total > o.credit_limit ? 'Over the limit' : (o.credit_limit - o.open_total | money) + ' available' }}</small></div>
        }
        <div class="st"><span>{{ isCustomer() ? 'Total sales' : 'Total purchases' }}</span><strong>{{ o.lifetime | money }}</strong>
          <small>Last activity {{ o.last_activity ? (o.last_activity | date: 'mediumDate') : '–' }}</small></div>
        <div class="contact">
          @if (o.email) { <a [href]="'mailto:' + o.email"><mat-icon>mail</mat-icon>{{ o.email }}</a> }
          @if (o.phone) { <a [href]="'tel:' + o.phone"><mat-icon>call</mat-icon>{{ o.phone }}</a> }
          @if (o.terms) { <span><mat-icon>event</mat-icon>{{ o.terms }}</span> }
        </div>
      </div>

      <div class="cols">
        <section class="panel">
          <div class="ph"><h2>Open {{ isCustomer() ? 'invoices' : 'bills' }}</h2>
            @if (canCreatePayment()) {
              <a mat-stroked-button [routerLink]="['/qb', isCustomer() ? 'receive_payment' : 'bill_payment', 'new']"
                 [state]="{ copy: { values: paymentValues(), lines: [] } }"><mat-icon>payments</mat-icon> {{ isCustomer() ? 'Receive payment' : 'Pay bills' }}</a>
            }
          </div>
          <div class="aging">
            @for (b of buckets; track b.key) {
              <div [class]="'ab ' + b.key" [style.flex-grow]="o.buckets[b.key] || 0"
                   [matTooltip]="b.label + ': ' + (o.buckets[b.key] | money)"></div>
            }
          </div>
          <div class="legend">@for (b of buckets; track b.key) { @if (o.buckets[b.key]) {
            <span [class]="b.key"><i></i>{{ b.label }} {{ o.buckets[b.key] | money }}</span> } }</div>
          @if (o.open_docs.length) {
            <table class="simple">
              <tr><th>No.</th><th>Due</th><th class="num">Open</th></tr>
              @for (d of o.open_docs.slice(0, 8); track d.record_id) {
                <tr class="clickable" [routerLink]="['/qb', d.entity, d.record_id]">
                  <td><strong>{{ d.name || '(no number)' }}</strong><div class="muted small">{{ d.txn_date | date: 'mediumDate' }}</div></td>
                  <td>{{ d.due_date | date: 'mediumDate' }}
                    @if (d.days_overdue > 0) { <div class="late small">{{ d.days_overdue }} days late</div> }</td>
                  <td class="num">{{ d.open | money }}</td>
                </tr>
              }
            </table>
            @if (o.open_docs.length > 8) { <p class="muted small">+ {{ o.open_docs.length - 8 }} more in the list below.</p> }
          } @else { <p class="muted">Nothing open.</p> }
        </section>

        <section class="panel">
          <h2>{{ isCustomer() ? 'Sales' : 'Purchases' }} by month</h2>
          <div class="spark">
            @for (v of o.monthly; track $index) {
              <div class="sb" [matTooltip]="(o.months[$index] | date: 'MMM y') + ': ' + (v | money)">
                <i [style.height.%]="max() ? (v / max()) * 100 : 0"></i><small>{{ o.months[$index] | date: 'MMMMM' }}</small></div>
            }
          </div>
          <h2 class="gap">Latest payments</h2>
          @for (p of o.payments.slice(0, 5); track p.record_id) {
            <a class="pay" [routerLink]="['/qb', p.entity, p.record_id]">
              <span><strong>{{ p.label }} {{ p.name }}</strong><small class="muted">{{ p.txn_date | date: 'mediumDate' }}</small></span>
              <span class="num">{{ p.amount | money }}</span></a>
          } @empty { <p class="muted">No payments yet.</p> }
        </section>
      </div>
    }
  `,
  styles: [`
    :host { display: block; margin-bottom: 16px; }
    .stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; margin-bottom: 14px; }
    .st { display: flex; flex-direction: column; gap: 2px; padding: 14px 16px; background: var(--surface); border: 1px solid var(--line);
      border-radius: var(--radius); }
    .st span { font-size: 12px; color: var(--muted); font-weight: 500; } .st strong { font-size: 20px; font-variant-numeric: tabular-nums; }
    .st small { font-size: 12px; color: var(--muted); }
    .st.main { background: linear-gradient(135deg, #0a5c80, #0b2e4f); border: 0; } .st.main * { color: #fff !important; }
    .st.main span, .st.main small { opacity: .8; }
    .st.bad strong, .st.bad small { color: var(--danger); }
    .contact { display: flex; flex-direction: column; justify-content: center; gap: 6px; font-size: 13px; }
    .contact a, .contact span { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; }
    .contact mat-icon { font-size: 17px; width: 17px; height: 17px; color: var(--muted); }
    .cols { display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; }
    @media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }
    .ph { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; } .ph h2 { margin: 0; }
    .aging { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--surface-2); gap: 2px; margin-bottom: 8px; }
    .ab { flex-basis: 0; height: 100%; background: var(--c); }
    .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; color: var(--muted); margin-bottom: 10px; }
    .legend span { display: inline-flex; align-items: center; gap: 5px; } .legend i { width: 8px; height: 8px; border-radius: 2px; background: var(--c); }
    .current { --c: #16a34a; } .d1_30 { --c: #eab308; } .d31_60 { --c: #f97316; } .d61_90 { --c: #ef4444; } .d90_plus { --c: #b91c1c; }
    .late { color: var(--danger); } .small { font-size: 12px; } .gap { margin-top: 18px; }
    .spark { display: flex; align-items: flex-end; gap: 4px; height: 110px; }
    .sb { flex: 1; height: 100%; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; gap: 4px; }
    .sb i { width: 100%; max-width: 22px; min-height: 2px; border-radius: 4px 4px 1px 1px; background: linear-gradient(180deg, #60a5fa, #2563eb); }
    .sb small { font-size: 10px; color: var(--muted); }
    .pay { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-top: 1px solid var(--line); color: inherit; }
    .pay span:first-child { display: flex; flex-direction: column; } .pay strong { font-size: 13px; font-weight: 550; } .pay small { font-size: 12px; }
  `],
})
export class PartyOverviewComponent {
  entity = input.required<string>();
  recordId = input.required<number>();
  listId = input<string | null>(null);
  name = input<string | null>(null);
  canCreatePayment = input(false);
  private svc = inject(InsightsService);
  o = signal<PartyOverview | null>(null);
  buckets = BUCKETS;
  isCustomer = computed(() => this.entity() === 'customer');
  max = computed(() => Math.max(0, ...(this.o()?.monthly ?? [])));

  constructor() {
    effect(() => {
      const e = this.entity(), id = this.recordId();
      this.o.set(null);
      this.svc.party(e, id).subscribe({ next: (o) => this.o.set(o), error: () => this.o.set(null) });
    }, { allowSignalWrites: true });
  }

  paymentValues() {
    const ref = { ListID: this.listId(), FullName: this.name() };
    return this.isCustomer() ? { CustomerRef: ref } : { PayeeEntityRef: ref };
  }
}
