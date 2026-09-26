import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { isValidHex, normalizeHex } from "../../../lib/color";

/* -------------------------------------------------------------------------- */
/* Range                                                                      */
/* -------------------------------------------------------------------------- */

type RangeFieldProps = {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format?: (value: number) => string;
  onChange: (value: number) => void;
};

export function RangeField({
  id,
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: RangeFieldProps) {
  return (
    <div className="ctl">
      <div className="ctl__head">
        <label className="ctl__label" htmlFor={id}>
          {label}
        </label>
        <span className="ctl__value">{format ? format(value) : String(value)}</span>
      </div>
      <input
        id={id}
        className="range"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Colour                                                                     */
/* -------------------------------------------------------------------------- */

type ColorFieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
};

export function ColorField({ id, label, value, onChange }: ColorFieldProps) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  const commit = (next: string) => {
    if (isValidHex(next)) {
      onChange(normalizeHex(next));
    }
  };

  return (
    <div className="ctl ctl--row">
      <span className="ctl__label" id={`${id}-label`}>
        {label}
      </span>

      <div className="color">
        <input
          className="color__swatch"
          type="color"
          value={normalizeHex(value)}
          aria-labelledby={`${id}-label`}
          onChange={(event) => onChange(event.target.value)}
        />
        <input
          className="color__hex"
          type="text"
          value={draft}
          spellCheck={false}
          maxLength={7}
          aria-label={`${label} hex value`}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              commit(draft);
            }
          }}
        />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Toggle                                                                     */
/* -------------------------------------------------------------------------- */

type ToggleFieldProps = {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
};

export function ToggleField({ id, label, checked, onChange }: ToggleFieldProps) {
  return (
    <div className="ctl ctl--row">
      <label className="ctl__label" htmlFor={id}>
        {label}
      </label>

      <span className="switch">
        <input
          id={id}
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="switch__track" aria-hidden="true" />
      </span>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Select                                                                     */
/* -------------------------------------------------------------------------- */

export type SelectOption<T extends string> = {
  value: T;
  label: string;
};

type SelectFieldProps<T extends string> = {
  id: string;
  label: string;
  value: T;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
};

export function SelectField<T extends string>({
  id,
  label,
  value,
  options,
  onChange,
}: SelectFieldProps<T>) {
  return (
    <div className="ctl">
      <label className="ctl__label" htmlFor={id}>
        {label}
      </label>
      <select
        className="select"
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Segmented                                                                  */
/* -------------------------------------------------------------------------- */

type SegmentedOption<T extends string> = {
  value: T;
  label: string;
  icon?: ReactNode;
};

type SegmentedFieldProps<T extends string> = {
  label: string;
  value: T;
  options: SegmentedOption<T>[];
  onChange: (value: T) => void;
  columns?: number;
};

export function SegmentedField<T extends string>({
  label,
  value,
  options,
  onChange,
  columns = options.length,
}: SegmentedFieldProps<T>) {
  return (
    <div className="ctl">
      <span className="ctl__label">{label}</span>
      <div
        className="segmented"
        style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
        role="group"
        aria-label={label}
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`segmented__option${value === option.value ? " is-active" : ""}`}
            onClick={() => onChange(option.value)}
            aria-pressed={value === option.value}
          >
            {option.icon}
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
