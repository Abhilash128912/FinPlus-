import React from 'react';

/** Shared presentation primitives for the Risk Desk, matching the app's dark theme. */

export const C = {
  bg: '#090d16',
  panel: 'rgba(255,255,255,0.03)',
  panelSolid: '#111827',
  border: 'rgba(255,255,255,0.08)',
  accent: '#38bdf8',
  text: '#e2e8f0',
  muted: '#94a3b8',
  dim: '#64748b',
  green: '#10b981',
  red: '#ef4444',
  amber: '#f59e0b',
  violet: '#a78bfa'
};

export const inr = (n, dp = 2) =>
  `₹${(Number(n) || 0).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;

export const pnlColor = n => (Number(n) > 0 ? C.green : Number(n) < 0 ? C.red : C.muted);

export function Panel({ title, subtitle, right, children, accent = C.border, style }) {
  return (
    <div
      style={{
        background: C.panel,
        border: `1px solid ${accent}`,
        borderRadius: '14px',
        padding: '18px',
        ...style
      }}
    >
      {(title || right) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', marginBottom: subtitle ? '4px' : '14px' }}>
          <div>
            {title && <div style={{ fontSize: '14px', fontWeight: 900, color: '#fff' }}>{title}</div>}
            {subtitle && <div style={{ fontSize: '11px', color: C.muted, marginTop: '3px' }}>{subtitle}</div>}
          </div>
          {right}
        </div>
      )}
      {subtitle && <div style={{ height: '10px' }} />}
      {children}
    </div>
  );
}

export function Stat({ label, value, sub, color = '#fff', size = '20px' }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: '10px', color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.4px', marginBottom: '5px' }}>
        {label}
      </div>
      <div style={{ fontSize: size, fontWeight: 900, color, lineHeight: 1.15, wordBreak: 'break-word' }}>{value}</div>
      {sub && <div style={{ fontSize: '10px', color: C.dim, marginTop: '4px' }}>{sub}</div>}
    </div>
  );
}

export function StatGrid({ children, min = '150px' }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(${min}, 1fr))`, gap: '16px' }}>
      {children}
    </div>
  );
}

export function Bar({ used, total, color = C.accent, height = 7 }) {
  const pct = total > 0 ? Math.max(0, Math.min(100, (used / total) * 100)) : 0;
  const over = total > 0 && used > total;
  return (
    <div style={{ background: 'rgba(255,255,255,0.07)', borderRadius: '999px', height: `${height}px`, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: over ? C.red : color, borderRadius: '999px', transition: 'width .3s' }} />
    </div>
  );
}

export function Chip({ children, tone = 'muted' }) {
  const tones = {
    muted: { bg: 'rgba(255,255,255,0.06)', fg: C.muted },
    good: { bg: 'rgba(16,185,129,0.14)', fg: C.green },
    bad: { bg: 'rgba(239,68,68,0.14)', fg: C.red },
    warn: { bg: 'rgba(245,158,11,0.14)', fg: C.amber },
    info: { bg: 'rgba(56,189,248,0.14)', fg: C.accent },
    violet: { bg: 'rgba(167,139,250,0.14)', fg: C.violet }
  };
  const t = tones[tone] || tones.muted;
  return (
    <span style={{ background: t.bg, color: t.fg, fontSize: '10px', fontWeight: 800, padding: '3px 8px', borderRadius: '999px', whiteSpace: 'nowrap' }}>
      {children}
    </span>
  );
}

export function Btn({ children, onClick, tone = 'primary', disabled, style, type = 'button' }) {
  const tones = {
    primary: { bg: C.accent, fg: '#04121c', bd: C.accent },
    ghost: { bg: 'rgba(255,255,255,0.04)', fg: C.text, bd: C.border },
    danger: { bg: 'rgba(239,68,68,0.15)', fg: C.red, bd: 'rgba(239,68,68,0.4)' },
    good: { bg: 'rgba(16,185,129,0.15)', fg: C.green, bd: 'rgba(16,185,129,0.4)' }
  };
  const t = tones[tone] || tones.primary;
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        background: disabled ? 'rgba(255,255,255,0.05)' : t.bg,
        color: disabled ? C.dim : t.fg,
        border: `1px solid ${disabled ? C.border : t.bd}`,
        borderRadius: '9px',
        padding: '9px 15px',
        fontWeight: 800,
        fontSize: '12px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        whiteSpace: 'nowrap',
        ...style
      }}
    >
      {children}
    </button>
  );
}

const fieldBase = {
  width: '100%',
  background: 'rgba(0,0,0,0.35)',
  border: `1px solid ${C.border}`,
  borderRadius: '8px',
  padding: '9px 11px',
  color: '#fff',
  fontSize: '13px',
  fontWeight: 600,
  boxSizing: 'border-box'
};

export function Field({ label, hint, children, required }) {
  return (
    <label style={{ display: 'block' }}>
      <div style={{ fontSize: '10px', color: C.muted, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.4px', marginBottom: '5px' }}>
        {label} {required && <span style={{ color: C.red }}>*</span>}
      </div>
      {children}
      {hint && <div style={{ fontSize: '10px', color: C.dim, marginTop: '4px' }}>{hint}</div>}
    </label>
  );
}

export function Input(props) {
  return <input {...props} style={{ ...fieldBase, ...(props.style || {}) }} />;
}

export function Select({ children, ...props }) {
  return (
    <select {...props} style={{ ...fieldBase, ...(props.style || {}) }}>
      {children}
    </select>
  );
}

export function TextArea(props) {
  return <textarea {...props} style={{ ...fieldBase, minHeight: '64px', resize: 'vertical', fontWeight: 500, ...(props.style || {}) }} />;
}

/** Blocking reasons and soft warnings, rendered consistently everywhere. */
export function Verdict({ blocked = [], warnings = [], compact }) {
  if (!blocked.length && !warnings.length) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {blocked.map((b, i) => (
        <div key={`b${i}`} style={{
          background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.35)',
          borderRadius: '8px', padding: compact ? '7px 10px' : '9px 12px',
          fontSize: compact ? '11px' : '12px', color: '#fca5a5', fontWeight: 600
        }}>
          <strong style={{ color: C.red }}>BLOCKED</strong> — {b.message}
        </div>
      ))}
      {warnings.map((w, i) => (
        <div key={`w${i}`} style={{
          background: 'rgba(245,158,11,0.09)', border: '1px solid rgba(245,158,11,0.3)',
          borderRadius: '8px', padding: compact ? '7px 10px' : '9px 12px',
          fontSize: compact ? '11px' : '12px', color: '#fcd34d', fontWeight: 600
        }}>
          <strong style={{ color: C.amber }}>WARNING</strong> — {w.message}
        </div>
      ))}
    </div>
  );
}

export function Modal({ title, subtitle, onClose, children, width = '760px' }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(2,6,14,0.82)', zIndex: 1000,
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '24px', overflowY: 'auto'
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#0d1421', border: `1px solid ${C.border}`, borderRadius: '16px',
          padding: '22px', width: '100%', maxWidth: width, margin: 'auto'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '18px', gap: '12px' }}>
          <div>
            <div style={{ fontSize: '16px', fontWeight: 900, color: '#fff' }}>{title}</div>
            {subtitle && <div style={{ fontSize: '11px', color: C.muted, marginTop: '4px' }}>{subtitle}</div>}
          </div>
          <Btn tone="ghost" onClick={onClose} style={{ padding: '6px 11px' }}>✕</Btn>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Empty({ children }) {
  return (
    <div style={{ padding: '26px', textAlign: 'center', color: C.dim, fontSize: '12px', fontWeight: 600 }}>
      {children}
    </div>
  );
}
