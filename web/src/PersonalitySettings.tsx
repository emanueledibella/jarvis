import { useId } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Toggle } from "./components";
import { formatNumber, t as tr } from "./i18n";

type PersonalityProfile = {
  enabled: boolean;
  humor: number;
  irony: number;
  professionalism: number;
  warmth: number;
  conciseness: number;
};

const sliders = [
  { key: "humor", label: "Humor", help: "From straightforward replies to playful jokes." },
  { key: "irony", label: "Irony", help: "From literal phrasing to dry wit." },
  { key: "professionalism", label: "Professionalism", help: "From casual to formal and structured." },
  { key: "warmth", label: "Warmth", help: "From matter-of-fact to friendly and expressive." },
  { key: "conciseness", label: "Conciseness", help: "From detailed explanations to the essentials." },
] as const;

export default function PersonalitySettings({
  profile,
  disabled,
  onChange,
}: {
  profile: PersonalityProfile;
  disabled: boolean;
  onChange: (profile: PersonalityProfile) => void;
}) {
  const id = useId();
  return (
    <section className="settings-card">
      <div className="card-heading">
        <SlidersHorizontal size={19} />
        <div>
          <h2>{tr("Personality")}</h2>
          <p>{tr("Choose how Jarvis expresses itself in chat and in new Live voice sessions.")}</p>
        </div>
      </div>
      <Toggle
        label={tr("Use a custom personality")}
        checked={profile.enabled}
        onChange={(enabled) => onChange({ ...profile, enabled })}
        disabled={disabled}
      />
      {sliders.map(({ key, label, help }) => (
        <label className="field personality-slider" key={key}>
          <span>
            {tr(label)}
            <span className="personality-value" aria-hidden="true">
              {formatNumber(profile[key])} / 100
            </span>
          </span>
          <input
            aria-label={tr(label)}
            aria-describedby={`${id}-${key}-help`}
            type="range"
            min={0}
            max={100}
            step={1}
            value={profile[key]}
            disabled={disabled || !profile.enabled}
            onChange={(event) =>
              onChange({ ...profile, [key]: event.currentTarget.valueAsNumber })
            }
          />
          <small id={`${id}-${key}-help`}>{tr(help)}</small>
        </label>
      ))}
    </section>
  );
}
