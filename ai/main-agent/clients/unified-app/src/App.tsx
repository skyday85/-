import { useEffect, useMemo, useState } from 'react';
import {
  beginMailAuthorization,
  bootstrap,
  classifyBankTransaction,
  confirmBankClassification,
  getFinanceReviewQueue,
  getFleetDocumentCandidates,
  getFleetVehicles,
  getFleetVehicleWorkItems,
  getFleetDocumentContent,
  assignFleetDocument,
  dismissFleetDocument,
  getMailFolder,
  getUnifiedInbox,
  processMailMessage,
  refreshMail as syncMail,
  sendAgentCommand,
  type BankTransaction,
  type BootstrapResponse,
  type MailMessage,
  type FleetDocumentCandidate,
  type FleetWorkItems,
} from './api';
import { ForwardReview, MailManagement } from './MailManagement';
import type { MailGrant } from './mail-admin-api';

const MAIL_FOLDERS = [
  ['all', 'Все'],
  ['important_requests', 'Важное / Запросы'],
  ['finance', 'Финансы'],
  ['procurement', 'Закупщик'],
  ['documents', 'Документы'],
  ['marketing', 'Маркетинг'],
  ['other', 'Прочее'],
] as const;

function detectPlatform(): 'mac' | 'iphone' {
  return /iPhone|iPod/i.test(navigator.userAgent) ? 'iphone' : 'mac';
}

export default function App() {
  const platform = useMemo(detectPlatform, []);
  const [boot, setBoot] = useState<BootstrapResponse | null>(null);
  const [mail, setMail] = useState<MailMessage[]>([]);
  const [mailFolder, setMailFolder] = useState<string>('all');
  const [financeReview, setFinanceReview] = useState<BankTransaction[]>([]);
  const [documents, setDocuments] = useState<FleetDocumentCandidate[]>([]);
  const [vehicles, setVehicles] = useState<Array<{ id: string; stateNumber?: string; brand?: string; model?: string }>>([]);
  const [documentTargets, setDocumentTargets] = useState<Record<string, { vehicleId: string; repairId: string; purchaseId: string }>>({});
  const [workItems, setWorkItems] = useState<Record<string, FleetWorkItems>>({});
  const [active, setActive] = useState('main_agent');
  const [error, setError] = useState<string | null>(null);
  const [command, setCommand] = useState('');
  const [agentResult, setAgentResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadMail(folder = mailFolder) {
    setMail(folder === 'all' ? await getUnifiedInbox() : await getMailFolder(folder));
  }

  async function reloadCore() {
    const b = await bootstrap(platform);
    setBoot(b);
    await loadMail();
  }

  async function reloadFinance() {
    setFinanceReview(await getFinanceReviewQueue());
  }

  async function reloadDocuments() {
    const [items, fleetVehicles] = await Promise.all([getFleetDocumentCandidates(), getFleetVehicles()]);
    setDocuments(items);
    setVehicles(fleetVehicles);
  }

  async function selectDocumentVehicle(candidateId: string, vehicleId: string) {
    setDocumentTargets((prev) => ({ ...prev, [candidateId]: { vehicleId, repairId: '', purchaseId: '' } }));
    if (!vehicleId || workItems[vehicleId]) return;
    try {
      const items = await getFleetVehicleWorkItems(vehicleId);
      setWorkItems((prev) => ({ ...prev, [vehicleId]: items }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить ремонты и закупки');
    }
  }

  async function assignDocument(item: FleetDocumentCandidate) {
    const target = documentTargets[item.candidate_id];
    if (!target?.vehicleId) return;
    try {
      setBusy(true);
      await assignFleetDocument(item.candidate_id, target.vehicleId, target.repairId || undefined, target.purchaseId || undefined);
      await reloadDocuments();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось привязать документ');
    } finally {
      setBusy(false);
    }
  }

  async function previewDocument(candidateId: string) {
    try {
      const blob = await getFleetDocumentContent(candidateId);
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось открыть документ');
    }
  }

  async function dismissDocument(candidateId: string) {
    try {
      setBusy(true);
      await dismissFleetDocument(candidateId);
      await reloadDocuments();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось отклонить документ');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    Promise.all([reloadCore(), reloadFinance(), reloadDocuments()]).catch((e) => setError(e instanceof Error ? e.message : 'Ошибка загрузки'));
  }, [platform]);

  async function selectMailFolder(folder: string) {
    setMailFolder(folder);
    try {
      await loadMail(folder);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось открыть папку');
    }
  }

  async function connect(provider: 'gmail' | 'outlook') {
    try {
      setError(null);
      const { authorization_url } = await beginMailAuthorization(provider);
      window.location.assign(authorization_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось начать авторизацию');
    }
  }

  async function refreshMail() {
    try {
      setBusy(true);
      setError(null);
      await syncMail();
      const b = await bootstrap(platform);
      setBoot(b);
      await loadMail();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось синхронизировать почту');
    } finally {
      setBusy(false);
    }
  }

  async function classifyMail(emailId: string) {
    try {
      setError(null);
      await processMailMessage(emailId);
      const b = await bootstrap(platform);
      setBoot(b);
      await loadMail();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось обработать письмо');
    }
  }

  async function submitCommand() {
    const text = command.trim();
    if (!text) return;
    try {
      setBusy(true);
      setError(null);
      setAgentResult(await sendAgentCommand(text));
      setCommand('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Главный агент недоступен');
    } finally {
      setBusy(false);
    }
  }

  async function proposeFinance(transactionId: string) {
    try {
      setBusy(true);
      await classifyBankTransaction(transactionId);
      await reloadFinance();
    } finally {
      setBusy(false);
    }
  }

  async function confirmFinance(item: BankTransaction) {
    if (!item.classification) return;
    try {
      setBusy(true);
      await confirmBankClassification(item.transaction_id, { operation_type: item.classification.operation_type, category: item.classification.category ?? undefined });
      await reloadFinance();
    } finally {
      setBusy(false);
    }
  }

  const baseNav = boot?.manifest.navigation ?? [
    { module_id: 'main_agent', title: 'Главный агент', routes: ['/agent'] },
    { module_id: 'mail', title: 'Почта', routes: ['/mail'] },
    { module_id: 'finance', title: 'Финансы', routes: ['/finance'] },
    { module_id: 'fleet', title: 'Автопарк', routes: ['/fleet'] },
    { module_id: 'sales', title: 'Продажи', routes: ['/sales'] },
    { module_id: 'marketing', title: 'Маркетинг', routes: ['/marketing'] },
    { module_id: 'procurement', title: 'Закупки', routes: ['/procurement'] },
    { module_id: 'tasks', title: 'Задачи', routes: ['/tasks'] },
  ];
  const isMailAdmin = boot?.mail_identity?.role === 'owner' || boot?.mail_identity?.role === 'admin';
  const nav = isMailAdmin
    ? [...baseNav, { module_id: 'mail_settings', title: 'Управление почтой', routes: ['/mail/admin'] }]
    : baseNav;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Главный агент</div>
        <nav>{nav.map((item) => (
          <button key={item.module_id} className={active === item.module_id ? 'active' : ''} onClick={() => setActive(item.module_id)}>
            <span>{item.title}</span>
            {item.module_id === 'mail' && boot?.mail.important_count ? <b>{boot.mail.important_count}</b> : null}
            {item.module_id === 'finance' && financeReview.length ? <b>{financeReview.length}</b> : null}
          </button>
        ))}</nav>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div><strong>{nav.find((x) => x.module_id === active)?.title ?? 'Главный агент'}</strong><small>{platform === 'iphone' ? 'iPhone' : 'Mac'} · единый контур</small></div>
          <button className="agent-button" onClick={() => setActive('main_agent')}>Спросить агента</button>
        </header>
        {error ? <div className="error">{error}</div> : null}

        {active === 'main_agent' && (
          <section className="agent-panel">
            <div className="hero-card">
              <p className="eyebrow">Центральное управление</p><h1>Что нужно сделать?</h1>
              <textarea value={command} onChange={(e) => setCommand(e.target.value)} placeholder="Например: проверь новые заявки на перевозку, счета и документы…" />
              <button disabled={busy || !command.trim()} onClick={submitCommand}>{busy ? 'Выполняю…' : 'Отправить Главному агенту'}</button>
              {agentResult ? <pre className="agent-result">{JSON.stringify(agentResult, null, 2)}</pre> : null}
            </div>
            <div className="status-grid">
              <article><span>Важная почта</span><strong>{boot?.mail.important_count ?? '—'}</strong><small>требует внимания</small></article>
              <article><span>Непрочитано</span><strong>{boot?.mail.unread_count ?? '—'}</strong><small>по всем ящикам</small></article>
              <article><span>Пользователь</span><strong>{boot?.client.user_id ? 'Активен' : '—'}</strong><small>личный почтовый контур</small></article>
            </div>
          </section>
        )}

        {active === 'mail' && (
          <section className="mail-layout">
            <div className="mail-toolbar">
              <div><h2>Единая почта</h2><p>Письма автоматически распределяются по рабочим папкам.</p></div>
              <div className="connect-actions"><button disabled={busy} onClick={refreshMail}>{busy ? 'Синхронизация…' : 'Обновить'}</button><button onClick={() => connect('gmail')}>+ Gmail</button><button onClick={() => connect('outlook')}>+ Outlook</button></div>
            </div>
            <div className="folder-tabs">
              {MAIL_FOLDERS.map(([id, title]) => <button key={id} className={mailFolder === id ? 'active' : ''} onClick={() => selectMailFolder(id)}>{title}{id !== 'all' && boot?.mail.folders[id] ? ` ${boot.mail.folders[id]}` : ''}</button>)}
            </div>
            <div className="mail-list">
              {mail.length === 0 ? <div className="empty-state">В этой папке писем нет.</div> : mail.map((item) => (
                <article key={item.email_id} className={`mail-row ${item.unread ? 'unread' : ''} ${item.importance === 'high' ? 'important' : ''}`} onClick={() => classifyMail(item.email_id)}>
                  <div className="mail-source">{item.importance === 'high' ? 'ВАЖНО' : item.account_id}</div>
                  <div className="mail-content"><strong>{item.sender}</strong><span>{item.subject || '(без темы)'}</span><small>{item.attention_reason || item.classification || 'нажмите для классификации'}</small></div>
                  <time>{new Date(item.received_at).toLocaleString('ru-RU')}</time>
                </article>
              ))}
            </div>
            <ForwardReview grants={(boot?.mail.accounts ?? []) as MailGrant[]} />
          </section>
        )}

        {active === 'mail_settings' && isMailAdmin && boot?.mail_identity && (
          <MailManagement currentUserId={boot.mail_identity.user_id} />
        )}

        {active === 'procurement' && (
          <section className="mail-layout">
            <div className="mail-toolbar"><div><h2>Документы от поставщиков</h2><p>Вложения из почты ждут подтверждения перед попаданием в историю автомобиля.</p></div><button disabled={busy} onClick={reloadDocuments}>Обновить</button></div>
            <div className="mail-list">
              {documents.length === 0 ? <div className="empty-state">Новых документов нет.</div> : documents.map((item) => (
                <article key={item.candidate_id} className="mail-row">
                  <div className="mail-source">ДОКУМЕНТ</div>
                  <div className="mail-content"><strong>{item.filename}</strong><span>{item.document_type}</span><small>Письмо: {item.source_email_id}</small></div>
                  <div className="connect-actions">
                    <button disabled={busy} onClick={() => void previewDocument(item.candidate_id)}>Просмотр</button>
                    <select disabled={busy} value={documentTargets[item.candidate_id]?.vehicleId || ''} onChange={(e) => void selectDocumentVehicle(item.candidate_id, e.target.value)}>
                      <option value="">Выбрать автомобиль</option>
                      {vehicles.map((v) => <option key={v.id} value={v.id}>{v.stateNumber || v.id} · {[v.brand, v.model].filter(Boolean).join(' ')}</option>)}
                    </select>
                    {documentTargets[item.candidate_id]?.vehicleId ? (
                      <>
                        <select disabled={busy} value={documentTargets[item.candidate_id]?.repairId || ''} onChange={(e) => setDocumentTargets((prev) => ({ ...prev, [item.candidate_id]: { ...prev[item.candidate_id], repairId: e.target.value, purchaseId: '' } }))}>
                          <option value="">Без привязки к ремонту</option>
                          {(workItems[documentTargets[item.candidate_id].vehicleId]?.repairs || []).map((r) => <option key={r.repair_id} value={r.repair_id}>{r.title || r.repair_id} · {r.status || ''}</option>)}
                        </select>
                        <select disabled={busy} value={documentTargets[item.candidate_id]?.purchaseId || ''} onChange={(e) => setDocumentTargets((prev) => ({ ...prev, [item.candidate_id]: { ...prev[item.candidate_id], purchaseId: e.target.value, repairId: '' } }))}>
                          <option value="">Без привязки к закупке</option>
                          {(workItems[documentTargets[item.candidate_id].vehicleId]?.purchases || []).map((p) => <option key={p.purchase_id} value={p.purchase_id}>{p.title || p.purchase_id} · {p.status || ''}</option>)}
                        </select>
                        <button disabled={busy} onClick={() => void assignDocument(item)}>Подтвердить</button>
                      </>
                    ) : null}
                    <button disabled={busy} onClick={() => void dismissDocument(item.candidate_id)}>Отклонить</button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {active === 'finance' && (
          <section className="mail-layout"><div className="mail-toolbar"><div><h2>Операции на подтверждение</h2><p>Предложение агента не является окончательной классификацией.</p></div></div><div className="mail-list">
            {financeReview.length === 0 ? <div className="empty-state">Нет операций, ожидающих подтверждения.</div> : financeReview.map((item) => (
              <article key={item.transaction_id} className="mail-row"><div className="mail-source">{item.direction === 'income' ? 'Поступление' : 'Списание'}</div><div className="mail-content"><strong>{item.counterparty_name || 'Без контрагента'} · {item.amount}</strong><span>{item.purpose || 'Без назначения платежа'}</span><small>{item.classification ? `${item.classification.category || item.classification.operation_type} · ${Math.round(item.classification.confidence * 100)}%` : 'Классификация ещё не предложена'}</small></div><div className="connect-actions">{!item.classification ? <button disabled={busy} onClick={() => proposeFinance(item.transaction_id)}>Предложить</button> : <button disabled={busy} onClick={() => confirmFinance(item)}>Подтвердить</button>}</div></article>
            ))}
          </div></section>
        )}

        {!['main_agent', 'mail', 'mail_settings', 'finance', 'procurement'].includes(active) && <section className="placeholder"><h2>{nav.find((x) => x.module_id === active)?.title}</h2><p>Модуль подключён к общей навигации.</p></section>}
      </main>
    </div>
  );
}
