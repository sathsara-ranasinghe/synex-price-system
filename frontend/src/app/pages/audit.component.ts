import { DatePipe, JsonPipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatSelectModule } from '@angular/material/select';
import { ApiService } from '../core/api.service';
import { AuditEntry } from '../core/models';

@Component({
  selector: 'app-audit',
  standalone: true,
  imports: [DatePipe, JsonPipe, FormsModule, MatFormFieldModule, MatSelectModule, MatPaginatorModule],
  template: `
    <div class="head"><h1>Audit log</h1></div>
    <div class="filters">
      <mat-form-field>
        <mat-label>Entity</mat-label>
        <mat-select [(ngModel)]="entity" (selectionChange)="page = 1; load()">
          <mat-option [value]="null">All</mat-option>
          @for (e of entities; track e) { <mat-option [value]="e">{{ e }}</mat-option> }
        </mat-select>
      </mat-form-field>
    </div>
    <div class="panel flush">
      <div class="scroll">
        <table class="simple">
          <tr><th>When</th><th>User</th><th>Entity</th><th>Action</th><th>Change</th></tr>
          @for (a of rows(); track a.audit_id) {
            <tr>
              <td>{{ a.created_at | date: 'short' }}</td><td>{{ a.username }}</td>
              <td>{{ a.entity }} {{ a.entity_id ? '#' + a.entity_id : '' }}</td><td>{{ a.action }}</td>
              <td class="diff">
                @for (k of keys(a); track k) {
                  <div><strong>{{ k }}</strong>: <span class="old">{{ a.old_value?.[k] ?? '' }}</span> → <span>{{ a.new_value?.[k] ?? '' }}</span></div>
                }
              </td>
            </tr>
          }
        </table>
      </div>
      <mat-paginator [length]="total()" [pageIndex]="page - 1" [pageSize]="50" (page)="onPage($event)" />
    </div>
  `,
  styles: [`.diff { font-size: 12px; max-width: 520px; word-break: break-word; } .old { color: var(--muted); text-decoration: line-through; }
    .filters mat-form-field { width: 200px; }`],
})
export class AuditComponent implements OnInit {
  private api = inject(ApiService);
  entities = ['supplier', 'item', 'supplier_item', 'price_approval', 'user', 'sync'];
  entity: string | null = null;
  page = 1;
  rows = signal<AuditEntry[]>([]);
  total = signal(0);

  ngOnInit() { this.load(); }
  load() {
    this.api.audit({ entity: this.entity, page: this.page, page_size: 50 }).subscribe((p) => { this.rows.set(p.items); this.total.set(p.total); });
  }
  onPage(e: PageEvent) { this.page = e.pageIndex + 1; this.load(); }
  keys(a: AuditEntry) {
    return [...new Set([...Object.keys(a.old_value ?? {}), ...Object.keys(a.new_value ?? {})])]
      .filter((k) => !['updated_at', 'qb_edit_sequence'].includes(k)).slice(0, 12);
  }
}
