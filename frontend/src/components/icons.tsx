import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function baseProps(props: IconProps): IconProps {
  return {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    className: "h-4 w-4",
    ...props,
  };
}

export function HomeIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V21h14V9.5" />
      <path d="M9.5 21v-6h5v6" />
    </svg>
  );
}

export function ActivityIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M3 12h4l2.5 7L14 5l2.5 7H21" />
    </svg>
  );
}

export function AlertTriangleIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M12 3.5 21.5 20h-19L12 3.5Z" />
      <path d="M12 9.5v4.5" />
      <path d="M12 17.25h.01" />
    </svg>
  );
}

export function CheckCircleIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.3 12.2 2.4 2.4 5-5.1" />
    </svg>
  );
}

export function XCircleIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="m9.2 9.2 5.6 5.6" />
      <path d="m14.8 9.2-5.6 5.6" />
    </svg>
  );
}

export function ChevronLeftIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M14.5 5 8 12l6.5 7" />
    </svg>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M9.5 5 16 12l-6.5 7" />
    </svg>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M5 9.5 12 16l7-6.5" />
    </svg>
  );
}

export function ShieldIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M12 3 4.5 6v6c0 4.6 3.2 7.7 7.5 9 4.3-1.3 7.5-4.4 7.5-9V6L12 3Z" />
      <path d="m9 12 2.2 2.2L15.5 10" />
    </svg>
  );
}

export function DatabaseIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <ellipse cx="12" cy="6" rx="7.5" ry="3" />
      <path d="M4.5 6v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3V6" />
      <path d="M4.5 12v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-6" />
    </svg>
  );
}

export function NetworkIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="4.5" r="2" />
      <circle cx="5" cy="18" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="M12 6.5v4M12 10.5 6.3 16.3M12 10.5l5.7 5.8" />
    </svg>
  );
}

export function ClockIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.3l3.5 2" />
    </svg>
  );
}

export function FileTextIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M7 3.5h7l3.5 3.5V20.5h-10.5V3.5Z" />
      <path d="M14 3.5V7h3.5" />
      <path d="M9 12.5h6M9 16h6" />
    </svg>
  );
}

export function BellIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M6 10.5a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5h-15S6 14.5 6 10.5Z" />
      <path d="M10.3 19a1.9 1.9 0 0 0 3.4 0" />
    </svg>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M4.6 7.2l1.9 1.1M17.5 15.7l1.9 1.1M3.5 12h2.2M18.3 12h2.2M4.6 16.8l1.9-1.1M17.5 8.3l1.9-1.1" />
    </svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m19.5 19.5-4.3-4.3" />
    </svg>
  );
}

export function XIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="m6 6 12 12M18 6 6 18" />
    </svg>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="m5 12.5 4.5 4.5L19.5 7" />
    </svg>
  );
}

export function HelpCircleIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.3 9.3a2.8 2.8 0 1 1 3.9 2.6c-.9.5-1.2 1-1.2 1.9" />
      <path d="M12 17.25h.01" />
    </svg>
  );
}

export function LinkIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M9.5 14.5 14.5 9.5" />
      <path d="M11 7.5 12.6 5.9a3.2 3.2 0 0 1 4.5 4.5L15.5 12" />
      <path d="M13 16.5 11.4 18.1a3.2 3.2 0 0 1-4.5-4.5L8.5 12" />
    </svg>
  );
}

export function SparklesIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M11.5 3.5 13 8l4.5 1.5L13 11l-1.5 4.5L10 11l-4.5-1.5L10 8l1.5-4.5Z" />
      <path d="M18.5 15.5 19.3 18l2.2.8-2.2.8-.8 2.4-.8-2.4-2.2-.8 2.2-.8Z" />
    </svg>
  );
}

export function ClipboardListIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <rect x="6" y="4.5" width="12" height="16" rx="2" />
      <path d="M9.5 3.5h5a1 1 0 0 1 1 1v1h-7v-1a1 1 0 0 1 1-1Z" />
      <path d="M9 11h6M9 14.5h6M9 18h4" />
    </svg>
  );
}

export function GaugeIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M4 15a8 8 0 1 1 16 0" />
      <path d="M12 15 15.5 9.5" />
      <path d="M12 15h.01" />
    </svg>
  );
}

export function LayersIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="m12 3.5 8 4.5-8 4.5-8-4.5 8-4.5Z" />
      <path d="m4 12 8 4.5 8-4.5" />
      <path d="m4 16 8 4.5 8-4.5" />
    </svg>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5" />
      <path d="M12 7.75h.01" />
    </svg>
  );
}

export function RadioIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <circle cx="12" cy="12" r="2" />
      <path d="M8.5 15.5a5 5 0 0 1 0-7M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M5.5 18.5a9 9 0 0 1 0-13M18.5 5.5a9 9 0 0 1 0 13" />
    </svg>
  );
}

export function MenuIcon(props: IconProps) {
  return (
    <svg {...baseProps(props)}>
      <path d="M4 6.5h16M4 12h16M4 17.5h16" />
    </svg>
  );
}
