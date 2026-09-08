import { useEffect, useMemo, useState } from 'react';
import { beginMailAuthorization, bootstrap, getUnifiedInbox, type BootstrapResponse, type MailMessage } from './api';

function detectPlatform(): 'mac' | 'iphone' {
  return /iPhone|iPod/i.test(navigator.userAgent) ? 'iphone' : 'mac';
}

export default function App() {
  const platform = useMemo(detectPlatform, []);
  const [boot, setBoot] = useState<BootstrapResponse | null>(null);
  const [mail, setMail] = useState<MailMessage[]>([]);
  const [active, setActive] = useState('main_agent');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([bootstrap(platform), getUnifiedInbox()])
      .then(([b, m]) => {
        setBoot(b);
        setMail(m);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка загрузки'));
  }, [platform]);

  async function connect(provider: 'gmail' | 'outlook') {
    try {
      const { authorization_url } = await beginMailAuthorization(provider);
      window.location.assign(authorization_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось начать авторизацию');
    }
  }

  const nav = boot?.manifest.navigation ?? [
    { module_id: 'main_agent', title: 'Главный агент', routes: ['/agent'] },
    { module_id: 'mail', title: 'Почта', routes: ['/mail'] },
    { module_id: 'finance', title: 'Финансы', routes: ['/finance'] },
    { module_id: 'fleet', title: 'Автопарк', routes: ['/fleet'] },
    { module_id: 'sales', title: 'Продажи', routes: ['/sales'] },
    { module_id: 'marketing', title: 'Маркетинг', routes: ['/marketing'] },
    { module_id: 'procurement', title: 'Закупки', routes: ['/procurement'] },
    { module_id: 'tasks', title: 'Задачи', routes: ['/tasks'] },
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Главный агент</div>
        <nav>
          {nav.map((item) => (
            <button key={item.module_id} className={active === item.module_id ? 'active' : ''} onClick={() => setActive(item.module_id)}>
              <span>{item.title}</span>
              {item.module_id === 'mail' && boot?.mail.unread_count ? <b>{boot.mail.unread_count}</b> : null}
            </button>
          ))}
        </nav>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <strong>{nav.find((x) => x.module_id === active)?.title ?? 'Главный агент'}</strong>
            <small>{platform === 'iphone' ? 'iPhone' : 'Mac'} · единый контур</small>
          </div>
          <button className="agent-button" onClick={() => setActive('main_agent')}>Спросить агента</button>
        </header>

        {error ? <div className="error">{error}</div> : null}

        {active === 'main_agent' && (
          <section className="agent-panel">
            <div className="hero-card">
              <p className="eyebrow">Центральное управление</p>
              <h1>Что нужно сделать?</h1>
              <textarea placeholder="Например: найди запчасть по VIN, проверь новые счета и покажи расходы по автомобилям…" />
              <button>Отправить Главному агенту</button>
            </div>
            <div className="status-grid">
              <article><span>Почта</span><strong>{boot?.mail.unread_count ?? '—'}</strong><small>непрочитанных</small></article>
              <article><span>Подключено почт</span><strong>{boot?.mail.accounts.length ?? '—'}</strong><small>единая лента</small></article>
              <article><span>Устройство</span><strong>{platform === 'iphone' ? 'iPhone' : 'Mac'}</strong><small>общий backend</small></article>
            </div>
          </section>
        )}

        {active === 'mail' && (
          <section className="mail-layout">
            <div className="mail-toolbar">
              <div>
                <h2>Все входящие</h2>
                <p>Gmail, Outlook и другие подключённые ящики в одной ленте</p>
              </div>
              <div className="connect-actions">
                <button onClick={() => connect('gmail')}>+ Gmail</button>
                <button onClick={() => connect('outlook')}>+ Outlook</button>
              </div>
            </div>
            <div className="mail-list">
              {mail.length === 0 ? (
                <div className="empty-state">Подключите почту или выполните синхронизацию.</div>
              ) : mail.map((item) => (
                <article key={item.email_id} className={item.unread ? 'mail-row unread' : 'mail-row'}>
                  <div className="mail-source">{item.account_id}</div>
                  <div className="mail-content">
                    <strong>{item.sender}</strong>
                    <span>{item.subject || '(без темы)'}</span>
                    <small>{item.classification || 'не классифицировано'}</small>
                  </div>
                  <time>{new Date(item.received_at).toLocaleString('ru-RU')}</time>
                </article>
              ))}
            </div>
          </section>
        )}

        {!['main_agent', 'mail'].includes(active) && (
          <section className="placeholder">
            <h2>{nav.find((x) => x.module_id === active)?.title}</h2>
            <p>Модуль подключён к общей навигации. Следующий шаг — вывести его рабочие данные через общий API.</p>
          </section>
        )}
      </main>
    </div>
  );
}
