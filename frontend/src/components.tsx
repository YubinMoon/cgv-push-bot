import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, CircleAlert, X } from "lucide-react";
import type { Status } from "./types";
import { errorMessage } from "./format";

export function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function StatusPill({ status }: { status: Status }) {
  const labels: Record<Status, string> = {
    active: "활성",
    expired: "만료",
    pending: "대기 중",
    sent: "발송 완료",
    failed: "실패",
  };
  return <span className={`pill ${status}`}>{labels[status]}</span>;
}

export function Pagination({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pagination">
      <span>
        {total
          ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} / ${total}`
          : "0건"}
      </span>
      <div>
        <button
          aria-label="이전 페이지"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          <ChevronLeft size={16} />
        </button>
        <strong>
          {page} / {pages}
        </strong>
        <button
          aria-label="다음 페이지"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}

export function Loading() {
  return (
    <div className="loading-state">
      <div className="spinner" />
      <span>불러오는 중…</span>
    </div>
  );
}

export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="loading-state">
      <CircleAlert size={30} />
      <p>{message}</p>
      <button className="secondary-button" onClick={retry}>
        다시 시도
      </button>
    </div>
  );
}

export function InlineError({ message }: { message: string }) {
  return (
    <div className="inline-error" role="alert">
      <CircleAlert size={16} />
      {message}
    </div>
  );
}

export function Empty({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="empty-state">
      {icon}
      <p>{text}</p>
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const dialog = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const panel = dialog.current;
    panel?.focus();
    function handleKey(event: KeyboardEvent) {
      const dialogs = document.querySelectorAll('[role="dialog"]');
      if (dialogs.item(dialogs.length - 1) !== panel) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
      }
      if (event.key !== "Tab") return;
      const controls = panel?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]',
      );
      if (!controls?.length) {
        event.preventDefault();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (
        event.shiftKey &&
        (document.activeElement === first || document.activeElement === panel)
      ) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last || document.activeElement === panel)
      ) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      previousFocus?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialog}
        tabIndex={-1}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-title">
          <h2>{title}</h2>
          <button aria-label="닫기" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

export function ConfirmModal({
  title,
  description,
  confirmLabel,
  danger,
  onClose,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function confirm() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await onConfirm();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={title}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <p className="confirm-description">{description}</p>
      {error && <InlineError message={error} />}
      <div className="modal-actions">
        <button className="secondary-button" onClick={onClose} disabled={busy}>
          취소
        </button>
        <button
          className={danger ? "danger-button" : "primary-button"}
          onClick={() => void confirm()}
          disabled={busy}
        >
          {busy ? "처리 중…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
