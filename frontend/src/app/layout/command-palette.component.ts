import { DatePipe } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, ElementRef, computed, effect, inject, input, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { Router } from '@angular/router';
import { Subject, catchError, debounceTime, of, switchMap } from 'rxjs';
import { UiService } from '../core/ui.service';
import { MoneyPipe } from '../shared/shared';

export interface PaletteLink { path: string; label: string; group: string; icon: string; keywords?: string }

interface Hit {
  record_id: number; entity: string; label: string; kind: string; name: string | null; party_name: string | null;
  txn_date: string | null; amount: number | null; is_active: boolean;
}

type Row =
  | { type: 'page'; link: PaletteLink }
  | { type: 'new'; link: PaletteLink }
  | { type: 'record'; hit: Hit; recent?: boolean };

/** Ctrl+K: jump to any page, start a new record, or find any customer / invoice / item by name or number. */
@Component({
  selector: 'app-command-palette',
  standalone: true,
  imports: [DatePipe, FormsModule, MatIconModule, MoneyPipe],
  template: `
    <div class="backdrop" (click)="close()"></div>
    <div class="box" role="dialog" aria-modal="true" aria-label="Search">
      <div class="search">
        <mat-icon>search</mat-icon>
        <input #inp [(ngModel)]="q" (ngModelChange)="typed($event)" (keydown)="key($event)"
               placeholder="Search customers, invoices, items, pages…" aria-label="Search" autocomplete="off" spellcheck="false" />
        @if (loading()) { <span class="spin" aria-hidden="true"></span> }
        <kbd>Esc</kbd>
      </div>

      <div class="results" role="listbox">
        @for (sec of sections(); track sec.title) {
          <div class="sec">{{ sec.title }}</div>
          @for (r of sec.rows; track $index) {
            <button class="row" role="option" [class.on]="index(r) === active()" [attr.aria-selected]="index(r) === active()"
                    (mouseenter)="active.set(index(r))" (click)="go(r)">
              @switch (r.type) {
                @case ('record') {
                  <span class="ic rec"><mat-icon>{{ r.recent ? 'history' : (r.hit.kind === 'txn' ? 'receipt_long' : 'badge') }}</mat-icon></span>
                  <span class="txt">
                    <strong>{{ r.hit.name || '(no number)' }}</strong>
                    <small>{{ r.hit.label }}@if (r.hit.party_name && r.hit.party_name !== r.hit.name) { · {{ r.hit.party_name }} }
                      @if (r.hit.txn_date) { · {{ r.hit.txn_date | date: 'mediumDate' }} }@if (!r.hit.is_active) { · inactive }</small>
                  </span>
                  @if (r.hit.amount !== null && r.hit.kind === 'txn') { <span class="amt">{{ r.hit.amount | money }}</span> }
                }
                @case ('new') {
                  <span class="ic new"><mat-icon>add</mat-icon></span>
                  <span class="txt"><strong>{{ r.link.label }}</strong><small>{{ r.link.group }}</small></span>
                }
                @default {
                  <span class="ic"><mat-icon>{{ r.link.icon }}</mat-icon></span>
                  <span class="txt"><strong>{{ r.link.label }}</strong><small>{{ r.link.group }}</small></span>
                }
              }
              <mat-icon class="enter">keyboard_return</mat-icon>
            </button>
          }
        } @empty {
          <div class="none">
            @if (q.trim().length >= 2 && !loading()) { Nothing found for “{{ q.trim() }}”. }
            @else { Type a name, invoice number or page. }
          </div>
        }
      </div>

      <div class="foot">
        <span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span>
        <span><kbd>Ctrl</kbd><kbd>K</kbd> search anywhere</span>
      </div>
    </div>
  `,
  styles: [`
    :host { position: fixed; inset: 0; z-index: 1000; display: flex; justify-content: center; align-items: flex-start; padding: 12vh 16px 16px; }
    .backdrop { position: absolute; inset: 0; background: rgba(8, 12, 22, .45); backdrop-filter: blur(2px); animation: fade .12s; }
    .box { position: relative; width: 100%; max-width: 640px; max-height: 72vh; display: flex; flex-direction: column;
      background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: var(--shadow-lg);
      overflow: hidden; animation: pop .14s ease-out; }
    .search { display: flex; align-items: center; gap: 10px; padding: 0 16px; height: 56px; border-bottom: 1px solid var(--line); }
    .search mat-icon { color: var(--muted); }
    .search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font: inherit; font-size: 16px; color: var(--text); }
    .spin { width: 16px; height: 16px; border: 2px solid var(--line-strong); border-top-color: var(--primary); border-radius: 50%;
      animation: spin .7s linear infinite; }
    kbd { font: 11px/1 Inter, system-ui, sans-serif; padding: 3px 6px; border-radius: 5px; border: 1px solid var(--line-strong);
      border-bottom-width: 2px; color: var(--muted); background: var(--surface-2); }
    .results { overflow-y: auto; padding: 6px 8px 8px; }
    .sec { padding: 10px 10px 4px; font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
    .row { display: flex; align-items: center; gap: 12px; width: 100%; padding: 8px 10px; border: 0; border-radius: 10px;
      background: none; font: inherit; text-align: left; color: var(--text); cursor: pointer; }
    .row.on { background: var(--primary-soft); }
    .ic { width: 32px; height: 32px; flex: none; border-radius: 8px; display: grid; place-items: center;
      background: var(--surface-2); border: 1px solid var(--line); color: var(--muted); }
    .ic mat-icon { font-size: 18px; width: 18px; height: 18px; }
    .ic.rec { color: var(--primary); } .ic.new { color: var(--ok); }
    .row.on .ic { border-color: color-mix(in srgb, var(--primary) 30%, var(--line)); }
    .txt { flex: 1; min-width: 0; display: flex; flex-direction: column; line-height: 1.3; }
    .txt strong { font-size: 14px; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .txt small { font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .amt { font-variant-numeric: tabular-nums; font-size: 13px; color: var(--text-2); }
    .enter { visibility: hidden; color: var(--muted); font-size: 16px; width: 16px; height: 16px; }
    .row.on .enter { visibility: visible; }
    .none { padding: 28px 16px; text-align: center; color: var(--muted); }
    .foot { display: flex; gap: 16px; padding: 10px 16px; border-top: 1px solid var(--line); background: var(--surface-2);
      font-size: 12px; color: var(--muted); }
    .foot span { display: inline-flex; gap: 4px; align-items: center; }
    @media (max-width: 600px) { :host { padding-top: 16px; } .foot { display: none; } }
    @keyframes pop { from { opacity: 0; transform: translateY(-6px) scale(.98); } }
    @keyframes fade { from { opacity: 0; } }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .box, .backdrop { animation: none; } }
  `],
})
export class CommandPaletteComponent {
  links = input<PaletteLink[]>([]);
  newLinks = input<PaletteLink[]>([]);
  private http = inject(HttpClient);
  private router = inject(Router);
  private ui = inject(UiService);
  private inp = viewChild<ElementRef<HTMLInputElement>>('inp');

  q = '';
  private query = signal('');
  hits = signal<Hit[]>([]);
  loading = signal(false);
  active = signal(0);
  private q$ = new Subject<string>();

  constructor() {
    this.q$.pipe(
      debounceTime(180),
      switchMap((q) => {
        if (q.length < 2) { this.loading.set(false); return of([] as Hit[]); }
        return this.http.get<Hit[]>('/api/qb/search', { params: new HttpParams().set('q', q).set('limit', 12) })
          .pipe(catchError(() => of([] as Hit[])));
      }),
    ).subscribe((h) => { this.hits.set(h); this.loading.set(false); this.active.set(0); });
    effect(() => this.inp()?.nativeElement.focus());
  }

  sections = computed(() => {
    const q = this.query().toLowerCase();
    const words = q.split(/\s+/).filter(Boolean);
    const match = (l: PaletteLink) => words.every((w) => `${l.label} ${l.group} ${l.keywords ?? ''}`.toLowerCase().includes(w));
    const out: { title: string; rows: Row[] }[] = [];
    if (!q) {
      const recent = this.ui.recent().slice(0, 6);
      if (recent.length) out.push({ title: 'Recently opened', rows: recent.map((r) => ({ type: 'record' as const, recent: true,
        hit: { record_id: r.record_id, entity: r.entity, label: r.label, kind: '', name: r.name, party_name: r.party_name,
          txn_date: null, amount: null, is_active: true } })) });
      out.push({ title: 'Go to', rows: this.links().slice(0, 8).map((link) => ({ type: 'page' as const, link })) });
      return out;
    }
    if (this.hits().length) out.push({ title: 'Records', rows: this.hits().map((hit) => ({ type: 'record' as const, hit })) });
    const pages = this.links().filter(match).slice(0, 6);
    if (pages.length) out.push({ title: 'Pages', rows: pages.map((link) => ({ type: 'page' as const, link })) });
    const create = this.newLinks().filter(match).slice(0, 4);
    if (create.length) out.push({ title: 'Create', rows: create.map((link) => ({ type: 'new' as const, link })) });
    return out;
  });

  private flat = computed(() => this.sections().flatMap((s) => s.rows));
  index(r: Row) { return this.flat().indexOf(r); }

  typed(v: string) {
    const q = v.trim();
    this.query.set(q);
    this.active.set(0);
    this.loading.set(q.length >= 2);
    this.q$.next(q);
  }

  key(e: KeyboardEvent) {
    const n = this.flat().length;
    if (e.key === 'ArrowDown') { e.preventDefault(); this.active.set(n ? (this.active() + 1) % n : 0); this.scroll(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this.active.set(n ? (this.active() - 1 + n) % n : 0); this.scroll(); }
    else if (e.key === 'Enter') { e.preventDefault(); const r = this.flat()[this.active()]; if (r) this.go(r); }
    else if (e.key === 'Escape') { e.preventDefault(); this.close(); }
  }

  private scroll() {
    setTimeout(() => document.querySelector('app-command-palette .row.on')?.scrollIntoView({ block: 'nearest' }));
  }

  go(r: Row) {
    this.close();
    if (r.type === 'record') this.router.navigate(['/qb', r.hit.entity, r.hit.record_id]);
    else this.router.navigateByUrl(r.link.path);
  }

  close() { this.ui.paletteOpen.set(false); }
}
