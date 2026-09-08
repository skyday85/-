export type ModuleManifest = {
  module_id: string;
  title: string;
  routes: string[];
  badge_source?: string | null;
};

export type BootstrapResponse = {
  client: {
    user_id: string;
    device_id: string;
    platform: 'mac' | 'iphone';
    app_version: string;
  };
  manifest: {
    device: 'mac' | 'iphone';
    navigation: ModuleManifest[];
    backend_contract: 'shared';
    main_agent_entry: string;
    mail_entry: string;
  };
  mail: {
    accounts: string[];
    unread_count: number;
  };
  agents: Array<Record<string, unknown>>;
};

export type MailMessage = {
  email_id: string;
  account_id: string;
  sender: string;
  subject: string;
  received_at: string;
  unread: boolean;
  classification?: string | null;
  route_to?: string | null;
};

export type AgentCommandResponse = {
  action: string;
  result: unknown;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
const APP_VERSION = import.meta.env.VITE_APP_VERSION || 'development';

function deviceId(): string {
  const key = 'main-agent-device-id';
  const current = localStorage.getItem(key);
  if (current) return current;
  const created = crypto.randomUUID();
  localStorage.setItem(key, created);
  return created;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-Device-Id': deviceId(),
      'X-App-Version': APP_VERSION,
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail || `API ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function bootstrap(platform: 'mac' | 'iphone') {
  return request<BootstrapResponse>(`/client/bootstrap?platform=${platform}`);
}

export function getUnifiedInbox(params: URLSearchParams = new URLSearchParams()) {
  return request<MailMessage[]>(`/mail/inbox?${params.toString()}`);
}

export function syncMail() {
  return request<{ total_imported: number }>(`/mail/sync`, { method: 'POST' });
}

export function processMail(emailId: string) {
  return request<MailMessage>(`/mail/messages/${encodeURIComponent(emailId)}/process`, { method: 'POST' });
}

export function beginMailAuthorization(provider: 'gmail' | 'outlook') {
  return request<{ authorization_url: string }>(`/mail/accounts/${provider}/authorize`, {
    method: 'POST',
    body: JSON.stringify({ return_to: '/mail' }),
  });
}

export function sendAgentCommand(text: string) {
  return request<AgentCommandResponse>(`/agent/commands`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}
