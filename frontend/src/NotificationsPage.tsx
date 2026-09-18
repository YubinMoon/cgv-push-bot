import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, ChevronRight, CircleAlert, RefreshCw } from "lucide-react";
import * as api from "./api";
import type { Notification, Paginated } from "./types";
import {
  ConfirmModal,
  Detail,
  Empty,
  InlineError,
  Modal,
  Pagination,
  StatusPill,
} from "./components";
import { displayName, errorMessage, formatTime } from "./format";
const PAGE_SIZE = 25;

export function NotificationsPage({
  setNotice,
}: {
  setNotice: (text: string) => void;
}) {
  const [data, setData] = useState<Paginated<Notification> | null>(null);
  const [filters, setFilters] = useState({ status: "", subscription_id: "" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Notification | null>(null);
  const [retryTarget, setRetryTarget] = useState<Notification | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const loadGeneration = useRef(0);
  const load = useCallback(() => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    return api
      .getNotifications({ ...filters, page, page_size: PAGE_SIZE })
      .then((result) => {
        if (generation === loadGeneration.current) {
          setData(result);
          setPage((current) =>
            Math.min(current, Math.max(1, Math.ceil(result.total / PAGE_SIZE))),
          );
          setError("");
        }
        return result;
      })
      .catch((cause) => {
        if (generation === loadGeneration.current)
          setError(errorMessage(cause));
      })
      .finally(() => {
        if (generation === loadGeneration.current) setLoading(false);
      });
  }, [filters, page]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);
  async function retry() {
    if (!retryTarget) return;
    await api.retryNotification(retryTarget.id);
    setRetryTarget(null);
    setSelected(null);
    setError("");
    setNotice("재시도를 접수했습니다.");
    void load();
  }
  function changeFilter(key: keyof typeof filters, value: string) {
    setSelected(null);
    setRetryTarget(null);
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }
  return (
    <>
      <div className="page-intro">
        <div>
          <p className="muted">총 {data?.total ?? 0}건</p>
          <h2>알림 내역</h2>
        </div>
        <button className="secondary-button" onClick={() => void load()}>
          <RefreshCw size={16} />
          새로고침
        </button>
      </div>
      <div className="filter-bar">
        <select
          aria-label="상태 필터"
          value={filters.status}
          onChange={(event) => changeFilter("status", event.target.value)}
        >
          <option value="">모든 상태</option>
          <option value="pending">대기 중</option>
          <option value="sent">발송 완료</option>
          <option value="failed">실패</option>
        </select>
        <input
          placeholder="구독 ID"
          aria-label="구독 ID"
          value={filters.subscription_id}
          onChange={(event) =>
            changeFilter("subscription_id", event.target.value)
          }
        />
      </div>
      {error && <InlineError message={error} />}
      <div className="panel table-panel">
        {loading && (
          <div className="table-loading">
            <div className="spinner small" />
          </div>
        )}
        {data && data.items.length > 0 ? (
          <NotificationTable
            items={data.items}
            onSelect={setSelected}
            onRetry={setRetryTarget}
          />
        ) : (
          data && <Empty icon={<Activity />} text="알림 내역이 없습니다." />
        )}
        {data && (
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={data.total}
            onChange={setPage}
          />
        )}
      </div>
      {selected && (
        <NotificationDetailModal
          item={selected}
          onClose={() => setSelected(null)}
          onRetry={() => setRetryTarget(selected)}
        />
      )}
      {retryTarget && (
        <ConfirmModal
          title="알림을 다시 시도할까요?"
          description="추가 1회 발송을 접수합니다. 발견 시각과 기존 시도 횟수는 유지됩니다."
          confirmLabel="재시도 접수"
          onClose={() => setRetryTarget(null)}
          onConfirm={retry}
        />
      )}
    </>
  );
}

function NotificationTable({
  items,
  onSelect,
  onRetry,
}: {
  items: Notification[];
  onSelect: (item: Notification) => void;
  onRetry: (item: Notification) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>영화</th>
            <th>대상</th>
            <th>상영관 / 날짜</th>
            <th>상태</th>
            <th>발견 시각</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} onClick={() => onSelect(item)}>
              <td>
                <strong>{item.movie_titles[0] || "영화 정보 없음"}</strong>
                <small>
                  {item.movie_titles.length > 1
                    ? `외 ${item.movie_titles.length - 1}편`
                    : ""}
                </small>
              </td>
              <td>
                <strong>{displayName(item.user_name, item.user_id)}</strong>
                <small>{displayName(item.channel_name, item.channel_id)}</small>
              </td>
              <td>
                <strong>{item.theater_name || "알 수 없는 상영관"}</strong>
                <small>{item.show_date}</small>
              </td>
              <td>
                <StatusPill status={item.status} />
                {item.status === "failed" && (
                  <button
                    className="table-action"
                    onClick={(event) => {
                      event.stopPropagation();
                      onRetry(item);
                    }}
                  >
                    재시도
                  </button>
                )}
              </td>
              <td>{formatTime(item.created_at)}</td>
              <td>
                <button
                  className="row-detail"
                  aria-label={`상세 보기 ${item.id}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(item);
                  }}
                >
                  <ChevronRight size={17} className="row-arrow" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NotificationDetailModal({
  item,
  onClose,
  onRetry,
}: {
  item: Notification;
  onClose: () => void;
  onRetry: () => void;
}) {
  return (
    <Modal title="알림 상세" onClose={onClose}>
      <div className="detail-head">
        <div>
          <StatusPill status={item.status} />
          <h2>{item.movie_titles.join(", ") || "영화 정보 없음"}</h2>
          <p className="muted">발견 {formatTime(item.created_at)}</p>
        </div>
        {item.status === "failed" && (
          <button className="primary-button" onClick={onRetry}>
            재시도
          </button>
        )}
      </div>
      <dl className="detail-grid">
        <Detail label="알림 ID" value={item.id} />
        <Detail label="구독 ID" value={item.subscription_id} />
        <Detail label="사용자 ID" value={item.user_id} />
        <Detail
          label="사용자"
          value={displayName(item.user_name, item.user_id)}
        />
        <Detail
          label="서버"
          value={displayName(item.guild_name, item.guild_id)}
        />
        <Detail
          label="채널"
          value={displayName(item.channel_name, item.channel_id)}
        />
        <Detail label="상영관" value={item.theater_name || "알 수 없음"} />
        <Detail label="상영일" value={item.show_date} />
        <Detail label="시도 횟수" value={`${item.attempts}회`} />
        <Detail label="발송 시각" value={formatTime(item.sent_at)} />
        <Detail label="다음 재시도" value={formatTime(item.next_retry_at)} />
      </dl>
      {item.last_error && (
        <div className="error-box">
          <CircleAlert size={17} />
          <span>{item.last_error}</span>
        </div>
      )}
    </Modal>
  );
}
