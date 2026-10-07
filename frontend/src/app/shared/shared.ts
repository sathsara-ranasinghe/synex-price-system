import { Pipe, PipeTransform } from '@angular/core';

/** 12345.5 -> "12,345.50" */
@Pipe({ name: 'money', standalone: true })
export class MoneyPipe implements PipeTransform {
  transform(v: string | number | null | undefined, currency?: string | null): string {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v).toLocaleString('en-LK', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return currency ? `${currency} ${n}` : n;
  }
}

/** "OtherCurrentAsset" -> "Other current asset" (QuickBooks enum values). */
export function humanize(v: unknown): string {
  if (typeof v !== 'string' || !/^[A-Z][a-zA-Z]+$/.test(v) || !/[a-z][A-Z]/.test(v)) return v as string;
  const words = v.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2').split(' ');
  return words.map((w, i) => (i === 0 || (w.length > 1 && w === w.toUpperCase()) ? w : w.toLowerCase())).join(' ');
}

@Pipe({ name: 'humanize', standalone: true })
export class HumanizePipe implements PipeTransform {
  transform(v: unknown): string { return humanize(v); }
}
