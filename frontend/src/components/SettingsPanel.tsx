import { type FormEvent, useState } from "react";

import type { Settings, SettingsUpdate } from "../types";

interface Props {
  settings: Settings;
  busy: boolean;
  onClose: () => void;
  onSave: (update: SettingsUpdate) => void;
  onUpload: (file: File) => Promise<string>;
}

export function SettingsPanel({
  settings,
  busy,
  onClose,
  onSave,
  onUpload,
}: Props) {
  const [kind, setKind] = useState(settings.source.kind);
  const [protocol, setProtocol] = useState(settings.source.protocol);
  const [host, setHost] = useState(settings.source.host);
  const [port, setPort] = useState(
    settings.source.port === null ? "" : String(settings.source.port),
  );
  const [basePath, setBasePath] = useState(settings.source.base_path);
  const [username, setUsername] = useState(settings.source.username ?? "");
  const [password, setPassword] = useState("");
  const [clearPassword, setClearPassword] = useState(false);
  const [tls, setTls] = useState(settings.source.tls);
  const [lazyDrafts, setLazyDrafts] = useState(settings.lazy_drafts);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSave({
      kind,
      protocol,
      host,
      port: port.trim() === "" ? null : Number(port),
      base_path: basePath,
      username: username.trim() === "" ? null : username.trim(),
      password: password === "" ? null : password,
      clear_password: clearPassword,
      tls,
      lazy_drafts: lazyDrafts,
    });
  };

  const upload = async (file: File | undefined) => {
    if (!file) {
      return;
    }
    setUploading(true);
    setUploadError(null);
    setUploadMessage(null);
    try {
      setUploadMessage(await onUpload(file));
    } catch (caught) {
      setUploadError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="settings-backdrop" role="presentation">
      <section
        className="settings-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Meeting settings"
      >
        <header className="settings-header">
          <div>
            <h2>Meeting settings</h2>
            <p>Saved to this meeting&apos;s meeting.json.</p>
          </div>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </header>

        <form className="settings-form" onSubmit={submit}>
          <fieldset>
            <legend>FTP source</legend>
            <div className="settings-grid">
              <label>
                Kind
                <select
                  aria-label="Source kind"
                  value={kind}
                  onChange={(event) => setKind(event.target.value)}
                >
                  <option value="local">local</option>
                  <option value="public">public</option>
                  <option value="remote">remote</option>
                </select>
              </label>
              <label>
                Protocol
                <select
                  aria-label="Source protocol"
                  value={protocol}
                  onChange={(event) => setProtocol(event.target.value)}
                >
                  <option value="ftp">ftp</option>
                  <option value="ftps">ftps</option>
                  <option value="https">https</option>
                </select>
              </label>
              <label>
                Host
                <input
                  aria-label="Source host"
                  required
                  value={host}
                  onChange={(event) => setHost(event.target.value)}
                />
              </label>
              <label>
                Port
                <input
                  aria-label="Source port"
                  inputMode="numeric"
                  placeholder="default"
                  value={port}
                  onChange={(event) => setPort(event.target.value)}
                />
              </label>
              <label className="wide">
                Base path
                <input
                  aria-label="Source base path"
                  required
                  value={basePath}
                  onChange={(event) => setBasePath(event.target.value)}
                />
              </label>
              <label>
                Username
                <input
                  aria-label="Source username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                />
              </label>
              <label>
                Password
                <input
                  aria-label="Source password"
                  type="password"
                  autoComplete="new-password"
                  placeholder={
                    settings.source.password_set
                      ? "leave blank to keep current"
                      : "no password"
                  }
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    if (event.target.value) {
                      setClearPassword(false);
                    }
                  }}
                />
              </label>
              <label>
                TLS
                <select
                  aria-label="Source TLS"
                  value={tls}
                  onChange={(event) => setTls(event.target.value)}
                >
                  <option value="none">none</option>
                  <option value="explicit">explicit</option>
                  <option value="implicit">implicit</option>
                </select>
              </label>
              <label className="check wide">
                <input
                  type="checkbox"
                  checked={clearPassword}
                  onChange={(event) => {
                    setClearPassword(event.target.checked);
                    if (event.target.checked) {
                      setPassword("");
                    }
                  }}
                />
                Clear any saved password
                {settings.source.password_env ? (
                  <span className="hint">
                    currently uses {settings.source.password_env}
                  </span>
                ) : null}
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Sync</legend>
            <label className="check">
              <input
                type="checkbox"
                checked={lazyDrafts}
                onChange={(event) => setLazyDrafts(event.target.checked)}
              />
              Fetch working drafts only when opened or tracked
            </label>
            <p className="hint">
              Agenda HTML and Inbox mail stay eager. Deferred drafts appear as
              remote artifacts until requested.
            </p>
          </fieldset>

          <fieldset>
            <legend>Allocation workbook</legend>
            <p className="hint">Current: {settings.excel}</p>
            <label>
              Upload and parse now
              <input
                aria-label="Excel workbook"
                type="file"
                accept=".xlsx,.xls"
                disabled={uploading}
                onChange={(event) => void upload(event.target.files?.[0])}
              />
            </label>
            {uploading ? <p className="hint">Uploading and parsing…</p> : null}
            {uploadMessage ? <p className="ok-text">{uploadMessage}</p> : null}
            {uploadError ? <p className="error-text">{uploadError}</p> : null}
          </fieldset>

          <div className="settings-actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Saving…" : "Save settings"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
