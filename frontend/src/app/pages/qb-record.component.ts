import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router, RouterLink } from '@angular/router';
import { errorText } from '../core/auth';
import { EntityMeta, LineMeta, QbLine, QbRecordDetail } from '../core/models';
import { Attachment, PortalService, WriteResult, openBlob } from '../core/portal.service';
import { QbFieldComponent } from '../shared/qb-field.component';
import { MoneyPipe } from '../shared/shared';

@Component({
  selector: 'app-qb-record',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, MatButtonModule, MatIconModule, QbFieldComponent, MoneyPipe],
  template: `
    @if (ent(); as e) {
      <a [routerLink]="['/qb', e.key]" class="back"><mat-icon>arrow_back</mat-icon> {{ e.plural }}</a>
      <div class="head">
        <div>
          <h1>{{ isNew() ? 'New ' + e.label.toLowerCase() : (detail()?.record?.name || e.label) }}</h1>
          @if (detail(); as d) {
            <div class="muted small">{{ e.label }} · last changed in QuickBooks {{ d.record.time_modified | date: 'medium' }}
              @if (d.record.amount !== null) { · {{ d.record.amount | money }} }</div>
          }
        </div>
        <span class="spacer"></span>
        @if (!isNew() && detail()) {
          @if (e.kind === 'txn') {
            <button mat-stroked-button (click)="print()"><mat-icon>print</mat-icon> Print / PDF</button>
            <button mat-stroked-button (click)="email()"><mat-icon>mail</mat-icon> E-mail</button>
          }
          @if ((e.key === 'estimate' || e.key === 'sales_order') && canCreate('invoice')) {
            <button mat-flat-button color="primary" (click)="copyTo('invoice')"><mat-icon>receipt_long</mat-icon> Create invoice</button>
          }
          @if (e.key === 'purchase_order' && canCreate('item_receipt')) {
            <button mat-stroked-button (click)="copyTo('item_receipt')"><mat-icon>inventory</mat-icon> Receive items</button>
          }
          @if (e.key === 'item_receipt' && canCreate('bill')) {
            <button mat-flat-button color="primary" (click)="toBill()"><mat-icon>request_quote</mat-icon> Convert to bill</button>
          }
          @if (e.can_void && e.permissions.delete) { <button mat-stroked-button (click)="act('void')"><mat-icon>block</mat-icon> Void</button> }
          @if (e.del_type && e.permissions.delete) { <button mat-stroked-button (click)="act('delete')"><mat-icon>delete</mat-icon> Delete</button> }
        }
      </div>

      @if (detail()?.pending_changes) {
        <div class="notice"><mat-icon>schedule</mat-icon> This record has changes waiting to be written to QuickBooks.</div>
      }
      @if (!editable()) {
        <div class="notice muted"><mat-icon>lock</mat-icon>
          {{ isNew() ? 'You cannot create ' + e.plural.toLowerCase() + '.' : e.can_mod ? 'Read only - you do not have edit permission.' :
             e.plural + ' cannot be edited through QuickBooks Web Connector. Delete and re-create instead.' }}</div>
      }

      <section class="panel">
        <div class="grid">
          @for (f of headerFields(); track f.path) {
            <qb-field [field]="f" [(value)]="values[f.path]" [disabled]="!editable() || (!isNew() && !f.mod)" (valueChange)="dirty = true; recalc()" />
          }
        </div>
      </section>

      @for (lt of e.lines; track lt.key) {
        <section class="panel lines">
          <h2>{{ e.lines.length > 1 ? lt.label + ' lines' : 'Lines' }}</h2>
          <div class="scroll">
            <table class="simple">
              <tr>
                @for (f of lt.fields; track f.path) { <th>{{ f.label }}</th> }
                @if (lt.amount) { <th class="num">Amount</th> }
                <th></th>
              </tr>
              @for (ln of linesOf(lt.key); track ln) {
                <tr>
                  @for (f of lt.fields; track f.path) {
                    <td class="cell" [class.wide]="f.type === 'ref' || f.type === 'txnref' || f.path === 'Desc'">
                      <qb-field [field]="f" [(value)]="ln.values[f.path]" [compact]="true" [disabled]="!linesEditable(lt)"
                                [partyId]="partyId()" (valueChange)="linesDirty = true; recalc()" />
                    </td>
                  }
                  @if (lt.amount) { <td class="num">{{ lineTotal(lt, ln) | money }}</td> }
                  <td>@if (linesEditable(lt)) {
                    <button mat-icon-button (click)="removeLine(ln)" aria-label="Remove line"><mat-icon>close</mat-icon></button>
                  }</td>
                </tr>
              }
            </table>
          </div>
          @if (linesEditable(lt)) {
            <button mat-button (click)="addLine(lt)"><mat-icon>add</mat-icon> Add {{ lt.label.toLowerCase() }} line</button>
          }
        </section>
      }
      @if (e.lines.length && totalAll()) {
        <div class="total">Total <strong>{{ totalAll() | money }}</strong></div>
      }

      @if (editable()) {
        <div class="actions">
          <a mat-button [routerLink]="['/qb', e.key]">Cancel</a>
          <button mat-flat-button color="primary" [disabled]="busy()" (click)="save()">
            {{ e.permissions.direct ? 'Save to QuickBooks' : 'Submit for approval' }}</button>
        </div>
        <p class="muted small right">Saved changes reach QuickBooks on the next Web Connector sync (a few minutes).</p>
      }

      @if (customFields().length) {
        <section class="panel">
          <h2>Custom fields</h2>
          <div class="cf">
            @for (c of customFields(); track c.name) { <div><span class="muted">{{ c.name }}</span><strong>{{ c.value }}</strong></div> }
          </div>
          <p class="muted small">Custom fields are read from QuickBooks; change them in QuickBooks.</p>
        </section>
      }

      @if (!isNew() && detail()) {
        <section class="panel">
          <div class="att-head">
            <h2>Attachments</h2>
            <span class="spacer"></span>
            <input type="file" hidden #fileInput (change)="upload($event)" />
            <button mat-stroked-button (click)="fileInput.click()" [disabled]="uploading()"><mat-icon>attach_file</mat-icon> Attach file</button>
          </div>
          @for (a of attachments(); track a.attachment_id) {
            <div class="att">
              <mat-icon>{{ a.content_type.startsWith('image/') ? 'image' : a.content_type.includes('pdf') ? 'picture_as_pdf' : 'description' }}</mat-icon>
              <a (click)="openAttachment(a)">{{ a.filename }}</a>
              <span class="muted small">{{ (a.size / 1024).toFixed(0) }} KB · {{ a.uploaded_by }} · {{ a.uploaded_at | date: 'short' }}</span>
              <span class="spacer"></span>
              <button mat-icon-button (click)="removeAttachment(a)" aria-label="Delete attachment"><mat-icon>delete</mat-icon></button>
            </div>
          } @empty { <p class="muted small">No files. Attachments are stored by the portal, not in QuickBooks.</p> }
        </section>
      }

      @if (detail()?.related?.length) {
        <section class="panel flush">
          <h2 class="pad">Transactions</h2>
          <table class="simple">
            <tr><th>Type</th><th>No.</th><th>Date</th><th class="num">Amount</th></tr>
            @for (r of detail()!.related; track r.record_id) {
              <tr class="clickable" [routerLink]="['/qb', r.entity, r.record_id]">
                <td>{{ r.label }}</td><td>{{ r.name }}</td><td>{{ r.txn_date | date: 'mediumDate' }}</td>
                <td class="num">{{ r.amount | money }}</td>
              </tr>
            }
          </table>
        </section>
      }
    }
  `,
  styles: [`
    .back { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); text-decoration: none; margin-bottom: 8px; }
    h1 { margin-bottom: 2px; } .small { font-size: 12px; } .pad { padding: 16px 16px 0; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); grid-auto-flow: row dense; gap: 8px 16px; align-items: start; }
    section { margin-bottom: 16px; }
    .lines td.cell { padding: 4px 6px; min-width: 110px; } .lines td.wide { min-width: 220px; }
    .notice { display: flex; gap: 8px; align-items: center; padding: 10px 14px; margin-bottom: 12px; border-radius: 8px;
      background: var(--primary-soft); }
    .total { text-align: right; font-size: 18px; margin: -4px 4px 16px; }
    .actions { display: flex; justify-content: flex-end; gap: 8px; } .right { text-align: right; }
    .head button { margin-left: 4px; }
    .cf { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px 16px; }
    .cf div { display: flex; flex-direction: column; } .cf span { font-size: 12px; }
    .att-head { display: flex; align-items: center; margin-bottom: 6px; } .att-head h2 { margin: 0; }
    .att { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-top: 1px solid var(--line); }
    .att a { cursor: pointer; font-weight: 500; } .att mat-icon { color: var(--muted); }
    .spacer { flex: 1; }
  `],
})
export class QbRecordComponent {
  entity = input.required<string>();
  id = input.required<string>();
  private portal = inject(PortalService);
  private snack = inject(MatSnackBar);
  private router = inject(Router);

  ent = signal<EntityMeta | null>(null);
  detail = signal<QbRecordDetail | null>(null);
  lines = signal<QbLine[]>([]);
  busy = signal(false);
  attachments = signal<Attachment[]>([]);
  uploading = signal(false);
  values: Record<string, any> = {};
  dirty = false;
  linesDirty = false;
  private tick = signal(0);

  isNew = computed(() => this.id() === 'new');
  customFields = computed(() => {
    const ext = (this.detail()?.data?.['DataExtRet'] as any[] | undefined) ?? [];
    return ext.filter((x) => x && x.DataExtName).map((x) => ({ name: x.DataExtName as string, value: x.DataExtValue as string }));
  });
  editable = computed(() => {
    const e = this.ent();
    if (!e) return false;
    return this.isNew() ? e.can_add && e.permissions.create : e.can_mod && e.permissions.edit;
  });
  headerFields = computed(() => (this.ent()?.fields ?? []).filter((f) => this.isNew() ? f.add : true));
  partyId = computed(() => {
    this.tick();
    const p = this.values['PayeeEntityRef'] ?? this.values['VendorRef'] ?? this.values['CustomerRef'];
    return p?.ListID ?? null;
  });
  totalAll = computed(() => {
    this.tick();
    const e = this.ent();
    return (e?.lines ?? []).reduce((t, lt) => t + this.linesOf(lt.key).reduce((s, ln) => s + this.lineTotal(lt, ln), 0), 0);
  });

  constructor() {
    effect(() => {
      const key = this.entity();
      const id = this.id();
      this.portal.load().then(() => {
        const e = this.portal.entity(key) ?? null;
        this.ent.set(e);
        this.dirty = this.linesDirty = false;
        if (id === 'new') {
          this.detail.set(null);
          this.values = {};
          for (const f of e?.fields ?? []) if (f.type === 'bool' && f.required) this.values[f.path] = true;
          if (e?.fields.some((f) => f.path === 'TxnDate')) this.values['TxnDate'] = new Date().toISOString().slice(0, 10);
          this.lines.set(e?.lines.length ? [{ type: e.lines[e.lines.length - 1].key, values: {} }] : []);
          const copy = (history.state as any)?.copy as { values: Record<string, any>; lines: QbLine[] } | undefined;
          if (copy) {
            this.values = { ...this.values, ...copy.values };
            this.lines.set(copy.lines);
            this.linesDirty = true;
          }
        } else {
          this.portal.get(key, Number(id)).subscribe((d) => {
            this.detail.set(d);
            this.values = structuredClone(d.form.values);
            this.lines.set(structuredClone(d.form.lines));
            this.portal.attachments(key, Number(id)).subscribe((a) => this.attachments.set(a));
          });
        }
      });
    }, { allowSignalWrites: true });
  }

  linesOf(type: string) { return this.lines().filter((l) => l.type === type); }
  linesEditable(lt: LineMeta) { return this.editable() && (this.isNew() || !!lt.mod_tag); }
  recalc() { this.tick.update((n) => n + 1); }

  lineTotal(lt: LineMeta, ln: QbLine): number {
    if (!lt.amount) return 0;
    if (lt.amount.includes('*')) {
      const [a, b] = lt.amount.split('*');
      return (Number(ln.values[a]) || 0) * (Number(ln.values[b]) || 0);
    }
    return Number(ln.values[lt.amount]) || 0;
  }

  addLine(lt: LineMeta) { this.lines.update((l) => [...l, { type: lt.key, values: {} }]); this.linesDirty = true; }
  removeLine(ln: QbLine) { this.lines.update((l) => l.filter((x) => x !== ln)); this.linesDirty = true; this.recalc(); }

  private clean(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(this.values)) if (v !== undefined && v !== '') out[k] = v;
    return out;
  }

  save() {
    const e = this.ent()!;
    const lines = this.lines().filter((l) => Object.values(l.values).some((v) => v !== null && v !== undefined && v !== ''));
    this.busy.set(true);
    const req = this.isNew()
      ? this.portal.create(e.key, this.clean(), e.lines.length ? lines : null)
      : this.portal.update(e.key, this.detail()!.record.record_id, this.clean(), this.linesDirty ? lines : null);
    req.subscribe({
      next: (r) => this.done(r, true),
      error: (err) => { this.snack.open(errorText(err), 'OK'); this.busy.set(false); },
    });
  }

  act(kind: 'void' | 'delete') {
    const e = this.ent()!;
    if (!confirm(`${kind === 'void' ? 'Void' : 'Delete'} this ${e.label.toLowerCase()} in QuickBooks?`)) return;
    const id = this.detail()!.record.record_id;
    (kind === 'void' ? this.portal.void(e.key, id) : this.portal.remove(e.key, id)).subscribe({
      next: (r) => this.done(r, true),
      error: (err) => this.snack.open(errorText(err), 'OK'),
    });
  }

  canCreate(key: string) { return !!this.portal.entity(key)?.permissions.create; }

  print() {
    const r = this.detail()!.record;
    this.portal.pdf(r.entity, r.record_id).subscribe({ next: (b) => openBlob(b), error: (e) => this.snack.open(errorText(e), 'OK') });
  }

  email() {
    const to = prompt('Send to (e-mail addresses, comma separated)');
    if (!to) return;
    const r = this.detail()!.record;
    this.portal.email(r.entity, r.record_id, to.split(',').map((x) => x.trim()).filter(Boolean), null).subscribe({
      next: (res) => this.snack.open(res.message, 'OK', { duration: 4000 }),
      error: (e) => this.snack.open(errorText(e), 'OK'),
    });
  }

  /** Open a new invoice / item receipt pre-filled from this estimate, sales order or purchase order. */
  copyTo(target: string) {
    const d = this.detail()!;
    const party = target === 'item_receipt' ? 'VendorRef' : 'CustomerRef';
    const values: Record<string, any> = { [party]: d.form.values[party], Memo: `From ${this.ent()!.label} ${d.record.name ?? ''}`.trim() };
    for (const k of ['ClassRef', 'BillAddress', 'ShipAddress', 'PONumber', 'TermsRef']) if (d.form.values[k]) values[k] = d.form.values[k];
    const lines = d.form.lines.map((l) => {
      const v = { ...l.values };
      if (target === 'item_receipt') { v['Cost'] = v['Rate']; delete v['Rate']; }
      return { type: 'item', values: v };
    });
    this.router.navigate(['/qb', target, 'new'], { state: { copy: { values, lines } } });
  }

  /** QuickBooks converts the item receipt into a bill when the bill links to it. */
  toBill() {
    const d = this.detail()!;
    this.router.navigate(['/qb', 'bill', 'new'], { state: { copy: {
      values: { VendorRef: d.form.values['VendorRef'], LinkToTxnID: d.record.qb_id, Memo: `Item receipt ${d.record.name ?? ''}`.trim() },
      lines: [] } } });
  }

  upload(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (!f) return;
    const r = this.detail()!.record;
    this.uploading.set(true);
    this.portal.upload(r.entity, r.record_id, f).subscribe({
      next: (a) => { this.attachments.update((l) => [a, ...l]); this.uploading.set(false); },
      error: (e) => { this.snack.open(errorText(e), 'OK'); this.uploading.set(false); },
    });
  }

  openAttachment(a: Attachment) {
    this.portal.attachmentBlob(a.attachment_id).subscribe((b) =>
      openBlob(b, a.content_type.includes('pdf') || a.content_type.startsWith('image/') ? undefined : a.filename));
  }

  removeAttachment(a: Attachment) {
    if (!confirm(`Delete ${a.filename}?`)) return;
    this.portal.deleteAttachment(a.attachment_id).subscribe({
      next: () => this.attachments.update((l) => l.filter((x) => x !== a)),
      error: (e) => this.snack.open(errorText(e), 'OK'),
    });
  }

  private done(r: WriteResult, back: boolean) {
    this.busy.set(false);
    this.snack.open(r.message, 'OK', { duration: 5000 });
    if (back) this.router.navigate(['/qb', this.ent()!.key]);
  }
}
