import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar } from '@angular/material/snack-bar';
import { errorText } from '../core/auth';
import { PortalService } from '../core/portal.service';

@Component({
  selector: 'app-roles',
  standalone: true,
  imports: [FormsModule, MatButtonModule, MatCheckboxModule, MatFormFieldModule, MatIconModule, MatInputModule],
  template: `
    <div class="head"><h1>Roles &amp; permissions</h1></div>
    <div class="layout">
      <section class="panel flush">
        @for (r of roles(); track r.role_name) {
          <button class="role" [class.sel]="r.role_name === sel()" (click)="pick(r.role_name)">
            {{ r.role_name }} <span class="muted">{{ r.permissions.length }}</span></button>
        }
        <div class="new">
          <mat-form-field><mat-label>New role name</mat-label><input matInput [(ngModel)]="newName" placeholder="e.g. design_team" /></mat-form-field>
          <button mat-stroked-button [disabled]="!newName" (click)="create()"><mat-icon>add</mat-icon> Add</button>
        </div>
      </section>

      <section class="panel">
        @if (sel(); as name) {
          <div class="head">
            <h2>{{ name }}</h2><span class="spacer"></span>
            @if (name !== 'admin') {
              <button mat-button (click)="remove(name)"><mat-icon>delete</mat-icon> Delete role</button>
              <button mat-flat-button color="primary" (click)="save(name)">Save</button>
            }
          </div>
          @if (name === 'admin') { <p class="muted">The admin role always has every permission.</p> }
          <p class="muted small"><strong>Write without approval</strong> sends this role's changes straight to QuickBooks.
            Without it, changes wait on the QuickBooks changes page for someone with <strong>Approve changes</strong>.</p>
          <div class="groups">
            @for (g of catalog(); track g.group) {
              <div class="group">
                <h3>{{ g.group }}</h3>
                @for (p of g.permissions; track p.key) {
                  <mat-checkbox [checked]="perms().has(p.key)" [disabled]="name === 'admin'" (change)="toggle(p.key)">{{ p.label }}</mat-checkbox>
                }
              </div>
            }
          </div>
        } @else { <p class="muted">Pick a role.</p> }
      </section>
    </div>
  `,
  styles: [`
    .layout { display: grid; grid-template-columns: 240px 1fr; gap: 16px; } @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
    .role { display: flex; justify-content: space-between; width: 100%; padding: 12px 16px; border: 0; border-bottom: 1px solid var(--line);
      background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; }
    .role.sel { background: var(--primary-soft); font-weight: 600; }
    .new { padding: 12px 16px; display: flex; flex-direction: column; gap: 8px; }
    .groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }
    .group { display: flex; flex-direction: column; } .group h3 { font-size: 14px; margin: 0 0 4px; }
    .small { font-size: 12px; }
  `],
})
export class RolesComponent implements OnInit {
  private portal = inject(PortalService);
  private snack = inject(MatSnackBar);
  roles = signal<{ role_name: string; permissions: string[] }[]>([]);
  catalog = signal<{ group: string; permissions: { key: string; label: string }[] }[]>([]);
  sel = signal<string | null>(null);
  perms = signal(new Set<string>());
  newName = '';

  ngOnInit() {
    this.portal.permissionCatalog().subscribe((c) => this.catalog.set(c));
    this.load();
  }

  load(select?: string) {
    this.portal.roles().subscribe((r) => {
      this.roles.set(r);
      this.pick(select ?? this.sel() ?? r[0]?.role_name);
    });
  }

  pick(name: string | undefined) {
    if (!name) return;
    this.sel.set(name);
    this.perms.set(new Set(this.roles().find((r) => r.role_name === name)?.permissions ?? []));
  }

  toggle(key: string) {
    this.perms.update((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  }

  private ok(msg: string, select?: string) {
    return { next: () => { this.snack.open(msg, '', { duration: 2000 }); this.load(select); },
      error: (e: unknown) => this.snack.open(errorText(e), 'OK') };
  }

  save(name: string) { this.portal.updateRole(name, [...this.perms()]).subscribe(this.ok('Role saved')); }
  create() {
    const name = this.newName.trim().toLowerCase().replace(/\s+/g, '_');
    this.portal.createRole(name, []).subscribe(this.ok('Role created', name));
    this.newName = '';
  }
  remove(name: string) {
    if (!confirm(`Delete role ${name}?`)) return;
    this.sel.set(null);
    this.portal.deleteRole(name).subscribe(this.ok('Role deleted'));
  }
}
