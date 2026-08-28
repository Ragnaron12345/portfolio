import type { ReactNode, SVGProps } from "react"

export type IconName =
  | "overview"
  | "documents"
  | "review"
  | "evaluations"
  | "upload"
  | "search"
  | "refresh"
  | "check"
  | "warning"
  | "error"
  | "menu"
  | "close"
  | "arrow"

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName
  size?: number
}

export function Icon({ name, size = 18, ...props }: IconProps) {
  const paths: Record<IconName, ReactNode> = {
    overview: <><path d="M4 11.5 12 4l8 7.5"/><path d="M6.5 10.5V20h11v-9.5M10 20v-5h4v5"/></>,
    documents: <><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 12h6M9 16h6"/></>,
    review: <><rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 3V1.5h6V3M9 9h6M9 13h4M8.5 17l1.5 1.5 3-3"/></>,
    evaluations: <><path d="M5 20V10h3v10zM11 20V4h3v16zM17 20v-7h3v7z"/></>,
    upload: <><path d="M12 16V4M8 8l4-4 4 4"/><path d="M5 14v6h14v-6"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></>,
    refresh: <><path d="M20 7v5h-5"/><path d="M18.2 16A8 8 0 1 1 19 8.5L20 12"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    warning: <><path d="M12 3 2.8 20h18.4z"/><path d="M12 9v5M12 17.5v.1"/></>,
    error: <><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/></>,
    menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
    arrow: <><path d="M4 12h16M14 6l6 6-6 6"/></>,
  }
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.75"
      {...props}
    >
      {paths[name]}
    </svg>
  )
}
