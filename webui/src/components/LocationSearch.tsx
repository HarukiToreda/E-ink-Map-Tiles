import { useEffect, useRef } from "react";
import { searchResultKey } from "../browser/search";
import type { SearchResult } from "../models";

interface LocationSearchProps {
  query: string;
  searching: boolean;
  results: SearchResult[];
  resolvingResult: string | null;
  onQueryChange: (query: string) => void;
  onSubmit: () => void;
  onDismiss: () => void;
  onView: (result: SearchResult) => void;
  onAdd: (result: SearchResult) => void;
}

export function LocationSearch({
  query,
  searching,
  results,
  resolvingResult,
  onQueryChange,
  onSubmit,
  onDismiss,
  onView,
  onAdd,
}: LocationSearchProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const dismissOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        containerRef.current &&
        !containerRef.current.contains(event.target)
      )
        onDismiss();
    };
    const dismissWithEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onDismiss();
    };
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("keydown", dismissWithEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("keydown", dismissWithEscape);
    };
  }, [onDismiss]);

  return (
    <div className="search-wrap" ref={containerRef}>
      <form
        className="search-field"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <label className="sr-only" htmlFor="location-search">
          Search for a location
        </label>
        <input
          id="location-search"
          value={query}
          onChange={(event) => onQueryChange(event.currentTarget.value)}
          placeholder="City, address, postal code, landmark…"
          autoComplete="off"
        />
        <button type="submit" disabled={searching || query.trim().length < 2}>
          {searching ? "Searching…" : "Search"}
        </button>
      </form>
      {results.length > 0 && (
        <div className="search-results" aria-label="Location search results">
          {results.map((result) => {
            const key = searchResultKey(result);
            return (
              <div className="search-result" key={key}>
                <span className="search-result-copy">
                  <strong>{result.display_name}</strong>
                  <span>
                    {result.category} · {result.lat.toFixed(5)}, {result.lon.toFixed(5)}
                  </span>
                </span>
                <button type="button" onClick={() => onView(result)}>
                  View
                </button>
                <button
                  type="button"
                  className="search-result-add"
                  disabled={!result.bbox || resolvingResult !== null}
                  onClick={() => onAdd(result)}
                >
                  {resolvingResult === key ? "Resolving…" : "+ Add area"}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
