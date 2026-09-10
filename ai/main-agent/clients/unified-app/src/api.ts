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
    accounts: Array<Record<string, unknown>>;
    connections: Array<Record<string, unknown>>;
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

export type BankClassification = {
  transaction_id: string;
  operation_type: string;
  category?: string | null;
  confidence: number;
  review_status: 'needs_review' | 'confirmed';
  rationale: string;
  confirmed_by_user: boolean;
};

export type BankTransaction = {
  transaction_id: string;
  date: string;
  amount: string;
  direction: 'income' | 'expense';
  counterparty_name: string;
  purpose: string;
  bank_reference?: string | null;
  classification?: BankClassification | null;
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

export function refreshMail() {
  return request<Record<string, unknown>>('/mail/sync', { method: 'POST' });
}

export function processMailMessage(emailId: string) {
  return request<Record<string, unknown>>(`/mail/messages/${encodeURIComponent(emailId)}/process`, { method: 'POST' });
}

export function sendAgentCommand(text: string) {
  return request<Record<string, unknown>>('/agent/commands', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

export function getFinanceReviewQueue() {
  return request<BankTransaction[]>('/finance/review');
}

export function classifyBankTransaction(transactionId: string) {
  return request<BankClassification>(`/finance/transactions/${encodeURIComponent(transactionId)}/classify`, {
    method: 'POST',
  });
}

export function confirmBankClassification(
  transactionId: string,
  changes: Partial<Pick<BankClassification, 'operation_type' | 'category' | 'rationale'>> = {},
) {
  return request<BankClassification>(`/finance/transactions/${encodeURIComponent(transactionId)}/confirm`, {
    method: 'POST',
    body: JSON.stringify(changes),
  });
}
