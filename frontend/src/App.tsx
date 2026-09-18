import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Bell,
  Film,
  LayoutDashboard,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import * as api from "./api";
import { ApiError } from "./api";
import type { Page } from "./types";
import { OverviewPage } from "./OverviewPage";
import { SubscriptionsPage } from "./SubscriptionsPage";
import { NotificationsPage } from "./NotificationsPage";

export function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [loginError, setLoginError] = useState("");
  useEffect(() => {
    void api
      .session()
      .then(setAuthenticated)
      .catch(() => setAuthenticated(false));
  }, []);

  if (authenticated === null)
    return (
      <div className="center-screen">
        <div className="spinner" />
      </div>
    );
  if (!authenticated)
    return (
      <Login
        onSuccess={() => setAuthenticated(true)}
        error={loginError}
        setError={setLoginError}
      />
    );
  return <Dashboard onLogout={() => setAuthenticated(false)} />;
}

function Login({
  onSuccess,
  error,
  setError,
}: {
  onSuccess: () => void;
  error: string;
  setError: (value: string) => void;
}) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!password) return setError("비밀번호를 입력하세요.");
    setLoading(true);
    setError("");
    try {
      await api.login(password);
      onSuccess();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 429) {
        setError("잠시 후 다시 시도하세요.");
      } else if (cause instanceof ApiError && cause.status === 401) {
        setError("비밀번호가 올바르지 않습니다.");
      } else {
        setError("서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.");
      }
    } finally {
      setLoading(false);
    }
  }
  return (
    <main className="login-page">
      <section className="login-brand" aria-label="CGV Push 소개">
        <div className="login-wordmark">
          <Film size={25} />
          <span>CGV</span> Push
        </div>
        <div className="login-story">
          <p className="eyebrow">MOVIE ALERT MANAGER</p>
          <h2>
            기다리던 영화의 시작,
            <br />
            놓치지 않도록.
          </h2>
          <p>
            상영 일정부터 알림 발송까지.
            <br />
            CGV Push의 모든 구독을 한곳에서 관리하세요.
          </p>
        </div>
        <footer>CGV PUSH · MANAGEMENT CONSOLE</footer>
      </section>
      <div className="login-form-area">
        <form className="login-card" onSubmit={submit}>
          <div className="brand-mark">
            <Film size={22} />
          </div>
          <p className="eyebrow">CGV PUSH</p>
          <h1>관리 대시보드</h1>
          <p className="muted">관리자 비밀번호를 입력해 계속하세요.</p>
          <label htmlFor="password">비밀번호</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            maxLength={1024}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
          />
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button
            className="primary-button wide"
            type="submit"
            disabled={loading}
          >
            {loading ? "확인 중…" : "로그인"}
          </button>
          <p className="login-note">관리자 전용 공간입니다.</p>
        </form>
      </div>
    </main>
  );
}

function Dashboard({ onLogout }: { onLogout: () => void }) {
  const [page, setPage] = useState<Page>("overview");
  const [menuOpen, setMenuOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const navigate = (next: Page) => {
    setPage(next);
    setMenuOpen(false);
    setNotice("");
  };
  useEffect(() => {
    const expire = () => onLogout();
    window.addEventListener("dashboard-auth-expired", expire);
    return () => window.removeEventListener("dashboard-auth-expired", expire);
  }, [onLogout]);
  async function logout() {
    try {
      await api.logout();
      onLogout();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) return;
      setNotice("로그아웃하지 못했습니다. 네트워크 상태를 확인하세요.");
    }
  }
  return (
    <div className="app-shell">
      <aside className={menuOpen ? "sidebar open" : "sidebar"}>
        <div className="sidebar-brand">
          <span className="brand-dot">
            <Film size={17} />
          </span>
          <span>CGV Push</span>
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="주 메뉴">
          <NavItem
            icon={<LayoutDashboard size={18} />}
            label="개요"
            active={page === "overview"}
            onClick={() => navigate("overview")}
          />
          <NavItem
            icon={<Bell size={18} />}
            label="구독"
            active={page === "subscriptions"}
            onClick={() => navigate("subscriptions")}
          />
          <NavItem
            icon={<Activity size={18} />}
            label="알림 내역"
            active={page === "notifications"}
            onClick={() => navigate("notifications")}
          />
        </nav>
        <div className="sidebar-footer">
          <button className="nav-item" onClick={() => void logout()}>
            <LogOut size={18} />
            로그아웃
          </button>
          <p className="sidebar-caption">CGV PUSH · ADMIN</p>
        </div>
      </aside>
      {menuOpen && (
        <button
          className="scrim"
          aria-label="메뉴 닫기"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <main className="content">
        <header className="topbar">
          <button
            className="menu-button"
            aria-label="메뉴"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            <Menu size={21} />
          </button>
          <div>
            <p className="eyebrow">관리 대시보드</p>
            <h1>
              {page === "overview"
                ? "개요"
                : page === "subscriptions"
                  ? "구독 관리"
                  : "알림 내역"}
            </h1>
          </div>
          <div className="topbar-spacer" />
          <StatusDot />
        </header>
        {notice && (
          <div className="toast" role="status">
            {notice}
            <button aria-label="알림 닫기" onClick={() => setNotice("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {page === "overview" && <OverviewPage onNavigate={navigate} />}
        {page === "subscriptions" && (
          <SubscriptionsPage setNotice={setNotice} />
        )}
        {page === "notifications" && (
          <NotificationsPage setNotice={setNotice} />
        )}
      </main>
    </div>
  );
}

function NavItem({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={active ? "nav-item active" : "nav-item"}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
    >
      {icon}
      {label}
    </button>
  );
}

function StatusDot() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const requestGeneration = useRef(0);
  const load = useCallback(() => {
    const generation = ++requestGeneration.current;
    void api
      .getOverview()
      .then((data) => {
        if (generation === requestGeneration.current) {
          setConnected(data.bot_connected);
        }
      })
      .catch(() => {
        if (generation === requestGeneration.current) setConnected(false);
      });
  }, []);
  useEffect(() => {
    load();
    const timer = window.setInterval(() => {
      if (!document.hidden) load();
    }, 15000);
    const refreshWhenVisible = () => {
      if (!document.hidden) load();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [load]);
  return (
    <div className="connection">
      <span className={connected ? "status-dot online" : "status-dot"} />
      {connected === null
        ? "연결 확인 중"
        : connected
          ? "봇 연결됨"
          : "봇 연결 끊김"}
    </div>
  );
}
