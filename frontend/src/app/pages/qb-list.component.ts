import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, HostListener, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink } from '@angular/router';
import { Subject, debounceTime } from 'rxjs';
import { EntityMeta, FieldMeta, QbRecord } from '../core/models';
import { ApiService } from '../core/api.service';
import { errorText } from '../core/auth';
import { InsightsService, SavedView } from '../core/insights.service';
import { PortalService, openBlob } from '../core/portal.service';
import { HumanizePipe, MoneyPipe } from '../shared/shared';

// shown in fixed columns already
const FIXED = ['Name', 'RefNumber', 'TxnDate', 'CustomerRef', 'VendorRef', 'PayeeEntityRef'];

type SortKey = 'name' | 'txn_date' | 'party_name' | 'amount';
interface Preset { key: string; label: string; range: () => [Date, Date] }

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const PRESETS: Preset[] = [
  { key: 'month', label: 'This month', range: () => { const n = new Date(); return [new Date(n.getFullYear(), n.getMonth(), 1), n]; } },
  { key: 'last', label: 'Last month', range: () => { const n = new Date();
    return [new Date(n.getFullYear(), n.getMonth() - 1, 1), new Date(n.getFullYear(), n.getMonth(), 0)]; } },
  { key: 'quarter', label: 'Last 3 months', range: () => { const n = new Date(); return [new Date(n.getFullYear(), n.getMonth() - 2, 1), n]; } },
  { key: 'year', label: 'This year', range: () => { const n = new Date(); return [new Date(n.getFullYear(), 0, 1), n]; } },
];

@Component({
  selector: 'app-qb-list',
  standalone: true,
  imports: [DatePipe, DecimalPipe, FormsModule, RouterLink, MatButtonModule, MatCheckboxModule, MatMenuModule, MatFormFieldModule, MatIconModule, MatInputModule,
    MatPaginatorModule, MatProgressBarModule, MatSelectModule, MatTooltipModule, MoneyPipe, HumanizePipe],
  template: `
    @if (ent(); as e) {
      <div class="head">
        <div>
          <div class="crumb">{{ moduleLabel() }}</div>
          <h1>{{ e.plural }} <span class="count">{{ total() | number }}</span></h1>
        </div>
        <span class="spacer"></span>
        <button mat-stroked-button [matMenuTriggerFor]="viewMenu"><mat-icon>bookmarks</mat-icon> Views</button>
        <button mat-stroked-button [matMenuTriggerFor]="colMenu"><mat-icon>view_column</mat-icon> Columns</button>
        <button mat-stroked-button (click)="exportExcel()" matTooltip="Download what you see as an Excel file">
          <mat-icon>table_view</mat-icon> Excel</button>
        @if (e.can_add && e.permissions.create) {
          <a mat-stroked-button [routerLink]="['/qb', e.key, 'import']"><mat-icon>upload_file</mat-icon> Import</a>
          <a mat-flat-button color="primary" [routerLink]="['/qb', e.key, 'new']"><mat-icon>add</mat-icon> New {{ e.label.toLowerCase() }}</a>
        }
      </div>

      <div class="toolbar">
        <div class="searchbox">
          <mat-icon>search</mat-icon>
          <input [(ngModel)]="q" (ngModelChange)="typed$.next()" [placeholder]="'Search ' + e.plural.toLowerCase() + '…'"
                 [attr.aria-label]="'Search ' + e.plural" />
          @if (q) { <button class="x" (click)="q = ''; reload(true)" aria-label="Clear search"><mat-icon>close</mat-icon></button> }
        </div>
        @if (e.kind === 'list') {
          <div class="seg" role="group" aria-label="Status">
            @for (s of statuses; track s.label) {
              <button [class.on]="active === s.value" (click)="active = s.value; reload(true)">{{ s.label }}</button>
            }
          </div>
        } @else {
          <div class="seg" role="group" aria-label="Date range">
            <button [class.on]="!preset() && !from && !to" (click)="clearDates()">All dates</button>
            @for (p of presets; track p.key) {
              <button [class.on]="preset() === p.key" (click)="usePreset(p)">{{ p.label }}</button>
            }
          </div>
          <div class="dates">
            <input type="date" [(ngModel)]="from" (change)="preset.set(null); reload(true)" aria-label="From date" />
            <span>–</span>
            <input type="date" [(ngModel)]="to" (change)="preset.set(null); reload(true)" aria-label="To date" />
          </div>
        }
      </div>

      <mat-menu #viewMenu="matMenu">
        <div class="menu-title">Saved views</div>
        @for (v of views(); track v.name) {
          <div class="view-row">
            <button mat-menu-item (click)="applyView(v)"><mat-icon>bookmark</mat-icon>{{ v.name }}</button>
            <button mat-icon-button (click)="$event.stopPropagation(); deleteView(v)" [attr.aria-label]="'Delete view ' + v.name">
              <mat-icon>close</mat-icon></button>
          </div>
        } @empty { <div class="menu-note">No saved views yet.</div> }
        <button mat-menu-item (click)="saveView()"><mat-icon>bookmark_add</mat-icon>Save current filters as a view…</button>
      </mat-menu>
      <mat-menu #colMenu="matMenu" class="col-menu">
        <div class="menu-title">Show columns</div>
        @for (f of allCols(); track f.path) {
          <div class="col-row" (click)="$event.stopPropagation()">
            <mat-checkbox [checked]="isShown(f)" (change)="toggleCol(f, $event.checked)">{{ f.label }}</mat-checkbox></div>
        }
        <button mat-menu-item (click)="resetCols()"><mat-icon>restart_alt</mat-icon>Default columns</button>
      </mat-menu>

      @if (sel().size) {
        <div class="selbar">
          <strong>{{ sel().size }} selected</strong>
          <button mat-stroked-button (click)="exportSelected()"><mat-icon>table_view</mat-icon> Excel</button>
          @if (e.kind === 'txn') {
            <button mat-stroked-button (click)="pdfSelected()" [disabled]="bulkBusy()"><mat-icon>picture_as_pdf</mat-icon> PDFs (zip)</button>
            <button mat-stroked-button (click)="emailSelected()" [disabled]="bulkBusy()"><mat-icon>forward_to_inbox</mat-icon> E-mail each</button>
          }
          <span class="spacer"></span>
          <button mat-button (click)="clearSel()">Clear</button>
        </div>
      }

      <div class="panel flush">
        <div class="bar">@if (loading() && rows().length) { <mat-progress-bar mode="indeterminate" /> }</div>
        <div class="scroll">
          <table class="simple">
            <thead><tr>
              <th class="ck"><mat-checkbox [checked]="pageAllPicked()" [indeterminate]="pageSomePicked() && !pageAllPicked()"
                (change)="pickPage($event.checked)" aria-label="Select all on this page" /></th>
              <th><button class="sort" (click)="sortBy('name')">{{ e.kind === 'txn' ? 'No.' : 'Name' }}<mat-icon>{{ arrow('name') }}</mat-icon></button></th>
              @if (e.kind === 'txn') {
                <th><button class="sort" (click)="sortBy('txn_date')">Date<mat-icon>{{ arrow('txn_date') }}</mat-icon></button></th>
                <th><button class="sort" (click)="sortBy('party_name')">Name<mat-icon>{{ arrow('party_name') }}</mat-icon></button></th>
              }
              @for (c of cols(); track c.path) { <th [class.num]="isNum(c)">{{ c.label }}</th> }
              @if (e.kind === 'txn') {
                <th class="num"><button class="sort right" (click)="sortBy('amount')">Amount<mat-icon>{{ arrow('amount') }}</mat-icon></button></th>
              }
            </tr></thead>
            <tbody>
              @if (loading() && !rows().length) {
                @for (i of skeleton; track i) {
                  <tr class="sk"><td colspan="20"><span [style.width.%]="40 + (i * 13) % 50"></span></td></tr>
                }
              } @else {
                @for (r of rows(); track r.record_id) {
                  <tr class="clickable" [class.sel]="sel().has(r.record_id)" (click)="open(r)">
                    <td class="ck" (click)="$event.stopPropagation()"><mat-checkbox [checked]="sel().has(r.record_id)"
                      (change)="pick(r.record_id, $event.checked)" [attr.aria-label]="'Select ' + (r.name || 'row')" /></td>
                    <td><a [routerLink]="['/qb', e.key, r.record_id]" (click)="$event.stopPropagation()">{{ r.name || '(no number)' }}</a>
                      @if (!r.is_active) { <span class="tag">inactive</span> }</td>
                    @if (e.kind === 'txn') { <td class="nowrap">{{ r.txn_date | date: 'mediumDate' }}</td><td>{{ r.party_name }}</td> }
                    @for (c of cols(); track c.path) {
                      <td [class.num]="isNum(c)">{{ isNum(c) ? (r.columns[c.path] | money) : (r.columns[c.path] | humanize) }}</td>
                    }
                    @if (e.kind === 'txn') { <td class="num strong">{{ r.amount | money }}</td> }
                  </tr>
                } @empty {
                  <tr><td colspan="20">
                    <div class="empty">
                      <mat-icon>{{ filtered() ? 'search_off' : 'inbox' }}</mat-icon>
                      @if (filtered()) {
                        <div>No {{ e.plural.toLowerCase() }} match these filters.</div>
                        <button mat-stroked-button (click)="resetFilters()">Clear filters</button>
                      } @else {
                        <div>No {{ e.plural.toLowerCase() }} yet. They appear after the next QuickBooks sync.</div>
                      }
                    </div>
                  </td></tr>
                }
              }
            </tbody>
            @if (e.kind === 'txn' && sum() !== null && rows().length) {
              <tfoot><tr>
                <td [attr.colspan]="4 + cols().length">Total of {{ total() | number }} {{ e.plural.toLowerCase() }}{{ filtered() ? ' (filtered)' : '' }}</td>
                <td class="num">{{ sum() | money }}</td>
              </tr></tfoot>
            }
          </table>
        </div>
        <mat-paginator [length]="total()" [pageIndex]="page - 1" [pageSize]="pageSize" [pageSizeOptions]="[25, 50, 100]"
                       (page)="onPage($event)" showFirstLastButtons />
      </div>
    }
  `,
  styles: [`
    .crumb { font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
    .count { font-size: 13px; font-weight: 600; color: var(--muted); background: var(--surface-2); border: 1px solid var(--line);
      padding: 2px 9px; border-radius: 999px; vertical-align: middle; margin-left: 6px; font-variant-numeric: tabular-nums; }

    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 14px; }
    .searchbox { flex: 1; min-width: 240px; display: flex; align-items: center; gap: 8px; height: 40px; padding: 0 6px 0 12px;
      background: var(--surface); border: 1px solid var(--line-strong); border-radius: 10px; transition: border-color .15s, box-shadow .15s; }
    .searchbox:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 18%, transparent); }
    .searchbox mat-icon { color: var(--muted); font-size: 20px; width: 20px; height: 20px; }
    .searchbox input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font: inherit; color: var(--text); }
    .x { border: 0; background: none; cursor: pointer; display: grid; place-items: center; padding: 4px; border-radius: 6px; }
    .x:hover { background: var(--surface-2); }
    .x mat-icon { font-size: 18px; width: 18px; height: 18px; }

    .seg { display: inline-flex; padding: 3px; gap: 2px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; flex-wrap: wrap; }
    .seg button { border: 0; background: none; font: inherit; font-size: 13px; font-weight: 500; color: var(--text-2);
      padding: 6px 12px; border-radius: 7px; cursor: pointer; white-space: nowrap; }
    .seg button:hover { color: var(--text); }
    .seg button.on { background: var(--surface); color: var(--primary); box-shadow: 0 1px 2px rgba(15, 23, 42, .1); font-weight: 600; }

    .dates { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); }
    .dates input { height: 38px; padding: 0 10px; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--surface);
      color: var(--text); font: inherit; font-size: 13px; color-scheme: inherit; }
    .dates input:focus { outline: 2px solid color-mix(in srgb, var(--primary) 40%, transparent); outline-offset: 0; }

    .bar { height: 4px; }
    .sort { display: inline-flex; align-items: center; gap: 2px; border: 0; background: none; padding: 0; cursor: pointer;
      font: inherit; text-transform: inherit; letter-spacing: inherit; color: inherit; }
    .sort:hover { color: var(--text); }
    .sort mat-icon { font-size: 15px; width: 15px; height: 15px; opacity: .8; }
    .nowrap { white-space: nowrap; }
    .strong { color: var(--text) !important; font-weight: 600; }
    tfoot td { background: var(--surface-2); font-weight: 600; color: var(--text); border-top: 1px solid var(--line); border-bottom: 0; }
    .sk td { padding: 14px; }
    .sk span { display: block; height: 12px; border-radius: 6px;
      background: linear-gradient(90deg, var(--surface-2), var(--line), var(--surface-2)); background-size: 200% 100%;
      animation: shimmer 1.2s infinite; }
    @keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
    .empty button { margin-top: 12px; }
    .ck { width: 40px; padding-right: 0 !important; }
    tr.sel td { background: var(--primary-soft); }
    .selbar { position: sticky; top: 64px; z-index: 2; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 12px;
      margin-bottom: 10px; border-radius: 10px; background: var(--surface); border: 1px solid color-mix(in srgb, var(--primary) 40%, var(--line));
      box-shadow: var(--shadow); }
    .menu-title { padding: 8px 16px 4px; font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
    .menu-note { padding: 4px 16px 8px; font-size: 13px; color: var(--muted); }
    .view-row { display: flex; align-items: center; } .view-row button[mat-menu-item] { flex: 1; }
    .col-row { padding: 0 8px; }
    @media (max-width: 700px) { .dates { width: 100%; } .dates input { flex: 1; } }
  `],
})
export class QbListComponent {
  entity = input.required<string>();
  /** ?q= from links such as the aging page */
  qParam = input<string | undefined>(undefined, { alias: 'q' });
  private portal = inject(PortalService);
  private router = inject(Router);
  private api = inject(ApiService);
  private insights = inject(InsightsService);
  private snack = inject(MatSnackBar);
  ent = signal<EntityMeta | null>(null);
  sel = signal<Set<number>>(new Set());
  bulkBusy = signal(false);

  rows = signal<QbRecord[]>([]);
  total = signal(0);
  sum = signal<number | null>(null);
  loading = signal(false);
  preset = signal<string | null>(null);
  sort = signal<{ key: SortKey; dir: 'asc' | 'desc' } | null>(null);
  typed$ = new Subject<void>();
  /** Every column the user may show (addresses are too wide for a list). */
  allCols = computed(() => (this.ent()?.fields ?? []).filter((f) => f.type !== 'address' && !FIXED.includes(f.path)));
  cols = computed(() => {
    const chosen = this.insights.prefs()?.columns?.[this.entity()];
    const all = this.allCols();
    return chosen ? all.filter((f) => chosen.includes(f.path)) : all.filter((f) => f.list);
  });
  views = computed<SavedView[]>(() => this.insights.prefs()?.views?.[this.entity()] ?? []);
  pageAllPicked = computed(() => this.rows().length > 0 && this.rows().every((r) => this.sel().has(r.record_id)));
  pageSomePicked = computed(() => this.rows().some((r) => this.sel().has(r.record_id)));
  moduleLabel = computed(() => this.portal.meta()?.modules.find((m) => m.key === this.ent()?.module)?.label ?? '');
  presets = PRESETS;
  statuses: { label: string; value: boolean | null }[] = [
    { label: 'Active', value: true }, { label: 'Inactive', value: false }, { label: 'All', value: null }];
  skeleton = [1, 2, 3, 4, 5, 6, 7, 8];

  q = '';
  active: boolean | null = true;
  from = '';
  to = '';
  page = 1;
  pageSize = 25;

  constructor() {
    this.insights.loadPrefs().catch(() => undefined);
    this.typed$.pipe(debounceTime(300)).subscribe(() => this.reload(true));
    effect(() => {
      const key = this.entity();
      this.portal.load().then(() => {
        this.ent.set(this.portal.entity(key) ?? null);
        this.q = this.qParam() ?? ''; this.from = ''; this.to = ''; this.page = 1; this.active = true;
        this.preset.set(null); this.sort.set(null); this.rows.set([]); this.sel.set(new Set());
        this.reload();
      });
    }, { allowSignalWrites: true });
  }

  // ---------------------------------------------------------------- columns & saved views (saved per user)
  isShown(f: FieldMeta) { return this.cols().some((c) => c.path === f.path); }
  toggleCol(f: FieldMeta, on: boolean) {
    const now = this.cols().map((c) => c.path);
    const next = on ? this.allCols().map((c) => c.path).filter((p) => p === f.path || now.includes(p)) : now.filter((p) => p !== f.path);
    this.savePrefs({ columns: { ...(this.insights.prefs()?.columns ?? {}), [this.entity()]: next } });
  }
  resetCols() {
    const cols = { ...(this.insights.prefs()?.columns ?? {}) };
    delete cols[this.entity()];
    this.savePrefs({ columns: cols });
  }
  saveView() {
    const name = prompt('Name for this view (for example "Overdue this month")')?.trim();
    if (!name) return;
    const params = { q: this.q, active: this.active, from: this.from, to: this.to, preset: this.preset(), sort: this.sort() };
    const list = [...this.views().filter((v) => v.name !== name), { name, params }];
    this.savePrefs({ views: { ...(this.insights.prefs()?.views ?? {}), [this.entity()]: list } }, `View "${name}" saved`);
  }
  applyView(v: SavedView) {
    const p = v.params as any;
    this.q = p.q ?? ''; this.active = p.active ?? true; this.sort.set(p.sort ?? null);
    const preset = PRESETS.find((x) => x.key === p.preset);
    if (preset) { this.usePreset(preset); return; }  // relative ranges ("This month") move with time
    this.from = p.from ?? ''; this.to = p.to ?? ''; this.preset.set(null);
    this.reload(true);
  }
  deleteView(v: SavedView) {
    this.savePrefs({ views: { ...(this.insights.prefs()?.views ?? {}), [this.entity()]: this.views().filter((x) => x.name !== v.name) } });
  }
  private savePrefs(patch: object, msg?: string) {
    this.insights.savePrefs(patch).subscribe({
      next: () => msg && this.snack.open(msg, '', { duration: 2500 }),
      error: (e) => this.snack.open(errorText(e), 'OK'),
    });
  }

  // ---------------------------------------------------------------- selection & bulk actions
  pick(id: number, on: boolean) {
    const s = new Set(this.sel());
    if (on) s.add(id); else s.delete(id);
    this.sel.set(s);
  }
  clearSel() { this.sel.set(new Set()); }
  pickPage(on: boolean) {
    const s = new Set(this.sel());
    for (const r of this.rows()) if (on) s.add(r.record_id); else s.delete(r.record_id);
    this.sel.set(s);
  }
  exportSelected() { this.api.download(`/files/export/${this.entity()}`, { ids: [...this.sel()], active: null }).subscribe(); }
  pdfSelected() {
    const ids = [...this.sel()];
    if (ids.length > 100) { this.snack.open('Select up to 100 documents at a time', 'OK'); return; }
    this.bulkBusy.set(true);
    this.insights.bulkPdf(this.entity(), ids).subscribe({
      next: (b) => { this.bulkBusy.set(false); openBlob(b, `${this.ent()?.plural ?? 'documents'}.zip`); },
      error: (e) => { this.bulkBusy.set(false); this.snack.open(errorText(e), 'OK'); },
    });
  }
  emailSelected() {
    const ids = [...this.sel()];
    if (ids.length > 100) { this.snack.open('Select up to 100 documents at a time', 'OK'); return; }
    const party = this.ent()?.module === 'purchasing' ? 'vendor' : 'customer';
    if (!confirm(`E-mail ${ids.length} documents? Each one goes to its own ${party}'s e-mail address saved in QuickBooks.`)) return;
    this.bulkBusy.set(true);
    this.insights.bulkEmail(this.entity(), ids, null).subscribe({
      next: (r) => {
        this.bulkBusy.set(false);
        const skipped = r.skipped.length ? ` · ${r.skipped.length} skipped (${[...new Set(r.skipped.map((x) => x.reason))].join('; ')})` : '';
        this.snack.open(`Sent ${r.sent.length}${skipped}`, 'OK', { duration: 8000 });
      },
      error: (e) => { this.bulkBusy.set(false); this.snack.open(errorText(e), 'OK'); },
    });
  }

  /** N = new record (when not typing in a field). */
  @HostListener('document:keydown', ['$event'])
  keys(ev: KeyboardEvent) {
    const typing = (ev.target as HTMLElement | null)?.closest?.('input, textarea, select, [contenteditable="true"]');
    const e = this.ent();
    if (!typing && !ev.ctrlKey && !ev.metaKey && !ev.altKey && ev.key.toLowerCase() === 'n' && e?.can_add && e.permissions.create) {
      ev.preventDefault();
      this.router.navigate(['/qb', e.key, 'new']);
    }
  }

  isNum(f: FieldMeta) { return f.type === 'money' || f.type === 'decimal'; }
  filtered() { return !!(this.q || this.from || this.to || (this.ent()?.kind === 'list' && this.active !== true)); }

  sortBy(key: SortKey) {
    const s = this.sort();
    // first click: dates & amounts newest/biggest first, names A→Z; second click flips; third resets
    const first = key === 'txn_date' || key === 'amount' ? 'desc' : 'asc';
    if (!s || s.key !== key) this.sort.set({ key, dir: first });
    else if (s.dir === first) this.sort.set({ key, dir: first === 'asc' ? 'desc' : 'asc' });
    else this.sort.set(null);
    this.reload(true);
  }
  arrow(key: SortKey) {
    const s = this.sort();
    return s?.key === key ? (s.dir === 'asc' ? 'arrow_upward' : 'arrow_downward') : 'unfold_more';
  }

  usePreset(p: Preset) {
    const [a, b] = p.range();
    this.from = iso(a); this.to = iso(b);
    this.preset.set(p.key);
    this.reload(true);
  }
  clearDates() { this.from = ''; this.to = ''; this.preset.set(null); this.reload(true); }
  resetFilters() { this.q = ''; this.active = true; this.clearDates(); }

  reload(reset = false) {
    const e = this.ent();
    if (!e) return;
    if (reset) this.page = 1;
    this.loading.set(true);
    const s = this.sort();
    this.portal.list(e.key, { q: this.q, active: e.kind === 'list' ? this.active : null, date_from: this.from, date_to: this.to,
      page: this.page, page_size: this.pageSize, sort: s?.key, dir: s?.dir }).subscribe({
      next: (p) => { this.rows.set(p.items); this.total.set(p.total); this.sum.set(p.sum_amount ?? null); this.loading.set(false); },
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
