import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Bell,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  RefreshCw,
} from "lucide-react";
import * as api from "./api";
import type { Overview, Page } from "./types";
import { ErrorState, Loading } from "./components";
import { errorMessage } from "./format";

export function OverviewPage({
  onNavigate,
}: {
  onNavigate: (page: Page) => void;
}) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const loadGeneration = useRef(0);
  const load = useCallback(() => {
    const generation = ++loadGeneration.current;
    return api
      .getOverview()
      .then((result) => {
        if (generation === loadGeneration.current) {
          setData(result);
          setError("");
        }
        return result;
      })
      .catch((cause) => {
        if (generation === loadGeneration.current)
          setError(errorMessage(cause));
      });
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);
  if (error) return <ErrorState message={error} retry={() => void load()} />;
  if (!data) return <Loading />;
  return (
    <>
      <div className="page-intro">
        <div>
          <p className="muted">실시간 운영 현황</p>
          <h2>구독과 발송 현황을 한눈에.</h2>
        </div>
        <button className="secondary-button" onClick={() => void load()}>
          <RefreshCw size={16} />
          새로고침
        </button>
      </div>
      <section className="stats-grid">
        <StatCard
          icon={<Bell />}
          label="활성 구독"
          value={data.active_subscriptions}
          accent
        />
        <StatCard
          icon={<Activity />}
          label="대기 중 알림"
          value={data.pending_notifications}
        />
        <StatCard
          icon={<CheckCircle2 />}
          label="발송 완료"
          value={data.sent_notifications}
        />
        <StatCard
          icon={<CircleAlert />}
          label="발송 실패"
          value={data.failed_notifications}
          warning={data.failed_notifications > 0}
        />
      </section>
      <section className="overview-grid">
        <DeliverySummary data={data} />
        <div className="panel health-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">SYSTEM HEALTH</p>
              <h3>시스템 상태</h3>
            </div>
            <span
              className={
                data.bot_connected && !data.poll_errors
                  ? "pill success"
                  : "pill danger"
              }
            >
              {data.bot_connected && !data.poll_errors ? "정상" : "확인 필요"}
            </span>
          </div>
          <div className="health-row">
            <span>Discord 봇</span>
            <strong>{data.bot_connected ? "연결됨" : "연결 끊김"}</strong>
          </div>
          <div className="health-row">
            <span>만료된 구독</span>
            <strong>{data.expired_subscriptions}건</strong>
          </div>
          <div className="health-row">
            <span>CGV 조회 오류</span>
            <strong className={data.poll_errors ? "text-danger" : ""}>
              {data.poll_errors}건
            </strong>
          </div>
        </div>
      </section>
      <section className="panel shortcuts">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">QUICK ACCESS</p>
            <h3>바로가기</h3>
          </div>
        </div>
        <div className="shortcut-grid">
          <button onClick={() => onNavigate("subscriptions")}>
            <Bell size={18} />
            <span>
              <strong>구독 관리</strong>
              <small>등록된 구독을 확인하고 관리합니다.</small>
            </span>
            <ChevronRight size={17} />
          </button>
          <button onClick={() => onNavigate("notifications")}>
            <Activity size={18} />
            <span>
              <strong>알림 내역</strong>
              <small>최근 발송 상태와 실패를 확인합니다.</small>
            </span>
            <ChevronRight size={17} />
          </button>
        </div>
      </section>
      <p className="section-note">
        15초마다 자동 갱신 · 보관 중인 전체 기록 기준 · 시각은 한국 표준시(KST)
      </p>
    </>
  );
}

function StatCard({
  icon,
  label,
  value,
  accent,
  warning,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  accent?: boolean;
  warning?: boolean;
}) {
  return (
    <div
      className={
        accent
          ? "stat-card accent"
          : warning
            ? "stat-card warning"
            : "stat-card"
      }
    >
      <div className="stat-icon">{icon}</div>
      <div>
        <p>{label}</p>
        <strong>{value.toLocaleString("ko-KR")}</strong>
      </div>
    </div>
  );
}

function DeliverySummary({ data }: { data: Overview }) {
  const segments = [
    { status: "sent", label: "완료", count: data.sent_notifications },
    { status: "pending", label: "대기", count: data.pending_notifications },
    { status: "failed", label: "실패", count: data.failed_notifications },
  ];
  const total = segments.reduce((sum, item) => sum + item.count, 0);
  return (
    <section className="panel delivery-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">DELIVERY OVERVIEW</p>
          <h3>알림 발송 현황</h3>
        </div>
        <span className="pill">전체 기록</span>
      </div>
      <p className="delivery-total">
        <strong>{total.toLocaleString("ko-KR")}</strong>건의 알림
      </p>
      <div className="delivery-bar" aria-hidden="true">
        {segments
          .filter((item) => item.count > 0)
          .map((item) => (
            <span
              key={item.status}
              className={item.status}
              style={{ flex: item.count }}
            />
          ))}
      </div>
      <div className="delivery-legend">
        {segments.map((item) => (
          <span key={item.status}>
            <i className={`legend-dot ${item.status}`} />
            {item.label}
            <strong>{item.count.toLocaleString("ko-KR")}</strong>
          </span>
        ))}
      </div>
      {total === 0 && (
        <p className="section-note">
          첫 알림이 생성되면 발송 상태가 표시됩니다.
        </p>
      )}
    </section>
  );
}
