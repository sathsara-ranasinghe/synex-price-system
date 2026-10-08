import { HttpClient } from '@angular/common/http';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { errorText } from '../core/auth';
import { EntityMeta } from '../core/models';
import { PortalService } from '../core/portal.service';

interface ImportDoc { row: number; key: string | null; summary: string; lines: number; values: unknown; line_items: unknown[]; errors: string[] }
interface Preview { documents: ImportDoc[]; valid: number; invalid: number; direct: boolean }
interface Result { sent_to_quickbooks: number; waiting_for_approval: number; skipped: number; errors: string[] }

@Component({
  selector: 'app-qb-import',
  standalone: true,
  imports: [RouterLink, MatButtonModule, MatIconModule, MatProgressBarModule],
  template: `
    @if (ent(); as e) {
      <a [routerLink]="['/qb', e.key]" class="back"><mat-icon>arrow_back</mat-icon> {{ e.plural }}</a>
      <div class="head"><div><h1>Import {{ e.plural.toLowerCase() }}</h1>
        <div class="sub">Add many {{ e.plural.toLowerCase() }} at once from Excel or CSV.</div></div></div>

      <div class="steps">
        <section class="panel step">
          <span class="num">1</span>
          <div>
            <h2>Download the template</h2>
            <p class="muted">Fill the first sheet. The <strong>Help</strong> sheet lists every column, which ones are required
              and the allowed values; the <strong>Example</strong> sheet shows a filled row.
              @if (e.lines.length) { Rows with the same <strong>Doc key</strong> become one {{ e.label.toLowerCase() }} - one line per row. }
              Customers, items, accounts and other lists are entered <strong>by name</strong>, exactly as in QuickBooks.</p>
            <button mat-flat-button color="primary" (click)="template('xlsx')"><mat-icon>table_view</mat-icon> Excel template</button>
            <button mat-stroked-button (click)="template('csv')"><mat-icon>description</mat-icon> CSV template</button>
          </div>
        </section>

        <section class="panel step">
          <span class="num">2</span>
          <div>
            <h2>Upload the filled file</h2>
            <p class="muted">.xlsx or .csv, up to 5,000 rows. Nothing is sent to QuickBooks until you confirm.</p>
            <input type="file" accept=".xlsx,.xlsm,.csv" hidden #f (change)="upload($event)" />
            <button mat-flat-button color="primary" (click)="f.click()" [disabled]="busy()"><mat-icon>upload_file</mat-icon> Choose file</button>
            @if (fileName()) { <span class="fname">{{ fileName() }}</span> }
          </div>
        </section>
      </div>
      @if (busy()) { <mat-progress-bar mode="indeterminate" /> }

      @if (preview(); as p) {
        <section class="panel flush result">
          <div class="bar">
            <span class="tag ok">{{ p.valid }} ready</span>
            @if (p.invalid) { <span class="tag bad">{{ p.invalid }} with problems - will be skipped</span> }
            <span class="spacer"></span>
            <button mat-flat-button color="primary" [disabled]="!p.valid || busy()" (click)="commit()">
              <mat-icon>cloud_upload</mat-icon>
              {{ p.direct ? 'Send ' + p.valid + ' to QuickBooks' : 'Submit ' + p.valid + ' for approval' }}</button>
          </div>
          <div class="scroll">
            <table class="simple">
              <tr><th>Row</th>@if (e.lines.length) {<th>Doc key</th>}<th>{{ e.label }}</th>@if (e.lines.length) {<th class="num">Lines</th>}<th>Status</th></tr>
              @for (d of shown(); track d.row) {
                <tr [class.bad-row]="d.errors.length">
                  <td>{{ d.row }}</td>@if (e.lines.length) {<td>{{ d.key }}</td>}<td>{{ d.summary }}</td>
                  @if (e.lines.length) {<td class="num">{{ d.lines }}</td>}
                  <td>@if (d.errors.length) { @for (er of d.errors; track $index) { <div class="err">{{ er }}</div> } }
                      @else { <span class="tag ok">OK</span> }</td>
                </tr>
              }
            </table>
          </div>
          @if (p.documents.length > shown().length) {
            <p class="muted pad">Showing the first {{ shown().length }} of {{ p.documents.length }}.</p>
          }
        </section>
      }

      @if (result(); as r) {
        <section class="panel done">
          <mat-icon>task_alt</mat-icon>
          <div>
            <strong>Import finished.</strong>
            {{ r.sent_to_quickbooks }} sent to QuickBooks (next sync), {{ r.waiting_for_approval }} waiting for approval,
            {{ r.skipped }} skipped.
            <div><a routerLink="/qb-changes">Open QuickBooks changes</a></div>
          </div>
        </section>
      }
    }
  `,
  styles: [`
    .back { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); margin-bottom: 8px; }
    .steps { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
    @media (max-width: 900px) { .steps { grid-template-columns: 1fr; } }
    .step { display: flex; gap: 16px; align-items: flex-start; }
    .step button { margin: 4px 8px 0 0; }
    .num { flex: none; width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; font-weight: 700;
      background: var(--primary-soft); color: var(--primary); }
    .fname { margin-left: 8px; color: var(--muted); }
    .result { margin-top: 16px; } .bar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--line); }
    .bad-row td { background: var(--danger-soft); } .err { color: var(--danger); font-size: 12.5px; }
    .pad { padding: 8px 16px; } .spacer { flex: 1; }
    .done { display: flex; gap: 12px; align-items: flex-start; margin-top: 16px; background: var(--ok-soft); border-color: transparent; }
    .done mat-icon { color: var(--ok); }
  `],
})
export class QbImportComponent {
  entity = input.required<string>();
  private portal = inject(PortalService);
  private api = inject(ApiService);
  private http = inject(HttpClient);
  private snack = inject(MatSnackBar);
  ent = signal<EntityMeta | null>(null);
  preview = signal<Preview | null>(null);
  result = signal<Result | null>(null);
  busy = signal(false);
  fileName = signal('');
  shown = computed(() => (this.preview()?.documents ?? []).slice(0, 500));

  constructor() {
    effect(() => {
      const key = this.entity();
      this.portal.load().then(() => this.ent.set(this.portal.entity(key) ?? null));
    }, { allowSignalWrites: true });
  }

  template(format: 'xlsx' | 'csv') { this.api.download(`/files/template/${this.ent()!.key}`, { format }).subscribe(); }

  upload(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    this.fileName.set(file.name);
    this.result.set(null);
    this.busy.set(true);
    const fd = new FormData();
    fd.append('file', file);
    this.http.post<Preview>(`/api/files/import/${this.ent()!.key}/preview`, fd).subscribe({
      next: (p) => { this.preview.set(p); this.busy.set(false); },
      error: (e) => { this.snack.open(errorText(e), 'OK'); this.preview.set(null); this.busy.set(false); },
    });
  }

  commit() {
    const docs = this.preview()!.documents.filter((d) => !d.errors.length).map((d) => ({ values: d.values, line_items: d.line_items }));
    this.busy.set(true);
    this.http.post<Result>(`/api/files/import/${this.ent()!.key}/commit`, { documents: docs }).subscribe({
      next: (r) => { this.result.set(r); this.preview.set(null); this.fileName.set(''); this.busy.set(false); },
      error: (e) => { this.snack.open(errorText(e), 'OK'); this.busy.set(false); },
    });
  }
}
