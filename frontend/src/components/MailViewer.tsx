import { useEffect, useState } from "react";

import { api } from "../api";
import type { MailSummary } from "../types";

export function MailDialog({
  mail,
  onClose,
}: {
  mail: MailSummary;
  onClose: () => void;
}) {
  const [body, setBody] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBody(null);
    setError(null);
    api
      .mailDetail(mail.id)
      .then((detail) => {
        if (!cancelled) {
          setBody(detail.body);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [mail.id]);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);

  const title = mail.subject ?? "(no subject)";

  return (
    <div
      className="mail-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        className="mail-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`Mail: ${title}`}
      >
        <header className="mail-dialog-header">
          <div>
            <h2>{title}</h2>
            <p>
              {mail.from_addr ?? "unknown sender"}
              {mail.to_addrs ? ` → ${mail.to_addrs}` : ""}
              {mail.cc_addrs ? ` · cc ${mail.cc_addrs}` : ""}
            </p>
            <p>{mail.date_utc ?? mail.ingested_at}</p>
          </div>
          <button type="button" onClick={onClose} autoFocus>
            Close
          </button>
        </header>
        <div className="mail-dialog-body">
          {error ? (
            <p className="error-text">Could not load mail body: {error}</p>
          ) : body === null ? (
            <p className="empty">Loading mail body…</p>
          ) : body.trim() ? (
            <div className="mail-body">{body}</div>
          ) : (
            <p className="empty">No plain-text body available.</p>
          )}
        </div>
      </section>
    </div>
  );
}
