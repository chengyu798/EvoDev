// 显示服务或模块的简短状态。
type StatusBadgeProps = {
  label: string;
  tone: "ready" | "pending" | "offline";
};

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${tone}`}>
      <span className="status-badge__dot" aria-hidden="true" />
      {label}
    </span>
  );
}
