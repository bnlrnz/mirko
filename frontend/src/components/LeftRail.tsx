import type { Filters, TdocSummary } from "../types";

interface Props {
  tdocs: TdocSummary[];
  allTdocs: TdocSummary[];
  filters: Filters;
  selected: string | null;
  onFilters: (filters: Filters) => void;
  onSelect: (tdoc: string) => void;
}

function unique(values: (string | null)[]): string[] {
  return [...new Set(values.filter((value): value is string => !!value))].sort();
}

export function LeftRail({
  tdocs,
  allTdocs,
  filters,
  selected,
  onFilters,
  onSelect,
}: Props) {
  const agendas = unique(allTdocs.map((row) => row.agenda_item));
  const types = unique(allTdocs.map((row) => row.type));
  const states = unique(allTdocs.map((row) => row.decision));
  const sources = unique(allTdocs.map((row) => row.source));

  const set = (key: keyof Filters, value: string | boolean) =>
    onFilters({ ...filters, [key]: value });

  return (
    <aside className="left-rail" aria-label="Tracked TDocs and filters">
      <section className="facet-panel">
        <h2>Filters</h2>
        <label>
          Agenda
          <select
            aria-label="Agenda filter"
            value={filters.agenda}
            onChange={(event) => set("agenda", event.target.value)}
          >
            <option value="">All</option>
            {agendas.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Type
          <select
            aria-label="Type filter"
            value={filters.type}
            onChange={(event) => set("type", event.target.value)}
          >
            <option value="">All</option>
            {types.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          State
          <select
            aria-label="State filter"
            value={filters.state}
            onChange={(event) => set("state", event.target.value)}
          >
            <option value="">All</option>
            {states.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Source
          <select
            aria-label="Source filter"
            value={filters.source}
            onChange={(event) => set("source", event.target.value)}
          >
            <option value="">All</option>
            {sources.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={filters.tracked}
            onChange={(event) => set("tracked", event.target.checked)}
          />
          Tracked only
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={filters.includeEphemeral}
            onChange={(event) => set("includeEphemeral", event.target.checked)}
          />
          Include ephemeral
        </label>
      </section>

      <section className="tdoc-list">
        <h2>
          TDocs <span>{tdocs.length}</span>
        </h2>
        {tdocs.length === 0 ? (
          <p className="empty">No TDocs match the current filters.</p>
        ) : (
          <ul>
            {tdocs.map((row) => (
              <li key={row.tdoc_number}>
                <button
                  type="button"
                  className={selected === row.tdoc_number ? "selected" : ""}
                  aria-current={selected === row.tdoc_number || undefined}
                  onClick={() => onSelect(row.tdoc_number)}
                >
                  <span className="tdoc-number">{row.tdoc_number}</span>
                  <span className="tdoc-title">{row.title ?? row.topic}</span>
                  <span className="badges">
                    {row.is_tracked ? <em className="badge tracked">★</em> : null}
                    {row.is_provisional ? (
                      <em className="badge provisional">new</em>
                    ) : null}
                    {row.has_conflict ? (
                      <em className="badge conflict">!</em>
                    ) : null}
                    {row.artifact_count > 0 ? (
                      <em className="badge">{row.artifact_count} files</em>
                    ) : null}
                    {row.mention_count > 0 ? (
                      <em className="badge">{row.mention_count} mail</em>
                    ) : null}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  );
}
