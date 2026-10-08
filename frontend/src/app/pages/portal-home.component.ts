import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { AuthService } from '../core/auth';
import { CompanyService } from '../core/company.service';
import { QbRecord } from '../core/models';
import { Insights, PortalService } from '../core/portal.service';
import { UiService } from '../core/ui.service';
import { MoneyPipe } from '../shared/shared';

const MODULE_STYLE: Record<string, { icon: string; hue: string }> = {
  sales: { icon: 'point_of_sale', hue: '#2563eb' },
  purchasing: { icon: 'shopping_cart', hue: '#0891b2' },
  banking: { icon: 'account_balance', hue: '#059669' },
  accounting: { icon: 'calculate', hue: '#7c3aed' },
  inventory: { icon: 'inventory_2', hue: '#d97706' },
  lists: { icon: 'category', hue: '#db2777' },
};

/** Short money for chart axes: 1.2M, 850K. */
function short(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return v.toFixed(0);
}

@Component({
  selector: 'app-portal-home',
  standalone: true,
  imports: [DatePipe, DecimalPipe, RouterLink, MatIconModule, MatTooltipModule, MoneyPipe],
  template: `
    <section class="hero">
      <div class="hero-txt">
        <div class="date">{{ today | date: 'EEEE, d MMMM y' }} · {{ companies.current()?.name }}</div>
        <h1>{{ greeting() }}{{ firstName() ? ', ' + firstName() : '' }}</h1>
        <p>What would you like to find?</p>
      </div>
      <button class="ask" (click)="ui.paletteOpen.set(true)">
        <mat-icon>search</mat-icon><span>Search customers, invoices, items…</span><kbd>Ctrl</kbd><kbd>K</kbd>
      </button>
      @if (quick().length) {
        <div class="quick">
          @for (q of quick(); track q.key) {
            <a [routerLink]="['/qb', q.key, 'new']"><mat-icon>add</mat-icon>{{ q.label }}</a>
          }
        </div>
      }
    </section>

    <!-- KPIs -->
    <div class="kpis">
      @if (d(); as d) {
        @if (d.open_ar !== null) {
          <a class="kpi" routerLink="/qb/invoice">
            <span class="ic" style="--h:#2563eb"><mat-icon>call_received</mat-icon></span>
            <span class="lbl">Open receivables</span><strong>{{ d.open_ar | money }}</strong>
            <span class="hint">Customers still owe you</span>
          </a>
        }
        @if (d.open_ap !== null) {
          <a class="kpi" routerLink="/qb/bill">
            <span class="ic" style="--h:#0891b2"><mat-icon>call_made</mat-icon></span>
            <span class="lbl">Open payables</span><strong>{{ d.open_ap | money }}</strong>
            <span class="hint">You still owe vendors</span>
          </a>
        }
        @if (salesThisMonth(); as s) {
          <div class="kpi">
            <span class="ic" style="--h:#059669"><mat-icon>trending_up</mat-icon></span>
            <span class="lbl">Sales · {{ s.month | date: 'MMMM y' }}</span><strong>{{ s.value | money }}</strong>
            <span class="hint" [class.good]="s.change !== null && s.change >= 0" [class.badc]="s.change !== null && s.change < 0">
              @if (s.change !== null) {
                <mat-icon>{{ s.change >= 0 ? 'arrow_upward' : 'arrow_downward' }}</mat-icon>{{ s.change | number: '1.0-0' }}% vs previous month
              } @else { {{ s.value ? 'No sales the month before' : 'No sales yet' }} }
            </span>
          </div>
        }
        <a class="kpi" routerLink="/qb-changes" [class.attn]="d.pending_changes > 0">
          <span class="ic" style="--h:#d97706"><mat-icon>pending_actions</mat-icon></span>
          <span class="lbl">Awaiting approval</span><strong>{{ d.pending_changes }}</strong>
          <span class="hint">{{ d.pending_changes ? 'Changes waiting for QuickBooks' : 'Nothing waiting' }}</span>
        </a>
      } @else {
        @for (i of [1, 2, 3, 4]; track i) { <div class="kpi sk"><span></span><span></span></div> }
      }
    </div>

    <div class="grid2">
      <!-- chart -->
      @if (chart(); as c) {
        <section class="panel chart">
          <div class="ph">
            <h2>Sales &amp; purchases</h2>
            <div class="legend">
              @if (c.hasSales) { <span><i class="s"></i>Sales</span> }
              @if (c.hasBuy) { <span><i class="p"></i>Purchases</span> }
            </div>
            <span class="spacer"></span>
            <div class="seg">
              @for (m of [6, 12]; track m) { <button [class.on]="months() === m" (click)="setMonths(m)">{{ m }} months</button> }
            </div>
          </div>
          @if (!c.empty) {
          <div class="plot">
            <div class="yaxis">@for (t of c.ticks; track $index) { <span>{{ t }}</span> }</div>
            <div class="cols">
              @for (b of c.bars; track b.month) {
                <div class="col" [matTooltip]="b.tip" matTooltipClass="multiline">
                  <div class="pair">
                    @if (c.hasSales) { <span class="bar s" [style.height.%]="b.s"></span> }
                    @if (c.hasBuy) { <span class="bar p" [style.height.%]="b.p"></span> }
                  </div>
                  <small>{{ b.month | date: (months() > 6 ? 'MMM' : 'MMM yy') }}</small>
                </div>
              }
            </div>
          </div>
          } @else {
            <div class="empty"><mat-icon>bar_chart</mat-icon><div>No sales or purchases in the last {{ months() }} months.</div></div>
          }
        </section>
      }

      <!-- top lists -->
      <section class="panel tops">
        @if (ins(); as i) {
          @if (i.top_customers.length) {
            <h2>Top customers <small class="muted">· {{ months() }} months</small></h2>
            @for (t of i.top_customers; track t.name) {
              <div class="top"><span class="nm">{{ t.name }}</span><span class="amt">{{ t.amount | money }}</span>
                <span class="meter"><i [style.width.%]="(t.amount / i.top_customers[0].amount) * 100"></i></span></div>
            }
          }
          @if (i.top_vendors.length) {
            <h2 [class.gap]="i.top_customers.length">Top vendors <small class="muted">· {{ months() }} months</small></h2>
            @for (t of i.top_vendors; track t.name) {
              <div class="top"><span class="nm">{{ t.name }}</span><span class="amt">{{ t.amount | money }}</span>
                <span class="meter v"><i [style.width.%]="(t.amount / i.top_vendors[0].amount) * 100"></i></span></div>
            }
          }
          @if (!i.top_customers.length && !i.top_vendors.length) {
            <div class="empty"><mat-icon>leaderboard</mat-icon><div>Top customers and vendors appear here once there are sales or bills.</div></div>
          }
        }
      </section>
    </div>

    <!-- recently opened -->
    @if (ui.recent().length) {
      <div class="sh"><h2 class="section">Pick up where you left off</h2>
        <button class="link" (click)="ui.clearRecent()">Clear</button></div>
      <div class="recent">
        @for (r of ui.recent().slice(0, 8); track r.entity + r.record_id) {
          <a class="rc" [routerLink]="['/qb', r.entity, r.record_id]">
            <span class="ic sm" style="--h:#6366f1"><mat-icon>history</mat-icon></span>
            <span class="t"><strong>{{ r.name || '(no number)' }}</strong><small>{{ r.label }}@if (r.party_name && r.party_name !== r.name) { · {{ r.party_name }} }</small></span>
          </a>
        }
      </div>
    }

    <h2 class="section">Workspaces</h2>
    <div class="modules">
      @for (m of modules(); track m.key) {
        <div class="module">
          <div class="mhead">
            <span class="ic" [style.--h]="m.hue"><mat-icon>{{ m.icon }}</mat-icon></span>
            <strong>{{ m.label }}</strong>
          </div>
          <div class="links">
            @for (e of m.entities; track e.key) {
              <a [routerLink]="['/qb', e.key]"><span>{{ e.plural }}</span><em>{{ (d()?.counts?.[e.key] ?? 0) | number }}</em></a>
            }
          </div>
        </div>
      }
    </div>

    <h2 class="section">Latest changes in QuickBooks</h2>
    <section class="panel flush">
      @if (d()?.recent?.length) {
        <div class="scroll">
          <table class="simple">
            <tr><th>Type</th><th>No.</th><th>Name</th><th>Date</th><th class="num">Amount</th></tr>
            @for (r of d()!.recent; track r.record_id) {
              <tr class="clickable" [routerLink]="['/qb', r.entity, r.record_id]">
                <td><span class="tag">{{ r.label }}</span></td><td><strong>{{ r.name }}</strong></td><td>{{ r.party_name }}</td>
                <td>{{ r.txn_date | date: 'mediumDate' }}</td><td class="num">{{ r.amount | money }}</td>
              </tr>
            }
          </table>
        </div>
      } @else {
        <div class="empty"><mat-icon>inbox</mat-icon><div>No transactions yet. They appear after the next QuickBooks sync.</div></div>
      }
    </section>
  `,
  styles: [`
    .hero { position: relative; overflow: hidden; padding: 26px 28px; margin-bottom: 18px; border-radius: 18px; color: #fff;
      background: radial-gradient(120% 140% at 100% 0%, #3b82f6 0%, transparent 55%),
                  linear-gradient(135deg, #0a5c80 0%, #0b2e4f 100%); box-shadow: var(--shadow); }
    .hero::after { content: ''; position: absolute; right: -80px; top: -80px; width: 260px; height: 260px; border-radius: 50%;
      border: 40px solid rgba(255, 255, 255, .06); pointer-events: none; }
    .date { font-size: 12.5px; font-weight: 500; opacity: .8; }
    .hero h1 { color: #fff; font-size: 28px; margin: 4px 0 2px; }
    .hero p { margin: 0 0 16px; opacity: .85; }
    .ask { position: relative; z-index: 1; display: flex; align-items: center; gap: 10px; width: 100%; max-width: 560px; height: 48px;
      padding: 0 12px 0 16px; border: 0; border-radius: 12px; background: #fff; color: #5f7584; font: inherit; font-size: 15px;
      cursor: text; box-shadow: 0 8px 24px rgba(0, 0, 0, .18); }
    .ask span { flex: 1; text-align: left; }
    .ask kbd { font: 11px/1 Inter, system-ui, sans-serif; padding: 3px 6px; border-radius: 5px; border: 1px solid #d6e0e7;
      border-bottom-width: 2px; color: #5f7584; background: #f6f8fa; }
    .quick { position: relative; z-index: 1; display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    .quick a { display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px 6px 8px; border-radius: 999px; font-size: 13px;
      font-weight: 500; color: #fff; background: rgba(255, 255, 255, .12); border: 1px solid rgba(255, 255, 255, .18);
      transition: background .15s; }
    .quick a:hover { background: rgba(255, 255, 255, .22); color: #fff; }
    .quick mat-icon { font-size: 17px; width: 17px; height: 17px; }

    .section { font-size: 12.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 28px 0 12px; }
    .sh { display: flex; align-items: baseline; justify-content: space-between; }
    .link { border: 0; background: none; color: var(--muted); font: inherit; font-size: 12.5px; cursor: pointer; }
    .link:hover { color: var(--primary); }
    .ic { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; flex: none;
      background: color-mix(in srgb, var(--h) 12%, transparent); color: var(--h); }
    .ic mat-icon { font-size: 20px; width: 20px; height: 20px; }
    .ic.sm { width: 30px; height: 30px; border-radius: 8px; } .ic.sm mat-icon { font-size: 17px; width: 17px; height: 17px; }

    .kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
    .kpi { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto auto auto; column-gap: 14px; row-gap: 2px;
      padding: 18px 20px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
      color: inherit; box-shadow: var(--shadow-sm); transition: box-shadow .15s, transform .15s, border-color .15s; }
    a.kpi:hover { box-shadow: var(--shadow); transform: translateY(-1px); border-color: var(--line-strong); }
    .kpi .ic { grid-row: 1 / 4; }
    .kpi .lbl { color: var(--muted); font-size: 12.5px; font-weight: 500; }
    .kpi strong { font-size: 23px; font-weight: 700; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; color: var(--text); }
    .kpi .hint { display: flex; align-items: center; gap: 2px; color: var(--muted); font-size: 12px; }
    .kpi .hint mat-icon { font-size: 14px; width: 14px; height: 14px; }
    .kpi .hint.good { color: var(--ok); } .kpi .hint.badc { color: var(--danger); }
    .kpi.attn strong { color: var(--warn); }
    .kpi.sk { height: 92px; display: flex; flex-direction: column; justify-content: center; gap: 10px; }
    .kpi.sk span { height: 12px; border-radius: 6px; width: 60%;
      background: linear-gradient(90deg, var(--surface-2), var(--line), var(--surface-2)); background-size: 200% 100%; animation: shimmer 1.2s infinite; }
    .kpi.sk span + span { width: 40%; height: 20px; }
    @keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }

    .grid2 { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(280px, 1fr); gap: 14px; margin-top: 14px; }
    @media (max-width: 1100px) { .grid2 { grid-template-columns: 1fr; } }
    .ph { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 12px; } .ph h2 { margin: 0; }
    .legend { display: flex; gap: 12px; font-size: 12.5px; color: var(--muted); }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .legend i { width: 10px; height: 10px; border-radius: 3px; }
    i.s, .bar.s { background: linear-gradient(180deg, #3b82f6, #2563eb); }
    i.p, .bar.p { background: linear-gradient(180deg, #67e8f9, #0891b2); }
    .seg { display: inline-flex; padding: 3px; gap: 2px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 9px; }
    .seg button { border: 0; background: none; font: inherit; font-size: 12.5px; color: var(--text-2); padding: 4px 10px; border-radius: 6px; cursor: pointer; }
    .seg button.on { background: var(--surface); color: var(--primary); font-weight: 600; box-shadow: 0 1px 2px rgba(15, 23, 42, .1); }
    .plot { display: flex; gap: 8px; height: 230px; }
    .yaxis { display: flex; flex-direction: column-reverse; justify-content: space-between; padding-bottom: 22px; font-size: 11px;
      color: var(--muted); text-align: right; min-width: 38px; font-variant-numeric: tabular-nums; }
    .cols { flex: 1; display: flex; gap: 6px; align-items: stretch; border-left: 1px solid var(--line);
      background: repeating-linear-gradient(to top, transparent 0, transparent calc(25% - 1px), var(--line) calc(25% - 1px), var(--line) 25%);
      background-size: 100% calc(100% - 22px); background-repeat: no-repeat; }
    .col { flex: 1; display: flex; flex-direction: column; align-items: center; min-width: 0; border-radius: 8px; cursor: default; }
    .col:hover { background: color-mix(in srgb, var(--primary-soft) 60%, transparent); }
    .pair { flex: 1; width: 100%; display: flex; justify-content: center; align-items: flex-end; gap: 3px; padding: 0 12%; }
    .bar { flex: 1; max-width: 22px; min-height: 2px; border-radius: 5px 5px 2px 2px; transition: height .4s cubic-bezier(.2, .8, .2, 1); }
    .col small { height: 22px; line-height: 22px; font-size: 11px; color: var(--muted); white-space: nowrap; }
    .center { text-align: center; margin-top: 6px; } .small { font-size: 12.5px; }

    .tops h2 { display: flex; align-items: baseline; gap: 4px; } .tops h2 small { font-weight: 500; font-size: 12px; }
    .tops h2.gap { margin-top: 20px; }
    .top { display: grid; grid-template-columns: 1fr auto; row-gap: 4px; padding: 6px 0; font-size: 13px; }
    .top .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-2); }
    .top .amt { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--text); }
    .meter { grid-column: 1 / -1; height: 5px; border-radius: 3px; background: var(--surface-2); overflow: hidden; }
    .meter i { display: block; height: 100%; border-radius: 3px; background: linear-gradient(90deg, #93c5fd, #2563eb); }
    .meter.v i { background: linear-gradient(90deg, #a5f3fc, #0891b2); }

    .recent { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
    .rc { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--surface); border: 1px solid var(--line);
      border-radius: 10px; color: inherit; transition: border-color .15s, box-shadow .15s; }
    .rc:hover { border-color: color-mix(in srgb, var(--primary) 35%, var(--line)); box-shadow: var(--shadow); }
    .rc .t { display: flex; flex-direction: column; min-width: 0; line-height: 1.3; }
    .rc strong { font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
    .rc small { font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .modules { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
    .module { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px;
      box-shadow: var(--shadow-sm); }
    .mhead { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; } .mhead strong { font-size: 14.5px; }
    .links { display: flex; flex-direction: column; }
    .links a { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; margin: 0 -8px; border-radius: 6px;
      color: var(--text-2); font-size: 13.5px; }
    .links a:hover { background: var(--primary-soft); color: var(--primary); }
    .links em { font-style: normal; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums;
      background: var(--surface-2); border: 1px solid var(--line); padding: 1px 8px; border-radius: 999px; }
    @media (max-width: 600px) {
      .kpis { grid-template-columns: 1fr 1fr; gap: 10px; }
      .kpi { grid-template-columns: 1fr; padding: 14px; } .kpi .ic { grid-row: auto; width: 30px; height: 30px; margin-bottom: 6px; }
      .kpi strong { font-size: 19px; } .kpi .hint { display: none; }
      .hero { padding: 20px 18px; } .hero h1 { font-size: 23px; } .ask kbd { display: none; } }
    @media (prefers-reduced-motion: reduce) { .bar, .kpi.sk span { transition: none; animation: none; } }
  `],
})
export class PortalHomeComponent implements OnInit {
  auth = inject(AuthService);
  ui = inject(UiService);
  companies = inject(CompanyService);
  private portal = inject(PortalService);
  today = new Date();
  months = signal(6);
  ins = signal<Insights | null>(null);
  d = signal<{ counts: Record<string, number>; open_ar: number | null; open_ap: number | null; pending_changes: number;
    recent: QbRecord[] } | null>(null);

  firstName = computed(() => (this.auth.me()?.full_name || '').split(' ')[0]);
  greeting = computed(() => {
    const h = new Date().getHours();
    return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  });

  modules = computed(() => {
    const meta = this.portal.meta();
    if (!meta) return [];
    return meta.modules
      .map((m) => ({ ...m, ...(MODULE_STYLE[m.key] ?? { icon: 'folder', hue: '#64748b' }),
        entities: meta.entities.filter((e) => e.module === m.key) }))
      .filter((m) => m.entities.length);
  });

  /** One-click "New …" buttons for the documents people make most. */
  quick = computed(() => {
    const ents = this.portal.meta()?.entities ?? [];
    return ['invoice', 'sales_receipt', 'estimate', 'customer', 'bill', 'purchase_order']
      .map((k) => ents.find((e) => e.key === k))
      .filter((e) => !!e && e.can_add && e.permissions.create)
      .slice(0, 5)
      .map((e) => ({ key: e!.key, label: e!.label }));
  });

  salesThisMonth = computed(() => {
    const i = this.ins();
    if (!i?.sales?.length) return null;
    const n = i.sales.length;
    const value = i.sales[n - 1], prev = n > 1 ? i.sales[n - 2] : 0;
    return { month: i.months[n - 1], value, change: prev ? ((value - prev) / prev) * 100 : null };
  });

  chart = computed(() => {
    const i = this.ins();
    if (!i || (!i.sales && !i.purchases)) return null;
    const s = i.sales ?? [], p = i.purchases ?? [];
    const max = Math.max(1, ...s, ...p);
    const step = this.niceStep(max / 4);
    const top = step * 4;
    const money = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
    return {
      hasSales: !!i.sales, hasBuy: !!i.purchases, empty: max <= 1,
      ticks: [0, 1, 2, 3, 4].map((k) => short(k * step)),
      bars: i.months.map((m, k) => ({
        month: m,
        s: ((s[k] ?? 0) / top) * 100,
        p: ((p[k] ?? 0) / top) * 100,
        tip: [i.sales ? `Sales: ${money.format(s[k])}` : '', i.purchases ? `Purchases: ${money.format(p[k])}` : '']
          .filter(Boolean).join(' · '),
      })),
    };
  });

  private niceStep(raw: number) {
    const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
    const f = raw / mag;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
  }

  ngOnInit() {
    this.portal.load();
    this.portal.dashboard().subscribe((d) => this.d.set(d));
    this.loadInsights();
  }

  setMonths(m: number) { this.months.set(m); this.loadInsights(); }
  private loadInsights() { this.portal.insights(this.months()).subscribe((i) => this.ins.set(i)); }
}
