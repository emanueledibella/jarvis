import React, { useEffect, useState } from "react";
import {
  Bluetooth,
  Lightbulb,
  LoaderCircle,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { api, patch, post, type Json } from "./api";
import { Badge, Field, Toggle } from "./components";
import { t as tr, useI18n } from "./i18n";

type Props = { notify: (text: string, error?: boolean) => void };

function LightCard({
  device,
  notify,
  reload,
  edit,
}: Props & { device: Json; reload: () => void; edit: (id: string) => void }) {
  const [state, setState] = useState<Json>({});
  const [draft, setDraft] = useState<Json>({});
  const [busy, setBusy] = useState(false);
  const caps = device.capabilities || {};
  async function perform(changes?: Json) {
    setBusy(true);
    try {
      const path = "/lights/" + encodeURIComponent(device.id) + "/state";
      const result = changes ? await post(path, changes) : await api(path);
      setState(result.light);
      setDraft({});
      if (changes) notify("Light state verified.");
    } catch (error: any) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="settings-card">
      <div className="card-heading">
        <Lightbulb size={22} />
        <div>
          <h2>{device.name}</h2>
          <p>{device.model || tr("Configured light")}</p>
        </div>
        <Badge
          state={
            state.on === true
              ? "connected"
              : state.on === false
                ? "disabled"
                : "not_connected"
          }
        >
          {state.on === true
            ? tr("On")
            : state.on === false
              ? tr("Off")
              : tr("State not read yet")}
        </Badge>
      </div>
      <p>
        {device.connection === "hue_bluetooth"
          ? tr("Hue Bluetooth · no Bridge")
          : tr("MCP lighting service")}{" "}
        · {device.scope === "work" ? tr("Work") : tr("Personal")}
      </p>
      <div className="button-row">
        <button className="btn" disabled={busy} onClick={() => perform()}>
          <RefreshCw size={14} />
          {tr("Read light state")}
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => perform({ on: true })}
        >
          {tr("Turn on")}
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => perform({ on: false })}
        >
          {tr("Turn off")}
        </button>
      </div>
      {caps.brightness && (
        <Field
          label={tr("Brightness, percent")}
          type="number"
          value={draft.brightness ?? state.brightness ?? ""}
          onChange={(value) =>
            setDraft((v) => ({ ...v, brightness: Number(value) }))
          }
          help={tr("0 turns the light off; 1–100 sets brightness.")}
        />
      )}
      {caps.temperature_kelvin && (
        <Field
          label={tr("White temperature, kelvin")}
          type="number"
          value={draft.temperature_kelvin ?? state.temperature_kelvin ?? ""}
          onChange={(value) =>
            setDraft((v) => {
              const next: Json = { ...v, temperature_kelvin: Number(value) };
              delete next.color;
              return next;
            })
          }
          help={
            tr("Lower values are warmer; higher values are cooler.") +
            " " +
            caps.min_kelvin +
            "–" +
            caps.max_kelvin +
            " K"
          }
        />
      )}
      {caps.color && (
        <Field
          label={tr("Color, hex")}
          value={draft.color ?? state.color ?? ""}
          onChange={(value) =>
            setDraft((v) => {
              const next: Json = { ...v, color: value };
              delete next.temperature_kelvin;
              return next;
            })
          }
          help={tr(
            "Use a color such as #FF8000. Color and white temperature are separate modes.",
          )}
        />
      )}
      <button
        className="btn primary"
        disabled={busy || !Object.keys(draft).length}
        onClick={() => perform(draft)}
      >
        {busy && <LoaderCircle size={14} className="spin" />}
        {tr("Apply light settings")}
      </button>
      <Toggle
        label={tr("Allow direct voice control")}
        checked={device.voice_control}
        help={tr(
          "Allows reversible lighting commands for this light. Other actions and untrusted content keep their approval rules.",
        )}
        onChange={(enabled) =>
          patch("/lights/" + device.id + "/grant", { voice_control: enabled })
            .then(reload)
            .catch((e) => notify(e.message, true))
        }
      />
      <button
        className="text-btn"
        disabled={busy}
        onClick={() =>
          api("/lights/" + device.id, { method: "DELETE" })
            .then(reload)
            .catch((e) => notify(e.message, true))
        }
      >
        <Trash2 size={14} />
        {tr("Remove from Jarvis")}
      </button>
      <button
        className="text-btn"
        disabled={busy}
        onClick={() => edit(device.id)}
      >
        {tr("Edit model and connection")}
      </button>
    </section>
  );
}

export default function Lighting({ notify }: Props) {
  useI18n();
  const [data, setData] = useState<Json>({ devices: [] });
  const [servers, setServers] = useState<Json[]>([]);
  const [candidates, setCandidates] = useState<Json[]>([]);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [editingBluetooth, setEditingBluetooth] = useState(false);
  const [form, setForm] = useState<Json>({
    name: "",
    model: "",
    light_profile: "white_ambiance",
    connection: "hue_bluetooth",
    scope: "personal",
    voice_control: false,
    candidate_id: "",
    min_kelvin: 2200,
    max_kelvin: 6500,
  });
  const [connection, setConnection] = useState<Json>({
    server: "",
    read_tool: "",
    set_tool: "",
  });
  const [target, setTarget] = useState("{}");
  const [fields, setFields] = useState(
    '{"on":"on","brightness":"brightness","temperature_kelvin":"temperature_kelvin","color":"color"}',
  );
  const [stateFields, setStateFields] = useState(
    '{"on":"on","brightness":"brightness","temperature_kelvin":"temperature_kelvin","color":"color"}',
  );
  async function load() {
    const result = await api("/lights");
    setData(result);
  }
  useEffect(() => {
    load().catch((e) => notify(e.message, true));
    api("/integrations")
      .then(setServers)
      .catch((e) => notify(e.message, true));
  }, []);
  const change = (key: string, value: any) =>
    setForm((previous) => ({ ...previous, [key]: value }));
  const server = servers.find((item) => item.name === connection.server);
  async function discover() {
    setBusy(true);
    try {
      const result = await post("/lights/discover");
      setCandidates(result.lights);
      change("candidate_id", "");
      if (!result.lights.length)
        notify(
          "No nearby Hue lights found. Keep the lamp powered, move the Mac closer, and close the Hue app on the phone before retrying.",
        );
    } catch (error: any) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  async function add() {
    setBusy(true);
    try {
      const payload = {
        ...form,
        candidate_id:
          form.connection === "hue_bluetooth" ? form.candidate_id : null,
        mcp:
          form.connection === "mcp"
            ? {
                ...connection,
                target: JSON.parse(target),
                fields: JSON.parse(fields),
                state_fields: JSON.parse(stateFields),
              }
            : null,
      };
      if (editing)
        await api("/lights/" + editing, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      else await post("/lights", payload);
      await load();
      setForm((previous) => ({
        ...previous,
        name: "",
        model: "",
        candidate_id: "",
      }));
      setEditing(null);
      setEditingBluetooth(false);
      setTarget("{}");
      notify("Light configured. Its supported controls are ready.");
    } catch (error: any) {
      notify(
        error.message ===
          "Bluetooth pairing was not confirmed. Allow the macOS pairing request and make the lamp discoverable."
          ? "Pairing is not complete. In the Hue app on your phone, choose Make Discoverable, then retry in Jarvis."
          : error.message,
        true,
      );
    } finally {
      setBusy(false);
    }
  }
  async function edit(id: string) {
    try {
      const config = await api("/lights/" + id + "/configuration");
      const { mcp, id: ignored, ...settings } = config;
      setForm({ ...settings, candidate_id: "" });
      setEditing(id);
      setEditingBluetooth(config.connection === "hue_bluetooth");
      setCandidates([]);
      if (mcp) {
        setConnection({
          server: mcp.server,
          read_tool: mcp.read_tool,
          set_tool: mcp.set_tool,
        });
        setTarget(JSON.stringify(mcp.target, null, 2));
        setFields(JSON.stringify(mcp.fields, null, 2));
        setStateFields(JSON.stringify(mcp.state_fields, null, 2));
      }
      document
        .getElementById("lighting-configuration")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error: any) {
      notify(error.message, true);
    }
  }
  return (
    <div className="settings-grid">
      <section className="settings-card full" id="lighting-configuration">
        <div className="card-heading">
          <Lightbulb size={22} />
          <div>
            <h2>{tr("Lights and devices")}</h2>
            <p>
              {tr(
                "Choose a model, a connection method, and the lights Jarvis may control.",
              )}
            </p>
          </div>
        </div>
        {!data.enabled && (
          <p className="info-line">
            {tr(
              "Lighting is disabled. Enable it above and save Settings before connecting a device.",
            )}
          </p>
        )}
        <div className="form-grid">
          <Field
            label={tr("Connection method")}
            value={form.connection}
            onChange={(value) => change("connection", value)}
            options={[
              {
                value: "hue_bluetooth",
                label: tr("Hue Bluetooth · no Bridge"),
              },
              { value: "mcp", label: tr("MCP lighting service") },
            ]}
          />
          <Field
            label={tr("Light name for voice commands")}
            value={form.name}
            onChange={(value) => change("name", value)}
            help={tr(
              "Choose a unique name you will use when speaking to Jarvis.",
            )}
          />
          <Field
            label={tr("Model, optional")}
            value={form.model}
            onChange={(value) => change("model", value)}
            help={tr(
              "Use the model shown in the manufacturer's app or on the product label.",
            )}
          />
          <Field
            label={tr("Light capabilities")}
            value={form.light_profile}
            onChange={(value) => change("light_profile", value)}
            options={[
              { value: "white", label: tr("White · fixed white and dimming") },
              {
                value: "white_ambiance",
                label: tr("Tunable white · warm to cool"),
              },
              { value: "color_ambiance", label: tr("Color · RGB and white") },
            ]}
          />
          <Field
            label={tr("Scope")}
            value={form.scope}
            onChange={(value) => change("scope", value)}
            options={[
              { value: "personal", label: tr("Personal") },
              { value: "work", label: tr("Work") },
            ]}
          />
          {form.light_profile !== "white" && (
            <>
              <Field
                label={tr("Minimum white temperature, kelvin")}
                type="number"
                value={form.min_kelvin}
                onChange={(value) => change("min_kelvin", Number(value))}
              />
              <Field
                label={tr("Maximum white temperature, kelvin")}
                type="number"
                value={form.max_kelvin}
                onChange={(value) => change("max_kelvin", Number(value))}
              />
            </>
          )}
        </div>
        {form.connection === "hue_bluetooth" ? (
          <>
            <p className="info-line">
              {tr(
                "Uses Bluetooth on the native Mac app. Allow Bluetooth and pairing when macOS asks. The lamp stays configured in the Hue app.",
              )}
            </p>
            <details className="lighting-pairing-help" open={!editingBluetooth}>
              <summary>{tr("Pair a lamp already linked to your phone")}</summary>
              <ol>
                <li>
                  {tr(
                    "On your phone, open Hue → Settings → Voice Assistants → Amazon Alexa or Google Home → Make Discoverable.",
                  )}
                </li>
                <li>
                  {tr(
                    "Keep the lamp powered and near the Mac. After enabling discovery, leave the Hue app in the background.",
                  )}
                </li>
                <li>
                  {tr(
                    "Return to Jarvis immediately: find and select your lamp, connect, and confirm the macOS pairing request if it appears.",
                  )}
                </li>
              </ol>
              <p>
                {tr(
                  "This opens a temporary pairing window and keeps the phone's Hue configuration. Repeat Make Discoverable if the window expires.",
                )}
              </p>
            </details>
            {!data.bluetooth_available && (
              <p className="info-line">
                {tr(
                  "Open the native Jarvis app on a Mac to find Bluetooth lights. Other systems can use an MCP lighting service.",
                )}
              </p>
            )}
            <button
              className="btn"
              disabled={busy || !data.enabled || !data.bluetooth_available}
              onClick={discover}
            >
              {busy ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <Bluetooth size={14} />
              )}
              {tr("Find nearby Hue lights")}
            </button>
            {!!candidates.length && (
              <Field
                label={tr("Choose your lamp")}
                value={form.candidate_id}
                onChange={(value) => change("candidate_id", value)}
                options={[
                  { value: "", label: tr("Select the lamp you own") },
                  ...candidates.map((item) => ({
                    value: item.candidate_id,
                    label: item.name,
                  })),
                ]}
              />
            )}
          </>
        ) : (
          <>
            <p className="info-line">
              {tr(
                "Choose an existing MCP server with allowed read and write tools. The state tool must return a JSON object; the set tool receives the mapped lighting fields.",
              )}
            </p>
            <div className="form-grid">
              <Field
                label={tr("MCP server")}
                value={connection.server}
                onChange={(value) =>
                  setConnection({ server: value, read_tool: "", set_tool: "" })
                }
                options={[
                  { value: "", label: tr("Choose a server") },
                  ...servers
                    .filter((item) => item.name !== "second_brain")
                    .map((item) => ({ value: item.name, label: item.name })),
                ]}
              />
              <Field
                label={tr("Read state tool")}
                value={connection.read_tool}
                onChange={(value) =>
                  setConnection((v) => ({ ...v, read_tool: value }))
                }
                options={[
                  { value: "", label: tr("Choose an allowed tool") },
                  ...(server?.read_tools || []).map((name: string) => ({
                    value: name,
                    label: name,
                  })),
                ]}
              />
              <Field
                label={tr("Set state tool")}
                value={connection.set_tool}
                onChange={(value) =>
                  setConnection((v) => ({ ...v, set_tool: value }))
                }
                options={[
                  { value: "", label: tr("Choose an allowed tool") },
                  ...(server?.write_tools || []).map((name: string) => ({
                    value: name,
                    label: name,
                  })),
                ]}
              />
            </div>
            <Field
              label={tr("Device target arguments, JSON")}
              type="textarea"
              value={target}
              onChange={setTarget}
              help={tr(
                "Constant arguments identifying this lamp, for example an entity_id. They stay in private application data.",
              )}
            />
            <details>
              <summary>{tr("Advanced field mapping")}</summary>
              <Field
                label={tr("Command field mapping, JSON")}
                type="textarea"
                value={fields}
                onChange={setFields}
              />
              <Field
                label={tr("State field mapping, JSON")}
                type="textarea"
                value={stateFields}
                onChange={setStateFields}
                help={tr(
                  "Map on, brightness, temperature_kelvin, and color to the service fields. Read paths may use dots. Omit unsupported fields.",
                )}
              />
            </details>
          </>
        )}
        <Toggle
          label={tr("Allow direct voice control")}
          checked={form.voice_control}
          onChange={(value) => change("voice_control", value)}
          help={tr(
            "Grant Jarvis permission to switch and adjust only this registered light. You can revoke it at any time.",
          )}
        />
        <button
          className="btn primary"
          disabled={
            busy ||
            !data.enabled ||
            !form.name.trim() ||
            (form.connection === "hue_bluetooth" &&
              !form.candidate_id &&
              !editingBluetooth)
          }
          onClick={add}
        >
          {busy ? (
            <LoaderCircle size={14} className="spin" />
          ) : (
            <Plus size={14} />
          )}
          {editing
            ? tr("Save light configuration")
            : tr("Connect and save light")}
        </button>
        {editing && (
          <button
            className="text-btn"
            disabled={busy}
            onClick={() => {
              setEditing(null);
              setEditingBluetooth(false);
              setTarget("{}");
              setForm((previous) => ({
                ...previous,
                name: "",
                model: "",
                candidate_id: "",
                voice_control: false,
              }));
            }}
          >
            {tr("Cancel")}
          </button>
        )}
      </section>
      {data.devices.map((device: Json) => (
        <LightCard
          key={device.id}
          device={device}
          notify={notify}
          reload={load}
          edit={edit}
        />
      ))}
    </div>
  );
}
