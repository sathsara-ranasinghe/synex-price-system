import { DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router, RouterLink } from '@angular/router';
import { InsightsService, StockItem } from '../core/insights.service';
import { PortalService } from '../core/portal.service';
import { MoneyPipe } from '../shared/shared';

/** Inventory at or below its reorder point, with one click to a purchase order. */
@Component({
  selector: 'app-stock-alerts',
  standalone: true,
  imports: [DecimalPipe, FormsModule, RouterLink, MatButtonModule, MatCheckboxModule, MatIconModule, MatProgressBarModule, MoneyPipe],
  template: `
    <div class="head">
      <div><h1>Items to reorder</h1>
        <div class="sub">Active inventory items at or below the reorder point set in QuickBooks.</div></div>
      <span class="spacer"></span>
      @if (canPo()) {
        <button mat-flat-button color="primary" [disabled]="!picked().length" (click)="createPo()">
          <mat-icon>add_shopping_cart</mat-icon> Create purchase order{{ picked().length ? ' (' + picked().length + ')' : '' }}</button>
      }
    </div>

    @if (loading()) { <mat-progress-bar mode="indeterminate" /> }
    @if (!loading()) {
      <div class="cards">
        <div class="card bad"><mat-icon>error_outline</mat-icon><div><strong>{{ uncovered() }}</strong><span>need ordering</span></div></div>
        <div class="card ok"><mat-icon>local_shipping</mat-icon><div><strong>{{ items().length - uncovered() }}</strong><span>already on order</span></div></div>
        <div class="card"><mat-icon>payments</mat-icon><div><strong>{{ orderValue() | money }}</strong><span>to buy the suggested quantities</span></div></div>
      </div>

      <section class="panel flush">
        <div class="scroll">
          <table class="simple">
            <thead><tr>
              @if (canPo()) { <th class="ck"><mat-checkbox [checked]="allPicked()" [indeterminate]="picked().length > 0 && !allPicked()"
                (change)="pickAll($event.checked)" aria-label="Select all" /></th> }
              <th>Item</th><th>Preferred vendor</th><th class="num">On hand</th><th class="num">Reorder at</th>
              <th class="num">On order</th><th class="num">Order qty</th><th class="num">Cost</th><th>Status</th>
            </tr></thead>
            <tbody>
              @for (it of items(); track it.record_id) {
                <tr [class.sel]="sel().has(it.record_id)">
                  @if (canPo()) { <td class="ck"><mat-checkbox [checked]="sel().has(it.record_id)" (change)="pick(it, $event.checked)"
                    [attr.aria-label]="'Select ' + it.name" /></td> }
                  <td><a [routerLink]="['/qb', it.entity, it.record_id]"><strong>{{ it.name }}</strong></a>
                    @if (it.desc) { <div class="muted small">{{ it.desc }}</div> }</td>
                  <td>{{ it.vendor?.FullName || '–' }}</td>
                  <td class="num" [class.neg]="it.qoh <= 0">{{ it.qoh | number: '1.0-2' }}</td>
                  <td class="num">{{ it.reorder_point | number: '1.0-2' }}</td>
                  <td class="num">{{ it.on_order ? (it.on_order | number: '1.0-2') : '–' }}</td>
                  <td class="num"><input class="qty" type="number" min="1" [(ngModel)]="qty[it.record_id]" (ngModelChange)="tick.set(tick() + 1)"
                    [attr.aria-label]="'Order quantity for ' + it.name" /></td>
                  <td class="num">{{ it.cost | money }}</td>
                  <td>@if (it.covered) { <span class="tag ok">On order</span> } @else if (it.qoh <= 0) { <span class="tag bad">Out of stock</span> }
                      @else { <span class="tag warn">Low</span> }</td>
                </tr>
              } @empty {
                <tr><td colspan="9"><div class="empty"><mat-icon>inventory</mat-icon>
                  <div>Nothing to reorder. Items appear here when stock falls to the reorder point set in QuickBooks.</div></div></td></tr>
              }
            </tbody>
          </table>
        </div>
      </section>
      @if (canPo()) { <p class="muted small">Tick items from the same vendor and press Create purchase order. The order opens as a draft for you to check before saving.</p> }
    }
  `,
  styles: [`
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-bottom: 14px; }
    .card { display: flex; align-items: center; gap: 12px; padding: 14px 16px; background: var(--surface); border: 1px solid var(--line);
      border-radius: var(--radius); }
    .card mat-icon { color: var(--primary); } .card.bad mat-icon { color: var(--danger); } .card.ok mat-icon { color: var(--ok); }
    .card div { display: flex; flex-direction: column; } .card strong { font-size: 20px; font-variant-numeric: tabular-nums; }
    .card span { font-size: 12.5px; color: var(--muted); }
    .ck { width: 44px; } .small { font-size: 12px; } .neg { color: var(--danger) !important; font-weight: 600; }
    tr.sel td { background: var(--primary-soft); }
    .qty { width: 80px; height: 32px; padding: 0 8px; text-align: right; border: 1px solid var(--line-strong); border-radius: 8px;
      background: var(--surface); color: var(--text); font: inherit; }
  `],
})
export class StockAlertsComponent implements OnInit {
  private svc = inject(InsightsService);
  private portal = inject(PortalService);
  private router = inject(Router);
  private snack = inject(MatSnackBar);
  items = signal<StockItem[]>([]);
  loading = signal(true);
  sel = signal<Set<number>>(new Set());
  tick = signal(0);
  qty: Record<number, number> = {};

  canPo = computed(() => !!this.portal.meta()?.entities.find((e) => e.key === 'purchase_order')?.permissions.create);
  uncovered = computed(() => this.items().filter((i) => !i.covered).length);
  picked = computed(() => this.items().filter((i) => this.sel().has(i.record_id)));
  allPicked = computed(() => this.items().length > 0 && this.picked().length === this.items().length);
  orderValue = computed(() => {
    this.tick();
    return this.items().filter((i) => !i.covered).reduce((t, i) => t + (Number(this.qty[i.record_id]) || 0) * i.cost, 0);
  });

  ngOnInit() {
    this.portal.load();
    this.svc.stock().subscribe({
      next: (r) => {
        for (const i of r.items) this.qty[i.record_id] = i.suggested;
        this.items.set(r.items);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  pick(it: StockItem, on: boolean) {
    const s = new Set(this.sel());
    if (on) s.add(it.record_id); else s.delete(it.record_id);
    this.sel.set(s);
  }
  pickAll(on: boolean) { this.sel.set(on ? new Set(this.items().map((i) => i.record_id)) : new Set()); }

  createPo() {
    const items = this.picked();
    const vendors = [...new Set(items.map((i) => i.vendor?.ListID).filter(Boolean))];
    if (vendors.length > 1) {
      this.snack.open('These items have different preferred vendors. Tick items of one vendor at a time.', 'OK', { duration: 6000 });
      return;
    }
    const vendor = items.find((i) => i.vendor)?.vendor ?? null;
    const lines = items.map((i) => ({ type: 'item', values: {
      ItemRef: { ListID: i.qb_id, FullName: i.name }, Desc: i.desc ?? undefined,
      Quantity: Number(this.qty[i.record_id]) || i.suggested, Rate: i.cost || undefined } }));
    this.router.navigate(['/qb', 'purchase_order', 'new'], { state: { copy: {
      values: { ...(vendor ? { VendorRef: vendor } : {}), Memo: 'Reorder - low stock' }, lines } } });
  }
}
