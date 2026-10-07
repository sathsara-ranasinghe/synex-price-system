import { HttpClient, HttpParams, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { AuditEntry, Notification, Page, QBWrite, SyncLog, SyncStatus, User } from './models';

type Params = Record<string, string | number | boolean | (string | number)[] | null | undefined>;

function toParams(p: Params = {}): HttpParams {
  let params = new HttpParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === null || v === undefined || v === '') continue;
    if (Array.isArray(v)) v.forEach((x) => (params = params.append(k, String(x))));
    else params = params.set(k, String(v));
  }
  return params;
}

/** Sync, approvals, notifications, users and audit. QuickBooks records go through PortalService. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private base = '/api';

  // changes waiting for QuickBooks
  qbWrites(status: string | null) { return this.http.get<QBWrite[]>(`${this.base}/qb-writes`, { params: toParams({ status }) }); }
  qbWriteApprove(id: number) { return this.http.post<QBWrite>(`${this.base}/qb-writes/${id}/approve`, {}); }
  qbWriteReject(id: number, note: string) { return this.http.post<QBWrite>(`${this.base}/qb-writes/${id}/reject`, { note }); }
  qbWriteRetry(id: number) { return this.http.post<QBWrite>(`${this.base}/qb-writes/${id}/retry`, {}); }

  // sync
  syncStatus() { return this.http.get<SyncStatus>(`${this.base}/sync/status`); }
  syncLogs() { return this.http.get<SyncLog[]>(`${this.base}/sync/logs`); }
  requestSync(full_resync: boolean) { return this.http.post<{ message: string }>(`${this.base}/sync/request`, { full_resync }); }

  // notifications
  notifications() { return this.http.get<Notification[]>(`${this.base}/notifications`); }
  unreadCount() { return this.http.get<{ count: number }>(`${this.base}/notifications/unread-count`); }
  readAll() { return this.http.post<void>(`${this.base}/notifications/read-all`, {}); }
  readOne(id: number) { return this.http.post<void>(`${this.base}/notifications/${id}/read`, {}); }

  // admin
  audit(p: Params) { return this.http.get<Page<AuditEntry>>(`${this.base}/audit`, { params: toParams(p) }); }
  users() { return this.http.get<User[]>(`${this.base}/users`); }
  roles() { return this.http.get<{ role_name: string; permissions: string[] }[]>(`${this.base}/roles`); }
  createUser(body: unknown) { return this.http.post<User>(`${this.base}/users`, body); }
  updateUser(id: number, body: unknown) { return this.http.patch<User>(`${this.base}/users/${id}`, body); }
  changePassword(current_password: string, new_password: string) {
    return this.http.post<void>(`${this.base}/auth/change-password`, { current_password, new_password });
  }

  /** Download a file from an authenticated endpoint (e.g. the .qwc file). */
  download(path: string, p: Params = {}): Observable<HttpResponse<Blob>> {
    return this.http.get(`${this.base}${path}`, { params: toParams(p), responseType: 'blob', observe: 'response' }).pipe(
      tap((res) => {
        const cd = res.headers.get('Content-Disposition') ?? '';
        const name = /filename=([^;]+)/.exec(cd)?.[1] ?? 'download';
        const url = URL.createObjectURL(res.body!);
        const a = document.createElement('a');
        a.href = url;
        a.download = name.replace(/"/g, '');
        a.click();
        URL.revokeObjectURL(url);
      }),
    );
  }
}
