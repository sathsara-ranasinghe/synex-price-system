import { BreakpointObserver } from '@angular/cdk/layout';
import { DatePipe } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { ApiService } from '../core/api.service';
import { AuthService, PERM } from '../core/auth';
import { SyncStatus } from '../core/models';
import { CompanyService } from '../core/company.service';
import { PortalService } from '../core/portal.service';
import { Theme, UiService } from '../core/ui.service';
import { CommandPaletteComponent, PaletteLink } from './command-palette.component';

interface NavLink { path: string; label: string; perm?: string; exact?: boolean }
interface NavGroup { key: string; label: string; icon: string; links: NavLink[] }

const MODULE_ICONS: Record<string, string> = {
  sales: 'point_of_sale', purchasing: 'shopping_cart', banking: 'account_balance', accounting: 'calculate',
  inventory: 'inventory_2', lists: 'category',
};

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [DatePipe, RouterOutlet, RouterLink, RouterLinkActive, MatSidenavModule, MatIconModule, MatButtonModule,
    MatBadgeModule, MatMenuModule, MatTooltipModule, CommandPaletteComponent],
  template: `
    <mat-sidenav-container class="container">
      <mat-sidenav [mode]="mobile() ? 'over' : 'side'" [opened]="!mobile()" #nav class="sidenav">
        <nav class="nav" aria-label="Main">
          <a class="brand" routerLink="/" (click)="mobile() && nav.close()">
            <img class="logo" src="logo-white.png" alt="Synex Group" width="52" height="52" />
            <span class="divider" aria-hidden="true"></span>
            <span class="brand-text"><strong>QB Portal</strong><small>Synex Group</small></span>
          </a>

          <div class="scroll-area">
            <a class="item top" routerLink="/" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }"
               (click)="mobile() && nav.close()">
              <mat-icon>space_dashboard</mat-icon><span>Home</span></a>

            @for (g of groups(); track g.key) {
              <button class="group" (click)="toggle(g.key)" [class.open]="isOpen(g.key)" [attr.aria-expanded]="isOpen(g.key)">
                <mat-icon>{{ g.icon }}</mat-icon><span>{{ g.label }}</span>
                <mat-icon class="chev">expand_more</mat-icon>
              </button>
              @if (isOpen(g.key)) {
                <div class="sub">
                  @for (l of g.links; track l.path) {
                    <a class="item" [routerLink]="l.path" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: !!l.exact }"
                       (click)="mobile() && nav.close()">{{ l.label }}</a>
                  }
                </div>
              }
            }
          </div>

          <button class="me" [matMenuTriggerFor]="userMenu">
            <span class="avatar">{{ initials() }}</span>
            <span class="who"><strong>{{ auth.me()?.full_name || auth.me()?.username }}</strong><small>{{ auth.me()?.role }}</small></span>
            <mat-icon>unfold_more</mat-icon>
          </button>
        </nav>
      </mat-sidenav>

      <mat-sidenav-content class="main">
        <header class="topbar">
          @if (mobile()) { <button mat-icon-button (click)="nav.toggle()" aria-label="Menu"><mat-icon>menu</mat-icon></button> }
          @if (companies.current(); as cur) {
            <button class="company" [matMenuTriggerFor]="companyMenu" [disabled]="companies.mine().length < 2"
                    [attr.aria-label]="'Company: ' + cur.name">
              <span class="co-ic"><mat-icon>domain</mat-icon></span>
              <span class="co-txt"><small>Company</small><strong>{{ cur.name }}</strong></span>
              @if (companies.mine().length > 1) { <mat-icon class="chev">expand_more</mat-icon> }
            </button>
            <mat-menu #companyMenu="matMenu">
              @for (c of companies.mine(); track c.company_id) {
                <button mat-menu-item (click)="companies.switchTo(c.company_id)">
                  <mat-icon>{{ c.company_id === cur.company_id ? 'check' : '' }}</mat-icon>{{ c.name }}</button>
              }
            </mat-menu>
          }
          <button class="find" (click)="ui.paletteOpen.set(true)" aria-label="Search (Ctrl+K)">
            <mat-icon>search</mat-icon><span class="find-txt">Search anything…</span>
            <span class="keys"><kbd>Ctrl</kbd><kbd>K</kbd></span>
          </button>
          <span class="spacer"></span>
          @if (sync(); as s) {
            <a class="sync" routerLink="/sync" [class.bad]="syncBad()"
               [matTooltip]="s.last_success ? 'Last QuickBooks sync ' + (s.last_success.started_at | date: 'medium') : 'Never synced'">
              <span class="dot"></span>
              <span class="sync-txt">{{ s.running ? 'Syncing…' : s.last_success ? 'Synced ' + ago(s.last_success.started_at) : 'Not synced' }}</span>
            </a>
          }
          <a mat-icon-button routerLink="/notifications" aria-label="Notifications">
            <mat-icon [matBadge]="unread() || null" matBadgeColor="warn" matBadgeSize="small">notifications</mat-icon>
          </a>
        </header>
        <main class="content"><router-outlet /></main>
      </mat-sidenav-content>
    </mat-sidenav-container>

    <mat-menu #userMenu="matMenu" xPosition="after" yPosition="above">
      <div class="menu-head">{{ auth.me()?.email }}</div>
      <a mat-menu-item routerLink="/account"><mat-icon>manage_accounts</mat-icon>Account &amp; security</a>
      <button mat-menu-item [matMenuTriggerFor]="themeMenu"><mat-icon>{{ themeIcon() }}</mat-icon>Appearance</button>
      <button mat-menu-item (click)="auth.logout()"><mat-icon>logout</mat-icon>Sign out</button>
    </mat-menu>
    <mat-menu #themeMenu="matMenu">
      @for (t of themes; track t.key) {
        <button mat-menu-item (click)="ui.setTheme(t.key)">
          <mat-icon>{{ t.icon }}</mat-icon>{{ t.label }}
          @if (ui.theme() === t.key) { <mat-icon class="tick">check</mat-icon> }
        </button>
      }
    </mat-menu>

    @if (ui.paletteOpen()) { <app-command-palette [links]="paletteLinks()" [newLinks]="newLinks()" /> }
  `,
  styles: [`
    .container { height: 100vh; background: var(--bg); }
    .sidenav { width: 264px; border: 0; border-radius: 0; background: var(--nav-bg); --mat-sidenav-container-shape: 0; }
    .nav { height: 100%; display: flex; flex-direction: column; color: var(--nav-text);
      background: linear-gradient(180deg, var(--nav-bg-2) 0%, var(--nav-bg) 40%); }

    .brand { display: flex; gap: 14px; align-items: center; margin: 0 12px 10px; padding: 18px 8px 16px; color: #fff;
      border-bottom: 1px solid rgba(255, 255, 255, .08); }
    .divider { width: 1px; height: 34px; background: rgba(255, 255, 255, .18); }
    .logo { width: 52px; height: 52px; flex: none; object-fit: contain; }
    .brand-text { display: flex; flex-direction: column; line-height: 1.15; }
    .brand-text strong { font-size: 16px; letter-spacing: -0.01em; }
    .brand-text small { color: var(--nav-muted); font-size: 12px; }

    .scroll-area { flex: 1; overflow-y: auto; padding: 4px 12px 12px; scrollbar-color: #253047 transparent; }
    .group, .item { display: flex; align-items: center; gap: 12px; width: 100%; border: 0; background: none; cursor: pointer;
      font: inherit; text-align: left; color: var(--nav-text); border-radius: 8px; transition: background .12s, color .12s; }
    .group { padding: 9px 10px; margin-top: 6px; font-weight: 500; font-size: 13.5px; }
    .group span { flex: 1; }
    .group mat-icon, .item.top mat-icon { font-size: 19px; width: 19px; height: 19px; color: var(--nav-muted); }
    .group .chev { transition: transform .15s; }
    .group.open .chev { transform: rotate(180deg); }
    .group:hover, .item:hover { background: rgba(255, 255, 255, .05); color: #fff; }
    .item.top { padding: 9px 10px; font-weight: 500; font-size: 13.5px; }
    .sub { position: relative; margin: 2px 0 6px 19px; padding-left: 12px; border-left: 1px solid #1f2a3f; }
    .sub .item { padding: 6px 10px; font-size: 13px; color: #9aa6ba; }
    .item.active { background: rgba(96, 140, 255, .14); color: #fff; font-weight: 600; }
    .sub .item { position: relative; }
    .sub .item.active::before { content: ''; position: absolute; left: -13px; top: 7px; width: 2px; height: 22px; border-radius: 2px;
      background: #60a5fa; }
    .item.top.active mat-icon { color: #93c5fd; }

    .me { display: flex; align-items: center; gap: 10px; margin: 8px 12px 14px; padding: 10px; border-radius: 10px;
      border: 1px solid #1d2638; background: rgba(255, 255, 255, .03); color: var(--nav-text); cursor: pointer; font: inherit; text-align: left; }
    .me:hover { background: rgba(255, 255, 255, .06); }
    .avatar { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; font-size: 12px;
      color: #fff; background: linear-gradient(135deg, #0ea5e9, #6366f1); flex: none; }
    .who { flex: 1; display: flex; flex-direction: column; line-height: 1.2; min-width: 0; }
    .who strong { color: #fff; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .who small { color: var(--nav-muted); font-size: 11.5px; text-transform: capitalize; }
    .me mat-icon { color: var(--nav-muted); font-size: 18px; width: 18px; height: 18px; }

    .topbar { position: sticky; top: 0; z-index: 3; height: 56px; display: flex; align-items: center; gap: 6px; padding: 0 20px;
      background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: saturate(160%) blur(10px);
      border-bottom: 1px solid var(--line); }
    .spacer { flex: 1; }
    .sync { display: inline-flex; align-items: center; gap: 8px; height: 30px; padding: 0 12px; border-radius: 999px; font-size: 12.5px;
      font-weight: 500; color: var(--text-2); background: var(--surface); border: 1px solid var(--line); margin-right: 4px;
      white-space: nowrap; }
    .sync .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); }
    .sync.bad .dot { background: var(--warn); box-shadow: 0 0 0 3px var(--warn-soft); }
    .content { padding: 28px 32px 48px; max-width: 1440px; margin: 0 auto; }
    .find { display: flex; align-items: center; gap: 8px; height: 38px; min-width: 280px; margin-left: 10px; padding: 0 8px 0 12px;
      border: 1px solid var(--line); border-radius: 10px; background: var(--surface); color: var(--muted); font: inherit;
      font-size: 13.5px; cursor: pointer; transition: border-color .15s, box-shadow .15s; }
    .find:hover { border-color: var(--line-strong); box-shadow: var(--shadow-sm); color: var(--text-2); }
    .find mat-icon { font-size: 19px; width: 19px; height: 19px; }
    .find-txt { flex: 1; text-align: left; }
    .keys { display: inline-flex; gap: 3px; }
    kbd { font: 11px/1 Inter, system-ui, sans-serif; padding: 3px 6px; border-radius: 5px; border: 1px solid var(--line-strong);
      border-bottom-width: 2px; color: var(--muted); background: var(--surface-2); }
    .tick { margin-left: auto; margin-right: 0 !important; color: var(--primary) !important; }
    @media (max-width: 600px) { .sync-txt { display: none; } .sync { padding: 0 11px; } }
    @media (max-width: 900px) { .find { min-width: 0; } .find-txt, .keys { display: none; } }
    .menu-head { padding: 10px 16px 6px; color: var(--muted); font-size: 12.5px; }
    .company { display: flex; align-items: center; gap: 10px; height: 40px; padding: 0 10px 0 6px; border-radius: 10px;
      border: 1px solid var(--line); background: var(--surface); color: var(--text); font: inherit; cursor: pointer; }
    .company:disabled { cursor: default; }
    .company:not(:disabled):hover { border-color: var(--line-strong); box-shadow: var(--shadow-sm); }
    .co-ic { width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; background: var(--primary-soft); color: var(--primary); }
    .co-ic mat-icon { font-size: 18px; width: 18px; height: 18px; }
    .co-txt { display: flex; flex-direction: column; line-height: 1.1; text-align: left; }
    .co-txt small { color: var(--muted); font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em; }
    .co-txt strong { font-size: 13.5px; }
    .company .chev { color: var(--muted); }
    @media (max-width: 600px) { .content { padding: 18px 16px 40px; } .topbar { padding: 0 8px; } }
  `],
})
export class ShellComponent implements OnInit, OnDestroy {
  auth = inject(AuthService);
  private api = inject(ApiService);
  private portal = inject(PortalService);
  companies = inject(CompanyService);
  ui = inject(UiService);
  themes: { key: Theme; label: string; icon: string }[] = [
    { key: 'auto', label: 'Match my computer', icon: 'brightness_auto' },
    { key: 'light', label: 'Light', icon: 'light_mode' },
    { key: 'dark', label: 'Dark', icon: 'dark_mode' },
  ];
  themeIcon = computed(() => this.themes.find((t) => t.key === this.ui.theme())?.icon ?? 'brightness_auto');
  mobile = toSignal(inject(BreakpointObserver).observe('(max-width: 900px)').pipe(map((r) => r.matches)), { initialValue: false });
  unread = signal(0);
  sync = signal<SyncStatus | null>(null);
  private open = signal<Set<string>>(this.loadOpen());
  private timer?: ReturnType<typeof setInterval>;

  initials = computed(() => {
    const n = (this.auth.me()?.full_name || this.auth.me()?.username || '?').trim();
    return n.split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase();
  });

  syncBad = computed(() => {
    const s = this.sync();
    if (!s?.last_success) return true;
    return Date.now() - new Date(s.last_success.started_at).getTime() > 3 * 3600_000;
  });

  groups = computed<NavGroup[]>(() => {
    const perms = new Set(this.auth.me()?.permissions ?? []);
    const has = (p?: string) => !p || perms.has(p);
    const meta = this.portal.meta();
    const out: NavGroup[] = [];

    for (const m of meta?.modules ?? []) {
      const ents = (meta?.entities ?? []).filter((e) => e.module === m.key);
      if (!ents.length) continue;
      out.push({ key: m.key, label: m.label, icon: MODULE_ICONS[m.key] ?? 'folder',
        links: ents.map((e) => ({ path: `/qb/${e.key}`, label: e.plural })) });
    }
    const qb: NavLink[] = [
      { path: '/qb-reports', label: 'Reports', perm: 'reports.view' },
      { path: '/qb-changes', label: 'Changes & approvals' },
      { path: '/sync', label: 'Sync status', perm: PERM.sync },
    ].filter((l) => has(l.perm));
    out.push({ key: 'quickbooks', label: 'QuickBooks', icon: 'sync_alt', links: qb });
    const admin = [
      { path: '/companies', label: 'Companies', perm: PERM.users },
      { path: '/users', label: 'Users', perm: PERM.users },
      { path: '/roles', label: 'Roles & permissions', perm: PERM.users },
      { path: '/audit', label: 'Audit log', perm: PERM.audit },
    ].filter((l) => has(l.perm));
    if (admin.length) out.push({ key: 'admin', label: 'Administration', icon: 'admin_panel_settings', links: admin });
    return out;
  });

  /** Every page the user can open, for the Ctrl+K search. */
  paletteLinks = computed<PaletteLink[]>(() => {
    const out: PaletteLink[] = [{ path: '/', label: 'Home', group: 'Dashboard', icon: 'space_dashboard', keywords: 'dashboard start' }];
    for (const g of this.groups()) {
      for (const l of g.links) out.push({ path: l.path, label: l.label, group: g.label, icon: g.icon });
    }
    out.push({ path: '/account', label: 'Account & security', group: 'You', icon: 'manage_accounts',
      keywords: 'password two-step 2fa authenticator profile' });
    out.push({ path: '/notifications', label: 'Notifications', group: 'You', icon: 'notifications' });
    return out;
  });

  /** "New invoice", "New customer"... for every entity the user may create. */
  newLinks = computed<PaletteLink[]>(() => (this.portal.meta()?.entities ?? [])
    .filter((e) => e.can_add && e.permissions.create)
    .map((e) => ({ path: `/qb/${e.key}/new`, label: `New ${e.label.toLowerCase()}`, group: 'Create', icon: 'add',
      keywords: `add create ${e.plural}` })));

  @HostListener('document:keydown', ['$event'])
  hotkey(e: KeyboardEvent) {
    const typing = (e.target as HTMLElement | null)?.closest?.('input, textarea, select, [contenteditable="true"]');
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      this.ui.paletteOpen.set(!this.ui.paletteOpen());
    } else if (e.key === '/' && !typing && !this.ui.paletteOpen()) {
      e.preventDefault();
      this.ui.paletteOpen.set(true);
    }
  }

  ngOnInit() {
    this.companies.load().then(() => this.portal.load());
    const poll = () => {
      this.api.unreadCount().subscribe((r) => this.unread.set(r.count));
      this.api.syncStatus().pipe(catchError(() => of(null))).subscribe((s) => this.sync.set(s));
    };
    poll();
    this.timer = setInterval(poll, 60_000);
  }

  ngOnDestroy() { clearInterval(this.timer); }

  ago(iso: string): string {
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (min < 1) return 'just now';
    if (min < 60) return `${min} min ago`;
    const h = Math.round(min / 60);
    return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
  }

  isOpen(key: string) { return this.open().has(key); }
  toggle(key: string) {
    this.open.update((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; });
    try { localStorage.setItem('synex_nav', JSON.stringify([...this.open()])); } catch { /* ignore */ }
  }
  private loadOpen(): Set<string> {
    try { return new Set(JSON.parse(localStorage.getItem('synex_nav') ?? '["sales","quickbooks"]')); }
    catch { return new Set(['sales', 'quickbooks']); }
  }
}
