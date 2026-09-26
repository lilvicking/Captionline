import { useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, Minus, RotateCcw } from "lucide-react";
import { CAPTION_FONTS } from "../../data/captionFonts";
import { CAPTION_PRESETS, resolvePreset, stylesMatch } from "../../data/captionPresets";
import {
  CAPTION_MAX_VERTICAL_POSITION,
  CAPTION_MIN_VERTICAL_POSITION,
  DEFAULT_CAPTION_STYLE,
  POSITION_PRESET_VALUES,
  positionPresetFor,
} from "../../types";
import type {
  CaptionFontId,
  CaptionPositionPreset,
  CaptionStyle,
  CaptionTextAlign,
} from "../../types";
import {
  ColorField,
  RangeField,
  SegmentedField,
  SelectField,
  ToggleField,
} from "./controls/CaptionControls";

type CaptionDesignerProps = {
  fileName: string;
  style: CaptionStyle;
  onChange: (style: CaptionStyle) => void;
  onReset: () => void;
};

const SECTIONS = [
  { id: "presets", label: "Presets" },
  { id: "text", label: "Text" },
  { id: "appearance", label: "Appearance" },
  { id: "position", label: "Position" },
  { id: "layout", label: "Layout" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

const WEIGHTS = [
  { value: "300", label: "Light" },
  { value: "400", label: "Regular" },
  { value: "500", label: "Medium" },
  { value: "600", label: "Semibold" },
  { value: "700", label: "Bold" },
  { value: "800", label: "Extrabold" },
  { value: "900", label: "Black" },
];

const ALIGN_OPTIONS: { value: CaptionTextAlign; label: string }[] = [
  { value: "left", label: "Left" },
  { value: "center", label: "Center" },
  { value: "right", label: "Right" },
];

const POSITION_OPTIONS: { value: CaptionPositionPreset; label: string; icon: JSX.Element }[] = [
  { value: "top", label: "Top", icon: <ArrowUp size={13} aria-hidden="true" /> },
  { value: "middle", label: "Middle", icon: <Minus size={13} aria-hidden="true" /> },
  { value: "bottom", label: "Bottom", icon: <ArrowDown size={13} aria-hidden="true" /> },
];

const FONT_OPTIONS = CAPTION_FONTS.map((font) => ({ value: font.id, label: font.label }));

export function CaptionDesigner({ fileName, style, onChange, onReset }: CaptionDesignerProps) {
  const [openSections, setOpenSections] = useState<SectionId[]>(["presets", "text"]);

  const update = <K extends keyof CaptionStyle>(key: K, value: CaptionStyle[K]) => {
    onChange({ ...style, [key]: value });
  };

  const toggleSection = (id: SectionId) => {
    setOpenSections((previous) =>
      previous.includes(id) ? previous.filter((item) => item !== id) : [...previous, id],
    );
  };

  const isOpen = (id: SectionId) => openSections.includes(id);

  const activePreset = CAPTION_PRESETS.find((preset) => stylesMatch(resolvePreset(preset), style));

  const isDefault = stylesMatch(style, DEFAULT_CAPTION_STYLE);

  return (
    <section className="panel">
      <div className="panel__header">
        <h2 className="panel__title">Caption designer</h2>
        <button
          className="button button--ghost button--sm"
          type="button"
          onClick={onReset}
          disabled={isDefault}
        >
          <RotateCcw size={14} aria-hidden="true" />
          Reset
        </button>
      </div>

      <p className="panel__file" title={fileName}>
        {fileName}
      </p>

      {/* ---------------- Presets ---------------- */}
      <div className="accordion">
        <button
          type="button"
          className="accordion__trigger"
          onClick={() => toggleSection("presets")}
          aria-expanded={isOpen("presets")}
        >
          Presets
          <ChevronDown
            className={`accordion__chevron${isOpen("presets") ? " is-open" : ""}`}
            size={15}
            aria-hidden="true"
          />
        </button>

        {isOpen("presets") ? (
          <div className="accordion__body">
            <div className="presets">
              {CAPTION_PRESETS.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  className={`preset${activePreset?.id === preset.id ? " is-active" : ""}`}
                  onClick={() => onChange(resolvePreset(preset))}
                  title={preset.description}
                  aria-pressed={activePreset?.id === preset.id}
                >
                  <span className="preset__label">{preset.label}</span>
                  <span className="preset__description">{preset.description}</span>
                </button>
              ))}
            </div>

            <p className="designer__status">
              {activePreset ? (
                <>
                  Based on <strong>{activePreset.label}</strong>. Adjust anything below.
                </>
              ) : (
                <>Custom style. Pick a preset to start over.</>
              )}
            </p>

            {style.wordHighlight ? (
              <p className="designer__note">
                Karaoke highlighting uses the word-level timestamps returned by the transcription
                service. The active word is whichever word spans{" "}
                <code>video.currentTime</code>, so nothing is faked. Captions without word timings
                render as plain text.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* ---------------- Text ---------------- */}
      <div className="accordion">
        <button
          type="button"
          className="accordion__trigger"
          onClick={() => toggleSection("text")}
          aria-expanded={isOpen("text")}
        >
          Text
          <ChevronDown
            className={`accordion__chevron${isOpen("text") ? " is-open" : ""}`}
            size={15}
            aria-hidden="true"
          />
        </button>

        {isOpen("text") ? (
          <div className="accordion__body">
            <SelectField
              id="caption-font"
              label="Font"
              value={style.fontFamily}
              options={FONT_OPTIONS}
              onChange={(value) => update("fontFamily", value as CaptionFontId)}
            />

            <RangeField
              id="caption-font-size"
              label="Font size"
              value={style.fontSize}
              min={16}
              max={96}
              step={1}
              format={(value) => `${value}px`}
              onChange={(value) => update("fontSize", value)}
            />

            <SelectField
              id="caption-font-weight"
              label="Weight"
              value={String(style.fontWeight)}
              options={WEIGHTS}
              onChange={(value) => update("fontWeight", Number(value))}
            />

            <ColorField
              id="caption-text-color"
              label="Text colour"
              value={style.textColor}
              onChange={(value) => update("textColor", value)}
            />

            <SegmentedField
              label="Alignment"
              value={style.textAlign}
              options={ALIGN_OPTIONS}
              onChange={(value) => update("textAlign", value)}
            />

            <ToggleField
              id="caption-uppercase"
              label="Uppercase"
              checked={style.uppercase}
              onChange={(checked) => update("uppercase", checked)}
            />

            <RangeField
              id="caption-letter-spacing"
              label="Letter spacing"
              value={style.letterSpacing}
              min={-0.05}
              max={0.3}
              step={0.005}
              format={(value) => `${value.toFixed(3)}em`}
              onChange={(value) => update("letterSpacing", value)}
            />

            <RangeField
              id="caption-word-spacing"
              label="Word spacing"
              value={style.wordSpacing}
              min={-0.1}
              max={0.5}
              step={0.01}
              format={(value) => `${value.toFixed(2)}em`}
              onChange={(value) => update("wordSpacing", value)}
            />

            <RangeField
              id="caption-line-height"
              label="Line height"
              value={style.lineHeight}
              min={0.9}
              max={2}
              step={0.05}
              format={(value) => value.toFixed(2)}
              onChange={(value) => update("lineHeight", value)}
            />
          </div>
        ) : null}
      </div>

      {/* ---------------- Appearance ---------------- */}
      <div className="accordion">
        <button
          type="button"
          className="accordion__trigger"
          onClick={() => toggleSection("appearance")}
          aria-expanded={isOpen("appearance")}
        >
          Appearance
          <ChevronDown
            className={`accordion__chevron${isOpen("appearance") ? " is-open" : ""}`}
            size={15}
            aria-hidden="true"
          />
        </button>

        {isOpen("appearance") ? (
          <div className="accordion__body">
            <ColorField
              id="caption-bg-color"
              label="Background"
              value={style.backgroundColor}
              onChange={(value) => update("backgroundColor", value)}
            />

            <RangeField
              id="caption-bg-opacity"
              label="Background opacity"
              value={style.backgroundOpacity}
              min={0}
              max={1}
              step={0.01}
              format={(value) => `${Math.round(value * 100)}%`}
              onChange={(value) => update("backgroundOpacity", value)}
            />

            <RangeField
              id="caption-bg-padding"
              label="Background padding"
              value={style.backgroundPadding}
              min={0}
              max={48}
              step={1}
              format={(value) => `${value}px`}
              onChange={(value) => update("backgroundPadding", value)}
            />

            <RangeField
              id="caption-bg-radius"
              label="Corner radius"
              value={style.backgroundRadius}
              min={0}
              max={48}
              step={1}
              format={(value) => `${value}px`}
              onChange={(value) => update("backgroundRadius", value)}
            />

            <ToggleField
              id="caption-outline"
              label="Text outline"
              checked={style.outlineEnabled}
              onChange={(checked) => update("outlineEnabled", checked)}
            />

            {style.outlineEnabled ? (
              <>
                <ColorField
                  id="caption-outline-color"
                  label="Outline colour"
                  value={style.outlineColor}
                  onChange={(value) => update("outlineColor", value)}
                />

                <RangeField
                  id="caption-outline-width"
                  label="Outline thickness"
                  value={style.outlineWidth}
                  min={0.5}
                  max={12}
                  step={0.5}
                  format={(value) => `${value}px`}
                  onChange={(value) => update("outlineWidth", value)}
                />
              </>
            ) : null}

            <ToggleField
              id="caption-shadow"
              label="Text shadow"
              checked={style.shadowEnabled}
              onChange={(checked) => update("shadowEnabled", checked)}
            />
          </div>
        ) : null}
      </div>

      {/* ---------------- Position ---------------- */}
      <div className="accordion">
        <button
          type="button"
          className="accordion__trigger"
          onClick={() => toggleSection("position")}
          aria-expanded={isOpen("position")}
        >
          Position
          <ChevronDown
            className={`accordion__chevron${isOpen("position") ? " is-open" : ""}`}
            size={15}
            aria-hidden="true"
          />
        </button>

        {isOpen("position") ? (
          <div className="accordion__body">
            <SegmentedField
              label="Quick presets"
              value={positionPresetFor(style.verticalPosition)}
              options={POSITION_OPTIONS}
              onChange={(value) => update("verticalPosition", POSITION_PRESET_VALUES[value])}
            />

            <RangeField
              id="caption-vertical"
              label="Vertical position"
              value={style.verticalPosition}
              min={CAPTION_MIN_VERTICAL_POSITION}
              max={CAPTION_MAX_VERTICAL_POSITION}
              step={0.5}
              format={(value) => `${value.toFixed(1)}%`}
              onChange={(value) => update("verticalPosition", value)}
            />

            <p className="designer__hint">
              Drag the caption on the video to place it precisely, or use the arrow keys while it
              is focused.
            </p>
          </div>
        ) : null}
      </div>

      {/* ---------------- Layout ---------------- */}
      <div className="accordion">
        <button
          type="button"
          className="accordion__trigger"
          onClick={() => toggleSection("layout")}
          aria-expanded={isOpen("layout")}
        >
          Layout
          <ChevronDown
            className={`accordion__chevron${isOpen("layout") ? " is-open" : ""}`}
            size={15}
            aria-hidden="true"
          />
        </button>

        {isOpen("layout") ? (
          <div className="accordion__body">
            <RangeField
              id="caption-max-width"
              label="Maximum width"
              value={style.maxWidthPercent}
              min={20}
              max={100}
              step={1}
              format={(value) => `${value}%`}
              onChange={(value) => update("maxWidthPercent", value)}
            />

            <RangeField
              id="caption-max-chars"
              label="Characters per line"
              value={style.maxCharsPerLine ?? 0}
              min={0}
              max={60}
              step={1}
              format={(value) => (value === 0 ? "No limit" : `${value} chars`)}
              onChange={(value) => update("maxCharsPerLine", value === 0 ? null : value)}
            />
          </div>
        ) : null}
      </div>

      <p className="panel__hint">
        Styles are stored as a single caption style object, so the same values can be handed to the
        video renderer when burned-in export is connected.
      </p>
    </section>
  );
}
