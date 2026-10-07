import { DatePipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../core/api.service';
import { errorText } from '../core/auth';
import { Company, CompanyService } from '../core/company.service';
import { User } from '../core/models';

@Component({
  selector: 'app-users',
  standalone: true,
  imports: [DatePipe, FormsModule, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule, MatSelectModule,
    MatSlideToggleModule],
  template: `
    <div class="head"><h1>Users</h1><span class="spacer"></span>
      <button mat-flat-button color="primary" (click)="startNew()"><mat-icon>person_add</mat-icon> New user</button></div>

    @if (form(); as f) {
      <section class="panel form">
        <h2>{{ f.user_id ? 'Edit ' + f.username : 'New user' }}</h2>
        <div class="row">
          <mat-form-field><mat-label>Username</mat-label><input matInput [(ngModel)]="f.username" [disabled]="!!f.user_id" /></mat-form-field>
          <mat-form-field><mat-label>Full name</mat-label><input matInput [(ngModel)]="f.full_name" /></mat-form-field>
          <mat-form-field><mat-label>Email</mat-label><input matInput type="email" [(ngModel)]="f.email" /></mat-form-field>
        </div>
        <div class="row">
          <mat-form-field><mat-label>Role</mat-label>
            <mat-select [(ngModel)]="f.role_name">
              @for (r of roles(); track r.role_name) { <mat-option [value]="r.role_name">{{ r.role_name }}</mat-option> }
            </mat-select>
          </mat-form-field>
          <mat-form-field><mat-label>Companies</mat-label>
            <mat-select multiple [(ngModel)]="f.company_ids" [disabled]="f.role_name === 'admin'">
              @for (c of companies(); track c.company_id) { <mat-option [value]="c.company_id">{{ c.name }}</mat-option> }
            </mat-select>
          </mat-form-field>
          <mat-form-field><mat-label>{{ f.user_id ? 'New password (leave blank to keep)' : 'Password' }}</mat-label>
            <input matInput type="password" [(ngModel)]="f.password" minlength="8" /></mat-form-field>
        </div>
        <div class="row toggles">
          <mat-slide-toggle [(ngModel)]="f.receive_alerts">Receive price alerts</mat-slide-toggle>
          @if (f.user_id) { <mat-slide-toggle [(ngModel)]="f.is_active">Active</mat-slide-toggle> }
        </div>
        <div class="actions">
          <button mat-button (click)="form.set(null)">Cancel</button>
          <button mat-flat-button color="primary" (click)="save()">Save</button>
        </div>
      </section>
    }

    <div class="panel flush scroll">
      <table class="simple">
        <tr><th>Username</th><th>Name</th><th>Email</th><th>Role</th><th>Companies</th><th>Status</th><th>Created</th><th></th></tr>
        @for (u of users(); track u.user_id) {
          <tr>
            <td>{{ u.username }}</td><td>{{ u.full_name }}</td><td>{{ u.email }}</td><td>{{ u.role_name }}</td>
            <td class="small">{{ u.role_name === 'admin' ? 'All' : companyNames(u.company_ids) }}</td>
            <td><span class="tag" [class.ok]="u.is_active" [class.bad]="!u.is_active">{{ u.is_active ? 'active' : 'disabled' }}</span></td>
            <td>{{ u.created_at | date: 'mediumDate' }}</td>
            <td><button mat-icon-button (click)="edit(u)" aria-label="Edit"><mat-icon>edit</mat-icon></button></td>
          </tr>
        }
      </table>
    </div>
    <p class="muted small">Users only see the companies ticked for them; admins see every company.
      What they can do in each module comes from their role (Administration → Roles &amp; permissions).</p>
  `,
  styles: [`.form { margin-bottom: 16px; } .row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
    .row mat-form-field { flex: 1; min-width: 200px; } .toggles { gap: 24px; }
    .actions { display: flex; justify-content: flex-end; gap: 8px; } .small { font-size: 12px; }`],
})
export class UsersComponent implements OnInit {
  private api = inject(ApiService);
  private snack = inject(MatSnackBar);
  users = signal<User[]>([]);
  roles = signal<{ role_name: string }[]>([]);
  companies = signal<Company[]>([]);
  private companySvc = inject(CompanyService);
  form = signal<(Partial<User> & { password?: string }) | null>(null);

  ngOnInit() {
    this.load();
    this.api.roles().subscribe((r) => this.roles.set(r));
    this.companySvc.all().subscribe((c) => this.companies.set(c));
  }
  load() { this.api.users().subscribe((u) => this.users.set(u)); }

  startNew() {
    const first = this.companies()[0]?.company_id;
    this.form.set({ username: '', full_name: '', email: '', role_name: 'viewer', receive_alerts: true, password: '',
      company_ids: first ? [first] : [] });
  }
  companyNames(ids: number[]) {
    return ids.map((id) => this.companies().find((c) => c.company_id === id)?.name).filter(Boolean).join(', ') || '—';
  }
  edit(u: User) { this.form.set({ ...u, password: '' }); }

  save() {
    const f = this.form()!;
    const body: Record<string, unknown> = { full_name: f.full_name, email: f.email, role_name: f.role_name,
      receive_alerts: f.receive_alerts, company_ids: f.company_ids ?? [] };
    if (f.password) body['password'] = f.password;
    const req = f.user_id
      ? this.api.updateUser(f.user_id, { ...body, is_active: f.is_active })
      : this.api.createUser({ ...body, username: f.username });
    req.subscribe({
      next: () => { this.form.set(null); this.load(); this.snack.open('Saved', '', { duration: 2000 }); },
      error: (e) => this.snack.open(errorText(e), 'OK'),
    });
  }
}
