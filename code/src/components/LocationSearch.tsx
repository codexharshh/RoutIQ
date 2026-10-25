import React, { useState, useCallback, useRef, useEffect } from 'react';
import type { Location, SearchResult } from '../types';
import { LocationSearchService } from '../services/locationSearchService';
import { MAP_CONFIG } from '../constants';

interface LocationSearchProps {
  onLocationSelect: (location: Location) => void;
  placeholder?: string;
}

export const LocationSearch: React.FC<LocationSearchProps> = ({
  onLocationSelect,
  placeholder = 'Search for a location...'
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [searchError, setSearchError] = useState<string | null>(null);

  const searchService = LocationSearchService.getInstance();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const performSearch = useCallback(async (searchQuery: string) => {
    const cleaned = searchQuery.trim();

    if (cleaned.length < 2) {
      setResults([]);
      setSearchError(null);
      setShowDropdown(false);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setSearchError(null);
    setShowDropdown(true);

    try {
      const searchResults = await searchService.searchLocations(cleaned);
      setResults(searchResults);
      setSelectedIndex(-1);
      setShowDropdown(true);

      if (searchResults.length === 0) {
        setSearchError('No matching locations were found. Try a road, locality, or city name.');
      }
    } catch (error) {
      console.error('Location search failed:', error);
      setResults([]);
      setSearchError(
        error instanceof Error
          ? error.message
          : 'Search failed. Please try again.'
      );
      setShowDropdown(true);
    } finally {
      setIsLoading(false);
    }
  }, [searchService]);

  const debouncedSearch = useCallback((searchQuery: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    debounceRef.current = setTimeout(() => {
      void performSearch(searchQuery);
    }, MAP_CONFIG.searchDebounceMs);
  }, [performSearch]);

  const handleClearSearch = () => {
    setQuery('');
    setResults([]);
    setSearchError(null);
    setShowDropdown(false);
    setSelectedIndex(-1);
    inputRef.current?.focus();
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    setQuery(value);
    setResults([]);
    setSearchError(null);
    setSelectedIndex(-1);

    if (value.trim().length >= 2) {
      setShowDropdown(true);
      debouncedSearch(value);
    } else {
      setShowDropdown(false);
    }
  };

  const handleResultSelect = (result: SearchResult) => {
    const location = searchService.convertSearchResultToLocation(result);

    if (!Number.isFinite(location.lat) || !Number.isFinite(location.lng)) {
      setSearchError('The selected location has invalid coordinates.');
      return;
    }

    onLocationSelect(location);
    setQuery(result.display_name);
    setShowDropdown(false);
    setSearchError(null);
    setSelectedIndex(-1);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      setShowDropdown(false);
      setSelectedIndex(-1);
      inputRef.current?.blur();
      return;
    }

    if (!showDropdown || results.length === 0) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setSelectedIndex((previous) =>
        previous < results.length - 1 ? previous + 1 : previous
      );
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setSelectedIndex((previous) => previous > 0 ? previous - 1 : previous);
    } else if (event.key === 'Enter' && selectedIndex >= 0) {
      event.preventDefault();
      handleResultSelect(results[selectedIndex]);
    }
  };

  const handleInputBlur = () => {
    // Allow time for the result to be selected before the input loses focus.
    setTimeout(() => {
      setShowDropdown(false);
      setSelectedIndex(-1);
    }, 200);
  };

  const handleInputFocus = () => {
    if (query.trim().length >= 2) setShowDropdown(true);
  };

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return (
    <div className="location-search">
      <div className="search-input-container">
        <div className="search-icon" aria-hidden="true">⌕</div>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onBlur={handleInputBlur}
          onFocus={handleInputFocus}
          placeholder={placeholder}
          className="search-input"
          autoComplete="off"
          aria-label="Search map location"
          aria-expanded={showDropdown}
          aria-controls="routiq-location-results"
        />

        {query && (
          <button
            type="button"
            onClick={handleClearSearch}
            className={`search-clear-button ${query ? 'visible' : ''}`}
            aria-label="Clear search"
          >
            ×
          </button>
        )}

        {isLoading && <div className="search-loading-spinner" />}
      </div>

      {showDropdown && (
        <div
          ref={dropdownRef}
          id="routiq-location-results"
          className="search-results"
          role="listbox"
        >
          {isLoading ? (
            <div className="search-loading">
              <div className="search-loading-spinner" />
              Searching locations...
            </div>
          ) : searchError ? (
            <div className="search-empty" role="status">
              <div className="search-empty-icon">!</div>
              {searchError}
            </div>
          ) : results.map((result, index) => (
            <div
              key={result.place_id}
              role="option"
              aria-selected={index === selectedIndex}
              className={`search-result-item ${index === selectedIndex ? 'selected' : ''}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => handleResultSelect(result)}
              onMouseEnter={() => setSelectedIndex(index)}
            >
              <div className="search-result-icon">⌖</div>
              <div className="search-result-text">
                <span className="search-result-name">{result.display_name}</span>
                <small className="search-result-meta">
                  {result.source ?? 'Location provider'} · {Number(result.lat).toFixed(5)}, {Number(result.lon).toFixed(5)}
                </small>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};