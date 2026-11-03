export function Spinner({ size = 20 }: { size?: number }) {
  return (
    <span
      className="inline-block animate-[spin_0.7s_linear_infinite] rounded-[50%] border-[2.5px] border-solid border-line border-t-primary shadow-[0_0_12px_var(--primary-glow)]"
      style={{ width: size, height: size, borderWidth: Math.max(2, Math.round(size / 8)) }}
      role="status"
      aria-label="Loading"
    />
  );
}
