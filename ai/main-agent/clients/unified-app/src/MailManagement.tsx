import { useEffect, useState, type FormEvent } from 'react';
import {
  approveMailForward, assignMailAccount, createMailRoutingRule, createOrgMailUser,
  dismissMailForward, downloadForwardAttachment, getAllMailGrants, getConnectedAccounts,
  getForwardingJobs, getForwardPreview, getMailRoutingRules, getOrgMailUsers,
  revokeMailAccount, setOrgMailUserStatus, setMailRoutingRuleStatus, uploadMailArchive,
  type ConnectedAccount, type ForwardJob, type ForwardPreview, type ForwardingRule,
  type MailGrant, type MailOrgUser,
} from './mail-admin-api';

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Ошибка обращения к почтовому сервису';
}

export function ForwardReview({ grants }: { grants: MailGrant[] }) {
  const [jobs, setJobs] = useState<ForwardJob[]>([]);
  const [preview, setPreview] = useState<ForwardPreview | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setError('');
      setJobs(await getForwardingJobs());
    } catch (caught) {
      setError(message(caught));
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function open(jobId: string) {
    try {
      setError('');
      setPreview(await getForwardPreview(jobId));
    } catch (caught) {
      setError(message(caught));
    }
  }

  function permitted(job: ForwardJob) {
    return grants.some((grant) =>
      grant.owner_user_id === job.owner_user_id &&
      grant.provider === job.provider &&
      grant.account_id === job.account_id && grant.can_forward,
    );
  }

  async function decide(job: ForwardJob, action: 'approve' | 'dismiss') {
    if (action === 'approve' && !window.confirm(
      `Переслать оригинальное письмо и все вложения на ${job.destination}?`,
    )) return;
    try {
      setBusy(true);
      setError('');
      if (action === 'approve') await approveMailForward(job.job_id);
      else await dismissMailForward(job.job_id);
      setPreview(null);
      await refresh();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  const waiting = jobs.filter((job) => job.status === 'pending_review');
  return (
    <section className="mail-admin-card">
      <div className="mail-admin-row">
        <div><h3>Письма на пересылку</h3><p>Распознанный текст и адрес назначения. Неоднозначные случаи остаются на проверке.</p></div>
        <button onClick={() => void refresh()} disabled={busy}>Обновить</button>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {waiting.length === 0 ? <p className="empty-state">Нет писем, ожидающих решения.</p> : waiting.map((job) => (
        <article key={job.job_id} className="mail-admin-item">
          <div><strong>{job.destination}</strong><small>{job.matched_in === 'unverified_attachment' ?
            'Текст вложения не распознан: проверьте оригинал' :
            job.matched_in === 'attachment' ? 'Совпадение во вложении' : 'Совпадение в тексте письма'}</small></div>
          <div className="mail-admin-row">
            <button type="button" onClick={() => void open(job.job_id)}>Просмотреть</button>
            {permitted(job) && <button type="button" disabled={busy} onClick={() => void decide(job, 'approve')}>Переслать</button>}
            {permitted(job) && <button type="button" disabled={busy} onClick={() => void decide(job, 'dismiss')}>Отклонить</button>}
          </div>
        </article>
      ))}
      {preview && (
        <div className="mail-admin-preview">
          <div className="mail-admin-row"><h3>{preview.message.subject || '(Без темы)'}</h3>
            <button type="button" onClick={() => setPreview(null)}>Закрыть</button></div>
          <p><strong>От:</strong> {preview.message.sender}</p>
          <p><strong>Получено:</strong> {new Date(preview.message.received_at).toLocaleString('ru-RU')}</p>
          <p><strong>Пересылка:</strong> {preview.job.destination}</p>
          <pre className="mail-admin-body">{preview.message.body_text || 'Письмо без текстового содержимого.'}</pre>
          <h4>Оригинальные вложения</h4>
          {preview.message.attachments.length === 0 ? <p>Нет вложений</p> :
            preview.message.attachments.map((attachment) => (
              <button key={attachment.attachment_id} type="button"
                onClick={() => void downloadForwardAttachment(
                  preview.job.job_id, attachment.attachment_id, attachment.filename,
                ).catch((caught) => setError(message(caught)))}>
                {attachment.filename}
              </button>
            ))}
        </div>
      )}
    </section>
  );
}

export function MailManagement({ currentUserId, onImport }: {
  currentUserId: string; onImport?: () => void;
}) {
  const [users, setUsers] = useState<MailOrgUser[]>([]);
  const [grants, setGrants] = useState<MailGrant[]>([]);
  const [rules, setRules] = useState<ForwardingRule[]>([]);
  const [accounts, setAccounts] = useState<ConnectedAccount[]>([]);
  const [sourceOwner, setSourceOwner] = useState(currentUserId);
  const [sourceAccount, setSourceAccount] = useState('');
  const [targetUser, setTargetUser] = useState('');
  const [canForward, setCanForward] = useState(false);
  const [archiveAddress, setArchiveAddress] = useState('');
  const [archiveFiles, setArchiveFiles] = useState<File[]>([]);
  const [archiveResult, setArchiveResult] = useState('');
  const [newUser, setNewUser] = useState({
    user_id: '', display_name: '', email: '', role: 'member' as 'member' | 'admin',
  });
  const [newRule, setNewRule] = useState({
    match_text: '', destination: '', scan_attachments: false, mode: 'review' as 'review' | 'auto',
  });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    const [nextUsers, nextGrants, nextRules] = await Promise.all([
      getOrgMailUsers(), getAllMailGrants(), getMailRoutingRules(),
    ]);
    setUsers(nextUsers);
    setGrants(nextGrants);
    setRules(nextRules);
  }

  useEffect(() => { void load().catch((caught) => setError(message(caught))); }, []);

  useEffect(() => {
    setAccounts([]);
    setSourceAccount('');
    if (sourceOwner) {
      void getConnectedAccounts(sourceOwner).then((items) => setAccounts(items))
        .catch((caught) => setError(message(caught)));
    }
  }, [sourceOwner]);

  const account = accounts.find((item) => item.account_id === sourceAccount);

  async function submit(event: FormEvent, work: () => Promise<unknown>, success: string) {
    event.preventDefault();
    try {
      setBusy(true);
      setError('');
      setNotice('');
      await work();
      await load();
      setNotice(success);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mail-admin">
      <h2>Управление почтовым сервисом</h2>
      <p>Пользователи входят через корпоративную систему авторизации. Здесь им выдаётся доступ
         только к выбранным почтовым ящикам. Учётная запись и пароль почты не передаются сотрудникам.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status" className="mail-admin-notice">{notice}</p>}
      <section className="mail-admin-card mail-import-card">
        <h3>Загрузить письма в единую почту</h3>
        <p>Первый этап: безопасный импорт архивов из Mail.ru, Яндекса и Timeweb.
           Выгрузите письма из почтового клиента в .eml или .mbox и загрузите сюда.
           Письма будут сгруппированы по содержимому, а оригиналы останутся на серверах.
           Пароли приложений здесь не нужны.</p>
        <form onSubmit={(event) => void submit(event, async () => {
          if (!archiveFiles.length) throw new Error('Выберите файлы писем');
          let received = 0, imported = 0, alreadyPresent = 0;
          for (let index = 0; index < archiveFiles.length; index++) {
            setArchiveResult(`Загрузка файла ${index + 1} из ${archiveFiles.length}: ${archiveFiles[index].name}`);
            const result = await uploadMailArchive(archiveAddress, archiveFiles[index]);
            received += result.received;
            imported += result.imported;
            alreadyPresent += result.already_present;
          }
          setArchiveResult(
            `Получено: ${received}; добавлено: ${imported}; ранее загружено: ${alreadyPresent}`,
          );
          setArchiveFiles([]);
          onImport?.();
          if (sourceOwner === currentUserId) {
            setAccounts(await getConnectedAccounts(currentUserId));
          }
        }, 'Письма загружены; пересылка и отправка отключены')}>
          <label>Адрес исходного почтового ящика
            <input type="email" required value={archiveAddress}
              onChange={(event) => setArchiveAddress(event.target.value)}
              placeholder="zakaz-pmtk@yandex.ru" autoComplete="off" />
          </label>
          <label>Экспортированные письма (.eml или .mbox, до 45 МБ на файл; можно несколько)
            <input type="file" required multiple accept=".eml,.mbox" key={archiveFiles.length ? archiveFiles.map((f) => f.name).join(":") : "cleared"}
              onChange={(event) => setArchiveFiles(Array.from(event.target.files || []))} />
          </label>
          <button type="submit" disabled={busy || !archiveAddress || archiveFiles.length === 0}>Загрузить и разобрать</button>
        </form>
        {archiveResult && <p role="status" className="mail-admin-notice">{archiveResult}</p>}
        <small>Автоматическое подключение к IMAP будет добавлено отдельно.
          Загрузка архива не выдаёт право удалять или отправлять письма.</small>
      </section>
      <div className="mail-admin-grid">
        <section className="mail-admin-card">
          <h3>Пользователи</h3>
          <form onSubmit={(event) => void submit(event, async () => {
            await createOrgMailUser(newUser);
            setNewUser({ user_id: '', email: '', display_name: '', role: 'member' });
          }, 'Пользователь добавлен')}>
            <label>Идентификатор из системы входа
              <input required value={newUser.user_id} onChange={(event) =>
                setNewUser({ ...newUser, user_id: event.target.value })} /></label>
            <label>Имя
              <input required value={newUser.display_name} onChange={(event) =>
                setNewUser({ ...newUser, display_name: event.target.value })} /></label>
            <label>Email пользователя
              <input required type="email" value={newUser.email} onChange={(event) =>
                setNewUser({ ...newUser, email: event.target.value })} /></label>
            <label>Роль
              <select value={newUser.role} onChange={(event) =>
                setNewUser({ ...newUser, role: event.target.value as 'member' | 'admin' })}>
                <option value="member">Сотрудник</option><option value="admin">Администратор</option>
              </select></label>
            <button disabled={busy}>Создать пользователя</button>
          </form>
          {users.map((user) => (
            <div key={user.user_id} className="mail-admin-item">
              <strong>{user.display_name}</strong><small>{user.email} · {user.role} ·
                {user.active ? ' активен' : ' отключён'}</small>
              {user.user_id !== currentUserId && user.role !== 'owner' &&
                <button type="button" disabled={busy} onClick={() =>
                  void submit({ preventDefault() {} } as FormEvent, () =>
                    setOrgMailUserStatus(user.user_id, !user.active), 'Статус пользователя изменён')}>
                  {user.active ? 'Отключить' : 'Активировать'}
                </button>}
            </div>
          ))}
        </section>
        <section className="mail-admin-card">
          <h3>Назначение почтовых ящиков</h3>
          <p>Подключите Gmail/Outlook через OAuth или загрузите архив .eml/.mbox выше.
             Затем назначьте этот ящик конкретному сотруднику.</p>
          <label>Владелец подключения
            <select value={sourceOwner} onChange={(event) => setSourceOwner(event.target.value)}>
              {users.filter((user) => user.active).map((user) =>
                <option key={user.user_id} value={user.user_id}>{user.display_name}</option>)}
            </select>
          </label>
          <label>Подключённый ящик
            <select value={sourceAccount} onChange={(event) => setSourceAccount(event.target.value)}>
              <option value="">Выберите почту</option>
              {accounts.map((item) => <option key={item.provider + item.account_id}
                value={item.account_id}>{item.address} ({item.provider})</option>)}
            </select>
          </label>
          <form onSubmit={(event) => void submit(event, async () => {
            if (!account || !targetUser) throw new Error('Укажите почту и пользователя');
            if (account.provider === 'archive' && canForward)
              throw new Error('Импортированные архивы доступны только для чтения');
            await assignMailAccount({ owner_user_id: sourceOwner,
              provider: account.provider, account_id: account.account_id,
              recipient_user_id: targetUser, can_forward: canForward });
          }, 'Почтовый ящик назначен')}>
            <label>Кому предоставить доступ
              <select required value={targetUser} onChange={(event) => setTargetUser(event.target.value)}>
                <option value="">Выберите сотрудника</option>
                {users.filter((user) => user.active).map((user) =>
                  <option key={user.user_id} value={user.user_id}>{user.display_name}</option>)}
              </select>
            </label>
            <label className="mail-admin-check">
              <input type="checkbox" checked={canForward} onChange={(event) => setCanForward(event.target.checked)} />
              Разрешить подтверждать пересылку из этого ящика (не для архивов)
            </label>
            <button disabled={busy || !account || !targetUser}>Назначить ящик</button>
          </form>
          {grants.map((grant) => (
            <div key={[grant.owner_user_id, grant.provider, grant.account_id, grant.recipient_user_id].join(':')}
              className="mail-admin-item">
              <strong>{grant.address}</strong>
              <small>{users.find((u) => u.user_id === grant.recipient_user_id)?.display_name ||
                grant.recipient_user_id}{grant.can_forward ? ' · может пересылать' : ' · только чтение'}</small>
              <button disabled={busy} type="button" onClick={() =>
                void submit({ preventDefault() {} } as FormEvent,
                  () => revokeMailAccount(grant), 'Доступ отозван')}>
                Отозвать
              </button>
            </div>
          ))}
        </section>
        <section className="mail-admin-card">
          <h3>Распознавание и пересылка</h3>
          <p>Сервис проверяет тему, текст письма и при выборе вложения. Для автоматического
             режима требуется явное разрешение; нераспознанные вложения всегда проверяются человеком.</p>
          <form onSubmit={(event) => void submit(event, async () => {
            if (!account) throw new Error('Выберите почтовый ящик');
            if (account.provider === 'archive')
              throw new Error('Пересылка из импортированного архива отключена');
            if (newRule.mode === 'auto' && !window.confirm(
              `Включить автоматическую пересылку с ${account.address} на ${newRule.destination}?`,
            )) return;
            await createMailRoutingRule({
              ...newRule, owner_user_id: sourceOwner, provider: account.provider,
              account_id: account.account_id,
            });
            setNewRule({ match_text: '', destination: '', scan_attachments: false, mode: 'review' });
          }, 'Правило распознавания добавлено')}>
            <label>Ключевая фраза (или * для всех писем)
              <input required value={newRule.match_text} onChange={(event) =>
                setNewRule({ ...newRule, match_text: event.target.value })} /></label>
            <label>Куда пересылать
              <input type="email" required value={newRule.destination} onChange={(event) =>
                setNewRule({ ...newRule, destination: event.target.value })} /></label>
            <label className="mail-admin-check">
              <input type="checkbox" checked={newRule.scan_attachments}
                onChange={(event) => setNewRule({ ...newRule, scan_attachments: event.target.checked })} />
              Искать текст во вложениях (PDF и изображения)
            </label>
            <label>Режим
              <select value={newRule.mode} onChange={(event) =>
                setNewRule({ ...newRule, mode: event.target.value as 'review' | 'auto' })}>
                <option value="review">После подтверждения</option>
                <option value="auto">Автоматически</option>
              </select>
            </label>
            <button disabled={busy || !account || account.provider === 'archive'}>Сохранить правило</button>
          </form>
          {rules.map((rule) => (
            <div key={rule.rule_id} className="mail-admin-item">
              <strong>{rule.match_text} → {rule.destination}</strong>
              <small>{rule.provider} · {rule.mode === 'auto' ? 'Автоматически' : 'С подтверждением'} ·
                {rule.enabled ? ' включено' : ' отключено'}</small>
              <button type="button" disabled={busy} onClick={() =>
                void submit({ preventDefault() {} } as FormEvent,
                  () => setMailRoutingRuleStatus(rule.rule_id, !rule.enabled),
                  'Правило обновлено')}>
                {rule.enabled ? 'Отключить правило' : 'Включить правило'}
              </button>
            </div>
          ))}
        </section>
      </div>
      <ForwardReview grants={grants.filter((grant) => grant.recipient_user_id === currentUserId)} />
    </section>
  );
}
