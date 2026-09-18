import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bell,
  ChevronRight,
  CircleAlert,
  RefreshCw,
  Trash2,
} from "lucide-react";
import * as api from "./api";
import type { Paginated, Subscription, SubscriptionDetail } from "./types";
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

export function SubscriptionsPage({
  setNotice,
}: {
  setNotice: (text: string) => void;
}) {
  const [data, setData] = useState<Paginated<Subscription> | null>(null);
  const [filters, setFilters] = useState({
    status: "",
    user_id: "",
    guild_id: "",
    channel_id: "",
    theater_id: "",
    show_date: "",
    keyword: "",
  });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<SubscriptionDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Subscription | null>(null);
  const loadGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const load = useCallback(() => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    return api
      .getSubscriptions({ ...filters, page, page_size: PAGE_SIZE })
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
  async function openDetail(item: Subscription) {
    const generation = ++detailGeneration.current;
    setSelected(null);
    setError("");
    try {
      const detail = await api.getSubscription(item.id);
      if (generation === detailGeneration.current) {
        setSelected(detail);
        setError("");
      }
    } catch (cause) {
      if (generation === detailGeneration.current)
        setError(errorMessage(cause));
    }
  }
  async function remove() {
    if (!deleteTarget) return;
    await api.deleteSubscription(deleteTarget.id);
    setDeleteTarget(null);
    setSelected(null);
    setError("");
    setNotice("구독을 삭제했습니다.");
    void load();
  }
  function changeFilter(key: keyof typeof filters, value: string) {
    ++detailGeneration.current;
    setSelected(null);
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }
  return (
    <>
      <div className="page-intro">
        <div>
          <p className="muted">총 {data?.total ?? 0}건</p>
          <h2>등록된 구독</h2>
        </div>
        <button className="secondary-button" onClick={() => void load()}>
          <RefreshCw size={16} />
          새로고침
        </button>
      </div>
      <div className="filter-bar">
        <input
          placeholder="영화 키워드"
          aria-label="영화 키워드"
          value={filters.keyword}
          onChange={(event) => changeFilter("keyword", event.target.value)}
        />
        <select
          aria-label="상태 필터"
          value={filters.status}
          onChange={(event) => changeFilter("status", event.target.value)}
        >
          <option value="">모든 상태</option>
          <option value="active">활성</option>
          <option value="expired">만료</option>
        </select>
        <input
          placeholder="사용자 ID"
          aria-label="사용자 ID"
          value={filters.user_id}
          onChange={(event) => changeFilter("user_id", event.target.value)}
        />
        <input
          placeholder="서버 ID"
          aria-label="서버 ID"
          value={filters.guild_id}
          onChange={(event) => changeFilter("guild_id", event.target.value)}
        />
        <input
          placeholder="채널 ID"
          aria-label="채널 ID"
          value={filters.channel_id}
          onChange={(event) => changeFilter("channel_id", event.target.value)}
        />
        <input
          type="date"
          aria-label="상영일"
          value={filters.show_date}
          onChange={(event) => changeFilter("show_date", event.target.value)}
        />
        <input
          placeholder="상영관 ID"
          aria-label="상영관 ID"
          value={filters.theater_id}
          onChange={(event) => changeFilter("theater_id", event.target.value)}
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
          <SubscriptionTable
            items={data.items}
            onSelect={(item) => void openDetail(item)}
          />
        ) : (
          data && <Empty icon={<Bell />} text="등록된 구독이 없습니다." />
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
        <SubscriptionDetailModal
          item={selected}
          onClose={() => setSelected(null)}
          onDelete={() => setDeleteTarget(selected)}
        />
      )}
      {deleteTarget && (
        <ConfirmModal
          title="구독을 삭제할까요?"
          description="구독과 관련된 발송 기록도 함께 정리됩니다."
          confirmLabel="삭제하기"
          danger
          onClose={() => setDeleteTarget(null)}
          onConfirm={remove}
        />
      )}
    </>
  );
}

function SubscriptionTable({
  items,
  onSelect,
}: {
  items: Subscription[];
  onSelect: (item: Subscription) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>대상</th>
            <th>상영관 / 날짜</th>
            <th>키워드</th>
            <th>상태</th>
            <th>최근 성공</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} onClick={() => onSelect(item)}>
              <td>
                <strong>{displayName(item.user_name, item.user_id)}</strong>
                <small>
                  {displayName(item.guild_name, item.guild_id)} ·{" "}
                  {displayName(item.channel_name, item.channel_id)}
                </small>
              </td>
              <td>
                <strong>{item.theater_name || item.theater_id}</strong>
                <small>{item.show_date}</small>
              </td>
              <td>{item.keyword || "모든 영화"}</td>
              <td>
                <StatusPill status={item.status} />
              </td>
              <td>{formatTime(item.last_success_at)}</td>
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

function SubscriptionDetailModal({
  item,
  onClose,
  onDelete,
}: {
  item: SubscriptionDetail;
  onClose: () => void;
  onDelete: () => void;
}) {
  return (
    <Modal title="구독 상세" onClose={onClose}>
      <div className="detail-head">
        <div>
          <StatusPill status={item.status} />
          <h2>{item.theater_name || item.theater_id}</h2>
          <p className="muted">
            {item.show_date} · {item.keyword || "모든 영화"}
          </p>
        </div>
        <button className="danger-button" onClick={onDelete}>
          <Trash2 size={16} />
          삭제
        </button>
      </div>
      <dl className="detail-grid">
        <Detail label="구독 ID" value={item.id} />
        <Detail label="사용자 ID" value={item.user_id} />
        <Detail label="채널 ID" value={item.channel_id} />
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
        <Detail label="생성일" value={formatTime(item.created_at)} />
        <Detail label="만료일" value={formatTime(item.expires_at)} />
        <Detail label="최근 성공" value={formatTime(item.last_success_at)} />
        <Detail label="대기 알림" value={`${item.pending_count}건`} />
        <Detail label="실패 알림" value={`${item.failed_count}건`} />
      </dl>
      {item.last_error && (
        <div className="error-box">
          <CircleAlert size={17} />
          <span>{item.last_error}</span>
        </div>
      )}
      <div className="detail-section">
        <h3>
          관찰한 영화 <span>{item.movies.length}</span>
        </h3>
        {item.movies.length ? (
          <p className="movie-list">{item.movies.join(" · ")}</p>
        ) : (
          <p className="muted">아직 확인된 영화가 없습니다.</p>
        )}
      </div>
      <div className="detail-section">
        <h3>
          관련 알림 <span>{item.notifications.length}</span>
        </h3>
        {item.notifications.length ? (
          <div className="mini-list">
            {item.notifications.map((notice) => (
              <div key={notice.id}>
                <StatusPill status={notice.status} />
                <span>{formatTime(notice.created_at)}</span>
                <small>{notice.movie_titles.join(", ")}</small>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">관련 알림이 없습니다.</p>
        )}
      </div>
    </Modal>
  );
}
