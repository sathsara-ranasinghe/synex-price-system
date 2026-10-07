export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Me {
  user_id: number;
  username: string;
  full_name: string | null;
  email: string;
  role: string;
  permissions: string[];
}

export interface User {
  user_id: number;
  username: string;
  full_name: string | null;
  email: string;
  role_name: string;
  is_active: boolean;
  receive_alerts: boolean;
  created_at: string;
  company_ids: number[];
}








export interface SyncLog {
  sync_id: number;
  started_at: string;
  finished_at: string | null;
  records_inserted: number;
  records_updated: number;
  status: string;
  error_message: string | null;
  triggered_by: string;
  qb_company_file: string | null;
  progress: number;
}

export interface SyncStatus {
  last_success: SyncLog | null;
  running: SyncLog | null;
  pending_request: boolean;
  pending_writes: number;
  run_every_minutes: number;
  qbwc_url: string;
}

export interface Notification {
  notification_id: number;
  type: string;
  message: string;
  link: string | null;
  is_read: boolean;
  created_at: string;
}

export interface AuditEntry {
  audit_id: number;
  username: string | null;
  entity: string;
  entity_id: string | null;
  action: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  created_at: string;
}



export interface QBWrite {
  write_id: number;
  kind: string;
  entity_id: number;
  summary: string;
  payload: Record<string, unknown>;
  status: 'pending' | 'approved' | 'sent' | 'done' | 'failed' | 'rejected';
  requested_by: string | null;
  requested_at: string;
  approved_at: string | null;
  sent_at: string | null;
  attempts: number;
  qb_ref: string | null;
  error_message: string | null;
}


// ---------------------------------------------------------------- QB Portal (metadata-driven)

export interface FieldMeta {
  path: string;
  label: string;
  type: 'str' | 'text' | 'int' | 'decimal' | 'money' | 'date' | 'bool' | 'enum' | 'ref' | 'address' | 'txnref';
  ref: string | null;
  add: boolean;
  mod: boolean;
  required: boolean;
  max: number | null;
  options: string[];
  list: boolean;
  min: number | null;
}

export interface LineMeta {
  key: string;
  label: string;
  add_tag: string;
  mod_tag: string | null;
  ret_tag: string;
  fields: FieldMeta[];
  amount: string | null;
}

export interface EntityMeta {
  key: string;
  label: string;
  plural: string;
  module: string;
  kind: 'list' | 'txn';
  fields: FieldMeta[];
  lines: LineMeta[];
  can_add: boolean;
  can_mod: boolean;
  del_type: string | null;
  can_void: boolean;
  id_field: string;
  permissions: { create: boolean; edit: boolean; delete: boolean; direct: boolean };
}

export interface PortalMeta {
  modules: { key: string; label: string }[];
  entities: EntityMeta[];
  reports: { key: string; family: string; label: string }[];
}

export interface QbRecord {
  record_id: number;
  entity: string;
  qb_id: string;
  name: string | null;
  party_name: string | null;
  txn_date: string | null;
  amount: number | null;
  is_active: boolean;
  deleted: boolean;
  time_modified: string | null;
  columns: Record<string, any>;
  label?: string;
}

export interface QbLine { type: string; TxnLineID?: string | null; values: Record<string, unknown> }

export interface QbRecordDetail {
  record: QbRecord;
  data: Record<string, unknown>;
  form: { values: Record<string, unknown>; lines: QbLine[] };
  pending_changes: number;
  related: QbRecord[];
}

export interface RefOption { ListID: string; FullName: string | null; label: string; entity: string; amount: number | null }
