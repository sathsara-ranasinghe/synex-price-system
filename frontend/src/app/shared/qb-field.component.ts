import { NgTemplateOutlet } from '@angular/common';
import { Component, OnInit, computed, inject, input, model, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { Subject, debounceTime, switchMap } from 'rxjs';
import { FieldMeta, RefOption } from '../core/models';
import { PortalService } from '../core/portal.service';
import { HumanizePipe } from './shared';

type Ref = { ListID?: string; FullName?: string | null } | null;
const ADDRESS = [['Addr1', 'Address line 1'], ['Addr2', 'Address line 2'], ['City', 'City'],
  ['State', 'State / province'], ['PostalCode', 'Postal code'], ['Country', 'Country']];

/** One editor for any registry field type. `compact` = used inside line tables (no labels). */
@Component({
  selector: 'qb-field',
  standalone: true,
  imports: [NgTemplateOutlet, HumanizePipe, FormsModule, MatFormFieldModule, MatInputModule, MatSelectModule, MatCheckboxModule, MatAutocompleteModule],
  template: `
    @switch (field().type) {
      @case ('bool') {
        <mat-checkbox [ngModel]="value() === true || value() === 'true'" (ngModelChange)="value.set($event)" [disabled]="disabled()">
          {{ field().label }}</mat-checkbox>
      }
      @case ('address') {
        <fieldset class="addr" [disabled]="disabled()">
          <legend>{{ field().label }}</legend>
          @for (p of addressParts; track p[0]) {
            <mat-form-field [class.wide]="p[0].startsWith('Addr')">
              <mat-label>{{ p[1] }}</mat-label>
              <input matInput maxlength="41" [ngModel]="addr()[p[0]] ?? ''" (ngModelChange)="setAddr(p[0], $event)" [disabled]="disabled()" />
            </mat-form-field>
          }
        </fieldset>
      }
      @case ('enum') {
        <mat-form-field [class.compact]="compact()">
          @if (!compact()) { <mat-label>{{ field().label }}</mat-label> }
          <mat-select [ngModel]="value()" (ngModelChange)="value.set($event)" [disabled]="disabled()" [required]="field().required">
            <mat-option [value]="null">—</mat-option>
            @for (o of field().options; track o) { <mat-option [value]="o">{{ o | humanize }}</mat-option> }
          </mat-select>
        </mat-form-field>
      }
      @case ('ref') { <ng-container *ngTemplateOutlet="picker" /> }
      @case ('txnref') { <ng-container *ngTemplateOutlet="picker" /> }
      @default {
        <mat-form-field [class.compact]="compact()" [class.wide]="field().type === 'text' && !compact()">
          @if (!compact()) { <mat-label>{{ field().label }}</mat-label> }
          @if (field().type === 'text' && !compact()) {
            <textarea matInput rows="2" [ngModel]="value() ?? ''" (ngModelChange)="value.set($event)" [disabled]="disabled()"
                      [attr.maxlength]="field().max" [required]="field().required"></textarea>
          } @else {
            <input matInput [type]="inputType()" [ngModel]="value() ?? ''" (ngModelChange)="value.set($event)" [disabled]="disabled()"
                   [attr.maxlength]="field().max" [required]="field().required" [attr.step]="field().type === 'int' ? 1 : 'any'" [attr.min]="field().min"
                   [attr.aria-label]="field().label" />
          }
        </mat-form-field>
      }
    }

    <ng-template #picker>
      <mat-form-field [class.compact]="compact()" class="picker">
        @if (!compact()) { <mat-label>{{ field().label }}</mat-label> }
        <input matInput [ngModel]="text()" (ngModelChange)="onType($event)" [matAutocomplete]="auto" [disabled]="disabled()"
               [required]="field().required" [attr.aria-label]="field().label" (focus)="onFocus()" />
        <mat-autocomplete #auto (optionSelected)="pick($event.option.value)">
          @for (o of options(); track o.ListID) { <mat-option [value]="o">{{ o.label }}</mat-option> }
        </mat-autocomplete>
      </mat-form-field>
    </ng-template>
  `,
  styles: [`
    :host { display: contents; }
    mat-form-field { width: 100%; }
    .compact { min-width: 90px; }
    .compact ::ng-deep .mat-mdc-form-field-infix { padding-top: 8px !important; padding-bottom: 8px !important; min-height: 36px; }
    .addr { grid-column: span 2; min-width: 0; border: 1px solid var(--line); border-radius: 10px; padding: 6px 12px 12px;
      margin: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; background: var(--surface-2); }
    @media (max-width: 700px) { .addr { grid-column: 1 / -1; } }
    .addr legend { color: var(--muted); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; padding: 0 4px; }
    .addr .wide { grid-column: 1 / -1; }
    .wide { grid-column: 1 / -1; }
  `],
})
export class QbFieldComponent implements OnInit {
  field = input.required<FieldMeta>();
  value = model<any>();
  disabled = input(false);
  compact = input(false);
  partyId = input<string | null>(null);  // limits txnref pickers (e.g. bills of one vendor)

  private portal = inject(PortalService);
  addressParts = ADDRESS;
  options = signal<RefOption[]>([]);
  search$ = new Subject<string>();
  private typed = signal<string | null>(null);

  addr = computed(() => (this.value() && typeof this.value() === 'object' ? this.value() : {}) as Record<string, string>);
  text = computed(() => {
    if (this.typed() !== null) return this.typed();
    const v = this.value();
    if (!v) return '';
    if (typeof v === 'string') return v;
    return (v as Ref)?.FullName ?? (v as Ref)?.ListID ?? '';
  });
  inputType = computed(() => {
    const t = this.field().type;
    return t === 'date' ? 'date' : ['int', 'decimal', 'money'].includes(t) ? 'number' : 'text';
  });

  ngOnInit() {
    this.search$.pipe(debounceTime(200), switchMap((q) => this.portal.options(this.field().ref!, q ?? '',
      this.field().type === 'txnref' ? this.partyId() : null)))  // only bills / invoices are limited to the chosen party
      .subscribe((o) => this.options.set(o));
  }

  onFocus() { this.search$.next(this.typed() ?? ''); }

  onType(t: string) {
    this.typed.set(t);
    if (!t) this.value.set(null);
    this.search$.next(t);
  }

  pick(o: RefOption) {
    this.typed.set(null);
    this.value.set(this.field().type === 'txnref' ? o.ListID : { ListID: o.ListID, FullName: o.FullName });
    if (this.field().type === 'txnref') this.typed.set(o.label);
  }

  setAddr(part: string, v: string) {
    this.value.set({ ...this.addr(), [part]: v || undefined });
  }
}
