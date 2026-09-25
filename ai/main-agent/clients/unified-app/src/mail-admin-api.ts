import { API_BASE, request } from './api';

export type MailOrgUser = {
  organization_id: string;
  user_id: string;
  display_name: string;
  email: string;
  role: 'owner' | 'admin' | 'member';
  active: boolean;
};

export type MailGrant = {
  organization_id: string;
  owner_user_id: string;
  provider: 'gmail' |'gmail' | 'outlook' | 'archive';
  account_id: string;
  recipient_user_id: string;
  address: string;
  can_forward: boolean;
};

export type ConnectedAccount = {
  owner_user_id?: string;
  account_id: string;
  address: string;
  provider: 'gmail' |'gmail' | 'outlook' | 'archive';
};

export type ForwardingRule = {
  rule_id: string;
  owner_user_id: string;
  provider: 'gmail' |'gmail' | 'outlook' | 'archive';
  account_id: string;
  match_text: string;
  destination: string;
  scan_attachments: boolean;
  mode: 'review' | 'auto';
  enabled: boolean;
};

export type ForwardJob = {
  job_id: string;
  organization_id: string;
  owner_user_id: string;
  account_id: string;
  provider: 'gmail' |'gmail' | 'outlook' | 'archive';
  rule_id: string;
  email_id: string;
  destination: string;
  matched_in: 'message' | 'attachment' | 'unverified_attachment';
  status: 'pending_review' | 'sending' | 'forwarded' | 'needs_reconciliation' | 'dismissed';
  decided_by: string | null;
};

export type ForwardPreview = {
  job: ForwardJob;
  message: {
    subject: string;
    sender: string;
    body_text: string;
    received_at: string;
    attachments: Array<{ attachment_id: string; filename: string; mime_type: string }>;
  };
};

export function getOrgMailUsers() {
  return request<{ items: MailOrgUser[] }>('/mail/admin/users').then((r) => r.items);
}

export function createOrgMailUser(values: Pick<MailOrgUser, 'user_id' | 'display_name' | 'email' | 'role'>) {
  return request<MailOrgUser>('/mail/admin/users', {
    method: 'POST',
    body: JSON.stringify(values),
  });
}

export function setOrgMailUserStatus(userId: string, active: boolean) {
  return request<MailOrgUser>(`/mail/admin/users/${encodeURIComponent(userId)}/status`, {
    method: 'POST',
    body: JSON.stringify({ active }),
  });
}

export function getConnectedAccounts(ownerUserId: string) {
  return request<{ items: ConnectedAccount[] }>(
    `/mail/admin/connected-accounts?owner_user_id=${encodeURIComponent(ownerUserId)}`,
  ).then((r) => r.items);
}

export function getAllMailGrants() {
  return request<{ items: MailGrant[] }>('/mail/admin/grants').then((r) => r.items);
}

export function assignMailAccount(values: Omit<MailGrant, 'organization_id' | 'address'>) {
  return request<MailGrant>('/mail/admin/grants', { method: 'POST', body: JSON.stringify(values) });
}

export function revokeMailAccount(values: Omit<MailGrant, 'organization_id' | 'address' | 'can_forward'>) {
  const params = new URLSearchParams({
    owner_user_id: values.owner_user_id,
    provider: values.provider,
    account_id: values.account_id,
    recipient_user_id: values.recipient_user_id,
  });
  return request<{ revoked: boolean }>(`/mail/admin/grants?${params.toString()}`, { method: 'DELETE' });
}

export function getMailRoutingRules() {
  return request<{ items: ForwardingRule[] }>('/mail/admin/rules').then((r) => r.items);
}

export function createMailRoutingRule(values: Omit<ForwardingRule, 'rule_id' | 'enabled'>) {
  return request<ForwardingRule>('/mail/admin/rules', { method: 'POST', body: JSON.stringify(values) });
}

export function getForwardingJobs() {
  return request<{ items: ForwardJob[] }>('/mail/forward-jobs').then((r) => r.items);
}

export function getForwardPreview(jobId: string) {
  return request<ForwardPreview>(`/mail/forward-jobs/${encodeURIComponent(jobId)}/preview`);
}

export async function downloadForwardAttachment(jobId: string, attachmentId: string, filename: string) {
  const response = await fetch(
    `${API_BASE}/mail/forward-jobs/${encodeURIComponent(jobId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { credentials: 'include' },
  );
  if (!response.ok) throw new Error(`Вложение недоступно: ${response.status}`);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || 'attachment';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function approveMailForward(jobId: string) {
  return request<{ status: string }>(`/mail/forward-jobs/${encodeURIComponent(jobId)}/approve`, {
    method: 'POST',
  });
}

export function dismissMailForward(jobId: string) {
  return request<ForwardJob>(`/mail/forward-jobs/${encodeURIComponent(jobId)}/dismiss`, {
    method: 'POST',
  });
}

export function setMailRoutingRuleStatus(ruleId: string, active: boolean) {
  return request<ForwardingRule>(`/mail/admin/rules/${encodeURIComponent(ruleId)}/status`, {
    method: 'POST',
    body: JSON.stringify({ active }),
  });
}

export async function uploadMailArchive(address: string, archive: File) {
  const body = new FormData();
  body.set('address', address);
  body.set('archive', archive);
  const response = await fetch(`${API_BASE}/mail/admin/import`, {
    method: 'POST',
    credentials: 'include',
    body,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `Import failed: ${response.status}`);
  }
  return response.json() as Promise<{
    address: string; account_id: string; imported: number;
    received: number; already_present: number; read_only: boolean;
  }>;
}
