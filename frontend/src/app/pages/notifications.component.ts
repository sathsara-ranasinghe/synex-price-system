import { DatePipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { Notification } from '../core/models';

@Component({
  selector: 'app-notifications',
  standalone: true,
  imports: [DatePipe, MatButtonModule, MatIconModule],
  template: `
    <div class="head"><h1>Notifications</h1><span class="spacer"></span>
      <button mat-stroked-button (click)="readAll()"><mat-icon>done_all</mat-icon> Mark all read</button></div>
    <div class="panel flush">
      @for (n of rows(); track n.notification_id) {
        <button class="note" [class.unread]="!n.is_read" (click)="open(n)">
          <mat-icon>{{ n.type === 'price_expiry' ? 'event_busy' : 'trending_up' }}</mat-icon>
          <span class="msg">{{ n.message }}</span>
          <span class="muted">{{ n.created_at | date: 'short' }}</span>
        </button>
      } @empty { <p class="muted pad">No notifications.</p> }
    </div>
  `,
  styles: [`
    .note { display: flex; gap: 12px; align-items: center; width: 100%; padding: 12px 16px; border: 0; border-bottom: 1px solid var(--line);
      background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; }
    .note:hover { background: var(--primary-soft); } .note.unread { font-weight: 600; } .msg { flex: 1; } .pad { padding: 16px; }
  `],
})
export class NotificationsComponent implements OnInit {
  private api = inject(ApiService);
  private router = inject(Router);
  rows = signal<Notification[]>([]);

  ngOnInit() { this.load(); }
  load() { this.api.notifications().subscribe((n) => this.rows.set(n)); }
  readAll() { this.api.readAll().subscribe(() => this.load()); }
  open(n: Notification) {
    this.api.readOne(n.notification_id).subscribe();
    if (n.link) this.router.navigateByUrl(n.link);
  }
}
