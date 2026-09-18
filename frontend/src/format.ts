import { ApiError, clearSession } from "./api";

export function displayName(
  name: string | null | undefined,
  id: string | null,
) {
  return name || (id ? `ID ${id}` : "개인 DM");
}

export function formatTime(value?: string | null) {
  if (!value) return "없음";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function errorMessage(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) {
    clearSession();
    return "세션이 만료되었습니다. 새로고침 후 다시 로그인하세요.";
  }
  return cause instanceof Error
    ? cause.message
    : "데이터를 불러오지 못했습니다.";
}
