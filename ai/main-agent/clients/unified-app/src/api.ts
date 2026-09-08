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

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.example.invalid';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json() as Promise<T>;
}

export function bootstrap(platform: 'mac' | 'iphone') {
  return request<BootstrapResponse>(`/client/bootstrap?platform=${platform}`);
}

export function getUnifiedInbox(params: URLSearchParams = new URLSearchParams()) {
  return request<MailMessage[]>(`/mail/inbox?${params.toString()}`);
}

export function beginMailAuthorization(provider: 'gmail' | 'outlook') {
  return request<{ authorization_url: string }>(`/mail/accounts/${provider}/authorize`, {
    method: 'POST',
    body: JSON.stringify({ return_to: '/mail' }),
  });
}
