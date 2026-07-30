import React from "react";

/* KNU PICK — icon set (Lucide-style stroked SVGs). window.Icon name=... */
const _ICON_PATHS = {
  home:      '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
  bell:      '<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  book:      '<path d="M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2z"/><path d="M4 19a2 2 0 0 0 2 2h12"/>',
  landmark:  '<path d="M3 21h18"/><path d="M5 21V10m4 11V10m6 11V10m4 11V10"/><path d="M12 3 21 8H3z"/>',
  bot:       '<rect x="4" y="8" width="16" height="11" rx="3"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1.2"/><path d="M9 13h.01M15 13h.01"/><path d="M2 13v3M22 13v3"/>',
  settings:  '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
  user:      '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  link:      '<path d="M9 13a4 4 0 0 0 6 .5l3-3a4 4 0 0 0-6-6l-1 1"/><path d="M15 11a4 4 0 0 0-6-.5l-3 3a4 4 0 0 0 6 6l1-1"/>',
  megaphone: '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M16 8a5 5 0 0 1 0 8"/>',
  flask:     '<path d="M9 3h6"/><path d="M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/><path d="M7.5 15h9"/>',
  calendar:  '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 3v4M16 3v4"/>',
  clock:     '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  search:    '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/>',
  chevron:   '<path d="m6 9 6 6 6-6"/>',
  paperclip: '<path d="M21 11.5 12.5 20a5 5 0 0 1-7-7l8.5-8.5a3.5 3.5 0 0 1 5 5L10.5 18a1.8 1.8 0 0 1-2.5-2.5l8-8"/>',
  send:      '<path d="M4 12h14M12 5l7 7-7 7"/>',
  coins:     '<circle cx="9" cy="9" r="5"/><path d="M14.5 5.3A5 5 0 0 1 15 19a5 5 0 0 1-1.3-.2"/>',
  utensils:  '<path d="M4 3v7a2 2 0 0 0 2 2v9M6 3v6M8 3v6"/><path d="M17 3c-1.5 0-3 1.8-3 5s1.5 4 1.5 4V21"/>',
  file:      '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  check:     '<path d="m20 6-11 11-5-5"/>',
  eye:       '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  cap:       '<path d="M22 9 12 5 2 9l10 4 10-4z"/><path d="M6 11v5c0 1 2.7 3 6 3s6-2 6-3v-5"/>',
  bars:      '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  plus:      '<path d="M12 5v14M5 12h14"/>',
  trash:     '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M6 6l1 14a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-14"/>',
  menu:      '<path d="M3 12h18M3 6h18M3 18h18"/>',
  refresh:   '<path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5"/>',
  star:      '<path d="M12 3.5l2.6 5.3 5.9.8-4.3 4.1 1 5.8L12 16.9 6.8 19.5l1-5.8L3.5 9.6l5.9-.8z"/>',
  starFill:  '<path d="M12 3.5l2.6 5.3 5.9.8-4.3 4.1 1 5.8L12 16.9 6.8 19.5l1-5.8L3.5 9.6l5.9-.8z" fill="currentColor" stroke="none"/>',
  play:      '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z" fill="currentColor" stroke="none"/>',
  fileText:  '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
  warning:   '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  external:  '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/>',
  citation:  '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 16h4"/>',
};

function Icon({ name, size = 18, stroke = 2, style, className }) {
  const d = _ICON_PATHS[name] || "";
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={stroke} strokeLinecap="round"
      strokeLinejoin="round" style={style} className={className}
      dangerouslySetInnerHTML={{ __html: d }}
    />
  );
}

/* KNU crest — 공주대 엠블럼을 단순화(블루 링 + 그린 보조 + 정자각 + KNU + 1948) */
function Crest({ size = 36 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className="brand-crest">
      {/* 링 */}
      <circle cx="24" cy="24" r="23" fill="#15539c"/>
      <circle cx="24" cy="24" r="22" fill="none" stroke="#1a7a4f" strokeWidth="1"/>
      <circle cx="24" cy="24" r="18.6" fill="#ffffff"/>
      <circle cx="24" cy="24" r="18.6" fill="none" stroke="#0f4380" strokeWidth="0.7"/>
      {/* 정자각(지붕 + 기둥 + 단) */}
      <g fill="#15539c" stroke="#15539c" strokeWidth="0.6" strokeLinejoin="round">
        <path d="M24 11.6 32.4 18.2 15.6 18.2 Z"/>
        <rect x="15.4" y="18.8" width="17.2" height="1.6" rx="0.5"/>
        <rect x="17.6" y="21" width="1.7" height="6.2"/>
        <rect x="21.2" y="21" width="1.7" height="6.2"/>
        <rect x="25.1" y="21" width="1.7" height="6.2"/>
        <rect x="28.7" y="21" width="1.7" height="6.2"/>
        <rect x="14.6" y="27.8" width="18.8" height="1.5" rx="0.5"/>
        <rect x="13.4" y="30.1" width="21.2" height="1.5" rx="0.5"/>
      </g>
      {/* KNU */}
      <text x="24" y="38.4" textAnchor="middle" fontSize="5.4" fontWeight="800" fill="#15539c" fontFamily="Georgia, serif">KNU</text>
      {/* 1948 */}
      <text x="24" y="14.3" textAnchor="middle" fontSize="3" fontWeight="700" fill="#1a7a4f">1948</text>
    </svg>
  );
}

export { Icon, Crest };
