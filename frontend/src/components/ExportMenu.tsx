import { useEffect, useRef, useState } from "react";

import type { ExportOptions } from "../types";

export const DEFAULT_EXPORT_OPTIONS: ExportOptions = {
  scope: "tracked",
  agendaItem: "",
  lineage: true,
  timeline: true,
  artifacts: true,
  notes: true,
  meetingNotes: true,
  state: true,
  mail: false,
};

type ToggleKey =
  | "lineage"
  | "timeline"
  | "artifacts"
  | "notes"
  | "meetingNotes"
  | "state"
  | "mail";

const CONTENT_OPTIONS: { key: ToggleKey; label: string }[] = [
  { key: "lineage", label: "Lineage graph" },
  { key: "timeline", label: "Timeline" },
  { key: "artifacts", label: "Artifacts" },
  { key: "notes", label: "Notes" },
  { key: "meetingNotes", label: "Meeting notes" },
  { key: "state", label: "State" },
  { key: "mail", label: "Mail" },
];

interface Props {
  agendaItems: string[];
  busy?: boolean;
  onExport: (options: ExportOptions) => void;
}

export function ExportMenu({ agendaItems, busy = false, onExport }: Props) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ExportOptions>(DEFAULT_EXPORT_OPTIONS);
  const wrapper = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const close = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const toggle = (key: ToggleKey) => {
    setOptions((current) => ({ ...current, [key]: !current[key] }));
  };

  return (
    <div className="export-menu" ref={wrapper}>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        Export
      </button>
      {open ? (
        <div
          className="export-panel"
          role="group"
          aria-label="Export options"
        >
          <fieldset className="export-group">
            <legend>Scope</legend>
            <label className="check">
              <input
                type="radio"
                name="export-scope"
                checked={options.scope === "tracked"}
                onChange={() =>
                  setOptions((current) => ({ ...current, scope: "tracked" }))
                }
              />
              Tracked only
            </label>
            <label className="check">
              <input
                type="radio"
                name="export-scope"
                checked={options.scope === "all"}
                onChange={() =>
                  setOptions((current) => ({ ...current, scope: "all" }))
                }
              />
              All TDocs
            </label>
          </fieldset>
          <label className="export-field">
            <span>Agenda item</span>
            <select
              value={options.agendaItem}
              onChange={(event) =>
                setOptions((current) => ({
                  ...current,
                  agendaItem: event.target.value,
                }))
              }
            >
              <option value="">All agenda items</option>
              {agendaItems.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="export-group">
            <legend>Include</legend>
            {CONTENT_OPTIONS.map((option) => (
              <label className="check" key={option.key}>
                <input
                  type="checkbox"
                  checked={options[option.key]}
                  onChange={() => toggle(option.key)}
                />
                {option.label}
              </label>
            ))}
          </fieldset>
          <div className="export-actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => {
                onExport(options);
                setOpen(false);
              }}
            >
              Download Markdown
            </button>
            <button type="button" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
