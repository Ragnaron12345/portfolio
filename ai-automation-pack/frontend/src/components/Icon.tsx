import type { ReactNode, SVGProps } from "react";

export type IconName =
  | "overview"
  | "executions"
  | "reviews"
  | "systems"
  | "audit"
  | "user"
  | "menu"
  | "close"
  | "play"
  | "refresh"
  | "chevron"
  | "check"
  | "warning"
  | "error"
  | "clock"
  | "external"
  | "search"
  | "filter"
  | "shield"
  | "file"
  | "arrow"
  | "retry";

const paths: Record<IconName, ReactNode> = {
  overview: <><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5M9 21v-7h6v7"/></>,
  executions: <><circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/></>,
  reviews: <><path d="M8 5V3h8v2M7 5h10a2 2 0 0 1 2 2v14H5V7a2 2 0 0 1 2-2Z"/><path d="M9 10h6M9 14h6M9 18h4"/></>,
  systems: <><rect x="3" y="3" width="18" height="7" rx="1"/><rect x="3" y="14" width="18" height="7" rx="1"/><path d="M7 6.5h.01M7 17.5h.01M11 6.5h7M11 17.5h7"/></>,
  audit: <><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 11h6M9 15h6M9 19h4"/></>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  play: <path d="m8 5 11 7-11 7z"/>,
  refresh: <><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></>,
  chevron: <path d="m9 5 7 7-7 7"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  warning: <><path d="M12 3 2.8 20h18.4z"/><path d="M12 9v4M12 17h.01"/></>,
  error: <><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  external: <><path d="M14 4h6v6M20 4l-9 9"/><path d="M19 13v7H4V5h7"/></>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  filter: <path d="M4 5h16l-6 7v6l-4 2v-8z"/>,
  shield: <><path d="M12 2.5 20 6v5.5c0 4.7-3.2 8.2-8 10-4.8-1.8-8-5.3-8-10V6z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></>,
  file: <><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
  retry: <><path d="M4 9V4h5M20 15v5h-5"/><path d="M5.7 5.7A8 8 0 0 1 19 9M18.3 18.3A8 8 0 0 1 5 15"/></>,
};

export function Icon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
