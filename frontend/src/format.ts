const HOUR_24: Intl.DateTimeFormatOptions = { hourCycle: "h23" };

function parse(value: string): Date | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string): string {
  const date = parse(value);
  return date ? date.toLocaleString(undefined, HOUR_24) : value;
}

export function formatTime(value: string): string {
  const date = parse(value);
  return date ? date.toLocaleTimeString(undefined, HOUR_24) : value;
}
