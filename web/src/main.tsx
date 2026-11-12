import { Capacitor } from "@capacitor/core";
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import RemoteBootstrap from "./Remote";
import { getInterfaceLanguage, setInterfaceLanguage } from "./localization";
import "./style.css";
import "./hud.css";

document.documentElement.dataset.platform = Capacitor.getPlatform();
setInterfaceLanguage(getInterfaceLanguage());
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RemoteBootstrap><App /></RemoteBootstrap>
  </React.StrictMode>,
);
