import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';
import { AuthService } from '../core/auth';
import { QbRecord } from '../core/models';
import { PortalService } from '../core/portal.service';
import { MoneyPipe } from '../shared/shared';

const MODULE_STYLE: Record<string, { icon: string; hue: string }> = {
  sales: { icon: 'point_of_sale', hue: '#2563eb' },
  purchasing: { icon: 'shopping_cart', hue: '#0891b2' },
  banking: { icon: 'account_balance', hue: '#059669' },
  accounting: { icon: 'calculate', hue: '#7c3aed' },
  inventory: { icon: 'inventory_2', hue: '#d97706' },
  lists: { icon: 'category', hue: '#db2777' },
};

@Component({
  selector: 'app-portal-home',
  standalone: true,
  imports: [DatePipe, DecimalPipe, RouterLink, MatIconModule, MoneyPipe],
  template: `
    <div class="hello">
      <div>
        <div class="date">{{ today | date: 'EEEE, d MMMM y' }}</div>
        <h1>{{ greeting() }}{{ firstName() ? ', ' + firstName() : '' }}</h1>
      </div>
    </div>

    @if (d(); as d) {
      <div class="kpis">
        @if (d.open_ar !== null) {
          <a class="kpi" routerLink="/qb/invoice">
            <span class="ic" style="--h:#2563eb"><mat-icon>call_received</mat-icon></span>
            <span class="lbl">Open receivables</span><strong>{{ d.open_ar | money }}</strong>
            <span class="hint">Unpaid invoices</span>
          </a>
        }
        @if (d.open_ap !== null) {
          <a class="kpi" routerLink="/qb/bill">
            <span class="ic" style="--h:#0891b2"><mat-icon>call_made</mat-icon></span>
            <span class="lbl">Open payables</span><strong>{{ d.open_ap | money }}</strong>
            <span class="hint">Unpaid bills</span>
          </a>
        }
        <a class="kpi" routerLink="/qb-changes" [class.attn]="d.pending_changes > 0">
          <span class="ic" style="--h:#d97706"><mat-icon>pending_actions</mat-icon></span>
          <span class="lbl">Awaiting approval</span><strong>{{ d.pending_changes }}</strong>
          <span class="hint">Changes for QuickBooks</span>
        </a>
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

    <h2 class="section">Recent activity in QuickBooks</h2>
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
    .hello { margin-bottom: 22px; } .hello h1 { font-size: 26px; margin: 2px 0 0; }
    .date { color: var(--muted); font-size: 13px; font-weight: 500; }
    .section { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 28px 0 12px; }

    .ic { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; flex: none;
      background: color-mix(in srgb, var(--h) 12%, transparent); color: var(--h); }
    .ic mat-icon { font-size: 20px; width: 20px; height: 20px; }

    .kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
    .kpi { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto auto auto; column-gap: 14px; row-gap: 2px;
      padding: 18px 20px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
      color: inherit; box-shadow: var(--shadow-sm); transition: box-shadow .15s, transform .15s, border-color .15s; }
    .kpi:hover { box-shadow: var(--shadow); transform: translateY(-1px); border-color: var(--line-strong); }
    .kpi .ic { grid-row: 1 / 4; }
    .kpi .lbl { color: var(--muted); font-size: 12.5px; font-weight: 500; }
    .kpi strong { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; color: var(--text); }
    .kpi .hint { color: var(--muted); font-size: 12px; }
    .kpi.attn strong { color: var(--warn); }

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
    .module.feature { grid-column: 1 / -1; display: flex; align-items: center; gap: 14px; color: inherit;
      background: linear-gradient(120deg, color-mix(in srgb, #8b5cf6 10%, var(--surface)), var(--surface) 60%);
      transition: box-shadow .15s, transform .15s; }
    .module.feature:hover { box-shadow: var(--shadow); transform: translateY(-1px); }
    .feature .txt { flex: 1; display: flex; flex-direction: column; } .feature .txt span { color: var(--muted); font-size: 13px; }
    .feature .go { color: var(--muted); }
  `],
})
export class PortalHomeComponent implements OnInit {
  auth = inject(AuthService);
  private portal = inject(PortalService);
  today = new Date();
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

  ngOnInit() {
    this.portal.load();
    this.portal.dashboard().subscribe((d) => this.d.set(d));
  }
}
