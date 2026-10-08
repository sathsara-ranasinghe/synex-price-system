import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, firstValueFrom, map, of, throwError } from 'rxjs';
import { CompanyService } from './company.service';
import { Me } from './models';

const TOKEN_KEY = 'synex_token';

export const PERM = {
  sync: 'sync.run',
  users: 'users.manage',
  audit: 'audit.view',
} as const;

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  readonly me = signal<Me | null>(null);
  readonly isLoggedIn = computed(() => this.me() !== null);

  get token(): string | null {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  }

  can(permission: string): boolean {
    return this.me()?.permissions.includes(permission) ?? false;
  }

  /** Returns an mfa token when the account uses an authenticator app (then call verifyCode). */
  async login(username: string, password: string): Promise<string | null> {
    const body = new URLSearchParams({ username, password });
    const res = await firstValueFrom(this.http.post<{ access_token: string | null; mfa_required: boolean; mfa_token: string | null }>(
      '/api/auth/login', body.toString(), { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }));
    if (res.mfa_required) return res.mfa_token;
    await this.signedIn(res.access_token!);
    return null;
  }

  async verifyCode(mfaToken: string, code: string): Promise<void> {
    const res = await firstValueFrom(this.http.post<{ access_token: string }>('/api/auth/login/verify', { mfa_token: mfaToken, code }));
    await this.signedIn(res.access_token);
  }

  private async signedIn(token: string) {
    try { localStorage.setItem(TOKEN_KEY, token); } catch { /* private mode */ }
    await this.loadMe();
  }

  loadMe(): Promise<boolean> {
    if (!this.token) return Promise.resolve(false);
    return firstValueFrom(this.http.get<Me>('/api/auth/me').pipe(
      map((me) => { this.me.set(me); return true; }),
      catchError(() => of(false)),
    ));
  }

  logout(): void {
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
    this.me.set(null);
    this.router.navigate(['/login']);
  }
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const token = auth.token;
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const company = CompanyService.stored();
  if (company && req.url.startsWith('/api/')) headers['X-Company-Id'] = String(company);
  const authed = Object.keys(headers).length ? req.clone({ setHeaders: headers }) : req;
  return next(authed).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status === 401 && !req.url.includes('/auth/login')) auth.logout();
      return throwError(() => err);
    }),
  );
};

export const authGuard: CanActivateFn = async (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.me() && !(await auth.loadMe())) return router.parseUrl('/login');
  const needed = route.data?.['permission'] as string | undefined;
  return !needed || auth.can(needed) ? true : router.parseUrl('/');
};

/** Pull a readable message out of a FastAPI error response. */
export function errorText(err: unknown): string {
  const e = err as HttpErrorResponse;
  const detail = e?.error?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail))
    return detail.map((d) => {
      const field = String(d.loc?.[d.loc.length - 1] ?? '').replace(/_/g, ' ').replace(/^qbwc /, 'Web Connector ');
      return field && field !== 'body' ? `${field}: ${d.msg}` : d.msg;
    }).join('; ');
  return e?.message ?? 'Something went wrong';
}
