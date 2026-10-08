import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';
import { EntityMeta, Page, PortalMeta, QbLine, QbRecord, QbRecordDetail, RefOption } from './models';

export interface Insights {
  months: string[];
  sales: number[] | null;
  purchases: number[] | null;
  top_customers: { name: string; amount: number }[];
  top_vendors: { name: string; amount: number }[];
}
export interface WriteResult { write_id: number; status: string; summary: string; message: string }
export interface Attachment { attachment_id: number; filename: string; content_type: string; size: number; uploaded_by: string | null; uploaded_at: string }

/** Open a downloaded blob in a new tab (PDFs) or save it. */
export function openBlob(blob: Blob, filename?: string) {
  const url = URL.createObjectURL(blob);
  if (filename) {
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } else {
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
}

@Injectable({ providedIn: 'root' })
export class PortalService {
  private http = inject(HttpClient);
  private base = '/api/qb';
  readonly meta = signal<PortalMeta | null>(null);

  async load(force = false): Promise<PortalMeta> {
    if (!this.meta() || force) this.meta.set(await firstValueFrom(this.http.get<PortalMeta>(`${this.base}/meta`)));
    return this.meta()!;
  }

  entity(key: string): EntityMeta | undefined {
    return this.meta()?.entities.find((e) => e.key === key);
  }

  entitiesOf(module: string): EntityMeta[] {
    return (this.meta()?.entities ?? []).filter((e) => e.module === module);
  }

  list(entity: string, p: Record<string, string | number | boolean | null | undefined>): Observable<Page<QbRecord>> {
    let params = new HttpParams();
    for (const [k, v] of Object.entries(p)) if (v !== null && v !== undefined && v !== '') params = params.set(k, String(v));
    return this.http.get<Page<QbRecord>>(`${this.base}/${entity}`, { params });
  }
  get(entity: string, id: number) { return this.http.get<QbRecordDetail>(`${this.base}/${entity}/${id}`); }
  create(entity: string, values: Record<string, unknown>, lines: QbLine[] | null) {
    return this.http.post<WriteResult>(`${this.base}/${entity}`, { values, lines });
  }
  update(entity: string, id: number, values: Record<string, unknown>, lines: QbLine[] | null) {
    return this.http.patch<WriteResult>(`${this.base}/${entity}/${id}`, { values, lines });
  }
  remove(entity: string, id: number) { return this.http.delete<WriteResult>(`${this.base}/${entity}/${id}`); }
  void(entity: string, id: number) { return this.http.post<WriteResult>(`${this.base}/${entity}/${id}/void`, {}); }
  options(target: string, q: string, partyId?: string | null) {
    let params = new HttpParams().set('q', q);
    if (partyId) params = params.set('party_id', partyId);
    return this.http.get<RefOption[]>(`${this.base}/options/${target}`, { params });
  }
  dashboard() { return this.http.get<any>(`${this.base}/dashboard`); }
  insights(months = 6) {
    return this.http.get<Insights>(`${this.base}/insights`, { params: new HttpParams().set('months', months) });
  }
  runReport(report_type: string, from_date: string | null, to_date: string | null) {
    return this.http.post<{ report_id: number }>(`${this.base}/reports`, { report_type, from_date, to_date });
  }
  reports() { return this.http.get<any[]>(`${this.base}/reports`); }
  report(id: number) { return this.http.get<any>(`${this.base}/reports/${id}`); }

  // documents
  pdf(entity: string, id: number) { return this.http.get(`/api/files/pdf/${entity}/${id}`, { responseType: 'blob' }); }
  email(entity: string, id: number, to: string[], message: string | null) {
    return this.http.post<{ message: string }>(`/api/files/email/${entity}/${id}`, { to, message });
  }
  attachments(entity: string, id: number) { return this.http.get<Attachment[]>(`/api/files/attachments/${entity}/${id}`); }
  upload(entity: string, id: number, file: File) {
    const fd = new FormData();
    fd.append('file', file);
    return this.http.post<Attachment>(`/api/files/attachments/${entity}/${id}`, fd);
  }
  deleteAttachment(id: number) { return this.http.delete(`/api/files/attachment/${id}`); }
  attachmentBlob(id: number) { return this.http.get(`/api/files/attachment/${id}`, { responseType: 'blob' }); }

  // roles
  permissionCatalog() { return this.http.get<{ group: string; permissions: { key: string; label: string }[] }[]>('/api/permissions'); }
  roles() { return this.http.get<{ role_name: string; permissions: string[] }[]>('/api/roles'); }
  createRole(role_name: string, permissions: string[]) { return this.http.post('/api/roles', { role_name, permissions }); }
  updateRole(role_name: string, permissions: string[]) { return this.http.put(`/api/roles/${role_name}`, { role_name, permissions }); }
  deleteRole(role_name: string) { return this.http.delete(`/api/roles/${role_name}`); }
}
