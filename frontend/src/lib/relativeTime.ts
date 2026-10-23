const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// Limiares em que a unidade seguinte passa a ler melhor ("em 50 minutos" vira "em 1 hora").
const UNITS: Array<{ unit: Intl.RelativeTimeFormatUnit; size: number; below: number }> = [
  { unit: "minute", size: MINUTE, below: 45 * MINUTE },
  { unit: "hour", size: HOUR, below: 22 * HOUR },
  { unit: "day", size: DAY, below: Infinity },
];

// "em 2 horas", "amanhã", "há 5 minutos", no idioma do navegador quando `locale` não é passado.
export function formatRelativeTime(target: Date, now: Date = new Date(), locale?: string): string {
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const diff = target.getTime() - now.getTime();

  if (Math.abs(diff) < 45 * SECOND) {
    return rtf.format(0, "second");
  }
  const { unit, size } = UNITS.find(({ below }) => Math.abs(diff) < below)!;
  return rtf.format(Math.round(diff / size), unit);
}
