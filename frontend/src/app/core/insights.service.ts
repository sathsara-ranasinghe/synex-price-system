import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, firstValueFrom, tap } from 'rxjs';

export type Bucket = 'current' | 'd1_30' | 'd31_60' | 'd61_90' | 'd90_plus';
export const BUCKETS: { key: Bucket; label: string }[] = [
  { key: 'current', label: 'Not due yet' }, { key: 'd1_30', label: '1-30 days' }, { key: 'd31_60', label: '31-60 days' },
  { key: 'd61_90', label: '61-90 days' }, { key: 'd90_plus', label: 'Over 90 days' },
];

export interface AgingParty extends Record<Bucket, number> {
  party_id: string | null; name: string | null; record_id: number | null; total: number; docs: number; oldest_due: string | null;
}
export interface Aging {
  side: 'ar' | 'ap'; as_of: string; party_entity: string; doc_entity: string;
  totals: Record<Bucket, number>; total: number; overdue: number; parties: AgingParty[];
}
export interface OpenDoc {
  record_id: number; entity: string; name: string | null; txn_date: string | null; due_date: string | null;
  days_overdue: number; amount: number; open: number; bucket: Bucket;
}
export interface PartyOverview {
  entity: string; record_id: number; name: string | null; balance: number; credit_limit: number | null;
  email: string | null; phone: string | null; terms: string | null; open_total: number; overdue_total: number;
  buckets: Record<Bucket, number>; open_docs: OpenDoc[]; open_count: number;
  payments: { record_id: number; entity: string; label: string; name: string | null; txn_date: string | null; amount: number }[];
  months: string[]; monthly: number[]; lifetime: number; last_activity: string | null; doc_entity: string;
}
export interface StockItem {
  record_id: number; entity: string; qb_id: string; name: string | null; desc: string | null; qoh: number;
  reorder_point: number; on_order: number; suggested: number; cost: number;
  vendor: { ListID: string; FullName: string } | null; covered: boolean;
}
export interface Lookup {
  entity: string; record_id: number; name: string | null;
  terms?: { ListID: string; FullName: string } | null; bill_address?: Record<string, string> | null;
  ship_address?: Record<string, string> | null; balance?: number; credit_limit?: number | null; email?: string | null;
  sales_price?: number | null; cost?: number | null; sales_desc?: string | null; purchase_desc?: string | null;
  qoh?: number | null; reorder_point?: number | null;
}
export interface Duplicate { record_id: number; name: string | null; party_name: string | null; txn_date: string | null; amount: number; reason: string }
export interface ActivityEvent { at: string; who: string | null; kind: string; text: string; status: string; error?: string | null; write_id?: number }
export interface WriteDiff {
  kind: string; entity: string; label: string; record: { record_id: number; name: string | null; amount: number | null } | null;
  fields: { label: string; old: string | null; new: string | null }[]; lines_old: string[]; lines_new: string[];
}
export interface SavedView { name: string; params: Record<string, unknown> }
export interface Prefs { columns: Record<string, string[]>; views: Record<string, SavedView[]>; daily_summary: boolean }

@Injectable({ providedIn: 'root' })
export class InsightsService {
  private http = inject(HttpClient);
  private base = '/api/insights';
  /** The signed-in user's saved list columns, views and e-mail settings (loaded once). */
  readonly prefs = signal<Prefs | null>(null);
  private loading?: Promise<Prefs>;

  aging(side: 'ar' | 'ap') { return this.http.get<Aging>(`${this.base}/aging`, { params: { side } }); }
  party(entity: string, id: number) { return this.http.get<PartyOverview>(`${this.base}/party/${entity}/${id}`); }
  stock() { return this.http.get<{ items: StockItem[]; count: number; uncovered: number }>(`${this.base}/stock`); }
  lookup(target: string, listId: string) { return this.http.get<Lookup>(`${this.base}/lookup/${target}/${encodeURIComponent(listId)}`); }
  duplicates(entity: string, p: { ref?: string; party_id?: string | null; amount?: number; txn_date?: string; exclude?: number }) {
    let params = new HttpParams();
    for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null && v !== '') params = params.set(k, String(v));
    return this.http.get<Duplicate[]>(`${this.base}/duplicates/${entity}`, { params });
  }
  activity(entity: string, id: number) { return this.http.get<ActivityEvent[]>(`${this.base}/activity/${entity}/${id}`); }
  digest() { return this.http.get<{ subject: string | null; body: string }>(`${this.base}/digest`); }
  sendDigest() { return this.http.post<{ message: string }>(`${this.base}/digest/send`, {}); }

  diff(writeId: number) { return this.http.get<WriteDiff>(`/api/qb-writes/${writeId}/diff`); }
  approveMany(ids: number[]) {
    return this.http.post<{ approved: number[]; skipped: { write_id: number; reason: string }[] }>('/api/qb-writes/approve-many', { ids });
  }

  bulkPdf(entity: string, ids: number[]): Observable<Blob> {
    return this.http.post('/api/files/bulk-pdf', { entity, ids }, { responseType: 'blob' });
  }
  bulkEmail(entity: string, ids: number[], message: string | null) {
    return this.http.post<{ sent: { name: string; to: string[] }[]; skipped: { name: string; party: string; reason: string }[] }>(
      '/api/files/bulk-email', { entity, ids, message });
  }

  /** Forget the cached preferences (another user signed in). */
  reset() { this.prefs.set(null); this.loading = undefined; }

  loadPrefs(): Promise<Prefs> {
    if (this.prefs()) return Promise.resolve(this.prefs()!);
    this.loading ??= firstValueFrom(this.http.get<Prefs>('/api/auth/prefs').pipe(tap((p) => this.prefs.set(p))));
    return this.loading;
  }
  savePrefs(patch: Partial<Prefs>) {
    return this.http.put<Prefs>('/api/auth/prefs', patch).pipe(tap((p) => this.prefs.set(p)));
  }
}
