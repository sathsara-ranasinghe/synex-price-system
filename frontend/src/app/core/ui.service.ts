import { Injectable, computed, inject, signal } from '@angular/core';
import { CompanyService } from './company.service';

export type Theme = 'auto' | 'light' | 'dark';

export interface RecentItem {
  company_id: number;
  entity: string;
  record_id: number;
  label: string;
  name: string | null;
  party_name: string | null;
  at: number;
}

const THEME_KEY = 'synex_theme';
const RECENT_KEY = 'synex_recent';
const MAX_RECENT = 30;

function read<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) ?? '') as T; } catch { return fallback; }
}
function write(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: keep in memory only */ }
}

/** Per-browser conveniences: colour theme, recently opened records and the Ctrl+K search window. */
@Injectable({ providedIn: 'root' })
export class UiService {
  private companies = inject(CompanyService);
  readonly theme = signal<Theme>(read<Theme>(THEME_KEY, 'auto'));
  readonly paletteOpen = signal(false);
  private recentAll = signal<RecentItem[]>(read<RecentItem[]>(RECENT_KEY, []));

  /** Recently opened records of the current company, newest first. */
  readonly recent = computed(() => {
    const id = this.companies.current()?.company_id;
    return this.recentAll().filter((r) => r.company_id === id);
  });

  constructor() { this.applyTheme(this.theme()); }

  setTheme(t: Theme) {
    this.theme.set(t);
    write(THEME_KEY, t);
    this.applyTheme(t);
  }

  private applyTheme(t: Theme) {
    const root = document.documentElement;
    if (t === 'auto') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', t);
  }

  addRecent(item: Omit<RecentItem, 'company_id' | 'at'>) {
    const company_id = this.companies.current()?.company_id;
    if (!company_id) return;
    const rest = this.recentAll().filter(
      (r) => !(r.company_id === company_id && r.entity === item.entity && r.record_id === item.record_id));
    const next = [{ ...item, company_id, at: Date.now() }, ...rest].slice(0, MAX_RECENT);
    this.recentAll.set(next);
    write(RECENT_KEY, next);
  }

  clearRecent() {
    const id = this.companies.current()?.company_id;
    const next = this.recentAll().filter((r) => r.company_id !== id);
    this.recentAll.set(next);
    write(RECENT_KEY, next);
  }
}
