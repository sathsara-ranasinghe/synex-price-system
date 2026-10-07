import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

export interface Company {
  company_id: number;
  name: string;
  qbwc_username: string;
  app_name: string;
  qbwc_url: string | null;
  effective_qbwc_url: string;
  company_file: string | null;
  is_active: boolean;
  created_at: string;
  last_sync: string | null;
  records: number;
}

const KEY = 'synex_company';

/** The QuickBooks company the user is working in. Sent to the API as X-Company-Id. */
@Injectable({ providedIn: 'root' })
export class CompanyService {
  private http = inject(HttpClient);
  readonly mine = signal<Company[]>([]);
  readonly currentId = signal<number | null>(CompanyService.stored());
  readonly current = computed(() => this.mine().find((c) => c.company_id === this.currentId()) ?? this.mine()[0] ?? null);

  static stored(): number | null {
    try { const v = localStorage.getItem(KEY); return v ? Number(v) : null; } catch { return null; }
  }

  async load(): Promise<void> {
    const list = await firstValueFrom(this.http.get<Company[]>('/api/companies/mine'));
    this.mine.set(list);
    if (!list.some((c) => c.company_id === this.currentId()) && list.length) this.remember(list[0].company_id);
  }

  /** Switch company and reload the app so every page shows the new company's data. */
  switchTo(id: number) {
    this.remember(id);
    window.location.assign('/');
  }

  private remember(id: number) {
    this.currentId.set(id);
    try { localStorage.setItem(KEY, String(id)); } catch { /* private mode */ }
  }

  // admin
  all() { return this.http.get<Company[]>('/api/companies'); }
  create(body: { name: string; qbwc_username: string; qbwc_password: string }) { return this.http.post<Company>('/api/companies', body); }
  urlSuggestion() { return this.http.get<{ url: string; note: string }>('/api/companies/url-suggestion'); }
  update(id: number, body: Record<string, unknown>) { return this.http.patch<Company>(`/api/companies/${id}`, body); }
}
