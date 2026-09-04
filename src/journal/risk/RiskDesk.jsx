import React, { useState } from 'react';
import { C, Chip } from './ui.jsx';
import { useRiskDesk } from './useRiskDesk.js';
import RiskDashboard from './RiskDashboard.jsx';
import DailyOpportunity from './DailyOpportunity.jsx';
import CashGrowth from './CashGrowth.jsx';
import RiskSetup from './RiskSetup.jsx';

/**
 * Risk Desk container.
 *
 * `externalLtps` is the existing App.jsx held-stock price map, passed in read-only.
 * That poller is not modified; this module adds its own for its own symbols.
 */
export default function RiskDesk({ view = 'dashboard', externalLtps = {} }) {
  const desk = useRiskDesk({ externalLtps });
  const [sub, setSub] = useState(view);

  const TABS = [
    { id: 'dashboard', label: '📊 Dashboard' },
    { id: 'daily', label: '🎯 Daily Opportunity', badge: desk.dayDecision?.eligible?.length || 0 },
    { id: 'cash', label: '💰 Cash & Growth' },
    { id: 'setup', label: '⚙️ Setup', warn: !desk.config?.configured }
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setSub(t.id)}
            style={{
              background: sub === t.id ? 'rgba(56,189,248,0.15)' : 'rgba(255,255,255,0.03)',
              border: `1.5px solid ${sub === t.id ? C.accent : C.border}`,
              color: sub === t.id ? '#fff' : C.muted,
              padding: '8px 15px',
              borderRadius: '9px',
              fontWeight: 800,
              fontSize: '12px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '7px'
            }}
          >
            {t.label}
            {t.badge > 0 && <Chip tone="good">{t.badge}</Chip>}
            {t.warn && <Chip tone="warn">!</Chip>}
          </button>
        ))}
      </div>

      {sub === 'dashboard' && <RiskDashboard desk={desk} onOpenDaily={() => setSub('daily')} />}
      {sub === 'daily' && <DailyOpportunity desk={desk} />}
      {sub === 'cash' && <CashGrowth desk={desk} />}
      {sub === 'setup' && <RiskSetup desk={desk} onReset={() => desk.actions.resetAll({ keepConfig: true })} />}
    </div>
  );
}
