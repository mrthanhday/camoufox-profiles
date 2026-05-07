import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api';

interface TagMeta {
  name: string;
  color: string;
  count: number;
}

interface TagInputProps {
  value: string[];
  onChange: (tags: string[]) => void;
  maxTags?: number;
  placeholder?: string;
  disabled?: boolean;
}

const TAG_COLORS: Record<string, string> = {
  red: '#ff3b30',
  orange: '#ff9f0a',
  yellow: '#ffd60a',
  green: '#30d158',
  blue: '#007aff',
  purple: '#bf5af2',
  pink: '#ff375f',
};

export function TagInput({
  value,
  onChange,
  maxTags = 10,
  placeholder = 'Add tag...',
  disabled = false,
}: TagInputProps) {
  const [input, setInput] = useState('');
  const [suggestions, setSuggestions] = useState<TagMeta[]>([]);
  const [allTags, setAllTags] = useState<TagMeta[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fetch all tags on mount
  useEffect(() => {
    api.listTags().then((data) => setAllTags(data.tags)).catch(() => {});
  }, []);

  // Filter suggestions when input changes
  useEffect(() => {
    if (!input.trim()) {
      setSuggestions(allTags.filter((t) => !value.includes(t.name)));
    } else {
      const q = input.toLowerCase();
      setSuggestions(
        allTags.filter(
          (t) => t.name.toLowerCase().includes(q) && !value.includes(t.name)
        )
      );
    }
    setHighlightIdx(-1);
  }, [input, allTags, value]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const addTag = useCallback(
    (name: string) => {
      const clean = name.trim().toLowerCase();
      if (!clean || value.includes(clean) || value.length >= maxTags) return;
      onChange([...value, clean]);
      setInput('');
      setShowDropdown(false);
    },
    [value, onChange, maxTags]
  );

  const removeTag = useCallback(
    (tag: string) => {
      onChange(value.filter((t) => t !== tag));
    },
    [value, onChange]
  );

  const getColor = (tagName: string): string => {
    const meta = allTags.find((t) => t.name === tagName);
    if (meta?.color && TAG_COLORS[meta.color]) return TAG_COLORS[meta.color];
    if (meta?.color && meta.color.startsWith('#')) return meta.color;
    return '';
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      if (highlightIdx >= 0 && highlightIdx < suggestions.length) {
        addTag(suggestions[highlightIdx].name);
      } else if (input.trim()) {
        addTag(input);
      }
    } else if (e.key === 'Backspace' && !input && value.length > 0) {
      removeTag(value[value.length - 1]);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIdx((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIdx((i) => Math.max(i - 1, -1));
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    }
  };

  const atLimit = value.length >= maxTags;
  const exactMatch = suggestions.some((s) => s.name === input.trim().toLowerCase());
  const showCreate = input.trim() && !exactMatch && !atLimit;

  return (
    <div className="tag-input" ref={containerRef}>
      <div
        className={`tag-input-box ${disabled ? 'disabled' : ''}`}
        onClick={() => inputRef.current?.focus()}
      >
        {value.map((tag) => {
          const color = getColor(tag);
          return (
            <span key={tag} className="tag-input-chip">
              {color && (
                <span
                  className="color-dot"
                  style={{ background: color }}
                />
              )}
              {tag}
              {!disabled && (
                <span
                  className="remove"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeTag(tag);
                  }}
                >
                  [x]
                </span>
              )}
            </span>
          );
        })}
        {!disabled && !atLimit && (
          <input
            ref={inputRef}
            className="tag-input-field"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              setShowDropdown(true);
            }}
            onFocus={() => setShowDropdown(true)}
            onKeyDown={handleKeyDown}
            placeholder={value.length === 0 ? placeholder : ''}
          />
        )}
        {atLimit && value.length > 0 && (
          <span className="tag-input-limit">max {maxTags}</span>
        )}
      </div>

      {showDropdown && !disabled && (suggestions.length > 0 || showCreate) && (
        <div className="tag-input-dropdown">
          {suggestions.slice(0, 8).map((s, i) => (
            <div
              key={s.name}
              className={`tag-input-dropdown-item ${
                i === highlightIdx ? 'highlighted' : ''
              }`}
              onMouseDown={(e) => {
                e.preventDefault();
                addTag(s.name);
              }}
              onMouseEnter={() => setHighlightIdx(i)}
            >
              {s.color && TAG_COLORS[s.color] && (
                <span
                  className="color-dot"
                  style={{ background: TAG_COLORS[s.color] }}
                />
              )}
              <span className="tag-name">{s.name}</span>
              <span className="tag-count">{s.count}</span>
            </div>
          ))}
          {showCreate && (
            <div
              className={`tag-input-dropdown-item create ${
                highlightIdx === suggestions.length ? 'highlighted' : ''
              }`}
              onMouseDown={(e) => {
                e.preventDefault();
                addTag(input);
              }}
            >
              [+] Create "{input.trim().toLowerCase()}"
            </div>
          )}
        </div>
      )}
    </div>
  );
}
