import { Routes } from '@angular/router';
import { PERM, authGuard } from './core/auth';
import { ShellComponent } from './layout/shell.component';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./pages/login.component').then((m) => m.LoginComponent) },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', loadComponent: () => import('./pages/portal-home.component').then((m) => m.PortalHomeComponent) },
      { path: 'qb/:entity', loadComponent: () => import('./pages/qb-list.component').then((m) => m.QbListComponent) },
      { path: 'qb/:entity/:id', loadComponent: () => import('./pages/qb-record.component').then((m) => m.QbRecordComponent) },
      { path: 'qb-reports', canActivate: [authGuard], data: { permission: 'reports.view' },
        loadComponent: () => import('./pages/qb-reports.component').then((m) => m.QbReportsComponent) },
      { path: 'qb-changes', loadComponent: () => import('./pages/qb-changes.component').then((m) => m.QbChangesComponent) },
      { path: 'sync', canActivate: [authGuard], data: { permission: PERM.sync },
        loadComponent: () => import('./pages/sync.component').then((m) => m.SyncComponent) },
      { path: 'companies', canActivate: [authGuard], data: { permission: PERM.users },
        loadComponent: () => import('./pages/companies.component').then((m) => m.CompaniesComponent) },
      { path: 'users', canActivate: [authGuard], data: { permission: PERM.users },
        loadComponent: () => import('./pages/users.component').then((m) => m.UsersComponent) },
      { path: 'roles', canActivate: [authGuard], data: { permission: PERM.users },
        loadComponent: () => import('./pages/roles.component').then((m) => m.RolesComponent) },
      { path: 'audit', canActivate: [authGuard], data: { permission: PERM.audit },
        loadComponent: () => import('./pages/audit.component').then((m) => m.AuditComponent) },
      { path: 'notifications', loadComponent: () => import('./pages/notifications.component').then((m) => m.NotificationsComponent) },
    ],
  },
  { path: '**', redirectTo: '' },
];
